"""Registry adapter around the MIT MetaSkills signal bandit.

Candidate aggregation is an application extension, not an upstream skill ranker.
Feedback replay makes explicitly attributed source posterior learning durable using
per-run file feedback records; no cloud calls or extra storage backend are required.
"""

from __future__ import annotations

import builtins
from typing import Any, Protocol

from ..contracts import SearchResult, Skill
from .metaskills_recommendation import (
    Reward,
    SignalBandit,
    SignalType,
    SkillFeedback,
    SuggestionContext,
    compute_reward,
)


class RecommendationRegistry(Protocol):
    def feedback(self) -> builtins.list[dict[str, Any]]: ...

    def get(self, skill_id: str) -> Skill: ...
    def list(self) -> builtins.list[Skill]: ...
    def dependencies(
        self, skill_id: str, *, recursive: bool = False
    ) -> builtins.list[Skill]: ...
    def dependents(self, skill_id: str) -> builtins.list[Skill]: ...
    def search(
        self, query: str, mode: str = "keyword", limit: int = 20, filters: Any = None
    ) -> builtins.list[SearchResult]: ...


def feedback_bandit(rows: builtins.list[dict[str, Any]]) -> SignalBandit:
    """Replay binary verified outcomes only for explicitly attributed signals.

    details.recommendation_signals lists source signal names. Optional
    details.recommendation_context supplies the context captured at suggestion time.
    Numeric task reward is exposed separately; no hidden threshold maps it to binary.
    """
    bandit = SignalBandit()
    for row in rows:
        details = row["details"]
        if not isinstance(details, dict):
            continue
        signals = details.get("recommendation_signals", [])
        if not isinstance(signals, list):
            continue
        raw_context = details.get("recommendation_context", {})
        context = (
            SuggestionContext(
                **{
                    key: value
                    for key, value in raw_context.items()
                    if key in ("tech_stack", "time_of_day", "project_size", "activity_pattern")
                    and isinstance(value, str)
                }
            )
            if isinstance(raw_context, dict)
            else SuggestionContext()
        )
        for value in dict.fromkeys(item for item in signals if isinstance(item, str)):
            try:
                signal = SignalType(value)
            except ValueError:
                continue
            bandit.update(signal, Reward.SUCCESS if row["success"] else Reward.FAILURE, context)
    return bandit


def task_feedback_reward(success: bool, duration_seconds: float = 0.0) -> float:
    return compute_reward(
        SkillFeedback("task_completed", success=success, duration_seconds=duration_seconds)
    )


def recommend_skills(
    registry: RecommendationRegistry, skill_id: str, limit: int = 10
) -> builtins.list[SearchResult]:
    """Extension policy: learned reciprocal lexical/semantic ranks plus dependencies.

    Reciprocal candidate ranks map unbounded in-memory BM25 and cosine onto a common
    scale. Only present candidate signals contribute. Dependency relations use the
    project_match signal. Estimated source weights keep this API deterministic.
    """
    if limit < 0:
        raise ValueError("limit must be nonnegative")
    current = registry.get(skill_id)
    count = len(registry.list())
    query = f"{current.name} {current.description} {current.content}"
    signals: dict[str, dict[SignalType, float]] = {}
    skills: dict[str, Skill] = {}
    for signal, mode in ((SignalType.BM25, "keyword"), (SignalType.EMBEDDING, "semantic")):
        try:
            rows = registry.search(query, mode=mode, limit=count)
        except ValueError as error:
            if mode == "semantic" and "EmbeddingProvider" in str(error):
                continue
            raise
        for rank, result in enumerate(rows, 1):
            if result.skill.id == skill_id:
                continue
            skills[result.skill.id] = result.skill
            signals.setdefault(result.skill.id, {})[signal] = 1.0 / rank
    for skill in registry.dependencies(skill_id) + registry.dependents(skill_id):
        skills[skill.id] = skill
        signals.setdefault(skill.id, {})[SignalType.PROJECT_MATCH] = 1.0
    weights = feedback_bandit(registry.feedback()).estimated_weights()
    results = [
        SearchResult(
            skill=skills[key],
            score=sum(weights.get(signal) * value for signal, value in values.items()),
        )
        for key, values in signals.items()
    ]
    return sorted(results, key=lambda result: (-result.score, result.skill.id))[:limit]
