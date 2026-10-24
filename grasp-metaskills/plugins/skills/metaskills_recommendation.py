"""MIT MetaSkills bandit port from dcd3fb55cabb438dc200f9b7c784ca14c08135ce.

Ports suggestions/bandit/{types,bandit,rewards,context}.rs core formulas.
Python Random is injectable; random streams differ from Rust rand_distr.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum

from .metaskills_search import f32

UPSTREAM_COMMIT = "dcd3fb55cabb438dc200f9b7c784ca14c08135ce"


class SignalType(str, Enum):
    BM25 = "bm25"
    EMBEDDING = "embedding"
    TRIGGER = "trigger"
    FRESHNESS = "freshness"
    PROJECT_MATCH = "project_match"
    FILE_TYPE_MATCH = "file_type_match"
    COMMAND_PATTERN = "command_pattern"
    USER_HISTORY = "user_history"


class Reward(str, Enum):
    SUCCESS = "success"
    FAILURE = "failure"


@dataclass(frozen=True)
class SkillFeedback:
    kind: str
    minutes: int = 0
    reason: str | None = None
    stars: int = 1
    success: bool = False
    duration_seconds: float = 0.0


def compute_reward(feedback: SkillFeedback) -> float:
    k = feedback.kind
    constants = {
        "explicit_helpful": 1.0,
        "loaded_only": 0.3,
        "ignored": 0.1,
        "explicit_not_helpful": 0.0,
        "unloaded_quickly": 0.0,
    }
    if k in constants:
        return f32(constants[k])
    if k == "used_duration":
        if not 0 <= feedback.minutes <= 0xFFFFFFFF:
            raise ValueError("minutes must fit u32")
        return (
            f32(0.8)
            if feedback.minutes > 5
            else f32(f32(0.4) + f32(min(f32(f32(feedback.minutes) / 5.0), 1.0) * f32(0.4)))
        )
    if k == "rating":
        if not 0 <= feedback.stars <= 255:
            raise ValueError("stars must fit u8")
        # Upstream does not clamp to 1..5; preserve that edge behavior.
        return f32(f32(f32(feedback.stars) - 1.0) / 4.0)
    if k == "task_completed":
        if feedback.duration_seconds < 0:
            raise ValueError("duration must be nonnegative")
        if not feedback.success:
            return f32(0.2)
        bonus = f32(f32(1.0 - min(f32(f32(feedback.duration_seconds) / 600.0), 1.0)) * f32(0.2))
        return f32(f32(0.7) + bonus)
    raise ValueError(f"unknown feedback kind: {k}")


def compute_contextual_reward(
    feedback: SkillFeedback, context_match: float, was_top_suggestion: bool
) -> float:
    base = compute_reward(feedback)
    match = f32(context_match)
    context_factor = f32(1.1 if match > f32(0.7) else 0.9 if match < f32(0.3) else 1.0)
    position_factor = f32(1.1 if was_top_suggestion and base > 0.5 else 1.0)
    return min(f32(f32(base * context_factor) * position_factor), 1.0)


def feedback_weight(feedback: SkillFeedback) -> float:
    return f32(
        {
            "explicit_helpful": 2,
            "explicit_not_helpful": 2,
            "rating": 1.5,
            "task_completed": 1.5,
            "used_duration": 1,
            "loaded_only": 0.8,
            "unloaded_quickly": 0.8,
            "ignored": 0.5,
        }[feedback.kind]
    )


def aggregate_rewards(feedbacks: list[SkillFeedback]) -> float:
    total, weight = 0.0, 0.0
    for feedback in feedbacks:
        w = feedback_weight(feedback)
        total = f32(total + f32(compute_reward(feedback) * w))
        weight = f32(weight + w)
    return f32(total / weight) if weight > 0 else 0.5


def legacy_reward_to_f32(reward: Reward) -> float:
    return 1.0 if reward == Reward.SUCCESS else 0.0


@dataclass
class BetaDistribution:
    alpha: float = 1.0
    beta: float = 1.0

    def sample(self, rng: random.Random) -> float:
        alpha = self.alpha if math.isfinite(self.alpha) and self.alpha > 0 else 1.0
        beta = self.beta if math.isfinite(self.beta) and self.beta > 0 else 1.0
        return rng.betavariate(alpha, beta)


@dataclass
class BanditArm:
    signal_type: SignalType
    decay_factor: float = 0.99
    successes: float = 0.0
    failures: float = 0.0
    estimated_prob: float = 0.5
    ucb: float = 0.0
    last_selected: datetime | None = None

    def observe(self, reward: Reward, prior: BetaDistribution) -> None:
        decay = min(1.0, max(0.0, self.decay_factor))
        self.successes *= decay
        self.failures *= decay
        if reward == Reward.SUCCESS:
            self.successes += 1
        else:
            self.failures += 1
        total = self.observations()
        if total > 0:
            self.estimated_prob = (prior.alpha + self.successes) / (
                prior.alpha + prior.beta + total
            )

    def observations(self) -> float:
        return self.successes + self.failures


@dataclass
class SignalWeights:
    weights: dict[SignalType, float] = field(default_factory=dict)

    def get(self, signal: SignalType) -> float:
        return self.weights.get(signal, 0.0)

    def normalize(self) -> None:
        total = sum(self.weights.values())
        if total <= 0:
            self.weights.update({signal: 1 / len(SignalType) for signal in SignalType})
        else:
            self.weights = {signal: value / total for signal, value in self.weights.items()}


@dataclass
class SuggestionContext:
    tech_stack: str | None = None
    time_of_day: str | None = None
    project_size: str | None = None
    activity_pattern: str | None = None

    def keys(self) -> list[tuple[str, str]]:
        return [
            (key, value)
            for key in ("tech_stack", "time_of_day", "project_size", "activity_pattern")
            if (value := getattr(self, key)) is not None
        ]


@dataclass
class ContextModifier:
    probability_bonus: dict[SignalType, float] = field(default_factory=dict)
    weight_multiplier: dict[SignalType, float] = field(default_factory=dict)
    observation_count: int = 0

    def apply(self, signal: SignalType, base: float) -> float:
        return max(
            0.0,
            base * self.weight_multiplier.get(signal, 1.0)
            + self.probability_bonus.get(signal, 0.0),
        )

    def update(self, signal: SignalType, reward: Reward) -> None:
        value = self.probability_bonus.get(signal, 0.0) + (
            0.05 if reward == Reward.SUCCESS else -0.05
        )
        self.probability_bonus[signal] = max(-0.5, min(0.5, value))


@dataclass
class BanditConfig:
    exploration_factor: float = 0.1
    observation_decay: float = 0.99
    min_observations: int = 10
    use_context: bool = True
    persist_frequency: int = 10


class SignalBandit:
    def __init__(self, config: BanditConfig | None = None, rng: random.Random | None = None):
        self.config = config or BanditConfig()
        self.rng = rng if rng is not None else random.Random()
        self.arms = {
            signal: BanditArm(signal, self.config.observation_decay) for signal in SignalType
        }
        self.prior = BetaDistribution()
        self.context_modifiers: dict[tuple[str, str], ContextModifier] = {}
        self.total_selections = 0

    def _weights(self, context: SuggestionContext, sampled: bool) -> SignalWeights:
        values = {}
        for signal in SignalType:
            arm = self.arms.get(signal)
            if sampled:
                distribution = (
                    BetaDistribution(
                        self.prior.alpha + arm.successes, self.prior.beta + arm.failures
                    )
                    if arm
                    else self.prior
                )
                value = max(0.0, distribution.sample(self.rng))
            else:
                value = arm.estimated_prob if arm else 0.5
            if self.config.use_context:
                for key in context.keys():
                    if key in self.context_modifiers:
                        value = self.context_modifiers[key].apply(signal, value)
            values[signal] = max(0.0, value)
        result = SignalWeights(values)
        result.normalize()
        return result

    def select_weights(self, context: SuggestionContext | None = None) -> SignalWeights:
        result = self._weights(context or SuggestionContext(), True)
        self.total_selections += 1
        return result

    def estimated_weights(self, context: SuggestionContext | None = None) -> SignalWeights:
        return self._weights(context or SuggestionContext(), False)

    def update(
        self, signal: SignalType, reward: Reward, context: SuggestionContext | None = None
    ) -> None:
        arm = self.arms.get(signal)
        if arm is None:
            return
        arm.observe(reward, self.prior)
        arm.last_selected = datetime.now(timezone.utc)
        bonus = (
            math.sqrt(math.log(max(self.total_selections, 1)) / max(arm.observations(), 1.0))
            * self.config.exploration_factor
        )
        arm.ucb = max(0.0, min(1.0, arm.estimated_prob + bonus))
        if self.config.use_context:
            for key in (context or SuggestionContext()).keys():
                modifier = self.context_modifiers.setdefault(key, ContextModifier())
                modifier.observation_count += 1
                modifier.update(signal, reward)
