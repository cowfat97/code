"""Import editable skill documents without executing their resources."""

from __future__ import annotations

import base64
import copy
import json
import os
import stat
from pathlib import Path
from typing import Any

import yaml

from ..contracts import Skill, SkillContract, SkillDependency
from .configuration import SkillSource


def _frontmatter(content: str) -> dict[str, Any]:
    lines = content.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}
    end = next((i for i, line in enumerate(lines[1:], 1) if line.strip() in {"---", "..."}), None)
    if end is None:
        raise ValueError("unclosed YAML frontmatter")
    metadata = yaml.safe_load("\n".join(lines[1:end]))
    if metadata is None:
        return {}
    if not isinstance(metadata, dict) or not all(isinstance(key, str) for key in metadata):
        raise ValueError("skill frontmatter must be a string-keyed mapping")
    return metadata


def _contract(metadata: dict[str, Any]) -> SkillContract:
    value = metadata.get("grasp_contract", metadata.get("grasp"))
    if value is None:
        return SkillContract()
    if not isinstance(value, dict):
        raise ValueError("explicit skill contract must be a mapping")
    value = copy.deepcopy(value)
    for old, new in (("precondition", "preconditions"), ("effect", "effects")):
        if old in value:
            if new in value:
                raise ValueError(f"contract specifies both {old} and {new}")
            value[new] = value.pop(old)
    return SkillContract.model_validate(value)


def load_source(source: SkillSource, base_path: Path) -> list[Skill]:
    if not source.enabled:
        return []
    path = Path(source.path).expanduser()
    if not path.is_absolute():
        path = base_path / path
    path = path.absolute()
    path.stat()
    if path.is_file():
        if path.name != "SKILL.md":
            raise ValueError("explicit skill file must be named SKILL.md")
        files = [path]
        root = path.parent.resolve(strict=True)
    elif path.is_dir():
        root = path.resolve(strict=True)
        path = root
        files = sorted(path.rglob("SKILL.md") if source.recursive else path.glob("SKILL.md"))
        files = [file for file in files if file.is_file()]
    else:
        raise ValueError("skill source must be a file or directory")
    if source.id is not None and len(files) != 1:
        raise ValueError("source id override requires exactly one SKILL.md")
    imported = []
    for file in files:
        actual = file.resolve(strict=True)
        if not actual.is_relative_to(root):
            raise ValueError("skill document escapes the source directory")
        directory = file.parent.resolve()
        directory.relative_to(root)
        content = actual.read_text(encoding="utf-8")
        raw = _frontmatter(content)
        relative = directory.relative_to(root).as_posix()
        default_id = root.name if relative == "." else relative
        identity = source.id if source.id is not None else raw.get("id", default_id)
        name = source.name if source.name is not None else raw.get("name", identity)
        description = (
            source.description if source.description is not None else raw.get("description", "")
        )
        sidecar_path = directory / "contract.json"
        sidecar: dict[str, Any] = {}
        if sidecar_path.exists():
            if not sidecar_path.resolve().is_relative_to(directory):
                raise ValueError("contract file escapes the skill directory")
            sidecar = json.loads(sidecar_path.read_text(encoding="utf-8"))
            allowed = {"id", "name", "description", "contract", "tool", "metadata", "dependencies"}
            if not isinstance(sidecar, dict) or set(sidecar) - allowed:
                raise ValueError("invalid contract.json fields")
        identity = source.id or sidecar.get("id", identity)
        name = source.name or sidecar.get("name", name)
        description = source.description or sidecar.get("description", description)
        metadata = copy.deepcopy(raw)
        metadata.update(sidecar.get("metadata", {}))
        metadata.pop("version", None)
        metadata["raw_frontmatter"] = copy.deepcopy(raw)
        metadata["resource_directory"] = str(directory)
        metadata["resources"] = _snapshot_resources(directory)
        tool = source.tool or sidecar.get("tool", raw.get("tool"))
        if tool is not None:
            if not isinstance(tool, str) or not tool.strip():
                raise ValueError("tool binding must be a nonempty string")
            metadata["tool"] = tool
        dependencies = sidecar.get("dependencies", raw.get("dependencies", []))
        skill = Skill(
            id=identity,
            name=name,
            description=description,
            content=content,
            metadata=metadata,
            dependencies=[
                SkillDependency(id=d) if isinstance(d, str) else SkillDependency.model_validate(d)
                for d in dependencies
            ],
            source=directory.as_uri(),
            contract=source.contract
            if source.contract is not None
            else (
                SkillContract.model_validate(sidecar["contract"])
                if "contract" in sidecar
                else _contract(raw)
            ),
        )
        imported.append(skill)
    return imported


def _snapshot_resources(directory: Path) -> dict[str, str]:
    resources = {}
    excluded = {".git", "__pycache__", ".venv"}
    for current, dirs, files in os.walk(directory, followlinks=False):
        parent = Path(current)
        retained = []
        for name in sorted(dirs):
            child = parent / name
            if name in excluded:
                continue
            resolved = child.resolve(strict=True)
            if not resolved.is_relative_to(directory):
                raise ValueError("resource directory symlink escapes the skill directory")
            if child.is_symlink() or (child / "SKILL.md").is_file():
                continue
            retained.append(name)
        dirs[:] = retained
        for name in sorted(files):
            file = parent / name
            if file == directory / "SKILL.md":
                continue
            actual = file.resolve(strict=True)
            if not actual.is_relative_to(directory):
                raise ValueError("resource file symlink escapes the skill directory")
            if not stat.S_ISREG(actual.stat().st_mode):
                raise ValueError("skill resources must be regular files")
            resources[file.relative_to(directory).as_posix()] = base64.b64encode(
                actual.read_bytes()
            ).decode("ascii")
    return resources


def resource_bytes(skill: Skill, relative_path: str | Path) -> bytes:
    relative = Path(relative_path)
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError("resource path must remain inside the skill directory")
    key = relative.as_posix()
    if key == "SKILL.md":
        return skill.content.encode("utf-8")
    resources = skill.metadata.get("resources")
    if not isinstance(resources, dict) or key not in resources:
        raise ValueError("resource is not present in the skill snapshot")
    return base64.b64decode(resources[key], validate=True)
