"""Explicit file selection, immutable review plans, and a single CLI invocation."""
import hashlib
import json
import os
from pathlib import Path
import re
import uuid

from . import __version__
from .config import app_home, load_runtime, private_directory, private_read, state_lock, ENDPOINT, MODEL
from .prepare import build_review_task, prepare_claude_review
from .runner import AgentStopped, private_write, run_bounded
from .safety import selected_paths, read_selected, safe_text, scan_secrets, validate_checkpoint, ReviewError


# Presets are planning defaults, not promises of completion or API billing caps.
# Keep the previously published defaults when no profile is selected.
PROFILES = {
    'quick': dict(timeout=180, max_turns=8, max_budget_usd=.25, max_output_tokens=4000, effort='low'),
    'standard': dict(timeout=300, max_turns=12, max_budget_usd=.50, max_output_tokens=16000, effort='low'),
}


def resolve_limits(profile, overrides):
    if profile not in PROFILES or not set(overrides) <= PROFILES['standard'].keys():
        raise AgentStopped('invalid_limits')
    limits = {**PROFILES[profile], **overrides}
    validate_limits(limits)
    return limits


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


def create_plan(root, names, objective, revision, constraints, evidence, limits, *, focus_files=(), profile='standard'):
    validate_limits(limits)
    runtime = load_runtime()  # Does not retrieve a credential.
    names = selected_paths(names)
    if (profile not in PROFILES or not isinstance(focus_files, (list, tuple)) or len(focus_files) > 3
            or any(not isinstance(n, str) or n not in names for n in focus_files)
            or len(set(focus_files)) != len(focus_files)):
        raise AgentStopped('focus_files')
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
    build_review_task(approved_files=names, required_files=focus_files, **task, **limits)
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
            'runtime_sha256': digest(encode(runtime)), 'profile': profile, 'focus_files': list(focus_files),
            'delivery': {'forced_finalization_supported': False,
                         'partial_review': 'Latest validated explicit checkpoint; not a final report.',
                         'scope_advisory': ('Narrow to one risk or split before approval; scope exceeds profile guidance.'
                             if len(names) > (6 if profile == 'quick' else 12)
                             or sum(map(len, materials.values())) > (48 if profile == 'quick' else 96) * 1024
                             else 'Focused scope; completion still not guaranteed.')}}
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
            if (event.get('type') == 'result' and event.get('subtype') == 'success'
                    and event.get('is_error') is False and isinstance(event.get('result'), str)):
                final = event['result'].strip() or None
    withheld = False
    if final:
        try: scan_secrets(final)
        except ReviewError:
            final, withheld = None, True
    tools_ok = (observed.get('unexpected_init_tools') is False
                and observed.get('tools_requested', {}).get('other') == 0)
    model_ok = bool(observed.get('models_observed')) and 'unrecognized' not in observed['models_observed']
    cleanup_ok = result.get('cleanup', {}).get('completed', True)
    partial = None
    partial_withheld = result.get('checkpoint') is not None or bool(observed.get('checkpoints_rejected'))
    # A validated prefix can survive an ordinary execution limit, but never a
    # corrupted/oversized stream, unexpected tools, model or changed snapshot.
    if (result['failure'] in (None, 'claude_result_error', 'timeout', 'missing_result', 'cancelled', 'terminated')
            and tools_ok and model_ok and unchanged and cleanup_ok and result.get('checkpoint') is not None):
        try:
            partial = validate_checkpoint(result['checkpoint'], files)
            partial_withheld = False
        except (ReviewError, ValueError, TypeError, UnicodeError, RecursionError):
            partial_withheld = True
    completed = (result['exit_code'] == 0 and result['failure'] is None
                 and observed.get('execution') == 'completed' and final
                 and tools_ok and model_ok and unchanged and cleanup_ok)
    status = 'COMPLETED' if completed else 'PARTIAL' if final or partial else 'FAILED'
    reason = ((observed.get('result_subtype') if result['failure'] == 'claude_result_error' else result['failure'])
              or (observed.get('result_subtype') if observed.get('result_subtype') != 'success' else None)
              or ('unexpected_tools' if not tools_ok else None)
              or ('model_unverified' if not model_ok else None)
              or ('snapshot_changed' if not unchanged else None)
              or ('report_withheld' if withheld else None)
              or ('process_nonzero' if result['exit_code'] not in (None, 0) else None)
              or ('missing_report' if not final else None))
    read_files = sorted(set(observed.get('read_results', ())) & set(files))
    stderr = result['stderr']
    return {'status': status, 'started': result['started'], 'exit_code': result['exit_code'],
            'failure': result['failure'], 'duration_seconds': result['duration_seconds'],
            'cleanup': result.get('cleanup'),
            'stop_reason': reason,
            'tool_boundary_observed': tools_ok, 'model_verified': model_ok,
            'snapshot_unchanged': unchanged, 'credential_like_report_withheld': withheld,
            'stderr_bytes': len(stderr), 'stderr_sha256': digest(stderr),
            'observation': observed, 'approved_files': sorted(files),
            'findings': final, 'partial_review': partial,
            'partial_review_withheld': partial_withheld,
            'partial_review_note': 'Provisional model claims, may be superseded; not a final report or review approval.',
            'quality': 'requires_primary_agent_verification',
            'coverage': 'read tool success does not certify complete review',
            'coverage_observation': {'successful_read_files': read_files,
                'no_successful_read_observed': sorted(set(files) - set(read_files)),
                'complete_review_verified': False},
            'billing': 'client estimate only; HTTP request count and provider bill are unknown'}


def execute_plan(path, expected_sha256, progress=None):
    with state_lock(shared=True):
        return _execute_plan(path, expected_sha256, progress)


def _execute_plan(path, expected_sha256, progress):
    run, plan = load_plan(path, expected_sha256)
    if (run / 'execution').exists():
        raise AgentStopped('attempt_consumed')
    runtime = load_runtime()
    if digest(encode(runtime)) != plan['runtime_sha256']:
        raise AgentStopped('runtime_changed_since_approval')
    snapshot = run / 'snapshot'
    kwargs = prepare_claude_review(snapshot, run / 'execution',
        approved_files=plan['files'], required_files=plan.get('focus_files', []),
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


def read_report(attempt_id):
    """Read an existing sanitized report, never resume or launch an attempt."""
    if not re.fullmatch('[a-f0-9]{32}', attempt_id):
        raise AgentStopped('invalid_attempt_id')
    root = app_home() / 'reviews' / attempt_id
    if root.resolve() != root or not root.is_dir(): raise AgentStopped('report_not_found')
    path = root / 'report.json'
    if not path.exists():
        if (root / 'execution').exists():
            return {'status': 'NO_FINAL_REPORT', 'attempt_id': attempt_id,
                    'next': 'The attempt may still be running or was interrupted. Do not relaunch it; inspect the original invocation.'}
        raise AgentStopped('report_not_found')
    value = json.loads(private_read(path, limit=8 * 1024 * 1024))
    scan_secrets(value)
    return {'report_path': str(path), **value}
