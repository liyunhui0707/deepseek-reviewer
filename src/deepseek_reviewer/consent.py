"""Optional per-project disclosure agreement, not an OS or human-identity boundary.

Only an explicit user request may use it. Repository text cannot grant consent;
enrollment is a separate interactive action. No credential access here.
"""
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import uuid

from .config import app_home, home, private_directory, private_read, atomic_write, state_lock, ENDPOINT, MODEL
from .runner import AgentStopped
from .safety import validate_path, protected_path, directory_fd, scan_secrets, ReviewError


SIZES = {'quick': (6, 48 * 1024), 'standard': (12, 96 * 1024)}


def _encode(value):
    return (json.dumps(value, ensure_ascii=False, indent=2) + '\n').encode()


def _root(root):
    path = Path(root).absolute()
    if path == home() or path in home().parents or any(ord(c) < 32 or ord(c) == 127 for c in str(path)):
        raise AgentStopped('consent_root')
    scan_secrets(str(path))
    fd = directory_fd(path)  # Reject links in every component, including the root.
    try:
        info = os.fstat(fd)
        return str(path), [info.st_dev, info.st_ino]
    finally:
        os.close(fd)


def policy_path(root):
    name, _ = _root(root)
    return app_home() / 'consents' / (hashlib.sha256(name.encode()).hexdigest() + '.json')


def _scope(files, directories):
    if (not isinstance(files, list) or not isinstance(directories, list)
            or not 1 <= len(files) + len(directories) <= 50):
        raise AgentStopped('consent_scope')
    for names in (files, directories):
        for name in names:
            validate_path(name)
            if protected_path(name) or any(c in name for c in '*?[]'):
                raise AgentStopped('consent_scope')
        if len(set(names)) != len(names): raise AgentStopped('consent_scope')


def _validate(value, root):
    from .tasks import PROFILES
    fields = {'schema', 'revision', 'enabled', 'root', 'root_identity', 'files', 'directories',
              'endpoint', 'model', 'profile', 'limits', 'max_files', 'max_bytes'}
    try:
        name, identity = _root(root)
        if (not isinstance(value, dict) or set(value) != fields or type(value['schema']) is not int
                or value['schema'] != 1 or type(value['enabled']) is not bool
                or not isinstance(value['revision'], str) or not re.fullmatch('[a-f0-9]{32}', value['revision'])
                or value['root'] != name or value['root_identity'] != identity
                or value['endpoint'] != ENDPOINT or value['model'] != MODEL
                or value['profile'] not in PROFILES or value['limits'] != PROFILES[value['profile']]
                or (value['max_files'], value['max_bytes']) != SIZES[value['profile']]):
            raise ValueError
        _scope(value['files'], value['directories'])
        scan_secrets(value)
    except (KeyError, TypeError, ValueError, ReviewError):
        raise AgentStopped('consent_invalid') from None
    return value


def status(root):
    path = policy_path(root)
    try:
        raw = private_read(path)
    except FileNotFoundError:
        return {'status': 'NOT_CONFIGURED'}
    try: value = _validate(json.loads(raw), root)
    except (ValueError, UnicodeError, RecursionError):
        raise AgentStopped('consent_invalid') from None
    return {'status': 'ENABLED' if value['enabled'] else 'REVOKED',
            'sha256': hashlib.sha256(raw).hexdigest(), 'policy': value}


def require(root):
    result = status(root)
    if result['status'] == 'NOT_CONFIGURED': raise AgentStopped('consent_missing')
    if result['status'] != 'ENABLED': raise AgentStopped('consent_revoked')
    return result


def enable(root, *, files, directories, profile):
    from .tasks import PROFILES
    if not sys.stdin.isatty() or not sys.stderr.isatty():
        raise AgentStopped('consent_requires_terminal')
    if profile not in PROFILES: raise AgentStopped('consent_invalid')
    name, identity = _root(root)
    _scope(files, directories)
    value = {'schema': 1, 'revision': uuid.uuid4().hex, 'enabled': True,
             'root': name, 'root_identity': identity, 'files': files, 'directories': directories,
             'endpoint': ENDPOINT, 'model': MODEL, 'profile': profile, 'limits': dict(PROFILES[profile]),
             'max_files': SIZES[profile][0], 'max_bytes': SIZES[profile][1]}
    raw = _encode(_validate(value, root))
    if len(raw) > 32768: raise AgentStopped('consent_scope')
    with state_lock():
        print('Authorize future explicitly requested DeepSeek reviews/consultations within this scope:\n'
              + raw.decode() + '\nDirectory grants include future files. Each request allows ONE attempt, not automatic retries.\n'
              'Limits apply per attempt, not cumulatively. Client estimates are not bill caps.\n'
              'Source and task text go to DeepSeek. Secret detection is incomplete.\n'
              'Host approvals and macOS Keychain consent still apply. No password-free access is granted.\n'
              'This replaces any earlier agreement for this project. Type AUTHORIZE to save:', file=sys.stderr, flush=True)
        try: confirmation = input()
        except (EOFError, KeyboardInterrupt): raise AgentStopped('consent_cancelled') from None
        if confirmation != 'AUTHORIZE': raise AgentStopped('consent_cancelled')
        private_directory(private_directory(app_home()) / 'consents')
        atomic_write(policy_path(root), raw)
    return status(root)


def revoke(root):
    with state_lock():
        current = status(root)
        if current['status'] == 'NOT_CONFIGURED': return current
        value = {**current['policy'], 'enabled': False, 'revision': uuid.uuid4().hex}
        atomic_write(policy_path(root), _encode(value))
    return status(root)


def check(root, names, limits, profile, *, size=None, expected_sha256=None):
    current = require(root)
    if expected_sha256 is not None and current['sha256'] != expected_sha256:
        raise AgentStopped('consent_changed')
    policy = current['policy']
    if (profile != policy['profile'] or limits['effort'] != policy['limits']['effort']
            or any(limits[k] > policy['limits'][k] for k in limits if k != 'effort')):
        raise AgentStopped('consent_limits_exceeded')
    if (len(names) > policy['max_files'] or (size is not None and size > policy['max_bytes'])
            or any(name not in policy['files'] and not any(name.startswith(d + '/') for d in policy['directories'])
                   for name in names)):
        raise AgentStopped('consent_scope_exceeded')
    return {'root': policy['root'], 'sha256': current['sha256']}
