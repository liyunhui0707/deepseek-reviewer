"""Execute the copied shell blocks against synthetic commands, never real installers."""
from html.parser import HTMLParser
from pathlib import Path
import re
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class InstallBlock(HTMLParser):
    def __init__(self):
        super().__init__(); self.capture = False; self.parts = []
    def handle_starttag(self, tag, attrs):
        if tag == 'pre' and dict(attrs).get('id') == 'install-code': self.capture = True
    def handle_endtag(self, tag):
        if tag == 'pre': self.capture = False
    def handle_data(self, text):
        if self.capture: self.parts.append(text)


class InstallInstructionTests(unittest.TestCase):
    def blocks(self):
        for filename in ('README.md', 'docs/guide.zh-CN.md'):
            for block in re.findall(r'```sh\n(.*?)```', (ROOT / filename).read_text(), re.S):
                if block.startswith('/bin/sh -eu -c'):
                    yield filename, block
        parser = InstallBlock(); parser.feed((ROOT / 'site/dist/index.html').read_text())
        yield 'website', ''.join(parser.parts)

    def run_block(self, block, failing):
        with tempfile.TemporaryDirectory(prefix='reviewer-copy-test-') as d:
            root = Path(d).resolve(); binary = root / 'bin'; binary.mkdir()
            product = root / '.local/bin'; product.mkdir(parents=True)
            commands = [(binary / 'shasum', 'checksum'), (binary / 'python3', 'python'),
                        (product / 'deepseek-reviewer', 'reviewer')]
            for path, name in commands:
                path.write_text('#!/bin/sh\n' + f'printf "%s\\n" "{name} $*" >> "$TRACE_FILE"\n'
                                + f'if [ "$FAIL_COMMAND" = "{name}" ]; then exit 9; fi\n')
                path.chmod(0o700)
            trace = root / 'trace'
            env = {'HOME': str(root), 'PATH': str(binary) + ':/usr/bin:/bin',
                   'TRACE_FILE': str(trace), 'FAIL_COMMAND': failing}
            result = subprocess.run(['/bin/sh', '-c', block], cwd=root, env=env,
                                    capture_output=True, timeout=5)
            return result.returncode, trace.read_text().splitlines()

    def test_copied_installation_stops_on_checksum_or_installer_failure(self):
        for name, block in self.blocks():
            with self.subTest(document=name):
                subprocess.run(['/bin/sh', '-n'], input=block.encode(), check=True, capture_output=True)
                if 'shasum ' not in block: continue
                code, trace = self.run_block(block, 'checksum')
                self.assertEqual(code, 9)
                self.assertEqual(len(trace), 1)
                self.assertTrue(trace[0].startswith('checksum'))
                code, trace = self.run_block(block, 'python')
                self.assertEqual(code, 9)
                self.assertEqual(len(trace), 2)
                self.assertFalse(any(t.startswith('reviewer') for t in trace))

    def test_success_and_configuration_failure_use_only_expected_commands(self):
        for name, block in self.blocks():
            with self.subTest(document=name):
                code, trace = self.run_block(block, '')
                self.assertEqual(code, 0)
                self.assertTrue(trace)
                self.assertTrue(all(t.split()[0] in ('checksum', 'python', 'reviewer') for t in trace))
                if 'deepseek-reviewer ' in block:
                    code, trace = self.run_block(block, 'reviewer')
                    self.assertEqual(code, 9)
                    self.assertEqual(sum(t.startswith('reviewer') for t in trace), 1)
