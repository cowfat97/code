"""Contracts and immutable public metadata for explicitly registered plugins."""

from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum
from typing import Any, Protocol


class Plugin(Protocol):
    """Factories must return a fresh instance; callbacks run on the manager loop."""

    async def start(self) -> object: ...
    async def invoke(
        self, operation: str, payload: Mapping[str, Any]
    ) -> dict[str, Any]: ...
    async def aclose(self) -> None: ...


class PluginState(str, Enum):
    REGISTERED = "registered"
    STARTING = "starting"
    RUNNING = "running"
    STOPPING = "stopping"
    STOPPED = "stopped"
    FAILED = "failed"


@dataclass(frozen=True)
class PluginInfo:
    name: str
    state: PluginState
    active_calls: int
    error_type: str | None


class PluginManagerError(Exception):
    """Base class for manager contract errors (plugin exceptions pass through)."""


class InvalidPluginNameError(PluginManagerError, ValueError):
    pass


class DuplicatePluginError(PluginManagerError, ValueError):
    pass


class UnknownPluginError(PluginManagerError, KeyError):
    pass


class PluginStateError(PluginManagerError, RuntimeError):
    pass


class ManagerClosedError(PluginManagerError, RuntimeError):
    pass


class ReentrantLifecycleError(PluginManagerError, RuntimeError):
    pass


class EventLoopError(PluginManagerError, RuntimeError):
    pass


class InvalidTimeoutError(PluginManagerError, ValueError):
    pass


class InvalidPluginResultError(PluginManagerError, TypeError):
    pass
