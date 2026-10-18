import os
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock, patch

from agent.infrastructure import observability
from agent.core.workflow import chat_workflow


class RecordingClient:
    def __init__(self):
        self.spans = []
        self.active = []

    def start_as_current_observation(self, **fields):
        client = self
        span = Mock()
        span.fields = fields
        span.parent = self.active[-1] if self.active else None
        self.spans.append(span)

        class Scope:
            def __enter__(self):
                client.active.append(span)
                return span

            def __exit__(self, *error):
                span.error = error[1]
                client.active.pop()

        return Scope()


class ObservabilityTests(unittest.TestCase):
    def setUp(self):
        observability._get_client.cache_clear()
        self.addCleanup(observability._get_client.cache_clear)

    def run_workflow(self, client):
        with patch.object(observability, "_get_client", return_value=client), patch.object(
            chat_workflow, "process_request", return_value="request"
        ), patch.object(chat_workflow, "build_agent", return_value="agent"), patch.object(
            chat_workflow, "chat", return_value=("reply", 3, 10)
        ):
            return chat_workflow.orchestrate_chat("input")

    def test_nested_stages_preserve_result_and_record_io(self):
        client = RecordingClient()
        self.assertEqual(self.run_workflow(client), ("reply", 3, 10))
        root, request, agent, chat = client.spans
        self.assertEqual([s.fields["name"] for s in client.spans],
                         ["orchestrate_chat", "process_request", "build_agent", "chat"])
        self.assertIsNone(root.parent)
        for child in (request, agent, chat):
            self.assertIs(child.parent, root)
        self.assertEqual([s.fields["input"] for s in client.spans],
                         ["input", "input", "request", "agent"])
        request.update.assert_called_once_with(output="request")
        agent.update.assert_called_once_with(output="agent")
        chat.update.assert_called_once_with(output=("reply", 3, 10))
        root.update.assert_called_once_with(output=("reply", 3, 10))

    def test_failure_marks_stage_and_root_and_stops_following_stages(self):
        for failed in ("process_request", "build_agent", "chat"):
            with self.subTest(failed=failed):
                client = RecordingClient()
                error = ValueError("business failure")
                with patch.object(observability, "_get_client", return_value=client), patch.object(
                    chat_workflow, "process_request", return_value="request"
                ) as process, patch.object(chat_workflow, "build_agent", return_value="agent") as build, patch.object(
                    chat_workflow, "chat", return_value=("reply", 3, 10)
                ) as chat:
                    {"process_request": process, "build_agent": build, "chat": chat}[failed].side_effect = error
                    with self.assertRaises(ValueError) as caught:
                        chat_workflow.orchestrate_chat("input")
                    self.assertIs(caught.exception, error)
                    self.assertIs(client.spans[0].error, error)
                    self.assertIs(client.spans[-1].error, error)
                    client.spans[-1].update.assert_called_once_with(
                        level="ERROR", status_message="business failure"
                    )
                    if failed == "process_request":
                        build.assert_not_called()
                    if failed != "chat":
                        chat.assert_not_called()

    def test_no_credentials_preserves_chat(self):
        with patch.dict(os.environ, {}, clear=True), self.assertLogs(observability.logger, level="WARNING"):
            self.assertIsNone(observability._get_client())
        self.assertEqual(self.run_workflow(None), ("reply", 3, 10))

    def test_client_uses_local_endpoint_and_allows_override(self):
        for override in (None, "http://localhost:3000"):
            with self.subTest(override=override):
                observability._get_client.cache_clear()
                constructor = Mock()
                env = {"LANGFUSE_PUBLIC_KEY": "test-public", "LANGFUSE_SECRET_KEY": "test-secret"}
                if override:
                    env["LANGFUSE_BASE_URL"] = override
                with patch.dict(os.environ, env, clear=True), patch.dict(
                    "sys.modules", {"langfuse": SimpleNamespace(Langfuse=constructor)}
                ):
                    self.assertIs(observability._get_client(), constructor.return_value)
                constructor.assert_called_once_with(
                    public_key="test-public", secret_key="test-secret",
                    base_url=override or "http://192.168.1.177:3000"
                )

    def test_monitoring_start_and_output_failures_do_not_break_chat(self):
        client = Mock()
        client.start_as_current_observation.side_effect = RuntimeError("unavailable")
        with self.assertLogs(observability.logger, level="WARNING"):
            self.assertEqual(self.run_workflow(client), ("reply", 3, 10))
        client = RecordingClient()
        original = client.start_as_current_observation

        def broken_update(**fields):
            scope = original(**fields)
            client.spans[-1].update.side_effect = RuntimeError("unavailable")
            return scope

        client.start_as_current_observation = broken_update
        with self.assertLogs(observability.logger, level="WARNING"):
            self.assertEqual(self.run_workflow(client), ("reply", 3, 10))

    def test_monitoring_exit_failure_does_not_replace_business_error(self):
        client = MagicMock()
        scope = client.start_as_current_observation.return_value
        scope.__exit__.side_effect = RuntimeError("monitoring failure")
        error = ValueError("original failure")
        with patch.object(observability, "_get_client", return_value=client), self.assertLogs(
            observability.logger, level="WARNING"
        ), self.assertRaises(ValueError) as caught:
            with observability.observe_stage("stage", "input"):
                raise error
        self.assertIs(caught.exception, error)


if __name__ == "__main__":
    unittest.main()
