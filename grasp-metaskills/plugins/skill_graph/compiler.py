"""MIT-derived GraSP compiler plus explicit deterministic planning extensions."""

from __future__ import annotations

import inspect
import re
from copy import deepcopy
from typing import Any

from jsonschema import Draft202012Validator
from packaging.specifiers import SpecifierSet
from packaging.version import Version

from ..contracts import DependencyEdge, ExecutionGraph, InputBinding, Skill, SkillNode
from ..skills.metaskills_dependencies import capability_edges, resolve_dependencies


class CompilationError(ValueError):
    def __init__(self, message: str, *, details: Any = None) -> None:
        super().__init__(message)
        self.details = details


def parse_pred(predicate: str) -> tuple[str, list[str]] | None:
    match = re.fullmatch(r"([a-z_]+)\(([^)]*)\)", predicate)
    return (match[1], [a.strip() for a in match[2].split(",") if a.strip()]) if match else None


def bind_skill(skill: Skill, args: list[str], node_id: str | None = None) -> SkillNode:
    if len(args) != len(skill.contract.params):
        raise CompilationError(f"arity {len(args)} != {len(skill.contract.params)}: {skill.id}")
    mapping = dict(zip(skill.contract.params, args, strict=True))

    def bind(value: str) -> str:
        # One pass prevents an actual argument named like another parameter
        # from being captured by a subsequent substitution.
        if not mapping:
            return value
        pattern = r"\b(?:" + "|".join(re.escape(p) for p in mapping) + r")\b"
        return re.sub(pattern, lambda match: mapping[match[0]], value)

    return SkillNode(
        id=node_id or f"{skill.id}:1",
        skill=skill.model_copy(deep=True),
        args=args,
        preconditions=[bind(p) for p in skill.contract.preconditions],
        effects=[bind(e) for e in skill.contract.effects],
    )


def infer_edges(
    nodes: list[SkillNode], order_hints: list[dict[str, Any]] | None = None
) -> list[DependencyEdge]:
    edges: list[DependencyEdge] = []

    def add(source: str, target: str, kind: Any, label: str) -> None:
        edge = DependencyEdge(source=source, target=target, type=kind, label=label)
        if source != target and edge not in edges:
            edges.append(edge)

    for first in nodes:
        for second in nodes:
            if first.id == second.id:
                continue
            common = [e for e in first.effects if e in second.preconditions]
            for predicate in common:
                add(first.id, second.id, "state", predicate)
            for arg in second.args:
                if any((p := parse_pred(e)) and p[1] == [arg] for e in common):
                    add(first.id, second.id, "data", f"{arg} → {second.id}")
    for hint in order_hints or []:
        add(
            hint.get("from", hint.get("source", "")),
            hint.get("to", hint.get("target", "")),
            "order",
            hint.get("label", "order"),
        )
    return edges


def backward_filter(nodes: list[SkillNode], goal: list[str], initial: list[str]) -> list[SkillNode]:
    kept: set[str] = set()
    produced = set(initial)
    needed = set(goal) - produced
    changed = True
    while changed:
        changed = False
        for node in nodes:
            if node.id not in kept and needed.intersection(node.effects):
                kept.add(node.id)
                produced.update(node.effects)
                needed.update(set(node.preconditions) - produced)
                changed = True
    return [node for node in nodes if node.id in kept]


def schema_compatible(source_schema: dict[str, Any], target_schema: dict[str, Any]) -> bool:
    """Conservative supported JSON Schema containment; not general implication."""
    source, target = source_schema, target_schema
    if not target or source == target:
        return True
    st, tt = source.get("type"), target.get("type")
    source_types = set(st if isinstance(st, list) else [st]) if st else set()
    target_types = set(tt if isinstance(tt, list) else [tt]) if tt else set()
    if "integer" in source_types and "number" in target_types:
        target_types.add("integer")
    if target_types and (not source_types or not source_types <= target_types):
        return False
    if "const" in target and source.get("const", object()) != target["const"]:
        return False
    if "enum" in target:
        values = source.get("enum", [source["const"]] if "const" in source else None)
        if values is None or any(v not in target["enum"] for v in values):
            return False
    required = set(target.get("required", []))
    if not required <= set(source.get("required", [])):
        return False
    for key, value in target.get("properties", {}).items():
        if key in source.get("properties", {}):
            if not schema_compatible(source["properties"][key], value):
                return False
        elif key in required or source.get("additionalProperties", True) is not False:
            return False
    if "items" in target and (
        not isinstance(target["items"], dict)
        or not isinstance(source.get("items"), dict)
        or not schema_compatible(source["items"], target["items"])
    ):
        return False
    for lower in ("minimum", "exclusiveMinimum", "minLength", "minItems", "minProperties"):
        if lower in target and (lower not in source or source[lower] < target[lower]):
            return False
    for upper in ("maximum", "exclusiveMaximum", "maxLength", "maxItems", "maxProperties"):
        if upper in target and (upper not in source or source[upper] > target[upper]):
            return False
    handled = {
        "type",
        "enum",
        "const",
        "required",
        "properties",
        "items",
        "minimum",
        "exclusiveMinimum",
        "minLength",
        "minItems",
        "minProperties",
        "maximum",
        "exclusiveMaximum",
        "maxLength",
        "maxItems",
        "maxProperties",
        "title",
        "description",
        "$schema",
        "default",
        "examples",
    }
    return all(
        source.get(key, object()) == value for key, value in target.items() if key not in handled
    )


def _acyclic(nodes: list[SkillNode], edges: list[DependencyEdge]) -> bool:
    try:
        ExecutionGraph(nodes=nodes, edges=edges).topological_order()
        return True
    except ValueError:
        return False


async def _resolve(value: Any) -> Any:
    return await value if inspect.isawaitable(value) else value


class GraphCompiler:
    def __init__(
        self,
        registry: Any,
        proposer: Any = None,
        *,
        strict_preconditions: bool = True,
        discovery_mode: str = "keyword",
    ) -> None:
        if discovery_mode not in {"keyword", "fulltext", "semantic", "hybrid"}:
            raise ValueError("invalid discovery mode")
        self.registry = registry
        self.proposer = proposer
        self.strict_preconditions = strict_preconditions
        self.discovery_mode = discovery_mode

    async def compile(
        self,
        *,
        goal: list[str],
        task: str = "",
        proposal: list[dict[str, Any]] | None = None,
        initial_conditions: list[str] | None = None,
        order_hints: list[dict[str, Any]] | None = None,
        inputs: dict[str, dict[str, Any]] | None = None,
    ) -> ExecutionGraph:
        skills = list(await _resolve(self.registry.list()))
        initial = initial_conditions or []
        metadata: dict[str, Any] = {"rejected": []}
        if task:
            from ..skills.retrieval import retrieve

            episodes = self.registry.episodes() if hasattr(self.registry, "episodes") else []
            metadata["retrieval"] = retrieve(skills=skills, goal=goal, task=task, episodes=episodes)
            metadata["routing"] = {k: metadata["retrieval"][k] for k in ("mode", "confidence")}
            metadata["routing"]["policy"] = "deterministic-explicit-goal"
            if hasattr(self.registry, "search"):
                discovery_options: dict[str, Any] = {"limit": len(skills)}
                if self.discovery_mode != "keyword":
                    discovery_options["mode"] = self.discovery_mode
                discovered = await _resolve(self.registry.search(task, **discovery_options))
                metadata["discovery_mode"] = self.discovery_mode
                metadata["recommendation_signals_by_skill"] = deepcopy(
                    getattr(self.registry, "last_search_signals", {})
                )
                priority = {r.skill.id: i for i, r in enumerate(discovered)}
                metadata["registry_discovery"] = [r.skill.id for r in discovered]
                skills.sort(key=lambda s: priority.get(s.id, len(priority)))
            if self.proposer and proposal is None:
                proposal = await self.proposer.propose(task=task, skills=skills, goal=goal)
        by_id = {s.id: s for s in skills}
        nodes: list[SkillNode] = []
        counts: dict[str, int] = {}

        def append(skill: Skill, args: list[str]) -> SkillNode:
            counts[skill.id] = counts.get(skill.id, 0) + 1
            node = bind_skill(skill, args, f"{skill.id}:{counts[skill.id]}")
            nodes.append(node)
            return node

        def achieve(predicate: str, active: set[str]) -> bool:
            if predicate in initial or any(predicate in n.effects for n in nodes):
                return True
            if predicate in active:
                return False
            if len(active) > 128 or len(nodes) > 10000:
                raise CompilationError("planning expansion limit exceeded")
            gp = parse_pred(predicate)
            for candidate in skills:
                for effect in candidate.contract.effects:
                    ep = parse_pred(effect)
                    mapping: dict[str, str] = {}
                    if effect == predicate:
                        pass
                    elif gp and ep and ep[0] == gp[0] and len(ep[1]) == len(gp[1]):
                        valid = True
                        for template, concrete in zip(ep[1], gp[1], strict=True):
                            if template in candidate.contract.params:
                                if template in mapping and mapping[template] != concrete:
                                    valid = False
                                mapping[template] = concrete
                            elif template != concrete:
                                valid = False
                        if not valid:
                            continue
                    else:
                        continue
                    if any(p not in mapping for p in candidate.contract.params):
                        continue
                    saved_nodes, saved_counts = list(nodes), dict(counts)
                    bound = bind_skill(candidate, [mapping[p] for p in candidate.contract.params])
                    if all(achieve(p, active | {predicate}) for p in bound.preconditions):
                        append(candidate, bound.args)
                        return True
                    nodes[:] = saved_nodes
                    counts.clear()
                    counts.update(saved_counts)
            return False

        if proposal is not None:
            for item in proposal:
                skill = by_id.get(item["skill"])
                if item.get("version") and hasattr(self.registry, "get"):
                    try:
                        skill = self.registry.get(item["skill"], item["version"])
                    except KeyError:
                        skill = None
                args = item.get("args", [])
                if skill is None or len(args) != len(skill.contract.params):
                    metadata["rejected"].append(
                        {
                            "skill": item["skill"],
                            "reason": "unknown skill"
                            if skill is None
                            else f"arity {len(args)} != {len(skill.contract.params)}",
                        }
                    )
                    continue
                append(skill, args)
            param_names = {p for s in skills for p in s.contract.params}
            normalized = []
            for g in goal:
                gp = parse_pred(g)
                matches = [
                    e
                    for n in nodes
                    for e in n.effects
                    if gp and (ep := parse_pred(e)) and ep[0] == gp[0] and len(ep[1]) == len(gp[1])
                ]
                normalized.append(
                    matches[0]
                    if gp and matches and g not in matches and all(a in param_names for a in gp[1])
                    else g
                )
            goal = normalized
            nodes = backward_filter(nodes, goal, initial)
        else:
            missing = [g for g in goal if not achieve(g, set())]
            if missing:
                raise CompilationError("goal unreachable: " + ", ".join(missing), details=missing)
        cursor = 0
        dependency_pairs: list[tuple[str, str]] = []
        capability_pairs: set[tuple[str, str, str]] = set()
        while True:
            while cursor < len(nodes):
                node = nodes[cursor]
                cursor += 1
                assert node.skill
                for dependency in node.skill.dependencies:
                    spec = (
                        dependency.version
                        if dependency.version[:1] in "<>=!~"
                        else "==" + dependency.version
                    )
                    options = [
                        s
                        for s in skills
                        if s.id == dependency.id
                        and (dependency.version == "*" or Version(s.version) in SpecifierSet(spec))
                    ]
                    if hasattr(self.registry, "resolve"):
                        try:
                            options.append(self.registry.resolve(dependency.id, dependency.version))
                        except KeyError:
                            pass
                    if not options:
                        raise CompilationError(
                            f"missing dependency: {dependency.id}@{dependency.version}"
                        )
                    selected = max(options, key=lambda s: Version(s.version))
                    found = next(
                        (
                            n
                            for n in nodes
                            if n.skill
                            and n.skill.id == selected.id
                            and n.skill.version == selected.version
                        ),
                        None,
                    )
                    if found is None:
                        if selected.contract.params:
                            raise CompilationError(
                                f"dependency requires explicit arguments: {selected.id}"
                            )
                        if proposal is None and not all(
                            achieve(p, set()) for p in selected.contract.preconditions
                        ):
                            raise CompilationError(
                                f"missing dependency preconditions: {selected.id}"
                            )
                        found = append(selected, [])
                    dependency_pairs.append((found.id, node.id))
                    if len(nodes) > 10000:
                        raise CompilationError("dependency expansion limit exceeded")

            # Explicit dependency pins select snapshots before capability closure.
            # The source graph has one node per ID, so project selected snapshots
            # over the active registry view instead of building another registry.
            selected_skills = dict(by_id)
            for selected_node in nodes:
                assert selected_node.skill
                selected_skills[selected_node.skill.id] = selected_node.skill
            before_capabilities = len(nodes)
            for node in list(nodes):
                assert node.skill
                view = dict(selected_skills)
                view[node.skill.id] = node.skill
                plan = resolve_dependencies(view.values(), node.skill.id)
                if plan.has_issues():
                    raise CompilationError(
                        f"capability dependency resolution failed: {node.skill.id}",
                        details=plan.model_dump(mode="json"),
                    )
                closure = {entry.skill_id for entry in plan.ordered}
                bound_by_id = {node.skill.id: node}
                for entry in plan.ordered:
                    if entry.skill_id == node.skill.id:
                        continue
                    selected = view[entry.skill_id]
                    found = next(
                        (
                            n
                            for n in nodes
                            if n.skill
                            and n.skill.id == selected.id
                            and n.skill.version == selected.version
                        ),
                        None,
                    )
                    if found is None:
                        if selected.contract.params:
                            raise CompilationError(
                                f"capability dependency requires explicit arguments: {selected.id}"
                            )
                        if proposal is None and not all(
                            achieve(p, set()) for p in selected.contract.preconditions
                        ):
                            raise CompilationError(
                                f"missing capability dependency preconditions: {selected.id}"
                            )
                        found = append(selected, [])
                    bound_by_id[entry.skill_id] = found
                for capability_edge in capability_edges(view.values()):
                    if capability_edge.source in closure and capability_edge.target in closure:
                        capability_pairs.add(
                            (
                                bound_by_id[capability_edge.target].id,
                                bound_by_id[capability_edge.source].id,
                                capability_edge.capability,
                            )
                        )
                if len(nodes) > 10000:
                    raise CompilationError("dependency expansion limit exceeded")
            if len(nodes) == before_capabilities:
                break
        edges = infer_edges(nodes, order_hints)
        for dependency_source, dependency_target in dependency_pairs:
            edges.append(
                DependencyEdge(
                    source=dependency_source,
                    target=dependency_target,
                    type="data",
                    label="skill dependency",
                )
            )
        for provider, dependent, capability in sorted(capability_pairs):
            edges.append(
                DependencyEdge(
                    source=provider,
                    target=dependent,
                    type="order",
                    label=f"capability:{capability}",
                )
            )
        ids = {n.id for n in nodes}
        if any(e.source not in ids or e.target not in ids for e in edges):
            raise CompilationError("invalid dependency reference")
        hard = [e for e in edges if e.type != "order" or e.label.startswith("capability:")]
        if not _acyclic(nodes, hard):
            raise CompilationError("cycle among hard edges")
        for edge in [
            e for e in edges if e.type == "order" and not e.label.startswith("capability:")
        ]:
            if _acyclic(nodes, hard + [edge]):
                hard.append(edge)
        edges = hard
        produced = set(initial) | {e for n in nodes for e in n.effects}
        missing_goal = set(goal) - produced
        if missing_goal:
            raise CompilationError("goal completeness failed: " + ", ".join(sorted(missing_goal)))
        missing_pre = {
            n.id: [
                p
                for p in n.preconditions
                if p not in initial
                and not any(p in other.effects for other in nodes if other.id != n.id)
            ]
            for n in nodes
        }
        missing_pre = {k: v for k, v in missing_pre.items() if v}
        metadata["missing_preconditions"] = missing_pre
        if missing_pre and self.strict_preconditions:
            raise CompilationError("missing preconditions", details=missing_pre)
        for node in nodes:
            assert node.skill
            node.input_values = (inputs or {}).get(node.id, {}).copy()
            target_schema = node.skill.contract.input_schema
            properties = target_schema.get("properties", {})
            for key in target_schema.get("required", []):
                if key in node.input_values:
                    errors = list(
                        Draft202012Validator(properties.get(key, {})).iter_errors(
                            node.input_values[key]
                        )
                    )
                    if errors:
                        raise CompilationError(f"input schema mismatch: {node.id}.{key}")
                    continue
                ancestors = {node.id}
                changed = True
                while changed:
                    before = len(ancestors)
                    ancestors.update(e.source for e in edges if e.target in ancestors)
                    changed = len(ancestors) != before
                candidates = [
                    n
                    for n in nodes
                    if n.id in ancestors
                    and n.id != node.id
                    and n.skill
                    and key in n.skill.contract.output_schema.get("properties", {})
                ]
                if len(candidates) != 1:
                    raise CompilationError(f"missing or ambiguous input binding: {node.id}.{key}")
                source = candidates[0]
                assert source.skill
                source_schema = source.skill.contract.output_schema["properties"][key]
                if not schema_compatible(source_schema, properties.get(key, {})):
                    raise CompilationError(
                        f"input/output schema type conflict: {source.id} → {node.id}.{key}"
                    )
                node.bindings[key] = InputBinding(node_id=source.id, output_key=key)
                edge = DependencyEdge(source=source.id, target=node.id, type="data", label=key)
                if edge not in edges:
                    edges.append(edge)
        src = SkillNode(id="src", kind="src", effects=initial)
        snk = SkillNode(id="snk", kind="snk", preconditions=goal)
        for node in nodes:
            if not any(e.target == node.id for e in edges):
                edges.append(
                    DependencyEdge(source="src", target=node.id, type="order", label="start")
                )
            if not any(e.source == node.id for e in edges) or set(node.effects).intersection(goal):
                edges.append(
                    DependencyEdge(source=node.id, target="snk", type="order", label="goal")
                )
        if not nodes:
            edges.append(DependencyEdge(source="src", target="snk", type="order", label="goal"))
        graph = ExecutionGraph(
            task=task,
            goal=goal,
            initial_conditions=initial,
            nodes=[src, *nodes, snk],
            edges=edges,
            metadata=metadata,
        )
        errors = graph.validate_graph()
        if errors:
            raise CompilationError("; ".join(errors))
        return graph
