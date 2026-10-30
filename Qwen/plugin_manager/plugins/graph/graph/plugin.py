"""Fixed operation facade over one registry, compiler and execution runtime.

The host owns executor/verifier capabilities and the registry lifetime. This
facade has no Harness SDK, tool transport, shell permission or global service.
"""

from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from ..contracts import ExecutionGraph, GraphState, NodeState
from ..contracts.providers import SkillExecutor, SkillVerifier
from .compiler import GraphCompiler
from .ports import PlannerPort, SkillsPort, ToolsPort
from .runtime import GraphRuntime
from .tool_executor import ToolSkillExecutor


class _Request(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class _TaskRequest(_Request):
    context: dict[str, Any] = Field(default_factory=dict)
    task: str = ""
    goal: list[str]
    initial_conditions: list[str] = Field(default_factory=list)
    inputs: dict[str, dict[str, Any]] = Field(default_factory=dict)
    proposal: list[dict[str, Any]] | None = None
    order_hints: list[dict[str, Any]] | None = None


class _PlanRequest(_Request):
    task: str = Field(min_length=1)
    goal: list[str] | None = None
    initial_conditions: list[str] = Field(default_factory=list)
    context: dict[str, Any] = Field(default_factory=dict)
    inputs: dict[str, dict[str, Any]] = Field(default_factory=dict)


class _GraphRequest(_Request):
    graph_id: str


class _ResumeRequest(_GraphRequest):
    retry_unknown: bool = False


class _RegisterRequest(_Request):
    spec: dict[str, Any]
    layer: str = "project"


class _SearchRequest(_Request):
    query: str
    mode: Literal["keyword", "fulltext", "semantic", "hybrid"] = "keyword"
    limit: int = Field(default=20, ge=0)
    filters: dict[str, Any] | None = None


class _SkillRequest(_Request):
    skill_id: str


class _DependenciesRequest(_SkillRequest):
    recursive: bool = False


class _ExportRequest(_Request):
    pass


class _ImportRequest(_Request):
    config: str | dict[str, Any]
    base_path: str | None = None


class _ToolRequest(_Request):
    name: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    timeout: float | None = Field(default=None, gt=0, allow_inf_nan=False)


class SkillGraphPlugin:
    """Expose typed plugin operations through ``await invoke(name, payload)``.

    Successful output and graph versions always come from durable runtime state;
    validation, lookup, compilation and execution exceptions retain their types.
    """

    def __init__(
        self,
        registry: SkillsPort,
        executor: SkillExecutor | None = None,
        *,
        tools: ToolsPort | None = None,
        planner: PlannerPort | None = None,
        verifier: SkillVerifier | None = None,
        repair_engine: Any = None,
        concurrency: int = 4,
        retries: int = 0,
        timeout: float = 30,
        discovery_mode: str = "keyword",
        strict_preconditions: bool = True,
    ) -> None:
        if executor is not None and tools is not None:
            raise ValueError("provide either executor or tools")
        if executor is None:
            if tools is None:
                raise ValueError("an executor or tools registry is required")
            executor = ToolSkillExecutor(tools)
        self.planner = planner
        self.tools = tools
        self.skills = registry
        self._compiler = GraphCompiler(
            registry,
            discovery_mode=discovery_mode,
            strict_preconditions=strict_preconditions,
        )
        self._runtime = GraphRuntime(
            registry,
            executor,
            verifier=verifier,
            repair_engine=repair_engine,
            concurrency=concurrency,
            retries=retries,
            timeout=timeout,
        )
        self._active: set[str] = set()

    def _load(self, graph_id: str) -> tuple[ExecutionGraph, GraphState]:
        saved = self.skills.load_run(graph_id)
        if saved is None:
            raise KeyError(graph_id)
        graph_data, state_data = saved
        return ExecutionGraph.model_validate(graph_data), GraphState.model_validate(
            state_data
        )

    def _report(self, graph_id: str) -> dict[str, Any]:
        graph, state = self._load(graph_id)
        outputs: dict[str, Any] = {}
        errors: dict[str, str] = {}
        verification: dict[str, Any] = {}
        for node in graph.nodes:
            ns = state.nodes.get(node.id)
            if ns is None:
                continue
            if node.kind == "skill" and ns.status == "succeeded" and ns.result:
                outputs[node.id] = ns.result.output
            if ns.error or ns.status in {
                "failed",
                "blocked",
                "outcome-unknown",
                "cancelled",
            }:
                errors[node.id] = ns.error or ns.status
            if ns.verification:
                verification[node.id] = ns.verification.model_dump(mode="json")
        return {
            "graph_id": graph.id,
            "graph_version": graph.version,
            "status": state.status,
            "outputs": outputs,
            "errors": errors,
            "verification": verification,
            "repair_audit": state.repair_audit,
            "trace": [event.model_dump(mode="json") for event in state.trace],
        }

    async def _prepare(self, request: _TaskRequest) -> dict[str, Any]:
        graph = await self._compiler.compile(**request.model_dump(exclude={"context"}))
        graph.metadata["context"] = deepcopy(request.context)
        state = GraphState(
            graph_id=graph.id,
            graph_version=graph.version,
            status="prepared",
            nodes={node.id: NodeState() for node in graph.nodes},
            facts=list(graph.initial_conditions),
        )
        self.skills.save_run(
            graph.id, graph.model_dump(mode="json"), state.model_dump(mode="json")
        )
        return {
            "graph_id": graph.id,
            "graph_version": graph.version,
            "status": "prepared",
        }

    async def _execute(
        self, graph_id: str, *, resume: bool = False, retry_unknown: bool = False
    ) -> dict[str, Any]:
        if graph_id in self._active:
            raise RuntimeError("graph already executing in this plugin")
        graph, state = self._load(graph_id)
        self._active.add(graph_id)
        try:
            if resume:
                await self._runtime.resume(graph_id, retry_unknown=retry_unknown)
            else:
                await self._runtime.execute(graph, state)
            return self._report(graph_id)
        finally:
            self._active.discard(graph_id)

    async def invoke(
        self, operation: str, payload: Mapping[str, Any]
    ) -> dict[str, Any]:
        """Dispatch only the fixed public operation set; never arbitrary attributes."""
        if not isinstance(payload, Mapping):
            raise TypeError("payload must be a mapping")
        document = dict(payload)
        if operation == "plan":
            planning_request = _PlanRequest.model_validate(document)
            if self.planner is None:
                raise ValueError("no planner was injected")
            plan = await self.planner.plan(
                task=planning_request.task,
                skills=self.skills.list(),
                goal=planning_request.goal,
                initial_conditions=planning_request.initial_conditions,
                context=planning_request.context,
            )
            planned_request = _TaskRequest.model_validate(
                {
                    **plan.to_plugin_request(inputs=planning_request.inputs),
                    "context": planning_request.context,
                }
            )
            return {
                "plan": plan.model_dump(mode="json"),
                "request": planned_request.model_dump(mode="json"),
            }
        if operation in {"prepare", "run"}:
            prepared = await self._prepare(_TaskRequest.model_validate(document))
            if operation == "run":
                return await self._execute(prepared["graph_id"])
            return prepared
        if operation in {"execute", "status", "cancel"}:
            request = _GraphRequest.model_validate(document)
            if operation == "execute":
                return await self._execute(request.graph_id)
            if operation == "status":
                return self._report(request.graph_id)
            self._load(request.graph_id)
            active = request.graph_id in self._active
            if active:
                self._runtime.cancel(request.graph_id)
            return {"graph_id": request.graph_id, "cancel_requested": active}
        if operation == "resume":
            recovery = _ResumeRequest.model_validate(document)
            return await self._execute(
                recovery.graph_id, resume=True, retry_unknown=recovery.retry_unknown
            )
        if operation == "skills.import":
            import_request = _ImportRequest.model_validate(document)
            return {
                "skills": [
                    s.model_dump(mode="json")
                    for s in self.skills.import_config(
                        import_request.config, base_path=import_request.base_path
                    )
                ]
            }
        if operation == "tools.list":
            _Request.model_validate(document)
            if self.tools is None:
                raise ValueError("no tools registry was injected")
            return {
                "tools": [
                    {
                        "name": t.name,
                        "description": t.description,
                        "input_schema": t.input_schema,
                        "output_schema": t.output_schema,
                        "source": t.source,
                    }
                    for t in self.tools.list_tools()
                ]
            }
        if operation == "tools.call":
            tool_request = _ToolRequest.model_validate(document)
            if self.tools is None:
                raise ValueError("no tools registry was injected")
            result = await self.tools.call(
                tool_request.name, tool_request.arguments, tool_request.timeout
            )
            return {
                "data": result.data,
                "content": result.content,
                "is_error": result.is_error,
            }
        if operation == "skills.register":
            registration = _RegisterRequest.model_validate(document)
            skill = self.skills.register_spec(
                registration.spec, layer=registration.layer
            )
            return {"skill": skill.model_dump(mode="json")}
        if operation == "skills.search":
            search = _SearchRequest.model_validate(document)
            return {
                "results": [
                    item.model_dump(mode="json")
                    for item in self.skills.search(
                        search.query,
                        mode=search.mode,
                        limit=search.limit,
                        filters=search.filters,
                    )
                ]
            }
        if operation == "skills.get":
            identity = _SkillRequest.model_validate(document)
            return {"skill": self.skills.get(identity.skill_id).model_dump(mode="json")}
        if operation == "skills.reload":
            _Request.model_validate(document)
            return {"skills": [s.model_dump(mode="json") for s in self.skills.reload()]}
        if operation == "skills.dependencies":
            dependencies = _DependenciesRequest.model_validate(document)
            return {
                "dependencies": [
                    skill.model_dump(mode="json")
                    for skill in self.skills.dependencies(
                        dependencies.skill_id,
                        recursive=dependencies.recursive,
                    )
                ]
            }
        if operation == "skills.compose":
            composition = _SkillRequest.model_validate(document)
            return {
                "composition": self.skills.compose_spec(
                    composition.skill_id
                ).model_dump(mode="json")
            }
        if operation == "skills.delete":
            deletion = _SkillRequest.model_validate(document)
            self.skills.delete(deletion.skill_id)
            return {"deleted": True}
        if operation == "skills.export":
            _ExportRequest.model_validate(document)
            return {"json": self.skills.export_json()}
        raise ValueError(f"Unknown plugin operation: {operation!r}")
