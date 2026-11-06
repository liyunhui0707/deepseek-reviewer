"""No-follow snapshot collection; never discovers credentials."""
import os
from pathlib import Path
import re
import stat
MAX_BYTES = 256 * 1024
MAX_FILES = 50

_SECRET = re.compile(
    r'-----BEGIN (?:[A-Z ]*PRIVATE KEY|OPENSSH PRIVATE KEY)-----'
    r'|\b(?:sk-[A-Za-z0-9_-]{20,}|AKIA[A-Z0-9]{16}|gh[pousr]_[A-Za-z0-9]{20,}|'
    r'github_pat_[A-Za-z0-9_]{20,}|xox[baprs]-[A-Za-z0-9-]{15,})'
    r'|(?i:\b(?:api[_-]?key|access[_-]?token|secret|password|authorization)\b\s*[=:]\s*["\x27]?[^\s"\x27]{8,})'
)

class ReviewError(Exception):
    """Only fixed, non-sensitive codes cross the adapter boundary."""
    def __init__(self, code):
        self.code = code
        super().__init__(code)

def validate_path(name):
    if (not isinstance(name, str) or not name or len(name) > 1024
            or name.startswith(('/', '-')) or '\\' in name
            or any(ord(c) < 32 or ord(c) == 127 for c in name)
            or any(p in ('', '.', '..') or p.startswith('-') for p in name.split('/'))):
        raise ReviewError('invalid_path')
    try:
        name.encode('utf-8', errors='strict')
    except UnicodeError:
        raise ReviewError('invalid_path') from None
    return name

def selected_paths(paths):
    if not isinstance(paths, (list, tuple)) or not 1 <= len(paths) <= MAX_FILES:
        raise ReviewError('file_limit')
    names = tuple(validate_path(x) for x in paths)
    if len(set(names)) != len(names):
        raise ReviewError('duplicate_path')
    return names

def protected_path(name):
    parts = name.casefold().split('/')
    denied = {'secrets', '.git', '.ssh', '.aws', '.azure', '.gnupg', '.codex', '.claude',
              '.agents', 'keychains', 'credentials', 'sessions', 'raw-sessions', 'logs',
              '.review-state', '.review-records', 'node_modules', '.venv', 'venv'}
    return any(p in denied or p.startswith('.env') or p.endswith(('.pem', '.key', '.p12', '.pfx', '.keychain', '.keychain-db'))
               or p in ('auth.json', 'credentials.json', 'id_rsa', 'id_ed25519', '.netrc',
                        '.npmrc', '.pypirc', 'cookies', 'cookies.sqlite', 'login data') for p in parts)

def directory_fd(path):
    """Open every component from / with O_NOFOLLOW; caller closes returned fd."""
    path = Path(path)
    if not path.is_absolute() or '..' in path.parts:
        raise ReviewError('invalid_root')
    fd = os.open('/', os.O_RDONLY | os.O_DIRECTORY)
    try:
        for part in path.parts[1:]:
            new = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            os.close(fd)
            fd = new
        return fd
    except OSError:
        os.close(fd)
        raise ReviewError('unsafe_path') from None

def read_selected(root, name, max_bytes=MAX_BYTES):
    validate_path(name)
    if protected_path(name):
        raise ReviewError('protected_path')
    fd = directory_fd(root)
    leaf = None
    try:
        for part in name.split('/')[:-1]:
            new = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            os.close(fd)
            fd = new
        leaf = os.open(name.split('/')[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
        before = os.fstat(leaf)
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
            raise ReviewError('unsupported_file')
        if before.st_size > max_bytes:
            raise ReviewError('input_limit')
        chunks = []
        length = 0
        while True:
            chunk = os.read(leaf, min(65536, max_bytes + 1 - length))
            if not chunk:
                break
            chunks.append(chunk)
            length += len(chunk)
            if length > max_bytes:
                raise ReviewError('input_limit')
        after = os.fstat(leaf)
        if (before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns) != (
                after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns):
            raise ReviewError('stale_snapshot')
        return b''.join(chunks)
    except FileNotFoundError:
        raise ReviewError('missing_file') from None
    except OSError:
        raise ReviewError('unsafe_path') from None
    finally:
        if leaf is not None:
            os.close(leaf)
        os.close(fd)

def scan_secrets(value):
    if isinstance(value, str):
        if _SECRET.search(value):
            raise ReviewError('sensitive_content')
    elif isinstance(value, dict):
        for key, item in value.items():
            scan_secrets(key)
            scan_secrets(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            scan_secrets(item)

def safe_text(data):
    if len(data) > MAX_BYTES:
        raise ReviewError('input_limit')
    if b'\x00' in data:
        raise ReviewError('binary')
    try:
        value = data.decode('utf-8', errors='strict')
    except UnicodeError:
        raise ReviewError('binary') from None
    scan_secrets(value)
    return value
