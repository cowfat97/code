import unittest
from unittest.mock import patch
from types import SimpleNamespace
from .base import ToolSpec
from .registry import load_tools, action_schema


class RegistryTests(unittest.TestCase):
    def test_loaded_tools_and_verification(self):
        tools = load_tools()
        result = tools["calculator"].execute("x*1.2*0.8=96")
        self.assertTrue(result["verification"]["valid"])
        self.assertEqual(result["calculation"]["result"], "100")
        with self.assertRaises(ValueError):
            tools["calculator"].execute({"expression": "1+1"})

    def test_new_tool_without_chat_changes(self):
        spec = ToolSpec("echo", "测试工具", str, lambda value: value)
        with patch("tool.registry.TOOL_MODULES", ("example",)), patch(
            "tool.registry.import_module", return_value=SimpleNamespace(TOOL=spec)
        ):
            tools = load_tools()
        self.assertEqual(tools["echo"].execute("hello"), "hello")
        schema = action_schema(tools, ["answer", "echo"])
        self.assertEqual(schema["anyOf"][1]["properties"]["action"]["enum"], ["echo"])
        self.assertNotIn("handler", tools["echo"].definition())


if __name__ == "__main__":
    unittest.main()
