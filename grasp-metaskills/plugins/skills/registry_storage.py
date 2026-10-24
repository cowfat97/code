"""Single-registry adapter for MetaSkills archive transactions.

The pending table is a transaction projection. Confirmed skills always live in
SkillRegistry's existing versions/active tables; there is no second skill registry.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable

from packaging.version import InvalidVersion, Version

from ..contracts import Skill, SkillContract
from .metaskills_spec import (
    normalize_spec,
    skill_from_spec,
    spec_content_hash,
    spec_from_skill,
)
from .metaskills_storage import GitArchive, Spec, TxManager


def _encode(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False)


class RegistryStorageMixin:
    """StorageBackend callbacks for the existing SkillRegistry connection."""

    if TYPE_CHECKING:
        db: sqlite3.Connection
        _prepare: Callable[[Skill], Skill]
        _register: Callable[[Skill, dict[str, Skill]], None]
        _check_cycles: Callable[[], None]
        get: Callable[..., Skill]
        dependents: Callable[[str], list[Skill]]
        resolve: Callable[..., Skill]

    git_archive: GitArchive | None = None
    tx_manager: TxManager | None = None

    def initialize_archive_storage(
        self,
        git_path: str | Path | None = None,
        *,
        ms_root: str | Path | None = None,
        recover: bool = True,
    ) -> None:
        self.initialize_storage_schema()
        self.git_archive = GitArchive(git_path) if git_path is not None else None
        self.tx_manager = None
        if self.git_archive is not None:
            root = Path(ms_root) if ms_root is not None else self.git_archive.root / ".ms"
            self.tx_manager = TxManager(self, self.git_archive, root)
            if recover:
                self.tx_manager.recover()

    def initialize_storage_schema(self) -> None:
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS metaskills_tx_log (
                id TEXT PRIMARY KEY, phase TEXT NOT NULL, document TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS metaskills_archive_state (
                skill_id TEXT PRIMARY KEY, archive_path TEXT NOT NULL, digest TEXT NOT NULL,
                layer TEXT NOT NULL DEFAULT 'project');
            CREATE TABLE IF NOT EXISTS metaskills_pending (
                skill_id TEXT PRIMARY KEY, document TEXT NOT NULL, layer TEXT NOT NULL);
        """)
        columns = {
            row["name"] for row in self.db.execute("PRAGMA table_info(metaskills_archive_state)")
        }
        if "layer" not in columns:
            self.db.execute(
                "ALTER TABLE metaskills_archive_state "
                "ADD COLUMN layer TEXT NOT NULL DEFAULT 'project'"
            )
        self.db.commit()

    def prepare_tx(self, record: Spec) -> None:
        with self.db:
            self.db.execute(
                "INSERT INTO metaskills_tx_log(id,phase,document) VALUES(?,?,?)",
                (record["id"], record["phase"], _encode(record)),
            )

    def set_tx_phase(self, tx_id: str, phase: str, record: Spec) -> None:
        with self.db:
            cursor = self.db.execute(
                "UPDATE metaskills_tx_log SET phase=?,document=? WHERE id=?",
                (phase, _encode(record), tx_id),
            )
            if cursor.rowcount != 1:
                raise KeyError("missing transaction " + tx_id)

    def incomplete_txs(self) -> list[Spec]:
        # Include complete rows for cleanup after a crash before journal removal.
        return [
            json.loads(row["document"])
            for row in self.db.execute("SELECT document FROM metaskills_tx_log ORDER BY rowid")
        ]

    def delete_tx(self, tx_id: str) -> None:
        with self.db:
            self.db.execute("DELETE FROM metaskills_tx_log WHERE id=?", (tx_id,))

    def snapshot_skill(self, skill_id: str) -> Any:
        row = self.db.execute(
            "SELECT document,layer FROM metaskills_pending WHERE skill_id=?",
            (skill_id,),
        ).fetchone()
        return dict(row) if row is not None else None

    def upsert_pending(self, spec: Spec, layer: str) -> None:
        normalized = normalize_spec(spec)
        # Validate the final executable projection before writing a Git commit.
        candidate = self._skill_for_spec(normalized, "", layer)
        # Validate dependency/cycle constraints without publishing a confirmed version.
        self.db.execute("SAVEPOINT metaskills_validate")
        try:
            self._register(candidate, {candidate.id: candidate})
            self._check_cycles()
        finally:
            self.db.execute("ROLLBACK TO metaskills_validate")
            self.db.execute("RELEASE metaskills_validate")
        with self.db:
            self.db.execute(
                "INSERT INTO metaskills_pending(skill_id,document,layer) VALUES(?,?,?) "
                "ON CONFLICT(skill_id) DO UPDATE SET document=excluded.document,"
                "layer=excluded.layer",
                (normalized["metadata"]["id"], _encode(normalized), layer),
            )

    def _skill_for_spec(self, spec: Spec, source: str, layer: str = "project") -> Skill:
        normalized = normalize_spec(spec)
        declared = normalized["metadata"]["version"]
        digest = spec_content_hash(normalized)
        skill = skill_from_spec(normalized)
        metadata = dict(skill.metadata)
        metadata["metaskills_declared_version"] = declared
        metadata["source_layer"] = layer
        try:
            base = str(Version(declared)) if declared else "0.1.0"
        except InvalidVersion:
            base = "0.1.0+ms." + digest
        candidate = self._prepare(skill.model_copy(update={"version": base, "metadata": metadata}))
        row = self.db.execute(
            "SELECT document FROM versions WHERE skill_id=? AND version=?",
            (candidate.id, candidate.version),
        ).fetchone()
        if row is not None:
            previous = Skill.model_validate_json(row["document"])
            # Same semantic spec is idempotent even when its source path differs.
            if (
                spec_content_hash(spec_from_skill(previous)) == digest
                and previous.metadata.get("source_layer", "project") == layer
            ):
                return previous
            public = Version(base).public
            # Layer is extrinsic to the native spec, but part of immutable Skill state.
            # Its suffix prevents same-spec layer revisions colliding in versions.
            layer_digest = hashlib.sha256(layer.encode()).hexdigest()[:16]
            mapped = public + "+ms." + digest + ".layer." + layer_digest
            candidate = self._prepare(
                skill.model_copy(update={"version": mapped, "metadata": metadata})
            )
        return candidate

    def finalize(
        self,
        spec: Spec,
        archive_path: str,
        digest: str,
        *,
        layer: str | None = None,
    ) -> None:
        normalized = normalize_spec(spec)
        if spec_content_hash(normalized) != digest:
            raise ValueError("transaction spec hash mismatch")
        if layer is None:
            pending = self.db.execute(
                "SELECT layer FROM metaskills_pending WHERE skill_id=?",
                (normalized["metadata"]["id"],),
            ).fetchone()
            if pending is None:
                pending = self.db.execute(
                    "SELECT layer FROM metaskills_archive_state WHERE skill_id=?",
                    (normalized["metadata"]["id"],),
                ).fetchone()
            layer = pending["layer"] if pending is not None else "project"
        candidate = self._skill_for_spec(normalized, archive_path, layer)
        with self.db:
            self._register(candidate, {candidate.id: candidate})
            self._check_cycles()
            self.db.execute(
                "INSERT INTO metaskills_archive_state(skill_id,archive_path,digest,layer) "
                "VALUES(?,?,?,?) "
                "ON CONFLICT(skill_id) DO UPDATE SET archive_path=excluded.archive_path,"
                "digest=excluded.digest,layer=excluded.layer",
                (candidate.id, archive_path, digest, layer),
            )
            self.db.execute("DELETE FROM metaskills_pending WHERE skill_id=?", (candidate.id,))

    def rollback_pending(self, skill_id: str, undo: Any) -> None:
        with self.db:
            self.db.execute("DELETE FROM metaskills_pending WHERE skill_id=?", (skill_id,))
            if undo is not None:
                self.db.execute(
                    "INSERT INTO metaskills_pending(skill_id,document,layer) VALUES(?,?,?)",
                    (skill_id, undo["document"], undo["layer"]),
                )

    def delete_stored_skill(self, skill_id: str) -> None:
        if self.dependents(skill_id):
            raise ValueError("cannot delete skill with active dependents")
        with self.db:
            self.db.execute("DELETE FROM active WHERE skill_id=?", (skill_id,))
            self.db.execute("DELETE FROM metaskills_archive_state WHERE skill_id=?", (skill_id,))
            self.db.execute("DELETE FROM skills_fts WHERE skill_id=?", (skill_id,))
            self.db.execute("DELETE FROM metaskills_pending WHERE skill_id=?", (skill_id,))

    def register_spec(
        self,
        spec: Spec,
        *,
        layer: str = "project",
        contract: SkillContract | None = None,
    ) -> Skill:
        document = normalize_spec(spec)
        if contract is not None:
            document["grasp_contract"] = contract.model_dump(mode="json")
        if self.tx_manager is not None:
            with self.tx_manager.lock():
                self.tx_manager.write_skill_with_layer(document, layer)
        else:
            self.finalize(document, "", spec_content_hash(document), layer=layer)
        return self.get(document["metadata"]["id"]).model_copy(deep=True)

    def delete_archived_skill(self, skill_id: str) -> None:
        # Check before moving/committing archive contents, not only in the callback.
        if self.dependents(skill_id):
            raise ValueError("cannot delete skill with active dependents")
        if self.tx_manager is not None:
            self.tx_manager.delete_skill_locked(skill_id)
        else:
            self.delete_stored_skill(skill_id)

    def get_spec(self, skill_id: str, version: str | None = None) -> Spec:
        return spec_from_skill(self.get(skill_id, version))

    def export_spec(self, skill_id: str, version: str | None = None) -> str:
        return _encode(self.get_spec(skill_id, version))

    def resolve_spec(self, skill_id: str, requirement: str = "*") -> Spec:
        return spec_from_skill(self.resolve(skill_id, requirement))
