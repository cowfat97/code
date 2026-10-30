"""One directory-backed registry: current definitions only, no skill version archive."""

from __future__ import annotations

import builtins
import hashlib
import json
import math
import re
import shutil
from collections import Counter
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from ..contracts import SearchResult, Skill
from ..contracts.providers import EmbeddingProvider
from .configuration import SkillsConfig, SkillSource
from .file_storage import RunStorage, atomic_write, file_lock, json_bytes
from .importer import load_source, resource_bytes
from .metaskills_composition import ResolvedSkillSpec, resolve_full
from .metaskills_dependencies import ResolvedDependencyPlan, resolve_dependencies
from .metaskills_search import HashEmbeddingProvider, SearchFilters, cosine_similarity, fuse_results
from .metaskills_spec import skill_from_spec, spec_from_skill


class SkillRegistry(RunStorage):
    def __init__(
        self,
        path: str | Path,
        *,
        state_path: str | Path,
        embedding_provider: EmbeddingProvider | None = HashEmbeddingProvider(),
    ) -> None:
        self.path = Path(path).resolve()
        self.embedding_provider = embedding_provider
        self.last_search_signals: dict[str, builtins.list[str]] = {}
        self._skills: dict[str, Skill] = {}
        self._sources: builtins.list[tuple[SkillSource, Path]] = []
        super().__init__(Path(state_path))

    def close(self) -> None:
        """Files are opened per operation; closing owns no persistent handle."""
        self._skills.clear()

    @staticmethod
    def _prepare(skill: Skill) -> Skill:
        data = skill.model_dump(mode="json")
        data.pop("content_hash", None)
        digest = hashlib.sha256(json_bytes(data)).hexdigest()
        return skill.model_copy(update={"content_hash": digest}, deep=True)

    @staticmethod
    def _validate(skills: dict[str, Skill]) -> None:
        visited: set[str] = set()
        active: set[str] = set()

        def visit(identity: str) -> None:
            if identity in active:
                raise ValueError(f"skill dependency cycle: {identity}")
            if identity in visited:
                return
            active.add(identity)
            for dependency in skills[identity].dependencies:
                if dependency.id not in skills:
                    raise ValueError(f"missing skill dependency: {dependency.id}")
                visit(dependency.id)
            active.remove(identity)
            visited.add(identity)

        for identity in skills:
            visit(identity)

    def reload(self) -> builtins.list[Skill]:
        self.path.mkdir(parents=True, exist_ok=True)
        with file_lock(self.path / ".registry.lock"):
            by_source: dict[str, Skill] = {}
            sources = [(SkillSource(path=str(self.path)), self.path.parent), *self._sources]
            for source, base in sources:
                for skill in load_source(source, base):
                    by_source[skill.source] = skill
            staged: dict[str, Skill] = {}
            for skill in by_source.values():
                if skill.id in staged:
                    raise ValueError(f"duplicate skill id: {skill.id}")
                staged[skill.id] = skill
            self._validate(staged)
            # Publish only after the complete directory set has passed validation.
            self._skills = {key: self._prepare(value) for key, value in staged.items()}
        return self.list()

    def import_config(
        self,
        config: str | Path | SkillsConfig | Mapping[str, Any],
        *,
        base_path: str | Path | None = None,
    ) -> builtins.list[Skill]:
        if isinstance(config, (str, Path)):
            config_path = Path(config).resolve(strict=True)
            parsed = SkillsConfig.load(config_path)
            base = Path(base_path) if base_path is not None else config_path.parent
        else:
            parsed = (
                config if isinstance(config, SkillsConfig) else SkillsConfig.from_mapping(config)
            )
            base = Path(base_path) if base_path is not None else Path.cwd()
        previous = self._sources.copy()
        for source in parsed.skills:
            pair = (source, base.resolve())
            if pair not in self._sources:
                self._sources.append(pair)
        try:
            return self.reload()
        except BaseException:
            self._sources = previous
            raise

    def import_directory(self, path: str | Path, **options: Any) -> builtins.list[Skill]:
        return self.import_config({"skills": [{"path": str(path), **options}]})

    def get(self, skill_id: str) -> Skill:
        return self._skills[skill_id].model_copy(deep=True)

    def list(self) -> builtins.list[Skill]:
        return [self.get(key) for key in sorted(self._skills)]

    def resolve(self, skill_id: str) -> Skill:
        return self.get(skill_id)

    def read_resource(self, skill_id: str, relative_path: str | Path) -> bytes:
        return resource_bytes(self.get(skill_id), relative_path)

    def dependencies(self, skill_id: str, *, recursive: bool = False) -> builtins.list[Skill]:
        found: dict[str, Skill] = {}

        def walk(skill: Skill) -> None:
            for dep in skill.dependencies:
                if dep.id not in found:
                    found[dep.id] = self.get(dep.id)
                    if recursive:
                        walk(found[dep.id])

        walk(self.get(skill_id))
        return list(found.values())

    def dependents(self, skill_id: str) -> builtins.list[Skill]:
        return [s for s in self.list() if any(d.id == skill_id for d in s.dependencies)]

    def capability_dependencies(self, skill_id: str) -> ResolvedDependencyPlan:
        return resolve_dependencies(self.list(), skill_id)

    def compose_spec(self, skill_id: str) -> ResolvedSkillSpec:
        repository = {s.id: spec_from_skill(s) for s in self.list()}
        return resolve_full(repository[skill_id], repository)

    def register_spec(self, spec: dict[str, Any], *, layer: str = "project") -> Skill:
        skill = skill_from_spec(spec)
        metadata = dict(skill.metadata)
        metadata["source_layer"] = layer
        return self.register(skill.model_copy(update={"metadata": metadata}))

    def register(self, skill: Skill) -> Skill:
        if skill.id in self._skills:
            raise ValueError("skill already exists; edit its files and reload")
        self._validate({**self._skills, skill.id: skill})
        directory = self.path / hashlib.sha256(skill.id.encode()).hexdigest()[:24]
        self.path.mkdir(parents=True, exist_ok=True)
        with file_lock(self.path / ".registry.lock"):
            if directory.exists():
                raise ValueError("skill directory already exists; reload registry first")
            directory.mkdir()
            try:
                metadata = dict(skill.metadata)
                resources = metadata.pop("resources", {})
                metadata.pop("resource_directory", None)
                for relative in resources:
                    resource = Path(relative)
                    if (
                        resource.is_absolute()
                        or ".." in resource.parts
                        or resource.name in {"SKILL.md", "contract.json"}
                    ):
                        raise ValueError("invalid embedded resource path")
                    atomic_write(directory / resource, resource_bytes(skill, relative))
                atomic_write(
                    directory / "contract.json",
                    json_bytes(
                        {
                            "id": skill.id,
                            "name": skill.name,
                            "description": skill.description,
                            "metadata": metadata,
                            "contract": skill.contract.model_dump(mode="json"),
                            "dependencies": [d.model_dump() for d in skill.dependencies],
                        }
                    ),
                )
                # SKILL.md publishes the directory to scanners only after metadata is durable.
                atomic_write(directory / "SKILL.md", skill.content.encode())
            except BaseException:
                shutil.rmtree(directory)
                raise
        self.reload()
        return self.get(skill.id)

    def delete(self, skill_id: str) -> None:
        skill = self.get(skill_id)
        if self.dependents(skill_id):
            raise ValueError("cannot delete skill with dependents")
        from urllib.parse import unquote, urlsplit

        source = urlsplit(skill.source)
        if source.scheme != "file":
            raise ValueError("skill has no editable source directory")
        directory = Path(unquote(source.path)).resolve()
        if not directory.is_relative_to(self.path):
            raise ValueError("delete externally configured skills in their source directory")
        with file_lock(self.path / ".registry.lock"):
            (directory / "SKILL.md").unlink()
        self.reload()

    def export_json(self) -> str:
        return json.dumps([s.model_dump(mode="json") for s in self.list()], ensure_ascii=False)

    def get_spec(self, skill_id: str) -> dict[str, Any]:
        return spec_from_skill(self.get(skill_id))

    @staticmethod
    def _tokens(text: str) -> builtins.list[str]:
        return re.findall(r"[a-z0-9_]+|[\u4e00-\u9fff]", text.casefold())

    def _lexical(
        self, query: str, skills: builtins.list[Skill]
    ) -> builtins.list[tuple[str, float]]:
        terms = set(self._tokens(query))
        if not terms:
            return [(s.id, 0.0) for s in skills]
        documents = [self._tokens(f"{s.name} {s.description} {s.content}") for s in skills]
        average = sum(map(len, documents)) / max(len(documents), 1) or 1
        frequencies = {term: sum(term in doc for doc in documents) for term in terms}
        ranked = []
        for skill, doc in zip(skills, documents, strict=True):
            counts = Counter(doc)
            score = sum(
                math.log(1 + (len(documents) - frequencies[t] + 0.5) / (frequencies[t] + 0.5))
                * counts[t]
                * 2.2
                / (counts[t] + 1.2 * (0.25 + 0.75 * len(doc) / average))
                for t in terms
                if counts[t]
            )
            if score:
                ranked.append((skill.id, score))
        return sorted(ranked, key=lambda pair: (-pair[1], pair[0]))

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
        """In-memory BM25 plus injectable embeddings and reciprocal rank fusion."""
        if mode not in ("keyword", "fulltext", "semantic", "hybrid"):
            raise ValueError(f"unknown search mode: {mode}")
        if limit < 0:
            raise ValueError("limit must be nonnegative")
        self.last_search_signals = {}
        candidates = {skill.id: skill for skill in self.list()}
        lexical = self._lexical(query, list(candidates.values()))
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
        from .registry_recommendation import recommend_skills

        return recommend_skills(self, skill_id, limit)
