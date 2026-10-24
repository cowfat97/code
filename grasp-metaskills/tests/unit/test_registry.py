import subprocess

import pytest

from grasp_metaskills.contracts import Skill, SkillDependency
from grasp_metaskills.registry import SkillRegistry


def test_immutable_versions_and_persistence(tmp_path):
    path = tmp_path / "skills.db"
    with SkillRegistry(path) as r:
        first = r.register(Skill(id="a", name="A", content="one"))
        assert len(first.content_hash) == 64
        with pytest.raises(ValueError, match="immutable"):
            r.register(Skill(id="a", name="A", content="two"))
        r.register(Skill(id="a", name="A", version="2.0", content="two"))
        assert r.get("a").version == "2.0"
        r.delete("a")
        assert r.list() == []
        assert r.get("a", "1.0.0") == first
    with SkillRegistry(path) as r:
        assert len(r.history("a")) == 2


def test_search_dependencies_export():
    with SkillRegistry() as r:
        r.register(
            Skill(id="base", name="Base", description="parse documents", metadata={"tag": "text"})
        )
        r.register(
            Skill(
                id="child",
                name="Child",
                description="compose document",
                dependencies=[SkillDependency(id="base", version=">=1.0")],
            )
        )
        assert r.search("parse")[0].skill.id == "base"
        assert r.search("parse", filters={"tag": "image"}) == []
        assert r.dependencies("child")[0].id == "base"
        assert r.dependents("base")[0].id == "child"
        assert r.recommend("base")[0].skill.id == "child"
        with pytest.raises(ValueError, match="dependents"):
            r.delete("base")
        with SkillRegistry() as other:
            assert len(other.import_json(r.export_json())) == 2


def test_missing_dependency_and_embedding_error():
    with SkillRegistry(embedding_provider=None) as r:
        with pytest.raises(ValueError, match="dependency"):
            r.register(Skill(id="a", name="a", dependencies=[SkillDependency(id="missing")]))
        with pytest.raises(ValueError, match="EmbeddingProvider"):
            r.search("x", mode="semantic")
        assert r.list() == []


def test_runs_and_feedback():
    with SkillRegistry() as r:
        r.register(Skill(id="a", name="a"))
        r.record_feedback("a", "1.0.0", "n", True, {"ok": True})
        assert r.feedback("a")[0]["success"] is True
        r.save_run("g", {"id": "g", "version": 1}, {"done": ["n"]})
        r.save_run("g", {"id": "g", "version": 2}, {"done": ["n", "m"]})
        assert r.load_run("g") == ({"id": "g", "version": 2}, {"done": ["n", "m"]})
        assert len(r.run_history("g")) == 2
        assert r.load_run("missing") is None


def test_semantic_and_hybrid():
    class Embeddings:
        def embed(self, texts):
            return [[1.0, 0.0] if "parse" in t else [0.0, 1.0] for t in texts]

    with SkillRegistry(embedding_provider=Embeddings()) as r:
        r.register(Skill(id="a", name="parse"))
        r.register(Skill(id="b", name="write"))
        assert r.search("parse", mode="semantic")[0].skill.id == "a"
        assert r.search("parse", mode="hybrid")[0].skill.id == "a"
        assert r.search("parse", mode="semantic", filters={"id": "b"})[0].skill.id == "b"


def test_import_is_atomic_and_dependency_versions():
    with SkillRegistry() as r:
        r.register(Skill(id="base", name="Base", version="1.0"))
        r.register(Skill(id="base", name="Base", version="2.0"))
        r.register(
            Skill(id="child", name="Child", dependencies=[SkillDependency(id="base", version="<2")])
        )
        assert r.dependencies("child")[0].version == "1.0"
        assert r.get("base", ">=2").version == "2.0"
        before = r.export_json()
        with pytest.raises(ValueError, match="dependency"):
            r.import_json(
                '[{"id":"good","name":"Good"},{"id":"bad","name":"Bad","dependencies":[{"id":"missing"}]}]'
            )
        assert r.export_json() == before


def test_content_hash_tamper_rejected():
    with SkillRegistry() as r:
        with pytest.raises(ValueError, match="hash"):
            r.register(Skill(id="a", name="A", content_hash="wrong"))


def test_git_snapshot_and_history(tmp_path):
    with SkillRegistry(git_path=tmp_path / "history") as r:
        r.register(Skill(id="a", name="A"))
        first = r.commit_git("First snapshot")
        assert len(first) == 40
        assert r.commit_git() == first
        r.register(Skill(id="a", name="A", version="2.0"))
        second = r.commit_git("Second snapshot")
        assert second != first
        assert r.git_history() == [second, first]
        result = subprocess.run(
            ["git", "-C", str(tmp_path / "history"), "show", f"{first}:skills.json"],
            check=True,
            capture_output=True,
            text=True,
        )
        assert "1.0.0" in result.stdout
        assert "2.0" not in result.stdout
