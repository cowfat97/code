"""请求边界装配外围 hooks；可选插件失败不阻断业务。"""

import copy
import logging
from importlib import import_module

from agent.core.hook_runtime import HookRuntime
from agent.entities.hooks import HookSpec
from agent.entities.plugins import HookPluginSpec
from .loader import read_plugin_config

logger = logging.getLogger(__name__)


def load_hook_runtime(*, config_path=None):
    path, config = read_plugin_config(config_path=config_path)
    hooks = []
    for entry in config["hook_plugins"]:
        if not entry["enabled"]:
            continue
        try:
            declaration = getattr(import_module(entry["module"]), "PLUGIN", None)
            if (not isinstance(declaration, HookPluginSpec)
                    or declaration.id != entry["id"]
                    or type(declaration.api_version) is not int
                    or declaration.api_version != 1
                    or not callable(declaration.create_hooks)):
                raise ValueError("HookPluginSpec声明无效")
            created = declaration.create_hooks(copy.deepcopy(entry["config"]))
            if not isinstance(created, (list, tuple)):
                raise ValueError("create_hooks必须返回list或tuple")
            ids = set()
            for hook in created:
                if (not isinstance(hook, HookSpec) or hook.id != entry["id"]
                        or hook.id in ids or not callable(hook.on_stage_start)
                        or not callable(hook.on_stage_end)):
                    raise ValueError("HookSpec无效或重复")
                ids.add(hook.id)
            hooks.extend(created)
        except Exception as exc:
            logger.warning("Hook 插件加载失败 plugin=%s path=%s (%s)",
                           entry["id"], path, type(exc).__name__)
    return HookRuntime(hooks)
