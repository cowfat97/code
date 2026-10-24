# Source-to-Python mapping

GraSP source revision: `e8eaf48522950a9148cb30b9672e1aeca0ba82e6`.
[Original core](https://github.com/luyu020816-droid/skill-dag/blob/e8eaf48522950a9148cb30b9672e1aeca0ba82e6/skill-dag/index.js).
Mappings concern that repository, an unofficial reproduction, not the paper or the
similarly named Ericbai06 project.

Classification: **P** source-derived port; **E** equivalent language adaptation;
**I** new integration behavior; **B** blocked/not implemented. Test names refer to
this distribution and must be interpreted with the limitations below.

| Upstream | Original file / function | Observed source behavior | Python implementation | Verification | Class |
|---|---|---|---|---|---|
| skill-dag | index.d.ts Skill/DagNode/DagEdge | string predicates, state/data/order, src/snk, args, repair budget | contracts.Skill/SkillNode/DependencyEdge/ExecutionGraph | unit/test_contracts.py; golden/test_grasp_compiler.py | E |
| skill-dag | index.js tokenize/tokenSim | lowercase ASCII tokens, stopword removal, Jaccard overlap | retrieval.py | golden/test_grasp_compiler.py | P |
| skill-dag | retrieve/kl/jsdScore/goalCover/route | direct and episode distributions with epsilon .001; lambda mixture; JSD agreement; sigmoid weighted confidence; eta history mixture; strict low/high thresholds | retrieval.py | golden/test_grasp_compiler.py confidence .4831/.9009 | P |
| skill-dag | parsePred/predArg/bindSkill | whole-word binding, exact predicates; unary predicate arguments create data hints (single-pass capture fix is an explicit Python extension) | compiler.py binding and edge inference | unit/test_compiler.py; golden/test_grasp_compiler.py | P/E |
| skill-dag | instantiate | explicit proposal filtering by skill id/arity; counted skill:id invocations | compiler.GraphCompiler | golden/test_grasp_compiler.py | E |
| skill-dag | backwardFilter | relevance closure from goal effects, remove unrelated nodes | compiler.py | golden/test_grasp_compiler.py apple excludes heat/slice | P |
| skill-dag | inferEdges | equal effect/precondition creates state edge; matching unary arg creates data hint; supplied order hints | compiler.py | golden/test_grasp_compiler.py exact state/data edge sets | P |
| skill-dag | topoOrder/hasCycle/reachable | Kahn order; reject hard cycle; add noncycling soft order constraints; src/snk structure | contracts.ExecutionGraph; compiler.GraphCompiler | unit/test_compiler.py; property/test_invariants.py | P/E |
| skill-dag | compileWith goal normalization | unbound goal parameter normalization; backwards filtering; completeness; structural source and sink | compiler.GraphCompiler | golden/test_grasp_compiler.py | P/E |
| skill-dag | compileWith missing facts | upstream can compile graphs with missing non-goal preconditions | compiler strict default plus explicit compatibility option | unit/test_compiler.py; golden/test_grasp_compiler.py | I (stricter default) |
| skill-dag | verifyStrict | before/initial must contain every precondition; after must contain every effect | verification.py | unit/test_runtime.py; unit/test_repair.py | P/E |
| skill-dag | verifySoft | optional LLM YES/NO postcondition relaxation | providers.LLMProvider protocol only; strict verification remains default | not implemented as automatic relaxation | B |
| skill-dag | BUILTIN_OPERATORS.Bypass | bypass only if downstream required effects already observed | repair.RepairEngine | unit/test_repair.py | P with safety extension |
| skill-dag | BUILTIN_OPERATORS.Rebind | same skill, new args, rebound preconditions/effects | repair.RepairEngine | unit/test_repair.py | P with revalidation |
| skill-dag | BUILTIN_OPERATORS.InsertPrereq | find predicate-name/arity producer, derive args, bounded new predecessor nodes/edges | repair.RepairEngine | golden/test_repair.py exact two added edges; unit/test_repair.py | P with stricter constant/unification and validation |
| skill-dag | BUILTIN_OPERATORS.Substitute | different skill covers downstream required effects | repair.RepairEngine | unit/test_repair.py; property/test_invariants.py | P with schema/dependency checks |
| skill-dag | BUILTIN_OPERATORS.Rewire | remove incoming order edge; never fake repair of a missing precondition | repair.RepairEngine | unit/test_repair.py | P with transactional validation |
| skill-dag | helperBag.downstreamReq/deriveArgs | effects needed by outgoing neighbors/sink; derive params from matching predicate | repair._downstream/_derive | unit/test_repair.py | P/E |
| skill-dag | DEFAULT_ORDER/repairWith | failure-specific operator order, decrement per-node budget, local-failed/local-exhausted | repair.DEFAULT_ORDER/RepairEngine | unit/test_repair.py | P/E |
| skill-dag | layoutNodes | deterministic x/y display positions | no UI coordinates | not applicable to harness-free runtime | B |
| skill-dag | NODE_TRANSITIONS/stableIdempotencyKey | scheduler-owned transitions, fixed per-plan/node/attempt key | runtime.py | golden/test_execution.py; integration/test_runtime.py | E |
| skill-dag | createExecutor/setNode/runNode | persist transitions and raw result before verifier; success/failure propagation | runtime.GraphRuntime | integration/test_runtime.py | E |
| skill-dag | createExecutor/run | first-ready serial schedule | runtime.GraphRuntime independent-ready concurrency | integration/test_runtime.py | I (parallel extension) |
| skill-dag | verifyNodeResult default | upstream defaults observed effects to declared expected effects on successful result | verification.py requires actual observed effects | integration/test_runtime.py verification failure | I (intentional stricter evidence) |
| skill-dag | cancel/resume | cancellation statuses; resume serial pending nodes | runtime.GraphRuntime cancellation and durable uncertain-outcome policy | integration/test_runtime.py | I (stronger recovery) |
| skill-dag | memoryStore/kvStore | ephemeral map or host-prefixed JSON KV | registry SQLite execution snapshots | unit/test_registry.py | I |
| skill-dag | manifestSource/frontmatterSource/parseFrontmatter/parseInlineArray | explicit grasp metadata; comma-aware inline arrays; skipped sources reported | adapters.py | golden/test_frontmatter.py | P/E |
| skill-dag | dshSkillsSource | DSH API, scope/TTL/cache, optional LLM contract inference | excluded; explicit metadata adapters only | not applicable | B |
| skill-dag | createProposer | explicit/retrieval/optional LLM proposals | providers.SkillProposer; compiler deterministic goal resolver | unit/test_compiler.py | I/E; no implicit model fallback |
| skill-dag | plugins/skill-dag-dsh/src | DSH/MCP/UI integration, display and host execution | excluded from package | package audit | B |
| meta_skill (MIT dcd3fb55) | core/skill.rs SkillSpec/SkillMetadata/SkillSection/SkillBlock | structured definition, capabilities, extends/includes; declared version is a string | metaskills_spec.py, unified Skill | golden/test_metaskills_spec.py; unit/test_spec_mapping.py | E |
| meta_skill | core/dependencies.rs DependencyGraph/resolve_dependencies | capability-to-every-provider edges, BFS closure, DFS cycles, reverse Kahn order and disclosure | metaskills_dependencies.py; compiler capability closure | golden/test_metaskills_dependencies.py; integration/test_compiler_capabilities.py | P/E |
| meta_skill | core/resolution.rs resolve_extends/resolve_full/merge_blocks | inheritance/include content merging, warnings, unusual repeated replacement behavior | metaskills_composition.py; registry.compose_spec | golden/test_metaskills_composition.py; integration/test_native_system.py | P/E |
| meta_skill | search/embeddings.rs HashEmbedder | Unicode tokenization, FNV-1a, salted token/bigram features, f32 accumulation and normalization | metaskills_search.HashEmbeddingProvider | golden/test_metaskills_search.py; actual Rust vector harness | P/E |
| meta_skill | search/embeddings.rs VectorIndex | dimension validation, insert/remove, dot-product ranking | metaskills_search.VectorIndex | unit/test_metaskills_search.py | P/E |
| meta_skill | search/hybrid.rs fuse_results/RrfConfig; search/context.rs SearchFilters | weighted k=60 RRF with f32 arithmetic; tag OR/layer/quality/deprecation filtering | metaskills_search.py; registry.search | golden/test_metaskills_search.py; integration/test_metaskills_search_registry.py | P/E |
| meta_skill | search/tantivy.rs | text indexing and BM25 lexical retrieval | registry SQLite FTS5 BM25 adapter; NOT Tantivy ranking equivalence | unit/test_registry.py; integration search tests | E with explicit engine difference |
| meta_skill | suggestions/bandit/{bandit,types,context,rewards}.rs | Beta/Thompson signal weights, decay, context modifiers and numeric feedback rewards | metaskills_recommendation.py; registry_recommendation.py | golden/test_metaskills_recommendation.py; persisted feedback integration | P/E |
| meta_skill | suggestions/mod.rs | module declarations, no complete skill candidate aggregation implementation | registry.recommend explicit integration policy uses source signal weights | integration/test_metaskills_search_registry.py | I, not invented source ranker |
| meta_skill | storage/sqlite.rs; migrations.rs | current skill record, pending state; WAL/NORMAL/cache pragmas; twelve migrations | unified versions/active + pending/archive projection; retained pragmas, new schema | real migration harness; golden fixture; registry tests | E/I; not binary database compatible |
| meta_skill | storage/git.rs GitArchive/write_skill/read_skill/history | per-skill by-id structured spec, rendered markdown and auxiliary files, path commits | metaskills_storage.GitArchive | golden/fixtures/metaskills_storage.json; unit/test_metaskills_storage.py | P/E; JSON is valid metadata YAML |
| meta_skill | storage/tx.rs TxManager/TxPhase/GlobalLock/recover | prepare, pending DB, Git, finalize DB, journal cleanup, recovery | metaskills_storage.TxManager + registry_storage single-registry backend | unit/test_metaskills_storage.py; integration/test_registry_archive.py | P/E with rollback/hash/OID safety corrections |
| meta_skill | cli/commands/index.rs compute_spec_hash | SHA256 of normalized compact SkillSpec JSON | metaskills_spec.spec_content_hash | golden spec/storage fixtures | E; unknown extension preservation is I |
| meta_skill | meta_skills/registry.rs | separate meta-skill slice-bundle tag/tech-stack registry | not duplicated as a second Registry; ordinary unified search supports tags | audited, slice bundle workflow excluded | B |
| integration | no upstream equivalent | immutable native update revisions, source-layer query projection, archived import, capability DAG integration, retrieval attribution into runtime feedback | registry_storage/registry/compiler/runtime | integration/test_native_system.py | I |
| integration | no upstream equivalent | JSON Schema contracts, version snapshots, SQLite feedback, named bindings, bounded transactional patches, partial-result reuse | contracts/compiler/registry/runtime/repair | unit/integration/property tests | I |

## Audit inventory and dependency boundary

GraSP repository: `skill-dag/index.js` is the dependency-free CommonJS core,
`index.d.ts` its public declarations, `test/{verify,integration-real-skills,
stage-a-persistence,stage-b-executor}.js` its executable tests. `plugins/skill-dag-dsh`
contains TypeScript client/server host integration and built JavaScript artifacts;
`scripts/demo-svg.mjs` and `docs/` concern demonstrations/research. Core package.json
has no dependencies and requires Node >=18. No JS is shipped by this Python package.

GraSP's predicates are exact strings, not a semantic type system with JSON Schema.
The source's data edges are argument hints, not named output bindings. JSON Schema,
explicit named bindings, version compatibility and recursive goal planning are
extensions and are never attributed to a different SkillDAG project.

MetaSkills audit uses only standard-MIT historical commit
`dcd3fb55cabb438dc200f9b7c784ca14c08135ce`. The later rider revision is
excluded. `src/lib.rs` exposes modules for core, storage, search, suggestions,
meta_skills, CLI/app, import/sync, TUI, auth/security, bundling, quality/testing,
agent/host integration and utilities. `core/skill.rs` defines SkillSpec;
`storage/mod.rs` publicly reexports Database/SkillRecord, GitArchive, TxManager and
TombstoneManager. Search depends on storage records plus Tantivy/vector engines;
CLI/app orchestrates them. Python replaces these boundary types with projections
of one Skill and one SQLite registry; it does not invoke the upstream CLI.
Detailed algorithm, tests and differences are in `metaskills-*-audit.md`.
The broad CLI/UI/host/sync/mining/simulation surface is excluded, not claimed as
ported. No auxiliary repository supplies missing primary-source algorithms.

Additional compatibility fix: upstream bindSkill applies substitutions sequentially, so args named like later parameters may be captured. Python binds all formal parameters in a single regex pass; test_binding_does_not_capture_other_parameter_names records this intentional correction.
