# MIT dependency mechanism audit

Audited snapshot: `meta_skill` commit `dcd3fb55cabb438dc200f9b7c784ca14c08135ce` (MIT). Implementation: `src/grasp_metaskills/metaskills_dependencies.py`. No later source was fetched.

## Actual mechanism and unified mapping

`src/core/dependencies.rs` defines capability dependency edges, four dependency load modes, five disclosure levels, load-plan entries, missing capabilities, and a resolved plan. Unified `Skill.metadata.requires` and `.provides` carry the original lists. These are capability names, not skill IDs or semver requirements. `resolve_dependencies` consumes existing unified `Skill` snapshots and returns value objects; there is no second registry or persisted skill model. `capability_edges` exposes the independent graph-building algorithm.

Every provider of a required capability is loaded. Edges exclude self dependencies, but a self-provided capability satisfies the requirement. Requirements and provider IDs are sorted; duplicates remain duplicates. BFS expands the closure up to 100 levels by default. The source silently truncates traversal at the maximum depth without emitting an issue; the port preserves this. Missing root IDs still yield root-only plans. Off mode returns immediately without indexing input.

Although one comment says Tarjan, actual cycle detection is DFS with a recursion stack and path extraction. A cycle returns the entire closure sorted by ID instead of a topological order. Source DFS iterates a Rust HashSet, so cycle rotation and sequence are unspecified; Python sorts starting nodes to stabilize reporting. Acyclic ordering follows the source's Kahn algorithm on dependent-to-prerequisite edges and reverses the final output. This means alphabetical ready ties appear reversed (two providers `a`, `b` return `b`, `a`, root), despite a source test comment suggesting otherwise. Auto and overview load dependencies at overview; full loads dependencies at full; the root retains the requested disclosure.

## Version and conflict scope

`src/core/skill.rs` stores a version string and declares environment predicate `VersionOp` (`eq`, `ne`, `lt`, `le`, `gt`, `ge`). Those declarations are not a skill semver constraint solver. `src/meta_skills/registry.rs` indexes tags and tech stacks and performs text/OR-tag/stack filtering. It has no version selection, semver conflict resolution, or dependency resolver. Therefore this port does not invent such behavior or interpret unified `SkillDependency.version`. Explicit ID/version dependency handling stays with the unified registry.

`src/core/resolution.rs` separately handles extends/includes composition: cycle detection over inheritance/include references, missing-parent errors and missing-include warnings, bounded deep-inheritance warnings, and content merging. It is implemented separately in `metaskills_composition.py` using pure native-spec dictionaries projected from the unified model by the caller. It returns transient results rather than storing another model or registry.

## Verification evidence

Red: `PYTHONPATH=src .venv/bin/python -m pytest tests/golden/test_metaskills_dependencies.py -q` failed collection with missing module before implementation. Golden cases correspond to the source tests `test_transitive_deps`, `test_missing_capability`, `test_detect_cycle`, and `test_resolve_no_deps`.

Rust source was actually executed using `rustc --edition=2021 --test`: copied `core/dependencies.rs` to `/tmp/metaskills-dependencies-source.rs`, removed serde import/derives/attributes, and substituted a minimal local `MsError::ValidationFailed` and Result alias. Algorithm and all original test bodies were unchanged. Result: **12 passed, 0 failed**. This is an isolated source harness, not a full upstream Cargo build or serde integration test. It emitted two harmless visibility/dead-field warnings from the stub.

Python golden/unit tests cover transitive dependencies, all providers, cycle and missing detection, disclosure, self providers, duplicate edges, depth truncation, source tie ordering, version-string noninterpretation, and malformed mapping rejection. Python validates list-of-string capability metadata because the unified metadata dictionary is less constrained than the Rust source's typed vectors.


## Composition port details

`resolve_extends(spec, specs_by_id)` and `resolve_full(spec, specs_by_id)` return `ResolvedSkillSpec`; `detect_inheritance_cycle`, `detect_full_cycle`, and `get_inheritance_chain` expose the original traversal rules. Input dictionaries are copied, preserving callers' snapshots. Source field names (`metadata`, `sections`, `blocks`, `block_type`, `includes`, `extends`) remain unchanged. The unified adapter must project current unified fields before calling; raw `Skill.metadata.metaskills_spec` is provenance rather than a second authority.

Merge semantics preserve unusual source behavior: metadata's nonempty child fields replace parent values; extends and replacement flags clear after merging; only child includes survive inheritance. Existing sections merge by ID with nonempty child titles taking precedence. Blocks group in text/rule/code/command/pitfall/checklist order. A replacement flag clears its block-type group on **each** child block, leaving only the final child block of that type. This is intentional fidelity, not a correction. New sections retain their child block order.

Includes resolve recursively, match target block types, optionally filter source sections by ID or title, prefix content, and prepend/append into a target section. Empty matches create no section. Missing includes warn and continue. More than three includes per target emit ManyIncludes; this reports volume, not a semantic conflict. Included-from tracks immediate include IDs (including repeats), not all nested sources. Parent warnings appear after a child's own depth warning. SectionShadowed is declared upstream but never emitted by the inspected merge algorithm.

Cycle checks consult the supplied repository exactly as upstream; callers should supply the root snapshot in the mapping to allow cycle discovery across a root reference. Missing inheritance-chain endpoints are included in `get_inheritance_chain`, while actual extends resolution errors on a missing parent. Warning variants use explicit `type` dictionaries in the transient Python result (rather than Rust serde's externally tagged representation). Error cases use ValueError with cycle/parent context.

Composition red was confirmed with missing module collection failure before implementation. Its source harness actually ran all **23 original resolution.rs tests: 23 passed, 0 failed**. To compile without fetching dependencies, storage repository implementations and serde derives/import were removed; local minimal cloneable structs/enums supplied the field and method surface used by the algorithm/tests. Algorithm bodies and original test bodies remained unchanged. This verifies the isolated resolution algorithms, not original SkillSpec serde/default/storage integration. Together the two Rust harnesses ran 35 source tests successfully.

Final Python verification: `PYTHONPATH=src .venv/bin/python -m pytest tests/golden/test_metaskills_dependencies.py tests/unit/test_metaskills_dependencies.py tests/golden/test_metaskills_composition.py tests/unit/test_metaskills_composition.py -q` → **25 passed**. These include source-case golden expectations and additional fidelity cases for replacement, metadata mapping, include filtering, warning order, and input immutability.
