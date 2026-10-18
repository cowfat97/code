"""真实 SDK 的本地导出验证，不向远程服务发送测试数据。"""
import importlib.util
import unittest

from agent.core.hook_runtime import HookRuntime
from agent.entities.hooks import HookSpec
from agent.plugins.langfuse.observer import LangfuseObserver


@unittest.skipUnless(importlib.util.find_spec("langfuse"), "Langfuse SDK is not installed")
class LangfuseSDKTests(unittest.TestCase):
    def test_nested_spans_error_and_flush_with_real_sdk(self):
        from langfuse import Langfuse
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

        exporter = InMemorySpanExporter()
        provider = TracerProvider()
        client = Langfuse(public_key="pk-lf-hook-runtime-sdk-test",
                          secret_key="sk-lf-hook-runtime-sdk-test",
                          base_url="http://127.0.0.1:1",
                          span_exporter=exporter, tracer_provider=provider)
        self.addCleanup(client.shutdown)
        observer = LangfuseObserver(client)
        runtime = HookRuntime([HookSpec("langfuse",observer.on_stage_start,observer.on_stage_end)])
        error = ValueError("test failure")
        with self.assertRaises(ValueError) as caught:
            with runtime.stage("root", "input"):
                with runtime.stage("child","input"):
                    raise error
        self.assertIs(caught.exception,error)
        client.flush()
        spans = {s.name:s for s in exporter.get_finished_spans()}
        self.assertEqual(set(spans),{"root","child"})
        self.assertIsNone(spans["root"].parent)
        self.assertEqual(spans["child"].parent.span_id,spans["root"].context.span_id)
        self.assertEqual(spans["root"].context.trace_id,spans["child"].context.trace_id)
        for span in spans.values():
            self.assertEqual(span.attributes["langfuse.observation.level"],"ERROR")
