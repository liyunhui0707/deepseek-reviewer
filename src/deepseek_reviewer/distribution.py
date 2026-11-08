"""Versioned local installation and explicit GitHub Release updates."""
import hashlib
from importlib.resources import files
import json
import os
from pathlib import Path
import re
import shlex
import sys
import tempfile
from urllib.parse import urlparse
from urllib.request import HTTPRedirectHandler, HTTPSHandler, build_opener, ProxyHandler
import zipfile

from . import __version__
from .config import app_home, private_directory, private_read, atomic_write, state_lock, home
from .runner import AgentStopped, private_write

RELEASES = 'https://github.com/liyunhui0707/deepseek-reviewer/releases'
MAX_DOWNLOAD = 20 * 1024 * 1024


def version_tuple(value):
    if not isinstance(value, str) or not re.fullmatch(r'(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)', value):
        raise AgentStopped('invalid_release_version')
    return tuple(map(int, value.split('.')))


def allowed_url(url):
    p = urlparse(url)
    if (p.scheme != 'https' or p.hostname not in ('github.com', 'release-assets.githubusercontent.com',
                                                'objects.githubusercontent.com')
            or p.username or p.password or p.port not in (None, 443)):
        raise AgentStopped('untrusted_download_target')


class SafeRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        allowed_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def fetch(url, limit):
    allowed_url(url)
    # Explicit update only; no ambient proxy, token, cookie, or GitHub credential.
    opener = build_opener(ProxyHandler({}), HTTPSHandler(), SafeRedirect())
    with opener.open(url, timeout=20) as response:
        allowed_url(response.url)
        body = response.read(limit + 1)
    if len(body) > limit:
        raise AgentStopped('download_size_limit')
    return body


def latest():
    value = json.loads(fetch(RELEASES + '/latest/download/release.json', 16384))
    if (set(value) != {'version', 'file', 'sha256'} or value['file'] != 'deepseek-reviewer.pyz'
            or not re.fullmatch('[a-f0-9]{64}', value['sha256'])):
        raise AgentStopped('invalid_release_manifest')
    version_tuple(value['version'])
    return value


def validate_archive(path, version, expected_hash):
    if path.resolve() != path or not path.is_file() or path.stat().st_size > MAX_DOWNLOAD:
        raise AgentStopped('invalid_release_archive')
    body = path.read_bytes()
    if hashlib.sha256(body).hexdigest() != expected_hash:
        raise AgentStopped('release_checksum_mismatch')
    with zipfile.ZipFile(path) as archive:
        metadata = json.loads(archive.read('deepseek_reviewer/release.json'))
        if metadata != {'version': version}:
            raise AgentStopped('release_version_mismatch')
    return body


def _launcher(root):
    # One stable launcher; installation.json is the single atomic activation point.
    # -I/-S excludes ambient Python paths/site hooks. No credentials are accessed.
    code = '''import hashlib,json,os,re,stat,sys
from pathlib import Path
root=Path(ROOT)
try:
 p=root/'installation.json'
 assert p.resolve()==p and stat.S_ISREG(p.stat().st_mode) and p.stat().st_size<=16384 and not p.stat().st_mode & 0o077
 s=json.loads(p.read_bytes())
 assert re.fullmatch(r'(0|[1-9]\\d*)\\.(0|[1-9]\\d*)\\.(0|[1-9]\\d*)',s['version'])
 a=root/'releases'/s['version']/'deepseek-reviewer.pyz'
 assert a.resolve()==a and a.is_file() and a.stat().st_size<=20971520
 assert hashlib.sha256(a.read_bytes()).hexdigest()==s['sha256']
except Exception:
 sys.stderr.write('Reviewer installation is incomplete or changed. Reinstall a verified release; no review started.\\n')
 sys.exit(1)
os.execv(sys.executable,[sys.executable,'-I',str(a),*sys.argv[1:]])
'''.replace('ROOT', repr(str(root)))
    return ('#!/bin/sh\nexec ' + shlex.join([str(Path(sys.executable).resolve()), '-I', '-S', '-c', code]) + ' "$@"\n').encode()


def _activate(version, archive_hash):
    root = private_directory(app_home())
    archive = root / 'releases' / version / 'deepseek-reviewer.pyz'
    validate_archive(archive, version, archive_hash)
    state_file = root / 'installation.json'
    previous = None
    current = None
    if state_file.exists():
        current = json.loads(private_read(state_file))
        version_tuple(current['version'])
        if not re.fullmatch('[a-f0-9]{64}', current['sha256']):
            raise AgentStopped('invalid_installation_state')
        previous = (current.get('previous') if current['version'] == version
                    else {'version': current['version'], 'sha256': current['sha256']})
    binary_dir = home() / '.local/bin'
    binary_dir.mkdir(parents=True, exist_ok=True)
    if binary_dir.resolve() != binary_dir:
        raise AgentStopped('unsafe_binary_directory')
    target = binary_dir / 'deepseek-reviewer'
    wrapper = _launcher(root)
    if target.is_symlink(): raise AgentStopped('unsafe_install_target')
    if target.exists() and not state_file.exists() and private_read(target, 16384) != wrapper:
        raise AgentStopped('existing_unmanaged_command')
    if target.exists() and current:
        old_archive = root / 'releases' / current['version'] / 'deepseek-reviewer.pyz'
        legacy = ('#!/bin/sh\nexec ' + shlex.join([str(Path(sys.executable).resolve()), str(old_archive)]) + ' "$@"\n').encode()
        actual_hash = hashlib.sha256(private_read(target, 16384)).hexdigest()
        expected_hash = current.get('launcher_sha256', hashlib.sha256(legacy).hexdigest())
        if actual_hash not in (expected_hash, hashlib.sha256(wrapper).hexdigest()):
            raise AgentStopped('existing_unmanaged_command')
    # Migrating the old fixed launcher first is safe: it still selects the old
    # valid state until the final atomic replacement succeeds. No two-file commit.
    state = {'version': version, 'sha256': archive_hash, 'previous': previous,
             'launcher_sha256': hashlib.sha256(wrapper).hexdigest()}
    atomic_write(target, wrapper, 0o700)
    atomic_write(state_file, (json.dumps(state) + '\n').encode(), 0o600)
    return {'version': version, 'command': str(target), 'previous': previous}


def install_archive(path, version, expected_hash):
    with state_lock():
        return _install_archive(path, version, expected_hash)


def _install_archive(path, version, expected_hash):
    version_tuple(version)
    path = Path(path).resolve()
    body = validate_archive(path, version, expected_hash)
    root = private_directory(app_home())
    directory = private_directory(private_directory(root / 'releases') / version)
    destination = directory / 'deepseek-reviewer.pyz'
    if destination.exists():
        validate_archive(destination, version, expected_hash)
    else:
        atomic_write(destination, body, 0o600)
    return _activate(version, expected_hash)


def install_self():
    path = Path(sys.argv[0]).resolve()
    if not zipfile.is_zipfile(path):
        raise AgentStopped('install_requires_release_pyz')
    return install_archive(path, __version__, hashlib.sha256(path.read_bytes()).hexdigest())


def update():
    with state_lock():
        return _update()


def _update():
    manifest = latest()
    state = app_home() / 'installation.json'
    installed_version = json.loads(private_read(state))['version'] if state.exists() else __version__
    if version_tuple(manifest['version']) <= version_tuple(installed_version):
        return {'status': 'up_to_date', 'version': installed_version}
    url = RELEASES + '/download/v' + manifest['version'] + '/' + manifest['file']
    body = fetch(url, MAX_DOWNLOAD)
    if hashlib.sha256(body).hexdigest() != manifest['sha256']:
        raise AgentStopped('release_checksum_mismatch')
    with tempfile.TemporaryDirectory(prefix='reviewer-update-') as directory:
        path = Path(directory) / manifest['file']
        private_write(path, body)
        installed = _install_archive(path, manifest['version'], manifest['sha256'])
        return {**installed, 'next': 'Run deepseek-reviewer install-skill --check, then --update if needed. Claude registration and credentials are unchanged.'}


def rollback():
    with state_lock():
        current = json.loads(private_read(app_home() / 'installation.json'))
        previous = current.get('previous')
        if not previous: raise AgentStopped('no_previous_installation')
        version_tuple(previous['version'])
        return _activate(previous['version'], previous['sha256'])


def bundled_skill():
    try:
        return {n: files('deepseek_reviewer').joinpath('skill', n).read_bytes()
                for n in ('SKILL.md', 'agents/openai.yaml')}
    except FileNotFoundError:
        raise AgentStopped('skill_bundle_missing_use_release') from None


# Exact public v1.0.0 files, for safe adoption of installations predating receipts.
LEGACY_SKILL_HASHES = {
    'SKILL.md': 'd9432966d8073f8e969d17601b2c8c2ee0ecf49487c77200a1262326453a13c4',
    'agents/openai.yaml': '7bb145994f515a14cc80baa1f9bc0902a38ba83f5961d2050981bf851bace173',
}


def _hashes(contents):
    return {n: hashlib.sha256(b).hexdigest() for n, b in contents.items()}


def _skill_files():
    target = home() / '.codex/skills/deepseek-reviewer'
    if target.resolve() != target or target.is_symlink():
        raise AgentStopped('skill_modified_or_unmanaged')
    if not target.exists(): return None
    entries = list(target.rglob('*'))
    if (any(p.is_symlink() for p in entries)
            or {p.relative_to(target).as_posix() for p in entries} != {'SKILL.md', 'agents', 'agents/openai.yaml'}):
        raise AgentStopped('skill_modified_or_unmanaged')
    return {n: private_read(target / n, 65536) for n in LEGACY_SKILL_HASHES}


def _skill_status():
    desired = bundled_skill()
    installed = _skill_files()
    if installed is None: return {'status': 'NOT_INSTALLED'}
    hashes = _hashes(installed)
    receipt = app_home() / 'skill-installation.json'
    trusted = json.loads(private_read(receipt))['hashes'] if receipt.exists() else LEGACY_SKILL_HASHES
    if hashes != trusted:
        return {'status': 'MODIFIED_OR_UNMANAGED', 'next': 'Preserve your customization; automatic replacement is refused.'}
    return {'status': 'CURRENT' if installed == desired else 'UPDATE_AVAILABLE',
            'installed_hashes': hashes, 'bundled_hashes': _hashes(desired)}


def skill_status():
    with state_lock(shared=True):
        value = _skill_status()
        # Metadata only. A differently named legacy Skill can still win natural
        # language routing; CURRENT alone must not hide that competing entry.
        value['conflicting_skills'] = [f'~/{folder}/deepseek-review' for folder in ('.agents/skills', '.codex/skills')
            if (home() / folder / 'deepseek-review').exists() or (home() / folder / 'deepseek-review').is_symlink()]
        return value


def install_skill(*, update=False):
    with state_lock():
        target = home() / '.codex/skills/deepseek-reviewer'
        desired = bundled_skill()
        current = _skill_files()
        if current is not None:
            if not update: raise AgentStopped('skill_already_exists_no_overwrite')
            status = _skill_status()['status']
            if status == 'MODIFIED_OR_UNMANAGED': raise AgentStopped('skill_modified_or_unmanaged')
            if status == 'CURRENT': return {'status': 'CURRENT', 'installed': str(target)}
            backup = {'before': {n: b.decode('utf-8') for n, b in current.items()},
                      'after_hashes': _hashes(desired)}
            atomic_write(app_home() / 'skill.previous.json', json.dumps(backup).encode())
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.TemporaryDirectory(prefix='.reviewer-skill-', dir=target.parent) as d:
                stage = Path(d)
                (stage / 'agents').mkdir(mode=0o700)
                for name, body in desired.items(): private_write(stage / name, body)
                atomic_write(app_home() / 'skill-installation.json', json.dumps(
                    {'version': __version__, 'hashes': _hashes(desired)}).encode())
                os.rename(stage, target)
            return {'status': 'INSTALLED', 'installed': str(target),
                    'note': 'Start a new Codex session to discover the skill.'}
        try:
            for name, body in desired.items(): atomic_write(target / name, body)
            atomic_write(app_home() / 'skill-installation.json', json.dumps(
                {'version': __version__, 'hashes': _hashes(desired)}).encode())
        except (OSError, KeyboardInterrupt):
            # Keep the bounded backup for explicit restore; never overwrite edits.
            raise AgentStopped('skill_update_incomplete') from None
        return {'status': 'INSTALLED' if current is None else 'UPDATED', 'installed': str(target),
                'note': 'Start a new Codex session to discover the skill.'}


def restore_skill():
    with state_lock():
        backup = json.loads(private_read(app_home() / 'skill.previous.json', 262144))
        old = {n: b.encode('utf-8') for n, b in backup['before'].items()}
        if set(old) != set(LEGACY_SKILL_HASHES): raise AgentStopped('skill_modified_or_unmanaged')
        current = _skill_files()
        if current is None or any(_hashes(current)[n] not in (_hashes(old)[n], backup['after_hashes'][n]) for n in old):
            raise AgentStopped('skill_modified_or_unmanaged')
        target = home() / '.codex/skills/deepseek-reviewer'
        for n, body in old.items(): atomic_write(target / n, body)
        atomic_write(app_home() / 'skill-installation.json', json.dumps({'hashes': _hashes(old)}).encode())
        return {'status': 'RESTORED', 'installed': str(target)}
