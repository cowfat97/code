"""插件装配协议实体，供插件工厂和加载器共享。"""

from .spec import PluginContext, PluginSpec, HookPluginSpec

__all__ = ["PluginContext", "PluginSpec", "HookPluginSpec"]
