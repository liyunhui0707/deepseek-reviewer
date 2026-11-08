"""Exercise the actual archive in a disposable home; no Claude or network."""
import hashlib
import json
import os
from pathlib import Path
import platform
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
    if platform.system() == 'Darwin':
        synthetic = Path(env['HOME']) / '.local/share/claude/versions/2.1.312'
        synthetic.parent.mkdir(parents=True)
        synthetic.write_text('#!' + sys.executable + '''
import sys
if '--version' in sys.argv: print('2.1.312 (Claude Code)')
elif '--help' in sys.argv: print('--restricted --safe-mode --tools --setting-sources --strict-mcp-config --max-budget-usd --no-session-persistence dontAsk stream-json')
else: raise SystemExit('No model command is permitted in the packaging test')
''')
        synthetic.chmod(0o700)
        for _ in range(2):
            setup = subprocess.run([str(command), 'setup', '--json'], env=env,
                                   check=True, capture_output=True, timeout=30)
            result = json.loads(setup.stdout)
            assert result['status'] == 'LOCAL_READY' and result['credentials'] == 'NOT CHECKED'
        health = subprocess.check_output([str(command), 'doctor', '--text'], env=env, timeout=10)
        assert b'LOCAL_READY' in health and b'NOT TESTED' in health
        skill_check = json.loads(subprocess.check_output([str(command), 'install-skill', '--check', '--json'], env=env))
        assert skill_check['status'] == 'CURRENT'
        preview = json.loads(subprocess.check_output([str(command), 'configure', '--check', '--json'], env=env, timeout=30))
        assert preview['changed'] is False
        print('PASS: packaged setup/doctor/Skill check/registration preview with a synthetic Claude only')
    else:
        print('NOT RUN on non-macOS: packaged native setup (offline unit tests cover its logic)')
print('PASS: actual archive, install, version, skill, no-overwrite and unconfigured fail-closed')
