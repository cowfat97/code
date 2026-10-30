"""Shared skill and graph data contracts."""

from __future__ import annotations

from collections import deque
from datetime import UTC, datetime
from typing import Any, Literal
from uuid import uuid4

from jsonschema import Draft202012Validator
from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator


class ContractModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SkillDependency(ContractModel):
    id: str


class SkillContract(ContractModel):
    params: list[str] = Field(default_factory=list)
    preconditions: list[str] = Field(default_factory=list)
    effects: list[str] = Field(default_factory=list)
    input_schema: dict[str, Any] = Field(default_factory=dict)
    output_schema: dict[str, Any] = Field(default_factory=dict)
    validators: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def valid_schemas(self) -> SkillContract:
        for schema in (self.input_schema, self.output_schema):
            Draft202012Validator.check_schema(schema)
        if len(self.params) != len(set(self.params)):
            raise ValueError("duplicate contract parameters")
        return self


class Skill(ContractModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    id: str = Field(min_length=1)
    name: str
    description: str = ""
    content: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)
    source: str = ""
    dependencies: list[SkillDependency] = Field(default_factory=list)
    contract: SkillContract = Field(default_factory=SkillContract)
    content_hash: str = ""


class InputBinding(ContractModel):
    node_id: str
    output_key: str


class SkillNode(ContractModel):
    id: str
    skill: Skill | None = None
    kind: Literal["src", "skill", "snk"] = "skill"
    args: list[str] = Field(default_factory=list)
    preconditions: list[str] = Field(default_factory=list)
    effects: list[str] = Field(default_factory=list)
    bindings: dict[str, InputBinding] = Field(default_factory=dict)
    input_values: dict[str, Any] = Field(default_factory=dict)
    repair_budget: int = Field(default=2, ge=0)


class DependencyEdge(ContractModel):
    source: str
    target: str
    type: Literal["state", "data", "order"]
    label: str = ""


class ExecutionGraph(ContractModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    version: int = Field(default=1, ge=1)
    task: str = ""
    goal: list[str] = Field(default_factory=list)
    initial_conditions: list[str] = Field(default_factory=list)
    nodes: list[SkillNode] = Field(default_factory=list)
    edges: list[DependencyEdge] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)

    def node(self, node_id: str) -> SkillNode:
        for node in self.nodes:
            if node.id == node_id:
                return node
        raise KeyError(node_id)

    def topological_order(self) -> list[str]:
        ids = [n.id for n in self.nodes]
        indegrees = dict.fromkeys(ids, 0)
        successors: dict[str, list[str]] = {i: [] for i in ids}
        for edge in self.edges:
            if edge.source not in indegrees or edge.target not in indegrees:
                raise ValueError("unknown dependency reference")
            indegrees[edge.target] += 1
            successors[edge.source].append(edge.target)
        ready = deque(i for i in ids if indegrees[i] == 0)
        result = []
        while ready:
            current = ready.popleft()
            result.append(current)
            for child in successors[current]:
                indegrees[child] -= 1
                if indegrees[child] == 0:
                    ready.append(child)
        if len(result) != len(ids):
            raise ValueError("cycle in execution graph")
        return result

    def descendants(self, ids: set[str]) -> set[str]:
        """Include the roots: repair invalidation always includes the changed node."""
        affected = set(ids)
        changed = True
        while changed:
            changed = False
            for edge in self.edges:
                if edge.source in affected and edge.target not in affected:
                    affected.add(edge.target)
                    changed = True
        return affected

    def validate_graph(self) -> list[str]:
        errors = []
        ids = [n.id for n in self.nodes]
        if len(ids) != len(set(ids)):
            errors.append("duplicate node id")
        try:
            self.topological_order()
        except ValueError as exc:
            errors.append(str(exc))
        for node in self.nodes:
            if node.kind == "skill" and node.skill is None:
                errors.append(f"missing skill snapshot: {node.id}")
            for key, binding in node.bindings.items():
                if binding.node_id not in ids:
                    errors.append(f"unknown binding source: {node.id}.{key}")
                elif not any(
                    e.source == binding.node_id and e.target == node.id and e.type == "data"
                    for e in self.edges
                ):
                    errors.append(f"binding without data dependency: {node.id}.{key}")
        return errors


class FailureInfo(ContractModel):
    """A capability reports a real failure without inventing effects or a repair."""

    model_config = ConfigDict(extra="forbid", strict=True)
    category: str = Field(min_length=1)
    reason_code: str = Field(min_length=1)
    message: str = ""
    affected_items: list[str] = Field(default_factory=list)
    details: dict[str, JsonValue] = Field(default_factory=dict)


class NodeResult(ContractModel):
    output: dict[str, Any] = Field(default_factory=dict)
    observed_effects: list[str] = Field(default_factory=list)
    evidence: list[str] = Field(default_factory=list)
    failure: FailureInfo | None = None


class VerificationResult(ContractModel):
    passed: bool
    category: str = ""
    message: str = ""
    details: dict[str, Any] = Field(default_factory=dict)


class NodeState(ContractModel):
    status: str = "pending"
    attempt: int = 0
    result: NodeResult | None = None
    verification: VerificationResult | None = None
    error: str | None = None
    idempotency_key: str | None = None
    cache_key: str | None = None
    recovery_retry: bool = False


class ExecutionTrace(ContractModel):
    node_id: str | None = None
    event: str
    details: dict[str, Any] = Field(default_factory=dict)
    timestamp: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())


class GraphState(ContractModel):
    graph_id: str
    graph_version: int = 1
    status: str = "pending"
    nodes: dict[str, NodeState] = Field(default_factory=dict)
    facts: list[str] = Field(default_factory=list)
    trace: list[ExecutionTrace] = Field(default_factory=list)
    repair_attempts: dict[str, int] = Field(default_factory=dict)
    repair_audit: list[dict[str, Any]] = Field(default_factory=list)
    # Persisted counters keep recovery bounded across runtime restarts.
    recovery_attempts: dict[str, int] = Field(default_factory=dict)
    recovery_streaks: dict[str, dict[str, Any]] = Field(default_factory=dict)


class ExecutionContext(ContractModel):
    graph_id: str
    node_id: str
    idempotency_key: str
    facts: tuple[str, ...] = ()


class SearchResult(ContractModel):
    skill: Skill
    score: float


class RepairOperation(ContractModel):
    type: Literal["Bypass", "Rebind", "InsertPrereq", "Substitute", "Rewire"]
    node_id: str
    args: list[str] | None = None
    replacement: Skill | None = None
    prerequisites: list[SkillNode] = Field(default_factory=list)
    edge: DependencyEdge | None = None


class RepairEvent(ContractModel):
    node_id: str
    type: str
    reason_code: str = ""
    affected_items: list[str] = Field(default_factory=list)
    details: dict[str, JsonValue] = Field(default_factory=dict)
    message: str = ""
    state: list[str] = Field(default_factory=list)
    args: list[str] | None = None


class RepairResult(ContractModel):
    repaired: bool
    graph: ExecutionGraph
    state: GraphState
    operation: RepairOperation | None = None
    reason: str = ""
