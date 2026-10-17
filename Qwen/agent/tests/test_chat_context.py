# 设计文档：[记忆工具化改造](../../../../文档/Qwen/Agent/记忆工具化改造/design/详细设计.md)
import copy
from dataclasses import replace
import json
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from agent.workflow import vllm_chat as chat
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
