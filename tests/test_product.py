import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from deepseek_reviewer import config, distribution, tasks
from deepseek_reviewer.prepare import prepare_claude_review
from deepseek_reviewer.runner import AgentStopped
from deepseek_reviewer.safety import ReviewError, read_selected


class PortableTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='reviewer-product-test-')
        self.root = Path(self.tmp.name).resolve()
        self.environment = patch.dict(os.environ, {'HOME': str(self.root)}, clear=True)
        self.environment.start()
        self.policy = patch.object(config, 'managed_policy_paths', return_value=[])
        self.policy.start()
        self.claude = self.root / 'synthetic-claude'
        self.claude.write_text('#!' + sys.executable + '''
import json, sys
if '--version' in sys.argv:
 print('2.1.312 (Claude Code)'); sys.exit(0)
if '--help' in sys.argv:
 print('--restricted --safe-mode --tools --setting-sources --strict-mcp-config --max-turns --max-budget-usd --no-session-persistence dontAsk stream-json'); sys.exit(0)
sys.stdin.read()
def emit(e): print(json.dumps(e), flush=True)
emit({'type':'system','subtype':'init','tools':['Read','Glob','Grep','EndConversation']})
emit({'type':'assistant','message':{'id':'synthetic-response','model':'deepseek-flash','content':[{'type':'tool_use','id':'synthetic-read','name':'Read','input':{'file_path':'price.py'}}]}})
emit({'type':'user','message':{'content':[{'type':'tool_result','tool_use_id':'synthetic-read','content':'fully synthetic'}]}})
report={'schema':2,'assessment':'Synthetic report only.','reviewed_files':['price.py'],'findings':[],'coverage_gaps':['Associated tests not inspected.']}
emit({'type':'result','subtype':'success','is_error':False,'result':json.dumps(report),'num_turns':2,'total_cost_usd':0.001,'usage':{'input_tokens':30,'output_tokens':10}})
''')
        self.claude.chmod(0o700)
        with patch.object(config.platform, 'system', return_value='Darwin'):
            self.runtime = config.register(self.claude)
        self.repo = self.root / 'synthetic-repo'
        self.repo.mkdir()
        (self.repo / 'price.py').write_text('def total(n):\n    return n + 1\n')
        (self.repo / 'test_price.py').write_text('assert total(0) == 0\n')
        self.limits = dict(timeout=2, max_turns=4, max_budget_usd=.1, max_output_tokens=1800, effort='low')

    def tearDown(self):
        self.policy.stop()
        self.environment.stop()
        for path in self.root.rglob('*'):
            if path.is_dir() and not path.is_symlink(): path.chmod(0o700)
        self.tmp.cleanup()

    def plan(self):
        return tasks.create_plan(self.repo, ['price.py', 'test_price.py'], 'Find synthetic defects',
                                 'synthetic revision', 'static only', 'synthetic evidence', self.limits)

    def test_prepare_is_offline_and_single_execution_returns_result(self):
        with patch.object(tasks, 'run_bounded') as launch:
            plan = self.plan()
            launch.assert_not_called()
        self.assertNotIn('source_root', plan)
        report = tasks.execute_plan(plan['plan'], plan['sha256'])
        self.assertEqual(report['status'], 'COMPLETED')
        self.assertEqual(report['review']['assessment'], 'Synthetic report only.')
        self.assertIn('Synthetic report only.', report['findings'])
        self.assertTrue(report['snapshot_unchanged'])
        self.assertEqual(report['observation']['read_results'], ['price.py'])
        self.assertIsNone(report['observation']['http_requests'])
        with self.assertRaisesRegex(AgentStopped, 'attempt_consumed'):
            tasks.execute_plan(plan['plan'], plan['sha256'])

    def test_isolated_environment_and_exact_restricted_arguments(self):
        plan = self.plan()
        run, value = tasks.load_plan(plan['plan'], plan['sha256'])
        invocation = prepare_claude_review(run / 'snapshot', run / 'inspection', runtime=self.runtime,
                      approved_files=value['files'], required_files=list(value['files']),
                      **value['task'], **value['limits'])
        args, env = invocation['args'], invocation['env']
        self.assertIn('--restricted', args)
        self.assertIn('--safe-mode', args)
        self.assertEqual(args[args.index('--tools') + 1], 'Read,Glob,Grep')
        self.assertEqual(args[args.index('--max-turns') + 1], '4')
        self.assertEqual(args[args.index('--thinking') + 1], 'disabled')
        self.assertEqual(env['MAX_THINKING_TOKENS'], '0')
        self.assertEqual(env['CLAUDE_CODE_MAX_OUTPUT_TOKENS'], '1800')
        self.assertEqual(args[args.index('--max-budget-usd') + 1], '0.1')
        self.assertNotIn('delivery_policy', invocation)
        self.assertEqual(json.loads(env['CLAUDE_CODE_EXTRA_BODY']), {'thinking': {'type': 'disabled'}})
        self.assertEqual(args[args.index('--setting-sources') + 1], '')
        self.assertEqual(args[args.index('--mcp-config') + 1], '{"mcpServers":{}}')
        self.assertEqual(env['CLAUDE_CONFIG_DIR'], env['CLAUDE_SECURESTORAGE_CONFIG_DIR'])
        self.assertNotEqual(env['HOME'], os.environ['HOME'])
        self.assertFalse(set(env) & {'ANTHROPIC_API_KEY','DEEPSEEK_API_KEY','ANTHROPIC_AUTH_TOKEN','HTTP_PROXY'})
        settings = json.loads((run / 'inspection/settings.json').read_text())
        self.assertTrue(settings['disableAllHooks'])
        self.assertTrue({'Bash','Edit','Write','mcp__*'} <= set(settings['permissions']['deny']))
        self.assertIn(config.SERVICE, settings['apiKeyHelper'])
        self.assertIn('2>/dev/null', settings['apiKeyHelper'])

    def test_pinned_hidden_turn_flag_does_not_fail_registration(self):
        # The real 2.1.312 option is defined with hideHelp(). Its absence from
        # --help is not absence of support; visible safety flags still matter.
        source = self.claude.read_text().replace(' --max-turns', '')
        self.claude.write_text(source)
        with patch.object(config.platform, 'system', return_value='Darwin'):
            self.assertEqual(config._inspect_claude(self.claude)['version'], '2.1.312')
            self.claude.write_text(source.replace('--restricted ', ''))
            with self.assertRaisesRegex(AgentStopped, 'missing_claude_capability'):
                config._inspect_claude(self.claude)
            self.claude.write_text(source.replace('2.1.312 (Claude Code)', '2.1.313 (Claude Code)'))
            with self.assertRaisesRegex(AgentStopped, 'unsupported_claude_version'):
                config._inspect_claude(self.claude)

    def test_tampered_plan_snapshot_runtime_and_managed_policy_stop(self):
        plan = self.plan()
        with self.assertRaisesRegex(AgentStopped, 'plan_changed'):
            tasks.execute_plan(plan['plan'], '0' * 64)
        snapshot = Path(plan['plan']).parent / 'snapshot/price.py'
        snapshot.chmod(0o600); snapshot.write_text('changed')
        with self.assertRaisesRegex(AgentStopped, 'review_materials'):
            tasks.execute_plan(plan['plan'], plan['sha256'])
        self.claude.write_text('replaced')
        with self.assertRaisesRegex(AgentStopped, 'registered_claude_changed'):
            config.load_runtime()
        policy = self.root / 'managed-policy'; policy.write_text('synthetic')
        with patch.object(config, 'managed_policy_paths', return_value=[policy]):
            with self.assertRaisesRegex(AgentStopped, 'managed_policy_present'):
                config.check_policy()

    def test_snapshot_rejects_secret_paths_symlinks_hardlinks_and_traversal(self):
        outside = self.root / 'outside'; outside.write_text('synthetic sentinel')
        (self.repo / 'link.py').symlink_to(outside)
        os.link(outside, self.repo / 'hard.py')
        for name in ['.env','secrets/file','../outside','link.py','hard.py','/absolute','login.keychain-db']:
            with self.subTest(name=name), self.assertRaises(ReviewError):
                read_selected(self.repo, name)
        (self.repo / 'secret.py').write_text('api_key=' + 'syntheticcredentialvalue')
        with self.assertRaisesRegex(ReviewError, 'sensitive_content'):
            tasks.create_plan(self.repo, ['secret.py'], 'q', 'r', 'c', 't', self.limits)

    def test_keychain_commands_never_supply_key_value_or_allow_all(self):
        for action in ['save', 'replace', 'remove']:
            command = config.credential_command(action, self.runtime['keychain'])
            self.assertNotIn('-A', command)
            self.assertEqual(command[command.index('-s') + 1], config.SERVICE)
            if action != 'remove':
                self.assertEqual(command[-1], '-w')
                self.assertEqual(command[command.index('-T') + 1], '')
        with patch('sys.stdin.isatty', return_value=False), patch.object(config.subprocess, 'call') as call:
            with self.assertRaisesRegex(AgentStopped, 'interactive_terminal'):
                config.credentials('save')
            call.assert_not_called()

    def test_invalid_limits_never_prepare_or_start(self):
        for key, value in [('timeout',601),('max_turns',33),('max_output_tokens',64001),
                           ('max_budget_usd', float('nan')),('max_budget_usd',2.01),('effort','high')]:
            limits = {**self.limits, key:value}
            with self.subTest(key=key), self.assertRaises(AgentStopped):
                tasks.validate_limits(limits)

    def test_unknown_tools_and_missing_report_do_not_complete(self):
        result = {'started':True,'exit_code':0,'failure':None,'duration_seconds':1,'stderr':b'',
            'stdout':b'{"type":"result","subtype":"success","is_error":false,"result":"example"}\n','claude':{
            'capture_complete':True,'execution':'completed','unexpected_init_tools':True,
            'tools_requested':{'other':1},'models_observed':['deepseek-flash']}}
        self.assertEqual(tasks.summarize(result, ['price.py'], True)['status'], 'FAILED')
        result['claude']['capture_complete'] = False
        self.assertEqual(tasks.summarize(result, ['price.py'], True)['status'], 'FAILED')


class ReleaseTests(unittest.TestCase):
    def test_install_update_checksum_and_rollback_in_disposable_home(self):
        with tempfile.TemporaryDirectory() as d, patch.dict(os.environ, {'HOME': d}, clear=True):
            root = Path(d).resolve()
            paths = []
            for version in ['1.0.0', '1.0.1']:
                archive = root / (version + '.pyz')
                with zipfile.ZipFile(archive, 'w') as z:
                    z.writestr('deepseek_reviewer/release.json', json.dumps({'version':version}))
                    z.writestr('__main__.py', 'print(' + repr(version) + ')')
                checksum = hashlib.sha256(archive.read_bytes()).hexdigest()
                paths.append((archive, version, checksum))
            first = distribution.install_archive(*paths[0])
            self.assertEqual(subprocess.check_output([first['command']]).decode().strip(), '1.0.0')
            manifest = {'file':'deepseek-reviewer.pyz','version':'1.0.1','sha256':paths[1][2]}
            with patch.object(distribution, 'latest', return_value=manifest), patch.object(distribution, 'fetch', return_value=paths[1][0].read_bytes()):
                updated = distribution.update()
            self.assertEqual(subprocess.check_output([updated['command']]).decode().strip(), '1.0.1')
            restored = distribution.rollback()
            self.assertEqual(subprocess.check_output([restored['command']]).decode().strip(), '1.0.0')
            with self.assertRaisesRegex(AgentStopped, 'checksum'):
                distribution.install_archive(paths[1][0], '1.0.1', '0' * 64)
            self.assertEqual(subprocess.check_output([restored['command']]).decode().strip(), '1.0.0')

    def test_download_and_version_boundaries(self):
        for url in ['http://github.com/file','https://evil.example/file','https://github.com.evil.example/file',
                    'https://token@github.com/file','https://github.com:444/file']:
            with self.assertRaises(AgentStopped): distribution.allowed_url(url)
        distribution.allowed_url('https://release-assets.githubusercontent.com/synthetic')
        for value in ['../1.0.0','v1.0.0','1.0.0-beta','01.0.0']:
            with self.assertRaises(AgentStopped): distribution.version_tuple(value)


if __name__ == '__main__': unittest.main()
