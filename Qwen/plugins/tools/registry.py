"""Unified explicit registration and execution for local functions and MCP."""

import asyncio
import copy
import inspect
import math
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any, Self

from pydantic import TypeAdapter

from .config import ToolsConfig
from .models import (
    DuplicateToolError,
    MCPConnectionError,
    ToolDefinition,
    ToolExecutionError,
    ToolNotFoundError,
    ToolResult,
    ToolValidationError,
)
from .schema import function_schema, validate
from .schema import output_schema as inferred_output_schema


class ToolRegistry:
    def __init__(self, config: ToolsConfig | Mapping[str, Any] | None = None) -> None:
        self.config = (
            config if isinstance(config, ToolsConfig) else ToolsConfig.from_mapping(config or {})
        )
        self._entries: dict[str, tuple[ToolDefinition, Any, Any]] = {}
        self._connections: dict[str, Any] = {}
        self._lock = asyncio.Lock()

    @classmethod
    def from_config(cls, config: str | Path | ToolsConfig | Mapping[str, Any]) -> Self:
        return cls(ToolsConfig.load(config) if isinstance(config, (str, Path)) else config)

    def register(
        self,
        fn: Callable[..., Any] | None = None,
        *,
        name: str | None = None,
        description: str | None = None,
        input_schema: dict[str, Any] | None = None,
        output_schema: dict[str, Any] | None = None,
    ) -> Callable[..., Any]:
        if fn is None:
            return lambda function: self.register(
                function,
                name=name,
                description=description,
                input_schema=input_schema,
                output_schema=output_schema,
            )
        tool_name = name or fn.__name__
        if tool_name in self._entries:
            raise DuplicateToolError(tool_name)
        if not tool_name:
            raise ValueError("tool name must not be empty")
        model = None
        if input_schema is None:
            input_schema, model, _ = function_schema(fn)
        if output_schema is None:
            output_schema = inferred_output_schema(fn)
        validate_schema = copy.deepcopy(input_schema)
        from jsonschema import validators

        validators.validator_for(validate_schema).check_schema(validate_schema)
        if output_schema is not None:
            validators.validator_for(output_schema).check_schema(output_schema)
        definition = ToolDefinition(
            tool_name,
            description if description is not None else inspect.getdoc(fn) or "",
            validate_schema,
            copy.deepcopy(output_schema),
            "local",
        )
        self._entries[tool_name] = (definition, fn, model)
        return fn

    def list_tools(self) -> list[ToolDefinition]:
        return [copy.deepcopy(entry[0]) for entry in self._entries.values()]

    async def connect(self) -> None:
        from .mcp import MCPConnection

        async with self._lock:
            if self._connections:
                return
            opened = {}
            discovered = {}
            try:
                for server, cfg in self.config.mcp_servers.items():
                    if not cfg.enabled:
                        continue
                    connection = MCPConnection(cfg)
                    opened[server] = connection
                    for tool in await connection.start():
                        if cfg.allowed_tools is not None and tool.name not in cfg.allowed_tools:
                            continue
                        name = f"{server}.{tool.name}"
                        if name in self._entries or name in discovered:
                            raise DuplicateToolError(name)
                        definition = ToolDefinition(
                            name,
                            tool.description or "",
                            copy.deepcopy(tool.inputSchema),
                            copy.deepcopy(tool.outputSchema),
                            f"mcp:{server}",
                        )
                        from jsonschema import validators

                        validators.validator_for(definition.input_schema).check_schema(
                            definition.input_schema
                        )
                        if definition.output_schema is not None:
                            validators.validator_for(definition.output_schema).check_schema(
                                definition.output_schema
                            )
                        discovered[name] = (definition, (connection, tool.name), None)
                for name in discovered:
                    if name in self._entries:
                        raise DuplicateToolError(name)
            except BaseException as exc:
                await asyncio.gather(*(conn.aclose() for conn in opened.values()))
                if isinstance(exc, asyncio.CancelledError):
                    raise
                raise MCPConnectionError("MCP connection or discovery failed") from exc
            self._connections = opened
            self._entries.update(discovered)

    async def call(
        self, name: str, arguments: dict[str, Any], timeout: float | None = None
    ) -> ToolResult:
        if timeout is not None and (
            isinstance(timeout, bool)
            or not isinstance(timeout, (int, float))
            or not math.isfinite(timeout)
            or timeout <= 0
        ):
            raise ValueError("timeout must be a positive finite number")
        arguments = copy.deepcopy(arguments)
        try:
            definition, target, model = self._entries[name]
        except KeyError:
            raise ToolNotFoundError(name) from None
        if not isinstance(arguments, dict):
            raise ToolValidationError("arguments must be an object")
        validate(definition.input_schema, arguments)

        async def invoke() -> ToolResult:
            if isinstance(target, tuple):
                connection, remote_name = target
                result = await connection.call(remote_name, arguments)
                data = result.structuredContent
                if definition.output_schema is not None and not result.isError:
                    validate(definition.output_schema, data, ToolExecutionError)
                return ToolResult(
                    data,
                    [
                        block.model_dump(mode="json", by_alias=True, exclude_none=True)
                        for block in result.content
                    ],
                    result.isError,
                )
            kwargs = arguments
            if model is not None:
                parsed = model.model_validate(arguments)
                kwargs = {key: getattr(parsed, key) for key in model.model_fields}
            if inspect.iscoroutinefunction(target):
                value = await target(**kwargs)
            else:
                value = await asyncio.to_thread(target, **kwargs)
                if inspect.isawaitable(value):
                    value = await value
            result = value if isinstance(value, ToolResult) else ToolResult(data=value)
            if definition.output_schema is not None:
                serialized = TypeAdapter(object).dump_python(result.data, mode="json")
                validate(definition.output_schema, serialized, ToolExecutionError)
            return result

        try:
            async with asyncio.timeout(timeout):
                return await invoke()
        except asyncio.CancelledError:
            raise
        except ToolExecutionError:
            raise
        except TimeoutError as exc:
            note = (
                "; synchronous work in a thread may continue"
                if not isinstance(target, tuple) and not inspect.iscoroutinefunction(target)
                else ""
            )
            raise ToolExecutionError(f"tool {name!r} timed out{note}") from exc
        except Exception as exc:
            raise ToolExecutionError(f"tool {name!r} failed") from exc

    async def aclose(self) -> None:
        async with self._lock:
            connections, self._connections = self._connections, {}
            self._entries = {
                name: entry for name, entry in self._entries.items() if entry[0].source == "local"
            }
            await asyncio.gather(*(connection.aclose() for connection in connections.values()))

    async def __aenter__(self) -> Self:
        await self.connect()
        return self

    async def __aexit__(self, exc_type: object, exc: object, traceback: object) -> None:
        await self.aclose()
