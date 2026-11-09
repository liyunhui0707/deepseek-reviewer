"""Report delivery regressions: synthetic children only, never paid requests."""
import copy
import json
import unittest

from deepseek_reviewer import cli, prepare, runner, tasks
import test_review_delivery as delivery_tests
from test_review_delivery import CHECKPOINT, message, checkpoint_event


REVIEW = {**CHECKPOINT, 'schema': 2,
          'assessment': 'The total is incremented instead of returned unchanged.',
          'reviewed_files': ['price.py']}


def read_events():
    return [
        {'type': 'assistant', 'message': {'id': 'read-response', 'model': 'deepseek-flash',
            'content': [{'type': 'tool_use', 'id': 'r1', 'name': 'Read',
                         'input': {'file_path': 'price.py'}}]}},
        {'type': 'user', 'message': {'content': [
            {'type': 'tool_result', 'tool_use_id': 'r1', 'content': '2 return n + 1'}]}}]


def final_event(value):
    return {'type': 'result', 'subtype': 'success', 'is_error': False,
            'result': '```review-report\n' + json.dumps(value) + '\n```'}


class ReportContractTests(unittest.TestCase):
    capture = delivery_tests.DeliveryTests.capture

    def summarize(self, events, **kwargs):
        result = self.capture(events, **kwargs)
        return tasks.summarize(result, ['price.py', 'test_price.py'], True, require_report=True)

    def test_progress_only_success_is_not_a_delivered_review(self):
        report = self.summarize([*read_events(), {'type': 'result', 'subtype': 'success',
            'is_error': False, 'result': 'I will now inspect the remaining files.'}])
        self.assertEqual(report['status'], 'FAILED')
        self.assertEqual(report['stop_reason'], 'invalid_review_report')
        self.assertIsNone(report['findings'])

    def test_equivalent_final_json_wrappers_preserve_the_same_review(self):
        body = json.dumps(REVIEW)
        for text, envelope in [
            (body, 'bare_json'),
            ('```json\n' + body + '\n```', 'json_fence'),
            ('```review-checkpoint\n' + body + '\n```', 'checkpoint_fence'),
            ('Final review:\r\n```review-report\r\n' + body + '\r\n```\r\n', 'review_report_fence'),
            ('Final review:\n  ```json  \n' + body + '\n  ```  \nDone.', 'json_fence')]:
            with self.subTest(envelope=envelope, text=text[:20]):
                event = {**final_event(REVIEW), 'result': text}
                report = self.summarize([*read_events(), event])
                self.assertEqual(report['status'], 'COMPLETED')
                self.assertEqual(report['review'], REVIEW)
                self.assertEqual(report['final_report_diagnostic'], {
                    'status': 'accepted', 'stage': 'complete', 'reason': None, 'envelope': envelope})

    def test_final_rejection_records_fixed_reason_without_raw_content(self):
        body = json.dumps(REVIEW)
        cases = [
            ('I will inspect more files.', 'missing_report_object', 'envelope'),
            ('```json\n' + body, 'incomplete_fence', 'envelope'),
            ('```python\n' + body + '\n```', 'unsupported_fence', 'envelope'),
            ('```review-report\n' + body + '\n```\n```json\n' + body + '\n```',
             'multiple_fences', 'envelope'),
            ('{"schema": 2, "assessment": "private malformed prose"', 'invalid_json', 'json'),
            (body.replace('"schema": 2', '"schema": 2, "schema": 2'), 'duplicate_key', 'json'),
            (body.replace('"schema": 2', '"schema": NaN'), 'nonfinite_number', 'json'),
            (json.dumps({**REVIEW, 'schema': 1}), 'unsupported_schema', 'schema'),
            (json.dumps({**REVIEW, 'assessment': ' '}), 'invalid_schema_or_values', 'schema'),
            (json.dumps({**REVIEW, 'reviewed_files': ['test_price.py']}), 'unobserved_read', 'evidence'),
            ('x' * 32769, 'report_too_large', 'input'),
        ]
        for text, reason, stage in cases:
            with self.subTest(reason=reason):
                report = self.summarize([*read_events(), {**final_event(REVIEW), 'result': text}])
                self.assertEqual(report['status'], 'FAILED')
                self.assertEqual(report['stop_reason'], 'invalid_review_report')
                diagnostic = report['final_report_diagnostic']
                self.assertEqual(diagnostic['status'], 'rejected')
                self.assertEqual(diagnostic['reason'], reason)
                self.assertEqual(diagnostic['stage'], stage)
                self.assertEqual(set(diagnostic), {'status', 'stage', 'reason', 'envelope'})
                self.assertNotIn('private malformed prose', json.dumps(report))
                self.assertIn('Final report validation: ' + stage + '/' + reason, cli.render(report))

    def test_legacy_label_in_terminal_success_does_not_override_completion_evidence(self):
        report = self.summarize([*read_events(), checkpoint_event(REVIEW),
            {**final_event(REVIEW), 'result': checkpoint_event(REVIEW)['message']['content'][0]['text']}])
        self.assertEqual(report['status'], 'COMPLETED')
        self.assertEqual(report['delivery'], 'FINAL')
        self.assertEqual(report['review'], REVIEW)
        self.assertEqual(report['partial_review'], REVIEW)
        self.assertEqual(report['final_report_diagnostic']['status'], 'accepted')
        self.assertTrue(report['observation']['final_report_available'])

    def test_success_does_not_substitute_earlier_artifact_for_missing_or_invalid_terminal_report(self):
        for text in ('', 'Done.', '{"schema":2}'):
            with self.subTest(text=text):
                report = self.summarize([*read_events(), message(final_event(REVIEW)['result']),
                    {**final_event(REVIEW), 'result': text}])
                self.assertEqual(report['status'], 'PARTIAL')
                self.assertEqual(report['partial_review'], REVIEW)
                self.assertTrue(report['partial_review_stale'])
                self.assertIsNone(report['review'])
                self.assertIsNone(report['findings'])
                self.assertFalse(report['observation']['final_report_available'])

    def test_terminal_revision_supersedes_earlier_artifact(self):
        revised = {**REVIEW, 'findings': [], 'assessment': 'Earlier hypothesis withdrawn after verification.'}
        report = self.summarize([*read_events(), checkpoint_event(REVIEW),
            {**final_event(revised), 'result': checkpoint_event(revised)['message']['content'][0]['text']}])
        self.assertEqual(report['status'], 'COMPLETED')
        self.assertEqual(report['review'], revised)
        self.assertEqual(report['partial_review'], REVIEW)
        self.assertNotIn(REVIEW['findings'][0]['explanation'], report['findings'])

    def test_nonzero_exit_keeps_valid_terminal_content_only_as_partial(self):
        report = self.summarize([*read_events(), final_event(REVIEW)], tail='sys.exit(1)')
        self.assertEqual(report['status'], 'PARTIAL')
        self.assertEqual(report['stop_reason'], 'process_nonzero')
        self.assertEqual(report['partial_review'], REVIEW)
        self.assertEqual(report['delivery'], 'PARTIAL')
        self.assertIsNone(report['findings'])
        self.assertIsNone(report['review'])
        self.assertFalse(report['observation']['final_report_available'])

    def test_new_prompt_uses_one_report_format_throughout(self):
        task = prepare.build_review_task(objective='One risk', revision='synthetic',
            approved_files=['price.py'], required_files=[], constraints='Read only',
            test_evidence='No tests run', timeout=10, max_turns=4, max_budget_usd=.1,
            max_output_tokens=1800)
        self.assertIn('```review-report\n', task)
        self.assertNotIn('review-checkpoint', task)
        self.assertIn('terminal response', task)

    def test_empty_and_non_text_results_are_diagnosed_without_accepting_an_artifact(self):
        for text, reason in [(' \n ', 'empty_result'), (None, 'non_text_result')]:
            event = {**final_event(REVIEW), 'result': text, 'structured_output': REVIEW}
            report = self.summarize([*read_events(), event])
            self.assertEqual(report['status'], 'FAILED')
            self.assertEqual(report['final_report_diagnostic']['reason'], reason)
            self.assertFalse(report['observation']['final_report_available'])
            self.assertIsNone(report['review'])

    def test_json_fence_does_not_bypass_scope_schema_or_secret_checks(self):
        invalid = [
            {**REVIEW, 'reviewed_files': ['../private.py']},
            {**REVIEW, 'reviewed_files': ['test_price.py']},
            {**REVIEW, 'assessment': '/Users/synthetic/personal-file'},
            {**REVIEW, 'thinking': 'hidden reasoning must not be persisted'},
            {**REVIEW, 'assessment': 'password=' + 'fake-private-value-only'},
        ]
        for label in ('json', 'review-checkpoint'):
            for value in invalid:
                event = {**final_event(REVIEW), 'result': '```' + label + '\n' + json.dumps(value) + '\n```'}
                report = self.summarize([*read_events(), event])
                self.assertEqual(report['status'], 'FAILED')
                self.assertIsNone(report['findings'])
                self.assertIsNone(report['review'])
                for forbidden in ('fake-private-value-only', '/Users/synthetic', 'hidden reasoning must'):
                    self.assertNotIn(forbidden, json.dumps(report))

    def test_secret_final_output_has_no_diagnostic_fragment_or_fingerprint(self):
        text = json.dumps({**REVIEW, 'assessment': 'authorization=' + 'fake-private-value-only'})
        report = self.summarize([*read_events(), {**final_event(REVIEW), 'result': text}])
        self.assertEqual(report['status'], 'FAILED')
        self.assertTrue(report['credential_like_report_withheld'])
        self.assertEqual(report['final_report_diagnostic'], {
            'status': 'rejected', 'stage': 'content', 'reason': 'sensitive_content', 'envelope': 'not_inspected'})
        self.assertNotIn('fake-private-value-only', json.dumps(report))

    def test_error_or_incomplete_execution_never_accepts_a_fenced_final(self):
        error = {**final_event(REVIEW), 'subtype': 'error_max_budget_usd', 'is_error': True}
        report = self.summarize([*read_events(), error], tail='sys.exit(1)')
        self.assertEqual(report['status'], 'FAILED')
        self.assertIsNone(report['review'])
        self.assertEqual(report['final_report_diagnostic']['status'], 'not_checked')
        # A final-looking assistant message followed by timeout stays partial.
        report = self.summarize([*read_events(), message(final_event(REVIEW)['result'])],
            tail='time.sleep(5)', timeout=.3)
        self.assertEqual(report['status'], 'PARTIAL')
        self.assertIsNone(report['review'])
        self.assertEqual(report['final_report_diagnostic']['status'], 'not_checked')

    def test_report_with_no_defects_is_valid_only_with_assessment_and_read_evidence(self):
        value = {**REVIEW, 'findings': [], 'assessment': 'No defect supported by the inspected function.'}
        report = self.summarize([*read_events(), final_event(value)])
        self.assertEqual(report['status'], 'COMPLETED')
        self.assertEqual(report['review'], value)
        self.assertIn(value['assessment'], report['findings'])
        for invalid in ({**value, 'assessment': ''}, {**value, 'reviewed_files': ['test_price.py']},
                        {**value, 'reviewed_files': []}):
            with self.subTest(invalid=invalid):
                self.assertEqual(self.summarize([*read_events(), final_event(invalid)])['status'], 'FAILED')

    def test_failed_execution_can_keep_opinion_but_cannot_complete(self):
        for subtype in ('error_max_budget_usd', 'error_max_turns'):
            report = self.summarize([*read_events(), checkpoint_event(REVIEW),
                {'type': 'result', 'subtype': subtype, 'is_error': True}], tail='sys.exit(1)')
            self.assertEqual(report['status'], 'PARTIAL')
            self.assertEqual(report['partial_review'], REVIEW)
            self.assertEqual(report['stop_reason'], subtype)

    def test_assistant_report_is_kept_when_client_budget_replaces_final_result(self):
        for text in (final_event(REVIEW)['result'], json.dumps(REVIEW),
                     '```json\r\n' + json.dumps(REVIEW) + '\r\n```',
                     '  ```review-report  \n' + json.dumps(REVIEW) + '\n  ```  ',
                     'Review complete:\n' + final_event(REVIEW)['result'] + '\nEnd of public report.'):
            report = self.summarize([*read_events(), message(text),
                {'type': 'result', 'subtype': 'error_max_budget_usd', 'is_error': True}], tail='sys.exit(1)')
            self.assertEqual(report['status'], 'PARTIAL')
            self.assertEqual(report['partial_review'], REVIEW)
            self.assertIsNone(report['findings'])

    def test_ambiguous_assistant_blocks_do_not_replace_a_valid_artifact(self):
        text = final_event(REVIEW)['result'] + '\n```json\n{"phase":"reading"}\n```'
        report = self.summarize([*read_events(), checkpoint_event(REVIEW), message(text)])
        self.assertEqual(report['status'], 'PARTIAL')
        self.assertEqual(report['partial_review'], REVIEW)
        self.assertTrue(report['partial_review_stale'])
        self.assertEqual(report['observation']['checkpoints_rejected'], 1)

    def test_thinking_is_observed_as_metadata_never_delivered_as_opinion(self):
        report = self.summarize([*read_events(), message(final_event(REVIEW)['result'], kind='thinking'),
            {'type': 'result', 'subtype': 'error_max_budget_usd', 'is_error': True}])
        self.assertEqual(report['status'], 'FAILED')
        self.assertTrue(report['observation']['thinking_content_observed'])
        self.assertIsNone(report['partial_review'])

    def test_unrelated_json_does_not_erase_a_public_review(self):
        for text in ('{"phase":"reading","next":"inspect tests"}', '```json\n{"phase":"reading"}\n```'):
            report = self.summarize([*read_events(), checkpoint_event(REVIEW), message(text)])
            self.assertEqual(report['partial_review'], REVIEW)
            self.assertEqual(report['observation']['checkpoints_rejected'], 0)
            self.assertFalse(report['partial_review_stale'])

    def test_bad_revision_preserves_only_safe_prior_artifact_with_warning(self):
        for text, category in [
            ('```review-report\n{"schema":\n```', 'format'),
            (final_event({**REVIEW, 'reviewed_files': ['test_price.py']})['result'], 'validation'),
            (final_event({**REVIEW, 'assessment': 'password=syntheticcredentialonly'})['result'], 'sensitive_content')]:
            with self.subTest(category=category):
                report = self.summarize([*read_events(), checkpoint_event(REVIEW), message(text)])
                self.assertEqual(report['status'], 'PARTIAL')
                self.assertEqual(report['partial_review'], REVIEW)
                self.assertTrue(report['partial_review_stale'])
                self.assertEqual(report['observation']['checkpoint_revision_error'], category)
                self.assertNotIn('syntheticcredentialonly', json.dumps(report))

    def test_valid_explicit_retraction_replaces_prior_opinion(self):
        withdrawn = {**REVIEW, 'assessment': 'Earlier finding withdrawn after checking context.', 'findings': []}
        report = self.summarize([*read_events(), checkpoint_event(REVIEW),
            message('```review-report\n{"schema":\n```'), checkpoint_event(withdrawn)])
        self.assertEqual(report['partial_review'], withdrawn)
        self.assertFalse(report['partial_review_stale'])
        self.assertIsNone(report['observation']['checkpoint_revision_error'])

    def test_malformed_or_secret_report_is_withheld_even_with_exit_zero(self):
        for field, value in [('assessment', 'password=syntheticcredentialonly'),
                             ('reviewed_files', ['../private.py']), ('schema', 9)]:
            data = copy.deepcopy(REVIEW); data[field] = value
            report = self.summarize([*read_events(), final_event(data)])
            self.assertEqual(report['status'], 'FAILED')
            self.assertIsNone(report['findings'])
            self.assertNotIn('syntheticcredentialonly', json.dumps(report))

    def test_repeated_tool_responses_can_reach_report_without_early_stop(self):
        events = [*read_events(), message('Still reading', response_id='r2'),
                  message('Still reading', response_id='r2'), message('Still reading', response_id='r3'),
                  message('Still verifying', response_id='r4'), final_event(REVIEW)]
        report = self.summarize(events)
        self.assertEqual(report['status'], 'COMPLETED')
        self.assertEqual(report['observation']['model_responses_observed'], 4)

    def test_no_opinion_still_stops_at_original_timeout(self):
        report = self.summarize([*read_events()], tail='time.sleep(5)', timeout=.3)
        self.assertEqual(report['stop_reason'], 'timeout')
        self.assertEqual(report['status'], 'FAILED')
        self.assertTrue(report['cleanup']['child_reaped'])
        self.assertLess(report['duration_seconds'], 2)

    def test_public_checkpoint_survives_timeout_without_promoting_thinking(self):
        report = self.summarize([*read_events(), checkpoint_event(REVIEW)],
            tail='time.sleep(5)', timeout=.4)
        self.assertEqual(report['status'], 'PARTIAL')
        self.assertEqual(report['stop_reason'], 'timeout')
        self.assertEqual(report['partial_review'], REVIEW)

    def test_unread_checkpoint_is_rejected_without_claiming_delivery(self):
        value = {**REVIEW, 'reviewed_files': ['test_price.py']}
        report = self.summarize([*read_events(), checkpoint_event(value)])
        self.assertEqual(report['stop_reason'], 'missing_result')
        self.assertIsNone(report['partial_review'])
        self.assertEqual(report['observation']['checkpoint_revision_error'], 'validation')

    def test_duplicate_report_keys_and_whitespace_assessment_fail_closed(self):
        event = final_event(REVIEW)
        event['result'] = event['result'].replace('"schema": 2', '"schema": 2, "schema": 2')
        for value in (event, final_event({**REVIEW, 'assessment': '  '})):
            self.assertEqual(self.summarize([*read_events(), value])['status'], 'FAILED')

    def test_unsafe_execution_never_exposes_an_accepted_report(self):
        result = self.capture([*read_events(), final_event(REVIEW)])
        for changed in ('snapshot', 'tools', 'model', 'cleanup'):
            item = copy.deepcopy(result)
            if changed == 'tools': item['claude']['unexpected_init_tools'] = True
            if changed == 'model': item['claude']['models_observed'] = ['unrecognized']
            if changed == 'cleanup': item['cleanup']['completed'] = False
            report = tasks.summarize(item, ['price.py'], changed != 'snapshot', require_report=True)
            self.assertEqual(report['status'], 'FAILED')
            self.assertIsNone(report['findings'])
            self.assertIsNone(report['review'])



if __name__ == '__main__': unittest.main()
