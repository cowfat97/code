import copy
import json
from pathlib import Path

import pytest

from grasp_metaskills.metaskills_spec import normalize_spec
from grasp_metaskills.registry import SkillRegistry


@pytest.fixture
def sample():
    path = Path(__file__).parents[1] / "golden/fixtures/metaskills_storage.json"
    return json.loads(path.read_text())["git_sample"]["spec"]


def test_single_registry_spec_archive_roundtrip(tmp_path, sample):
    with SkillRegistry(tmp_path / "registry.db", git_path=tmp_path / "archive") as registry:
        skill = registry.register_spec(sample)
        assert skill.id == "sample-skill"
        assert registry.get_spec(skill.id) == normalize_spec(sample)
        assert json.loads(registry.export_spec(skill.id)) == normalize_spec(sample)
        assert registry.git_archive.read_skill(skill.id) == registry.get_spec(skill.id)
        assert registry.db.execute("SELECT count(*) FROM metaskills_pending").fetchone()[0] == 0
        assert registry.incomplete_txs() == []
        assert len(registry.list()) == 1


def test_repeat_declared_version_maps_to_hash_revision(tmp_path, sample):
    with SkillRegistry(tmp_path / "registry.db", git_path=tmp_path / "archive") as registry:
        first = registry.register_spec(sample)
        changed = copy.deepcopy(sample)
        changed["sections"][0]["blocks"][0]["content"] = "changed"
        second = registry.register_spec(changed)
        assert first.version == "1.0.0"
        assert second.version.startswith("1.0.0+ms.")
        assert registry.get_spec(first.id)["metadata"]["version"] == "1.0.0"
        assert registry.get_spec(first.id, first.version) == sample
        assert registry.register_spec(changed).version == second.version
        assert len(registry.history(first.id)) == 2


def test_arbitrary_source_version_retained(tmp_path, sample):
    sample["metadata"]["version"] = "release version arbitrary"
    with SkillRegistry(tmp_path / "registry.db", git_path=tmp_path / "archive") as registry:
        skill = registry.register_spec(sample)
        assert skill.version.startswith("0.1.0+ms.")
        assert registry.get_spec(skill.id)["metadata"]["version"] == "release version arbitrary"


def test_failed_git_update_keeps_confirmed_and_recovers(tmp_path, sample, monkeypatch):
    with SkillRegistry(tmp_path / "registry.db", git_path=tmp_path / "archive") as registry:
        first = registry.register_spec(sample)
        changed = copy.deepcopy(sample)
        changed["metadata"]["name"] = "pending only"
        monkeypatch.setattr(
            registry.git_archive,
            "write_skill",
            lambda spec: (_ for _ in ()).throw(RuntimeError("commit failed")),
        )
        with pytest.raises(RuntimeError):
            registry.register_spec(changed)
        assert registry.get(first.id) == first
        assert registry.get_spec(first.id) == sample
        assert registry.db.execute("SELECT count(*) FROM metaskills_pending").fetchone()[0] == 1
        assert registry.tx_manager.recover()["rolled_back"] == 1
        assert registry.get(first.id) == first
        assert registry.db.execute("SELECT count(*) FROM metaskills_pending").fetchone()[0] == 0


def test_reopen_completes_commit_before_phase_failure(tmp_path, sample, monkeypatch):
    path, archive = tmp_path / "registry.db", tmp_path / "archive"
    registry = SkillRegistry(path, git_path=archive)
    original = registry.set_tx_phase

    def fail_committed(tx_id, phase, record):
        if phase == "committed":
            raise RuntimeError("crash after git commit")
        original(tx_id, phase, record)

    monkeypatch.setattr(registry, "set_tx_phase", fail_committed)
    with pytest.raises(RuntimeError):
        registry.register_spec(sample)
    with pytest.raises(KeyError):
        registry.get("sample-skill")
    registry.close()
    with SkillRegistry(path, git_path=archive) as reopened:
        assert reopened.get_spec("sample-skill") == sample
        assert reopened.incomplete_txs() == []
        assert reopened.db.execute("SELECT count(*) FROM metaskills_pending").fetchone()[0] == 0


def test_non_archive_spec_uses_same_registry(tmp_path, sample):
    with SkillRegistry(tmp_path / "registry.db") as registry:
        registry.initialize_archive_storage()
        registry.register_spec(sample)
        assert registry.get_spec("sample-skill") == sample
        assert len(registry.history("sample-skill")) == 1


def test_dependency_validation_precedes_git_commit(tmp_path, sample):
    sample["grasp_dependencies"] = [{"id": "missing", "version": "*"}]
    with SkillRegistry(tmp_path / "registry.db", git_path=tmp_path / "archive") as registry:
        with pytest.raises(ValueError, match="unsatisfied dependency"):
            registry.register_spec(sample)
        assert registry.git_archive.history("sample-skill") == []
        assert registry.list() == []
        assert registry.tx_manager.recover()["rolled_back"] == 1


def test_deletion_checks_dependents_before_archive_move(tmp_path, sample):
    with SkillRegistry(tmp_path / "registry.db", git_path=tmp_path / "archive") as registry:
        registry.register_spec(sample)
        dependent = copy.deepcopy(sample)
        dependent["metadata"]["id"] = "dependent"
        dependent["grasp_dependencies"] = [{"id": "sample-skill", "version": "*"}]
        registry.register_spec(dependent)
        history = registry.git_archive.history("sample-skill")
        with pytest.raises(ValueError, match="dependents"):
            registry.delete_archived_skill("sample-skill")
        assert registry.git_archive.read_skill("sample-skill") == sample
        assert registry.git_archive.history("sample-skill") == history
        registry.delete_archived_skill("dependent")
        registry.delete_archived_skill("sample-skill")
        with pytest.raises(KeyError):
            registry.get("sample-skill")
        assert registry.get("sample-skill", "1.0.0").id == "sample-skill"


@pytest.mark.parametrize("archive_enabled", [False, True])
def test_explicit_layer_filters_and_native_export(tmp_path, sample, archive_enabled):
    from grasp_metaskills.metaskills_spec import spec_content_hash

    archive = tmp_path / "archive" if archive_enabled else None
    with SkillRegistry(tmp_path / "registry.db", git_path=archive) as registry:
        first = registry.register_spec(sample, layer="global")
        assert first.metadata["source_layer"] == "global"
        assert [r.skill.id for r in registry.search("Hello", filters={"layer": "global"})] == [
            "sample-skill"
        ]
        assert registry.search("Hello", filters={"layer": "project"}) == []
        assert registry.get_spec(first.id) == sample
        assert spec_content_hash(registry.get_spec(first.id)) == spec_content_hash(sample)
        assert registry.register_spec(sample, layer="global").version == first.version
        revised = registry.register_spec(sample, layer="project")
        assert revised.version != first.version
        assert revised.metadata["source_layer"] == "project"
        assert registry.search("Hello", filters={"layer": "global"}) == []
        assert registry.search("Hello", filters={"layer": "project"})[0].skill.id == first.id
        assert registry.register_spec(sample, layer="project").version == revised.version
        assert registry.get_spec(first.id) == sample
        assert registry.get(first.id, first.version).metadata["source_layer"] == "global"
        state = registry.db.execute(
            "SELECT layer,digest FROM metaskills_archive_state WHERE skill_id=?", (first.id,)
        ).fetchone()
        assert state["layer"] == "project"
        assert state["digest"] == spec_content_hash(sample)


def test_layer_projection_schema_upgrade(tmp_path):
    import sqlite3

    path = tmp_path / "registry.db"
    with sqlite3.connect(path) as connection:
        connection.execute(
            "CREATE TABLE metaskills_archive_state (skill_id TEXT PRIMARY KEY, "
            "archive_path TEXT NOT NULL, digest TEXT NOT NULL)"
        )
        connection.execute(
            "INSERT INTO metaskills_archive_state VALUES ('old','archive/path','hash')"
        )
    with SkillRegistry(path) as registry:
        row = registry.db.execute("SELECT * FROM metaskills_archive_state").fetchone()
        assert row["layer"] == "project"
        assert row["digest"] == "hash"


def test_layer_survives_recovery_after_finalize_before_complete(tmp_path, sample, monkeypatch):
    with SkillRegistry(tmp_path / "registry.db", git_path=tmp_path / "archive") as registry:
        original = registry.set_tx_phase

        def fail_complete(tx_id, phase, record):
            if phase == "complete":
                raise RuntimeError("finalized before complete phase")
            original(tx_id, phase, record)

        monkeypatch.setattr(registry, "set_tx_phase", fail_complete)
        with pytest.raises(RuntimeError):
            registry.register_spec(sample, layer="global")
        assert registry.get("sample-skill").metadata["source_layer"] == "global"
        monkeypatch.setattr(registry, "set_tx_phase", original)
        assert registry.tx_manager.recover()["completed"] == 1
        assert registry.get("sample-skill").metadata["source_layer"] == "global"
        assert len(registry.history("sample-skill")) == 1
        assert registry.get_spec("sample-skill") == sample
