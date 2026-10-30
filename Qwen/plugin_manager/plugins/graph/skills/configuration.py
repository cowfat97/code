"""Explicit local skill sources configured through JSON or TOML."""

from __future__ import annotations

import json
import tomllib
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Self

from pydantic import BaseModel, ConfigDict, Field

from ..contracts import SkillContract


class SkillSource(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    path: str = Field(min_length=1)
    enabled: bool = True
    recursive: bool = True
    id: str | None = Field(default=None, min_length=1)
    name: str | None = None
    description: str | None = None
    contract: SkillContract | None = None
    tool: str | None = None


class SkillsConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    skills: list[SkillSource] = Field(default_factory=list)

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> Self:
        return cls.model_validate(value)

    @classmethod
    def load(cls, path: str | Path) -> Self:
        path = Path(path)
        with path.open("rb") as stream:
            value = tomllib.load(stream) if path.suffix.lower() == ".toml" else json.load(stream)
        return cls.from_mapping(value)
