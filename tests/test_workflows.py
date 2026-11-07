"""User workflows and interrupted maintenance; synthetic binaries, no credentials."""
import contextlib
import hashlib
import io
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import unittest
from unittest.mock import patch

import test_product
from deepseek_reviewer import cli, config, distribution, tasks
from deepseek_reviewer.runner import AgentStopped


class WorkflowTests(unittest.TestCase):
    setUp = test_product.PortableTests.setUp
    tearDown = test_product.PortableTests.tearDown
    plan = test_product.PortableTests.plan

    def bundle(self, version='one'):
        return {'SKILL.md': ('synthetic skill ' + version).encode(),
                'agents/openai.yaml': b'interface: {}\n'}

    def test_runtime_preview_replace_restore_and_stale_confirmation(self):
        target = config.app_home() / 'runtime.json'
        original = target.read_bytes()
        other = self.root / 'replacement-claude'
        other.write_bytes(self.claude.read_bytes()); other.chmod(0o700)
        with patch.object(config.platform, 'system', return_value='Darwin'):
            preview = config.preview_registration(other)
            self.assertEqual(target.read_bytes(), original)
            self.assertEqual(preview['current_sha256'], hashlib.sha256(original).hexdigest())
            with self.assertRaisesRegex(AgentStopped, 'runtime_confirmation_changed'):
                config.register(other, replace=True, expected_sha256='0' * 64)
            config.register(other, replace=True, expected_sha256=preview['current_sha256'])
        self.assertEqual(config.load_runtime()['claude'], str(other))
        self.assertEqual((config.app_home() / 'runtime.previous.json').read_bytes(), original)
        config.restore_runtime(hashlib.sha256(target.read_bytes()).hexdigest())
        self.assertEqual(config.load_runtime()['claude'], str(self.claude))

    def test_setup_is_repeatable_without_keychain_or_model(self):
        with patch.object(distribution, 'bundled_skill', return_value=self.bundle()), \
                patch.object(config, 'credentials') as credentials:
            first = cli.setup(None)
            second = cli.setup(None)
        credentials.assert_not_called()
        self.assertEqual(first['status'], 'LOCAL_READY')
        self.assertEqual(second['skill']['status'], 'CURRENT')
        self.assertEqual(second['credentials'], 'NOT CHECKED')

    def test_first_setup_finds_existing_binary_and_never_enrolls_key(self):
        (config.app_home() / 'runtime.json').rename(config.app_home() / 'synthetic-prior-registration')
        with patch.object(config.platform, 'system', return_value='Darwin'), \
                patch.object(config, 'discover_claude', return_value=self.claude), \
                patch.object(distribution, 'bundled_skill', return_value=self.bundle()), \
                patch.object(config, 'credentials') as credential:
            result = cli.setup(None)
        credential.assert_not_called()
        self.assertEqual(result['status'], 'LOCAL_READY')
        self.assertEqual(config.load_runtime()['sha256'], self.runtime['sha256'])

    def test_unsupported_replacement_leaves_registration_and_backup_untouched(self):
        original = (config.app_home() / 'runtime.json').read_bytes()
        other = self.root / 'incompatible-claude'
        other.write_bytes(self.claude.read_bytes().replace(b'2.1.312', b'9.9.999'))
        other.chmod(0o700)
        with patch.object(config.platform, 'system', return_value='Darwin'):
            with self.assertRaisesRegex(AgentStopped, 'unsupported_claude_version'):
                config.register(other, replace=True, expected_sha256=hashlib.sha256(original).hexdigest())
        self.assertEqual((config.app_home() / 'runtime.json').read_bytes(), original)
        self.assertFalse((config.app_home() / 'runtime.previous.json').exists())

    def test_registration_preview_rejects_unknown_or_credential_like_fields(self):
        target = config.app_home() / 'runtime.json'
        for value in ({**self.runtime, 'unexpected': 'synthetic'},
                      {**self.runtime, 'claude': '/synthetic/sk-' + 'X' * 25}):
            target.write_text(json.dumps(value))
            with patch.object(config.platform, 'system', return_value='Darwin'):
                with self.assertRaisesRegex(AgentStopped, 'runtime_config_invalid'):
                    config.preview_registration(self.claude)

    def test_skill_update_preserves_user_edits_and_supports_restore(self):
        target = config.home() / '.codex/skills/deepseek-reviewer/SKILL.md'
        with patch.object(distribution, 'bundled_skill', return_value=self.bundle()):
            distribution.install_skill()
        with patch.object(distribution, 'bundled_skill', return_value=self.bundle('two')):
            self.assertEqual(distribution.skill_status()['status'], 'UPDATE_AVAILABLE')
            distribution.install_skill(update=True)
            self.assertEqual(target.read_bytes(), self.bundle('two')['SKILL.md'])
            distribution.restore_skill()
            self.assertEqual(target.read_bytes(), self.bundle()['SKILL.md'])
            target.write_text('user customization')
            with self.assertRaisesRegex(AgentStopped, 'skill_modified_or_unmanaged'):
                distribution.install_skill(update=True)
            self.assertEqual(target.read_text(), 'user customization')

    def test_skill_extra_file_is_not_silently_overwritten(self):
        with patch.object(distribution, 'bundled_skill', return_value=self.bundle()):
            distribution.install_skill()
            (config.home() / '.codex/skills/deepseek-reviewer/custom.md').write_text('custom')
            with self.assertRaisesRegex(AgentStopped, 'skill_modified_or_unmanaged'):
                distribution.install_skill(update=True)

    def test_interrupted_skill_update_can_restore_without_overwriting_customization(self):
        with patch.object(distribution, 'bundled_skill', return_value=self.bundle()):
            distribution.install_skill()
        write = distribution.atomic_write
        def fail_yaml(path, body, *args):
            if Path(path).name == 'openai.yaml': raise OSError('synthetic disk failure')
            return write(path, body, *args)
        with patch.object(distribution, 'bundled_skill', return_value=self.bundle('two')), \
                patch.object(distribution, 'atomic_write', side_effect=fail_yaml):
            with self.assertRaisesRegex(AgentStopped, 'skill_update_incomplete'):
                distribution.install_skill(update=True)
        distribution.restore_skill()
        target = config.home() / '.codex/skills/deepseek-reviewer/SKILL.md'
        self.assertEqual(target.read_bytes(), self.bundle()['SKILL.md'])
        target.write_text('new user customization')
        with self.assertRaisesRegex(AgentStopped, 'skill_modified_or_unmanaged'):
            distribution.restore_skill()
        self.assertEqual(target.read_text(), 'new user customization')

    def test_known_legacy_skill_can_be_adopted_but_unknown_skill_cannot(self):
        with patch.object(distribution, 'bundled_skill', return_value=self.bundle()):
            distribution.install_skill()
        receipt = config.app_home() / 'skill-installation.json'
        receipt.rename(config.app_home() / 'synthetic-old-receipt')
        hashes = {n: hashlib.sha256(b).hexdigest() for n, b in self.bundle().items()}
        with patch.object(distribution, 'LEGACY_SKILL_HASHES', hashes), \
                patch.object(distribution, 'bundled_skill', return_value=self.bundle('two')):
            self.assertEqual(distribution.skill_status()['status'], 'UPDATE_AVAILABLE')
            distribution.install_skill(update=True)
            self.assertTrue(receipt.exists())

    def test_maintenance_cannot_overlap_a_review(self):
        with config.state_lock(shared=True):
            with self.assertRaisesRegex(AgentStopped, 'state_busy'):
                with config.state_lock():
                    self.fail('maintenance entered during a review')
            with patch.object(config, '_credentials') as credentials:
                with self.assertRaisesRegex(AgentStopped, 'state_busy'): config.credentials('replace')
                credentials.assert_not_called()

    def test_cancellation_still_saves_report_and_consumes_attempt(self):
        plan = self.plan()
        def cancel(_): raise KeyboardInterrupt
        report = tasks.execute_plan(plan['plan'], plan['sha256'], progress=cancel)
        self.assertEqual(report['failure'], 'cancelled')
        self.assertEqual(report['status'], 'FAILED')
        self.assertEqual(tasks.read_report(plan['id'])['failure'], 'cancelled')
        self.assertNotIn('stdout', json.loads(Path(report['report_path']).read_text()))
        with self.assertRaisesRegex(AgentStopped, 'attempt_consumed'):
            tasks.execute_plan(plan['plan'], plan['sha256'])

    def test_coverage_is_observed_reads_not_a_quality_certificate(self):
        plan = self.plan()
        report = tasks.execute_plan(plan['plan'], plan['sha256'])
        self.assertEqual(report['coverage_observation']['successful_read_files'], ['price.py'])
        self.assertEqual(report['coverage_observation']['no_successful_read_observed'], ['test_price.py'])
        self.assertEqual(report['quality'], 'requires_primary_agent_verification')

    def test_human_and_json_diagnostics_never_query_credentials(self):
        for flag in ('--text', '--json'):
            out = io.StringIO()
            with patch.object(config, 'credentials') as credentials, contextlib.redirect_stdout(out):
                self.assertEqual(cli.main(['doctor', flag]), 0)
            credentials.assert_not_called()
            self.assertIn('LOCAL_READY', out.getvalue())
            self.assertNotIn('Keychain authentication passed', out.getvalue())

    def test_errors_explain_the_next_step_without_raw_os_details(self):
        err = io.StringIO()
        with patch.object(config, 'load_runtime', side_effect=AgentStopped('registered_claude_changed')), \
                contextlib.redirect_stderr(err):
            self.assertEqual(cli.main(['doctor', '--json']), 1)
        value = json.loads(err.getvalue())
        self.assertEqual(value['error'], 'registered_claude_changed')
        self.assertIn('configure', value['next'])

    def test_progress_and_terminal_output_do_not_invent_authentication_or_accept_control_codes(self):
        out = io.StringIO()
        with contextlib.redirect_stderr(out):
            cli.progress_notice({'phase': 'started', 'notification': 'heartbeat', 'elapsed_seconds': 5,
                                 'remaining_seconds': 295, 'tool': None, 'file': None}, 'text')
        self.assertIn('cause unknown', out.getvalue())
        self.assertIn('295s remaining', out.getvalue())
        self.assertNotIn('waiting for Keychain', out.getvalue())
        self.assertEqual(cli.terminal_text('\x1b[31mred\x1b[0m\x1b]0;secret-title\x07'), 'red')

    def test_report_lookup_cannot_read_arbitrary_paths(self):
        for value in ('../runtime.json', '/etc/passwd', 'not-an-attempt'):
            with self.assertRaisesRegex(AgentStopped, 'invalid_attempt_id'): tasks.read_report(value)

    def test_sigterm_stops_synthetic_child_and_saves_failure(self):
        plan = self.plan()
        # A separate Python process receives the signal; never the user's CLI/session.
        code = '''import json,sys,time
from deepseek_reviewer import tasks,config
config.managed_policy_paths=lambda: []
def progress(e):
 if e['phase']=='started':
  print('STARTED',flush=True)
  time.sleep(20)
r=tasks.execute_plan(sys.argv[1],sys.argv[2],progress=progress)
print(json.dumps({'failure':r['failure'],'status':r['status']}),flush=True)
'''
        env = {'HOME': str(self.root), 'PATH': '/usr/bin:/bin',
               'PYTHONPATH': str(Path(__file__).resolve().parents[1] / 'src')}
        child = subprocess.Popen([sys.executable, '-B', '-c', code, plan['plan'], plan['sha256']],
                                 env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        try:
            # select bounds the handshake even if the implementation regresses.
            import select
            self.assertTrue(select.select([child.stdout], [], [], 5)[0])
            self.assertEqual(child.stdout.readline().strip(), 'STARTED')
            child.send_signal(signal.SIGTERM)
            out, err = child.communicate(timeout=5)
            self.assertEqual(child.returncode, 0, err)
            self.assertEqual(json.loads(out)['status'], 'FAILED')
            self.assertEqual(tasks.read_report(plan['id'])['failure'], 'terminated')
        finally:
            if child.poll() is None: child.kill(); child.wait(timeout=5)
            child.stdout.close(); child.stderr.close()


class InstallationRecoveryTests(unittest.TestCase):
    def test_legacy_launcher_migration_preserves_state_and_can_rollback(self):
        import shlex, tempfile, zipfile
        with tempfile.TemporaryDirectory() as d, patch.dict(os.environ, {'HOME': d}, clear=True):
            root = Path(d).resolve()
            app = config.private_directory(config.app_home())
            old_dir = config.private_directory(config.private_directory(app / 'releases') / '1.0.0')
            old = old_dir / 'deepseek-reviewer.pyz'
            new = root / 'candidate.pyz'
            for path, version in [(old, '1.0.0'), (new, '1.0.1')]:
                with zipfile.ZipFile(path, 'w') as z:
                    z.writestr('deepseek_reviewer/release.json', json.dumps({'version': version}))
                    z.writestr('__main__.py', 'print(' + repr(version) + ')')
                path.chmod(0o600)
            old_hash = hashlib.sha256(old.read_bytes()).hexdigest()
            new_hash = hashlib.sha256(new.read_bytes()).hexdigest()
            config.atomic_write(app / 'installation.json', json.dumps(
                {'version': '1.0.0', 'sha256': old_hash, 'previous': None}).encode())
            command = root / '.local/bin/deepseek-reviewer'
            command.parent.mkdir(parents=True)
            config.atomic_write(command, ('#!/bin/sh\nexec ' + shlex.join(
                [str(Path(sys.executable).resolve()), str(old)]) + ' "$@"\n').encode(), 0o700)
            preserved = {'runtime.json': b'{"synthetic":"registration"}',
                         'reviews/synthetic/report.json': b'{"synthetic":"evidence"}'}
            for name, body in preserved.items():
                (app / name).parent.mkdir(parents=True, exist_ok=True)
                config.atomic_write(app / name, body)
            write = distribution.atomic_write
            def fail_state(path, body, mode):
                if Path(path).name == 'installation.json': raise OSError('synthetic disk failure')
                return write(path, body, mode)
            with patch.object(distribution, 'atomic_write', side_effect=fail_state):
                with self.assertRaises(OSError): distribution.install_archive(new, '1.0.1', new_hash)
            self.assertEqual(subprocess.check_output([str(command)], timeout=5).strip(), b'1.0.0')
            distribution.install_archive(new, '1.0.1', new_hash)
            self.assertEqual(subprocess.check_output([str(command)], timeout=5).strip(), b'1.0.1')
            distribution.rollback()
            self.assertEqual(subprocess.check_output([str(command)], timeout=5).strip(), b'1.0.0')
            for name, body in preserved.items(): self.assertEqual((app / name).read_bytes(), body)

    def test_state_write_failure_keeps_previous_executable_and_rollback(self):
        import os, tempfile, zipfile
        with tempfile.TemporaryDirectory() as d, patch.dict(os.environ, {'HOME': d}, clear=True):
            root = Path(d).resolve()
            def archive(version):
                path = root / (version + '.pyz')
                with zipfile.ZipFile(path, 'w') as z:
                    z.writestr('deepseek_reviewer/release.json', json.dumps({'version': version}))
                    z.writestr('__main__.py', 'print(' + repr(version) + ')')
                return path, version, hashlib.sha256(path.read_bytes()).hexdigest()
            first = distribution.install_archive(*archive('1.0.0'))
            args = archive('1.0.1')
            write = distribution.atomic_write
            def interrupted(path, body, mode):
                if Path(path).name == 'installation.json': raise OSError('synthetic disk failure')
                return write(path, body, mode)
            with patch.object(distribution, 'atomic_write', side_effect=interrupted):
                with self.assertRaises(OSError): distribution.install_archive(*args)
            self.assertEqual(subprocess.check_output([first['command']]).decode().strip(), '1.0.0')
            self.assertEqual(json.loads((config.app_home() / 'installation.json').read_text())['version'], '1.0.0')
            distribution.install_archive(*args)
            distribution.install_archive(*args)  # Reinstall must not destroy rollback history.
            distribution.rollback()
            self.assertEqual(subprocess.check_output([first['command']]).decode().strip(), '1.0.0')
            command = Path(first['command'])
            command.write_text('#!/bin/sh\nprintf custom\n')
            with self.assertRaisesRegex(AgentStopped, 'existing_unmanaged_command'):
                distribution.install_archive(*args)
            self.assertEqual(command.read_text(), '#!/bin/sh\nprintf custom\n')

    def test_first_install_interruption_is_recoverable_with_same_verified_archive(self):
        import tempfile, zipfile
        with tempfile.TemporaryDirectory() as d, patch.dict(os.environ, {'HOME': d}, clear=True):
            archive = Path(d).resolve() / 'product.pyz'
            with zipfile.ZipFile(archive, 'w') as z:
                z.writestr('deepseek_reviewer/release.json', '{"version":"1.0.0"}')
                z.writestr('__main__.py', 'print("1.0.0")')
            digest = hashlib.sha256(archive.read_bytes()).hexdigest()
            write = distribution.atomic_write
            def fail_state(path, body, mode):
                if Path(path).name == 'installation.json': raise OSError('synthetic disk failure')
                return write(path, body, mode)
            with patch.object(distribution, 'atomic_write', side_effect=fail_state):
                with self.assertRaises(OSError): distribution.install_archive(archive, '1.0.0', digest)
            command = config.home() / '.local/bin/deepseek-reviewer'
            failed = subprocess.run([str(command)], capture_output=True, timeout=5)
            self.assertNotEqual(failed.returncode, 0)
            self.assertNotIn(b'1.0.0', failed.stdout)
            distribution.install_archive(archive, '1.0.0', digest)
            self.assertEqual(subprocess.check_output([str(command)]).decode().strip(), '1.0.0')
