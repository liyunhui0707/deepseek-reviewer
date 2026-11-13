"""Reusable disclosure consent; synthetic files/processes only, no credentials."""
import contextlib
import io
import json
from pathlib import Path
import unittest
from unittest.mock import patch

import test_product
from deepseek_reviewer import cli, config, consent, tasks
from deepseek_reviewer.runner import AgentStopped
from deepseek_reviewer.safety import ReviewError


class ConsentTests(unittest.TestCase):
    setUp = test_product.PortableTests.setUp
    tearDown = test_product.PortableTests.tearDown

    def enable(self, **kwargs):
        with contextlib.redirect_stderr(io.StringIO()), patch('sys.stdin.isatty', return_value=True), \
                patch('sys.stderr.isatty', return_value=True), patch('builtins.input', return_value='AUTHORIZE'):
            return consent.enable(self.repo, files=kwargs.pop('files', ['price.py', 'test_price.py']),
                                  directories=kwargs.pop('directories', []), profile='quick', **kwargs)

    def plan(self, **kwargs):
        return tasks.create_plan(self.repo, kwargs.pop('names', ['price.py', 'test_price.py']),
            'Inspect synthetic calculation', 'synthetic', 'static only', 'none',
            kwargs.pop('limits', self.limits), profile='quick', use_consent=True, **kwargs)

    def test_enable_requires_terminal_confirmation_and_never_retrieves_credentials(self):
        with patch('sys.stdin.isatty', return_value=False), patch.object(config, 'credentials') as key:
            with self.assertRaisesRegex(AgentStopped, 'consent_requires_terminal'):
                consent.enable(self.repo, files=['price.py'], directories=[], profile='quick')
            key.assert_not_called()
        with contextlib.redirect_stderr(io.StringIO()), patch('sys.stdin.isatty', return_value=True), \
                patch('sys.stderr.isatty', return_value=True), patch('builtins.input', return_value='no'):
            with self.assertRaisesRegex(AgentStopped, 'consent_cancelled'):
                consent.enable(self.repo, files=['price.py'], directories=[], profile='quick')
        self.assertEqual(consent.status(self.repo)['status'], 'NOT_CONFIGURED')

    def test_scope_preview_and_private_storage(self):
        value = self.enable()
        self.assertEqual(value['status'], 'ENABLED')
        self.assertEqual(value['policy']['limits'], tasks.PROFILES['quick'])
        self.assertEqual(value['policy']['endpoint'], config.ENDPOINT)
        path = consent.policy_path(self.repo)
        self.assertEqual(path.stat().st_mode & 0o777, 0o600)
        self.assertEqual(path.parent.stat().st_mode & 0o777, 0o700)
        self.assertEqual(consent.status(self.repo)['sha256'], value['sha256'])
        path.chmod(0o644)
        with self.assertRaisesRegex(AgentStopped, 'unsafe_private_file'):
            consent.status(self.repo)

    def test_matching_consent_plan_offline_and_synthetic_execution_once(self):
        receipt = self.enable()
        with patch.object(tasks, 'run_bounded') as launch:
            plan = self.plan()
            launch.assert_not_called()
        self.assertEqual(plan['consent']['sha256'], receipt['sha256'])
        report = tasks.execute_plan(plan['plan'], plan['sha256'], use_consent=True)
        self.assertEqual(report['status'], 'COMPLETED')
        with self.assertRaisesRegex(AgentStopped, 'attempt_consumed'):
            tasks.execute_plan(plan['plan'], plan['sha256'], use_consent=True)

    def test_missing_revoked_changed_and_regranted_policy_stop_before_attempt(self):
        with self.assertRaisesRegex(AgentStopped, 'consent_missing'):
            self.plan()
        self.enable()
        plan = self.plan()
        for mutate in (lambda: consent.revoke(self.repo), self.enable):
            mutate()
            for use in (True, False):
                with patch.object(tasks, 'prepare_claude_review') as prepare, patch.object(tasks, 'run_bounded') as launch:
                    with self.assertRaisesRegex(AgentStopped, 'consent_(revoked|changed)'):
                        tasks.execute_plan(plan['plan'], plan['sha256'], use_consent=use)
                    prepare.assert_not_called(); launch.assert_not_called()
            self.assertFalse((Path(plan['plan']).parent / 'execution').exists())

    def test_manual_plan_cannot_claim_standing_consent(self):
        plan = test_product.PortableTests.plan(self)
        self.enable()
        with patch.object(tasks, 'run_bounded') as launch:
            with self.assertRaisesRegex(AgentStopped, 'consent_plan_required'):
                tasks.execute_plan(plan['plan'], plan['sha256'], use_consent=True)
            launch.assert_not_called()
        self.assertEqual(tasks.execute_plan(plan['plan'], plan['sha256'])['status'], 'COMPLETED')

    def test_exact_files_directory_boundary_and_protected_materials(self):
        (self.repo / 'src').mkdir(); (self.repo / 'src-other').mkdir()
        (self.repo / 'src/ok.py').write_text('synthetic')
        (self.repo / 'src-other/no.py').write_text('synthetic')
        self.enable(files=['price.py'], directories=['src'])
        self.plan(names=['src/ok.py'])
        for name in ['test_price.py', 'src-other/no.py', '../price.py', str(self.repo / 'price.py')]:
            with self.subTest(name=name), self.assertRaises((AgentStopped, ReviewError)):
                self.plan(names=[name])
        (self.repo / 'src/link.py').symlink_to(self.repo / 'test_price.py')
        (self.repo / 'src/.env').write_text('synthetic only')
        (self.repo / 'src/sensitive.py').write_text('sk-' + 'S' * 24)
        for name in ['src/link.py', 'src/.env', 'src/sensitive.py']:
            with self.subTest(name=name), self.assertRaises(ReviewError):
                self.plan(names=[name])

    def test_limits_size_and_file_count_cannot_expand(self):
        self.enable(files=[], directories=['src'])
        (self.repo / 'src').mkdir()
        (self.repo / 'src/a').write_text('x' * (48 * 1024 + 1))
        with self.assertRaisesRegex(AgentStopped, 'consent_scope_exceeded'):
            self.plan(names=['src/a'])
        for i in range(7): (self.repo / f'src/{i}').write_text('synthetic')
        with self.assertRaisesRegex(AgentStopped, 'consent_scope_exceeded'):
            self.plan(names=[f'src/{i}' for i in range(7)])
        for field, value in [('max_budget_usd', .26), ('timeout', 181), ('max_turns', 9),
                             ('max_output_tokens', 4001), ('effort', None)]:
            with self.subTest(field=field), self.assertRaisesRegex(AgentStopped, 'consent_limits_exceeded'):
                self.plan(names=['src/0'], limits={**self.limits, field: value})

    def test_invalid_scope_root_policy_and_links_fail_closed(self):
        for name in ['.', '../src', '/src', '.env', 'secrets', 'src/*']:
            with self.subTest(name=name), self.assertRaises((ReviewError, AgentStopped)):
                self.enable(files=[], directories=[name])
        for root in [self.root, self.root.parent, Path('/')]:
            with self.assertRaisesRegex(AgentStopped, 'consent_root'):
                consent.status(root)
        self.enable()
        path = consent.policy_path(self.repo)
        original = path.read_bytes()
        for change in [{'endpoint': 'https://example.invalid'}, {'limits': {}}, {'unexpected': True}, {'enabled': 'yes'}]:
            path.write_text(json.dumps({**json.loads(original), **change}))
            with self.assertRaisesRegex(AgentStopped, 'consent_invalid'):
                consent.status(self.repo)
        path.write_bytes(original)
        backup = path.with_suffix('.backup'); path.rename(backup); path.symlink_to(backup)
        with self.assertRaises(AgentStopped): consent.status(self.repo)

    def test_revocation_is_recorded_and_does_not_remove_reports_or_credentials(self):
        self.enable()
        plan = self.plan()
        with patch.object(config, 'credentials') as key:
            self.assertEqual(consent.revoke(self.repo)['status'], 'REVOKED')
            key.assert_not_called()
        self.assertTrue(Path(plan['plan']).exists())
        self.assertFalse(json.loads(consent.policy_path(self.repo).read_text())['enabled'])

    def test_launch_rechecks_snapshot_size_before_credentials_or_process(self):
        self.enable()
        plan = self.plan()
        path = Path(plan['plan'])
        value = json.loads(path.read_bytes())
        value['bytes'] = 0
        path.write_bytes(tasks.encode(value))
        with patch.object(tasks, 'prepare_claude_review') as prepare, patch.object(tasks, 'run_bounded') as launch:
            with self.assertRaisesRegex(AgentStopped, 'consent_invalid'):
                tasks.execute_plan(path, tasks.digest(path.read_bytes()), use_consent=True)
            prepare.assert_not_called(); launch.assert_not_called()

    def test_cli_uses_consent_without_second_confirmation(self):
        self.enable()
        plan = self.plan()
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()), \
                patch('builtins.input', side_effect=AssertionError('unexpected confirmation')):
            result = cli.main(['review', '--plan', plan['plan'], '--plan-sha256', plan['sha256'], '--use-consent', '--json'])
        self.assertEqual(result, 0)
        self.assertEqual(json.loads(out.getvalue())['status'], 'COMPLETED')

    def test_replaced_project_directory_requires_new_consent(self):
        self.enable()
        self.repo.rename(self.root / 'original-synthetic-repo')
        self.repo.mkdir()
        with self.assertRaisesRegex(AgentStopped, 'consent_invalid'):
            consent.status(self.repo)

    def test_cli_consent_profile_is_used_and_manual_default_unchanged(self):
        self.enable()
        args = ['prepare', '--root', str(self.repo), '--file', 'price.py', '--question', 'Synthetic review', '--json']
        for flags, expected in [([], 'standard'), (['--use-consent'], 'quick')]:
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                self.assertEqual(cli.main(args + flags), 0)
            plan = json.loads(output.getvalue())
            self.assertEqual(plan['profile'], expected)
            self.assertEqual(plan['limits'], tasks.PROFILES[expected])
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(cli.main(args + ['--use-consent', '--profile', 'standard']), 1)

    def test_policy_update_cannot_overlap_review(self):
        self.enable()
        with config.state_lock(shared=True):
            with self.assertRaisesRegex(AgentStopped, 'state_busy'):
                consent.revoke(self.repo)
