"""The public CLI; preparation is offline, review requires explicit approval."""
import argparse
import json
from pathlib import Path
import platform
import sys

from . import __version__
from . import config, distribution, tasks
from .runner import AgentStopped
from .safety import ReviewError


def emit(value, stream=sys.stdout):
    print(json.dumps(value, ensure_ascii=False, indent=2), file=stream, flush=True)


def parser():
    p = argparse.ArgumentParser(prog='deepseek-reviewer', description='Independent, read-only DeepSeek reviews through Claude Code on macOS.')
    p.add_argument('--version', action='version', version=__version__)
    sub = p.add_subparsers(dest='command', required=True)
    sub.add_parser('doctor', help='Check local registration; no model or Keychain lookup')
    c = sub.add_parser('configure', help='Register an existing compatible Claude executable')
    c.add_argument('--claude', required=True)
    c = sub.add_parser('credentials', help='Interactive Terminal only; native Keychain save/replace/remove')
    c.add_argument('action', choices=['save', 'replace', 'remove'])
    c = sub.add_parser('prepare', help='Copy only explicitly selected files into a private review snapshot')
    c.add_argument('--root', type=Path, required=True)
    c.add_argument('--file', action='append', required=True, dest='names')
    c.add_argument('--question', required=True)
    c.add_argument('--revision', default='explicitly selected working files')
    c.add_argument('--constraints', default='Static review only. Do not change files or run tests.')
    c.add_argument('--test-evidence', default='No local test evidence supplied; do not infer tests passed.')
    c.add_argument('--timeout', type=int, default=300)
    c.add_argument('--max-turns', type=int, default=12)
    c.add_argument('--max-budget-usd', type=float, default=0.50)
    c.add_argument('--max-output-tokens', type=int, default=16000)
    c.add_argument('--effort', choices=['low', 'default'], default='low')
    c = sub.add_parser('review', help='Send one approved snapshot to DeepSeek; one Claude process, no relaunch')
    c.add_argument('--plan', type=Path, required=True)
    c.add_argument('--plan-sha256', required=True)
    c.add_argument('--approve-upload', action='store_true', required=True)
    sub.add_parser('install', help='Install this verified release into ~/.local; no PATH edits')
    sub.add_parser('install-skill', help='Install the bundled Codex skill without overwriting an existing skill')
    sub.add_parser('check-update', help='Read official GitHub release metadata (network)')
    sub.add_parser('update', help='Download, verify and activate the latest official release (network)')
    sub.add_parser('rollback', help='Activate the previous local version; no network')
    return p


def main(argv=None):
    args = parser().parse_args(argv)
    try:
        if args.command == 'doctor':
            runtime = config.load_runtime()
            emit({'status': 'READY', 'platform': platform.system(), 'product_version': __version__,
                  'claude_version': runtime['version'], 'registered_binary_unchanged': True,
                  'provider': config.ENDPOINT, 'model': config.MODEL,
                  'credentials': 'NOT READ', 'live_compatibility_on_this_mac': 'NOT TESTED'})
        elif args.command == 'configure':
            runtime = config.register(args.claude)
            emit({'status': 'configured', 'claude_version': runtime['version'], 'sha256': runtime['sha256'],
                  'next': 'In your own Terminal: deepseek-reviewer credentials save'})
        elif args.command == 'credentials':
            return config.credentials(args.action)
        elif args.command == 'prepare':
            limits = {k: getattr(args, k) for k in ('timeout', 'max_turns', 'max_budget_usd', 'max_output_tokens')}
            limits['effort'] = None if args.effort == 'default' else args.effort
            emit(tasks.create_plan(args.root, args.names, args.question, args.revision,
                                   args.constraints, args.test_evidence, limits))
        elif args.command == 'review':
            print('STARTING — Keychain may require Allow in macOS. Do not use Always Allow.', file=sys.stderr, flush=True)
            report = tasks.execute_plan(args.plan, args.plan_sha256,
                       progress=lambda value: print(json.dumps(value), file=sys.stderr, flush=True))
            emit(report)
            return 0 if report['status'] == 'COMPLETED' else 1
        elif args.command == 'install': emit(distribution.install_self())
        elif args.command == 'install-skill': emit(distribution.install_skill())
        elif args.command == 'check-update': emit(distribution.latest())
        elif args.command == 'update': emit(distribution.update())
        elif args.command == 'rollback': emit(distribution.rollback())
        return 0
    except KeyboardInterrupt:
        emit({'status': 'STOPPED', 'error': 'cancelled'}, sys.stderr)
    except (AgentStopped, ReviewError) as exc:
        emit({'status': 'STOPPED', 'error': str(exc)}, sys.stderr)
    except Exception as exc:
        # Never echo arbitrary OS errors, HTTP bodies, credentials or raw paths.
        emit({'status': 'STOPPED', 'error': type(exc).__name__}, sys.stderr)
    return 1
