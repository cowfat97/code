"""Harness-to-plugin calls without tool dispatch."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from copy import deepcopy
from typing import Any, Protocol, TypeAlias

Payload: TypeAlias = Mapping[str, Any]
Mapper: TypeAlias = Callable[[Payload], Payload]
OPERATIONS = frozenset(
    {
        "run",
        "plan",
        "prepare",
        "execute",
        "status",
        "cancel",
        "resume",
        "skills.register",
        "skills.search",
        "skills.get",
        "skills.reload",
        "skills.dependencies",
        "skills.compose",
        "skills.delete",
        "skills.export",
        "skills.import",
        "tools.list",
        "tools.call",
    }
)


class PluginPort(Protocol):
    async def invoke(self, operation: str, payload: Payload) -> dict[str, Any]: ...


class PluginAdapter:
    """Call plugin APIs; the plugin owns planning, storage and its injected executor."""

    def __init__(
        self,
        plugin: PluginPort,
        *,
        request_mapper: Mapper | None = None,
        report_mapper: Mapper | None = None,
    ) -> None:
        self._plugin = plugin
        self._request_mapper = request_mapper
        self._report_mapper = report_mapper

    @staticmethod
    def _copy_mapping(value: Payload) -> dict[str, Any]:
        if not isinstance(value, Mapping):
            raise TypeError("plugin payload/result must be a mapping")
        return deepcopy(dict(value))

    async def call(self, operation: str, payload: Payload | None = None) -> dict[str, Any]:
        """Unmodified plugin API call. Errors propagate; no implicit retry or success."""
        if operation not in OPERATIONS:
            raise ValueError(f"unsupported plugin operation: {operation}")
        response = await self._plugin.invoke(
            operation, self._copy_mapping({} if payload is None else payload)
        )
        return self._copy_mapping(response)

    def _request(self, request: Payload) -> dict[str, Any]:
        copied = self._copy_mapping(request)
        return self._copy_mapping(self._request_mapper(copied)) if self._request_mapper else copied

    def _report(self, report: Payload) -> dict[str, Any]:
        copied = self._copy_mapping(report)
        return self._copy_mapping(self._report_mapper(copied)) if self._report_mapper else copied

    async def plan(self, request: Payload) -> dict[str, Any]:
        return await self.call("plan", self._request(request))

    async def run(self, request: Payload) -> dict[str, Any]:
        return self._report(await self.call("run", self._request(request)))

    async def prepare(self, request: Payload) -> dict[str, Any]:
        return await self.call("prepare", self._request(request))

    async def execute(self, graph_id: str) -> dict[str, Any]:
        return self._report(await self.call("execute", {"graph_id": graph_id}))

    async def status(self, graph_id: str) -> dict[str, Any]:
        return await self.call("status", {"graph_id": graph_id})

    async def cancel(self, graph_id: str) -> dict[str, Any]:
        return await self.call("cancel", {"graph_id": graph_id})

    async def resume(self, graph_id: str, *, retry_unknown: bool = False) -> dict[str, Any]:
        return self._report(
            await self.call("resume", {"graph_id": graph_id, "retry_unknown": retry_unknown})
        )
