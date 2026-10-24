"""Unified SQLite registry with source-derived MetaSkills discovery and archives."""

from __future__ import annotations

import builtins
import hashlib
import json
import math
import re
import sqlite3
import subprocess
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from packaging.specifiers import InvalidSpecifier, SpecifierSet
from packaging.version import InvalidVersion, Version

from ..contracts import SearchResult, Skill, SkillContract
from ..contracts.providers import EmbeddingProvider
from .configuration import SkillsConfig
from .metaskills_composition import ResolvedSkillSpec
from .metaskills_dependencies import ResolvedDependencyPlan
from .metaskills_search import (
    HashEmbeddingProvider,
    SearchFilters,
    cosine_similarity,
    fuse_results,
)
from .registry_recommendation import recommend_skills
from .registry_storage import RegistryStorageMixin


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _matches(version: str, requirement: str) -> bool:
    if requirement in ("", "*"):
        return True
    try:
        spec = requirement if any(c in requirement for c in "<>=!~") else f"=={requirement}"
        return Version(version) in SpecifierSet(spec)
    except (InvalidVersion, InvalidSpecifier) as error:
        raise ValueError(f"invalid version requirement: {requirement}") from error


class SkillRegistry(RegistryStorageMixin):
    """SQLite confirms immutable skills; optional Git writes use recoverable journals.

    Deletion hides the active definition and retains immutable historical versions.
    """

    def __init__(
        self,
        path: str | Path = ":memory:",
        *,
        embedding_provider: EmbeddingProvider | None = HashEmbeddingProvider(),
        git_path: str | Path | None = None,
    ) -> None:
        self.path = str(path)
        self.embedding_provider = embedding_provider
        self.last_search_signals: dict[str, builtins.list[str]] = {}
        self.git_path = Path(git_path) if git_path is not None else None
        self.db = sqlite3.connect(self.path)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA foreign_keys=ON")
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA synchronous=NORMAL")
        self.db.execute("PRAGMA cache_size=-64000")
        self.db.execute("PRAGMA mmap_size=268435456")
        self.db.execute("PRAGMA temp_store=MEMORY")
        self.db.execute("PRAGMA busy_timeout=5000")
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS versions (
                skill_id TEXT NOT NULL, version TEXT NOT NULL, document TEXT NOT NULL,
                content_hash TEXT NOT NULL, created TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY(skill_id,version));
            CREATE TABLE IF NOT EXISTS active (
                skill_id TEXT PRIMARY KEY, version TEXT NOT NULL,
                FOREIGN KEY(skill_id,version) REFERENCES versions(skill_id,version));
            CREATE VIRTUAL TABLE IF NOT EXISTS skills_fts USING fts5(
                skill_id UNINDEXED, name, description, content);
            CREATE TABLE IF NOT EXISTS feedback (
                id INTEGER PRIMARY KEY, skill_id TEXT NOT NULL, version TEXT NOT NULL,
                node_id TEXT NOT NULL, success INTEGER NOT NULL, details TEXT NOT NULL,
                created TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(skill_id,version) REFERENCES versions(skill_id,version));
            CREATE TABLE IF NOT EXISTS runs (
                sequence INTEGER PRIMARY KEY, graph_id TEXT NOT NULL,
                graph_version INTEGER NOT NULL, graph TEXT NOT NULL, state TEXT NOT NULL,
                created TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
            CREATE INDEX IF NOT EXISTS runs_graph ON runs(graph_id,sequence);
            CREATE TABLE IF NOT EXISTS episodes (
                id INTEGER PRIMARY KEY, document TEXT NOT NULL);
        """)
        self.db.commit()
        self.initialize_archive_storage(self.git_path)

    def __enter__(self) -> SkillRegistry:
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()

    def close(self) -> None:
        self.db.close()

    def import_directory(
        self,
        path: str | Path,
        *,
        recursive: bool = True,
        id: str | None = None,
        name: str | None = None,
        version: str | None = None,
        description: str | None = None,
        contract: SkillContract | None = None,
        tool: str | None = None,
    ) -> builtins.list[Skill]:
        from .configuration import SkillSource
        from .importer import import_source

        return import_source(
            self,
            SkillSource(
                path=str(path),
                recursive=recursive,
                id=id,
                name=name,
                version=version,
                description=description,
                contract=contract,
                tool=tool,
            ),
            Path.cwd(),
        )

    def import_config(
        self,
        config: str | Path | SkillsConfig | Mapping[str, Any],
        *,
        base_path: str | Path | None = None,
    ) -> builtins.list[Skill]:
        from .configuration import SkillsConfig
        from .importer import import_source

        if isinstance(config, (str, Path)):
            config_path = Path(config).resolve(strict=True)
            parsed = SkillsConfig.load(config_path)
            base = Path(base_path) if base_path is not None else config_path.parent
        else:
            parsed = (
                config if isinstance(config, SkillsConfig) else SkillsConfig.from_mapping(config)
            )
            base = Path(base_path) if base_path is not None else Path.cwd()
        imported = []
        for source in parsed.skills:
            imported.extend(import_source(self, source, base))
        return imported

    def read_resource(
        self, skill_id: str, relative_path: str | Path, version: str | None = None
    ) -> bytes:
        from .importer import resource_bytes

        return resource_bytes(self.get(skill_id, version), relative_path)

    def _prepare(self, skill: Skill) -> Skill:
        try:
            Version(skill.version)
        except InvalidVersion as error:
            raise ValueError(f"invalid skill version: {skill.version}") from error
        data = skill.model_dump(mode="json")
        data["content_hash"] = ""
        digest = hashlib.sha256(_json(data).encode()).hexdigest()
        if skill.content_hash and skill.content_hash != digest:
            raise ValueError("content hash does not match skill definition")
        data["content_hash"] = digest
        return Skill.model_validate(data)

    def register(self, skill: Skill) -> Skill:
        prepared = self._prepare(skill)
        if self.tx_manager is not None:
            from .metaskills_spec import spec_from_skill

            existing = self.db.execute(
                "SELECT document FROM versions WHERE skill_id=? AND version=?",
                (prepared.id, prepared.version),
            ).fetchone()
            if existing and Skill.model_validate_json(existing["document"]) != prepared:
                # Native spec edits may map a revision; explicit Python versions stay immutable.
                old = Skill.model_validate_json(existing["document"])
                if spec_from_skill(old) != spec_from_skill(prepared):
                    raise ValueError(
                        f"immutable version already exists: {prepared.id}@{prepared.version}"
                    )
            return self.register_spec(
                spec_from_skill(prepared),
                layer=str(prepared.metadata.get("source_layer", "project")),
            )
        with self.db:
            self._register(prepared, {prepared.id: prepared})
            self._check_cycles()
        return prepared.model_copy(deep=True)

    def _register(self, skill: Skill, staged: dict[str, Skill]) -> None:
        existing = self.db.execute(
            "SELECT document FROM versions WHERE skill_id=? AND version=?",
            (skill.id, skill.version),
        ).fetchone()
        if existing and Skill.model_validate_json(existing["document"]) != skill:
            raise ValueError(f"immutable version already exists: {skill.id}@{skill.version}")
        for dep in skill.dependencies:
            if dep.id == skill.id:
                raise ValueError("self dependency is invalid")
            candidate = staged.get(dep.id)
            if candidate is not None and _matches(candidate.version, dep.version):
                continue
            try:
                self.resolve(dep.id, dep.version)
            except KeyError as error:
                raise ValueError(f"unsatisfied dependency {dep.id}@{dep.version}") from error
        self.db.execute(
            "INSERT OR IGNORE INTO versions(skill_id,version,document,content_hash) "
            "VALUES(?,?,?,?)",
            (skill.id, skill.version, skill.model_dump_json(), skill.content_hash),
        )
        self.db.execute(
            "INSERT INTO active(skill_id,version) VALUES(?,?) "
            "ON CONFLICT(skill_id) DO UPDATE SET version=excluded.version",
            (skill.id, skill.version),
        )
        self.db.execute("DELETE FROM skills_fts WHERE skill_id=?", (skill.id,))
        self.db.execute(
            "INSERT INTO skills_fts(skill_id,name,description,content) VALUES(?,?,?,?)",
            (skill.id, skill.name, skill.description, skill.content),
        )

    def _check_cycles(self) -> None:
        visiting: set[tuple[str, str]] = set()
        visited: set[tuple[str, str]] = set()

        def visit(skill: Skill) -> None:
            key = (skill.id, skill.version)
            if key in visiting:
                raise ValueError("skill dependency cycle")
            if key in visited:
                return
            visiting.add(key)
            for dep in skill.dependencies:
                visit(self.resolve(dep.id, dep.version))
            visiting.remove(key)
            visited.add(key)

        for skill in self.list():
            visit(skill)

    def get(self, skill_id: str, version: str | None = None) -> Skill:
        if version is None:
            row = self.db.execute(
                "SELECT v.document FROM versions v JOIN active a "
                "ON v.skill_id=a.skill_id AND v.version=a.version WHERE a.skill_id=?",
                (skill_id,),
            ).fetchone()
        else:
            row = self.db.execute(
                "SELECT document FROM versions WHERE skill_id=? AND version=?", (skill_id, version)
            ).fetchone()
            if row is None and any(c in version for c in "<>=!~*"):
                return self.resolve(skill_id, version)
        if row is None:
            raise KeyError(f"{skill_id}@{version or 'active'}")
        return Skill.model_validate_json(row["document"])

    def resolve(self, skill_id: str, requirement: str = "*") -> Skill:
        candidates = [s for s in self.history(skill_id) if _matches(s.version, requirement)]
        if not candidates:
            raise KeyError(f"{skill_id}@{requirement}")
        winner = max(candidates, key=lambda s: Version(s.version))
        public = Version(winner.version).public
        revisions = [s for s in candidates if Version(s.version).public == public]
        if any("+ms." in s.version for s in revisions):
            # Content digests identify revisions; their lexical order is not time.
            try:
                active = self.get(skill_id)
                if any(active.version == s.version for s in revisions):
                    return active
            except KeyError:
                pass
            by_version = {s.version: s for s in revisions}
            for row in self.db.execute(
                "SELECT version FROM versions WHERE skill_id=? ORDER BY rowid DESC", (skill_id,)
            ):
                if row["version"] in by_version:
                    return by_version[row["version"]]
        return winner

    def list(self) -> builtins.list[Skill]:
        rows = self.db.execute(
            "SELECT v.document FROM versions v JOIN active a "
            "ON v.skill_id=a.skill_id AND v.version=a.version ORDER BY a.skill_id"
        )
        return [Skill.model_validate_json(r["document"]) for r in rows]

    def history(self, skill_id: str) -> builtins.list[Skill]:
        rows = self.db.execute("SELECT document FROM versions WHERE skill_id=?", (skill_id,))
        return sorted(
            (Skill.model_validate_json(r["document"]) for r in rows),
            key=lambda s: Version(s.version),
        )

    def delete(self, skill_id: str) -> None:
        if self.tx_manager is not None:
            self.delete_archived_skill(skill_id)
            return
        if self.dependents(skill_id):
            raise ValueError("cannot delete skill with active dependents")
        with self.db:
            self.db.execute("DELETE FROM active WHERE skill_id=?", (skill_id,))
            self.db.execute("DELETE FROM skills_fts WHERE skill_id=?", (skill_id,))

    def dependencies(
        self, skill_id: str, version: str | None = None, *, recursive: bool = False
    ) -> builtins.list[Skill]:
        root = self.get(skill_id, version)
        result: dict[tuple[str, str], Skill] = {}

        def add(skill: Skill) -> None:
            for dep in skill.dependencies:
                candidate = self.resolve(dep.id, dep.version)
                key = (candidate.id, candidate.version)
                if key in result:
                    continue
                result[key] = candidate
                if recursive:
                    add(candidate)

        add(root)
        return list(result.values())

    def dependents(self, skill_id: str) -> builtins.list[Skill]:
        try:
            capabilities = set(self.get(skill_id).metadata.get("provides", []))
        except KeyError:
            capabilities = set()
        return [
            s
            for s in self.list()
            if s.id != skill_id
            and (
                any(d.id == skill_id for d in s.dependencies)
                or capabilities.intersection(s.metadata.get("requires", []))
            )
        ]

    def capability_dependencies(self, skill_id: str) -> ResolvedDependencyPlan:
        """Source load plan over the same active unified skill definitions."""
        from .metaskills_dependencies import resolve_dependencies

        self.get(skill_id)
        return resolve_dependencies(self.list(), skill_id)

    def compose_spec(self, skill_id: str) -> ResolvedSkillSpec:
        """Resolve source extends/includes using live unified metadata projections.

        The returned value is transient. Persist it explicitly with register_spec
        if desired; no second mutable specification repository is maintained.
        """
        from .metaskills_composition import resolve_full

        repository = {skill.id: self.get_spec(skill.id) for skill in self.list()}
        return resolve_full(repository[skill_id], repository)

    @staticmethod
    def _filter(skill: Skill, filters: dict[str, Any] | SearchFilters | None) -> bool:
        source_keys = {"tags", "layer", "min_quality", "include_deprecated"}
        if isinstance(filters, SearchFilters):
            source_filters = filters
            generic: dict[str, Any] = {}
        else:
            values = filters or {}
            source_filters = SearchFilters(**{k: v for k, v in values.items() if k in source_keys})
            generic = {k: v for k, v in values.items() if k not in source_keys}
        metadata = skill.metadata
        raw_tags = metadata.get("tags", [])
        tags = (
            [tag.lower() for tag in raw_tags if isinstance(tag, str)]
            if isinstance(raw_tags, list)
            else []
        )
        if not source_filters.matches(
            tags,
            str(metadata.get("source_layer", metadata.get("layer", "project"))),
            float(metadata.get("quality_score", metadata.get("quality", 0.0))),
            bool(metadata.get("is_deprecated", metadata.get("deprecated", False))),
        ):
            return False
        for key, expected in generic.items():
            actual = getattr(skill, key, metadata.get(key))
            if isinstance(expected, (list, set, tuple)):
                if actual not in expected:
                    return False
            elif actual != expected:
                return False
        return True

    def search(
        self,
        query: str,
        mode: str = "keyword",
        limit: int = 20,
        filters: dict[str, Any] | SearchFilters | None = None,
    ) -> builtins.list[SearchResult]:
        """SQLite lexical candidates plus source MetaSkills hash/cosine/RRF/filter core."""
        if mode not in ("keyword", "fulltext", "semantic", "hybrid"):
            raise ValueError(f"unknown search mode: {mode}")
        if limit < 0:
            raise ValueError("limit must be nonnegative")
        self.last_search_signals = {}
        candidates = {skill.id: skill for skill in self.list()}
        lexical: builtins.list[tuple[str, float]] = []
        tokens = re.findall(r"\w+", query, flags=re.UNICODE)
        if tokens:
            expression = " OR ".join('"' + token.replace('"', '""') + '"' for token in tokens)
            rows = self.db.execute(
                "SELECT skill_id,bm25(skills_fts) AS rank FROM skills_fts "
                "WHERE skills_fts MATCH ? ORDER BY rank,skill_id",
                (expression,),
            )
            lexical = [
                (row["skill_id"], -float(row["rank"]))
                for row in rows
                if row["skill_id"] in candidates
            ]
        elif mode in ("keyword", "fulltext"):
            lexical = [(key, 0.0) for key in sorted(candidates)]
        signals = {key: ["bm25"] for key, _ in lexical}
        if mode in ("keyword", "fulltext"):
            ranked = lexical
        else:
            if self.embedding_provider is None:
                raise ValueError("semantic/hybrid search requires an EmbeddingProvider")
            ids = sorted(candidates)
            texts = [query] + [
                f"{candidates[key].name}\n{candidates[key].description}\n{candidates[key].content}"
                for key in ids
            ]
            vectors = self.embedding_provider.embed(texts)
            if len(vectors) != len(texts) or not vectors or not vectors[0]:
                raise ValueError("EmbeddingProvider returned invalid vector count or empty vector")
            dims = len(vectors[0])
            if any(
                len(vector) != dims or any(not math.isfinite(x) for x in vector)
                for vector in vectors
            ):
                raise ValueError(
                    "EmbeddingProvider returned invalid dimensions or nonfinite values"
                )
            semantic = [
                (key, cosine_similarity(vectors[0], vector))
                for key, vector in zip(ids, vectors[1:], strict=True)
            ]
            semantic.sort(key=lambda item: (-item[1], item[0]))
            if mode == "semantic":
                signals = {key: ["embedding"] for key, _ in semantic}
            else:
                for key, _ in semantic:
                    signals.setdefault(key, []).append("embedding")
            ranked = (
                semantic
                if mode == "semantic"
                else [(result.skill_id, result.score) for result in fuse_results(lexical, semantic)]
            )
        # Upstream filters apply after fusion, before final caller truncation.
        filtered = [(key, score) for key, score in ranked if self._filter(candidates[key], filters)]
        self.last_search_signals = {key: signals.get(key, []) for key, _ in filtered[:limit]}
        return [SearchResult(skill=candidates[key], score=score) for key, score in filtered[:limit]]

    def recommend(self, skill_id: str, limit: int = 10) -> builtins.list[SearchResult]:
        """Application candidate aggregation using upstream learned signal weights."""
        return recommend_skills(self, skill_id, limit)

    def export_json(self, *, include_history: bool = False) -> str:
        if include_history:
            rows = self.db.execute("SELECT document FROM versions ORDER BY skill_id,version")
            return _json([json.loads(row["document"]) for row in rows])
        return _json([s.model_dump(mode="json") for s in self.list()])

    def import_json(self, data: str) -> builtins.list[Skill]:
        raw = json.loads(data)
        if not isinstance(raw, list):
            raise ValueError("import must contain a JSON list")
        skills = [self._prepare(Skill.model_validate(item)) for item in raw]
        staged = {s.id: s for s in skills}
        if self.tx_manager is not None:
            # Preflight the whole batch before any archive mutation. Actual archive
            # writes remain per-skill journal transactions, as in upstream's batch.
            self.db.execute("SAVEPOINT archive_import_validate")
            try:
                for skill in skills:
                    self._register(skill, staged)
                self._check_cycles()
            finally:
                self.db.execute("ROLLBACK TO archive_import_validate")
                self.db.execute("RELEASE archive_import_validate")
            remaining = list(enumerate(skills))
            imported: dict[int, Skill] = {}
            while remaining:
                progressed = False
                for index, skill in list(remaining):
                    try:
                        for dep in skill.dependencies:
                            self.resolve(dep.id, dep.version)
                    except KeyError:
                        continue
                    imported[index] = self.register(skill)
                    remaining.remove((index, skill))
                    progressed = True
                if not progressed:
                    raise ValueError("archive import has unresolved version dependencies")
            return [imported[index] for index in range(len(skills))]
        with self.db:
            for skill in skills:
                self._register(skill, staged)
            self._check_cycles()
        return skills

    def record_feedback(
        self, skill_id: str, version: str, node_id: str, success: bool, details: Any
    ) -> None:
        self.get(skill_id, version)
        with self.db:
            self.db.execute(
                "INSERT INTO feedback(skill_id,version,node_id,success,details) VALUES(?,?,?,?,?)",
                (skill_id, version, node_id, int(success), _json(details)),
            )

    def feedback(self, skill_id: str, version: str | None = None) -> builtins.list[dict[str, Any]]:
        sql = "SELECT * FROM feedback WHERE skill_id=?"
        params: tuple[str, ...] = (skill_id,)
        if version is not None:
            sql += " AND version=?"
            params += (version,)
        records = []
        for row in self.db.execute(sql + " ORDER BY id", params):
            record = dict(row)
            record["success"] = bool(record["success"])
            record["details"] = json.loads(record["details"])
            records.append(record)
        return records

    def record_episode(self, task: str, trajectory: builtins.list[str], success: bool) -> None:
        with self.db:
            self.db.execute(
                "INSERT INTO episodes(document) VALUES(?)",
                (_json({"task": task, "trajectory": trajectory, "success": int(success)}),),
            )

    def episodes(self) -> builtins.list[dict[str, Any]]:
        return [
            json.loads(row["document"])
            for row in self.db.execute("SELECT document FROM episodes ORDER BY id")
        ]

    def save_run(self, graph_id: str, graph: dict[str, Any], state: dict[str, Any]) -> None:
        with self.db:
            self.db.execute(
                "INSERT INTO runs(graph_id,graph_version,graph,state) VALUES(?,?,?,?)",
                (graph_id, int(graph.get("version", 1)), _json(graph), _json(state)),
            )

    def load_run(self, graph_id: str) -> tuple[dict[str, Any], dict[str, Any]] | None:
        row = self.db.execute(
            "SELECT graph,state FROM runs WHERE graph_id=? ORDER BY sequence DESC LIMIT 1",
            (graph_id,),
        ).fetchone()
        return (json.loads(row["graph"]), json.loads(row["state"])) if row else None

    def run_history(self, graph_id: str) -> builtins.list[tuple[dict[str, Any], dict[str, Any]]]:
        return [
            (json.loads(r["graph"]), json.loads(r["state"]))
            for r in self.db.execute(
                "SELECT graph,state FROM runs WHERE graph_id=? ORDER BY sequence", (graph_id,)
            )
        ]

    def commit_git(self, message: str = "Snapshot skill registry") -> str:
        if self.git_path is None:
            raise ValueError("git_path is required for Git history")
        self.git_path.mkdir(parents=True, exist_ok=True)

        def git(*args: str) -> str:
            return subprocess.run(
                ["git", "-C", str(self.git_path), *args], check=True, capture_output=True, text=True
            ).stdout.strip()

        if not (self.git_path / ".git").exists():
            git("init", "--quiet")
        snapshot = self.git_path / "skills.json"
        snapshot.write_text(self.export_json(include_history=True) + "\n", encoding="utf-8")
        git("add", "--", "skills.json")
        changed = subprocess.run(
            ["git", "-C", str(self.git_path), "diff", "--cached", "--quiet", "--", "skills.json"],
            check=False,
        ).returncode
        if changed not in (0, 1):
            raise RuntimeError("Git staged diff failed")
        if changed:
            git(
                "-c",
                "user.name=grasp-metaskills",
                "-c",
                "user.email=registry@localhost",
                "commit",
                "--quiet",
                "-m",
                message,
                "--",
                "skills.json",
            )
        return git("rev-parse", "HEAD")

    def git_history(self) -> builtins.list[str]:
        if self.git_path is None:
            raise ValueError("git_path is required for Git history")
        result = subprocess.run(
            ["git", "-C", str(self.git_path), "log", "--format=%H", "--", "skills.json"],
            check=True,
            capture_output=True,
            text=True,
        )
        return result.stdout.splitlines()
