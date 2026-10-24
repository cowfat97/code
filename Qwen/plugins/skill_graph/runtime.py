"""Durable asynchronous scheduler; capabilities are explicitly injected.

GraSP scheduler/fact verification semantics are ported; parallelism, recovery,
cache fingerprints and checked incremental repair are integration extensions.
"""

from __future__ import annotations

import asyncio
import copy
import hashlib
import json
from typing import Any

from ..contracts import (
    ExecutionContext,
    ExecutionGraph,
    ExecutionTrace,
    GraphState,
    NodeResult,
    NodeState,
    RepairEvent,
    SkillNode,
    VerificationResult,
)
from ..contracts.providers import SkillExecutor, SkillVerifier
from .verification import verify_input, verify_result

_DONE = {"succeeded", "bypassed"}


class GraphRuntime:
    def __init__(
        self,
        registry: Any,
        executor: SkillExecutor,
        verifier: SkillVerifier | None = None,
        repair_engine: Any = None,
        concurrency: int = 4,
        retries: int = 0,
        timeout: float = 30,
    ) -> None:
        if concurrency < 1 or retries < 0 or timeout <= 0:
            raise ValueError("invalid runtime limits")
        self.registry = registry
        self.executor = executor
        self.verifier = verifier
        self.repair_engine = repair_engine
        self.concurrency = concurrency
        self.retries = retries
        self.timeout = timeout
        self._cancelled: set[str] = set()
        self._active: dict[str, set[asyncio.Task[None]]] = {}
        self._running_graphs: set[str] = set()

    def cancel(self, graph_id: str) -> None:
        self._cancelled.add(graph_id)
        for task in self._active.get(graph_id, set()):
            task.cancel()

    def _persist(self, graph: ExecutionGraph, state: GraphState) -> None:
        self.registry.save_run(
            graph.id, graph.model_dump(mode="json"), state.model_dump(mode="json")
        )

    def _event(
        self,
        graph: ExecutionGraph,
        state: GraphState,
        node_id: str | None,
        event: str,
        **details: Any,
    ) -> None:
        state.trace.append(ExecutionTrace(node_id=node_id, event=event, details=details))
        self._persist(graph, state)

    async def resume(self, graph_id: str, *, retry_unknown: bool = False) -> GraphState:
        saved = self.registry.load_run(graph_id)
        if saved is None:
            raise KeyError(graph_id)
        graph_data, state_data = saved
        graph = ExecutionGraph.model_validate(graph_data)
        state = GraphState.model_validate(state_data)
        recovered_roots = set()
        for node_id, ns in state.nodes.items():
            if ns.status == "running":
                ns.status = "outcome-unknown"
                ns.error = "interrupted during execution; external outcome must be reconciled"
            if retry_unknown and ns.status == "outcome-unknown":
                ns.status = "pending"
                ns.recovery_retry = True
                recovered_roots.add(node_id)
            elif ns.status == "cancelled":
                # These were never-started nodes; in-flight actions remain unknown.
                ns.status = "pending"
                recovered_roots.add(node_id)
        for node_id in graph.descendants(recovered_roots):
            if state.nodes[node_id].status == "blocked":
                state.nodes[node_id].status = "pending"
        self._cancelled.discard(graph_id)
        return await self.execute(graph, state)

    @staticmethod
    def _inputs(node: SkillNode, state: GraphState) -> dict[str, Any]:
        inputs = copy.deepcopy(node.input_values)
        for key, binding in node.bindings.items():
            result = state.nodes[binding.node_id].result
            if result is None:
                raise ValueError("missing bound result")
            inputs[key] = copy.deepcopy(result.output[binding.output_key])
        return inputs

    @staticmethod
    def _cache_key(node: SkillNode, inputs: dict[str, Any]) -> str:
        return hashlib.sha256(
            json.dumps(
                {"node": node.model_dump(mode="json"), "inputs": inputs}, sort_keys=True
            ).encode()
        ).hexdigest()

    async def execute(self, graph: ExecutionGraph, state: GraphState | None = None) -> GraphState:
        if graph.id in self._running_graphs:
            raise RuntimeError("graph already executing in this runtime")
        self._running_graphs.add(graph.id)
        try:
            return await self._execute(graph, state)
        finally:
            self._running_graphs.discard(graph.id)

    async def _execute(self, graph: ExecutionGraph, state: GraphState | None) -> GraphState:
        graph = graph.model_copy(deep=True)
        errors = graph.validate_graph()
        if errors:
            raise ValueError("; ".join(errors))
        if state is None:
            state = GraphState(
                graph_id=graph.id, graph_version=graph.version, facts=list(graph.initial_conditions)
            )
        else:
            state = state.model_copy(deep=True)
        if state.graph_id != graph.id or state.graph_version != graph.version:
            raise ValueError("state does not match graph version")
        for node in graph.nodes:
            if node.skill:
                self.registry.get(node.skill.id, node.skill.version)
            state.nodes.setdefault(node.id, NodeState())
        for ns in state.nodes.values():
            if ns.status == "running":
                ns.status = "outcome-unknown"
                ns.error = "interrupted execution requires reconciliation"
        if any(n.status == "outcome-unknown" for n in state.nodes.values()):
            state.status = "outcome-unknown"
            self._event(graph, state, None, "reconciliation_required")
            return state
        stale = set()
        for node in graph.nodes:
            ns = state.nodes[node.id]
            if ns.status in _DONE and ns.cache_key:
                try:
                    unchanged = ns.cache_key == self._cache_key(node, self._inputs(node, state))
                except (KeyError, ValueError):
                    unchanged = False
                if not unchanged:
                    stale.add(node.id)
        if stale:
            affected = graph.descendants(stale)
            for node_id in affected:
                previous = state.nodes[node_id]
                state.nodes[node_id] = NodeState(attempt=previous.attempt)
            self._event(graph, state, None, "cache_invalidated", affected=sorted(affected))
        confirmed = set(graph.initial_conditions)
        for ns in state.nodes.values():
            if ns.status in _DONE and ns.result:
                confirmed.update(ns.result.observed_effects)
        state.facts = sorted(confirmed)
        state.status = "running"
        self._event(graph, state, None, "started", version=graph.version)
        while True:
            if graph.id in self._cancelled:
                for ns in state.nodes.values():
                    if ns.status in {"pending", "ready"}:
                        ns.status = "cancelled"
                state.status = "cancelled"
                break
            ready = [
                n
                for n in graph.nodes
                if state.nodes[n.id].status in {"pending", "ready", "verifying"}
                and all(
                    state.nodes[e.source].status in _DONE for e in graph.edges if e.target == n.id
                )
            ]
            if not ready:
                break
            batch = ready[: self.concurrency]
            tasks = {asyncio.create_task(self._run_node(graph, state, n.id)) for n in batch}
            self._active[graph.id] = tasks
            try:
                await asyncio.gather(*tasks)
            except asyncio.CancelledError:
                self.cancel(graph.id)
                await asyncio.gather(*tasks, return_exceptions=True)
            finally:
                self._active.pop(graph.id, None)
            repaired = False
            for node in batch:
                ns = state.nodes[node.id]
                if ns.status != "failed" or self.repair_engine is None:
                    continue
                category = ns.verification.category if ns.verification else "execution"
                if category not in {"precondition", "postcondition", "execution", "timeout"}:
                    category = "postcondition"
                outcome = self.repair_engine.repair(
                    graph,
                    state,
                    RepairEvent(
                        node_id=node.id,
                        type=category,
                        message=ns.error or "",
                        state=list(state.facts),
                    ),
                )
                graph, state = outcome.graph, outcome.state
                self._persist(graph, state)
                if outcome.repaired:
                    self._event(graph, state, node.id, "repaired", version=graph.version)
                    repaired = True
                    break
            if repaired:
                continue
            for node in graph.nodes:
                if state.nodes[node.id].status in {"failed", "outcome-unknown"}:
                    for descendant in graph.descendants({node.id}) - {node.id}:
                        if state.nodes[descendant].status in {"pending", "ready"}:
                            state.nodes[descendant].status = "blocked"
        if state.status != "cancelled":
            complete = all(n.status in _DONE for n in state.nodes.values())
            goals_met = set(graph.goal) <= set(state.facts)
            if any(n.status == "outcome-unknown" for n in state.nodes.values()):
                state.status = "outcome-unknown"
            else:
                state.status = "succeeded" if complete and goals_met else "failed"
        self._event(graph, state, None, "finished", status=state.status)
        if hasattr(self.registry, "record_episode"):
            self.registry.record_episode(
                graph.task,
                [n.skill.id for n in graph.nodes if n.skill and state.nodes[n.id].status in _DONE],
                state.status == "succeeded",
            )
        return state

    async def _run_node(self, graph: ExecutionGraph, state: GraphState, node_id: str) -> None:
        node = graph.node(node_id)
        ns = state.nodes[node_id]
        try:
            inputs = self._inputs(node, state)
        except (KeyError, ValueError) as exc:
            ns.status, ns.error = "failed", str(exc)
            ns.verification = VerificationResult(
                passed=False, category="input_binding", message=str(exc)
            )
            self._event(graph, state, node_id, "failed", category="input_binding")
            return
        check = verify_input(node, inputs, state.facts)
        if not check.passed:
            ns.status, ns.error, ns.verification = "failed", check.message, check
            self._feedback(graph, node, ns)
            self._event(graph, state, node_id, "failed", category=check.category)
            return
        context = ExecutionContext(
            graph_id=graph.id,
            node_id=node_id,
            idempotency_key=ns.idempotency_key or "",
            facts=tuple(state.facts),
        )
        if ns.status != "verifying":
            ns.status = "ready"
            self._event(graph, state, node_id, "ready")
            for retry in range(self.retries + 1):
                ns.status = "running"
                if not ns.recovery_retry:
                    ns.attempt += 1
                    ns.idempotency_key = f"grasp:idem:{graph.id}:{node_id}:{ns.attempt}"
                elif not ns.idempotency_key:
                    ns.idempotency_key = f"grasp:idem:{graph.id}:{node_id}:{ns.attempt}"
                ns.recovery_retry = False
                context.idempotency_key = ns.idempotency_key
                ns.cache_key = self._cache_key(node, inputs)
                self._event(graph, state, node_id, "running", attempt=ns.attempt)
                try:
                    if node.kind in {"src", "snk"}:
                        ns.result = NodeResult(observed_effects=list(state.facts))
                    else:
                        ns.result = NodeResult.model_validate(
                            await asyncio.wait_for(
                                self.executor.execute(
                                    node.model_copy(deep=True),
                                    copy.deepcopy(inputs),
                                    context.model_copy(deep=True),
                                ),
                                self.timeout,
                            )
                        ).model_copy(deep=True)
                    ns.status = "verifying"
                    self._event(graph, state, node_id, "result_persisted")
                    break
                except asyncio.CancelledError:
                    ns.status = "outcome-unknown" if node.kind == "skill" else "cancelled"
                    ns.error = "cancelled during execution; external outcome unknown"
                    self._event(graph, state, node_id, "cancelled", outcome=ns.status)
                    raise
                except Exception as exc:
                    ns.error = str(exc) or type(exc).__name__
                    category = "timeout" if isinstance(exc, TimeoutError) else "execution"
                    ns.verification = VerificationResult(
                        passed=False, category=category, message=ns.error
                    )
                    # A timed-out external action may have happened. Retry is safe
                    # only if the host explicitly declares this capability idempotent.
                    if (
                        category == "timeout"
                        and node.skill
                        and not node.skill.metadata.get("idempotent", False)
                    ):
                        ns.status = "outcome-unknown"
                        self._event(graph, state, node_id, "outcome-unknown", category=category)
                        return
                    self._event(graph, state, node_id, "attempt_failed", category=category)
                    if retry == self.retries:
                        ns.status = "failed"
            if ns.status == "failed":
                self._feedback(graph, node, ns)
                self._persist(graph, state)
                return
        assert ns.result is not None
        try:
            verdict = verify_result(node, ns.result)
            if (
                verdict.passed
                and node.skill
                and node.skill.contract.validators
                and not self.verifier
            ):
                verdict = VerificationResult(
                    passed=False,
                    category="custom_validator",
                    message="contract requires an injected custom verifier",
                )
            if verdict.passed and self.verifier and node.kind == "skill":
                verdict = await asyncio.wait_for(
                    self.verifier.verify(
                        node.model_copy(deep=True),
                        copy.deepcopy(inputs),
                        ns.result.model_copy(deep=True),
                        context.model_copy(deep=True),
                    ),
                    self.timeout,
                )
        except asyncio.CancelledError:
            # The raw result is already durable; recovery reruns verification only.
            ns.status = "verifying"
            self._event(graph, state, node_id, "cancelled", stage="verification")
            raise
        except Exception as exc:
            verdict = VerificationResult(passed=False, category="verification", message=str(exc))
        ns.verification = verdict
        ns.status = "succeeded" if verdict.passed else "failed"
        ns.error = None if verdict.passed else verdict.message
        if verdict.passed:
            state.facts = sorted(set(state.facts) | set(ns.result.observed_effects))
        self._feedback(graph, node, ns)
        self._event(graph, state, node_id, ns.status, category=verdict.category)

    def _feedback(self, graph: ExecutionGraph, node: SkillNode, ns: NodeState) -> None:
        if node.skill:
            self.registry.record_feedback(
                node.skill.id,
                node.skill.version,
                node.id,
                ns.status == "succeeded",
                {
                    "error": ns.error,
                    "attempt": ns.attempt,
                    "graph_id": graph.id,
                    "graph_version": graph.version,
                    "recommendation_signals": graph.metadata.get(
                        "recommendation_signals_by_skill", {}
                    ).get(node.skill.id, []),
                },
            )
