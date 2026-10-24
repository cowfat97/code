"""Real registry/compiler integration, source search and persisted feedback replay."""

import pytest

from grasp_metaskills.compiler import GraphCompiler
from grasp_metaskills.contracts import Skill, SkillContract
from grasp_metaskills.metaskills_recommendation import SignalType
from grasp_metaskills.metaskills_search import SearchFilters, fuse_results
from grasp_metaskills.registry import SkillRegistry
from grasp_metaskills.registry_recommendation import feedback_bandit, task_feedback_reward


def seed(registry):
    registry.register(
        Skill(
            id="git",
            name="git commit workflow",
            description="git commit workflow",
            metadata={"tags": ["Rust"], "source_layer": "global", "quality_score": 0.8},
            contract=SkillContract(effects=["done(x)"]),
        )
    )
    registry.register(
        Skill(
            id="other",
            name="quantum photon entanglement",
            metadata={"tags": ["physics"], "source_layer": "project", "quality_score": 0.9},
        )
    )
    registry.register(Skill(id="old", name="git commit workflow", metadata={"deprecated": True}))


def test_default_hash_semantic_hybrid_post_fusion_filters_and_roundtrip(tmp_path):
    path = tmp_path / "registry.sqlite"
    with SkillRegistry(path) as registry:
        seed(registry)
        assert registry.search("git commit workflow", mode="semantic")[0].skill.id == "git"
        lexical = registry.search("git", filters={"include_deprecated": True})
        semantic = registry.search("git", mode="semantic", filters={"include_deprecated": True})
        expected = fuse_results(
            [(r.skill.id, r.score) for r in lexical], [(r.skill.id, r.score) for r in semantic]
        )
        hybrid = registry.search("git", mode="hybrid", filters={"include_deprecated": True})
        assert [(r.skill.id, r.score) for r in hybrid] == [(r.skill_id, r.score) for r in expected]
        filters = SearchFilters(tags=["rust", "cli"], layer="org", min_quality=0.7)
        result = registry.search("git", mode="hybrid", filters=filters, limit=1)
        assert [r.skill.id for r in result] == ["git"]
        assert registry.last_search_signals == {"git": ["bm25", "embedding"]}
        assert registry.search("git", filters={"tags": ["physics"], "id": "git"}) == []
        exported = registry.export_json()
    with SkillRegistry(path) as reopened, SkillRegistry() as imported:
        imported.import_json(exported)
        assert reopened.search("git", mode="hybrid") == imported.search("git", mode="hybrid")


@pytest.mark.asyncio
async def test_real_registry_discovery_to_compiler():
    with SkillRegistry() as registry:
        seed(registry)
        graph = await GraphCompiler(registry).compile(task="git commit", goal=["done(x)"])
        assert "git" in graph.metadata["registry_discovery"]
        assert [n.skill.id for n in graph.nodes if n.skill] == ["git"]
        assert graph.validate_graph() == []


def test_attributed_feedback_learning_replays_after_reopen(tmp_path):
    path = tmp_path / "feedback.sqlite"
    with SkillRegistry(path) as registry:
        seed(registry)
        registry.record_feedback(
            "git",
            "1.0.0",
            "git:1",
            True,
            {
                "recommendation_signals": ["embedding"],
                "recommendation_context": {"tech_stack": "rust"},
            },
        )
        registry.record_feedback("other", "1.0.0", "other:1", False, {})
        before = feedback_bandit(registry.db)
        assert before.arms[SignalType.EMBEDDING].estimated_prob == 2 / 3
        assert before.arms[SignalType.BM25].observations() == 0
        assert task_feedback_reward(True, 60) > task_feedback_reward(False, 60)
    with SkillRegistry(path) as registry:
        after = feedback_bandit(registry.db)
        assert after.estimated_weights().weights == before.estimated_weights().weights
        assert after.context_modifiers[("tech_stack", "rust")].observation_count == 1
        assert registry.recommend("git")


@pytest.mark.asyncio
async def test_hybrid_source_discovery_directly_compiles_with_both_signal_attributions():
    with SkillRegistry() as registry:
        seed(registry)
        graph = await GraphCompiler(registry, discovery_mode="hybrid").compile(
            task="git commit", goal=["done(x)"]
        )
        assert graph.metadata["discovery_mode"] == "hybrid"
        assert graph.metadata["recommendation_signals_by_skill"]["git"] == ["bm25", "embedding"]
        assert graph.node("git:1").skill.id == "git"
        assert graph.validate_graph() == []
