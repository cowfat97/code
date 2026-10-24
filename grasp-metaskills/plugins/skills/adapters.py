"""Explicit GraSP metadata adapters; no natural language to contract inference.

The small frontmatter parser follows index.js parseFrontmatter/parseInlineArray
rather than silently treating descriptions as executable contracts (MIT port).
"""

from __future__ import annotations

import re
from typing import Any

from ..contracts import Skill, SkillContract


def parse_inline_array(inner: str) -> list[str]:
    result: list[str] = []
    buffer = ""
    depth = 0
    quote: str | None = None
    for char in inner.strip():
        if quote:
            if char == quote:
                quote = None
            else:
                buffer += char
            continue
        if char in {"'", '"'}:
            quote = char
        elif char in "([":
            depth += 1
            buffer += char
        elif char in ")]":
            depth -= 1
            buffer += char
        elif char == "," and depth == 0:
            result.append(buffer.strip())
            buffer = ""
        else:
            buffer += char
    if buffer.strip():
        result.append(buffer.strip())
    return [s for s in result if s]


def parse_frontmatter(text: str) -> dict[str, Any] | None:
    match = re.match(r"^---\s*\n([\s\S]*?)\n---", text)
    if not match:
        return None
    root: dict[str, Any] = {}
    current = root
    for line in match[1].splitlines():
        if not line.strip() or re.match(r"^\s*#", line):
            continue
        field = re.match(r"^\s*([a-zA-Z_][\w-]*)\s*:\s*(.*)$", line)
        if not field:
            continue
        key, raw = field[1], field[2].strip()
        target = current if re.match(r"^\s{2,}\S", line) else root
        if not raw:
            root.setdefault(key, {})
            current = root[key]
        elif raw.startswith("[") and raw.endswith("]"):
            target[key] = parse_inline_array(raw[1:-1])
        elif raw in {"true", "false"}:
            target[key] = raw == "true"
        elif re.fullmatch(r"-?\d+(\.\d+)?", raw):
            target[key] = float(raw) if "." in raw else int(raw)
        else:
            target[key] = re.sub(r"""^["']|["']$""", "", raw)
    return root


def manifest_skills(manifest: dict[str, Any]) -> list[Skill]:
    skills = []
    for definition in manifest.get("skills", []):
        skills.append(
            Skill(
                id=definition["id"],
                name=definition.get("name", definition["id"]),
                description=definition.get("description", ""),
                version=definition.get("version", "1.0.0"),
                source=definition.get("source", "grasp-manifest"),
                contract=SkillContract(
                    params=definition.get("params", []),
                    preconditions=definition.get("precondition", []),
                    effects=definition.get("effect", []),
                ),
                metadata={"upstream": definition},
            )
        )
    return skills


def frontmatter_skills(files: list[dict[str, str]]) -> tuple[list[Skill], list[dict[str, str]]]:
    skills: list[Skill] = []
    skipped = []
    for file in files:
        metadata = parse_frontmatter(file["content"]) or {}
        grasp = metadata.get("grasp") or metadata.get("GraSP")
        if not grasp or not (grasp.get("precondition") or grasp.get("effect")):
            skipped.append({"name": file["name"], "reason": "no grasp: block"})
            continue
        skill_id = re.sub(r"[^a-z0-9_]+", "_", file["name"].lower()).strip("_")
        skills.append(
            Skill(
                id=skill_id,
                name=metadata.get("name", file["name"]),
                content=file["content"],
                description=metadata.get("description", ""),
                source=file["name"],
                metadata={"upstream": metadata},
                contract=SkillContract(
                    params=grasp.get("params", []),
                    preconditions=grasp.get("precondition", []),
                    effects=grasp.get("effect", []),
                ),
            )
        )
    return skills, skipped
