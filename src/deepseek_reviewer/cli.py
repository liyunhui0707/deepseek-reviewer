"""The public CLI; preparation is offline, review requires explicit approval."""
import argparse
import json
from pathlib import Path
import platform
import re
import sys

from . import __version__
from . import config, consent, distribution, tasks
from .runner import AgentStopped
from .safety import ReviewError


HINTS = {
    'consent_requires_terminal': 'Enroll project consent in your own interactive Terminal after reviewing scope and limits. Do not auto-confirm it from an agent.',
    'consent_cancelled': 'No agreement saved. Nothing was sent and no credential was read.',
    'consent_missing': 'No project agreement exists. Obtain task-specific disclosure/cost authorization, or enroll one in your own Terminal.',
    'consent_revoked': 'Project consent was revoked. Do not retry or silently switch to another approval path.',
    'consent_changed': 'The agreement changed after preparation. Inspect it and prepare a new plan; do not reuse this one.',
    'consent_scope_exceeded': 'Selected paths, file count or bytes exceed project consent. Narrow the task or obtain separate explicit authorization for a new plan.',
    'consent_limits_exceeded': 'Profile or resources exceed project consent. Keep the agreed limits or obtain separate explicit authorization.',
    'consent_invalid': 'The agreement is incompatible, malformed or belongs to a replaced directory. Inspect it; do not bypass the check.',
    'consent_scope': 'Select exact relative files or subdirectories, without wildcards, protected paths or traversal. Whole-project grants are not supported.',
    'consent_root': 'Use a specific canonical project directory, not your home directory or one of its ancestors.',
    'consent_plan_required': 'Prepare with --use-consent first; ordinary plans require explicit task-specific upload approval.',
    'review_checkpoint_missing': 'Historical experimental no-opinion stop. It did not deliver a report; do not relaunch automatically.',
    'invalid_review_report': 'The client ended, but did not deliver a valid assessment, findings and coverage report. Execution success is not review success.',
    'unsupported_plan': 'Prepare a new plan and confirm its exact scope and delivery policy. Older plans are not silently reinterpreted; saved reports remain readable.',
    'runtime_missing_or_unsafe_run_configure': 'Run deepseek-reviewer setup. If a registration exists, inspect it; do not delete it to bypass checks.',
    'claude_not_found': 'Install Claude Code from its official publisher, then run setup --claude /absolute/path/to/the/compatible/binary.',
    'unsupported_claude_version': 'Use the documented compatible Claude version. This tool never silently upgrades or downgrades Claude.',
    'registered_claude_changed': 'Stop reviews. Run configure --claude PATH --check; approve the verified replacement before configure --replace.',
    'already_configured_use_a_reviewed_migration': 'Run configure --claude PATH --check, then --replace --expected-runtime-sha256 HASH if you approve the change.',
    'runtime_confirmation_changed': 'Registration changed or confirmation is missing. Run configure --claude PATH --check again; inspect the new difference.',
    'runtime_confirmation_required': 'Replacement/restore requires --expected-runtime-sha256 from configure --check.',
    'managed_policy_present_requires_review': 'Managed Claude policy is present. Ask your administrator to review compatibility; do not bypass it.',
    'state_busy': 'A review or maintenance operation is active. Wait for it to finish; do not remove the lock file or restart a consumed review.',
    'skill_already_exists_no_overwrite': 'Run install-skill --check. Use --update only for an unchanged product-managed Skill.',
    'skill_modified_or_unmanaged': 'Your Skill is customized or unrecognized. Keep it intact and compare manually; automatic replacement is refused.',
    'skill_update_incomplete': 'An update stopped. For a previously managed Skill, use install-skill --restore. Preserve any files from an incomplete first installation for inspection.',
    'skill_bundle_missing_use_release': 'Use the built release archive; the source checkout does not contain the packaged Skill resources.',
    'credentials_require_your_interactive_terminal': 'Run credentials save/replace/remove in your own interactive Terminal. Never paste a key into Codex.',
    'unexpected_default_keychain': 'The default Keychain differs from the registered login Keychain. Inspect it yourself; no key was read.',
    'attempt_consumed': 'Read the existing report with report --id ID. A new paid attempt requires fresh authorization; never reset this attempt.',
    'plan_changed': 'The approved plan changed. Inspect it and prepare a new plan; do not substitute another hash without approval.',
    'runtime_changed_since_approval': 'The runtime changed after preparation. Prepare and authorize a new plan after compatibility checks.',
    'sensitive_content': 'Possible credential content was detected. Inspect the selected materials locally; do not paste the matched value into chat.',
    'snapshot_total_limit': 'Reduce the review to one focused task and its necessary context; prepare a smaller snapshot.',
    'timeout': 'The deadline expired and the child process was stopped. Read the saved report; no automatic retry occurred.',
    'cancelled': 'The review was cancelled and its child process was stopped. The attempt remains consumed.',
    'terminated': 'The review received a termination request. Its child process was stopped; the attempt remains consumed.',
    'error_max_turns': 'The agent turn limit was reached. Inspect coverage and narrow the next task before requesting another paid review.',
    'error_max_budget_usd': 'The client budget threshold was reached. This is not the provider invoice; do not automatically retry or raise the budget.',
    'process_nonzero': 'The child exited unsuccessfully. Any available review is partial; do not treat it as completed.',
    'cleanup_failed': 'Process cleanup could not be confirmed. Inspect the cleanup status; do not relaunch or report completion.',
    'focus_files': 'Choose at most three --focus-file paths, each already included by --file.',
    'no_previous_installation': 'No previous product installation is recorded. Install a separately verified release instead.',
    'release_checksum_mismatch': 'The downloaded or installed archive does not match its checksum. Do not execute it.',
    'existing_unmanaged_command': 'An existing command is not the recorded product launcher. Preserve it and inspect the conflict; automatic overwrite is refused.',
}


def diagnostic(code):
    # Fixed codes only: never echo arbitrary exception bodies, headers or paths.
    if not re.fullmatch('[A-Za-z_][A-Za-z0-9_]{0,95}', code): code = 'unexpected_error'
    return {'status': 'STOPPED', 'error': code,
            'next': HINTS.get(code, 'Stop and inspect the saved report and documented prerequisites. Do not retry a paid review automatically.')}


def terminal_text(value):
    text = str(value)
    text = re.sub(r'\x1b(?:\][^\x07]*(?:\x07|\x1b\\)|\[[0-?]*[ -/]*[@-~])', '', text)
    return ''.join(c for c in text if c in '\n\t' or ord(c) >= 32 and ord(c) != 127)


def render(value):
    lines = [str(value.get('status', 'OK'))]
    if 'error' in value: lines.append('Reason: ' + value['error'])
    if 'findings' in value:
        if value.get('delivery') == 'NONE':
            lines.append('Review delivery failed: file reads and execution progress are not review opinions.')
        reason = value.get('stop_reason')
        if reason:
            lines.extend(['Reason: ' + reason, HINTS.get(reason, 'Inspect the report before deciding on another review.')])
        diagnostic = value.get('final_report_diagnostic', {})
        if diagnostic.get('status') == 'rejected':
            lines.append('Final report validation: ' + diagnostic['stage'] + '/' + diagnostic['reason']
                         + ' (' + diagnostic['envelope'] + ')')
        observation = value.get('observation', {})
        def known(item): return 'unknown' if item is None else str(item)
        lines.append('Model: ' + (', '.join(observation.get('models_observed', [])) or 'unverified'))
        lines.append('Elapsed: ' + known(value.get('duration_seconds')) + 's; client estimate: ' + known(observation.get('client_estimated_usd')) + ' USD')
        lines.append('Observed responses: ' + known(observation.get('model_responses_observed')) + '; HTTP requests and provider bill: unknown')
        usage = observation.get('usage', {})
        lines.append('Reported tokens: input=' + known(usage.get('input_tokens')) + ', output=' + known(usage.get('output_tokens'))
                     + '; source: ' + observation.get('usage_source', 'unknown'))
        lines.append('Expected tools observed: ' + known(value.get('tool_boundary_observed')) + '; snapshot unchanged: ' + known(value.get('snapshot_unchanged')))
        if value.get('cleanup'): lines.append('Process cleanup confirmed: ' + known(value['cleanup'].get('completed')))
        coverage = value.get('coverage_observation', {})
        lines.append('Successful Read observed: ' + ', '.join(coverage.get('successful_read_files', [])))
        lines.append('No successful Read observed: ' + ', '.join(coverage.get('no_successful_read_observed', [])))
        lines.append('Reading is not complete coverage. Findings require your primary agent to verify.')
        lines.extend(['', value.get('findings') or 'No accepted final Findings were captured.'])
        partial = value.get('partial_review')
        if partial is not None:
            lines.append('\nPartial review available (provisional; final report supersedes it):')
            if value.get('partial_review_stale'):
                lines.append('WARNING: later output was not validated; this is an earlier artifact, not an accepted final conclusion.')
            if partial.get('assessment'): lines.append(partial['assessment'])
            for finding in partial['findings']:
                lines.extend([f"{finding['severity']} [{finding['kind']}] {finding['file']}:{finding['line']}",
                              finding['evidence'], finding['explanation'], 'Suggestion: ' + finding['suggestion']])
            if not partial['findings']: lines.append('No supported findings at this checkpoint; not an approval.')
            lines.extend('Coverage gap: ' + gap for gap in partial['coverage_gaps'])
        if value.get('partial_review_withheld'):
            lines.append('Checkpoint withheld because capture or execution evidence was unsafe/inconsistent.')
    else:
        for key in ('product_version', 'claude_version', 'provider', 'model', 'credentials', 'live_compatibility_on_this_mac', 'skill', 'current', 'proposed', 'current_sha256'):
            if key in value: lines.append(key + ': ' + json.dumps(value[key], ensure_ascii=False))
    if 'plan' in value:
        lines.extend(['Task: ' + value['task']['objective'],
                      'Files (' + str(len(value['files'])) + ', ' + str(value['bytes']) + ' bytes): ' + ', '.join(value['files']),
                      'Limits: ' + json.dumps(value['limits']),
                      'Endpoint: ' + value['endpoint'], 'Plan: ' + value['plan'], 'Plan SHA-256: ' + value['sha256'],
                      ('Project agreement matched. An explicit user request is still required; announce scope, then execute once without duplicate conversation approval.'
                       if value.get('consent') else 'Preparation is offline. Source disclosure and a paid call still require authorization.')])
        if 'delivery' in value:
            lines.extend(['Profile: ' + value['profile'] + '; priority files: ' + ', '.join(value['focus_files']),
                          value['delivery']['scope_advisory'],
                          'Thinking requested: ' + value['delivery'].get('thinking_requested', 'legacy default'),
                          'No early termination based on missing checkpoints; original execution limits apply.',
                          'Early checkpoints requested; forced finalization before limits is not supported.'])
    if 'policy' in value:
        lines.extend(['Project agreement: ' + json.dumps(value['policy'], ensure_ascii=False, indent=2),
                      'Agreement SHA-256: ' + value['sha256']])
    for key in ('command', 'installed', 'report_path', 'note', 'next'):
        if value.get(key): lines.append(key + ': ' + str(value[key]))
    return terminal_text('\n'.join(lines))


def emit(value, stream=None, *, format='json'):
    stream = sys.stdout if stream is None else stream
    print(render(value) if format == 'text' else json.dumps(value, ensure_ascii=False, indent=2), file=stream, flush=True)


def doctor():
    runtime = config.load_runtime()
    try: skill = distribution.skill_status()
    except AgentStopped as exc: skill = {'status': 'NEEDS_ATTENTION', 'error': str(exc)}
    return {'status': 'LOCAL_READY', 'platform': platform.system(), 'product_version': __version__,
            'claude_version': runtime['version'], 'registered_binary_unchanged': True,
            'provider': config.ENDPOINT, 'model': config.MODEL, 'skill': skill,
            'credentials': 'NOT CHECKED', 'live_compatibility_on_this_mac': 'NOT TESTED',
            'next': 'Local registration is valid. Check Skill status; enroll credentials yourself if needed. No model or authentication test was performed.'}


def setup(claude):
    target = config.app_home() / 'runtime.json'
    if target.exists() or target.is_symlink():
        runtime = config.load_runtime()
        if claude and str(Path(claude).expanduser().resolve()) != runtime['claude']:
            raise AgentStopped('already_configured_use_a_reviewed_migration')
    else:
        config.register(claude or config.discover_claude())
    skill = distribution.skill_status()
    if skill['status'] == 'NOT_INSTALLED' and not skill.get('conflicting_skills'):
        distribution.install_skill()
        skill = distribution.skill_status()
    ready = skill['status'] == 'CURRENT' and not skill.get('conflicting_skills')
    return {**doctor(), 'status': 'LOCAL_READY' if ready else 'ACTION_REQUIRED',
            'skill': skill, 'next': ('In your own Terminal, enroll your key once with credentials save if needed. Start a new Codex session, then say: Use DeepSeek to review these changes.'
                if ready else 'Run install-skill --check. Resolve any legacy Skill conflict before use; customized Skills are never overwritten.')}


def progress_notice(value, format):
    if format == 'json':
        print(json.dumps(value), file=sys.stderr, flush=True)
        return
    phase = {'started': 'Process started; authentication state unknown', 'initialized': 'Reviewer initialized',
             'model_response': 'Model response received', 'tool_call': 'Using file tool',
             'tool_result': 'Tool result received', 'result_received': 'Final result received', 'finished': 'Process finished'}.get(value['phase'], value['phase'])
    if value.get('notification') == 'heartbeat': phase += '; no new event (cause unknown)'
    detail = ' '.join(str(value[k]) for k in ('tool', 'file') if value.get(k))
    if value.get('checkpoints_observed'): detail += f" | public checkpoints: {value['checkpoints_observed']}"
    print(terminal_text(f"{value['elapsed_seconds']:.0f}s | {phase} {detail} | {value['remaining_seconds']:.0f}s remaining"), file=sys.stderr, flush=True)


def parser():
    p = argparse.ArgumentParser(prog='deepseek-reviewer', description='Independent, read-only DeepSeek reviews through Claude Code on macOS.')
    p.add_argument('--version', action='version', version=__version__)
    formats = p.add_mutually_exclusive_group()
    formats.add_argument('--json', dest='output_format', action='store_const', const='json')
    formats.add_argument('--text', dest='output_format', action='store_const', const='text')
    sub = p.add_subparsers(dest='command', required=True)
    sub.add_parser('doctor', help='Check local registration; no model or Keychain lookup')
    c = sub.add_parser('setup', help='Find/register compatible Claude and install the Skill; no credentials or model')
    c.add_argument('--claude')
    c = sub.add_parser('configure', help='Register an existing compatible Claude executable')
    c.add_argument('--claude')
    mode = c.add_mutually_exclusive_group()
    mode.add_argument('--check', action='store_true', help='Preview registration and current confirmation hash without changing it')
    mode.add_argument('--replace', action='store_true')
    mode.add_argument('--restore', action='store_true')
    c.add_argument('--expected-runtime-sha256')
    c = sub.add_parser('credentials', help='Interactive Terminal only; native Keychain save/replace/remove')
    c.add_argument('action', choices=['save', 'replace', 'remove'])
    c = sub.add_parser('consent', help='Optional project disclosure agreement; enable requires your interactive Terminal, no credentials/models')
    c.add_argument('action', choices=['enable', 'status', 'revoke'])
    c.add_argument('--root', type=Path, required=True)
    c.add_argument('--file', action='append', default=[], dest='files')
    c.add_argument('--directory', action='append', default=[], dest='directories')
    c.add_argument('--profile', choices=tuple(tasks.PROFILES), default='quick')
    c = sub.add_parser('prepare', help='Copy only explicitly selected files into a private review snapshot')
    c.add_argument('--root', type=Path, required=True)
    c.add_argument('--file', action='append', required=True, dest='names')
    c.add_argument('--question', required=True)
    c.add_argument('--revision', default='explicitly selected working files')
    c.add_argument('--constraints', default='Static review only. Do not change files or run tests.')
    c.add_argument('--test-evidence', default='No local test evidence supplied; do not infer tests passed.')
    c.add_argument('--profile', choices=tuple(tasks.PROFILES),
                   help='quick: 180s/8 turns/4000 output/$0.25; standard (unchanged defaults): 300s/12/16000/$0.50. Not completion guarantees.')
    c.add_argument('--use-consent', action='store_true', help='Require the enrolled project agreement; no automatic fallback or enrollment')
    c.add_argument('--focus-file', action='append', default=[], dest='focus_files',
                   help='Prioritize up to three paths already selected by --file; other selected files remain available')
    c.add_argument('--timeout', type=int)
    c.add_argument('--max-turns', type=int)
    c.add_argument('--max-budget-usd', type=float)
    c.add_argument('--max-output-tokens', type=int)
    c.add_argument('--effort', choices=['low', 'default'])
    c = sub.add_parser('review', help='Send one approved snapshot to DeepSeek; one Claude process, no relaunch')
    c.add_argument('--plan', type=Path, required=True)
    c.add_argument('--plan-sha256', required=True)
    mode = c.add_mutually_exclusive_group(required=True)
    mode.add_argument('--approve-upload', action='store_true', help='Use explicit task-specific disclosure/cost approval')
    mode.add_argument('--use-consent', action='store_true', help='Recheck the project agreement bound to this plan')
    c = sub.add_parser('report', help='Read a saved report; never resume or launch a model')
    c.add_argument('--id', required=True)
    sub.add_parser('install', help='Install this verified release into ~/.local; no PATH edits')
    c = sub.add_parser('install-skill', help='Install, inspect or explicitly update the managed Codex Skill')
    mode = c.add_mutually_exclusive_group()
    mode.add_argument('--check', action='store_true')
    mode.add_argument('--update', action='store_true')
    mode.add_argument('--restore', action='store_true')
    sub.add_parser('check-update', help='Read official GitHub release metadata (network)')
    sub.add_parser('update', help='Download, verify and activate the latest official release (network)')
    sub.add_parser('rollback', help='Activate the previous local version; no network')
    for command in sub.choices.values():
        formats = command.add_mutually_exclusive_group()
        formats.add_argument('--json', dest='output_format', action='store_const', const='json', default=argparse.SUPPRESS)
        formats.add_argument('--text', dest='output_format', action='store_const', const='text', default=argparse.SUPPRESS)
    return p


def main(argv=None):
    args = parser().parse_args(argv)
    format = args.output_format or ('text' if sys.stdout.isatty() else 'json')
    def output(value): emit(value, format=format)
    try:
        if args.command == 'doctor':
            output(doctor())
        elif args.command == 'setup':
            result = setup(args.claude)
            output(result)
            return 0 if result['status'] == 'LOCAL_READY' else 1
        elif args.command == 'configure':
            if (args.replace or args.restore) and not args.expected_runtime_sha256:
                raise AgentStopped('runtime_confirmation_required')
            if args.restore:
                runtime = config.restore_runtime(args.expected_runtime_sha256)
            else:
                claude = args.claude or config.discover_claude()
                if args.check:
                    output(config.preview_registration(claude)); return 0
                runtime = config.register(claude, replace=args.replace, expected_sha256=args.expected_runtime_sha256)
            output({'status': 'configured', 'claude_version': runtime['version'], 'sha256': runtime['sha256'],
                  'next': 'No credentials changed. Run doctor; enroll your key with credentials save in your own Terminal only if needed.'})
        elif args.command == 'credentials':
            return config.credentials(args.action)
        elif args.command == 'consent':
            if args.action == 'enable':
                output(consent.enable(args.root, files=args.files, directories=args.directories, profile=args.profile))
            else:
                if args.files or args.directories: raise AgentStopped('consent_scope')
                output(consent.status(args.root) if args.action == 'status' else consent.revoke(args.root))
        elif args.command == 'prepare':
            overrides = {k: getattr(args, k) for k in ('timeout', 'max_turns', 'max_budget_usd', 'max_output_tokens')
                         if getattr(args, k) is not None}
            if args.effort is not None: overrides['effort'] = None if args.effort == 'default' else args.effort
            profile = args.profile or (consent.require(args.root)['policy']['profile'] if args.use_consent else 'standard')
            limits = tasks.resolve_limits(profile, overrides)
            output(tasks.create_plan(args.root, args.names, args.question, args.revision,
                                   args.constraints, args.test_evidence, limits,
                                   focus_files=args.focus_files, profile=profile, use_consent=args.use_consent))
        elif args.command == 'review':
            print('STARTING — Keychain may require Allow in macOS. Do not use Always Allow.', file=sys.stderr, flush=True)
            report = tasks.execute_plan(args.plan, args.plan_sha256,
                       progress=lambda value: progress_notice(value, format), use_consent=args.use_consent)
            output(report)
            return 0 if report['status'] == 'COMPLETED' else 1
        elif args.command == 'report': output(tasks.read_report(args.id))
        elif args.command == 'install': output(distribution.install_self())
        elif args.command == 'install-skill':
            output(distribution.skill_status() if args.check else distribution.restore_skill() if args.restore else distribution.install_skill(update=args.update))
        elif args.command == 'check-update': output(distribution.latest())
        elif args.command == 'update': output(distribution.update())
        elif args.command == 'rollback': output(distribution.rollback())
        return 0
    except KeyboardInterrupt:
        emit(diagnostic('cancelled'), sys.stderr, format=format)
    except (AgentStopped, ReviewError) as exc:
        emit(diagnostic(str(exc)), sys.stderr, format=format)
    except Exception as exc:
        # Never echo arbitrary OS errors, HTTP bodies, credentials or raw paths.
        emit(diagnostic(type(exc).__name__), sys.stderr, format=format)
    return 1
