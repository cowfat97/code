"""插件工厂共享的上下文和插件注册声明。"""

from dataclasses import dataclass
from typing import Callable, Mapping, Sequence

from ..tools import ToolSpec


@dataclass(frozen=True)
class PluginContext:
    """本轮装配插件时的不可变历史快照，不包含当前用户输入。"""

    # 每项为 (role, content)，来自此前已提交的消息。
    history: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True)
class PluginSpec:
    """插件模块通过 PLUGIN 导出的声明，由加载器校验并装配工具。"""

    id: str  # 插件标识，须与 plugins.json 中的 id 一致。
    api_version: int  # 插件协议版本；当前加载器只接受整数 1。
    # 工厂接收本轮上下文和插件配置，返回供该轮使用的工具定义。
    create_tools: Callable[[PluginContext, Mapping[str, object]], Sequence[ToolSpec]]
