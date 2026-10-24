"""Owned, configuration-driven composition entry for host applications."""

from __future__ import annotations

import asyncio
import json
import tomllib
from collections.abc import Callable, Mapping
from contextvars import ContextVar
from copy import deepcopy
from pathlib import Path
from typing import Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field

from .contracts.providers import SkillVerifier
from .meta.planner import LLMProvider, MetaPlanner
from .skill_graph.adapter import Payload, PluginAdapter
from .skill_graph.plugin import SkillGraphPlugin
from .skill_graph.recovery import PolicyRepairEngine, RepairPolicy, RepairStrategy
from .skills.configuration import SkillsConfig
from .skills.registry import SkillRegistry
from .tools import local
from .tools.registry import ToolRegistry

_invocation: ContextVar[asyncio.Task[dict[str, Any]] | None] = ContextVar(
    "plugin_invocation", default=None
)


class PluginConfig(BaseModel):
    """Paths are relative to the entry configuration file, or the constructor base."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)
    skills_dir: str = Field(default="../skill_library", min_length=1)
    state_dir: str = Field(default="../state", min_length=1)
    skills_file: str = Field(default="skills.json", min_length=1)
    mcp_file: str = Field(default="mcp.json", min_length=1)
    meta_file: str = Field(default="meta.json", min_length=1)
    concurrency: int = Field(default=4, gt=0)
    retries: int = Field(default=0, ge=0)
    timeout: float = Field(default=30, gt=0, allow_inf_nan=False)
    discovery_mode: Literal["keyword", "fulltext", "semantic", "hybrid"] = "keyword"
    repair_enabled: bool = False
    repair_policy: RepairPolicy = Field(default_factory=RepairPolicy)

    @classmethod
    def load(cls, path: str | Path) -> Self:
        path = Path(path)
        with path.open("rb") as stream:
            value = tomllib.load(stream) if path.suffix.lower() == ".toml" else json.load(stream)
        return cls.model_validate(value)


class Plugin:
    """Own every composed resource. Start twice raises; closing twice is harmless.

    Construction loads config/plugin.json automatically when config is omitted.
    It performs no storage IO or connections. Startup registers tools from
    plugins.tools.local before optional injected functions and configured MCP tools.
    Configuration never imports Python code.
    Active invocations cannot close their own plugin; the host owns its lifecycle.
    """

    def __init__(
        self,
        config: PluginConfig | Mapping[str, Any] | None = None,
        *,
        llm_provider: LLMProvider | None = None,
        functions: Mapping[str, Callable[..., Any]] | None = None,
        verifier: SkillVerifier | None = None,
        repair_strategy: RepairStrategy | None = None,
        base_path: str | Path | None = None,
    ) -> None:
        self._base = (
            (Path(__file__).resolve().parent / "config")
            if base_path is None
            else Path(base_path).absolute()
        )
        self.config = (
            PluginConfig.load(self._base / "plugin.json")
            if config is None
            else PluginConfig.model_validate(config)
        )
        self._provider = llm_provider
        self._functions = dict(functions or {})
        for name, fn in self._functions.items():
            if not isinstance(name, str) or not name or not callable(fn):
                raise TypeError("functions must map nonempty names to callables")
        self._verifier = verifier
        self._repair_strategy = repair_strategy
        self._lock = asyncio.Lock()
        self._adapter: PluginAdapter | None = None
        self._registry: SkillRegistry | None = None
        self._tools: ToolRegistry | None = None
        self._active: set[asyncio.Task[dict[str, Any]]] = set()
        self._closing = False
        self._close_task: asyncio.Task[None] | None = None

    @classmethod
    def from_config(
        cls,
        path: str | Path | None = None,
        *,
        llm_provider: LLMProvider | None = None,
        functions: Mapping[str, Callable[..., Any]] | None = None,
        verifier: SkillVerifier | None = None,
        repair_strategy: RepairStrategy | None = None,
    ) -> Self:
        path = (
            Path(__file__).resolve().parent / "config" / "plugin.json"
            if path is None
            else Path(path)
        ).resolve(strict=True)
        return cls(
            PluginConfig.load(path),
            llm_provider=llm_provider,
            functions=functions,
            verifier=verifier,
            repair_strategy=repair_strategy,
            base_path=path.parent,
        )

    def _path(self, value: str) -> Path:
        return self._base / value

    async def start(self) -> Self:
        async with self._lock:
            if self._adapter is not None or self._closing:
                raise RuntimeError("plugin is already started or closing")
            # Validate all configuration before opening file-backed storage.
            skills_path = self._path(self.config.skills_file)
            skills = SkillsConfig.load(skills_path)
            tools = ToolRegistry.from_config(self._path(self.config.mcp_file))
            planner = MetaPlanner.from_config(
                self._path(self.config.meta_file), provider=self._provider
            )
            registry: SkillRegistry | None = None
            try:
                local.register_tools(tools)
                for name, fn in self._functions.items():
                    tools.register(fn, name=name)
                registry = SkillRegistry(
                    self._path(self.config.skills_dir),
                    state_path=self._path(self.config.state_dir),
                )
                registry.import_config(skills, base_path=skills_path.parent)
                await tools.connect()
                graph = SkillGraphPlugin(
                    registry,
                    tools=tools,
                    planner=planner,
                    verifier=self._verifier,
                    repair_engine=(
                        PolicyRepairEngine(
                            registry, self.config.repair_policy, strategy=self._repair_strategy
                        )
                        if self.config.repair_enabled else None
                    ),
                    concurrency=self.config.concurrency,
                    retries=self.config.retries,
                    timeout=self.config.timeout,
                    discovery_mode=self.config.discovery_mode,
                )
            except BaseException:
                try:
                    await tools.aclose()
                finally:
                    if registry is not None:
                        registry.close()
                raise
            self._registry, self._tools = registry, tools
            self._adapter = PluginAdapter(graph)
            self._close_task = None
            return self

    async def __aenter__(self) -> Self:
        return await self.start()

    async def __aexit__(self, exc_type: object, exc: object, traceback: object) -> None:
        await self.aclose()

    async def _cleanup(self) -> None:
        try:
            tasks = list(self._active)
            for task in tasks:
                task.cancel()
            if tasks:
                await asyncio.gather(*tasks, return_exceptions=True)
            try:
                if self._tools is not None:
                    await self._tools.aclose()
            finally:
                if self._registry is not None:
                    self._registry.close()
        finally:
            self._adapter = None
            self._registry = None
            self._tools = None
            self._closing = False

    async def aclose(self) -> None:
        if _invocation.get() in self._active:
            raise RuntimeError("cannot close plugin from its active invocation")
        async with self._lock:
            if self._close_task is None:
                if self._adapter is None:
                    return
                self._closing = True
                self._close_task = asyncio.create_task(self._cleanup())
            task = self._close_task
        # Shield resource cleanup even when the host task is cancelled.
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError:
            await asyncio.shield(task)
            raise

    async def invoke(self, operation: str, payload: Payload | None = None) -> dict[str, Any]:
        async with self._lock:
            if self._adapter is None or self._closing:
                raise RuntimeError("plugin is not started")
            adapter = self._adapter
            value = {} if payload is None else payload
            if not isinstance(value, Mapping):
                raise TypeError("plugin payload must be a mapping")
            document = deepcopy(dict(value))

            async def dispatch() -> dict[str, Any]:
                _invocation.set(asyncio.current_task())
                if operation in {"run", "prepare"}:
                    request = document
                    if "goal" not in request:
                        planned = await adapter.plan(request)
                        request = planned["request"]
                    if operation == "run":
                        return await adapter.run(request)
                    return await adapter.prepare(request)
                return await adapter.call(operation, document)

            task = asyncio.create_task(dispatch())
            self._active.add(task)
        try:
            return await task
        finally:
            self._active.discard(task)

    async def call(self, operation: str, payload: Payload | None = None) -> dict[str, Any]:
        return await self.invoke(operation, payload)

    async def run(self, request: Payload) -> dict[str, Any]:
        return await self.invoke("run", request)

    async def prepare(self, request: Payload) -> dict[str, Any]:
        return await self.invoke("prepare", request)

    async def plan(self, request: Payload) -> dict[str, Any]:
        return await self.invoke("plan", request)

    async def execute(self, graph_id: str) -> dict[str, Any]:
        return await self.invoke("execute", {"graph_id": graph_id})

    async def status(self, graph_id: str) -> dict[str, Any]:
        return await self.invoke("status", {"graph_id": graph_id})

    async def cancel(self, graph_id: str) -> dict[str, Any]:
        return await self.invoke("cancel", {"graph_id": graph_id})

    async def resume(self, graph_id: str, *, retry_unknown: bool = False) -> dict[str, Any]:
        return await self.invoke("resume", {"graph_id": graph_id, "retry_unknown": retry_unknown})
