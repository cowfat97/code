"""MetaSkills dcd3fb55cabb438dc200f9b7c784ca14c08135ce golden formulas.
rewards.rs::test_{duration_reward_scaling,task_completion_reward,aggregate_rewards};
types.rs::BanditArm::observe; bandit.rs::update_increases_estimated_prob.
Rust reward values captured by isolated rustc harness using original source.
"""

from grasp_metaskills.metaskills_recommendation import (
    BanditArm,
    BetaDistribution,
    Reward,
    SignalType,
    SkillFeedback,
    aggregate_rewards,
    compute_contextual_reward,
    compute_reward,
    f32,
)


def test_rust_reward_formula_golden():
    used = SkillFeedback("used_duration", minutes=3)
    assert compute_reward(used) == f32(0.64)
    assert compute_contextual_reward(used, 0.9, True) == f32(0.7744)
    assert aggregate_rewards([SkillFeedback("explicit_helpful"), used]) == f32(0.87999994)
    assert [
        compute_reward(SkillFeedback("task_completed", success=True, duration_seconds=s))
        for s in (0, 60, 600)
    ] == [f32(0.9), f32(0.88), f32(0.7)]


def test_beta_posterior_decay_golden():
    arm = BanditArm(SignalType.BM25, decay_factor=0.5)
    prior = BetaDistribution()
    arm.observe(Reward.SUCCESS, prior)
    assert (arm.successes, arm.failures, arm.estimated_prob) == (1, 0, 2 / 3)
    arm.observe(Reward.FAILURE, prior)
    assert (arm.successes, arm.failures, arm.estimated_prob) == (0.5, 1, 1.5 / 3.5)
