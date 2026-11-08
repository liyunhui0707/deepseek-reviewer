"""Local compatibility registration. No credential value is read here."""
import hashlib
from contextlib import contextmanager
import fcntl
import json
import os
from pathlib import Path
import platform
import re
import shlex
import shutil
import stat
import subprocess
import tempfile

from .runner import AgentStopped, private_write
from .safety import scan_secrets, ReviewError

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


@contextmanager
def state_lock(*, shared=False):
    """OS-released lock: reviews share it; maintenance requires exclusivity."""
    root = private_directory(app_home())
    fd = os.open(root / 'maintenance.lock', os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
            raise AgentStopped('unsafe_private_file')
        try: fcntl.flock(fd, (fcntl.LOCK_SH if shared else fcntl.LOCK_EX) | fcntl.LOCK_NB)
        except BlockingIOError: raise AgentStopped('state_busy') from None
        yield
    finally:
        os.close(fd)


def private_read(path, limit=32768):
    path = Path(path)
    if path.resolve() != path:
        raise AgentStopped('unsafe_private_file')
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, 'rb') as f:
        info = os.fstat(f.fileno())
        if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_uid != os.getuid()
                or info.st_mode & 0o077 or info.st_size > limit):
            raise AgentStopped('unsafe_private_file')
        data = f.read(limit + 1)
    if len(data) > limit: raise AgentStopped('unsafe_private_file')
    return data


def atomic_write(path, body, mode=0o600):
    path = Path(path)
    if path.is_symlink(): raise AgentStopped('unsafe_install_target')
    fd, temporary = tempfile.mkstemp(prefix='.reviewer-', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as f:
            f.write(body); f.flush(); os.fsync(f.fileno())
        os.chmod(temporary, mode)
        os.replace(temporary, path)
    finally:
        # Only the temporary file created by this call; never a user path.
        if os.path.exists(temporary): os.unlink(temporary)


def discover_claude():
    pinned = home() / '.local/share/claude/versions' / TESTED_CLAUDE
    if pinned.is_file(): return pinned
    candidate = shutil.which('claude')
    if candidate: return Path(candidate)
    raise AgentStopped('claude_not_found')


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


def _inspect_claude(claude):
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
        # Pinned 2.1.312 supports --max-turns but defines it with hideHelp().
        # Keep it in the review invocation; only visible flags belong here.
        if not all(x.encode() in help_result.stdout for x in
                   ('--restricted', '--safe-mode', '--tools', '--setting-sources', '--strict-mcp-config',
                    '--max-budget-usd', '--no-session-persistence', 'dontAsk', 'stream-json')):
            raise AgentStopped('missing_claude_capability')
    if fingerprint(p) != before:
        raise AgentStopped('claude_changed_during_registration')
    value = {'schema': 1, 'claude': str(p), 'version': TESTED_CLAUDE, 'sha256': before,
             'keychain': str(home() / 'Library/Keychains/login.keychain-db')}
    return value


def preview_registration(claude):
    with state_lock(shared=True):
        proposed = _inspect_claude(claude)
        target = app_home() / 'runtime.json'
        raw = private_read(target) if target.exists() or target.is_symlink() else None
        current = json.loads(raw) if raw else None
        if current is not None:
            _validate_runtime_shape(current)  # Never echo unknown configuration fields.
        return {'status': 'PREVIEW', 'current': current, 'proposed': proposed,
                'current_sha256': hashlib.sha256(raw).hexdigest() if raw else None,
                'credentials': 'NOT READ', 'changed': current != proposed}


def _confirmed_runtime(expected_sha256):
    raw = private_read(app_home() / 'runtime.json')
    if not expected_sha256 or hashlib.sha256(raw).hexdigest() != expected_sha256:
        raise AgentStopped('runtime_confirmation_changed')
    return raw


def register(claude, *, replace=False, expected_sha256=None):
    with state_lock():
        target = app_home() / 'runtime.json'
        exists = target.exists() or target.is_symlink()
        if exists and not replace:
            raise AgentStopped('already_configured_use_a_reviewed_migration')
        if replace and not exists: raise AgentStopped('runtime_missing_or_unsafe_run_configure')
        original = _confirmed_runtime(expected_sha256) if replace else None
        value = _inspect_claude(claude)
        if original is None:
            private_write(target, value)
        else:
            atomic_write(app_home() / 'runtime.previous.json', original)
            atomic_write(target, (json.dumps(value) + '\n').encode())
        return value


def restore_runtime(expected_sha256):
    with state_lock():
        current = _confirmed_runtime(expected_sha256)
        previous = private_read(app_home() / 'runtime.previous.json')
        value = json.loads(previous)
        verify_runtime(value)  # A missing/changed old binary cannot be restored safely.
        atomic_write(app_home() / 'runtime.json', previous)
        atomic_write(app_home() / 'runtime.previous.json', current)
        return value


def load_runtime():
    p = app_home() / 'runtime.json'
    if p.is_symlink() or not p.is_file() or p.stat().st_mode & 0o077:
        raise AgentStopped('runtime_missing_or_unsafe_run_configure')
    value = json.loads(private_read(p))
    verify_runtime(value)
    return value


def _validate_runtime_shape(value):
    if (not isinstance(value, dict) or set(value) != {'schema', 'claude', 'version', 'sha256', 'keychain'}
            or value['schema'] != 1 or value['version'] != TESTED_CLAUDE
            or not isinstance(value['claude'], str) or not Path(value['claude']).is_absolute()
            or not isinstance(value['sha256'], str) or not re.fullmatch('[a-f0-9]{64}', value['sha256'])
            or value['keychain'] != str(home() / 'Library/Keychains/login.keychain-db')):
        raise AgentStopped('runtime_config_invalid')
    try: scan_secrets(value)
    except ReviewError: raise AgentStopped('runtime_config_invalid') from None


def verify_runtime(value):
    _validate_runtime_shape(value)
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
    with state_lock():
        return _credentials(action)


def _credentials(action):
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
