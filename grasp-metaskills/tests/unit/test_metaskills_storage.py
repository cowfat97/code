import copy
import json
from pathlib import Path

import pytest

from grasp_metaskills.metaskills_storage import GitArchive, TxManager, content_hash, render_markdown


class Backend:
    """Crash harness only, not a second production registry."""

    def __init__(self):
        self.rows = {}
        self.txs = {}
        self.fail = None

    def prepare_tx(self, record):
        self.txs[record["id"]] = copy.deepcopy(record)

    def set_tx_phase(self, tx_id, phase, record):
        if self.fail == phase:
            raise RuntimeError("injected crash at " + phase)
        self.txs[tx_id] = copy.deepcopy(record)

    def incomplete_txs(self):
        return copy.deepcopy(list(self.txs.values()))

    def delete_tx(self, tx_id):
        self.txs.pop(tx_id, None)

    def snapshot_skill(self, skill_id):
        return copy.deepcopy(self.rows.get(skill_id))

    def upsert_pending(self, spec, layer):
        self.rows[spec["metadata"]["id"]] = {"spec": spec, "pending": True, "layer": layer}

    def finalize(self, spec, archive_path, digest):
        self.rows[spec["metadata"]["id"]] = {"spec": spec, "pending": False, "hash": digest}

    def rollback_pending(self, skill_id, undo):
        if undo is None:
            self.rows.pop(skill_id, None)
        else:
            self.rows[skill_id] = undo

    def delete_stored_skill(self, skill_id):
        self.rows.pop(skill_id, None)


@pytest.fixture
def sample():
    fixture = Path(__file__).parents[1] / "golden/fixtures/metaskills_storage.json"
    return json.loads(fixture.read_text())["git_sample"]["spec"]


def test_source_git_sample(tmp_path, sample):
    archive = GitArchive(tmp_path / "archive")
    oid = archive.write_skill(sample)
    assert archive.read_skill("sample-skill", oid) == sample
    assert (
        render_markdown(sample)
        == "# Sample Skill\n\nSample description\n\n## Introduction\n\nHello\n\n"
    )
    assert content_hash(sample) == content_hash(archive.read_skill("sample-skill"))
    assert archive.history("sample-skill") == [oid]
    archive.delete_skill("sample-skill")
    with pytest.raises(FileNotFoundError):
        archive.read_skill("sample-skill")
    assert archive.read_skill("sample-skill", oid) == sample


@pytest.mark.parametrize("phase", ["pending", "committed", "complete"])
def test_recovery_crash_windows(tmp_path, sample, phase):
    db = Backend()
    archive = GitArchive(tmp_path / "archive")
    manager = TxManager(db, archive, tmp_path)
    db.fail = phase
    with pytest.raises(RuntimeError):
        manager.write_skill(sample)
    db.fail = None
    report = manager.recover()
    if phase == "pending":
        assert report["rolled_back"] == 1
        assert not db.rows
    else:
        assert report["completed"] == 1
        assert db.rows["sample-skill"]["hash"] == content_hash(sample)
    assert not db.txs
    assert not list((tmp_path / "tx").glob("*.json"))
    assert manager.recover() == {"rolled_back": 0, "completed": 0, "orphaned_files": 0}


def test_existing_head_does_not_complete_failed_update(tmp_path, sample, monkeypatch):
    db = Backend()
    archive = GitArchive(tmp_path / "archive")
    manager = TxManager(db, archive, tmp_path)
    manager.write_skill(sample)
    before = copy.deepcopy(db.rows)
    changed = copy.deepcopy(sample)
    changed["metadata"]["description"] = "new payload never committed"
    monkeypatch.setattr(archive, "write_skill", lambda spec: (_ for _ in ()).throw(RuntimeError()))
    with pytest.raises(RuntimeError):
        manager.write_skill(changed)
    assert manager.recover()["rolled_back"] == 1
    assert db.rows == before


def test_delete_commit_crash_recovery(tmp_path, sample):
    db = Backend()
    manager = TxManager(db, GitArchive(tmp_path / "archive"), tmp_path)
    manager.write_skill(sample)
    db.fail = "committed"
    with pytest.raises(RuntimeError):
        manager.delete_skill_locked("sample-skill")
    db.fail = None
    assert manager.recover()["completed"] == 1
    assert not db.rows


def test_existing_record_restored_after_pending_phase_write_failure(tmp_path, sample):
    db = Backend()
    manager = TxManager(db, GitArchive(tmp_path / "archive"), tmp_path)
    manager.write_skill(sample)
    before = copy.deepcopy(db.rows)
    changed = copy.deepcopy(sample)
    changed["metadata"]["name"] = "uncommitted name"
    db.fail = "pending"
    with pytest.raises(RuntimeError):
        manager.write_skill(changed)
    db.fail = None
    assert manager.recover()["rolled_back"] == 1
    assert db.rows == before


def test_orphan_journal_is_tombstoned(tmp_path):
    db = Backend()
    manager = TxManager(db, GitArchive(tmp_path / "archive"), tmp_path)
    (tmp_path / "tx/broken.json").write_text("not-json")
    assert manager.recover()["orphaned_files"] == 1
    assert list((tmp_path / "tombstones/tx").glob("broken.json_*"))


@pytest.mark.parametrize("skill_id", ["", ".", "..", "../escape", "a/b", "a\\b"])
def test_archive_rejects_invalid_ids(tmp_path, skill_id):
    with pytest.raises(ValueError):
        GitArchive(tmp_path / "archive").skill_path(skill_id)


def test_write_and_delete_preserve_unrelated_staged_change(tmp_path, sample):
    archive = GitArchive(tmp_path / "archive")
    unrelated = archive.root / "unrelated.txt"
    unrelated.write_text("keep staged")
    archive._git("add", "--", "unrelated.txt")
    archive.write_skill(sample)
    assert archive._git("diff", "--cached", "--name-only") == "unrelated.txt"
    assert "unrelated.txt" not in archive._git("ls-tree", "--name-only", "HEAD").splitlines()
    archive.delete_skill("sample-skill")
    assert archive._git("diff", "--cached", "--name-only") == "unrelated.txt"
    assert "unrelated.txt" not in archive._git("ls-tree", "--name-only", "HEAD").splitlines()


@pytest.mark.parametrize(
    "skill_id", ["bad id", "bad\nid", "a:b", "a*", "a?", "a\tX", "\nfoo", "foo\n"]
)
def test_archive_rejects_non_identifier_characters(tmp_path, skill_id):
    with pytest.raises(ValueError):
        GitArchive(tmp_path / "archive").skill_path(skill_id)


def test_write_and_read_reject_external_file_symlink(tmp_path, sample):
    archive = GitArchive(tmp_path / "archive")
    outside = tmp_path / "outside.json"
    outside.write_text("sentinel")
    skill_dir = archive.skill_path("sample-skill")
    skill_dir.mkdir()
    (skill_dir / "skill.spec.json").symlink_to(outside)
    with pytest.raises(ValueError, match="escapes"):
        archive.write_skill(sample)
    assert outside.read_text() == "sentinel"
    with pytest.raises(ValueError, match="escapes"):
        archive.read_skill("sample-skill")


def test_archive_rejects_external_structure_symlink(tmp_path):
    root = tmp_path / "archive"
    root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (root / "skills").symlink_to(outside, target_is_directory=True)
    with pytest.raises(ValueError, match="escapes"):
        GitArchive(root)
    assert not (outside / "by-id").exists()
