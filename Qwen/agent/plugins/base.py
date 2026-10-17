# 设计文档：[插件机制](../../../../文档/Qwen/Agent/插件机制/design/详细设计.md)
from dataclasses import dataclass
from typing import Callable, Mapping, Sequence
from agent.tools.base import ToolSpec


@dataclass(frozen=True)
class PluginContext:
    history: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True)
class PluginSpec:
    id: str
    api_version: int
    create_tools: Callable[[PluginContext, Mapping[str, object]], Sequence[ToolSpec]]


class PluginLoadError(ValueError):
    """插件配置或装配失败，本轮不应继续生成。"""
