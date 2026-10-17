# 设计文档：[插件机制](../../../../文档/Qwen/Agent/插件机制/design/详细设计.md)


class PluginLoadError(ValueError):
    """插件配置或装配失败，本轮不应继续生成。"""
