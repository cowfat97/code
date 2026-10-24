"""Both source mechanisms operate through one public registry and runtime."""

import pytest

from grasp_metaskills import (
    GraphCompiler,
    GraphRuntime,
    NodeResult,
    RepairEngine,
    SkillContract,
    SkillRegistry,
)
from grasp_metaskills.metaskills_recommendation import SignalType
from grasp_metaskills.registry_recommendation import feedback_bandit


def native(sid, *, requires=(), provides=(), text=""):
    return {
        "metadata": {
            "id": sid,
            "name": sid,
            "version": "1.0.0",
            "description": "native processing " + sid,
            "requires": list(requires),
            "provides": list(provides),
        },
        "sections": [
            {
                "id": "body",
                "title": "Body",
                "blocks": [{"id": "text", "block_type": "text", "content": text}],
            }
        ],
    }


async def test_native_registration_discovery_execution_repair_feedback_and_version_pin(tmp_path):
    with SkillRegistry(tmp_path / "state.db", git_path=tmp_path / "archive") as registry:
        registry.register_spec(native("provider", provides=["tool"]))
        original = registry.register_spec(
            native("primary", requires=["tool"]), contract=SkillContract(effects=["done(x)"])
        )
        registry.register_spec(
            native("alternative", requires=["tool"]), contract=SkillContract(effects=["done(x)"])
        )
        graph = await GraphCompiler(registry).compile(
            task="native primary", goal=["done(x)"], proposal=[{"skill": "primary", "args": []}]
        )
        changed = native("primary", requires=["tool"], text="new body")
        updated = registry.register_spec(changed, contract=SkillContract(effects=["done(x)"]))
        assert updated.version != original.version
        assert graph.node("primary:1").skill.version == original.version
        assert graph.node("primary:1").skill.source == "metaskills://skills/primary"
        assert registry.git_archive.read_skill("primary")["sections"] == changed["sections"]
        calls = []

        class Executor:
            async def execute(self, node, inputs, context):
                calls.append(node.skill.id)
                if node.skill.id == "primary":
                    raise ValueError("actual selected executor failure")
                return NodeResult(observed_effects=node.effects)

        result = await GraphRuntime(
            registry, Executor(), repair_engine=RepairEngine(registry)
        ).execute(graph)
        assert result.status == "succeeded"
        assert calls == ["provider", "primary", "alternative"]
        assert result.repair_audit[-1]["operator"] == "Substitute"
        assert "provider:1" not in result.repair_audit[-1]["affected"]
        assert registry.feedback("primary", original.version)[0]["success"] is False
        assert registry.load_run(graph.id)[0]["version"] == 2
        assert registry.capability_dependencies("primary").is_ok()
        await GraphRuntime(registry, Executor()).resume(graph.id)
        assert calls == ["provider", "primary", "alternative"]


async def test_search_attribution_is_persisted_into_source_bandit(tmp_path):
    path = tmp_path / "state.db"
    with SkillRegistry(path) as registry:
        skill = registry.register_spec(
            native("processing"), contract=SkillContract(effects=["ready(x)"])
        )
        graph = await GraphCompiler(registry).compile(task="processing", goal=["ready(x)"])

        class Executor:
            async def execute(self, node, inputs, context):
                return NodeResult(observed_effects=node.effects)

        assert (await GraphRuntime(registry, Executor()).execute(graph)).status == "succeeded"
        rows = registry.feedback(skill.id)
        assert rows[0]["details"]["recommendation_signals"] == ["bm25"]
        before = feedback_bandit(registry.db).arms[SignalType.BM25].successes
    with SkillRegistry(path) as reopened:
        assert feedback_bandit(reopened.db).arms[SignalType.BM25].successes == before
        assert before > 0


def test_composition_queries_live_metadata_and_preserves_parent():
    with SkillRegistry() as registry:
        parent = native("parent", text="parent rule")
        parent["sections"][0]["blocks"][0]["block_type"] = "rule"
        registry.register_spec(parent)
        child = native("child", text="child rule")
        child["extends"] = "parent"
        child["sections"][0]["blocks"][0]["block_type"] = "rule"
        registry.register_spec(child)
        composed = registry.compose_spec("child")
        assert composed.inheritance_chain == ["parent", "child"]
        blocks = composed.spec["sections"][0]["blocks"]
        assert [b["content"] for b in blocks] == ["parent rule", "child rule"]
        assert registry.get_spec("parent")["sections"] == parent["sections"]
        assert registry.get_spec("child")["extends"] == "parent"


def test_capability_provider_delete_checks_same_dependency_truth():
    with SkillRegistry() as registry:
        registry.register_spec(native("provider", provides=["tool"]))
        registry.register_spec(native("consumer", requires=["tool"]))
        with pytest.raises(ValueError, match="dependents"):
            registry.delete("provider")
        assert registry.get("provider")


def test_native_revision_resolve_uses_active_not_hash_order():
    with SkillRegistry() as registry:
        for name in ("First", "Second", "Third"):
            spec = native("provider")
            spec["metadata"]["name"] = name
            latest = registry.register_spec(spec)
        assert registry.resolve("provider").version == latest.version
        assert registry.resolve("provider").name == "Third"
        assert len(registry.history("provider")) == 3


def test_json_import_with_git_uses_same_archive_and_supports_delete(tmp_path):
    from grasp_metaskills import Skill, SkillDependency

    with SkillRegistry() as source:
        source.register(Skill(id="base", name="Base"))
        source.register(
            Skill(id="consumer", name="Consumer", dependencies=[SkillDependency(id="base")])
        )
        exported = source.export_json()
    with SkillRegistry(tmp_path / "state.db", git_path=tmp_path / "archive") as destination:
        imported = destination.import_json(exported)
        assert {s.id for s in imported} == {"base", "consumer"}
        for skill in imported:
            assert destination.git_archive.read_skill(skill.id) == destination.get_spec(skill.id)
            assert destination.git_archive.history(skill.id)
        destination.delete("consumer")
        destination.delete("base")
        assert destination.list() == []
        assert destination.history("consumer")
