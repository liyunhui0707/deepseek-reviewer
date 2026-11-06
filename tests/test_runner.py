import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
from deepseek_reviewer import runner as a
ROOT = Path(__file__).resolve().parents[1]

class ClaudeCaptureTests(unittest.TestCase):
    """Synthetic Python stdout only; never launches Claude or a model."""

    CHILD = '''import json, sys, time
def emit(value):
    sys.stdout.buffer.write((json.dumps(value, ensure_ascii=False) + '\\n').encode())
    sys.stdout.buffer.flush()
progress = {"type":"system", "subtype":"thinking_tokens", "estimated_tokens":1,
            "estimated_tokens_delta":1, "session_id":"synthetic", "uuid":"progress"}
result = {"type":"result", "subtype":"success", "is_error":False,
          "result":"synthetic findings", "usage":{"output_tokens":12}, "total_cost_usd":0.001}
'''

    HIGH_LIMITS = {'max_stdout_bytes': 4 * 1024 * 1024,
                   'max_stdout_stream_bytes': 64 * 1024 * 1024,
                   'max_jsonl_record_bytes': 1024 * 1024}

    def capture(self, code, *, filtered=True, timeout=5, **limits):
        return a.run_bounded(
            [sys.executable, '-I', '-S', '-B', '-c', self.CHILD + code],
            ROOT, {'PATH': '/usr/bin:/bin'}, '', timeout=timeout,
            **({'claude_stream_json': True} if filtered else {}), **limits)

    def test_opt_in_limits_accept_longer_task_and_larger_evidence(self):
        result = self.capture('''
for _ in range(30000): emit(progress)
emit({"type":"user", "content":"x" * 400000})
emit(result)
''', timeout=600, **self.HIGH_LIMITS)
        self.assertIsNone(result['failure']); self.assertEqual(result['exit_code'], 0)
        self.assertGreater(result['stdout_bytes_received'], 4 * 1024 * 1024)
        self.assertEqual(result['stdout_progress_events_dropped'], 30000)
        events = [json.loads(line) for line in result['stdout'].splitlines()]
        self.assertEqual(events[0], {'type': 'user', 'content': 'x' * 400000})
        self.assertEqual(events[1]['result'], 'synthetic findings')
        # Per-call overrides must not change subsequent callers' defaults.
        old = self.capture('emit({"type":"user", "content":"x" * 400000})\nemit(result)')
        self.assertEqual(old['failure'], 'stdout_line_limit')

    def test_high_limits_still_stop_retained_record_and_stderr_overflow(self):
        for code, expected in [
            ('for _ in range(6): emit({"type":"future_security_event", "data":"x" * 900000})\nemit(result)', 'output_limit'),
            ('emit({"type":"user", "content":"x" * (1024 * 1024)})\nemit(result)', 'stdout_line_limit'),
            ('sys.stderr.buffer.write(b"x" * 270000)\nemit(result)', 'output_limit'),
        ]:
            with self.subTest(expected=expected, code=code):
                result = self.capture(code, **self.HIGH_LIMITS)
                self.assertEqual(result['failure'], expected)
                self.assertIsNotNone(result['exit_code'])
                if not code.startswith('sys.stderr'):
                    self.assertNotIn(b'synthetic findings', result['stdout'])
                self.assertLessEqual(len(result['stdout']), 4 * 1024 * 1024)
                self.assertLessEqual(len(result['stderr']), a.MAX_CAPTURE)

    def test_raw_stream_limit_counts_discarded_progress_and_is_inclusive(self):
        progress = {'type': 'system', 'subtype': 'thinking_tokens', 'estimated_tokens': 1,
                    'estimated_tokens_delta': 1, 'session_id': 'synthetic', 'uuid': 'progress'}
        final = {'type': 'result', 'subtype': 'success', 'is_error': False, 'result': 'ok'}
        wire_size = sum(len((json.dumps(event) + '\n').encode()) for event in (progress, final))
        code = 'emit(progress)\nemit(' + repr(final) + ')'
        accepted = self.capture(code, max_stdout_stream_bytes=wire_size)
        self.assertIsNone(accepted['failure'])
        self.assertEqual(accepted['stdout_bytes_received'], wire_size)
        rejected = self.capture(code, max_stdout_stream_bytes=wire_size - 1)
        self.assertEqual(rejected['failure'], 'stdout_stream_limit')

    def test_high_raw_stream_ceiling_is_still_enforced(self):
        # Exercise the real 64 MiB boundary without a large retained buffer.
        output = bytearray()
        capture = a._ClaudeStreamCapture(output, **self.HIGH_LIMITS)
        event = (json.dumps({'type': 'system', 'subtype': 'thinking_tokens',
                            'estimated_tokens': 1, 'estimated_tokens_delta': 1,
                            'session_id': 'synthetic', 'uuid': 'progress'}) + '\n').encode()
        block = event * (8192 // len(event))
        limit = self.HIGH_LIMITS['max_stdout_stream_bytes']
        while capture.received + len(block) <= limit:
            capture.feed(block)
        with self.assertRaisesRegex(a.AgentStopped, '^stdout_stream_limit$'):
            capture.feed(block)
        self.assertEqual(output, b'')

    def test_invalid_resource_limits_rejected_before_process_creation(self):
        invalid = [{'timeout': value} for value in (0, -1, True, '600', 600.01, float('nan'), float('inf'))]
        for name, ceiling in self.HIGH_LIMITS.items():
            invalid.extend({name: value} for value in (0, -1, True, 1.5, '1024', ceiling + 1))
        invalid.extend({'filtered': False, name: 1024}
                       for name in ('max_stdout_stream_bytes', 'max_jsonl_record_bytes'))
        for kwargs in invalid:
            with self.subTest(kwargs=kwargs), patch.object(a.subprocess, 'Popen') as launch:
                with self.assertRaisesRegex(a.AgentStopped, '^execution_limit$'):
                    self.capture('emit(result)', **kwargs)
                launch.assert_not_called()

    def test_high_capture_limits_keep_timeout_and_final_result_checks(self):
        timed_out = self.capture('emit(progress)\ntime.sleep(10)', timeout=.15, **self.HIGH_LIMITS)
        self.assertEqual(timed_out['failure'], 'timeout')
        self.assertIsNotNone(timed_out['exit_code'])
        self.assertLess(timed_out['duration_seconds'], 3)
        for code, expected in [('emit(progress)', 'missing_result'),
                               ('emit(result)\nsys.stdout.buffer.write(b\'{"type":\')', 'invalid_stdout_json')]:
            with self.subTest(expected=expected):
                self.assertEqual(self.capture(code, **self.HIGH_LIMITS)['failure'], expected)

    def test_old_raw_cap_reproduces_progress_exhaustion(self):
        result = self.capture('for _ in range(1800): emit(progress)\nemit(result)', filtered=False)
        self.assertEqual(result['failure'], 'output_limit')

    def test_progress_flood_preserves_all_evidence_bytes(self):
        events = [
            {'type': 'system', 'subtype': 'init', 'tools': ['Read', 'Glob', 'Grep']},
            {'type': 'assistant', 'message': {'content': [
                {'type': 'tool_use', 'id': 'read-1', 'name': 'Read', 'input': {'file_path': 'synthetic.py'}}]}},
            {'type': 'user', 'message': {'content': [
                {'type': 'tool_result', 'tool_use_id': 'read-1', 'content': '合成\n' + 'x' * 50000}]}},
            {'type': 'system', 'subtype': 'permission_denied', 'message': 'outside synthetic root'},
            {'type': 'future_safety_event', 'details': {'blocked': True}},
        ]
        # Generate the large payload in the child, not in command-line arguments.
        code = 'events = ' + repr(events).replace(repr('合成\n' + 'x' * 50000), "'合成\\n' + 'x' * 50000")
        code += '\nfor event in events: emit(event)\nfor _ in range(1800): emit(progress)\nemit(result)'
        result = self.capture(code)
        self.assertIsNone(result['failure']); self.assertEqual(result['exit_code'], 0)
        expected = b''.join((json.dumps(e, ensure_ascii=False) + '\n').encode() for e in events)
        self.assertTrue(result['stdout'].startswith(expected))
        last = json.loads(result['stdout'].splitlines()[-1])
        self.assertEqual(last['result'], 'synthetic findings')
        self.assertEqual(last['usage'], {'output_tokens': 12})
        self.assertEqual(last['total_cost_usd'], 0.001)
        self.assertEqual(result['stdout_progress_events_dropped'], 1800)
        self.assertGreater(result['stdout_bytes_received'], a.MAX_CAPTURE)
        self.assertEqual(result['stdout_bytes_received'],
                         len(result['stdout']) + result['stdout_progress_bytes_dropped'])

    def test_progress_lookalikes_and_unknown_fields_are_not_discarded(self):
        code = '''
for change in ({"error":"keep this"}, {"estimated_tokens":True},
               {"estimated_tokens":"1"}, {"subtype":"thinking_tokens_v2"},
               {"type":"assistant"}, {"user_message_uuid":42}):
    emit({**progress, **change})
emit({**progress, "user_message_uuid":"synthetic-message"})
emit(result)
'''
        result = self.capture(code)
        self.assertIsNone(result['failure'])
        self.assertEqual(len(result['stdout'].splitlines()), 7)
        self.assertIn(b'keep this', result['stdout'])
        self.assertEqual(result['stdout_progress_events_dropped'], 1)

    def test_chunked_unicode_and_final_event_without_newline(self):
        result = self.capture('''
wire = (json.dumps(progress) + "\\n" + json.dumps({**result, "result":"合成"}, ensure_ascii=False)).encode()
for byte in wire:
    sys.stdout.buffer.write(bytes([byte])); sys.stdout.buffer.flush()
''')
        self.assertIsNone(result['failure'])
        self.assertFalse(result['stdout'].endswith(b'\n'))
        self.assertEqual(json.loads(result['stdout'])['result'], '合成')

    def test_missing_result_is_not_success_even_with_exit_zero(self):
        result = self.capture('emit(progress)')
        self.assertEqual(result['exit_code'], 0)
        self.assertEqual(result['failure'], 'missing_result')

    def test_malformed_truncated_or_ambiguous_json_fails_closed(self):
        for payload, expected in [
            (b'{"type":', 'invalid_stdout_json'),
            (b'{not-json}\n', 'invalid_stdout_json'),
            (b'{"type":"system","type":"result"}\n', 'invalid_stdout_json'),
            (b'{"type":"system","value":NaN}\n', 'invalid_stdout_json'),
            (b'{"type":"system","text":"\xff"}\n', 'invalid_stdout_json'),
            (b'[]\n', 'invalid_stdout_event'),
        ]:
            with self.subTest(payload=payload):
                result = self.capture('sys.stdout.buffer.write(' + repr(payload) + ')')
                self.assertEqual(result['failure'], expected)
        result = self.capture('emit(result)\nsys.stdout.buffer.write(b\'{"type":\')')
        self.assertEqual(result['failure'], 'invalid_stdout_json')
        self.assertIn(b'synthetic findings', result['stdout'])

    def test_result_errors_and_missing_result_fields_fail_closed(self):
        for event, expected in [
            ({'type': 'result'}, 'invalid_result_event'),
            ({'type': 'result', 'subtype': 'success', 'is_error': 'false'}, 'invalid_result_event'),
            ({'type': 'result', 'subtype': 'success', 'is_error': False}, 'invalid_result_event'),
            ({'type': 'result', 'subtype': 'error_max_budget_usd', 'is_error': True}, 'claude_result_error'),
        ]:
            with self.subTest(event=event):
                result = self.capture('emit(' + repr(event) + ')')
                self.assertEqual(result['failure'], expected)
                self.assertEqual(json.loads(result['stdout']), event)

    def test_duplicate_final_result_fails_closed(self):
        result = self.capture('emit(result)\nemit(result)')
        self.assertEqual(result['failure'], 'duplicate_result')

    def test_retained_output_line_and_stderr_limits_remain(self):
        for code, expected in [
            ('for _ in range(4): emit({"type":"future_security_event", "data":"x" * 80000})', 'output_limit'),
            ('emit({"type":"user", "content":"x" * 270000})', 'stdout_line_limit'),
            ('sys.stderr.buffer.write(b"x" * 270000)', 'output_limit'),
        ]:
            with self.subTest(expected=expected, code=code):
                result = self.capture(code)
                self.assertEqual(result['failure'], expected)
                self.assertLessEqual(len(result['stdout']), a.MAX_CAPTURE)
                self.assertLessEqual(len(result['stderr']), a.MAX_CAPTURE)

    def test_raw_progress_stream_still_has_a_finite_limit(self):
        with patch.object(a, 'MAX_CLAUDE_STREAM', 2048):
            result = self.capture('for _ in range(100): emit(progress)\nemit(result)')
        self.assertEqual(result['failure'], 'stdout_stream_limit')

    def test_timeout_cleans_up_without_relaunch_and_keeps_stderr(self):
        result = self.capture('emit(progress)\nprint("synthetic diagnostic", file=sys.stderr, flush=True)\ntime.sleep(10)', timeout=.15)
        self.assertEqual(result['failure'], 'timeout')
        self.assertIsNotNone(result['exit_code'])
        self.assertIn(b'synthetic diagnostic', result['stderr'])
        self.assertLess(result['duration_seconds'], 3)

    def test_nonzero_exit_is_not_masked_by_a_success_event(self):
        result = self.capture('emit(result)\nprint("synthetic error", file=sys.stderr)\nsys.exit(7)')
        self.assertEqual(result['exit_code'], 7)
        self.assertIn(b'synthetic error', result['stderr'])
