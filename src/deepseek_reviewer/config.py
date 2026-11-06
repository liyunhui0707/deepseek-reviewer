"""Local compatibility registration. No credential value is read here."""
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import shlex
import stat
import subprocess
import tempfile

from .runner import AgentStopped, private_write

TESTED_CLAUDE = '2.1.312'
SERVICE = 'io.github.liyunhui0707.deepseek-reviewer'
ACCOUNT = 'deepseek-reviewer'
ENDPOINT = 'https://api.deepseek.com/anthropic'
MODEL = 'deepseek-flash[1m]'


def home():
    return Path.home().resolve()


def app_home():
    return home() / '.local/share/deepseek-reviewer'


def private_directory(path):
    path = Path(path)
    if path.is_symlink():
        raise AgentStopped('unsafe_private_directory')
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    if path.resolve() != path or path.stat().st_uid != os.getuid() or path.stat().st_mode & 0o077:
        raise AgentStopped('unsafe_private_directory')
    return path


def managed_policy_paths():
    # A managed policy can override CLI settings. Do not read its contents.
    return [Path('/Library/Application Support/ClaudeCode') / n for n in
            ('managed-settings.json', 'managed-settings.d', 'managed-mcp.json')] + [
        Path('/Library/Managed Preferences/com.anthropic.claudecode.plist'),
        Path('/Library/Managed Preferences') / home().name / 'com.anthropic.claudecode.plist',
        home() / 'Library/Preferences/com.anthropic.claudecode.plist',
        home() / 'Library/Managed Preferences/com.anthropic.claudecode.plist']


def check_policy():
    if any(p.exists() or p.is_symlink() for p in managed_policy_paths()):
        raise AgentStopped('managed_policy_present_requires_review')


def fingerprint(path):
    with Path(path).open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


def register(claude):
    if platform.system() != 'Darwin':
        raise AgentStopped('macos_required')
    check_policy()
    p = Path(claude).expanduser().resolve(strict=True)
    if not p.is_file() or not os.access(p, os.X_OK) or p.stat().st_mode & 0o022:
        raise AgentStopped('unsafe_claude_executable')
    before = fingerprint(p)
    with tempfile.TemporaryDirectory(prefix='reviewer-cli-check-') as d:
        env = {'PATH': '/usr/bin:/bin', 'HOME': d, 'TMPDIR': d,
               'CLAUDE_CONFIG_DIR': d, 'CLAUDE_SECURESTORAGE_CONFIG_DIR': d,
               'DISABLE_AUTOUPDATER': '1', 'CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC': '1'}
        version = subprocess.run([str(p), '--version'], env=env, capture_output=True, timeout=10, check=True)
        if not re.fullmatch(re.escape(TESTED_CLAUDE) + r' \(Claude Code\)\s*', version.stdout.decode()):
            raise AgentStopped('unsupported_claude_version')
        help_result = subprocess.run([str(p), '--help'], env=env, capture_output=True, timeout=10, check=True)
        if not all(x.encode() in help_result.stdout for x in
                   ('--restricted', '--safe-mode', '--tools', '--setting-sources', '--strict-mcp-config',
                    '--max-turns', '--max-budget-usd', '--no-session-persistence', 'dontAsk', 'stream-json')):
            raise AgentStopped('missing_claude_capability')
    if fingerprint(p) != before:
        raise AgentStopped('claude_changed_during_registration')
    value = {'schema': 1, 'claude': str(p), 'version': TESTED_CLAUDE, 'sha256': before,
             'keychain': str(home() / 'Library/Keychains/login.keychain-db')}
    root = private_directory(app_home())
    target = root / 'runtime.json'
    if target.exists() or target.is_symlink():
        raise AgentStopped('already_configured_use_a_reviewed_migration')
    private_write(target, value)
    return value


def load_runtime():
    p = app_home() / 'runtime.json'
    if p.is_symlink() or not p.is_file() or p.stat().st_mode & 0o077:
        raise AgentStopped('runtime_missing_or_unsafe_run_configure')
    value = json.loads(p.read_text())
    verify_runtime(value)
    return value


def verify_runtime(value):
    if (not isinstance(value, dict) or set(value) != {'schema', 'claude', 'version', 'sha256', 'keychain'}
            or value['schema'] != 1 or value['version'] != TESTED_CLAUDE
            or value['keychain'] != str(home() / 'Library/Keychains/login.keychain-db')):
        raise AgentStopped('runtime_config_invalid')
    p = Path(value['claude'])
    if (not p.is_absolute() or p.resolve() != p or not p.is_file()
            or not os.access(p, os.X_OK) or p.stat().st_mode & 0o022
            or fingerprint(p) != value['sha256']):
        raise AgentStopped('registered_claude_changed')
    check_policy()


def keychain_helper(runtime):
    # Only Claude executes this command. Never run it as a credential preflight.
    return 'exec ' + shlex.join(['/usr/bin/security', 'find-generic-password',
             '-s', SERVICE, '-a', ACCOUNT, '-w', runtime['keychain']]) + ' 2>/dev/null'


def credential_command(action, keychain):
    if action == 'remove':
        return ['/usr/bin/security', 'delete-generic-password', '-s', SERVICE, '-a', ACCOUNT, keychain]
    return ['/usr/bin/security', 'add-generic-password', *(['-U'] if action == 'replace' else []),
            '-s', SERVICE, '-a', ACCOUNT, '-T', '', '-w']


def credentials(action):
    import sys
    if not sys.stdin.isatty() or not sys.stderr.isatty():
        raise AgentStopped('credentials_require_your_interactive_terminal')
    runtime = load_runtime()
    # Metadata only. add-generic-password -w must be last to invoke hidden input.
    current = subprocess.run(['/usr/bin/security', 'default-keychain', '-d', 'user'],
                             capture_output=True, timeout=10, check=True)
    if current.stdout.decode().strip().strip('"') != runtime['keychain']:
        raise AgentStopped('unexpected_default_keychain')
    print('Use the native hidden prompt. Never paste a key into chat. Use Allow, not Always Allow, for later access.', file=sys.stderr)
    return subprocess.call(credential_command(action, runtime['keychain']))
