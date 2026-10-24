# MetaSkills storage audit — fixed MIT snapshot

Source: `grasp-metaskills-upstream-meta-skill`, commit `dcd3fb55cabb438dc200f9b7c784ca14c08135ce` only. No later source consulted. This is a source-level audit, not a claim that Rust tests ran.

## Persistence contract

`src/core/skill.rs:44–271` defines the structured `SkillSpec` as source of truth, format version `1.0`, metadata, ordered sections/blocks, optional inheritance and composition. Metadata version is a plain string, not a store-level immutable semver key. The convenience `Skill::new` uses `0.1.0`; `SkillSpec::new` leaves the metadata version at its default empty string.

`migrations/001_initial_schema.sql` has `skills(id PRIMARY KEY)` and one current record per ID, plus aliases, evidence, slices, capabilities, dependencies, usage and transaction tables. There is no versions/active pair. `sqlite.rs:357–408` upserts current records. `GitArchive` provides historical commits, not a SQL semver resolver.

`git.rs:249–305` writes `skills/by-id/<id>/metadata.yaml`, `skill.spec.json`, `SKILL.md`, `spec.lens.json` (`{}`), `evidence.json` (`{}`), `slices.json` (`[]`) and preserves/creates `usage-log.jsonl`. Each write commits `Update skill <id>`. It also creates empty evidence/tests directories, which Git does not track. Read methods read the working tree, not a chosen historical revision. Git commit rendering (`render_skill_markdown`) and SQLite body compilation (`spec_lens::compile_markdown`) are separate implementations; do not assume byte identity. IDs are trimmed by write, and reject empty, `..`, slash/backslash; `skill_path` is a distinct validation path.

## Dual write, recovery, and limitations

`tx.rs:419–644` implements prepare → pending → committed → complete, with both SQLite `tx_log` and fsynced JSON files under `tx/`. Pending upserts current metadata/token count, Git writes/commits the spec, then SQLite finalizes source_path/content_hash/body. Cleanup deletes the SQL transaction and renames its file to `tombstones/tx`. No transaction encompasses both media. File content fsync is present; parent-directory fsync is not.

Only `write_skill_locked`, batch writes and delete acquire `ms.lock`; `write_skill`/`write_skill_with_layer` do not. Batch acquires one lock then writes each skill individually, so it is not all-or-nothing. Default layer is Project. The layer is not in TxRecord payload.

`tx.rs:646–810` recovery reads incomplete SQL records first. Prepare writes roll back; Pending writes finalize if `GitArchive::skill_committed(id)` finds the skill in HEAD, otherwise roll back; Committed writes finalize. Recovery does not verify that HEAD content matches this transaction payload or commit identity. Existing skill HEAD presence can therefore falsely complete a failed update. Orphan/malformed filesystem records are tombstoned, not replayed into SQL. Complete SQL rows are excluded by the incomplete query, despite a defensive Complete branch.

`sqlite.rs:942–985` deliberately preserves source_path/hash/body on an existing pending upsert but replaces name/description/version/author/layer/metadata/token count. `rollback_tx` only deletes rows whose source_path is `pending`; it does not restore overwritten metadata of a prior committed record. Thus rollback is not full restoration of pre-update state. A failure between pending upsert and phase update can leave Prepare with an already changed row. Git worktree files from a failed commit are not reverted. These are upstream limitations, not guarantees to amplify in a port.

Delete (`tx.rs:479–525`) records intent, Git-tombstones/commits first, then deletes SQL. Prepare/Pending delete recovery checks working-tree `skill_exists`, unlike Pending write's HEAD check; failed Git commit after directory move can consequently be treated as successful deletion. Delete recovery suppresses SQL deletion errors and cleans transaction records anyway. Foreign keys may reject deletion when non-cascading dependents exist. `Database::delete_skill` itself is a single DELETE, not dependency-aware cascading cleanup.

`Database::integrity_check` only returns whether SQLite `PRAGMA integrity_check` yields `ok`; it does not compare Git, SQL hash, evidence or FTS. No cross-store repair/rebuild/import/export operation is defined in these storage files.

## Hash, provenance, migration, and transfer

`tx.rs:856–867` hashes compact `serde_json::to_string(SkillSpec)` UTF-8 with SHA-256, lowercase 64-character hex without prefix. It is not a content-only hash, sorted-key canonical JSON, YAML hash or SKILL.md hash. Field order and serde skip/default rules matter; optional context is omitted if empty, author/license serialize as null, empty capability/tag vectors remain. Other HashMap-bearing types need separate determinism review before claiming canonical hashing.

`sqlite.rs:29–47` records source_path/layer, git_remote/git_commit and content_hash. TxManager finalization only sets path/hash/body; it does not set git_commit to the returned archive commit OID. `skill_evidence` is keyed by (skill_id, rule_id) with EvidenceRef arrays and coverage snapshots. `get_evidence` recomputes coverage from refs, counting only stored nonempty rule arrays; it does not return the stored coverage snapshot. Archive write resets evidence.json to `{}` rather than exporting SQLite evidence. Consequently JSON export of only skills would lose provenance, usage and auxiliary state.

`migrations.rs` explicitly selects 12 files, uses PRAGMA user_version, applies execute_batch then separately updates the version, without an encompassing migration transaction. The unused `008_add_skill_feedback.sql` is not a thirteenth migration; selected feedback migration is `009_add_skill_feedback.sql`. A future user_version is not rejected and returns the constant 12. PRAGMAs enable WAL, NORMAL synchronous, foreign keys cache size −64000, mmap size 268435456 and in-memory temp storage (`sqlite.rs:1550`).

Storage read/write of a SkillSpec is not the current Registry JSON-list import/export format. `src/import/` classifies/parses source content and generates structured specs; bundle transfer is separate: `bundler/manifest.rs` declares BundleManifest, BundledSkill paths/hashes, dependency requirements and signatures; `bundler/package.rs` builds/verifies binary blob packages. Bundle SHA-256 uses prefixed hashes, distinct from transaction hashes. Semver in bundle dependency resolution does not imply SQL skill-version history.

## Faithful port interface and current Registry differences

Keep a dedicated structured spec model and `MetaSkillStore` with `upsert_record/get/list/delete`, `GitArchive.write_skill/read_skill/delete_skill/skill_committed`, `TxManager.write_skill_with_layer/write_skill_locked/write_skills_batch/delete_skill_locked/recover`, and a `RecoveryReport(rolled_back, completed, orphaned_files)`. Expose provenance methods separately. If implementing stronger atomicity, payload/HEAD equality, rollback backups, or full export, label those deliberate improvements rather than source parity.

Current `src/grasp_metaskills/registry.py` has immutable `(id, version)` documents, active selection, semver resolver, dependency guards, JSON list transfer and manually requested `skills.json` Git snapshots. Those are project extensions and do not substitute for the source protocol. Feedback/run/episode tables are also not the upstream storage schema. A facade may adapt callers while preserving explicit semantic boundaries.

## Evidence and license

The companion fixture identifies real upstream sample helpers/test expectations and separates source-derived expectations from executed checks. Executed locally: Python sqlite3 applied the exact 12 selected SQL migration files to an in-memory database; user_version=12, integrity_check=ok, 38 SQLite tables. Rust unit tests were read but not executed by this audit.

The fixed snapshot LICENSE is standard MIT, copyright (c) 2026 Jeffrey Emanuel; Cargo.toml declares MIT. No additional license/copyright/SPDX headers were found in the six audited Rust files or migrations, and the tracked tree contains no other filename matching LICENSE/NOTICE/third-party/vendor. Preserve the MIT copyright and permission notice when copying substantial code or fixtures. This scope found no excluded/non-MIT storage source. This is not a dependency license clearance: Cargo.lock libraries and the Git dependency `toon_rust` retain their own licenses, and copying third-party implementations/assets requires a separate audit. SkillMetadata.license is user-content metadata, not a relicensing grant.

## Implemented Python storage adapter and validation

`src/grasp_metaskills/metaskills_storage.py` provides a GitArchive and transaction coordinator against a callback protocol implemented by the single owning registry; the test-only in-memory Backend is a fault-injection harness. It accepts native SkillSpec dictionaries. Historical revision read is a deliberate convenience extension over upstream working-tree reads.

Safety extensions: snapshot the prior SQL projection before prepare; persist that undo payload in the transaction; recovery restores it even if the pending upsert succeeded before phase logging failed. Pending recovery requires exact spec-hash equality in HEAD plus a matching commit; if an OID was recorded it must be an ancestor of HEAD with the expected spec. It never completes solely because an unrelated old skill ID exists. Delete recovery checks committed-tree absence rather than the moved working tree, and propagates backend deletion errors. Locking uses POSIX flock (platform limitation), with batch still sequential rather than atomic. Orphan journals are quarantined/tombstoned rather than replayed.

Tests executed: `PYTHONPATH=grasp-metaskills/src grasp-metaskills/.venv/bin/python -m pytest -q grasp-metaskills/tests/unit/test_metaskills_storage.py` → **14 passed**. These cover archive roundtrip and historical read, upstream sample markdown, three write phase failure windows, restoration of existing metadata, rejection of the upstream HEAD-presence false-positive, committed delete recovery, orphan handling, and invalid IDs. The Rust suite was not executed. `ruff check` and formatting passed for the adapter and tests before the final added tests; pytest passed after those additions.

Adapter limitations to preserve in user-facing claims: metadata.yaml initially uses JSON syntax (valid YAML), spec JSON formatting is semantically compatible rather than a byte-for-byte clone of serde's pretty writer, directory entries are not fsynced, and arbitrary crash-corrupted JSON recovery should not be advertised as repaired automatically. Snapshot callbacks must return JSON-serializable state, and SQL callbacks must persist transaction payloads alongside phase updates. Commit identity/hash checks are integrity checks, not cryptographic authentication.

Follow-up hardening: shared `metaskills_spec.normalize_spec/spec_content_hash/render_skill_markdown` now own normalization, hashing and rendering; storage compatibility wrappers delegate to them. Git commits pass `--only` and explicit owned paths so unrelated staged files remain staged and absent from the new commit. Skill IDs use upstream `skill_path`'s Unicode alphanumeric/`-_.` allowlist and reject whitespace. Archive file and directory paths are resolved beneath the archive root before reads/writes, including existing file symlinks, and delete checks descendants before moving them. Scoped commit and resolved-path checks are explicit safety extensions over the source implementation. Metadata YAML remains JSON syntax, semantically valid YAML with different output bytes from serde_yaml.

Follow-up checks: storage unit pytest **25 passed**, ruff clean, mypy storage module clean. Tests added unrelated staged changes across write/delete, external file/directory symlink rejection, and identifier character validation.

## Production single-registry integration (supersedes early adapter proposal)

There is no MetaSkillStore or second authoritative registry. RegistryStorageMixin
implements the callback protocol on SkillRegistry's existing SQLite connection.
`versions/active` remains the only confirmed definition authority. Pending rows are
transaction payloads; archive_state contains only path/digest/layer provenance.
register_spec, ordinary register with Git, and JSON import use phased archives;
JSON batch import preflights and orders explicit dependencies before per-skill commits.
Original source-layer values are projected into searchable metadata and preserved
through finalize/recovery without changing native spec hashes. Changing only layer
gets an immutable local revision. Archive spec roundtrips contain no hidden layer
extension. Recovery after finalization uses confirmed archive-state layer.

Original PRAGMA cache_size is -64000 KiB (not 64*1024); the registry preserves it.
A busy timeout is a Python integration addition. Source schema is not reused as a
second database. Production crash/layer/migration integration tests pass, in addition
to algorithm/fault-injection unit tests; see verification.md for final suite totals.
