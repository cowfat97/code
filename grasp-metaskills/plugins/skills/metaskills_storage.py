"""MetaSkills MIT snapshot storage protocol, with explicit crash-safety improvements.

Ported from Jeffrey Emanuel's meta_skill dcd3fb55 (MIT; see licenses/).
The registry remains the owner of skill records; this module owns archive and tx journals.
"""

from __future__ import annotations

import json
import os
import subprocess
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator, Protocol, cast

from .metaskills_spec import normalize_spec, render_skill_markdown, spec_content_hash

Spec = dict[str, Any]


def spec_json(spec: Spec) -> str:
    """Use the shared SkillSpec defaults and declaration-order serialization."""
    return json.dumps(
        normalize_spec(spec), ensure_ascii=False, separators=(",", ":"), allow_nan=False
    )


def content_hash(spec: Spec) -> str:
    return spec_content_hash(spec)


def render_markdown(spec: Spec) -> str:
    return render_skill_markdown(spec)


class GitArchive:
    def __init__(self, root: str | Path):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        if not (self.root / ".git").exists():
            self._git("init", "--quiet")
        for name in ("skills/by-id", "skills/by-source", "builds", "bundles/published"):
            self._safe_path(self.root / name).mkdir(parents=True, exist_ok=True)

    def _git(self, *args: str) -> str:
        return subprocess.run(
            ["git", "-C", str(self.root), *args], check=True, capture_output=True, text=True
        ).stdout.strip()

    def skill_path(self, skill_id: str) -> Path:
        if (
            not skill_id
            or skill_id == "."
            or ".." in skill_id
            or not all(c.isalnum() or c in "-_." for c in skill_id)
        ):
            raise ValueError("invalid skill id")
        path = self.root / "skills/by-id" / skill_id
        if not path.resolve().is_relative_to(self.root):
            raise ValueError("skill path escapes archive")
        return path

    def _safe_path(self, path: Path) -> Path:
        if not path.resolve().is_relative_to(self.root):
            raise ValueError("archive path escapes root")
        return path

    def _commit(self, message: str, paths: list[str]) -> str:
        self._git(
            "-c",
            "user.name=ms",
            "-c",
            "user.email=ms@localhost",
            "commit",
            "--quiet",
            "--allow-empty",
            "--only",
            "-m",
            message,
            "--",
            *paths,
        )
        return self._git("rev-parse", "HEAD")

    def write_skill(self, spec: Spec) -> str:
        path = self.skill_path(spec["metadata"]["id"])
        path.mkdir(parents=True, exist_ok=True)
        for name in ("evidence", "tests"):
            self._safe_path(path / name).mkdir(exist_ok=True)
        normalized = json.loads(spec_json(spec))
        files = {
            "metadata.yaml": json.dumps(normalized["metadata"], ensure_ascii=False, indent=2),
            "skill.spec.json": json.dumps(normalized, ensure_ascii=False, indent=2),
            "SKILL.md": render_markdown(normalized),
            "spec.lens.json": "{}",
            "evidence.json": "{}",
            "slices.json": "[]",
        }
        for name, value in files.items():
            self._safe_path(path / name).write_text(value, encoding="utf-8")
        self._safe_path(path / "usage-log.jsonl").touch(exist_ok=True)
        paths = [str((path / name).relative_to(self.root)) for name in (*files, "usage-log.jsonl")]
        self._git("add", "--", *paths)
        return self._commit("Update skill " + spec["metadata"]["id"].strip(), paths)

    def read_skill(self, skill_id: str, revision: str | None = None) -> Spec:
        path = self.skill_path(skill_id) / "skill.spec.json"
        if revision is None:
            return cast(Spec, json.loads(self._safe_path(path).read_text(encoding="utf-8")))
        oid = self._git("rev-parse", "--verify", revision + "^{commit}")
        return cast(
            Spec, json.loads(self._git("show", oid + ":" + path.relative_to(self.root).as_posix()))
        )

    def history(self, skill_id: str) -> list[str]:
        path = self.skill_path(skill_id).relative_to(self.root)
        try:
            return self._git("log", "--format=%H", "--", str(path)).splitlines()
        except subprocess.CalledProcessError:
            return []

    def matching_commit(self, skill_id: str, digest: str, oid: str | None = None) -> str | None:
        """Require exact spec hash, and ancestry when an OID was journaled."""
        try:
            if content_hash(self.read_skill(skill_id, "HEAD")) != digest:
                return None
        except (subprocess.CalledProcessError, ValueError, KeyError):
            return None
        candidates = [oid] if oid else self.history(skill_id)
        for candidate in candidates:
            try:
                self._git("merge-base", "--is-ancestor", str(candidate), "HEAD")
                if content_hash(self.read_skill(skill_id, candidate)) == digest:
                    return candidate
            except (subprocess.CalledProcessError, ValueError, KeyError):
                continue
        return None

    def delete_skill(self, skill_id: str) -> str:
        path = self.skill_path(skill_id)
        if not path.exists():
            raise KeyError(skill_id)
        tombstone = self.root / "tombstones" / (skill_id + "_" + uuid.uuid4().hex)
        self._safe_path(tombstone).parent.mkdir(exist_ok=True)
        for child in path.rglob("*"):
            self._safe_path(child)
        path.rename(tombstone)
        self._git(
            "add",
            "-A",
            "--",
            str(path.relative_to(self.root)),
            str(tombstone.relative_to(self.root)),
        )
        return self._commit(
            "Tombstone skill " + skill_id,
            [str(path.relative_to(self.root)), str(tombstone.relative_to(self.root))],
        )


class StorageBackend(Protocol):
    """Implemented by the single owning SkillRegistry; undo must be JSON serializable."""

    def prepare_tx(self, record: Spec) -> None: ...
    def set_tx_phase(self, tx_id: str, phase: str, record: Spec) -> None: ...
    def incomplete_txs(self) -> list[Spec]: ...
    def delete_tx(self, tx_id: str) -> None: ...
    def snapshot_skill(self, skill_id: str) -> Any: ...
    def upsert_pending(self, spec: Spec, layer: str) -> None: ...
    def finalize(self, spec: Spec, archive_path: str, digest: str) -> None: ...
    def rollback_pending(self, skill_id: str, undo: Any) -> None: ...
    def delete_stored_skill(self, skill_id: str) -> None: ...


class TxManager:
    def __init__(self, db: StorageBackend, git: GitArchive, ms_root: str | Path):
        self.db, self.git, self.root = db, git, Path(ms_root)
        self.tx_dir = self.root / "tx"
        self.tx_dir.mkdir(parents=True, exist_ok=True)

    @contextmanager
    def lock(self) -> Iterator[None]:
        import fcntl

        with (self.root / "ms.lock").open("a+") as handle:
            fcntl.flock(handle, fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(handle, fcntl.LOCK_UN)

    def _journal(self, tx: Spec) -> None:
        path = self.tx_dir / (tx["id"] + ".json")
        with path.open("w", encoding="utf-8") as handle:
            json.dump(tx, handle, ensure_ascii=False, allow_nan=False)
            handle.flush()
            os.fsync(handle.fileno())

    def _phase(self, tx: Spec, phase: str) -> None:
        tx["phase"] = phase
        self.db.set_tx_phase(tx["id"], phase, tx)
        self._journal(tx)

    def _cleanup(self, tx: Spec) -> None:
        self.db.delete_tx(tx["id"])
        path = self.tx_dir / (tx["id"] + ".json")
        if path.exists():
            tombstones = self.root / "tombstones/tx"
            tombstones.mkdir(parents=True, exist_ok=True)
            path.rename(tombstones / (path.name + "_" + uuid.uuid4().hex))

    def write_skill_with_layer(self, spec: Spec, layer: str = "project") -> None:
        spec = json.loads(spec_json(spec))
        skill_id = spec["metadata"]["id"]
        self.git.skill_path(skill_id)
        tx = {
            "id": str(uuid.uuid4()),
            "entity_type": "skill",
            "entity_id": skill_id,
            "phase": "prepare",
            "payload_json": spec_json(spec),
            "created_at": datetime.now(timezone.utc).isoformat(),
            "layer": layer,
            "digest": content_hash(spec),
            "undo": self.db.snapshot_skill(skill_id),
        }
        self.db.prepare_tx(tx)
        self._journal(tx)
        self.db.upsert_pending(spec, layer)
        self._phase(tx, "pending")
        tx["git_commit"] = self.git.write_skill(spec)
        self._phase(tx, "committed")
        self._finalize(tx)

    write_skill = write_skill_with_layer

    def write_skill_locked(self, spec: Spec) -> None:
        with self.lock():
            self.write_skill(spec)

    def write_skills_batch(self, skills: list[Spec]) -> None:
        with self.lock():
            for spec in skills:
                self.write_skill(spec)

    def delete_skill_locked(self, skill_id: str) -> None:
        with self.lock():
            self.git.skill_path(skill_id)
            tx = {
                "id": str(uuid.uuid4()),
                "entity_type": "delete_skill",
                "entity_id": skill_id,
                "phase": "prepare",
                "payload_json": "{}",
                "created_at": datetime.now(timezone.utc).isoformat(),
                "undo": self.db.snapshot_skill(skill_id),
            }
            # Record parent HEAD to distinguish a committed deletion from a moved worktree.
            tx["before_commit"] = self.git._git("rev-parse", "HEAD")
            self.db.prepare_tx(tx)
            self._journal(tx)
            tx["git_commit"] = self.git.delete_skill(skill_id)
            self._phase(tx, "committed")
            self.db.delete_stored_skill(skill_id)
            self._phase(tx, "complete")
            self._cleanup(tx)

    def _delete_committed(self, tx: Spec) -> bool:
        try:
            head = self.git._git("rev-parse", "HEAD")
            before = tx.get("before_commit")
            if not before or head == before:
                return False
            self.git._git("merge-base", "--is-ancestor", before, head)
            oid = tx.get("git_commit", head)
            self.git._git("merge-base", "--is-ancestor", oid, head)
            # Both the recorded deletion commit and current HEAD must omit the spec.
            for revision in (oid, head):
                try:
                    self.git.read_skill(tx["entity_id"], revision)
                    return False
                except subprocess.CalledProcessError:
                    pass
            return True
        except subprocess.CalledProcessError:
            return False

    def _finalize(self, tx: Spec) -> None:
        spec = json.loads(tx["payload_json"])
        self.db.finalize(spec, str(self.git.skill_path(tx["entity_id"])), tx["digest"])
        self._phase(tx, "complete")
        self._cleanup(tx)

    def recover(self) -> dict[str, int]:
        report = {"rolled_back": 0, "completed": 0, "orphaned_files": 0}
        with self.lock():
            for tx in self.db.incomplete_txs():
                if tx["phase"] == "complete":
                    self._cleanup(tx)
                    continue
                if tx["entity_type"] == "delete_skill":
                    if self._delete_committed(tx):
                        self.db.delete_stored_skill(tx["entity_id"])
                        report["completed"] += 1
                    else:
                        report["rolled_back"] += 1
                    self._cleanup(tx)
                    continue
                match = self.git.matching_commit(
                    tx["entity_id"], tx["digest"], tx.get("git_commit")
                )
                if tx["phase"] in ("pending", "committed") and match:
                    tx["git_commit"] = match
                    self._finalize(tx)
                    report["completed"] += 1
                else:
                    self.db.rollback_pending(tx["entity_id"], tx.get("undo"))
                    self._cleanup(tx)
                    report["rolled_back"] += 1
            for path in self.tx_dir.glob("*.json"):
                tombstones = self.root / "tombstones/tx"
                tombstones.mkdir(parents=True, exist_ok=True)
                path.rename(tombstones / (path.name + "_" + uuid.uuid4().hex))
                report["orphaned_files"] += 1
        return report
