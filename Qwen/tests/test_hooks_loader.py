import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from agent.entities.hooks import HookSpec
from agent.entities.plugins import HookPluginSpec, PluginContext
from agent.plugins import hooks_loader, loader
from agent.plugins.base import PluginLoadError


class HookLoaderTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "plugins.json"

    def config(self, entries=(), tools=()):
        self.path.write_text(json.dumps({"schema_version":1,"plugins":list(tools),
                                        "hook_plugins":list(entries)}), encoding="utf-8")
        return self.path

    def entry(self, **changes):
        return dict(id="monitor", module="fake.monitor", enabled=True, config={}, **changes)

    def test_disabled_not_imported_and_old_config_supported(self):
        self.path.write_text('{"schema_version":1,"plugins":[]}', encoding="utf-8")
        with patch.object(hooks_loader, "import_module") as imported:
            hooks_loader.load_hook_runtime(config_path=self.path)
            self.config([dict(self.entry(), enabled=False)])
            hooks_loader.load_hook_runtime(config_path=self.path)
        imported.assert_not_called()

    def test_request_instances_and_not_tool_registration(self):
        calls = []
        def factory(config):
            seen = []
            calls.append(seen)
            return [HookSpec("monitor", lambda e: seen.append(e), lambda *a: None)]
        self.config([self.entry()])
        with patch.object(hooks_loader, "import_module",
                          return_value=SimpleNamespace(PLUGIN=HookPluginSpec("monitor",1,factory))):
            a = hooks_loader.load_hook_runtime(config_path=self.path)
            b = hooks_loader.load_hook_runtime(config_path=self.path)
        with a.stage("a", None): pass
        with b.stage("b", None): pass
        self.assertNotEqual(calls[0][0].request_id,calls[1][0].request_id)
        self.assertEqual(loader.load_plugins(PluginContext(),config_path=self.path), {})

    def test_optional_plugin_failures_are_isolated(self):
        self.config([self.entry()])
        for module in [SimpleNamespace(), SimpleNamespace(PLUGIN=HookPluginSpec("wrong",1,lambda c: [])),
                       SimpleNamespace(PLUGIN=HookPluginSpec("monitor",1,Mock(side_effect=ValueError()))),
                       SimpleNamespace(PLUGIN=HookPluginSpec("monitor",1,lambda c: [object()]))]:
            with patch.object(hooks_loader,"import_module",return_value=module), self.assertLogs(
                    hooks_loader.logger,level="WARNING"):
                hooks_loader.load_hook_runtime(config_path=self.path)
        with patch.object(hooks_loader,"import_module",side_effect=ImportError()), self.assertLogs(
                hooks_loader.logger,level="WARNING"):
            hooks_loader.load_hook_runtime(config_path=self.path)

    def test_strict_hook_config_and_cross_kind_ids(self):
        for entries in [{}, [dict(self.entry(),enabled=1)], [self.entry(),self.entry()]]:
            self.path.write_text(json.dumps({"schema_version":1,"plugins":[],"hook_plugins":entries}))
            with self.assertRaises(PluginLoadError):
                hooks_loader.load_hook_runtime(config_path=self.path)
        self.config([self.entry()], [self.entry()])
        with self.assertRaises(PluginLoadError):
            hooks_loader.load_hook_runtime(config_path=self.path)
