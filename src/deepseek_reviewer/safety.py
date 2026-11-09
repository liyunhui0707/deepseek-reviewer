"""No-follow snapshot collection; never discovers credentials."""
import json
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


def validate_checkpoint(value, approved_files):
    """Only a bounded, explicitly public review artifact, never arbitrary prose.

    This validates shape/disclosure, not the model's claims or cited line accuracy.
    Unknown fields (including reasoning) are rejected rather than logged.
    """
    def text(item):
        return (isinstance(item, str) and bool(item.strip()) and len(item) <= 2000
                and not any(ord(c) < 32 and c not in '\n\t' or ord(c) == 127 for c in item)
                and not re.search(r'/(?:Users|home|private|tmp)/', item))
    version = value.get('schema') if isinstance(value, dict) else None
    fields = {'schema', 'findings', 'coverage_gaps'}
    if version == 2: fields |= {'assessment', 'reviewed_files'}
    if (not isinstance(value, dict) or set(value) != fields
            or type(version) is not int or version not in (1, 2)
            or not isinstance(value['findings'], list) or len(value['findings']) > 12
            or not isinstance(value['coverage_gaps'], list) or len(value['coverage_gaps']) > 20
            or not all(text(gap) for gap in value['coverage_gaps'])
            or len(json.dumps(value, ensure_ascii=False).encode()) > 16384):
        raise ReviewError('invalid_checkpoint')
    if version == 2:
        reviewed = value['reviewed_files']
        if (not text(value['assessment']) or not isinstance(reviewed, list) or not reviewed
                or not all(isinstance(name, str) and name in approved_files for name in reviewed)
                or len(reviewed) != len(set(reviewed))):
            raise ReviewError('invalid_checkpoint')
    fields = {'kind', 'severity', 'file', 'line', 'evidence', 'explanation', 'suggestion'}
    for finding in value['findings']:
        if (not isinstance(finding, dict) or set(finding) != fields
                or finding['kind'] not in ('finding', 'hypothesis', 'advice')
                or finding['severity'] not in ('P0', 'P1', 'P2', 'P3')
                or not isinstance(finding['file'], str) or finding['file'] not in approved_files
                or type(finding['line']) is not int or not 1 <= finding['line'] <= 10000000
                or not all(text(finding[k]) for k in ('evidence', 'explanation', 'suggestion'))):
            raise ReviewError('invalid_checkpoint')
    scan_secrets(value)
    return value


def parse_review_report(text, approved_files, read_files, *, diagnostic=None):
    """Accept an explicit public report, not progress text or hidden reasoning.

    One schema for public revisions and terminal results. Fence labels carry no
    completion authority; the caller must verify terminal execution separately.
    Accept bare JSON or one review-report/json/legacy review-checkpoint fence.
    Diagnostic values are fixed labels, never exception text or model content.
    Structural validity and observed reads do not prove review quality.
    """
    detail = diagnostic if diagnostic is not None else {}
    detail.update(status='rejected', stage='input', reason=None, envelope='not_inspected')

    def reject(stage, reason):
        detail.update(stage=stage, reason=reason)
        raise ReviewError('invalid_review_report')

    if not isinstance(text, str): reject('input', 'non_text_result')
    try: size = len(text.encode('utf-8'))
    except UnicodeError: reject('input', 'invalid_encoding')
    if size > 32768: reject('input', 'report_too_large')
    if not text.strip(): reject('input', 'empty_result')
    try: scan_secrets(text)
    except ReviewError: reject('content', 'sensitive_content')
    text = text.replace('\r\n', '\n').strip()
    if text.startswith('{'):
        detail['envelope'] = 'bare_json'
        body = text
    else:
        # Count every fence, rather than selecting a favorable report from
        # multiple blocks that might contradict or supersede each other.
        fences = list(re.finditer(r'(?m)^[ \t]*```([^\n`]*)$', text))
        if not fences:
            detail['envelope'] = 'unrecognized'
            reject('envelope', 'missing_report_object')
        label = fences[0][1].strip()
        detail['envelope'] = {'review-report': 'review_report_fence', 'json': 'json_fence',
                              'review-checkpoint': 'checkpoint_fence'}.get(label, 'unsupported_fence')
        if len(fences) > 2: reject('envelope', 'multiple_fences')
        if len(fences) != 2 or fences[1][1].strip(): reject('envelope', 'incomplete_fence')
        if label not in ('review-report', 'json', 'review-checkpoint'):
            reject('envelope', 'unsupported_fence')
        body = text[fences[0].end():fences[1].start()]

    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result: reject('json', 'duplicate_key')
            result[key] = value
        return result
    def constant(_): reject('json', 'nonfinite_number')
    try: value = json.loads(body, object_pairs_hook=unique, parse_constant=constant)
    except (ValueError, UnicodeError, RecursionError): reject('json', 'invalid_json')
    if not isinstance(value, dict) or type(value.get('schema')) is not int or value['schema'] != 2:
        reject('schema', 'unsupported_schema')
    try: validate_checkpoint(value, approved_files)
    except ReviewError as exc:
        if exc.code == 'sensitive_content': reject('content', 'sensitive_content')
        reject('schema', 'invalid_schema_or_values')
    except (ValueError, TypeError, UnicodeError, RecursionError):
        reject('schema', 'invalid_schema_or_values')
    if not set(value['reviewed_files']) <= set(read_files): reject('evidence', 'unobserved_read')
    if any(item['file'] not in value['reviewed_files'] for item in value['findings']):
        reject('evidence', 'finding_not_reviewed')
    detail.update(status='accepted', stage='complete', reason=None)
    return value


def render_review(value):
    lines = [value['assessment']]
    for item in value['findings']:
        lines.extend([f"{item['severity']} [{item['kind']}] {item['file']}:{item['line']}",
                      item['evidence'], item['explanation'], 'Suggestion: ' + item['suggestion']])
    if not value['findings']: lines.append('No supported findings reported; not an approval.')
    lines.append('Reviewed files (model claim): ' + ', '.join(value['reviewed_files']))
    lines.extend('Coverage gap: ' + gap for gap in value['coverage_gaps'])
    return '\n'.join(lines)

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
