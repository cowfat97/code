# Architecture

One Python package shares `contracts.Skill`, one `SkillRegistry`, and one set of
immutable skill definitions. `SkillSpec` is an interchange value object, not a
second registry. Native sections and unknown fields are preserved in provenance;
`spec_from_skill` projects live metadata before export/composition. Explicit
`grasp_contract`, `grasp_dependencies`, `grasp_content`, `grasp_metadata` and
`grasp_source` extension fields bridge source formats without treating prose or
capability names as verified predicates.

SQLite `versions/active` confirms definitions. Native source versions may repeat;
changed content receives an addressable local `+ms.<digest>` revision while the
original declared version roundtrips unchanged. Resolution selects the highest
compatible public version and active/latest confirmed native revision, never hash
lexical order. Graph nodes deep-copy exact versions, source and content hash.
The source layer is query provenance; it does not alter native spec serialization.

Task text enters registry discovery. Source hash embeddings, RRF and filters work
locally; SQLite FTS5 adapts Tantivy lexical search. Candidate order feeds GraSP
retrieval and deterministic backwards goal resolution. The compiler applies source
backward filtering/binding/State-Data-Order inference, then expands native capability
requires/provides to all providers and explicit ID/version dependencies. These
lists are authoritative only in each Skill snapshot; graph edges are projections.
Capability names never become runtime facts. JSON Schema checks and automatic
named input bindings are integration extensions.

The async runtime schedules independent ready nodes, binds actual inputs, validates
schemas/preconditions/effects and persists raw results before custom verification.
Only observed effects become confirmed facts. Host capabilities are injected through
SkillExecutor/SkillVerifier; no skill text is handed to shell. LLMProvider,
EmbeddingProvider and SkillProposer are replaceable protocols. Runtime feedback
stores pinned skill/version, graph/version and captured retrieval signals. Source
bandit posteriors replay those SQLite feedback rows; candidate score aggregation is
an explicitly new policy.

Repair uses the actual source Bypass/Rebind/InsertPrereq/Substitute/Rewire operators.
Patches operate on copies, recheck DAG/type/predicate/version/capability dependencies,
then increment graph version and invalidate changed roots and descendants in old
and new graphs. Other verified results survive. Budgets, rejected patches and
accepted operations are durable audit records.

Optional Git history uses native per-skill archives and TxManager journals. Pending
specs do not replace confirmed SQLite versions. Commit and finalization are separate
phases; reopen reconciles exact content/commit evidence or rolls back pending data.
This is recoverable coordination, not a cross-store atomic transaction. JSON batch
import preflights all definitions, then archives dependency-first per skill. A failed
Git batch can have earlier confirmed items, as source batch transactions do.
`commit_git` additionally exposes an explicit whole-registry JSON snapshot extension.

See source-mapping.md, compatibility.md, limitations.md and the detailed historical
MetaSkills audit documents for exact source boundaries.
