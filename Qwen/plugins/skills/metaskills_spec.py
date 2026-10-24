"""SkillSpec compatibility mapping from MIT MetaSkills dcd3fb55 core/skill.rs.

There is one executable Skill model. Original structured documents are retained as
provenance; live identity/capability metadata is projected from the unified Skill.
No prose or capability string is promoted to a verifiable GraSP predicate.
"""

from __future__ import annotations

import copy
import hashlib
import json
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from ..contracts import Skill, SkillContract, SkillDependency


class SkillBlock(BaseModel):
    model_config = ConfigDict(extra="allow")
    id: str
    block_type: str = "text"
    content: str


class SkillSection(BaseModel):
    model_config = ConfigDict(extra="allow")
    id: str
    title: str
    blocks: list[SkillBlock] = Field(default_factory=list)


class SkillMetadata(BaseModel):
    model_config = ConfigDict(extra="allow")
    id: str = ""
    name: str = ""
    description: str = ""
    tags: list[str] = Field(default_factory=list)
    requires: list[str] = Field(default_factory=list)
    provides: list[str] = Field(default_factory=list)
    platforms: list[str] = Field(default_factory=list)
    author: str | None = None
    license: str | None = None
    context: dict[str, Any] = Field(default_factory=dict)


class SkillSpec(BaseModel):
    model_config = ConfigDict(extra="allow")
    format_version: str = "1.0"
    metadata: SkillMetadata
    sections: list[SkillSection] = Field(default_factory=list)
    extends: str | None = None
    replace_rules: bool = False
    replace_examples: bool = False
    replace_pitfalls: bool = False
    replace_checklist: bool = False
    includes: list[dict[str, Any]] = Field(default_factory=list)


def normalize_spec(spec: dict[str, Any] | SkillSpec) -> dict[str, Any]:
    """Apply source defaults and serde's skip rules; preserve extension fields."""
    parsed = spec if isinstance(spec, SkillSpec) else SkillSpec.model_validate(spec)
    result = parsed.model_dump(mode="json")
    if result["extends"] is None:
        del result["extends"]
    for key in ("replace_rules", "replace_examples", "replace_pitfalls", "replace_checklist"):
        if not result[key]:
            del result[key]
    if not result["includes"]:
        del result["includes"]
    else:
        for include in result["includes"]:
            include.setdefault("position", "append")
            for key in ("prefix", "sections"):
                if include.get(key) is None:
                    include.pop(key, None)
    context = {k: v for k, v in result["metadata"]["context"].items() if v}
    if context:
        result["metadata"]["context"] = context
    else:
        del result["metadata"]["context"]
    return result


def spec_content_hash(spec: dict[str, Any] | SkillSpec) -> str:
    """Port cli/commands/index.rs compute_spec_hash's compact JSON SHA-256."""
    encoded = json.dumps(normalize_spec(spec), ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(encoded.encode()).hexdigest()


def render_skill_markdown(spec: dict[str, Any] | SkillSpec) -> str:
    """Port storage/git.rs render_skill_markdown, including code-fence handling."""
    document = normalize_spec(spec)
    metadata = document["metadata"]
    out: str = "# " + str(metadata["name"]) + "\n\n"
    if metadata["description"]:
        out += metadata["description"] + "\n\n"
    for section in document["sections"]:
        out += "## " + section["title"] + "\n\n"
        for block in section["blocks"]:
            if block["block_type"] == "code":
                content = block["content"].rstrip()
                out += (
                    content + "\n\n"
                    if content.lstrip().startswith("```")
                    else ("```\n" + content + "\n```\n\n")
                )
            else:
                out += block["content"] + "\n\n"
    return out


def skill_from_spec(
    spec: dict[str, Any] | SkillSpec, *, contract: SkillContract | None = None, source: str = ""
) -> Skill:
    document = normalize_spec(spec)
    if contract is not None:
        document["grasp_contract"] = contract.model_dump(mode="json")
    elif "grasp_contract" in document:
        contract = SkillContract.model_validate(document["grasp_contract"])
    metadata = copy.deepcopy(document.get("grasp_metadata", {}))
    metadata.update(copy.deepcopy(document["metadata"]))
    identity = {key: metadata.pop(key) for key in ("id", "name", "description")}
    metadata["metaskills_spec"] = document
    metadata["metaskills_spec_hash"] = spec_content_hash(document)
    return Skill(
        **identity,
        metadata=metadata,
        source=document.get("grasp_source", source or f"metaskills://skills/{identity['id']}"),
        dependencies=[
            SkillDependency.model_validate(d) for d in document.get("grasp_dependencies", [])
        ],
        content=document.get("grasp_content", render_skill_markdown(document)),
        contract=contract or SkillContract(),
    )


def spec_from_skill(skill: Skill) -> dict[str, Any]:
    original = skill.metadata.get("metaskills_spec")
    if original is None:
        original = {"metadata": {}, "sections": []}
    document = copy.deepcopy(original)
    metadata = document.setdefault("metadata", {})
    metadata.update(
        id=skill.id,
        name=skill.name,
        description=skill.description,
    )
    for key in ("tags", "requires", "provides", "platforms", "author", "license", "context"):
        if key in skill.metadata:
            metadata[key] = copy.deepcopy(skill.metadata[key])
    if "grasp_contract" in document or skill.contract != SkillContract():
        document["grasp_contract"] = skill.contract.model_dump(mode="json")
    native_keys = {"tags", "requires", "provides", "platforms", "author", "license", "context"}
    provenance_keys = {
        "metaskills_spec",
        "metaskills_spec_hash",
        "metaskills_declared_version",
        "source_layer",
    }
    custom = {
        key: copy.deepcopy(value)
        for key, value in skill.metadata.items()
        if key not in native_keys | provenance_keys
    }
    if custom or "grasp_metadata" in document:
        document["grasp_metadata"] = custom
    if skill.dependencies or "grasp_dependencies" in document:
        document["grasp_dependencies"] = [d.model_dump(mode="json") for d in skill.dependencies]
    implicit_origin = (
        original is not None
        and "grasp_source" not in original
        and skill.source == f"metaskills://skills/{skill.id}"
    )
    if not implicit_origin and (skill.source or "grasp_source" in document):
        document["grasp_source"] = skill.source
    if skill.content != render_skill_markdown(document) or "grasp_content" in document:
        document["grasp_content"] = skill.content
    return normalize_spec(document)
