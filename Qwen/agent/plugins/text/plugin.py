# 设计文档：[插件机制](../../../../../文档/Qwen/Agent/插件机制/design/详细设计.md)
from agent.plugins.base import PluginSpec
from agent.tools.base import ToolSpec


def create_tools(context, config):
    if config:
        raise ValueError('text插件仅接受空配置')
    return [ToolSpec('text__count', '统计文本的Unicode码点数量。', str,
                     lambda text: {'count': len(text)})]


PLUGIN = PluginSpec('text', 1, create_tools)
