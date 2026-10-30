"""Provider-injected business task proposals with pinned candidate evidence."""

from __future__ import annotations

import asyncio
import json
import re
import tomllib
from collections import Counter
from collections.abc import Mapping, Sequence
from copy import deepcopy
from pathlib import Path
from typing import Any, Protocol
from uuid import uuid4

from pydantic import ValidationError

from ..contracts import Skill
from .models import MetaConfig, MetaPlan, ModelResponse
from .prompt import build_prompt, digest, encode


class MetaValidationError(ValueError):
    """Caller data or model proposal is invalid."""


class MetaProviderError(RuntimeError):
    """Injected provider failed; no retry was performed."""


class MetaProviderUnavailable(MetaProviderError):
    """No model provider was injected."""


class MetaTimeoutError(MetaProviderError):
    """Model request exceeded the configured timeout."""


class LLMProvider(Protocol):
    async def complete(self, prompt: str) -> str: ...


def _object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _constant(value: str) -> Any:
    raise ValueError(f"nonfinite JSON constant: {value}")


def _strings(value: Any, name: str) -> list[str]:
    if not isinstance(value, list) or any(not isinstance(x, str) or not x.strip() for x in value):
        raise MetaValidationError(f"{name} must be a list of nonblank strings")
    return list(value)


class MetaPlanner:
    def __init__(
        self, provider: LLMProvider | None = None, config: MetaConfig = MetaConfig()
    ) -> None:
        self.config = config.model_copy(deep=True)
        if provider is None and self.config.llm is not None:
            from .http_provider import OpenAICompatibleProvider

            provider = OpenAICompatibleProvider(self.config.llm)
        self.provider = provider

    @classmethod
    def from_config(
        cls,
        config: str | Path | Mapping[str, Any] | MetaConfig,
        *,
        provider: LLMProvider | None = None,
    ) -> MetaPlanner:
        if isinstance(config, MetaConfig):
            return cls(provider, config)
        if isinstance(config, (str, Path)):
            path = Path(config)
            if path.suffix.lower() == ".toml":
                value = tomllib.loads(path.read_text(encoding="utf-8"))
            else:
                value = json.loads(
                    path.read_text(encoding="utf-8"),
                    object_pairs_hook=_object,
                    parse_constant=_constant,
                )
        else:
            value = dict(config)
        return cls(provider, MetaConfig.model_validate(value))

    async def propose(
        self, *, task: str, skills: list[Skill], goal: list[str]
    ) -> list[dict[str, Any]]:
        plan = await self.plan(task=task, skills=skills, goal=goal)
        return [step.model_dump() for step in plan.proposal]

    async def plan(
        self,
        *,
        task: str,
        skills: Sequence[Skill],
        goal: list[str] | None = None,
        initial_conditions: list[str] | None = None,
        context: Mapping[str, Any] | None = None,
    ) -> MetaPlan:
        if self.provider is None:
            raise MetaProviderUnavailable("configure llm in meta config before planning")
        if not isinstance(task, str) or not task.strip():
            raise MetaValidationError("task must be a nonempty string")
        explicit = _strings(goal, "goal") if goal is not None else None
        if explicit == []:
            raise MetaValidationError("goal must be nonempty")
        initial = (
            _strings(initial_conditions, "initial_conditions")
            if initial_conditions is not None
            else []
        )
        if len(skills) > self.config.max_candidates:
            raise MetaValidationError("candidate limit exceeded")
        try:
            snapshots = [Skill.model_validate(s.model_dump()).model_copy(deep=True) for s in skills]
            catalog = {s.id: s for s in snapshots}
            if len(catalog) != len(snapshots):
                raise MetaValidationError("duplicate skill candidate")
            hashes = {s.id: digest(encode(s.model_dump())) for s in snapshots}
            summaries = [
                {
                    "id": s.id,
                    "name": s.name,
                    "description": s.description[: self.config.max_content_chars],
                    "content": s.content[: self.config.max_content_chars],
                    "contract": s.contract.model_dump(),
                    "dependencies": [d.model_dump() for d in s.dependencies],
                }
                for s in snapshots
            ]
            prompt = build_prompt(
                {
                    "task": task,
                    "explicit_goal": explicit,
                    "initial_conditions": initial,
                    "context": deepcopy(dict(context or {})),
                    "candidates": summaries,
                    "max_steps": self.config.max_steps,
                }
            )
        except (ValueError, TypeError, AttributeError) as exc:
            raise MetaValidationError(str(exc)) from exc
        if len(prompt) > self.config.max_prompt_chars:
            raise MetaValidationError("prompt limit exceeded; narrow candidates or context")
        prompt_hash = digest(prompt)
        try:
            response = await asyncio.wait_for(self.provider.complete(prompt), self.config.timeout)
        except TimeoutError as exc:
            raise MetaTimeoutError("model request timed out") from exc
        except MetaProviderError:
            raise
        except Exception as exc:
            raise MetaProviderError("model provider failed") from exc
        try:
            if not isinstance(response, str):
                raise ValueError("provider response must be a string")
            decoded = json.loads(response, object_pairs_hook=_object, parse_constant=_constant)
            result = ModelResponse.model_validate(decoded)
            if explicit is not None and result.goal != explicit:
                raise ValueError("model changed explicit goal")
            if not result.goal:
                raise ValueError("model must provide a nonempty goal")
            _strings(result.goal, "goal")
            if len(result.proposal) > self.config.max_steps:
                raise ValueError("step limit exceeded")
            effects = set(initial)
            counts: Counter[str] = Counter()
            node_ids: set[str] = set()
            for step in result.proposal:
                if step.skill not in catalog:
                    raise ValueError(f"unknown skill: {step.skill}")
                selected = catalog[step.skill]
                if len(step.args) != len(selected.contract.params):
                    raise ValueError(f"argument arity mismatch: {step.skill}")
                mapping = dict(zip(selected.contract.params, step.args, strict=True))
                pattern = r"\b(?:" + "|".join(re.escape(p) for p in mapping) + r")\b"
                effects.update(
                    re.sub(pattern, lambda m: mapping[m[0]], effect) if mapping else effect
                    for effect in selected.contract.effects
                )
                counts[step.skill] += 1
                node_ids.add(f"{step.skill}:{counts[step.skill]}")
            if not set(result.goal) <= effects:
                raise ValueError("goal not supported by selected effects or initial facts")
            for hint in result.order_hints:
                if hint.source not in node_ids or hint.target not in node_ids:
                    raise ValueError("order hint references unknown node")
                if hint.source == hint.target:
                    raise ValueError("self order hint")
            return MetaPlan(
                **result.model_dump(),
                task=task,
                initial_conditions=initial,
                prompt_sha256=prompt_hash,
                response_sha256=digest(response),
                skill_hashes=hashes,
                plan_id=str(uuid4()),
            )
        except (ValueError, TypeError, ValidationError) as exc:
            raise MetaValidationError(str(exc)) from exc
