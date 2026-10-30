"""Standard-library manager for configured independent child plugin packages."""

from .contracts import (
    DuplicatePluginError,
    EventLoopError,
    InvalidPluginNameError,
    InvalidPluginResultError,
    InvalidTimeoutError,
    ManagerClosedError,
    Plugin,
    PluginInfo,
    PluginManagerError,
    PluginState,
    PluginStateError,
    ReentrantLifecycleError,
    UnknownPluginError,
)
from .manager import PluginManager

__all__ = [
    "DuplicatePluginError",
    "EventLoopError",
    "InvalidPluginNameError",
    "InvalidPluginResultError",
    "InvalidTimeoutError",
    "ManagerClosedError",
    "Plugin",
    "PluginInfo",
    "PluginManager",
    "PluginManagerError",
    "PluginState",
    "PluginStateError",
    "ReentrantLifecycleError",
    "UnknownPluginError",
]
