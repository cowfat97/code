"""通过 hooks 注册监控，不向模型提供工具。"""

from agent.entities.hooks import HookSpec
from agent.entities.plugins import HookPluginSpec
from .observer import LangfuseObserver, _get_client


def create_hooks(config):
    if config:
        raise ValueError("Langfuse 不接受插件选项，请使用 LANGFUSE_* 环境变量")
    client = _get_client()
    if client is None:
        return []
    observer = LangfuseObserver(client)
    return [HookSpec("langfuse", observer.on_stage_start, observer.on_stage_end)]


PLUGIN = HookPluginSpec("langfuse", 1, create_hooks)
