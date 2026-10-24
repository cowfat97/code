# Public Python API

All contracts, protocols, errors and primary classes are re-exported from
`grasp_metaskills`. The executable offline example is the smallest full dataflow.

## Registry

`SkillRegistry(path=':memory:', embedding_provider=HashEmbeddingProvider(), git_path=None)` supports
context management. `register(Skill)` creates a definition or switches the active
pointer to an existing immutable version. To update, register a **new version**;
re-registering different contents with an existing version is an error. A supplied
content hash must match the whole canonical definition (excluding the hash field).
When constructing a changed copy, clear the old hash with `content_hash=''`.

- `get(id, version=None)`, `resolve(id, requirement='*')`, `list()`, `history(id)`.
- `delete(id)` hides active/search data, retains history and rejects active dependents.
- `dependencies(id, version=None, recursive=False)`, `dependents(id)`.
- `search(query, mode='keyword', limit=20, filters=None)` returns SearchResult objects.
- `recommend(id, limit=10)` applies learned source signal weights to lexical/semantic ranks and dependency features (integration policy).
- `export_json(include_history=False)` / `import_json(text)` (SQLite atomic; optional archive import uses preflight + per-skill transactions).
- `record_feedback(...)`, `feedback(id, version=None)`; `record_episode(...)`, `episodes()`.
- `save_run(id, graph_dict, state_dict)`, `load_run(id)`, `run_history(id)`.
- Explicit `commit_git(message)` / `git_history()` when git_path is configured.

Native interchange:

- `register_spec(spec, layer='project', contract=None)` accepts native structured JSON.
- `get_spec(id, version=None)` / `export_spec(id, version=None)` project the live definition.
- `resolve_spec(id, requirement='*')`, `compose_spec(id)` resolve versions/composition.
- `capability_dependencies(id)` returns the source dependency/disclosure plan.
- `git_archive.history(id)` / `.read_skill(id, revision=None)` inspect per-skill history.
- `tx_manager.recover()` is explicit; initialization also performs recovery.

The default embedding provider is the real source hash feature algorithm, not a
trained neural model. Pass a provider to replace it or explicit None to disable
semantic/hybrid search. SearchFilters exposes source tag/layer/quality/deprecation
rules; ordinary dictionary filters support metadata fields.

Native definitions without an explicit source use stable metaskills://skills/<id>
origins in graph snapshots; this implicit origin does not alter native export JSON.
Native declared versions need not be PEP440 or immutable. Python maps changed
same-version specs to local hash revisions and retains the native declaration.
Explicit `register(Skill)` still enforces immutable Python version definitions.

## Compile

`await GraphCompiler(registry, proposer=None, strict_preconditions=True, discovery_mode="keyword").compile(`
`goal=[...], task='', proposal=None, initial_conditions=None, order_hints=None, inputs=None)`.

Goal predicates determine success; task text ranks candidates. Proposal items contain
`skill`, `args`, and optional exact `version`; an explicit invalid item is reported
under graph.metadata.rejected. Missing goals, hard cycles, invalid references,
missing preconditions and incompatible/ambiguous typed inputs raise CompilationError.
The source-compatible strict_preconditions=False mode exposes missing facts in graph
metadata for runtime checking/repair. `inputs` maps node IDs to literal input dicts.

Graph snapshots include immutable stored versions/source/hash, concrete args and
predicates, explicit bindings, edges, initial facts, goal and metadata. Serialize with
`model_dump_json()`, restore with `ExecutionGraph.model_validate_json(text)`.

## Execute and verify

`GraphRuntime(registry, executor, verifier=None, repair_engine=None, concurrency=4,`
`retries=0, timeout=30)` provides `await execute(graph, state=None)`,
`await resume(graph_id, retry_unknown=False)`, and synchronous `cancel(graph_id)`.
The returned GraphState includes node status/result/verdict/attempt/key, observed
facts, trace, graph version, repair counters and audit. Snapshots remain in SQLite.
All skill versions in an externally supplied graph must exist in this registry.

SkillExecutor.execute receives `(node, inputs, context)` and returns NodeResult.
Results are persisted before verification. Strict fact/Schema checks run first.
An injected SkillVerifier.verify receives `(node, inputs, result, context)` and returns
VerificationResult; it cannot override a failed built-in input/output/fact check.
The executor/verifier receives copies, so it cannot mutate scheduler-owned snapshots.
Input schemas validate actual values; output schemas validate actual returned data.
No declared effect becomes a confirmed fact without an observed result.

## Repair

`RepairEngine(registry, l_max=3, e_max=5, max_repairs=8, operator_order=None)` implements
sync `repair(graph,state,RepairEvent)` candidate selection and
`apply(graph,state,RepairOperation)` for explicit operations. Invalid explicit patches
raise RepairError and leave inputs unchanged. RepairResult contains repaired/reason,
new graph, new state, and the selected operation. Callers using explicit repair must
continue with the returned graph/state pair. GraphRuntime integrates this automatically.
Per-node budgets are set on SkillNode.repair_budget. Empty operator_order disables
operators. A repair increments graph version, invalidates changed roots/descendants,
retains independent results, and audits success/rejection/exhaustion.
