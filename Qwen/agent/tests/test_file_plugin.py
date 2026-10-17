# 设计文档：[限定目录文件读取](../../../../文档/Qwen/Agent/限定目录文件读取/design/详细设计.md)
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from agent.plugins.base import PluginContext
from agent.plugins.files import plugin
from agent.tools.registry import load_tools


class FilePluginTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.root_patch = patch.object(plugin, 'ROOT', self.root)
        self.root_patch.start()
        self.addCleanup(self.root_patch.stop)
        self.tool = plugin.PLUGIN.create_tools(PluginContext(), {})[0]

    def read(self, **kwargs):
        return self.tool.execute({'path': 'a.txt', **kwargs})

    def test_unicode_bom_lines_and_eof(self):
        (self.root / 'a.txt').write_bytes(b'\xef\xbb\xbf' + '中文\r\nsecond\nlast'.encode())
        self.assertEqual(self.read(start_line=2, line_count=1), dict(path='a.txt', start_line=2, end_line=2, total_lines=3, content='second\n', eof=False))
        self.assertEqual(self.read()['content'], '中文\r\nsecond\nlast')
        self.assertTrue(self.read(start_line=3)['eof'])
        result = self.read(start_line=4)
        self.assertEqual((result['content'], result['end_line'], result['eof']), ('', None, True))
        (self.root / 'a.txt').write_bytes(b'')
        self.assertEqual(self.read()['total_lines'], 0)
        self.assertIsNone(self.read()['end_line'])

    def test_nested_file_and_symlinks(self):
        nested = self.root / 'nested'
        nested.mkdir()
        (nested / 'a.txt').write_text('one\ntwo\n')
        self.assertEqual(self.read(path='nested/a.txt', line_count=1)['content'], 'one\n')
        (self.root / 'a.txt').write_text('inside')
        (self.root / 'inside_link').symlink_to(self.root / 'a.txt')
        with self.assertRaises(ValueError): self.read(path='inside_link')
        (self.root / 'a.txt').write_text('line\n' * 201)
        self.assertFalse(self.read(line_count=200)['eof'])
        self.assertEqual(self.read(start_line=201, line_count=1)['end_line'], 201)

    def test_schema_and_strict_arguments(self):
        schema = self.tool.parameters()
        self.assertFalse(schema['additionalProperties'])
        self.assertEqual(self.tool.max_calls, 1)
        self.assertFalse(self.tool.require_success)
        for args in [{}, {'path': ''}, {'path': 1}, {'path': 'a', 'other': 1},
                     *[{'path': 'a', 'start_line': v} for v in [0, True, '1', 1.0]],
                     *[{'path': 'a', 'line_count': v} for v in [0, 201, False, '1', 1.0]]]:
            with self.subTest(args=args), self.assertRaises(ValueError):
                self.tool.execute(args)

    def test_path_rejections(self):
        for name in ['/etc/passwd', '../a', 'x/../a', 'x\\a', '.env', 'x/.a', 'a\0b', '.', 'a//b', 'a/']:
            with self.subTest(name=name), self.assertRaises(ValueError) as caught:
                self.read(path=name)
            self.assertNotIn(str(self.root), str(caught.exception))

    def test_invalid_file_types_and_encoding(self):
        (self.root / 'dir').mkdir()
        os.mkfifo(self.root / 'fifo')
        (self.root / 'link').symlink_to('/dev/null')
        (self.root / 'parent').symlink_to(self.root, target_is_directory=True)
        for name in ['missing', 'dir', 'fifo', 'link', 'parent/a.txt']:
            with self.subTest(name=name), self.assertRaises(ValueError):
                self.read(path=name)
        for data in [b'bad\0text', b'\xff']:
            (self.root / 'a.txt').write_bytes(data)
            with self.assertRaises(ValueError): self.read()
        with patch.object(plugin.os, 'fstat', return_value=type('Stat', (), {'st_mode': 0o020000, 'st_size': 0})()):
            with self.assertRaises(ValueError): self.read()

    def test_limits(self):
        for size, succeeds in [(65536, True), (65537, False)]:
            (self.root / 'a.txt').write_bytes(b'a\n' * (size // 2) + b'a' * (size % 2))
            if succeeds: self.assertEqual(len(self.read(line_count=200)['content']), 400)
            else:
                with self.assertRaises(ValueError): self.read()
        (self.root / 'a.txt').write_text('x' * 16001)
        with self.assertRaisesRegex(ValueError, '行数'): self.read()
        (self.root / 'a.txt').write_text('x' * 16000)
        self.assertEqual(len(self.read()['content']), 16000)

    def test_bounded_actual_read_and_fd_cleanup(self):
        (self.root / 'a.txt').write_text('ok')
        real_open, real_close = os.open, os.close
        opened, closed = [], []
        def opening(*args, **kwargs):
            fd = real_open(*args, **kwargs)
            opened.append(fd)
            return fd
        def closing(fd):
            closed.append(fd)
            return real_close(fd)
        for fail in [False, True]:
            opened.clear(); closed.clear()
            with patch.object(plugin.os, 'open', side_effect=opening), patch.object(plugin.os, 'close', side_effect=closing):
                if fail:
                    with patch.object(plugin.os, 'read', side_effect=OSError('private content')):
                        with self.assertRaises(ValueError) as caught: self.read()
                        self.assertNotIn('private content', str(caught.exception))
                else: self.read()
            self.assertCountEqual(opened, closed)
        with patch.object(plugin.os, 'read', return_value=b'x' * 65537):
            with self.assertRaises(ValueError): self.read()

    def test_unsupported_platform_and_config(self):
        with patch.object(plugin.os, 'supports_dir_fd', set()):
            with self.assertRaisesRegex(ValueError, '支持'): self.read()
        for config in [{'root': '/'}, {'design_document': ''}, {'design_document': 1}, {'design_document': 'x', 'extra': 1}]:
            with self.assertRaises(ValueError): plugin.PLUGIN.create_tools(PluginContext(), config)
        with patch.object(Path, 'read_text', side_effect=AssertionError('metadata read')):
            plugin.PLUGIN.create_tools(PluginContext(), {'design_document': 'missing'})

    def test_real_registry(self):
        (self.root / 'a.txt').write_text('registered')
        tools = load_tools()
        self.assertEqual(tools['files__read_text'].execute({'path': 'a.txt'})['content'], 'registered')
