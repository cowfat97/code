"""MIT adaptation of meta_skill core/dependencies.rs, dcd3fb55.

Uses unified Skill snapshots; metadata.requires/provides are capability strings.
Explicit SkillDependency version requirements belong to the unified registry and
are not interpreted by this upstream capability resolver.
"""

from collections import deque
from enum import StrEnum
from typing import Iterable

from pydantic import Field

from ..contracts import ContractModel, Skill


class DependencyLoadMode(StrEnum):
    OFF = "off"
    AUTO = "auto"
    FULL = "full"
    OVERVIEW = "overview"


class DisclosureLevel(StrEnum):
    MINIMAL = "minimal"
    OVERVIEW = "overview"
    STANDARD = "standard"
    FULL = "full"
    COMPLETE = "complete"


class CapabilityEdge(ContractModel):
    source: str
    target: str
    capability: str


class SkillLoadPlan(ContractModel):
    skill_id: str
    disclosure: DisclosureLevel
    reason: str


class MissingCapability(ContractModel):
    required_by: str
    capability: str


class ResolvedDependencyPlan(ContractModel):
    ordered: list[SkillLoadPlan] = Field(default_factory=list)
    missing: list[MissingCapability] = Field(default_factory=list)
    cycles: list[list[str]] = Field(default_factory=list)

    def is_ok(self) -> bool:
        return not self.has_issues()

    def has_issues(self) -> bool:
        return bool(self.missing or self.cycles)


def _capabilities(skill: Skill, key: str) -> list[str]:
    value = skill.metadata.get(key, [])
    if not isinstance(value, list) or not all(isinstance(x, str) for x in value):
        raise ValueError(f"{skill.id}: metadata.{key} must be a list of strings")
    return value


def capability_edges(skills: Iterable[Skill]) -> list[CapabilityEdge]:
    """Build sorted edges to every provider, excluding self edges.

    As in upstream add_skill, reusing an ID replaces the node but retains its
    previous provider index entries. This function accepts a sequence, not a registry.
    """
    nodes, providers = _index(skills)
    return _edges(nodes, providers)


def _index(skills: Iterable[Skill]) -> tuple[dict[str, Skill], dict[str, list[str]]]:
    nodes = {}
    providers: dict[str, list[str]] = {}
    for skill in skills:
        for capability in _capabilities(skill, "provides"):
            providers.setdefault(capability, []).append(skill.id)
        _capabilities(skill, "requires")
        nodes[skill.id] = skill
    return nodes, providers


def _edges(nodes: dict[str, Skill], providers: dict[str, list[str]]) -> list[CapabilityEdge]:
    return [
        CapabilityEdge(source=id, target=provider, capability=cap)
        for id, node in sorted(nodes.items())
        for cap in sorted(_capabilities(node, "requires"))
        for provider in sorted(providers.get(cap, []))
        if provider != id
    ]


def resolve_dependencies(
    skills: Iterable[Skill],
    root_skill_id: str,
    root_disclosure: DisclosureLevel | str = DisclosureLevel.STANDARD,
    mode: DependencyLoadMode | str = DependencyLoadMode.AUTO,
    max_depth: int = 100,
) -> ResolvedDependencyPlan:
    """BFS closure, DFS back-edge detection, reverse Kahn order, disclosure.

    Upstream silently truncates closure at max_depth, and accepts unknown roots.
    Cycle traversal starts in sorted order here: upstream HashSet order is random.
    """
    mode, root_disclosure = DependencyLoadMode(mode), DisclosureLevel(root_disclosure)
    if max_depth < 0:
        raise ValueError("max_depth must be nonnegative")
    if mode == DependencyLoadMode.OFF:
        return ResolvedDependencyPlan(
            ordered=[
                SkillLoadPlan(skill_id=root_skill_id, disclosure=root_disclosure, reason="root")
            ]
        )
    nodes, providers = _index(skills)
    edges = _edges(nodes, providers)
    direct: dict[str, list[str]] = {id: [] for id in nodes}
    for edge in edges:
        direct[edge.source].append(edge.target)
    closure, queue, missing = {root_skill_id}, deque([root_skill_id]), []
    for _ in range(max_depth):
        if not queue:
            break
        for _ in range(len(queue)):
            current = queue.popleft()
            if current not in nodes:
                continue
            for cap in sorted(_capabilities(nodes[current], "requires")):
                if cap not in providers:
                    missing.append(MissingCapability(required_by=current, capability=cap))
                else:
                    for provider in sorted(providers[cap]):
                        if provider not in closure:
                            closure.add(provider)
                            queue.append(provider)
    visited: set[str] = set()
    active: set[str] = set()
    path: list[str] = []
    cycles: list[list[str]] = []

    def visit(id: str) -> None:
        visited.add(id)
        active.add(id)
        path.append(id)
        for dep in direct.get(id, []):
            if dep not in closure:
                continue
            if dep not in visited:
                visit(dep)
            elif dep in active:
                cycles.append(path[path.index(dep) :].copy())
        path.pop()
        active.remove(id)

    for id in sorted(closure):
        if id not in visited:
            visit(id)
    if cycles:
        order = sorted(closure)
    else:
        indegrees = dict.fromkeys(closure, 0)
        adj = {id: sorted(dep for dep in direct.get(id, []) if dep in closure) for id in closure}
        for deps in adj.values():
            for dep in deps:
                indegrees[dep] += 1
        ready, order = deque(sorted(id for id in closure if not indegrees[id])), []
        while ready:
            id = ready.popleft()
            order.append(id)
            for dep in adj[id]:
                indegrees[dep] -= 1
                if not indegrees[dep]:
                    ready.append(dep)
        order.reverse()
    dep_level = (
        DisclosureLevel.FULL if mode == DependencyLoadMode.FULL else DisclosureLevel.OVERVIEW
    )
    return ResolvedDependencyPlan(
        ordered=[
            SkillLoadPlan(
                skill_id=id,
                disclosure=root_disclosure if id == root_skill_id else dep_level,
                reason="root" if id == root_skill_id else f"dependency of {root_skill_id}",
            )
            for id in order
        ],
        missing=missing,
        cycles=cycles,
    )
