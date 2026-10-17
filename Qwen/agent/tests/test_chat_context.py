# 设计文档：[插件机制](../../../../文档/Qwen/Agent/插件机制/design/详细设计.md)
# 设计文档：[记忆工具化改造](../../../../文档/Qwen/Agent/记忆工具化改造/design/详细设计.md)
import copy
from dataclasses import replace
import json
from types import SimpleNamespace
import unittest
import tempfile
from pathlib import Path
from agent.plugins.base import PluginLoadError
from agent.entities import PluginSpec
from agent.plugins import loader
from agent.entities import ToolSpec
from unittest.mock import patch

from agent.workflow import core_loop as chat
from agent.tools.registry import load_tools


def action(name='answer', argument='好的'):
    return json.dumps({'thought': '', 'action': name, 'argument': argument}, ensure_ascii=False)


class ChatContextTests(unittest.TestCase):
    def setUp(self):
        self.old = getattr(chat, '_messages', None)
        chat._messages = []

    def tearDown(self):
        if self.old is None:
            del chat._messages
        else:
            chat._messages = self.old

    def run_chat(self, text, outputs):
        with patch.object(chat, '_generate', side_effect=outputs):
            return chat.chat(text)

    def test_commit_stats_and_multiple_rounds(self):
        reply, count, chars = self.run_chat('苹果', [action()])
        self.assertEqual(reply, '好的')
        self.assertEqual(count, 3)
        self.assertEqual(chars, sum(len(m['content']) for m in chat._messages))
        self.assertEqual(self.run_chat('再问', [action()])[1], 5)
        self.assertEqual(sum(m['role'] == 'system' for m in chat._messages), 1)
        self.assertEqual(chat._messages[0]['content'], chat.REACT_SYSTEM_PROMPT)

    def test_current_excluded_previous_identical_retained(self):
        for expected in [[], ['苹果']]:
            seen = []
            def generate(turns, tools, allowed_actions):
                self.assertEqual(chat._messages[-1]['role'] if chat._messages else None,
                                 'assistant' if expected else None)
                seen.append(copy.deepcopy(turns))
                return action('memory_search', '苹果') if len(seen) == 1 else action()
            with patch.object(chat, '_generate', side_effect=generate):
                chat.chat('苹果')
            observation = json.loads(seen[1][-1]['content'].removeprefix('[观察] '))
            self.assertEqual(observation['result'], {'matches': expected, 'found': bool(expected)})
            self.assertEqual(seen[1][-2]['role'], 'assistant')

    def test_failures_preserve_committed_state(self):
        failures = [[RuntimeError('生成失败')], ['not json'], [action(argument=' ')],
                    [action('repeat', 'x')] * 5]
        repeat = replace(load_tools()['memory_search'], name='repeat', max_calls=6)
        for seeded in [False, True]:
            for outputs in failures:
                with self.subTest(seeded=seeded, outputs=outputs):
                    chat._messages = []
                    if seeded:
                        self.run_chat('已提交', [action()])
                    before = copy.deepcopy(chat._messages)
                    with patch.object(chat, 'load_tools', return_value={'repeat': repeat}):
                        with self.assertRaises(RuntimeError):
                            self.run_chat('失败问题', outputs)
                    self.assertEqual(chat._messages, before)

    def test_handler_and_footer_exceptions_do_not_commit(self):
        for field in ['handler', 'result_footer']:
            def fail(value):
                raise LookupError('unexpected')
            tool = replace(load_tools()['memory_search'], **{field: fail})
            with patch.object(chat, 'load_tools', return_value={'memory_search': tool}):
                with self.assertRaises(LookupError):
                    self.run_chat('失败', [action('memory_search', 'x')])
            self.assertEqual(chat._messages, [])

    def test_calculator_footer_and_call_limit(self):
        seen = []
        outputs = iter([action('calculator', '200/10%'), action('calculator', '1+1'), action()])
        def generate(turns, tools, allowed_actions):
            seen.append(list(allowed_actions))
            return next(outputs)
        with patch.object(chat, '_generate', side_effect=generate):
            reply, count, chars = chat.chat('计算')
        self.assertIn('calculator', seen[1])
        self.assertNotIn('calculator', seen[2])
        self.assertIn('1+1；2', reply)
        self.assertIn('2000', chat._messages[3]['content'])
        self.assertEqual(count, len(chat._messages))
        self.assertEqual(chars, sum(len(m['content']) for m in chat._messages))

    def test_memory_call_limit_and_reset_after_failed_round(self):
        self.run_chat('苹果资料', [action()])
        committed = copy.deepcopy(chat._messages)
        seen = []

        def repeat_memory(turns, tools, allowed_actions):
            seen.append(list(allowed_actions))
            return action('memory_search', '苹果')

        with patch.object(chat, '_generate', side_effect=repeat_memory):
            with self.assertRaisesRegex(RuntimeError, '模型行动不符合当前工具流程'):
                chat.chat('重复调用')
        self.assertIn('memory_search', seen[0])
        self.assertNotIn('memory_search', seen[1])
        self.assertEqual(chat._messages, committed)

        for question in ['继续查找', '再次查找']:
            observations = []

            def search_once(turns, tools, allowed_actions):
                if not observations:
                    self.assertIn('memory_search', allowed_actions)
                    observations.append(None)
                    return action('memory_search', '苹果')
                self.assertNotIn('memory_search', allowed_actions)
                observations.append(json.loads(turns[-1]['content'].removeprefix('[观察] ')))
                return action()

            with patch.object(chat, '_generate', side_effect=search_once):
                chat.chat(question)
            self.assertEqual(observations[1]['result'],
                             {'matches': ['苹果资料'], 'found': True})

    def test_generate_dynamic_context_only_in_request(self):
        payloads = []
        class Client:
            def __enter__(self):
                self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))
                return self
            def __exit__(self, *args):
                pass
            def create(self, **payload):
                payloads.append(payload)
                class Stream:
                    def __enter__(self): return self
                    def __exit__(self, *args): pass
                    def __iter__(self):
                        yield SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content=action()), finish_reason='stop')])
                return Stream()
        turns = [{'role': 'system', 'content': '固定提示'}]
        with patch.object(chat, 'OpenAI', return_value=Client()):
            for _ in range(2):
                chat._generate(turns, load_tools(), ['answer', 'memory_search'])
        self.assertEqual(turns[0]['content'], '固定提示')
        for payload in payloads:
            self.assertEqual(payload['messages'][0]['content'].count('当前可用工具'), 1)


class PluginChatTests(unittest.TestCase):
    tearDown = ChatContextTests.tearDown
    run_chat = ChatContextTests.run_chat
    def setUp(self):
        ChatContextTests.setUp(self)
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'plugins.json'
        env = patch.dict('os.environ', {'QWEN_PLUGINS_CONFIG': str(self.path)})
        env.start()
        self.addCleanup(env.stop)
        self.write_config()

    def write_config(self, enabled=True):
        self.path.write_text(json.dumps({'schema_version': 1, 'plugins': [
            {'id': 'text', 'module': 'agent.plugins.text.plugin', 'enabled': enabled, 'config': {}}
        ]}))

    def test_plugin_executes_and_configuration_changes_next_round(self):
        seen = []
        def generate(turns, tools, allowed_actions):
            seen.append(list(allowed_actions))
            if len(seen) == 1:
                self.write_config(False)
                self.assertIn('text__count', tools)
                return action('text__count', '中文 a')
            self.assertNotIn('text__count', allowed_actions)
            self.assertEqual(json.loads(turns[-1]['content'][5:])['result'], {'count': 4})
            return action()
        with patch.object(chat, '_generate', side_effect=generate):
            reply, count, chars = chat.chat('计数')
        self.assertEqual((reply, count, chars), ('好的', len(chat._messages), sum(len(m['content']) for m in chat._messages)))
        with patch.object(chat, '_generate', side_effect=lambda turns, tools, allowed_actions: self.assertNotIn('text__count', tools) or action()):
            chat.chat('下一轮')
        before = copy.deepcopy(chat._messages)
        with self.assertRaisesRegex(RuntimeError, '模型行动不符合'):
            self.run_chat('禁用', [action('text__count', 'x')])
        self.assertEqual(chat._messages, before)

    def test_loading_failures_before_model_and_no_commit(self):
        self.run_chat('成功', [action()])
        before = copy.deepcopy(chat._messages)
        for raw in ['invalid', json.dumps({'schema_version': 1, 'plugins': [
            {'id': 'text', 'module': 'not_installed_xyz', 'enabled': True, 'config': {}}]})]:
            self.path.write_text(raw)
            with patch.object(chat, '_generate') as generate:
                with self.assertRaises(PluginLoadError): chat.chat('失败')
            generate.assert_not_called()
            self.assertEqual(chat._messages, before)

    def test_plugin_history_excludes_current_identical_input(self):
        contexts = []
        def factory(context, config):
            contexts.append(context)
            return [ToolSpec('text__history', '历史', str,
                             lambda text: [content for role, content in context.history if role == 'user' and content == text])]
        with patch.object(loader, 'import_module', return_value=SimpleNamespace(PLUGIN=PluginSpec('text', 1, factory))):
            for expected in [[], ['苹果']]:
                outputs = iter([action('text__history', '苹果'), action()])
                def generate(turns, tools, allowed_actions):
                    if turns[-1]['content'].startswith('[观察]'):
                        self.assertEqual(json.loads(turns[-1]['content'][5:])['result'], expected)
                    return next(outputs)
                with patch.object(chat, '_generate', side_effect=generate): chat.chat('苹果')
        self.assertEqual(contexts[0].history, ())
        self.assertEqual(sum(pair == ('user', '苹果') for pair in contexts[1].history), 1)

    def test_multiple_tools_limits_and_required_success(self):
        attempts = []
        def retry(value):
            attempts.append(value)
            if len(attempts) % 2: raise ValueError('retry')
            return value
        first = ToolSpec('text__first', '重试', str, retry, max_calls=2, require_success=True,
                         result_footer=lambda result: '页脚'+result)
        second = ToolSpec('text__second', '独立', str, lambda value: value)
        plugin = PluginSpec('text', 1, lambda c, p: [first, second])
        seen = []
        outputs = iter([action('text__first', 'x'), action('text__first', 'x'), action('text__second', 'y'), action()])
        def generate(turns, tools, allowed_actions):
            seen.append(allowed_actions[:])
            return next(outputs)
        with patch.object(loader, 'import_module', return_value=SimpleNamespace(PLUGIN=plugin)), patch.object(chat, '_generate', side_effect=generate):
            self.assertEqual(chat.chat('测试')[0], '好的\n页脚x')
        self.assertEqual(seen[1], ['text__first'])
        self.assertNotIn('text__first', seen[2])
        self.assertIn('text__second', seen[2])
        self.assertNotIn('text__second', seen[3])
        before = copy.deepcopy(chat._messages)
        fail = lambda value: (_ for _ in ()).throw(ValueError('always fails'))
        for tool, outputs, error in [
            (replace(first, handler=fail), [action(first.name, 'x')]*2, RuntimeError),
            (replace(first, handler=lambda v: v, result_footer=lambda v: (_ for _ in ()).throw(LookupError())), [action(first.name, 'x')], LookupError),
            (replace(first, handler=lambda v: (_ for _ in ()).throw(LookupError())), [action(first.name, 'x')], LookupError)]:
            with patch.object(loader, 'import_module', return_value=SimpleNamespace(PLUGIN=PluginSpec('text', 1, lambda c, p: [tool]))):
                with self.assertRaises(error): self.run_chat('失败', outputs)
            self.assertEqual(chat._messages, before)
        optional = replace(first, handler=fail, require_success=False)
        with patch.object(loader, 'import_module', return_value=SimpleNamespace(PLUGIN=PluginSpec('text', 1, lambda c, p: [optional]))):
            self.assertEqual(self.run_chat('可恢复', [action(first.name, 'x'), action()])[0], '好的')

    def test_real_generate_plugin_definition_and_schema(self):
        payloads = []
        class Client:
            def __enter__(self):
                self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))
                return self
            def __exit__(self, *args): pass
            def create(self, **payload):
                payloads.append(payload)
                class Stream:
                    def __enter__(self): return self
                    def __exit__(self, *args): pass
                    def __iter__(self):
                        yield SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content=action()), finish_reason='stop')])
                return Stream()
        with patch.object(chat, 'OpenAI', return_value=Client()):
            chat.chat('问题')
        payload = payloads[0]
        self.assertIn('text__count', payload['messages'][0]['content'])
        branches = payload['response_format']['json_schema']['schema']['anyOf']
        self.assertTrue(any(b['properties']['action']['enum'] == ['text__count'] for b in branches))
        self.assertEqual(chat._messages[0]['content'], chat.REACT_SYSTEM_PROMPT)

    def test_factory_failure_no_model_and_required_limit_rejects_repeated_action(self):
        self.run_chat('先成功', [action()])
        before = copy.deepcopy(chat._messages)
        def fail(context, config): raise RuntimeError('factory failure')
        with patch.object(loader, 'import_module', return_value=SimpleNamespace(PLUGIN=PluginSpec('text', 1, fail))), patch.object(chat, '_generate') as generate:
            with self.assertRaises(PluginLoadError): chat.chat('失败')
        generate.assert_not_called()
        self.assertEqual(chat._messages, before)
        tools = [ToolSpec('text__a', 'a', str, lambda value: value),
                 ToolSpec('text__b', 'b', str, lambda value: value)]
        with patch.object(loader, 'import_module', return_value=SimpleNamespace(PLUGIN=PluginSpec('text', 1, lambda c, p: tools))):
            with self.assertRaisesRegex(RuntimeError, '模型行动不符合'):
                self.run_chat('重复', [action('text__a', 'x'), action('text__b', 'y'), action('text__a', 'z')])
        self.assertEqual(chat._messages, before)
