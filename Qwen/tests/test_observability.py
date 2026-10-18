import os
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock, patch

from agent.core.hook_runtime import HookRuntime
from agent.entities.hooks import StageEvent, StageResult
from agent.plugins.langfuse import observer, plugin
from agent.core.workflow import chat_workflow


class LangfusePluginTests(unittest.TestCase):
    def setUp(self):
        observer._create_client.cache_clear()
        self.addCleanup(observer._create_client.cache_clear)

    def test_no_credentials_and_disabled_no_sdk_import(self):
        with patch.dict(os.environ, {}, clear=True), patch.dict("sys.modules", {"langfuse": None}):
            with self.assertLogs(observer.logger, level="WARNING"):
                self.assertEqual(plugin.create_hooks({}), [])

    def test_local_endpoint_cached_client_and_safe_exit_flush(self):
        client = Mock()
        env = {"LANGFUSE_PUBLIC_KEY":"pk-test", "LANGFUSE_SECRET_KEY":"sk-test"}
        for override in (None, "http://localhost:3010"):
            observer._create_client.cache_clear()
            values = dict(env)
            if override: values["LANGFUSE_BASE_URL"] = override
            constructor = Mock(return_value=client)
            with patch.dict(os.environ, values, clear=True), patch.dict(
                    "sys.modules", {"langfuse":SimpleNamespace(Langfuse=constructor)}), patch.object(
                    observer.atexit, "register") as registered:
                self.assertIs(observer._get_client(), client)
                self.assertIs(observer._get_client(), client)
            constructor.assert_called_once_with(public_key="pk-test",secret_key="sk-test",
                base_url=override or "http://127.0.0.1:3000")
            registered.assert_called_once()
            callback, *args = registered.call_args.args
            callback(*args)
        self.assertEqual(client.flush.call_count, 2)
        client.flush.side_effect = ValueError()
        with self.assertLogs(observer.logger, level="WARNING"):
            callback(*args)

    def test_scope_exits_even_if_update_fails(self):
        client = MagicMock()
        scope = client.start_as_current_observation.return_value
        span = scope.__enter__.return_value
        span.update.side_effect = ValueError("update failed")
        hook = observer.LangfuseObserver(client)
        event = StageEvent("r","s",None,"root","input")
        token = hook.on_stage_start(event)
        result = StageResult("error",None,"ValueError","business",1)
        with self.assertRaises(ValueError):
            hook.on_stage_end(event,token,result)
        scope.__exit__.assert_called_once_with(None,None,None)

    def test_real_workflow_nested_stages_and_original_failure(self):
        records, active = [], []
        class Client:
            def start_as_current_observation(self, **fields):
                span = Mock()
                record = dict(fields=fields, span=span, parent=active[-1] if active else None)
                records.append(record)
                class Scope:
                    def __enter__(self):
                        active.append(record)
                        return span
                    def __exit__(self,*error):
                        active.pop()
                return Scope()
        client = Client()
        with patch.object(plugin, "_get_client", return_value=client):
            runtime = HookRuntime(plugin.create_hooks({}))
        with patch.object(chat_workflow,"process_request",return_value="request"), patch.object(
                chat_workflow,"build_agent",return_value="agent"), patch.object(
                chat_workflow,"chat",return_value=("reply",3,10)):
            self.assertEqual(chat_workflow.orchestrate_chat("input",runtime=runtime),("reply",3,10))
        self.assertEqual([r["fields"]["name"] for r in records],
                         ["orchestrate_chat","process_request","build_agent","chat"])
        self.assertTrue(all(r["parent"] is records[0] for r in records[1:]))
        self.assertEqual(records[0]["span"].update.call_args.kwargs["output"], ["reply",3,10])
        self.assertEqual(active, [])
        records.clear()
        error = ValueError("business")
        with patch.object(chat_workflow,"process_request",side_effect=error), patch.object(
                chat_workflow,"build_agent") as build:
            with self.assertRaises(ValueError) as caught:
                chat_workflow.orchestrate_chat("input",runtime=runtime)
        self.assertIs(caught.exception,error)
        build.assert_not_called()
        self.assertEqual(len(records),2)
        self.assertEqual(active,[])
        for record in records:
            self.assertEqual(record["span"].update.call_args.kwargs["level"],"ERROR")

    def test_workflow_without_runtime_does_not_load_plugins(self):
        with patch.object(chat_workflow,"process_request",return_value="request"), patch.object(
                chat_workflow,"build_agent",return_value="agent"), patch.object(
                chat_workflow,"chat",return_value=("ok",1,2)):
            self.assertEqual(chat_workflow.orchestrate_chat("input"),("ok",1,2))

    def test_optional_initialization_and_options_failures(self):
        with self.assertRaises(ValueError):
            plugin.create_hooks({"unknown":True})
        with patch.dict(os.environ,{"LANGFUSE_PUBLIC_KEY":"p","LANGFUSE_SECRET_KEY":"s"}), patch.dict(
                "sys.modules",{"langfuse":None}), self.assertLogs(observer.logger,level="WARNING"):
            self.assertEqual(plugin.create_hooks({}),[])
