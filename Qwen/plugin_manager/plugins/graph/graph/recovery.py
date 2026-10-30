"""Deterministic failure policies over checked GraSP operations; no business rules."""

from __future__ import annotations

import json
from typing import Any, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ..contracts import (
    ExecutionGraph,
    ExecutionTrace,
    GraphState,
    NodeState,
    RepairEvent,
    RepairOperation,
    RepairResult,
)
from .repair import RepairEngine, RepairError, RepairLibrary

Operator = Literal["InsertPrereq", "Rebind", "Substitute", "Rewire", "Bypass"]


class RepairRule(BaseModel):
    """Rules match in configuration order; empty selectors match any failure."""

    model_config = ConfigDict(extra="forbid", strict=True)
    name: str = Field(min_length=1)
    reason_codes: list[str] = Field(default_factory=list)
    categories: list[str] = Field(default_factory=list)
    action: Literal["retry", "patch", "stop"]
    max_attempts: int = Field(default=2, ge=0)
    operators: list[Operator] = Field(default_factory=list)

    @model_validator(mode="after")
    def valid_action(self) -> RepairRule:
        if self.action == "patch" and not self.operators:
            raise ValueError("patch requires an explicit operator allowlist")
        if self.action != "patch" and self.operators:
            raise ValueError("operators only apply to patch actions")
        if any(not value.strip() for value in [self.name, *self.reason_codes, *self.categories]):
            raise ValueError("rule names and selectors must not be blank")
        return self

    def matches(self, failure: RepairEvent) -> bool:
        return (not self.reason_codes or failure.reason_code in self.reason_codes) and (
            not self.categories or failure.type in self.categories
        )


class RepairPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    max_decisions: int = Field(default=8, ge=0)
    max_same_failure: int = Field(default=2, ge=0)
    max_node_attempts: int = Field(default=2, ge=0)
    max_added_nodes: int = Field(default=3, ge=0)
    max_added_edges: int = Field(default=5, ge=0)
    rules: list[RepairRule] = Field(default_factory=list)

    @model_validator(mode="after")
    def unique_rules(self) -> RepairPolicy:
        names = [rule.name for rule in self.rules]
        if len(names) != len(set(names)):
            raise ValueError("duplicate repair rule name")
        return self


class RepairStrategy(Protocol):
    """Pure, synchronous proposal callback; returned operations are always validated.

    No executor, filesystem, model or Harness is supplied by this protocol.
    Implementations must not mutate input snapshots or perform external actions.
    """

    def propose(
        self,
        graph: ExecutionGraph,
        state: GraphState,
        failure: RepairEvent,
        rule: RepairRule,
    ) -> list[RepairOperation]: ...


class PolicyRepairEngine:
    """Retry, propose a checked patch, or stop; nothing fabricates observed facts."""

    structured_failures = True

    def __init__(
        self,
        registry: RepairLibrary,
        policy: RepairPolicy,
        *,
        strategy: RepairStrategy | None = None,
    ) -> None:
        self.registry = registry
        self.policy = policy.model_copy(deep=True)
        self.strategy = strategy

    @staticmethod
    def _audit(
        graph: ExecutionGraph,
        state: GraphState,
        failure: RepairEvent,
        rule: RepairRule | None,
        reason: str,
        *,
        repaired: bool = False,
        operation: RepairOperation | None = None,
        **details: Any,
    ) -> RepairResult:
        audit = {
            "kind": "policy",
            "rule": rule.name if rule else None,
            "action": rule.action if rule else "stop",
            "reason": reason,
            "node_id": failure.node_id,
            "failure": failure.model_dump(mode="json"),
            "to_version": graph.version,
            **details,
        }
        state.repair_audit.append(audit)
        state.trace.append(
            ExecutionTrace(node_id=failure.node_id, event="recovery_decision", details=audit)
        )
        return RepairResult(
            repaired=repaired, graph=graph, state=state, reason=reason, operation=operation
        )

    @staticmethod
    def _protect(
        old: ExecutionGraph, new: ExecutionGraph, operation: RepairOperation | None
    ) -> None:
        for node in old.nodes:
            if not node.skill or node.skill.metadata.get("repair_protected") is not True:
                continue
            # A mandatory gate cannot be removed, rebound, bypassed or substituted.
            if operation and operation.node_id == node.id and operation.type in {
                "Bypass", "Substitute", "Rebind"
            }:
                raise RepairError("protected node cannot be bypassed or replaced")
            try:
                replacement = new.node(node.id)
            except (KeyError, StopIteration) as exc:
                raise RepairError("protected node removed") from exc
            if replacement != node:
                raise RepairError("protected node changed")
            if not old.descendants({node.id}) <= new.descendants({node.id}):
                raise RepairError("protected node ordering weakened")

    def repair(self, graph: ExecutionGraph, state: GraphState, event: RepairEvent) -> RepairResult:
        if graph.id != state.graph_id or graph.version != state.graph_version:
            raise RepairError("repair state does not match graph version")
        node = graph.node(event.node_id)
        updated = state.model_copy(deep=True)
        failure = event.model_copy(deep=True)
        failure.reason_code = failure.reason_code or failure.type
        # Only persisted observations are evidence; reports cannot add facts.
        failure.state = list(state.facts)
        rule = next((r for r in self.policy.rules if r.matches(failure)), None)
        if failure.type in {"outcome-unknown", "cancelled"} or (
            failure.type == "timeout"
            and node.skill and node.skill.metadata.get("idempotent") is not True
        ):
            return self._audit(graph, updated, failure, rule, "reconciliation-required")
        if updated.nodes.get(node.id, NodeState()).status != "failed":
            return self._audit(graph, updated, failure, rule, "node-not-failed")
        if rule is None:
            return self._audit(graph, updated, failure, None, "no-rule")
        if rule.action == "stop":
            return self._audit(graph, updated, failure, rule, "policy-stop")
        key = json.dumps([node.id, rule.name], separators=(",", ":"))
        if sum(updated.recovery_attempts.values()) >= self.policy.max_decisions:
            return self._audit(graph, updated, failure, rule, "global-exhausted")
        if updated.recovery_attempts.get(key, 0) >= rule.max_attempts:
            return self._audit(graph, updated, failure, rule, "rule-exhausted")
        prefix = f"[{json.dumps(node.id)},"
        node_attempts = sum(
            count for identity, count in updated.recovery_attempts.items()
            if identity.startswith(prefix)
        )
        if node_attempts >= min(node.repair_budget, self.policy.max_node_attempts):
            return self._audit(graph, updated, failure, rule, "node-exhausted")
        previous = updated.recovery_streaks.get(node.id, {})
        fingerprint = json.dumps([failure.type, failure.reason_code])
        streak = previous.get("count", 0) + 1 if previous.get("key") == fingerprint else 1
        if streak > self.policy.max_same_failure:
            return self._audit(graph, updated, failure, rule, "repeated-failure")
        updated.recovery_streaks[node.id] = {"key": fingerprint, "count": streak}
        updated.recovery_attempts[key] = updated.recovery_attempts.get(key, 0) + 1
        if rule.action == "retry":
            if not node.skill or node.skill.metadata.get("idempotent") is not True:
                return self._audit(graph, updated, failure, rule, "retry-unsafe")
            affected = graph.descendants({node.id})
            for identity in affected:
                before = updated.nodes.get(identity, NodeState())
                updated.nodes[identity] = NodeState(attempt=before.attempt)
            confirmed = set(graph.initial_conditions)
            for current in updated.nodes.values():
                if current.status in {"succeeded", "bypassed"} and current.result:
                    confirmed.update(current.result.observed_effects)
            updated.facts = sorted(confirmed)
            updated.status = "pending"
            return self._audit(
                graph, updated, failure, rule, "retry", repaired=True, affected=sorted(affected)
            )
        engine = RepairEngine(
            self.registry,
            l_max=self.policy.max_added_nodes,
            e_max=self.policy.max_added_edges,
            max_repairs=self.policy.max_decisions,
            operator_order=list(rule.operators),
        )
        try:
            if self.strategy is None:
                # Work on snapshots: rejection of a protected patch has no side effects.
                outcome = engine.repair(graph.model_copy(deep=True), updated, failure)
                if not outcome.repaired:
                    return self._audit(
                        graph, outcome.state, failure, rule, outcome.reason,
                        from_version=graph.version,
                    )
                self._protect(graph, outcome.graph, outcome.operation)
            else:
                proposals = self.strategy.propose(
                    graph.model_copy(deep=True), updated.model_copy(deep=True),
                    failure.model_copy(deep=True), rule.model_copy(deep=True),
                )
                if not isinstance(proposals, list) or len(proposals) > 8:
                    raise RepairError("strategy must return at most 8 candidate operations")
                outcome = None
                rejected = []
                for proposal in proposals:
                    try:
                        candidate = RepairOperation.model_validate(proposal)
                    except ValueError:
                        rejected.append("invalid operation format")
                        continue
                    if candidate.node_id != node.id or candidate.type not in rule.operators:
                        rejected.append("operation outside matched rule")
                        continue
                    try:
                        registered = {skill.id: skill for skill in self.registry.list()}
                        snapshots = [n.skill for n in candidate.prerequisites if n.skill]
                        if candidate.replacement:
                            snapshots.append(candidate.replacement)
                        if any(registered.get(skill.id) != skill for skill in snapshots):
                            raise RepairError("proposal references an unregistered skill snapshot")
                        checked = engine.apply(graph, updated, candidate)
                        self._protect(graph, checked.graph, candidate)
                    except (RepairError, ValueError) as exc:
                        rejected.append(str(exc))
                        continue
                    outcome = checked
                    break
                if outcome is None:
                    return self._audit(
                        graph, updated, failure, rule, "no-valid-patch", rejected=rejected
                    )
        except Exception as exc:
            # A faulty proposal is not permission to execute or weaken a graph.
            return self._audit(
                graph, updated, failure, rule, "patch-rejected",
                error_type=type(exc).__name__,
                rejected=str(exc) if isinstance(exc, RepairError) else "strategy error",
            )
        assert outcome is not None
        return self._audit(
            outcome.graph, outcome.state, failure, rule, "patched", repaired=True,
            operation=outcome.operation, from_version=graph.version,
        )
