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
from .config import app_home, private_directory, home
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


def atomic_write(path, body, mode):
    path = Path(path)
    if path.is_symlink():
        raise AgentStopped('unsafe_install_target')
    fd, temporary = tempfile.mkstemp(prefix='.reviewer-', dir=path.parent)
    with os.fdopen(fd, 'wb') as f:
        f.write(body)
        f.flush()
        os.fsync(f.fileno())
    os.chmod(temporary, mode)
    os.replace(temporary, path)


def validate_archive(path, version, expected_hash):
    if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_DOWNLOAD:
        raise AgentStopped('invalid_release_archive')
    body = path.read_bytes()
    if hashlib.sha256(body).hexdigest() != expected_hash:
        raise AgentStopped('release_checksum_mismatch')
    with zipfile.ZipFile(path) as archive:
        metadata = json.loads(archive.read('deepseek_reviewer/release.json'))
        if metadata != {'version': version}:
            raise AgentStopped('release_version_mismatch')
    return body


def activate(version, archive_hash):
    root = private_directory(app_home())
    archive = root / 'releases' / version / 'deepseek-reviewer.pyz'
    validate_archive(archive, version, archive_hash)
    state_file = root / 'installation.json'
    previous = None
    if state_file.exists():
        current = json.loads(state_file.read_text())
        previous = {'version': current['version'], 'sha256': current['sha256']}
    binary_dir = home() / '.local/bin'
    binary_dir.mkdir(parents=True, exist_ok=True)
    if binary_dir.resolve() != binary_dir:
        raise AgentStopped('unsafe_binary_directory')
    target = binary_dir / 'deepseek-reviewer'
    if target.exists() and not state_file.exists():
        raise AgentStopped('existing_unmanaged_command')
    # Record the previous version before activation; no shell profile edits.
    state = {'version': version, 'sha256': archive_hash, 'previous': previous}
    wrapper = '#!/bin/sh\nexec ' + shlex.join([str(Path(sys.executable).resolve()), str(archive)]) + ' "$@"\n'
    atomic_write(target, wrapper.encode(), 0o700)
    atomic_write(state_file, (json.dumps(state) + '\n').encode(), 0o600)
    return {'version': version, 'command': str(target), 'previous': previous}


def install_archive(path, version, expected_hash):
    version_tuple(version)
    path = Path(path).resolve()
    body = validate_archive(path, version, expected_hash)
    root = private_directory(app_home())
    directory = private_directory(private_directory(root / 'releases') / version)
    destination = directory / 'deepseek-reviewer.pyz'
    if destination.exists():
        validate_archive(destination, version, expected_hash)
    else:
        private_write(destination, body)
    return activate(version, expected_hash)


def install_self():
    path = Path(sys.argv[0]).resolve()
    if not zipfile.is_zipfile(path):
        raise AgentStopped('install_requires_release_pyz')
    return install_archive(path, __version__, hashlib.sha256(path.read_bytes()).hexdigest())


def update():
    manifest = latest()
    if version_tuple(manifest['version']) <= version_tuple(__version__):
        return {'status': 'up_to_date', 'version': __version__}
    url = RELEASES + '/download/v' + manifest['version'] + '/' + manifest['file']
    body = fetch(url, MAX_DOWNLOAD)
    if hashlib.sha256(body).hexdigest() != manifest['sha256']:
        raise AgentStopped('release_checksum_mismatch')
    with tempfile.TemporaryDirectory(prefix='reviewer-update-') as directory:
        path = Path(directory) / manifest['file']
        private_write(path, body)
        return install_archive(path, manifest['version'], manifest['sha256'])


def rollback():
    current = json.loads((app_home() / 'installation.json').read_text())
    previous = current.get('previous')
    if not previous:
        raise AgentStopped('no_previous_installation')
    version_tuple(previous['version'])
    return activate(previous['version'], previous['sha256'])


def install_skill():
    target = home() / '.codex/skills/deepseek-reviewer'
    if target.exists() or target.is_symlink():
        raise AgentStopped('skill_already_exists_no_overwrite')
    target.mkdir(parents=True, mode=0o700)
    for name in ('SKILL.md', 'agents/openai.yaml'):
        p = target / name
        p.parent.mkdir(exist_ok=True)
        private_write(p, files('deepseek_reviewer').joinpath('skill', name).read_bytes())
    return {'installed': str(target), 'note': 'Start a new Codex session to discover the skill.'}
