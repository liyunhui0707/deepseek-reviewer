"""Bounded subprocess capture reused from the accepted Reviewer workflow."""
import json
import math
import os
from pathlib import Path
import re
import selectors
import signal
import subprocess
import threading
import time
from .safety import validate_path, validate_checkpoint, parse_review_report, ReviewError

MAX_CAPTURE = 256 * 1024
MAX_CLAUDE_STREAM = 4 * 1024 * 1024
MAX_EXECUTION_SECONDS = 600
MAX_STDOUT_BYTES = 4 * 1024 * 1024
MAX_STDOUT_STREAM_BYTES = 64 * 1024 * 1024
MAX_JSONL_RECORD_BYTES = 1024 * 1024
USAGE_FIELDS = ('input_tokens', 'output_tokens', 'cache_read_input_tokens', 'cache_creation_input_tokens')

class AgentStopped(Exception):
    pass

def private_write(path, data):
    if not isinstance(data, bytes):
        data = (json.dumps(data, indent=2, ensure_ascii=True) + '\n').encode()
    fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, 'wb') as f:
        f.write(data)

class _ClaudeStreamCapture:
    """Bounded line filter, not a tool dispatcher or review-result validator."""

    def __init__(self, output, *, max_stdout_bytes, max_stdout_stream_bytes,
                 max_jsonl_record_bytes, cwd=None, progress_files=()):
        self.output = output
        self.max_stdout_bytes = max_stdout_bytes
        self.max_stdout_stream_bytes = max_stdout_stream_bytes
        self.max_jsonl_record_bytes = max_jsonl_record_bytes
        self.pending = bytearray()
        self.received = self.dropped_events = self.dropped_bytes = 0
        self.result_seen = self.result_error = False
        self.phase = 'started'
        self.current_tool = self.current_file = None
        self.response_ids = set()
        self.calls = {}
        self.tool_counts = {'Read': 0, 'Glob': 0, 'Grep': 0, 'lifecycle': 0, 'other': 0}
        self.tool_results = 0
        self.read_results = set()
        self.models = set()
        self.assistant_text = False
        self.thinking_content_observed = False
        self.result_subtype = None
        self.final_report = False
        self.num_turns = self.cost = None
        self.usage = {}
        self.response_usage = {}
        self.cwd = os.path.abspath(cwd) if cwd is not None else None
        self.progress_files = set(progress_files)
        self.unexpected_init_tools = None
        self.checkpoint = None
        self.checkpoints_observed = self.checkpoints_rejected = 0
        self.checkpoint_revision_error = None

    def _checkpoint(self, text):
        # Only public report artifacts can revise a report. Ordinary JSON
        # status messages, tool results and thinking are not report revisions.
        text = text.replace('\r\n', '\n').strip()
        markers = re.findall(r'(?m)^[ \t]*```(review-checkpoint|review-report|json)[ \t]*$', text)
        if not markers and not text.startswith('{'): return
        category = 'format'
        try:
            if len(text.encode()) > 32768 or len(markers) > 1:
                raise ValueError
            body = text
            if markers:
                match = re.search(r'(?m)^[ \t]*```' + markers[0] + r'[ \t]*\n(.*?)\n[ \t]*```[ \t]*(?=\n|$)', text, re.S)
                if not match: raise ValueError
                body = match[1]
            value = json.loads(body, object_pairs_hook=self._object, parse_constant=self._constant)
            if (not markers or markers == ['json']) and (not isinstance(value, dict) or 'schema' not in value
                    or not {'assessment', 'findings', 'reviewed_files'} & value.keys()):
                return
            category = 'validation'
            if isinstance(value, dict) and value.get('schema') == 2:
                # Same content/envelope checks as the terminal report; only its
                # event provenance determines provisional versus final delivery.
                diagnostic = {}
                try:
                    candidate = parse_review_report(text, self.progress_files, self.read_results,
                                                    diagnostic=diagnostic)
                except ReviewError:
                    category = ('sensitive_content' if diagnostic.get('stage') == 'content' else
                                'format' if diagnostic.get('stage') in ('input', 'envelope', 'json') else 'validation')
                    raise
            else:
                # Retain legacy schema-1 checkpoint compatibility; it can never
                # satisfy the current product's terminal schema-2 requirement.
                candidate = validate_checkpoint(value, self.progress_files)
                if not markers: raise ValueError
            # Commit only a validated cumulative revision, including an explicit
            # retraction with empty findings. Never clear a safe prior artifact.
            self.checkpoint = candidate
            self.checkpoint_revision_error = None
            self.checkpoints_observed += 1
        except (ValueError, TypeError, UnicodeError, RecursionError, ReviewError) as exc:
            if not markers and category == 'format': return
            self.checkpoint_revision_error = ('sensitive_content' if isinstance(exc, ReviewError)
                                              and str(exc) == 'sensitive_content' else category)
            self.checkpoints_rejected += 1

    def _observe(self, event):
        """Observe fixed labels, approved relative filenames and numeric metadata.

        Never forward text, reasoning, search expressions, IDs, raw paths,
        tool results, credential state or stderr to progress callbacks.
        """
        if event['type'] == 'system' and event.get('subtype') == 'init':
            self.phase = 'initialized'
            tools = event.get('tools')
            if isinstance(tools, list):
                self.unexpected_init_tools = bool(self.unexpected_init_tools) or any(
                    t not in ('Read', 'Glob', 'Grep', 'EndConversation') for t in tools)
        message = event.get('message')
        if isinstance(message, dict) and event['type'] in ('assistant', 'user'):
            content = message.get('content', [])
            if not isinstance(content, list): content = []
            if event['type'] == 'assistant':
                self.phase = 'model_response'
                if isinstance(message.get('id'), str):
                    self.response_ids.add(message['id'])
                    usage = message.get('usage')
                    if isinstance(usage, dict):
                        accumulated = self.response_usage.setdefault(message['id'], {})
                        # Stream snapshots may repeat the same response's usage.
                        # Keep its greatest observed count, never add duplicates.
                        for key in USAGE_FIELDS:
                            if type(usage.get(key)) is int and usage[key] >= 0:
                                accumulated[key] = max(accumulated.get(key, 0), usage[key])
                if isinstance(message.get('model'), str):
                    self.models.add(message['model'] if message['model'] in ('deepseek-flash', 'deepseek-flash[1m]') else 'unrecognized')
            for block in content:
                if not isinstance(block, dict): continue
                if event['type'] == 'assistant' and block.get('type') in ('thinking', 'redacted_thinking'):
                    self.thinking_content_observed = True
                if event['type'] == 'assistant' and block.get('type') == 'text' and isinstance(block.get('text'), str):
                    self.assistant_text |= bool(block['text'])
                    self._checkpoint(block['text'])
                if event['type'] == 'assistant' and block.get('type') == 'tool_use' and isinstance(block.get('id'), str):
                    tool = block.get('name')
                    tool = tool if tool in ('Read', 'Glob', 'Grep') else 'lifecycle' if tool == 'EndConversation' else 'other'
                    filename = None
                    fields = block.get('input')
                    if tool == 'Read' and isinstance(fields, dict) and isinstance(fields.get('file_path'), str) and self.cwd:
                        relative = os.path.relpath(os.path.normpath(os.path.join(self.cwd, fields['file_path'])), self.cwd)
                        if relative in self.progress_files: filename = relative
                    if block['id'] not in self.calls:
                        self.calls[block['id']] = (tool, filename, False)
                        self.tool_counts[tool] += 1
                    self.phase, self.current_tool, self.current_file = 'tool_call', tool, filename
                if event['type'] == 'user' and block.get('type') == 'tool_result' and isinstance(block.get('tool_use_id'), str):
                    call = self.calls.get(block['tool_use_id'])
                    if call and not call[2]:
                        tool, filename, _ = call
                        self.calls[block['tool_use_id']] = (tool, filename, True)
                        self.tool_results += 1
                        if tool == 'Read' and filename and block.get('is_error', False) is False:
                            self.read_results.add(filename)
                        self.phase, self.current_tool, self.current_file = 'tool_result', tool, filename
        if event['type'] == 'result':
            self.phase = 'result_received'
            subtype = event['subtype']
            self.result_subtype = subtype if subtype in ('success', 'error_max_turns', 'error_max_budget_usd',
                                  'error_during_execution', 'error_max_structured_output_retries') else 'other_result'
            text_result = event.get('result')
            self.final_report = not self.result_error and bool(
                text_result.strip() if isinstance(text_result, str) else event.get('structured_output'))
            if type(event.get('num_turns')) is int and event['num_turns'] >= 0: self.num_turns = event['num_turns']
            cost = event.get('total_cost_usd')
            if type(cost) in (int, float) and 0 <= cost <= 1e9 and math.isfinite(cost): self.cost = cost
            usage = event.get('usage')
            if isinstance(usage, dict):
                self.usage = {k: usage[k] for k in USAGE_FIELDS
                              if type(usage.get(k)) is int and usage[k] >= 0}

    def summary(self, started, exit_code, failure):
        execution = 'failed'
        if not started: execution = 'not_started'
        elif failure is None and exit_code == 0 and self.result_seen and not self.result_error: execution = 'completed'
        elif failure == 'timeout' or (failure == 'claude_result_error' and self.result_subtype in ('error_max_turns', 'error_max_budget_usd')):
            execution = 'incomplete'
        capture_complete = failure in (None, 'claude_result_error')
        observed_usage = {key: sum(usage.get(key, 0) for usage in self.response_usage.values())
                          for key in USAGE_FIELDS if any(key in usage for usage in self.response_usage.values())}
        return {'execution': execution, 'result_present': self.result_seen, 'capture_complete': capture_complete,
                'result_subtype': self.result_subtype, 'final_report_available': self.final_report and capture_complete,
                'assistant_text_observed': self.assistant_text, 'coverage': 'not_assessed',
                'thinking_content_observed': self.thinking_content_observed,
                'thinking_progress_events': self.dropped_events,
                'checkpoints_observed': self.checkpoints_observed, 'checkpoints_rejected': self.checkpoints_rejected,
                'checkpoint_revision_error': self.checkpoint_revision_error,
                'authentication': 'unknown', 'http_requests': None, 'provider_billed_usd': None,
                'model_responses_observed': len(self.response_ids), 'models_observed': sorted(self.models),
                'tools_requested': dict(self.tool_counts), 'tool_results_observed': self.tool_results,
                'read_results': sorted(self.read_results), 'unexpected_init_tools': self.unexpected_init_tools,
                'num_turns': self.num_turns, 'client_estimated_usd': self.cost,
                'usage': dict(self.usage) if self.usage else observed_usage,
                'usage_source': 'result' if self.usage else 'observed_responses_partial' if observed_usage else 'not_observed'}

    @staticmethod
    def _object(pairs):
        value = {}
        for key, item in pairs:
            if key in value:
                raise ValueError('duplicate JSON key')
            value[key] = item
        return value

    @staticmethod
    def _constant(_):
        raise ValueError('non-finite JSON number')

    def _line(self, line):
        if len(line) > self.max_jsonl_record_bytes:
            raise AgentStopped('stdout_line_limit')
        try:
            event = json.loads(line.decode('utf-8'), object_pairs_hook=self._object,
                               parse_constant=self._constant)
        except (UnicodeError, ValueError, RecursionError):
            raise AgentStopped('invalid_stdout_json') from None
        if not isinstance(event, dict) or not isinstance(event.get('type'), str):
            raise AgentStopped('invalid_stdout_event')
        required = {'type', 'subtype', 'estimated_tokens', 'estimated_tokens_delta',
                    'session_id', 'uuid'}
        # Pinned 2.1.312 schema: only numeric UI progress, never reasoning text.
        # Unknown fields/types stay in the evidence instead of being discarded.
        if (event.get('type') == 'system' and event.get('subtype') == 'thinking_tokens'
                and required <= event.keys() <= required | {'user_message_uuid'}
                and all(type(event[k]) is int and event[k] >= 0
                        for k in ('estimated_tokens', 'estimated_tokens_delta'))
                and all(isinstance(event[k], str) and 0 < len(event[k]) <= 128
                        for k in ('session_id', 'uuid', 'user_message_uuid') if k in event)):
            self.dropped_events += 1
            self.dropped_bytes += len(line)
            return
        if len(self.output) + len(line) > self.max_stdout_bytes:
            raise AgentStopped('output_limit')
        self.output.extend(line)  # Preserve all other events byte-for-byte.
        if event['type'] == 'result':
            if self.result_seen:
                raise AgentStopped('duplicate_result')
            if not isinstance(event.get('subtype'), str) or type(event.get('is_error')) is not bool:
                raise AgentStopped('invalid_result_event')
            self.result_seen = True
            self.result_error = event['is_error'] or event['subtype'] != 'success'
            if not self.result_error and not (isinstance(event.get('result'), str)
                                             or isinstance(event.get('structured_output'), dict)):
                raise AgentStopped('invalid_result_event')
        self._observe(event)

    def feed(self, data):
        self.received += len(data)
        if self.received > self.max_stdout_stream_bytes:
            raise AgentStopped('stdout_stream_limit')
        self.pending.extend(data)
        while (end := self.pending.find(b'\n')) >= 0:
            line = bytes(self.pending[:end + 1])
            del self.pending[:end + 1]
            self._line(line)
        if len(self.pending) > self.max_jsonl_record_bytes:
            raise AgentStopped('stdout_line_limit')

    def finish(self):
        if self.pending:
            self._line(bytes(self.pending))
            self.pending.clear()
        if not self.result_seen:
            raise AgentStopped('missing_result')
        if self.result_error:
            raise AgentStopped('claude_result_error')

def run_bounded(args, cwd, env, task, timeout=60, *, claude_stream_json=False,
                max_stdout_bytes=None, max_stdout_stream_bytes=None,
                max_jsonl_record_bytes=None, on_progress=None, progress_interval=30,
                progress_files=(), launch_claim=None):
    """One subprocess, bounded pipes and no retry; opt-in Claude progress filter.

    A complete capture is not review acceptance. Callers must still check exit,
    tool evidence, result/coverage and credential cleanup.

    Defaults: 60 seconds, 256 KiB retained stdout/stderr, 4 MiB raw Claude
    stdout, 256 KiB JSONL records (including newline). Explicit ceilings:
    600 seconds, 4 MiB retained stdout, 64 MiB raw stdout, 1 MiB JSONL records.
    Stream/record overrides require claude_stream_json; stderr stays 256 KiB.
    Timeout termination retains the existing bounded process-group cleanup.
    on_progress is a trusted, nonblocking callback receiving sanitized metadata
    only. It must not fetch credentials or run tools. Exceptions stop this call.
    launch_claim is optional exclusive private state; failures never release it.
    """
    if (type(timeout) not in (int, float) or not 0 < timeout <= MAX_EXECUTION_SECONDS
            or len(task.encode()) > 8192
            or (not claude_stream_json and (max_stdout_stream_bytes is not None
                                           or max_jsonl_record_bytes is not None))):
        raise AgentStopped('execution_limit')
    if ((on_progress is not None and (not claude_stream_json or not callable(on_progress)))
            or type(progress_interval) not in (int, float) or not .05 <= progress_interval <= 60
            or not isinstance(progress_files, (tuple, list))):
        raise AgentStopped('progress_options')
    try:
        for name in progress_files: validate_path(name)
    except ReviewError:
        raise AgentStopped('progress_options') from None
    max_stdout_bytes = MAX_CAPTURE if max_stdout_bytes is None else max_stdout_bytes
    max_stdout_stream_bytes = MAX_CLAUDE_STREAM if max_stdout_stream_bytes is None else max_stdout_stream_bytes
    max_jsonl_record_bytes = MAX_CAPTURE if max_jsonl_record_bytes is None else max_jsonl_record_bytes
    if any(type(value) is not int or not 0 < value <= ceiling for value, ceiling in (
            (max_stdout_bytes, MAX_STDOUT_BYTES),
            (max_stdout_stream_bytes, MAX_STDOUT_STREAM_BYTES),
            (max_jsonl_record_bytes, MAX_JSONL_RECORD_BYTES))):
        raise AgentStopped('execution_limit')
    if launch_claim is not None:
        try: private_write(Path(launch_claim), {'state': 'consumed_before_launch'})
        except FileExistsError: raise AgentStopped('attempt_consumed') from None
    proc = None; streams = selectors.DefaultSelector(); output = {'stdout': bytearray(), 'stderr': bytearray()}
    capture = (_ClaudeStreamCapture(output['stdout'], max_stdout_bytes=max_stdout_bytes,
                                   max_stdout_stream_bytes=max_stdout_stream_bytes,
                                   max_jsonl_record_bytes=max_jsonl_record_bytes,
                                   cwd=cwd, progress_files=progress_files)
               if claude_stream_json else None)
    failure = None; started = time.monotonic()
    cleanup_errors = []
    last_notice = started; last_output = started; last_signature = None
    callback_failed = False

    def notify(kind='event', *, finished=False):
        nonlocal last_notice, last_signature, callback_failed
        if on_progress is None or callback_failed: return
        now = time.monotonic()
        signature = (capture.phase, capture.current_tool, capture.current_file,
                     len(capture.response_ids), sum(capture.tool_counts.values()), capture.tool_results,
                     capture.checkpoints_observed)
        if not finished and kind != 'heartbeat' and signature == last_signature: return
        notice = {'notification': kind, 'phase': 'finished' if finished else capture.phase,
                  'elapsed_seconds': round(now - started, 3), 'seconds_since_output': round(now - last_output, 3),
                  'remaining_seconds': max(0, round(timeout - (now - started), 1)),
                  'tool': capture.current_tool, 'file': capture.current_file,
                  'model_responses_observed': len(capture.response_ids),
                  'tool_calls_observed': sum(capture.tool_counts.values()), 'tool_results_observed': capture.tool_results,
                  'checkpoints_observed': capture.checkpoints_observed}
        if finished:
            notice.update(execution=capture.summary(proc is not None, proc.returncode if proc else None, failure)['execution'],
                          exit_code=proc.returncode if proc else None, failure=failure,
                          result_subtype=capture.result_subtype)
        try: on_progress(notice)
        except AgentStopped:
            callback_failed = True
            raise
        except Exception:
            callback_failed = True
            raise AgentStopped('progress_callback_error') from None
        last_notice, last_signature = now, signature
    previous_sigterm = None
    def terminate(_signum, _frame):
        raise AgentStopped('terminated')
    if threading.current_thread() is threading.main_thread():
        previous_sigterm = signal.signal(signal.SIGTERM, terminate)
    try:
        proc = subprocess.Popen(args, cwd=cwd, env=env, stdin=subprocess.PIPE,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True)
        notify()
        try:
            proc.stdin.write(task.encode()); proc.stdin.close()
        except BrokenPipeError:
            failure = 'stdin_closed'  # Still drain startup diagnostics below.
        for name in output:
            pipe = getattr(proc, name); os.set_blocking(pipe.fileno(), False)
            streams.register(pipe, selectors.EVENT_READ, name)
        while streams.get_map() or proc.poll() is None:
            if time.monotonic() - started > timeout: raise AgentStopped('timeout')
            for key, _ in streams.select(.1):
                data = os.read(key.fileobj.fileno(), 8192)
                if not data: streams.unregister(key.fileobj); continue
                last_output = time.monotonic()
                if capture is not None and key.data == 'stdout':
                    capture.feed(data)
                    notify()
                    continue
                limit = max_stdout_bytes if key.data == 'stdout' else MAX_CAPTURE
                if len(output[key.data]) + len(data) > limit: raise AgentStopped('output_limit')
                output[key.data].extend(data)
            if time.monotonic() - last_notice >= progress_interval: notify('heartbeat')
        proc.wait(timeout=max(.1, timeout - (time.monotonic() - started)))
        if capture is not None:
            capture.finish()
    except KeyboardInterrupt:
        failure = 'cancelled'
        callback_failed = True
    except (OSError, subprocess.TimeoutExpired, AgentStopped) as exc:
        failure = str(exc) if isinstance(exc, AgentStopped) else type(exc).__name__
    finally:
        if previous_sigterm is not None:
            signal.signal(signal.SIGTERM, previous_sigterm)
        streams.close()
        if proc:
            def signal_group(sig):
                try: os.killpg(proc.pid, sig)
                except ProcessLookupError: pass
                except OSError: cleanup_errors.append('group_signal_failed')
            signal_group(signal.SIGTERM)
            try: proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                signal_group(signal.SIGKILL)
                try: proc.wait(timeout=2)
                except subprocess.TimeoutExpired: cleanup_errors.append('child_not_reaped')
            signal_group(signal.SIGKILL)
            for p in (proc.stdout, proc.stderr): p.close()
            if proc.stdin and not proc.stdin.closed: proc.stdin.close()
    if cleanup_errors and failure is None: failure = 'cleanup_failed'
    try: notify(finished=True)
    except AgentStopped: failure = 'progress_callback_error'
    return {'started': proc is not None, 'exit_code': proc.returncode if proc else None,
            'failure': failure, 'duration_seconds': round(time.monotonic()-started, 3),
            'cleanup': {'completed': not cleanup_errors, 'errors': sorted(set(cleanup_errors)),
                        'child_reaped': proc is None or proc.returncode is not None},
            **({'stdout_bytes_received': capture.received,
                'checkpoint': capture.checkpoint,
                'stdout_progress_events_dropped': capture.dropped_events,
                'stdout_progress_bytes_dropped': capture.dropped_bytes,
                'claude': capture.summary(proc is not None, proc.returncode if proc else None, failure)} if capture is not None else {}),
            **{k: bytes(v) for k, v in output.items()}}
