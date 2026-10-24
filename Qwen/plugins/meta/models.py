"""Strict proposal contracts; graph compilation remains a separate responsibility."""

from __future__ import annotations

import re
from copy import deepcopy
from typing import Any
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class LLMConfig(StrictModel):
    base_url: str
    model: str
    api_key_env: str | None = None
    timeout: float = Field(default=30, gt=0, allow_inf_nan=False)

    @field_validator("base_url")
    @classmethod
    def validate_base_url(cls, value: str) -> str:
        try:
            parsed = urlsplit(value)
            port = parsed.port
        except ValueError:
            raise ValueError("base_url must be an HTTP(S) API root") from None
        if (
            value != value.strip()
            or any(c.isspace() or ord(c) < 32 for c in value)
            or parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or "?" in value
            or "#" in value
            or port == 0
            or "\\" in value
        ):
            raise ValueError(
                "base_url must be an HTTP(S) API root without credentials, query or fragment"
            )
        return value

    @field_validator("model")
    @classmethod
    def validate_model(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("model must be nonblank")
        return value

    @field_validator("api_key_env")
    @classmethod
    def validate_api_key_env(cls, value: str | None) -> str | None:
        if value is not None and re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", value) is None:
            raise ValueError("api_key_env must name an environment variable")
        return value


class MetaConfig(StrictModel):
    llm: LLMConfig | None = None
    timeout: float = Field(default=30, gt=0, allow_inf_nan=False)
    max_candidates: int = Field(default=100, gt=0)
    max_steps: int = Field(default=64, gt=0)
    max_content_chars: int = Field(default=2000, ge=0)
    max_prompt_chars: int = Field(default=100000, gt=0)


class PlanStep(StrictModel):
    skill: str = Field(min_length=1)
    args: list[str]


class OrderHint(StrictModel):
    source: str = Field(min_length=1)
    target: str = Field(min_length=1)
    label: str = "order"


class ModelResponse(StrictModel):
    goal: list[str]
    proposal: list[PlanStep]
    order_hints: list[OrderHint] = Field(default_factory=list)
    rationale: str = ""


class MetaPlan(ModelResponse):
    task: str
    initial_conditions: list[str]
    prompt_sha256: str
    response_sha256: str
    skill_hashes: dict[str, str]
    plan_id: str

    def to_plugin_request(
        self, *, inputs: dict[str, dict[str, Any]] | None = None
    ) -> dict[str, Any]:
        result = self.model_dump(
            include={"task", "goal", "initial_conditions", "proposal", "order_hints"}
        )
        if inputs is not None:
            result["inputs"] = deepcopy(inputs)
        return result
