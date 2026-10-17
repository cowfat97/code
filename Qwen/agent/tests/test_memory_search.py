# 设计文档：[记忆工具化改造](../../../../文档/Qwen/Agent/记忆工具化改造/design/详细设计.md)
import ast
import copy
import importlib.util
from pathlib import Path
import unittest

from agent.tools import memory_search
from agent.tools.registry import load_tools


class MemorySearchTests(unittest.TestCase):
    def test_recent_matches_filter_and_no_match(self):
        history = [{'role': 'user', 'content': f'苹果{i}'} for i in range(5)]
        history += [{'role': role, 'content': text} for role, text in [
            ('system', '苹果'), ('assistant', '苹果'),
            ('user', '[观察] 苹果'), ('user', '<think>苹果')]]
        before = copy.deepcopy(history)
        tool = memory_search.bind_history(history)
        self.assertEqual(tool.execute(' 苹果 '), {'matches': ['苹果2', '苹果3', '苹果4'], 'found': True})
        self.assertEqual(tool.execute('香蕉'), {'matches': [], 'found': False})
        self.assertEqual(history, before)

    def test_snapshot_and_default_and_rebinding(self):
        history = [{'role': 'user', 'content': '原文'}]
        bound = load_tools(history)['memory_search']
        history[0]['content'] = '改写'
        history.append({'role': 'user', 'content': '原文新增'})
        self.assertEqual(bound.execute('原文')['matches'], ['原文'])
        self.assertEqual(load_tools(history)['memory_search'].execute('原文')['matches'], ['原文新增'])
        self.assertFalse(load_tools()['memory_search'].execute('原文')['found'])
        self.assertFalse(memory_search.TOOL.execute('原文')['found'])
        self.assertIn('calculator', load_tools())

    def test_argument_boundaries(self):
        tool = memory_search.TOOL
        for value in ['', '  ', None, 1, 'a' * 257]:
            with self.subTest(value=value), self.assertRaises(ValueError):
                tool.execute(value)
        for value in ['a', 'a' * 256]:
            self.assertEqual(tool.execute(value), {'matches': [], 'found': False})

    def test_removed_package_and_dependency_direction(self):
        root = Path(__file__).resolve().parents[1]
        self.assertFalse((root / 'memory/session_memory.py').exists())
        self.assertFalse((root / 'memory/__init__.py').exists())
        # A leftover bytecode directory may form a namespace package; the removed module must not resolve.
        try:
            spec = importlib.util.find_spec('agent.memory.session_memory')
        except ModuleNotFoundError:
            spec = None
        self.assertIsNone(spec)
        for path in root.rglob('*.py'):
            if 'tests' in path.parts:
                continue
            tree = ast.parse(path.read_text())
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom):
                    self.assertFalse((node.module or '').startswith('agent.memory'), str(path))
                    if 'tools' in path.parts:
                        self.assertFalse((node.module or '').startswith('agent.workflow'), str(path))
                elif isinstance(node, ast.Import):
                    for alias in node.names:
                        self.assertFalse(alias.name.startswith('agent.memory'), str(path))
                        if 'tools' in path.parts:
                            self.assertFalse(alias.name.startswith('agent.workflow'), str(path))
