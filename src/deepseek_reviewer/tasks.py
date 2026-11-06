"""Explicit file selection, immutable review plans, and a single CLI invocation."""
import hashlib
import json
import os
from pathlib import Path
import re
import uuid

from . import __version__
from .config import app_home, load_runtime, private_directory, fingerprint, ENDPOINT, MODEL
from .prepare import prepare_claude_review
from .runner import AgentStopped, private_write, run_bounded
from .safety import selected_paths, read_selected, safe_text, scan_secrets, ReviewError


def digest(data):
    return hashlib.sha256(data).hexdigest()


def encode(value):
    return (json.dumps(value, ensure_ascii=False, indent=2) + '\n').encode()


def validate_limits(limits):
    expected = {'timeout', 'max_turns', 'max_budget_usd', 'max_output_tokens', 'effort'}
    if set(limits) != expected:
        raise AgentStopped('invalid_limits')
    for key, ceiling in [('timeout', 600), ('max_turns', 32), ('max_output_tokens', 64000)]:
        if type(limits[key]) is not int or not 0 < limits[key] <= ceiling:
            raise AgentStopped('invalid_limits')
    budget = limits['max_budget_usd']
    if type(budget) not in (int, float) or not 0 < budget <= 2 or limits['effort'] not in (None, 'low'):
        raise AgentStopped('invalid_limits')


def create_plan(root, names, objective, revision, constraints, evidence, limits):
    validate_limits(limits)
    runtime = load_runtime()  # Does not retrieve a credential.
    names = selected_paths(names)
    root = Path(root).absolute()
    task = {'objective': objective, 'revision': revision, 'constraints': constraints, 'test_evidence': evidence}
    if any(not isinstance(v, str) or not v.strip() for v in task.values()):
        raise AgentStopped('task_required')
    scan_secrets(task)
    materials = {name: read_selected(root, name) for name in names}
    if sum(map(len, materials.values())) > 256 * 1024:
        raise AgentStopped('snapshot_total_limit')
    for body in materials.values():
        safe_text(body)
    if len(encode(task)) + len(encode(list(names))) > 6000:
        raise AgentStopped('task_too_large')
    runs = private_directory(private_directory(app_home()) / 'reviews')
    run = runs / uuid.uuid4().hex
    run.mkdir(mode=0o700)
    snapshot = run / 'snapshot'
    snapshot.mkdir(mode=0o700)
    hashes = {}
    for name, body in materials.items():
        p = snapshot / name
        p.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        private_write(p, body)
        p.chmod(0o400)
        hashes[name] = digest(body)
    for p in sorted(snapshot.rglob('*'), reverse=True):
        if p.is_dir(): p.chmod(0o500)
    snapshot.chmod(0o500)
    plan = {'schema': 1, 'product_version': __version__, 'id': run.name,
            'endpoint': ENDPOINT, 'model': MODEL, 'files': hashes,
            'bytes': sum(map(len, materials.values())), 'task': task, 'limits': limits,
            'runtime_sha256': digest(encode(runtime))}
    raw = encode(plan)
    private_write(run / 'plan.json', raw)
    return {'plan': str(run / 'plan.json'), 'sha256': digest(raw), **plan,
            'next': 'Review the file list and task. Authorize sending this snapshot to DeepSeek before review.'}


def load_plan(path, expected_sha256):
    p = Path(path).absolute()
    runs = app_home() / 'reviews'
    if (p.name != 'plan.json' or p.parent.parent != runs or not re.fullmatch('[a-f0-9]{32}', p.parent.name)
            or p.resolve() != p or p.stat().st_mode & 0o077 or p.stat().st_size > 32768):
        raise AgentStopped('unsafe_plan_path')
    raw = p.read_bytes()
    if digest(raw) != expected_sha256:
        raise AgentStopped('plan_changed')
    plan = json.loads(raw)
    if (plan['schema'] != 1 or plan['product_version'] != __version__ or plan['id'] != p.parent.name
            or plan['endpoint'] != ENDPOINT or plan['model'] != MODEL):
        raise AgentStopped('unsupported_plan')
    validate_limits(plan['limits'])
    return p.parent, plan


def summarize(result, files, unchanged):
    """Never persist raw tool contents, thinking, environment, or stderr."""
    observed = result.get('claude', {})
    final = None
    # Invalid/truncated capture never yields an accepted report.
    if observed.get('capture_complete'):
        for line in result['stdout'].splitlines():
            event = json.loads(line)
            if event.get('type') == 'result' and isinstance(event.get('result'), str):
                final = event['result']
    withheld = False
    if final:
        try: scan_secrets(final)
        except ReviewError:
            final, withheld = None, True
    tools_ok = (observed.get('unexpected_init_tools') is False
                and observed.get('tools_requested', {}).get('other') == 0)
    model_ok = bool(observed.get('models_observed')) and 'unrecognized' not in observed['models_observed']
    completed = (result['exit_code'] == 0 and result['failure'] is None
                 and observed.get('execution') == 'completed' and final
                 and tools_ok and model_ok and unchanged)
    status = 'COMPLETED' if completed else 'PARTIAL' if final else 'FAILED'
    stderr = result['stderr']
    return {'status': status, 'started': result['started'], 'exit_code': result['exit_code'],
            'failure': result['failure'], 'duration_seconds': result['duration_seconds'],
            'tool_boundary_observed': tools_ok, 'model_verified': model_ok,
            'snapshot_unchanged': unchanged, 'credential_like_report_withheld': withheld,
            'stderr_bytes': len(stderr), 'stderr_sha256': digest(stderr),
            'observation': observed, 'approved_files': sorted(files),
            'findings': final, 'quality': 'requires_primary_agent_verification',
            'coverage': 'read tool success does not certify complete review',
            'billing': 'client estimate only; HTTP request count and provider bill are unknown'}


def execute_plan(path, expected_sha256, progress=None):
    run, plan = load_plan(path, expected_sha256)
    if (run / 'execution').exists():
        raise AgentStopped('attempt_consumed')
    runtime = load_runtime()
    if digest(encode(runtime)) != plan['runtime_sha256']:
        raise AgentStopped('runtime_changed_since_approval')
    snapshot = run / 'snapshot'
    kwargs = prepare_claude_review(snapshot, run / 'execution',
        approved_files=plan['files'], required_files=list(plan['files']),
        runtime=runtime, **plan['task'], **plan['limits'])
    result = run_bounded(**kwargs, on_progress=progress)
    try:
        unchanged = (set(p.relative_to(snapshot).as_posix() for p in snapshot.rglob('*') if p.is_file()) == set(plan['files'])
                     and all(digest(read_selected(snapshot, n)) == h for n, h in plan['files'].items())
                     and not any(p.is_symlink() for p in snapshot.rglob('*')))
    except (OSError, ReviewError):
        unchanged = False
    report = summarize(result, plan['files'], unchanged)
    private_write(run / 'report.json', report)
    # Original bytes remain memory-only. They are never written to a logfile.
    return {'report_path': str(run / 'report.json'), **report}
