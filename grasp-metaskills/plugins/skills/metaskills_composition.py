"""Pure native-spec composition adapted from MIT core/resolution.rs (dcd3fb55).

The caller supplies already projected native JSON specs, not a second registry.
Functions copy their inputs and return transient resolution values.
"""

from copy import deepcopy
from typing import Any, Mapping

from pydantic import Field

from ..contracts import ContractModel

MAX_INHERITANCE_DEPTH = 5
Spec = dict[str, Any]
Repository = Mapping[str, Spec]


class ResolvedSkillSpec(ContractModel):
    spec: dict[str, Any]
    inheritance_chain: list[str]
    included_from: list[str] = Field(default_factory=list)
    warnings: list[dict[str, Any]] = Field(default_factory=list)


def detect_inheritance_cycle(skill_id: str, repository: Repository) -> list[str] | None:
    chain: list[str] = []
    current = skill_id
    while True:
        if current in chain:
            return chain[chain.index(current) :] + [current]
        chain.append(current)
        parent = repository.get(current, {}).get("extends")
        if parent is None:
            return None
        current = parent


def detect_full_cycle(skill_id: str, repository: Repository) -> list[str] | None:
    visited: set[str] = set()
    path: list[str] = []

    def visit(id: str) -> list[str] | None:
        if id in visited:
            return path[path.index(id) :] + [id] if id in path else None
        visited.add(id)
        path.append(id)
        skill = repository.get(id)
        if skill is not None:
            references = [skill["extends"]] if skill.get("extends") is not None else []
            references += [include["skill"] for include in skill.get("includes", [])]
            for reference in references:
                cycle = visit(reference)
                if cycle:
                    return cycle
        path.pop()
        return None

    return visit(skill_id)


def get_inheritance_chain(skill_id: str, repository: Repository) -> list[str]:
    chain: list[str] = []
    current = skill_id
    while True:
        if current in chain:
            raise ValueError(f"cyclic inheritance: {chain}")
        chain.append(current)
        parent = repository.get(current, {}).get("extends")
        if parent is None:
            return list(reversed(chain))
        current = parent


def _merge(parent: Spec, child: Spec) -> Spec:
    result = deepcopy(parent)
    result["metadata"]["id"] = child["metadata"]["id"]
    result["format_version"] = child.get("format_version", "1.0")
    for field in (
        "name",
        "description",
        "version",
        "tags",
        "requires",
        "provides",
        "platforms",
        "context",
    ):
        if child["metadata"].get(field):
            result["metadata"][field] = deepcopy(child["metadata"][field])
    for field in ("author", "license"):
        if child["metadata"].get(field) is not None:
            result["metadata"][field] = child["metadata"][field]
    result["extends"] = None
    for flag in ("replace_rules", "replace_examples", "replace_pitfalls", "replace_checklist"):
        result[flag] = False
    result["includes"] = deepcopy(child.get("includes", []))
    sections = result.setdefault("sections", [])
    by_id = {section["id"]: index for index, section in enumerate(sections)}
    flags = {
        "rule": "replace_rules",
        "code": "replace_examples",
        "pitfall": "replace_pitfalls",
        "checklist": "replace_checklist",
    }
    for section in child.get("sections", []):
        if section["id"] not in by_id:
            by_id[section["id"]] = len(sections)
            sections.append(deepcopy(section))
            continue
        target = sections[by_id[section["id"]]]
        by_type: dict[str, list[Spec]] = {}
        for block in target.get("blocks", []):
            by_type.setdefault(block["block_type"], []).append(block)
        for block in section.get("blocks", []):
            kind = block["block_type"]
            if child.get(flags.get(kind, ""), False):
                # Source replaces on *each* child block: only the last survives.
                by_type[kind] = [deepcopy(block)]
            else:
                by_type.setdefault(kind, []).append(deepcopy(block))
        order = ("text", "rule", "code", "command", "pitfall", "checklist")
        target["blocks"] = [block for kind in order for block in by_type.pop(kind, [])]
        target["blocks"] += [block for blocks in by_type.values() for block in blocks]
        if section.get("title"):
            target["title"] = section["title"]
    return result


def resolve_extends(skill: Spec, repository: Repository) -> ResolvedSkillSpec:
    id = skill["metadata"]["id"]
    parent_id = skill.get("extends")
    if parent_id is None:
        return ResolvedSkillSpec(spec=deepcopy(skill), inheritance_chain=[id])
    cycle = detect_inheritance_cycle(id, repository)
    if cycle:
        raise ValueError(f"cyclic inheritance: {cycle}")
    if parent_id not in repository:
        raise ValueError(f"parent skill not found: {parent_id} (child {id})")
    parent = resolve_extends(repository[parent_id], repository)
    chain = parent.inheritance_chain + [id]
    warnings = []
    if len(chain) > MAX_INHERITANCE_DEPTH:
        warnings.append({"type": "DeepInheritance", "depth": len(chain), "chain": chain})
    return ResolvedSkillSpec(
        spec=_merge(parent.spec, skill),
        inheritance_chain=chain,
        included_from=parent.included_from,
        warnings=warnings + parent.warnings,
    )


def _apply_include(target: Spec, source: Spec, include: Spec) -> None:
    section_id = include["into"]
    kind = {
        "rules": "rule",
        "examples": "code",
        "pitfalls": "pitfall",
        "checklist": "checklist",
        "context": "text",
    }[section_id]
    blocks = []
    for section in source.get("sections", []):
        filters = include.get("sections")
        if (
            filters is not None
            and section["id"] not in filters
            and section.get("title") not in filters
        ):
            continue
        for block in section.get("blocks", []):
            if block["block_type"] == kind:
                copy = deepcopy(block)
                if include.get("prefix") is not None:
                    copy["content"] = include["prefix"] + copy["content"]
                blocks.append(copy)
    if not blocks:
        return
    sections = target.setdefault("sections", [])
    section = next((s for s in sections if s["id"] == section_id), None)
    if section is None:
        sections.append({"id": section_id, "title": section_id.title(), "blocks": blocks})
    elif include.get("position", "append") == "prepend":
        section["blocks"] = blocks + section.get("blocks", [])
    else:
        section.setdefault("blocks", []).extend(blocks)


def resolve_full(skill: Spec, repository: Repository) -> ResolvedSkillSpec:
    resolved = resolve_extends(skill, repository)
    cycle = detect_full_cycle(skill["metadata"]["id"], repository)
    if cycle:
        raise ValueError(f"cyclic inheritance: {cycle}")
    for include in resolved.spec.get("includes", []):
        source = repository.get(include["skill"])
        if source is None:
            resolved.warnings.append(
                {
                    "type": "IncludedSkillNotFound",
                    "skill_id": include["skill"],
                    "included_by": resolved.spec["metadata"]["id"],
                }
            )
            continue
        included = resolve_full(source, repository)
        _apply_include(resolved.spec, included.spec, include)
        resolved.included_from.append(include["skill"])
        resolved.warnings.extend(included.warnings)
    by_target: dict[str, list[str]] = {}
    for include in skill.get("includes", []):
        by_target.setdefault(include["into"], []).append(include["skill"])
    for target, sources in by_target.items():
        if len(sources) > 3:
            resolved.warnings.append(
                {
                    "type": "ManyIncludes",
                    "target": target,
                    "count": len(sources),
                    "sources": sources,
                }
            )
    resolved.spec["includes"] = []
    return resolved
