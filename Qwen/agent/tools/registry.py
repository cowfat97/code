# 设计文档：[记忆工具化改造](../../../../文档/Qwen/Agent/记忆工具化改造/design/详细设计.md)
"""显式注册可信工具模块；新增工具只需在此登记模块，不修改聊天流程。"""
from importlib import import_module

TOOL_MODULES = (
    "agent.tools.calculator",
    "agent.tools.memory_search",
)


def load_tools(history=()):
    tools = {}
    for module_name in TOOL_MODULES:
        module = import_module(module_name)
        binder = getattr(module, "bind_history", None)
        spec = binder(history) if binder is not None else module.TOOL
        if spec.name == "answer" or spec.name in tools or spec.max_calls < 1:
            raise ValueError(f"工具注册无效：{spec.name}")
        tools[spec.name] = spec
    return tools


def action_schema(tools, allowed):
    branches = []
    for name in allowed:
        argument = {"type": "string", "minLength": 1} if name == "answer" else tools[name].parameters()
        branches.append({"type": "object", "properties": {
            "thought": {"type": "string"}, "action": {"type": "string", "enum": [name]},
            "argument": argument}, "required": ["thought", "action", "argument"],
            "additionalProperties": False})
    return {"anyOf": branches}
