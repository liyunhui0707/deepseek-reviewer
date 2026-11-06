"""Build a portable zipapp using only Python's standard library."""
import hashlib
import json
from pathlib import Path
import shutil
import tempfile
import zipapp

ROOT = Path(__file__).resolve().parents[1]
VERSION = '1.0.0'


def main():
    output = ROOT / 'dist'
    output.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='reviewer-build-') as directory:
        stage = Path(directory)
        shutil.copytree(ROOT / 'src/deepseek_reviewer', stage / 'deepseek_reviewer',
                        ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
        shutil.copytree(ROOT / 'skill', stage / 'deepseek_reviewer/skill')
        (stage / 'deepseek_reviewer/release.json').write_text(json.dumps({'version': VERSION}))
        (stage / '__main__.py').write_text('from deepseek_reviewer.cli import main\nraise SystemExit(main())\n')
        shutil.copyfile(ROOT / 'LICENSE', stage / 'LICENSE')
        zipapp.create_archive(stage, output / 'deepseek-reviewer.pyz', interpreter='/usr/bin/env python3', compressed=True)
    archive = output / 'deepseek-reviewer.pyz'
    checksum = hashlib.sha256(archive.read_bytes()).hexdigest()
    (output / 'SHA256SUMS').write_text(checksum + '  deepseek-reviewer.pyz\n')
    (output / 'release.json').write_text(json.dumps({'version': VERSION, 'file': archive.name, 'sha256': checksum}, indent=2) + '\n')
    print(json.dumps({'version': VERSION, 'sha256': checksum, 'bytes': archive.stat().st_size}))


if __name__ == '__main__': main()
