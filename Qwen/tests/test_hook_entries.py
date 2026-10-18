import unittest
from unittest.mock import Mock, patch

import quick_start
from agent.web import controller
from agent.core.hook_runtime import HookRuntime


class HookEntryTests(unittest.TestCase):
    def test_web_passes_request_runtime_and_preserves_response(self):
        runtime = HookRuntime()
        with patch.object(controller, "load_hook_runtime", return_value=runtime) as load, patch.object(
                controller, "orchestrate_chat", return_value=("reply",3,5)) as chat:
            result = controller.chat_endpoint(controller.ChatRequest(message="hello"))
        self.assertEqual(result, {"reply":"reply","count":3,"chars":5})
        load.assert_called_once_with()
        chat.assert_called_once_with("hello",runtime=runtime)

    def test_cli_creates_runtime_per_request(self):
        first, second = HookRuntime(), HookRuntime()
        with patch.object(quick_start,"load_hook_runtime",side_effect=[first,second]) as load, patch.object(
                quick_start,"orchestrate_chat",return_value=("reply",1,2)) as chat, patch(
                "builtins.input",side_effect=["one","two","quit"]), patch("builtins.print"), patch.object(
                quick_start,"setup_logging"):
            quick_start.main()
        self.assertEqual(load.call_count,2)
        self.assertIs(chat.call_args_list[0].kwargs["runtime"],first)
        self.assertIs(chat.call_args_list[1].kwargs["runtime"],second)
