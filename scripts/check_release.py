"""Exercise the actual archive in a disposable home; no Claude or network."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parents[1]
archive = ROOT / 'dist/deepseek-reviewer.pyz'
manifest = json.loads((ROOT / 'dist/release.json').read_text())
assert hashlib.sha256(archive.read_bytes()).hexdigest() == manifest['sha256']
with zipfile.ZipFile(archive) as z:
    assert not any(name.endswith('.pyc') or '__pycache__' in name or '.review-' in name for name in z.namelist())
    assert 'deepseek_reviewer/skill/SKILL.md' in z.namelist()
    assert 'deepseek_reviewer/reviewer.json' in z.namelist()
with tempfile.TemporaryDirectory(prefix='reviewer-install-check-') as d:
    env = {'HOME': str(Path(d).resolve()), 'PATH': '/usr/bin:/bin'}
    subprocess.run([sys.executable, str(archive), 'install'], env=env, check=True, capture_output=True)
    command = Path(env['HOME']) / '.local/bin/deepseek-reviewer'
    assert subprocess.check_output([str(command), '--version'], env=env).decode().strip() == manifest['version']
    subprocess.run([str(command), 'install-skill'], env=env, check=True, capture_output=True)
    skill = Path(env['HOME']) / '.codex/skills/deepseek-reviewer/SKILL.md'
    assert skill.is_file()
    repeated = subprocess.run([str(command), 'install-skill'], env=env, capture_output=True)
    assert repeated.returncode != 0
    doctor = subprocess.run([str(command), 'doctor'], env=env, capture_output=True)
    assert doctor.returncode != 0  # No registration is invented on a fresh Mac.
    assert json.loads(doctor.stderr)['error'] == 'runtime_missing_or_unsafe_run_configure'
print('PASS: actual archive, install, version, skill, no-overwrite and unconfigured fail-closed')
