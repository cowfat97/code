"""Lifecycle, registration, execution and monitoring behind one Python API."""

from __future__ import annotations

import asyncio
import copy
import hashlib
import inspect
import json
import logging
import math
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter
from typing import Any
from uuid import uuid4

from pydantic import TypeAdapter

from .builtin.text2sql import SQLGenerator, make_text2sql
from .core.config import GatewayConfig
from .core.function_call import parse_arguments
from .core.models import (
    DuplicateToolError,
    MCPConnectionError,
    ToolDefinition,
    ToolExecutionError,
    ToolNotFoundError,
    ToolResult,
    ToolTimeoutError,
    ToolValidationError,
)
from .core.registry import Entry, ToolRegistry
from .core.schema import validate
from .mcp.config import MCPConfig, MCPServerConfig
from .monitor import Observer, SQLiteMonitor, ToolEvent

logger = logging.getLogger(__name__)


class ToolGateway:
    def __init__(
        self,
        *,
        load_builtin: bool | None = None,
        load_mcp: bool | None = None,
        mcp_config: str | Path | None = None,
        concurrency: int | None = None,
        timeout: float | None = None,
        observers: list[Observer] | None = None,
        monitor_path: str | Path | None = "@default",
        config_file: str | Path | None = None,
    ) -> None:
        settings_path = (
            Path(config_file)
            if config_file is not None
            else Path(__file__).parent / "config/gateway.json"
        ).resolve()
        settings = GatewayConfig.load(settings_path)
        load_builtin = settings.load_builtin if load_builtin is None else load_builtin
        load_mcp = settings.load_mcp if load_mcp is None else load_mcp
        concurrency = settings.concurrency if concurrency is None else concurrency
        timeout = settings.timeout if timeout is None else timeout
        if not isinstance(load_builtin, bool) or not isinstance(load_mcp, bool):
            raise ValueError("load_builtin and load_mcp must be booleans")
        if isinstance(concurrency, bool) or not isinstance(concurrency, int) or concurrency < 1:
            raise ValueError("concurrency must be a positive integer")
        self._check_timeout(timeout)
        self._monitor_path = (
            (settings_path.parent / settings.monitor_file).resolve()
            if monitor_path == "@default" and settings.monitor_file is not None
            else Path(monitor_path)
            if monitor_path not in {None, "@default"}
            else None
        )
        self._monitor: SQLiteMonitor | None = None
        self.monitoring_errors = 0
        self._registry = ToolRegistry()
        self._load_builtin, self._load_mcp = load_builtin, load_mcp
        self._config_path = (
            Path(mcp_config) if mcp_config is not None else settings_path.parent / settings.mcp_file
        )
        self._observers = tuple(observers or ())
        if any(not callable(o) or inspect.iscoroutinefunction(o) for o in self._observers):
            raise TypeError("observers must be synchronous callbacks")
        self._slots = asyncio.Semaphore(concurrency)
        self._timeout = timeout
        self._connections: dict[str, Any] = {}
        self._active: dict[asyncio.Task[Any], str] = {}
        self._workers: set[asyncio.Task[Any]] = set()
        self._state = "new"
        self._lock = asyncio.Lock()
        self._close_task: asyncio.Task[Any] | None = None

    @classmethod
    def from_config(cls, path: str | Path, **overrides: Any):
        return cls(config_file=path, **overrides)

    @staticmethod
    def _check_timeout(value: float) -> None:
        if (
            isinstance(value, bool)
            or not isinstance(value, (float, int))
            or not math.isfinite(value)
            or value <= 0
        ):
            raise ValueError("timeout must be positive and finite")

    def _emit(self, kind: Any, name: str, *, source: str = "local", **data: Any) -> None:
        event = ToolEvent(kind, name, datetime.now(timezone.utc).isoformat(), source, **data)
        receivers: list[Observer] = list(self._observers)
        if self._monitor_path is not None and self._state != "closed":
            try:
                if self._monitor is None:
                    self._monitor = SQLiteMonitor(self._monitor_path)
                receivers.insert(0, self._monitor)
            except Exception:
                self.monitoring_errors += 1
                logger.warning("SQLite monitoring unavailable")
        for observer in receivers:
            try:
                result = observer(event)
                if inspect.isawaitable(result):
                    if inspect.iscoroutine(result):
                        result.close()
                    raise TypeError("observer must not return an awaitable")
            except Exception:
                # Never log callback exceptions: their messages may contain private data.
                self.monitoring_errors += 1
                logger.warning("Tool observer failed")

    def register(self, function: Any, *, name: str | None = None, **options: Any) -> None:
        if self._state in {"closing", "closed"}:
            raise RuntimeError("gateway is closed")
        label = str(name if name is not None else getattr(function, "__name__", "<unnamed>"))
        try:
            self._registry.register(function, name=name, **options)
        except Exception as exc:
            self._emit("registration_failed", label, error_type=type(exc).__name__)
            raise
        self._emit("registered", label)

    def unregister(self, name: str) -> None:
        try:
            if self._state in {"closing", "closed"}:
                raise RuntimeError("gateway is closed")
            entry = self._registry.get(name)
            if entry.definition.source != "local":
                raise ValueError("use unregister_mcp to remove an MCP server")
            self._registry.remove(name)
        except Exception as exc:
            self._emit("unregistration_failed", name, error_type=type(exc).__name__)
            raise
        self._emit("unregistered", name)

    def list_tools(self) -> list[ToolDefinition]:
        return self._registry.list_tools()

    def monitoring_events(self, **filters: Any) -> list[dict[str, Any]]:
        """Read persisted events; never opens an unrelated business database."""
        if self._monitor_path is None:
            raise RuntimeError("SQLite monitoring is disabled")
        if self._monitor is not None:
            return self._monitor.list_events(**filters)
        with SQLiteMonitor(self._monitor_path) as monitor:
            return monitor.list_events(**filters)

    @staticmethod
    def _function_name(name: str) -> str:
        # Model APIs restrict function names; dotted MCP names remain public gateway names.
        if re.fullmatch(r"[A-Za-z0-9_-]{1,64}", name):
            return name
        return "tool_" + hashlib.sha256(name.encode()).hexdigest()[:48]

    def function_definitions(self) -> list[dict[str, Any]]:
        result, used = [], set()
        for tool in self.list_tools():
            name = self._function_name(tool.name)
            if name in used:
                raise ValueError("function name collision; rename the conflicting tool")
            used.add(name)
            result.append(
                {
                    "type": "function",
                    "function": {
                        "name": name,
                        "description": f"{tool.name}: {tool.description}",
                        "parameters": tool.input_schema,
                    },
                }
            )
        return result

    def register_text2sql(self, generator: SQLGenerator, *, name: str = "text2sql") -> None:
        self.register(make_text2sql(generator), name=name)

    async def start(self) -> ToolGateway:
        async with self._lock:
            if self._state != "new":
                raise RuntimeError("gateway already started or closed")
            before = self._registry.entries.copy()
            self._state = "starting"
            try:
                if self._load_builtin:
                    from .builtin import BUILTIN_TOOLS

                    for name, fn in BUILTIN_TOOLS.items():
                        self.register(fn, name=name)
                if self._load_mcp:
                    config = MCPConfig.load(self._config_path)
                    for name, cfg in config.mcp_servers.items():
                        if cfg.enabled:
                            await self._register_mcp(name, cfg)
            except BaseException:
                await asyncio.gather(
                    *(c.aclose() for c in self._connections.values()),
                    return_exceptions=True,
                )
                self._connections.clear()
                for name in self._registry.entries.keys() - before.keys():
                    self._emit(
                        "unregistered",
                        name,
                        source=self._registry.get(name).definition.source,
                    )
                self._registry.entries = before
                if self._monitor is not None:
                    self._monitor.close()
                    self._monitor = None
                self._state = "new"
                raise
            self._state = "running"
            return self

    async def register_mcp(self, name: str, config: MCPServerConfig | dict[str, Any]) -> None:
        async with self._lock:
            if self._state != "running":
                raise RuntimeError("gateway is not running")
            await self._register_mcp(name, MCPServerConfig.model_validate(config))

    async def _register_mcp(self, name: str, config: MCPServerConfig) -> None:
        from .mcp.client import MCPConnection

        if not name or "." in name:
            raise ValueError("server name must be nonempty and contain no dots")
        if not config.enabled:
            return
        if name in self._connections:
            raise DuplicateToolError(name)
        # The reserved command uses this Python runtime and the packaged server script.
        config = config.model_copy(deep=True)
        if config.command == "@builtin/pgmcp":
            inherited = {
                key: value
                for key, value in os.environ.items()
                if key
                in {
                    "PGHOST",
                    "PGPORT",
                    "PGUSER",
                    "PGPASSWORD",
                    "PGDATABASE",
                    "PGSERVICE",
                    "PGSERVICEFILE",
                    "PGPASSFILE",
                    "PGSSLMODE",
                    "PGSSLROOTCERT",
                    "PGSSLCERT",
                    "PGSSLKEY",
                    "PGMCP_STATEMENT_TIMEOUT_MS",
                }
            }
            config.env = {**inherited, **(config.env or {})}
            config.command = sys.executable
            config.args = [
                str(Path(__file__).parent / "builtin/pgmcp/server.py"),
                *config.args,
            ]
        connection = MCPConnection(config)
        try:
            discovered = await connection.start()
            pending = ToolRegistry()
            for tool in discovered:
                if config.allowed_tools is not None and tool.name not in config.allowed_tools:
                    continue
                full_name = f"{name}.{tool.name}"
                if full_name in self._registry.entries:
                    raise DuplicateToolError(full_name)
                pending.add(
                    Entry(
                        ToolDefinition(
                            full_name,
                            tool.description or "",
                            copy.deepcopy(tool.inputSchema),
                            copy.deepcopy(tool.outputSchema),
                            f"mcp:{name}",
                        ),
                        connection,
                        remote_name=tool.name,
                    )
                )
            self._registry.entries.update(pending.entries)
            self._connections[name] = connection
            for entry in pending.entries.values():
                self._emit("registered", entry.definition.name, source=f"mcp:{name}")
            self._emit("mcp_connected", name, source=f"mcp:{name}")
        except BaseException as exc:
            await connection.aclose()
            self._emit(
                "mcp_connection_failed",
                name,
                source=f"mcp:{name}",
                error_type=type(exc).__name__,
            )
            if isinstance(exc, asyncio.CancelledError):
                raise
            raise MCPConnectionError(f"MCP server {name!r} registration failed") from exc

    async def unregister_mcp(self, name: str) -> None:
        async with self._lock:
            if self._state != "running":
                raise RuntimeError("gateway is not running")
            connection = self._connections.get(name)
            if connection is None:
                raise ToolNotFoundError(name)
            names = [
                n for n, e in self._registry.entries.items() if e.definition.source == f"mcp:{name}"
            ]
            if any(n in names for n in self._active.values()):
                raise RuntimeError("MCP server has active calls")
            for n in names:
                self._registry.remove(n)
                self._emit("unregistered", n, source=f"mcp:{name}")
            del self._connections[name]
            await connection.aclose()
            self._emit("mcp_disconnected", name, source=f"mcp:{name}")

    async def _execute(
        self, entry: Entry, arguments: dict[str, Any], started: asyncio.Event
    ) -> ToolResult:
        async with self._slots:
            started.set()
            if entry.remote_name is not None:
                response = await entry.target.call(entry.remote_name, arguments)
                result = ToolResult(
                    response.structuredContent,
                    [
                        b.model_dump(mode="json", by_alias=True, exclude_none=True)
                        for b in response.content
                    ],
                    response.isError,
                )
            else:
                kwargs = arguments
                if entry.arguments_model is not None:
                    parsed = entry.arguments_model.model_validate(arguments)
                    kwargs = {key: getattr(parsed, key) for key in type(parsed).model_fields}
                if inspect.iscoroutinefunction(entry.target):
                    value = await entry.target(**kwargs)
                else:
                    value = await asyncio.to_thread(entry.target, **kwargs)
                    if inspect.isawaitable(value):
                        value = await value
                result = value if isinstance(value, ToolResult) else ToolResult(value)
            if not result.is_error and entry.definition.output_schema is not None:
                value = TypeAdapter(object).dump_python(result.data, mode="json")
                validate(entry.definition.output_schema, value, ToolExecutionError)
            return result

    async def call(
        self,
        name: str,
        arguments: dict[str, Any] | None = None,
        timeout: float | None = None,
    ) -> ToolResult:
        if self._state != "running":
            raise RuntimeError("gateway is not running")
        timeout = self._timeout if timeout is None else timeout
        self._check_timeout(timeout)
        call_id, start = uuid4().hex, perf_counter()
        source = "local"
        self._emit("call_started", name, call_id=call_id)
        worker = None
        task = asyncio.current_task()
        assert task is not None
        self._active[task] = name
        kind, error = "call_failed", None
        try:
            entry = self._registry.get(name)
            source = entry.definition.source
            values = {} if arguments is None else copy.deepcopy(arguments)
            if not isinstance(values, dict):
                raise ToolValidationError("arguments must be an object")
            validate(entry.definition.input_schema, values)
            started = asyncio.Event()
            worker = asyncio.create_task(self._execute(entry, values, started))
            self._workers.add(worker)
            worker.add_done_callback(self._worker_done)
            try:
                async with asyncio.timeout(timeout):
                    result = await asyncio.shield(worker)
            except (TimeoutError, asyncio.CancelledError):
                # Threads cannot be killed. Keep their semaphore slot until completion.
                if (
                    not started.is_set()
                    or entry.remote_name is not None
                    or inspect.iscoroutinefunction(entry.target)
                ):
                    worker.cancel()
                    await asyncio.gather(worker, return_exceptions=True)
                raise
            kind = "call_failed" if result.is_error else "call_succeeded"
            return result
        except asyncio.CancelledError:
            kind, error = "call_cancelled", "CancelledError"
            raise
        except TimeoutError:
            kind, error = "call_timed_out", "ToolTimeoutError"
            raise ToolTimeoutError("tool timed out; execution outcome may be unknown") from None
        except (ToolValidationError, ToolNotFoundError, ToolExecutionError) as exc:
            error = type(exc).__name__
            raise
        except Exception as exc:
            error = type(exc).__name__
            raise ToolExecutionError(f"tool {name!r} failed") from exc
        finally:
            self._active.pop(task, None)
            self._emit(
                kind,
                name,
                source=source,
                call_id=call_id,
                duration_ms=(perf_counter() - start) * 1000,
                error_type=error,
            )

    def _worker_done(self, task: asyncio.Task[Any]) -> None:
        self._workers.discard(task)
        if not task.cancelled():
            task.exception()  # Consume failures of timed-out synchronous work.

    async def function_call(
        self,
        name: str,
        arguments: str | dict[str, Any],
        *,
        timeout: float | None = None,
    ) -> ToolResult:
        self.function_definitions()  # Validate the model-facing namespace before dispatch.
        matches = [t.name for t in self.list_tools() if self._function_name(t.name) == name]
        actual = matches[0] if matches else name
        return await self.call(actual, parse_arguments(arguments), timeout)

    async def handle_function_call(self, tool_call: dict[str, Any]) -> dict[str, Any]:
        if tool_call.get("type") != "function" or not isinstance(tool_call.get("id"), str):
            raise ToolValidationError("expected a function tool_call with id")
        function = tool_call.get("function")
        if not isinstance(function, dict) or not isinstance(function.get("name"), str):
            raise ToolValidationError("invalid function tool_call")
        result = await self.function_call(function["name"], function.get("arguments", "{}"))
        return {
            "role": "tool",
            "tool_call_id": tool_call["id"],
            "content": json.dumps(
                {
                    "data": result.data,
                    "content": result.content,
                    "is_error": result.is_error,
                },
                ensure_ascii=False,
                default=str,
            ),
        }

    async def _cleanup(self) -> None:
        tasks = [t for t in self._active if t is not asyncio.current_task()]
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        # Wait for synchronous workers too, before releasing externally owned resources.
        await asyncio.gather(*tuple(self._workers), return_exceptions=True)
        async with self._lock:
            for name, connection in self._connections.items():
                await connection.aclose()
                self._emit("mcp_disconnected", name, source=f"mcp:{name}")
            self._connections.clear()
            for definition in self.list_tools():
                self._emit("unregistered", definition.name, source=definition.source)
            self._registry.entries.clear()
            if self._monitor is not None:
                self._monitor.close()
                self._monitor = None
            self._state = "closed"

    async def aclose(self) -> None:
        if asyncio.current_task() in self._workers or asyncio.current_task() in self._active:
            raise RuntimeError("a tool cannot close its own gateway")
        async with self._lock:
            if self._state == "closed":
                return
            if self._close_task is None:
                self._state = "closing"
                self._close_task = asyncio.create_task(self._cleanup())
            closing = self._close_task
        try:
            await asyncio.shield(closing)
        except asyncio.CancelledError:
            await asyncio.shield(closing)
            raise

    async def __aenter__(self) -> ToolGateway:
        return await self.start()

    async def __aexit__(self, *args: Any) -> None:
        await self.aclose()
