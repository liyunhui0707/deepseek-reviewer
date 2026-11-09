"""Delivery failures reproduced using synthetic subprocesses; no Claude/Keychain."""
import copy
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

from deepseek_reviewer import cli, distribution, runner, tasks
from deepseek_reviewer.runner import AgentStopped
import test_product

CHECKPOINT = {'schema': 1, 'findings': [{
    'kind': 'finding', 'severity': 'P2', 'file': 'price.py', 'line': 2,
    'evidence': 'return n + 1', 'explanation': 'Adds one to the expected total.',
    'suggestion': 'Return n.'}], 'coverage_gaps': ['Associated tests not yet checked.']}


def message(text, kind='text', response_id='response-1'):
    return {'type': 'assistant', 'message': {'id': response_id, 'model': 'deepseek-flash',
            'content': [{'type': kind, 'text' if kind == 'text' else 'thinking': text}]}}


def checkpoint_event(value=CHECKPOINT):
    return message('```review-checkpoint\n' + json.dumps(value) + '\n```')


class DeliveryTests(unittest.TestCase):
    def capture(self, events, tail='', timeout=3, **kwargs):
        events = [{'type': 'system', 'subtype': 'init', 'tools': ['Read', 'Glob', 'Grep']}, *events]
        code = 'import json,time,sys\n'
        code += 'for e in ' + repr(events) + ': print(json.dumps(e), flush=True)\n' + tail
        return runner.run_bounded([sys.executable, '-I', '-S', '-B', '-c', code],
            Path(__file__).parent, {'PATH': '/usr/bin:/bin'}, '', timeout,
            claude_stream_json=True, progress_files=['price.py', 'test_price.py'], **kwargs)

    def report(self, result):
        return tasks.summarize(result, ['price.py', 'test_price.py'], True)

    def test_budget_and_turn_exhaustion_preserve_explicit_partial_review(self):
        for stop in ('error_max_budget_usd', 'error_max_turns'):
            with self.subTest(stop=stop):
                result = self.capture([checkpoint_event(), {'type': 'result', 'subtype': stop,
                    'is_error': True, 'total_cost_usd': 1.027, 'num_turns': 10,
                    'usage': {'input_tokens': 120, 'output_tokens': 90}}], 'sys.exit(1)')
                report = self.report(result)
                self.assertEqual(report['status'], 'PARTIAL')
                self.assertEqual(report['partial_review'], CHECKPOINT)
                self.assertIsNone(report['findings'])
                self.assertEqual(report['stop_reason'], stop)
                self.assertEqual(report['observation']['client_estimated_usd'], 1.027)
                self.assertIsNone(report['observation']['http_requests'])
                self.assertIn('Partial review available', cli.render(report))

    def test_timeout_and_missing_result_keep_complete_checkpoint_not_success(self):
        for tail, stop in [('time.sleep(10)', 'timeout'), ('', 'missing_result')]:
            with self.subTest(stop=stop):
                report = self.report(self.capture([checkpoint_event()], tail, timeout=.3))
                self.assertEqual(report['status'], 'PARTIAL')
                self.assertEqual(report['stop_reason'], stop)
                self.assertIsNone(report['observation']['client_estimated_usd'])
                self.assertFalse(report['observation']['final_report_available'])
                self.assertEqual(report['coverage_observation']['no_successful_read_observed'],
                                 ['price.py', 'test_price.py'])

    def test_success_keeps_final_and_identifies_partial_as_provisional(self):
        report = self.report(self.capture([checkpoint_event(), {'type': 'result', 'subtype': 'success',
                'is_error': False, 'result': 'Final report corrects the early hypothesis.'}]))
        self.assertEqual(report['status'], 'COMPLETED')
        self.assertEqual(report['findings'], 'Final report corrects the early hypothesis.')
        self.assertEqual(report['partial_review'], CHECKPOINT)
        self.assertIn('provisional', cli.render(report))

    def test_error_string_and_unmarked_or_thinking_text_are_not_findings(self):
        for event in (message('PRELIMINARY: let me think through the code'),
                      message('```review-checkpoint\n' + json.dumps(CHECKPOINT) + '\n```', 'thinking'),
                      {'type': 'user', 'message': checkpoint_event()['message']}):
            with self.subTest(event=event):
                report = self.report(self.capture([event, {'type': 'result', 'subtype': 'error_max_budget_usd',
                    'is_error': True, 'result': 'Budget exhausted.'}]))
                self.assertEqual(report['status'], 'FAILED')
                self.assertIsNone(report['findings'])
                self.assertIsNone(report['partial_review'])

    def test_invalid_checkpoints_are_withheld_without_disclosing_their_contents(self):
        invalid = []
        for key, value in [('file', '../private.py'), ('file', 'unapproved.py'), ('line', True),
                           ('explanation', 'api_key=' + 'syntheticcredentialonly'),
                           ('evidence', '/Users/synthetic/private.txt'), ('suggestion', 'x' * 20000)]:
            item = copy.deepcopy(CHECKPOINT); item['findings'][0][key] = value; invalid.append(item)
        invalid.append({**CHECKPOINT, 'thinking': 'private reasoning'})
        for index, item in enumerate(invalid):
            with self.subTest(case=index):
                report = self.report(self.capture([checkpoint_event(item)]))
                self.assertIsNone(report['partial_review'])
                self.assertEqual(report['status'], 'FAILED')
                self.assertEqual(report['observation']['checkpoints_rejected'], 1)
                self.assertNotIn('syntheticcredentialonly', json.dumps(report))

    def test_corrupt_stream_or_unexpected_tools_do_not_deliver_accepted_partial(self):
        for tail, extra in [('print("invalid json", flush=True)', []), ('', [
            {'type': 'assistant', 'message': {'content': [
                {'type': 'tool_use', 'id': 'bad', 'name': 'Bash', 'input': {}}]}}])]:
            report = self.report(self.capture([checkpoint_event(), *extra], tail))
            self.assertEqual(report['status'], 'FAILED')
            self.assertIsNone(report['partial_review'])

    def test_output_limit_does_not_promote_prefix_to_accepted_partial(self):
        report = self.report(self.capture([checkpoint_event()],
            'print(json.dumps({"type":"unknown", "data":"x"*2000}))', max_stdout_bytes=1800))
        self.assertEqual(report['status'], 'FAILED')
        self.assertEqual(report['stop_reason'], 'output_limit')
        self.assertIsNone(report['partial_review'])

    def test_latest_cumulative_checkpoint_is_kept_and_progress_does_not_include_text(self):
        updated = {'schema': 1, 'findings': [], 'coverage_gaps': ['Earlier finding withdrawn; more context needed.']}
        notices = []
        result = self.capture([checkpoint_event(), checkpoint_event(updated)], on_progress=notices.append)
        self.assertEqual(self.report(result)['partial_review'], updated)
        self.assertEqual(result['claude']['checkpoints_observed'], 2)
        self.assertNotIn('Earlier finding', json.dumps(notices))

    def test_partial_usage_deduplicates_response_ids_without_inventing_cost(self):
        first = checkpoint_event()
        first['message']['usage'] = {'input_tokens': 30, 'output_tokens': 8}
        later = copy.deepcopy(first); later['message']['usage']['output_tokens'] = 12
        result = self.capture([first, first, later])
        observation = self.report(result)['observation']
        self.assertEqual(observation['usage'], {'input_tokens': 30, 'output_tokens': 12})
        self.assertEqual(observation['usage_source'], 'observed_responses_partial')
        self.assertEqual(observation['model_responses_observed'], 1)
        self.assertIsNone(observation['client_estimated_usd'])
        final = {'type': 'result', 'subtype': 'success', 'is_error': False, 'result': 'report',
                 'usage': {'input_tokens': 80, 'output_tokens': 18}, 'total_cost_usd': .02}
        final_observation = self.report(self.capture([first, final]))['observation']
        self.assertEqual(final_observation['usage']['input_tokens'], 80)
        self.assertEqual(final_observation['usage_source'], 'result')

    def test_checkpoint_fragment_duplicate_fields_and_unknown_schema_fail_closed(self):
        for content in ('```review-checkpoint\n{"schema":',
                        '```review-checkpoint\n{"schema":1,"schema":1,"findings":[],"coverage_gaps":[]}\n```',
                        '```review-checkpoint\n{"schema":2,"findings":[],"coverage_gaps":[]}\n```'):
            report = self.report(self.capture([message(content)]))
            self.assertEqual(report['status'], 'FAILED')
            self.assertEqual(report['observation']['checkpoints_rejected'], 1)

    def test_changed_snapshot_never_accepts_checkpoint(self):
        result = self.capture([checkpoint_event()])
        report = tasks.summarize(result, ['price.py'], False)
        self.assertEqual(report['status'], 'FAILED')
        self.assertTrue(report['partial_review_withheld'])

    def test_invalid_revision_keeps_prior_artifact_explicitly_stale(self):
        report = self.report(self.capture([checkpoint_event(), checkpoint_event({**CHECKPOINT, 'schema': 2})]))
        self.assertEqual(report['status'], 'PARTIAL')
        self.assertEqual(report['partial_review'], CHECKPOINT)
        self.assertTrue(report['partial_review_stale'])
        self.assertIn('earlier artifact', cli.render(report))

    def test_whitespace_result_is_not_a_report(self):
        report = self.report(self.capture([message('Preparing'), {'type': 'result', 'subtype': 'success',
                                            'is_error': False, 'result': '  \n'}]))
        self.assertEqual(report['status'], 'FAILED')
        self.assertIsNone(report['findings'])
        self.assertFalse(report['observation']['final_report_available'])

    def test_cleanup_error_preserves_original_failure_and_never_completes(self):
        for result_event, expected in [
                ({'type': 'result', 'subtype': 'success', 'is_error': False, 'result': 'Final'}, 'cleanup_failed'),
                ({'type': 'result', 'subtype': 'error_max_budget_usd', 'is_error': True}, 'claude_result_error')]:
            with self.subTest(expected=expected), patch.object(runner.os, 'killpg', side_effect=PermissionError):
                result = self.capture([checkpoint_event(), result_event])
            self.assertEqual(result['failure'], expected)
            self.assertFalse(result['cleanup']['completed'])
            self.assertTrue(result['cleanup']['child_reaped'])
            report = self.report(result)
            self.assertEqual(report['status'], 'FAILED')


class PreparationTests(unittest.TestCase):
    setUp = test_product.PortableTests.setUp
    tearDown = test_product.PortableTests.tearDown
    plan = test_product.PortableTests.plan
    def test_profiles_keep_standard_defaults_and_apply_explicit_overrides(self):
        quick = tasks.resolve_limits('quick', {})
        standard = tasks.resolve_limits('standard', {})
        self.assertLess(quick['max_output_tokens'], standard['max_output_tokens'])
        self.assertEqual(standard['max_budget_usd'], .5)
        self.assertEqual(standard['timeout'], 300)
        self.assertEqual(tasks.resolve_limits('quick', {'timeout': 200})['timeout'], 200)
        with self.assertRaises(AgentStopped): tasks.resolve_limits('quick', {'timeout': 601})
        with self.assertRaises(AgentStopped): tasks.resolve_limits('unknown', {})

    def test_focus_and_scope_advice_are_bound_into_plan_without_launch(self):
        with patch.object(tasks, 'run_bounded') as launch:
            plan = tasks.create_plan(self.repo, ['price.py', 'test_price.py'], 'One specific risk', 'r', 'c', 't',
                self.limits, focus_files=['price.py'], profile='quick')
        launch.assert_not_called()
        _, loaded = tasks.load_plan(plan['plan'], plan['sha256'])
        self.assertEqual(loaded['focus_files'], ['price.py'])
        self.assertEqual(loaded['profile'], 'quick')
        self.assertFalse(loaded['delivery']['forced_finalization_supported'])
        self.assertEqual(loaded['delivery']['thinking_requested'], 'disabled')
        self.assertEqual(loaded['delivery']['completion_basis'], 'validated_terminal_result_v1')
        self.assertIsNone(loaded['delivery']['guard'])
        self.assertEqual(loaded['schema'], 2)
        with self.assertRaisesRegex(AgentStopped, 'focus_files'):
            tasks.create_plan(self.repo, ['price.py'], 'q', 'r', 'c', 't', self.limits, focus_files=['missing.py'])

    def test_legacy_skill_conflict_is_visible_without_reading_or_replacing_it(self):
        old = self.root / '.agents/skills/deepseek-review'
        old.mkdir(parents=True)
        (old / 'SKILL.md').write_text('legacy adapter, preserve this customization')
        with patch.object(distribution, 'bundled_skill', return_value={'SKILL.md': b'product'}):
            status = distribution.skill_status()
        self.assertEqual(status['conflicting_skills'], ['~/.agents/skills/deepseek-review'])
        self.assertEqual((old / 'SKILL.md').read_text(), 'legacy adapter, preserve this customization')

    def test_cli_profile_overrides_and_focus_reach_preparation(self):
        import contextlib, io
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(cli.main(['prepare', '--root', str(self.repo), '--file', 'price.py',
                '--question', 'One risk', '--profile', 'quick', '--focus-file', 'price.py',
                '--max-turns', '7', '--effort', 'default', '--json']), 0)
        plan = json.loads(out.getvalue())
        self.assertEqual(plan['limits']['max_turns'], 7)
        self.assertEqual(plan['limits']['max_output_tokens'], 4000)
        self.assertIsNone(plan['limits']['effort'])
        self.assertEqual(plan['focus_files'], ['price.py'])

    def test_scope_advisory_does_not_enlarge_approved_resources(self):
        (self.repo / 'large.py').write_text('# synthetic evidence\n' * 2600)
        plan = tasks.create_plan(self.repo, ['large.py'], 'q', 'r', 'c', 't', self.limits, profile='quick')
        self.assertIn('exceeds profile guidance', plan['delivery']['scope_advisory'])
        self.assertEqual(plan['limits'], self.limits)

    def test_saved_partial_report_is_retrievable_without_relaunch_or_raw_text(self):
        from test_report_contract import read_events, REVIEW
        plan = self.plan()
        result = DeliveryTests().capture([*read_events(), checkpoint_event(REVIEW), {'type': 'result',
            'subtype': 'error_max_budget_usd', 'is_error': True}], 'sys.exit(1)')
        with patch.object(tasks, 'run_bounded', return_value=result) as launch:
            report = tasks.execute_plan(plan['plan'], plan['sha256'])
            saved = tasks.read_report(plan['id'])
            launch.assert_called_once()
        self.assertEqual(saved['status'], 'PARTIAL')
        self.assertEqual(saved['partial_review'], REVIEW)
        serialized = Path(report['report_path']).read_text()
        self.assertNotIn('stdout', serialized)
        self.assertNotIn('"content"', serialized)
        self.assertEqual(Path(report['report_path']).stat().st_mode & 0o777, 0o600)
        with self.assertRaisesRegex(AgentStopped, 'attempt_consumed'):
            tasks.execute_plan(plan['plan'], plan['sha256'])

    def test_saved_format_diagnostic_is_retrievable_without_raw_rejected_text(self):
        from test_report_contract import read_events, final_event, REVIEW
        plan = self.plan()
        result = DeliveryTests().capture([*read_events(), checkpoint_event(REVIEW),
            {**final_event(REVIEW), 'result': '{"assessment": "private malformed prose"'}])
        with patch.object(tasks, 'run_bounded', return_value=result) as launch:
            report = tasks.execute_plan(plan['plan'], plan['sha256'])
            saved = tasks.read_report(plan['id'])
            launch.assert_called_once()
        self.assertEqual(saved['status'], 'PARTIAL')
        self.assertEqual(saved['partial_review'], REVIEW)
        self.assertEqual(saved['final_report_diagnostic']['reason'], 'invalid_json')
        self.assertIn('Final report validation: json/invalid_json', cli.render(saved))
        self.assertNotIn('private malformed prose', Path(report['report_path']).read_text())
        self.assertEqual(Path(report['report_path']).stat().st_mode & 0o777, 0o600)

    def test_setup_does_not_install_competing_skill_or_hide_conflict(self):
        with patch.object(distribution, 'skill_status', return_value={'status': 'NOT_INSTALLED',
                'conflicting_skills': ['~/.agents/skills/deepseek-review']}), \
                patch.object(distribution, 'install_skill') as install:
            result = cli.setup(None)
        self.assertEqual(result['status'], 'ACTION_REQUIRED')
        install.assert_not_called()

    def test_preparation_rejects_oversized_prompt_before_creating_attempt(self):
        from deepseek_reviewer import config
        runs = config.app_home() / 'reviews'
        with self.assertRaisesRegex(AgentStopped, 'review_task_too_large'):
            tasks.create_plan(self.repo, ['price.py'], 'q' * 5850, 'r', 'c', 't', self.limits)
        self.assertFalse(runs.exists())

    def test_older_plan_is_not_silently_reinterpreted(self):
        plan = self.plan()
        path = Path(plan['plan'])
        value = json.loads(path.read_text()); value['schema'] = 1
        raw = tasks.encode(value); path.write_bytes(raw)
        with patch.object(tasks, 'run_bounded') as launch:
            with self.assertRaisesRegex(AgentStopped, 'unsupported_plan'):
                tasks.execute_plan(path, tasks.digest(raw))
        launch.assert_not_called()
        self.assertFalse((path.parent / 'execution').exists())

    def test_withdrawn_guard_plan_is_not_silently_reinterpreted(self):
        plan = self.plan()
        path = Path(plan['plan'])
        value = json.loads(path.read_text())
        value['delivery']['guard'] = {'checkpoint_seconds': 1, 'checkpoint_responses': 2}
        raw = tasks.encode(value); path.write_bytes(raw)
        with patch.object(tasks, 'run_bounded') as launch:
            with self.assertRaisesRegex(AgentStopped, 'unsupported_plan'):
                tasks.execute_plan(path, tasks.digest(raw))
        launch.assert_not_called()
        self.assertFalse((path.parent / 'execution').exists())

    def test_old_fence_based_plan_is_not_silently_reinterpreted(self):
        plan = self.plan()
        path = Path(plan['plan'])
        value = json.loads(path.read_text())
        value['delivery'].pop('completion_basis', None)
        raw = tasks.encode(value); path.write_bytes(raw)
        with patch.object(tasks, 'run_bounded', side_effect=AssertionError('unexpected launch')) as launch:
            with self.assertRaisesRegex(AgentStopped, 'unsupported_plan'):
                tasks.execute_plan(path, tasks.digest(raw))
        launch.assert_not_called()
        self.assertFalse((path.parent / 'execution').exists())

    def test_saved_historical_partial_is_read_without_reclassification(self):
        plan = self.plan()
        path = Path(plan['plan']).parent / 'report.json'
        old = {'status': 'PARTIAL', 'delivery': 'PARTIAL', 'findings': None,
               'final_report_diagnostic': {'status': 'rejected', 'stage': 'envelope',
                    'reason': 'checkpoint_not_final', 'envelope': 'checkpoint_fence'}}
        runner.private_write(path, old)
        before = path.read_bytes()
        with patch.object(tasks, 'run_bounded') as launch:
            report = tasks.read_report(plan['id'])
        launch.assert_not_called()
        self.assertEqual(report, {'report_path': str(path), **old})
        self.assertEqual(path.read_bytes(), before)
