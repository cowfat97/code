# 设计文档：[插件机制](../../../../文档/Qwen/Agent/插件机制/design/详细设计.md)
# 设计文档：[记忆工具化改造](../../../../文档/Qwen/Agent/记忆工具化改造/design/详细设计.md)
"""装配内置工具与可信本地插件，每轮绑定独立历史快照。"""
from importlib import import_module
from agent.entities import PluginContext
from agent.plugins.loader import load_plugins

TOOL_MODULES = (
    "agent.tools.math.calculator",
    "agent.tools.memory.search",
)


def load_tools(history=(), *, plugin_config_path=None):
    snapshot = []
    for message in history:
        if not isinstance(message, dict) or not isinstance(message.get('role'), str) or not isinstance(message.get('content'), str):
            raise ValueError('历史消息role/content必须为字符串')
        snapshot.append((message['role'], message['content']))
    context = PluginContext(tuple(snapshot))
    bound_history = [{'role': role, 'content': content} for role, content in context.history]
    tools = {}
    for module_name in TOOL_MODULES:
        module = import_module(module_name)
        binder = getattr(module, "bind_history", None)
        spec = binder(bound_history) if binder is not None else module.TOOL
        if spec.name == "answer" or spec.name in tools or spec.max_calls < 1:
            raise ValueError(f"工具注册无效：{spec.name}")
        tools[spec.name] = spec
    tools.update(load_plugins(context, config_path=plugin_config_path, reserved_names=tools))
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
