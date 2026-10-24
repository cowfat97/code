import math
import random

import pytest

from grasp_metaskills.metaskills_recommendation import (
    BetaDistribution,
    Reward,
    SignalBandit,
    SignalType,
    SignalWeights,
    SkillFeedback,
    SuggestionContext,
    aggregate_rewards,
    compute_contextual_reward,
    compute_reward,
    f32,
)


def test_source_reward_variants_and_unclamped_rating():
    expected = {
        "explicit_helpful": 1,
        "explicit_not_helpful": 0,
        "ignored": 0.1,
        "loaded_only": 0.3,
        "unloaded_quickly": 0,
    }
    for kind, value in expected.items():
        assert compute_reward(SkillFeedback(kind)) == f32(value)
    assert [compute_reward(SkillFeedback("rating", stars=s)) for s in (1, 3, 5)] == [0, 0.5, 1]
    assert compute_reward(SkillFeedback("rating", stars=0)) == -0.25
    assert compute_reward(SkillFeedback("rating", stars=9)) == 2
    assert compute_reward(SkillFeedback("used_duration", minutes=0)) == f32(0.4)
    assert compute_reward(SkillFeedback("used_duration", minutes=10)) == f32(0.8)
    assert compute_reward(SkillFeedback("task_completed", success=False)) == f32(0.2)
    assert compute_contextual_reward(SkillFeedback("explicit_helpful"), 0.9, True) == 1
    assert aggregate_rewards([]) == 0.5


def test_thompson_weights_normalized_reproducible_and_learning():
    a = SignalBandit(rng=random.Random(24))
    b = SignalBandit(rng=random.Random(24))
    assert a.select_weights().weights == b.select_weights().weights
    assert a.total_selections == 1
    assert sum(a.estimated_weights().weights.values()) == 1
    for _ in range(50):
        a.update(SignalType.BM25, Reward.SUCCESS)
    assert a.arms[SignalType.BM25].estimated_prob > 0.5
    assert a.estimated_weights().get(SignalType.BM25) > a.estimated_weights().get(
        SignalType.EMBEDDING
    )
    for _ in range(20):
        weights = a.select_weights()
        assert sum(weights.weights.values()) == pytest.approx(1)
        assert all(0 <= v <= 1 for v in weights.weights.values())


def test_beta_invalid_parameters_and_distribution_mean():
    rng = random.Random(2)
    values = [BetaDistribution(8, 2).sample(rng) for _ in range(10000)]
    assert sum(values) / len(values) == pytest.approx(0.8, abs=0.01)
    for params in ((0, -1), (math.nan, math.inf)):
        assert 0 <= BetaDistribution(*params).sample(rng) <= 1


def test_context_updates_clamp_and_multiplier_order():
    bandit = SignalBandit()
    context = SuggestionContext(tech_stack="rust", time_of_day="morning")
    for _ in range(20):
        bandit.update(SignalType.EMBEDDING, Reward.SUCCESS, context)
    modifier = bandit.context_modifiers[("tech_stack", "rust")]
    assert modifier.observation_count == 20
    assert modifier.probability_bonus[SignalType.EMBEDDING] == 0.5
    modifier.weight_multiplier[SignalType.EMBEDDING] = 2
    assert modifier.apply(SignalType.EMBEDDING, 0.25) == 1
    assert bandit.estimated_weights(context).get(
        SignalType.EMBEDDING
    ) > bandit.estimated_weights().get(SignalType.EMBEDDING)
    for _ in range(40):
        modifier.update(SignalType.EMBEDDING, Reward.FAILURE)
    assert modifier.probability_bonus[SignalType.EMBEDDING] == -0.5
    empty = SignalWeights()
    empty.normalize()
    assert set(empty.weights) == set(SignalType)
    assert all(v == 0.125 for v in empty.weights.values())
