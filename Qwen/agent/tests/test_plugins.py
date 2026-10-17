# 设计文档：[限定目录文件读取](../../../../文档/Qwen/Agent/限定目录文件读取/design/详细设计.md)
# 设计文档：[插件机制](../../../../文档/Qwen/Agent/插件机制/design/详细设计.md)
import json
import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch

from agent.entities import PluginContext
from agent.plugins import loader


class PluginTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'plugins.json'
        self.env = patch.dict('os.environ', {}, clear=True)
        self.env.start()
        self.addCleanup(self.env.stop)

    def config(self, plugins=()):
        self.path.write_text(json.dumps({'schema_version': 1, 'plugins': list(plugins)}))
        return self.path

    def text(self, enabled=True):
        return {'id': 'text', 'module': 'agent.plugins.text.plugin',
                'enabled': enabled, 'config': {}}

    def test_missing_default_and_explicit_empty(self):
        with patch.object(loader, 'DEFAULT_CONFIG_PATH', self.path):
            self.assertEqual(loader.load_plugins(PluginContext()), {})
        self.assertEqual(loader.load_plugins(PluginContext(), config_path=self.config()), {})

    def test_default_disabled(self):
        with patch.object(loader, 'import_module') as imported:
            self.assertEqual(loader.load_plugins(PluginContext(), config_path=self.config([self.text(False)])), {})
        imported.assert_not_called()

    def test_text_count_strict_unicode(self):
        tools = loader.load_plugins(PluginContext(), config_path=self.config([self.text()]))
        tool = tools['text__count']
        for value, expected in [('', 0), ('中文 a', 4), ('e\u0301', 2), ('😀', 1)]:
            self.assertEqual(tool.execute(value), {'count': expected})
        for value in [None, 1, []]:
            with self.assertRaises(ValueError):
                tool.execute(value)
        self.assertEqual(tool.max_calls, 1)
        self.assertFalse(tool.require_success)

    def load(self):
        return loader.load_plugins(PluginContext(), config_path=self.path)

    def test_strict_configuration(self):
        from agent.plugins.base import PluginLoadError
        valid = {'schema_version': 1, 'plugins': []}
        invalid = [[], {}, {**valid, 'extra': 1}, {**valid, 'schema_version': True},
                   {**valid, 'schema_version': 2}, {**valid, 'plugins': {}},
                   {**valid, 'metadata': {}}, {**valid, 'metadata': {'design_document': ''}},
                   {**valid, 'metadata': {'design_document': 'x', 'other': 0}}]
        for entry in [{**self.text(False), 'enabled': 0}, {**self.text(False), 'config': []},
                      {**self.text(False), 'id': 'Text'}, {**self.text(False), 'id': 'x'*33},
                      {**self.text(False), 'module': '.relative'},
                      {**self.text(False), 'module': 'bad-module'},
                      {**self.text(False), 'module': 'x..y'},
                      {**self.text(False), 'extra': 1}]:
            invalid.append({**valid, 'plugins': [entry]})
        invalid.append({**valid, 'plugins': [self.text(False), self.text(False)]})
        for data in invalid:
            with self.subTest(data=data):
                self.path.write_text(json.dumps(data))
                with self.assertRaisesRegex(PluginLoadError, 'stage=配置.*path='):
                    self.load()
        for raw in ['{"schema_version":1,"schema_version":1,"plugins":[]}',
                    '{"schema_version":1,"plugins":[],"metadata":{"design_document":NaN}}',
                    '{"schema_version":1,"plugins":[],"x":Infinity}',
                    '{"schema_version":1,"plugins":[{"id":"text","module":"agent.plugins.text.plugin","enabled":false,"config":{"value":1e400}}]}', 'broken']:
            self.path.write_text(raw)
            with self.assertRaises(PluginLoadError):
                self.load()

    def test_paths_and_read_errors(self):
        from agent.plugins.base import PluginLoadError
        self.config()
        with patch.dict('os.environ', {'QWEN_PLUGINS_CONFIG': 'missing'}):
            self.assertEqual(loader.load_plugins(PluginContext(), config_path=self.path), {})
        with patch.dict('os.environ', {'QWEN_PLUGINS_CONFIG': ''}):
            with self.assertRaises(PluginLoadError):
                loader.load_plugins(PluginContext())
        for path in ['', self.path.parent / 'missing', self.path.parent]:
            with self.assertRaises(PluginLoadError):
                loader.load_plugins(PluginContext(), config_path=path)
        with patch.object(loader, 'QWEN_ROOT', self.path.parent):
            self.assertEqual(loader.load_plugins(PluginContext(), config_path='plugins.json'), {})
        with patch.object(loader, 'DEFAULT_CONFIG_PATH', self.path), patch.object(Path, 'read_text', side_effect=PermissionError()):
            with self.assertRaises(PluginLoadError):
                loader.load_plugins(PluginContext())

    def test_disabled_never_imported_and_metadata_not_read(self):
        self.path.write_text(json.dumps({'schema_version': 1, 'plugins': [self.text(False)],
                                       'metadata': {'design_document': 'does-not-exist'}}))
        with patch.object(loader, 'import_module', side_effect=AssertionError('imported')):
            self.assertEqual(self.load(), {})

    def test_declarations_factories_and_tools(self):
        from dataclasses import replace
        from types import SimpleNamespace
        from agent.plugins.base import PluginLoadError
        from agent.entities import PluginSpec, ToolSpec
        good = ToolSpec('text__count', 'description', str, lambda value: value)
        make = lambda tools: PluginSpec('text', 1, lambda context, config: tools)
        self.config([self.text()])
        declarations = [None, object(), replace(make([good]), id='other'),
                        replace(make([good]), api_version=True), replace(make([good]), api_version=2),
                        replace(make([good]), create_tools=None)]
        for declaration in declarations:
            with self.subTest(declaration=declaration), patch.object(loader, 'import_module', return_value=SimpleNamespace(PLUGIN=declaration)):
                with self.assertRaisesRegex(PluginLoadError, 'stage=声明.*plugin=text'):
                    self.load()
        with patch.object(loader, 'import_module', return_value=SimpleNamespace()):
            with self.assertRaises(PluginLoadError): self.load()
        invalid_tools = [[], {}, (t for t in [good]), [object()], [good, good]]
        for field, value in [('name', 'count'), ('name', 'text__Count'), ('name', 'text__'+'x'*33),
                             ('description', ''), ('handler', None), ('max_calls', True),
                             ('max_calls', 0), ('require_success', 1), ('result_footer', 'x'),
                             ('argument_type', object())]:
            invalid_tools.append([good, replace(good, **{field: value})])
        for tools in invalid_tools:
            with self.subTest(tools=tools), patch.object(loader, 'import_module', return_value=SimpleNamespace(PLUGIN=make(tools))):
                with self.assertRaisesRegex(PluginLoadError, 'stage=工具校验'):
                    self.load()
        for schema in [[], {'value': object()}, {'value': float('nan')}]:
            with patch.object(loader, 'import_module', return_value=SimpleNamespace(PLUGIN=make([good]))), patch.object(ToolSpec, 'parameters', return_value=schema):
                with self.assertRaises(PluginLoadError): self.load()
        with patch.object(loader, 'import_module', return_value=SimpleNamespace(PLUGIN=make([good]))):
            with self.assertRaises(PluginLoadError):
                loader.load_plugins(PluginContext(), config_path=self.path, reserved_names=['text__count'])
        long_id = 'x'*32
        self.config([{**self.text(), 'id': long_id}])
        long_spec = PluginSpec(long_id, 1, lambda c, p: [replace(good, name=long_id+'__'+'x'*31)])
        with patch.object(loader, 'import_module', return_value=SimpleNamespace(PLUGIN=long_spec)):
            with self.assertRaises(PluginLoadError): self.load()

    def test_error_chains_and_no_handler_execution(self):
        from types import SimpleNamespace
        from unittest.mock import Mock
        from agent.plugins.base import PluginLoadError
        from agent.entities import PluginSpec, ToolSpec
        self.config([self.text()])
        for stage in ['导入', '工厂']:
            error = RuntimeError('specific failure')
            target = patch.object(loader, 'import_module', side_effect=error) if stage == '导入' else patch.object(loader, 'import_module', return_value=SimpleNamespace(PLUGIN=PluginSpec('text', 1, Mock(side_effect=error))))
            with target, self.assertRaisesRegex(PluginLoadError, 'stage='+stage) as caught:
                self.load()
            self.assertIs(caught.exception.__cause__, error)
        with patch.object(loader, 'import_module', side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt): self.load()
        handler, footer = Mock(), Mock()
        tool = ToolSpec('text__one', 'one', str, handler, result_footer=footer)
        def factory(context, config):
            config['nested'].append('changed')
            return [tool]
        self.config([{**self.text(), 'config': {'nested': []}}])
        with patch.object(loader, 'import_module', return_value=SimpleNamespace(PLUGIN=PluginSpec('text', 1, factory))):
            self.assertEqual(self.load(), {'text__one': tool})
        handler.assert_not_called()
        footer.assert_not_called()
        self.assertEqual(json.loads(self.path.read_text())['plugins'][0]['config'], {'nested': []})

    def test_text_rejects_plugin_options(self):
        from agent.plugins.base import PluginLoadError
        self.config([{**self.text(), 'config': {'option': 1}}])
        with self.assertRaisesRegex(PluginLoadError, 'stage=工厂'):
            self.load()

    def test_registry_snapshot_and_config_forwarding(self):
        from dataclasses import FrozenInstanceError
        from types import SimpleNamespace
        from agent.entities import PluginSpec, ToolSpec
        from agent.tools.registry import load_tools
        history = [{'role': 'user', 'content': '苹果'}]
        contexts = []
        def create(context, config):
            contexts.append(context)
            with self.assertRaises(FrozenInstanceError): context.history = ()
            return [ToolSpec('text__history', 'history', str, lambda _: context.history)]
        self.config([self.text()])
        with patch.object(loader, 'import_module', return_value=SimpleNamespace(PLUGIN=PluginSpec('text', 1, create))):
            tools = load_tools(history, plugin_config_path=self.path)
        history[0]['content'] = 'changed'
        history.append({'role': 'user', 'content': 'new'})
        self.assertEqual(contexts[0].history, (('user', '苹果'),))
        self.assertEqual(tools['text__history'].execute('x'), (('user', '苹果'),))
        self.assertEqual(tools['memory_search'].execute('苹果')['matches'], ['苹果'])
        self.assertEqual(set(load_tools()), {'calculator', 'memory_search', 'files__read_text'})
        for message in [{'role': 1, 'content': 'x'}, {'role': 'user', 'content': []}, {}]:
            with self.assertRaises(ValueError): load_tools([message])

    def test_two_factories_share_immutable_round_snapshot(self):
        from dataclasses import FrozenInstanceError
        from types import SimpleNamespace
        from agent.entities import PluginSpec, ToolSpec
        from agent.tools.registry import load_tools
        source = [{'role': 'user', 'content': 'original'}]
        seen = []
        def factory(plugin_id):
            def create(context, config):
                seen.append(context)
                with self.assertRaises(TypeError): context.history[0][1] = 'corrupt'
                with self.assertRaises(FrozenInstanceError): context.history += (('user', 'corrupt'),)
                source[0]['content'] = 'changed'
                return [ToolSpec(plugin_id+'__one', 'one', str, lambda _: context.history)]
            return SimpleNamespace(PLUGIN=PluginSpec(plugin_id, 1, create))
        self.config([{**self.text(), 'id': name, 'module': name} for name in ['first', 'second']])
        with patch.object(loader, 'import_module', side_effect=lambda name: factory(name)):
            tools = load_tools(source, plugin_config_path=self.path)
        self.assertIs(seen[0], seen[1])
        for name in ['first__one', 'second__one']:
            self.assertEqual(tools[name].execute('x'), (('user', 'original'),))
