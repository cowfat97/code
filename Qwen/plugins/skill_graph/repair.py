"""GraSP's five local operators with transactional safety extensions.

Ported from skill-dag/index.js BUILTIN_OPERATORS/helperBag/repairWith (MIT).
New versions and checked invalidation are integration extensions.
"""

from __future__ import annotations

import re
from typing import Any, Protocol

from ..contracts import (
    DependencyEdge,
    ExecutionGraph,
    ExecutionTrace,
    GraphState,
    NodeResult,
    NodeState,
    RepairEvent,
    RepairOperation,
    RepairResult,
    Skill,
    SkillNode,
)

DEFAULT_ORDER = {
    "precondition": ["InsertPrereq", "Rebind", "Substitute", "Rewire", "Bypass"],
    "postcondition": ["Substitute", "Rebind", "Rewire", "Bypass", "InsertPrereq"],
    "execution": ["Substitute", "Rebind", "Rewire", "Bypass"],
    "timeout": ["Substitute", "Bypass"],
}


class RepairLibrary(Protocol):
    def list(self) -> list[Skill]: ...


class RepairError(ValueError):
    """A patch fails an invariant and has not been committed."""


def _bound(skill: Skill, args: list[str], node_id: str) -> SkillNode:
    from .compiler import CompilationError, bind_skill

    try:
        return bind_skill(skill, args, node_id)
    except CompilationError as exc:
        raise RepairError(str(exc)) from exc


def _derive(skill: Skill, concrete: str) -> list[str] | None:
    match = re.fullmatch(r"([a-z_]+)\(([^)]*)\)", concrete)
    if not match:
        return [] if concrete in skill.contract.effects and not skill.contract.params else None
    name, body = match.groups()
    actual = [s.strip() for s in body.split(",")]
    for effect in skill.contract.effects:
        template = re.fullmatch(r"([a-z_]+)\(([^)]*)\)", effect)
        if not template or template[1] != name:
            continue
        formal = [s.strip() for s in template[2].split(",")]
        if len(formal) != len(actual):
            continue
        values: dict[str, str] = {}
        valid = True
        for param, arg in zip(formal, actual, strict=True):
            if param in skill.contract.params:
                if param in values and values[param] != arg:
                    valid = False
                values[param] = arg
            elif param != arg:
                valid = False
        if valid and all(p in values for p in skill.contract.params):
            return [values[p] for p in skill.contract.params]
    return None


def _downstream(graph: ExecutionGraph, node: SkillNode) -> set[str]:
    wanted = set(graph.goal)
    for edge in graph.edges:
        if edge.source == node.id:
            wanted.update(graph.node(edge.target).preconditions)
    return wanted.intersection(node.effects)


def _missing(graph: ExecutionGraph) -> set[tuple[str, str]]:
    """Check producer ancestry, rather than accepting a fact from any DAG node."""
    missing = set()
    ancestors: dict[str, set[str]] = {n.id: set() for n in graph.nodes}
    for node_id in graph.topological_order():
        for edge in graph.edges:
            if edge.target == node_id:
                ancestors[node_id].update(ancestors[edge.source] | {edge.source})
        available = set(graph.initial_conditions)
        for parent in ancestors[node_id]:
            available.update(graph.node(parent).effects)
        for pre in graph.node(node_id).preconditions:
            if pre not in available:
                missing.add((node_id, pre))
    return missing


class RepairEngine:
    """Apply bounded operators on copies, validate, then atomically expose a version."""

    def __init__(
        self,
        registry: RepairLibrary,
        *,
        l_max: int = 3,
        e_max: int = 5,
        max_repairs: int = 8,
        operator_order: list[str] | None = None,
    ) -> None:
        if min(l_max, e_max, max_repairs) < 0:
            raise ValueError("repair budgets must be nonnegative")
        self.registry = registry
        self.l_max = l_max
        self.e_max = e_max
        self.max_repairs = max_repairs
        self.operator_order = operator_order

    def _validate(
        self, old: ExecutionGraph, new: ExecutionGraph, touched: set[str], facts: set[str]
    ) -> None:
        errors = new.validate_graph()
        if errors:
            raise RepairError("; ".join(errors))
        # Original upstream graphs can already lack facts (strict=False). A patch
        # may fix those incrementally but cannot introduce any new missing fact.
        introduced = _missing(new) - _missing(old)
        for node_id in touched:
            introduced.update(
                (nid, pre) for nid, pre in _missing(new) if nid == node_id and pre not in facts
            )
        introduced = {(nid, pre) for nid, pre in introduced if pre not in facts}
        if introduced:
            raise RepairError(f"missing precondition after repair: {sorted(introduced)}")
        from .compiler import schema_compatible

        for node in new.nodes:
            if not node.skill:
                continue
            # Capability names are metadata dependencies, not observed predicates.
            # A replacement cannot silently acquire a new unscheduled prerequisite.
            from ..skills.metaskills_dependencies import capability_edges

            snapshot = [n.skill for n in new.nodes if n.skill]
            edges = capability_edges(snapshot)
            available = {c for skill in snapshot for c in skill.metadata.get("provides", [])}
            missing_capabilities = set(node.skill.metadata.get("requires", [])) - available
            if missing_capabilities:
                raise RepairError(
                    f"missing capability after repair: {sorted(missing_capabilities)}"
                )
            for edge in edges:
                if edge.source != node.skill.id:
                    continue
                providers = [n for n in new.nodes if n.skill and n.skill.id == edge.target]
                if not any(
                    node.id in new.descendants({p.id}) and node.id != p.id for p in providers
                ):
                    raise RepairError(f"unscheduled capability dependency: {edge.capability}")
            for dependency in node.skill.dependencies:
                candidates = [n for n in new.nodes if n.skill and n.skill.id == dependency.id]
                if not any(
                    n.skill
                    and node.id in new.descendants({n.id})
                    and n.id != node.id
                    for n in candidates
                ):
                    raise RepairError(f"invalid skill dependency: {dependency.id}")
            from jsonschema import Draft202012Validator

            schema = node.skill.contract.input_schema
            required = set(schema.get("required", []))
            if not required <= (set(node.bindings) | set(node.input_values)):
                raise RepairError(f"missing required repair input: {node.id}")
            properties = schema.get("properties", {})
            for key, value in node.input_values.items():
                value_schema = properties.get(key, schema.get("additionalProperties", {}))
                value_errors = list(Draft202012Validator(value_schema).iter_errors(value))
                if value_errors:
                    raise RepairError(f"repair input schema: {value_errors[0].message}")
            for key, binding in node.bindings.items():
                source = new.node(binding.node_id)
                if not source.skill:
                    raise RepairError("data binding from structural node")
                output = source.skill.contract.output_schema.get("properties", {})
                if binding.output_key not in output or not schema_compatible(
                    output[binding.output_key], properties.get(key, {})
                ):
                    raise RepairError("incompatible replacement input/output contract")

    def apply(
        self, graph: ExecutionGraph, state: GraphState, operation: RepairOperation
    ) -> RepairResult:
        if state.graph_id != graph.id or state.graph_version != graph.version:
            raise RepairError("repair state does not match graph version")
        node = graph.node(operation.node_id)
        attempts = state.repair_attempts.get(node.id, 0)
        if (
            attempts >= node.repair_budget
            or sum(state.repair_attempts.values()) >= self.max_repairs
        ):
            raise RepairError("local-exhausted")
        patched = graph.model_copy(deep=True)
        updated = state.model_copy(deep=True)
        target = patched.node(node.id)
        facts = set(graph.initial_conditions) | set(state.facts)
        touched = {node.id}
        before_edges = {e.model_dump_json() for e in patched.edges}
        before_ids = {n.id for n in patched.nodes}
        requirements = _downstream(graph, node)
        if operation.type == "Bypass":
            if not requirements <= facts:
                raise RepairError("Bypass requires observed downstream facts")
            retained_result = state.nodes.get(node.id, NodeState()).result
            for consumer in graph.nodes:
                for binding in consumer.bindings.values():
                    if binding.node_id == node.id and (
                        not retained_result or binding.output_key not in retained_result.output
                    ):
                        raise RepairError("Bypass cannot manufacture required data")
            target.preconditions = []
            target.effects = sorted(requirements)
        elif operation.type == "Rebind":
            if not target.skill or operation.args is None:
                raise RepairError("Rebind requires skill and args")
            replacement = _bound(target.skill, operation.args, node.id)
            target.args = replacement.args
            target.preconditions = replacement.preconditions
            target.effects = replacement.effects
        elif operation.type == "Substitute":
            replacement_skill = operation.replacement
            if not replacement_skill or not target.skill or replacement_skill.id == target.skill.id:
                raise RepairError("Substitute requires a different skill")
            args = operation.args or []
            replacement = _bound(replacement_skill, args, node.id)
            if not requirements <= set(replacement.effects):
                raise RepairError("replacement does not preserve downstream effects")
            target.skill = replacement.skill
            target.args = replacement.args
            target.preconditions = replacement.preconditions
            target.effects = replacement.effects
            # Existing concrete values/bindings are revalidated below and at run time.
            from jsonschema import Draft202012Validator

            if not target.bindings:
                errors = list(
                    Draft202012Validator(replacement_skill.contract.input_schema).iter_errors(
                        target.input_values
                    )
                )
                if errors:
                    raise RepairError(f"replacement input schema: {errors[0].message}")
        elif operation.type == "InsertPrereq":
            if not operation.prerequisites:
                raise RepairError("InsertPrereq requires at least one new skill")
            for prereq in operation.prerequisites:
                if prereq.id in {n.id for n in patched.nodes}:
                    raise RepairError("duplicate inserted node")
                patched.nodes.append(prereq.model_copy(deep=True))
                touched.add(prereq.id)
                for effect in prereq.effects:
                    if effect in target.preconditions:
                        patched.edges.append(
                            DependencyEdge(
                                source=prereq.id, target=target.id, type="state", label=effect
                            )
                        )
                if any(n.id == "src" for n in patched.nodes):
                    patched.edges.append(
                        DependencyEdge(source="src", target=prereq.id, type="order", label="repair")
                    )
        elif operation.type == "Rewire":
            candidate = operation.edge or next(
                (e for e in patched.edges if e.target == target.id and e.type == "order"), None
            )
            if candidate is None or candidate.type != "order" or candidate not in patched.edges:
                raise RepairError("Rewire removes an existing order edge only")
            if candidate.target != target.id:
                raise RepairError("Rewire target does not match node")
            patched.edges.remove(candidate)

        if operation.type in {"Rebind", "Substitute", "InsertPrereq"}:
            # Rebuild state edges incident to changed nodes. Preserve order edges
            # and real data bindings; neither can be inferred from predicate text.
            patched.edges = [
                e
                for e in patched.edges
                if not (e.type == "state" and (e.source in touched or e.target in touched))
            ]
            for source in patched.nodes:
                for dest in patched.nodes:
                    if (
                        source.kind != "skill"
                        or dest.kind != "skill"
                        or source.id == dest.id
                        or not ({source.id, dest.id} & touched)
                    ):
                        continue
                    for effect in source.effects:
                        if effect in dest.preconditions:
                            patched.edges.append(
                                DependencyEdge(
                                    source=source.id, target=dest.id, type="state", label=effect
                                )
                            )
        added = {e.model_dump_json() for e in patched.edges} - before_edges
        added_nodes = {n.id for n in patched.nodes} - before_ids
        if len(added_nodes) > self.l_max or len(added) > self.e_max:
            raise RepairError("patch exceeds l_max/e_max")
        self._validate(graph, patched, touched, facts)
        affected = graph.descendants(touched & before_ids) | patched.descendants(touched)
        patched.version += 1
        updated.graph_version = patched.version
        updated.status = "pending"
        updated.repair_attempts[node.id] = attempts + 1
        for affected_id in affected:
            previous = updated.nodes.get(affected_id)
            # Idempotency keys change on a genuinely new attempt after repair.
            updated.nodes[affected_id] = NodeState(attempt=previous.attempt if previous else 0)
        if operation.type == "Bypass":
            updated.nodes[node.id].status = "bypassed"
            previous_result = state.nodes.get(node.id, NodeState()).result
            updated.nodes[node.id].result = NodeResult(
                output=previous_result.output if previous_result else {},
                observed_effects=sorted(requirements),
            )
        retained = set(patched.initial_conditions)
        for node_state in updated.nodes.values():
            if node_state.status in {"succeeded", "bypassed"} and node_state.result:
                retained.update(node_state.result.observed_effects)
        updated.facts = sorted(retained)
        audit: dict[str, Any] = {
            "operator": operation.type,
            "node_id": node.id,
            "from_version": graph.version,
            "to_version": patched.version,
            "affected": sorted(affected),
            "added_nodes": sorted(added_nodes),
            "added_edges": len(added),
            "operation": operation.model_dump(mode="json"),
            "previous_node": node.model_dump(mode="json"),
        }
        updated.repair_audit.append(audit)
        updated.trace.append(ExecutionTrace(node_id=node.id, event="repair", details=audit))
        return RepairResult(repaired=True, graph=patched, state=updated, operation=operation)

    def repair(self, graph: ExecutionGraph, state: GraphState, event: RepairEvent) -> RepairResult:
        node = graph.node(event.node_id)
        attempts = state.repair_attempts.get(node.id, 0)
        if (
            attempts >= node.repair_budget
            or sum(state.repair_attempts.values()) >= self.max_repairs
        ):
            exhausted = state.model_copy(deep=True)
            audit = {
                "operator": None,
                "node_id": node.id,
                "reason": "local-exhausted",
                "from_version": graph.version,
                "to_version": graph.version,
            }
            exhausted.repair_audit.append(audit)
            exhausted.trace.append(
                ExecutionTrace(node_id=node.id, event="repair-exhausted", details=audit)
            )
            return RepairResult(
                repaired=False, graph=graph, state=exhausted, reason="local-exhausted"
            )
        facts = set(event.state) | set(state.facts) | set(graph.initial_conditions)
        library = self.registry.list()
        rejected = []
        order = (
            self.operator_order
            if self.operator_order is not None
            else DEFAULT_ORDER.get(event.type, DEFAULT_ORDER["precondition"])
        )
        for name in order:
            operation: RepairOperation | None = None
            if name == "Bypass" and _downstream(graph, node) <= facts:
                operation = RepairOperation(type="Bypass", node_id=node.id)
            elif name == "Rebind" and event.args is not None:
                operation = RepairOperation(type="Rebind", node_id=node.id, args=event.args)
            elif name == "Substitute":
                needed = _downstream(graph, node)
                for candidate in library:
                    if not needed or (node.skill and candidate.id == node.skill.id):
                        continue
                    bindings = (
                        [[]]
                        if not candidate.contract.params
                        else [
                            derived
                            for predicate in sorted(needed)
                            if (derived := _derive(candidate, predicate)) is not None
                        ]
                    )
                    for args in bindings:
                        if not needed <= set(_bound(candidate, args, node.id).effects):
                            continue
                        candidate_op = RepairOperation(
                            type="Substitute", node_id=node.id, replacement=candidate, args=args
                        )
                        try:
                            supplied = state.model_copy(deep=True)
                            supplied.facts = sorted(facts)
                            return self.apply(graph, supplied, candidate_op)
                        except RepairError as exc:
                            rejected.append(str(exc))
            elif name == "InsertPrereq":
                prerequisites: list[SkillNode] = []
                for missing in [p for p in node.preconditions if p not in facts]:
                    for candidate in library:
                        prereq_args = _derive(candidate, missing)
                        if prereq_args is None:
                            continue
                        existing = {n.id for n in graph.nodes} | {n.id for n in prerequisites}
                        count = 1
                        while f"{candidate.id}:{count}" in existing:
                            count += 1
                        prerequisites.append(
                            _bound(candidate, prereq_args, f"{candidate.id}:{count}")
                        )
                        break
                if prerequisites:
                    operation = RepairOperation(
                        type="InsertPrereq", node_id=node.id, prerequisites=prerequisites
                    )
            elif name == "Rewire":
                if event.type == "precondition" and any(p not in facts for p in node.preconditions):
                    continue
                operation = RepairOperation(type="Rewire", node_id=node.id)
            if operation:
                try:
                    # A supplied event state is observed evidence, not a new declaration.
                    supplied = state.model_copy(deep=True)
                    supplied.facts = sorted(facts)
                    return self.apply(graph, supplied, operation)
                except RepairError as exc:
                    rejected.append(str(exc))
        failed = state.model_copy(deep=True)
        failed.repair_attempts[node.id] = attempts + 1
        failed.repair_audit.append(
            {
                "operator": None,
                "node_id": node.id,
                "reason": "local-failed",
                "rejected": rejected,
                "from_version": graph.version,
                "to_version": graph.version,
            }
        )
        failed.trace.append(
            ExecutionTrace(node_id=node.id, event="repair-failed", details={"rejected": rejected})
        )
        return RepairResult(repaired=False, graph=graph, state=failed, reason="local-failed")
