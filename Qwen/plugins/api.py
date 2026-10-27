"""Owned, configuration-driven composition entry for host applications."""

from __future__ import annotations

import asyncio
import json
import tomllib
from collections.abc import Callable, Mapping, Sequence
from contextvars import ContextVar
from copy import deepcopy
from dataclasses import asdict
from importlib import import_module
from pathlib import Path
from typing import Any, Literal, Protocol, Self, cast

from pydantic import BaseModel, ConfigDict, Field

from .contracts.providers import SkillVerifier
from .graph.adapter import Payload, PluginAdapter
from .graph.plugin import SkillGraphPlugin
from .graph.ports import ToolDescriptor, ToolResponse, ToolsPort
from .graph.recovery import PolicyRepairEngine, RepairPolicy, RepairStrategy
from .meta.planner import LLMProvider, MetaPlanner
from .skills.configuration import SkillsConfig
from .skills.registry import SkillRegistry
from .task import TaskManager, ValidationIssue

_invocation: ContextVar[asyncio.Task[dict[str, Any]] | None] = ContextVar(
    "plugin_invocation", default=None
)


class GatewayPort(ToolsPort, Protocol):
    """Only the independent gateway public lifecycle and registration API is required."""

    def register(self, function: Any, *, name: str | None = None, **options: Any) -> None: ...
    async def start(self) -> Any: ...
    async def aclose(self) -> None: ...


class _GatewayAdapter:
    """Normalize the gateway timeout into the graph runtime's timeout contract."""

    def __init__(self, gateway: GatewayPort, timeout_error: type[Exception]) -> None:
        self._gateway = gateway
        self._timeout_error = timeout_error

    def register(self, function: Any, *, name: str | None = None, **options: Any) -> None:
        self._gateway.register(function, name=name, **options)

    def list_tools(self) -> Sequence[ToolDescriptor]:
        return self._gateway.list_tools()

    async def start(self) -> None:
        await self._gateway.start()

    async def aclose(self) -> None:
        await self._gateway.aclose()

    async def call(
        self, name: str, arguments: dict[str, Any], timeout: float | None = None
    ) -> ToolResponse:
        try:
            return await self._gateway.call(name, arguments, timeout)
        except self._timeout_error as exc:
            raise TimeoutError(str(exc)) from exc


def _gateway(config_file: Path) -> GatewayPort:
    parent = __package__.rpartition(".")[0]
    module = import_module(f"{parent}.tools" if parent else "tools")
    return _GatewayAdapter(
        cast(GatewayPort, module.ToolGateway(config_file=config_file)), module.ToolTimeoutError
    )


class PluginConfig(BaseModel):
    """Paths are relative to the entry configuration file, or the constructor base."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)
    skills_dir: str = Field(default="../skills/library", min_length=1)
    state_dir: str = Field(default="../state", min_length=1)
    skills_file: str = Field(default="skills.json", min_length=1)
    tools_config_file: str = Field(default="../../tools/config/gateway.json", min_length=1)
    meta_file: str = Field(default="meta.json", min_length=1)
    task_templates_dir: str = Field(default="../task/templates", min_length=1)
    task_template: str = Field(default="basic", min_length=1)
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
    It performs no storage IO or connections. Startup uses the sibling tools gateway,
    which owns builtins, MCP and monitoring.
    Optional injected functions are registered through that gateway.
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
        self.tasks = TaskManager(self._path(self.config.task_templates_dir))
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
        self._tools: GatewayPort | None = None
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
            tools = _gateway(self._path(self.config.tools_config_file))
            planner = MetaPlanner.from_config(
                self._path(self.config.meta_file), provider=self._provider
            )
            registry: SkillRegistry | None = None
            try:
                for name, fn in self._functions.items():
                    tools.register(fn, name=name)
                registry = SkillRegistry(
                    self._path(self.config.skills_dir),
                    state_path=self._path(self.config.state_dir),
                )
                registry.import_config(skills, base_path=skills_path.parent)
                await tools.start()
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

    def _check_task(
        self, document: dict[str, Any], *, planning: bool
    ) -> tuple[dict[str, Any], dict[str, Any] | None]:
        """Validate task data before planning; interaction remains owned by the host."""
        allowed = {
            "task", "goal", "initial_conditions", "context", "inputs", "proposal",
            "order_hints", "task_data",
        }
        unknown = document.keys() - allowed
        if unknown:
            raise ValueError(f"Unknown task request fields: {sorted(unknown)}")
        request = deepcopy(document)
        if "task" in request and not isinstance(request["task"], str):
            raise TypeError("task must be a string")
        supplied = request.pop("task_data", None)
        if supplied is not None and not isinstance(supplied, Mapping):
            raise TypeError("task_data must be a mapping")
        if "task_data" in document and supplied is None:
            raise TypeError("task_data must be a mapping")
        data = dict(supplied) if supplied is not None else {}
        descriptions = [
            request.get("task"), data.get("objective"), data.get("domain"), data.get("category")
        ]
        intent_text = "\n".join(value for value in descriptions if isinstance(value, str))
        selection = self.tasks.recognize(intent_text, fallback=self.config.task_template)
        template_id = selection.template_id
        template = self.tasks.load_template(template_id)
        declares_objective = "objective" in template.schema.get("properties", {})
        if supplied is None and declares_objective:
            if "task" in request:
                data["objective"] = request["task"]
            elif (
                template_id == "basic"
                and isinstance(request.get("goal"), list) and request["goal"]
                and all(isinstance(goal, str) for goal in request["goal"])
            ):
                data["objective"] = "Achieve: " + ", ".join(request["goal"])
        validation = self.tasks.validate(data, template_id=template_id)
        issues = list(validation.issues)
        definition = self.tasks.create(data, template_id=template_id) if validation.valid else None
        # Only validated, default-merged data may supply the planning objective.
        objective = (
            definition.data.get("objective") if definition is not None
            else data.get("objective", self.tasks.load_template(template_id).defaults.get("objective"))
        )
        description = request.get("task", objective)
        if planning and (not isinstance(description, str) or not description.strip()):
            issues.append(ValidationIssue("/task", "Provide a task description for planning", "required"))
        if issues:
            return request, {
                "status": "needs_input",
                "issues": [asdict(issue) for issue in issues],
            }
        assert definition is not None
        if "task" not in request and isinstance(objective, str):
            request["task"] = objective
        if planning:
            context = request.get("context", {})
            if not isinstance(context, dict):
                raise TypeError("context must be a mapping")
            request["context"] = {**context, "task_data": definition.data}
        return request, None

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
                if operation in {"run", "prepare", "plan"}:
                    request, missing = self._check_task(
                        document, planning=operation == "plan" or "goal" not in document
                    )
                    if missing is not None:
                        return missing
                    if operation == "plan":
                        return await adapter.plan(request)
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
