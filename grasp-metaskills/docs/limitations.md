# Scope, differences and unimplemented features

## Source/revision boundary

This is a source-derived port of selected actual core mechanisms from the pinned
GraSP MIT source and **historical** MetaSkills MIT `dcd3fb55`. It is not the complete
MetaSkills application, nor compatible with its later restricted revisions. Source
maps identify each port, adaptation and integration extension. The full Rust crate
was not built or tested; isolated original Rust algorithm harnesses were executed.
No auxiliary repository substitutes for the primary source.

## GraSP

The source is itself an unofficial reproduction, not the original paper's official
implementation. Predicates are positive exact string facts; there is no delete-effect
calculus, probabilistic planning or optimality guarantee. The source's optimization
is backward relevance filtering. Declared h/pMax parameters are not implemented in
the source repair operators; Python does not invent a global replanner/radius port.
The deterministic goal resolver and JSON Schema contracts are integration additions.
It does not backtrack after a later schema-binding failure. Ambiguous bindings or
unbound parameters require explicit caller inputs/proposals.

DSH/host skill scopes, MCP/UI, display layout and optional prose-to-contract LLM
inference are excluded. Soft LLM YES/NO verification relaxation is not automatically
implemented. Custom provider/verifier implementations belong to callers. Unsupported
source verifier prose is preserved as metadata, not made executable. Executors are
trusted injected capabilities; this library is not a process sandbox.

## MetaSkills

The historical native SkillSpec, capability dependency loading, inheritance/includes,
hash embedding, vector operations, f32 RRF, search filters, bandit/rewards and
SQLite/Git journal mechanisms are implemented with explicit compatibility mappings.
The broader app remains excluded: TUI/CLI command parity, agent detection/mail,
CASS/beads/CM host integrations, auth/updater, remote sync, conflict/tombstone/purge
workflows, mining/dedup, quality/lint/testing simulations, slice-bundle packaging and
meta-skill TOML parsing/tech-stack indexes. These are not empty stubs in the package.
Some exceed the requested harness-free core or concern separate application flows;
they are not claimed complete by this delivery.

SQLite FTS5 replaces Tantivy: tokenization/BM25 and scores are not byte-equivalent.
The source hash embedder is a deterministic untrained feature map, not neural semantic
understanding. No cloud API is required. A custom EmbeddingProvider can replace it.
The inspected upstream local ONNX provider was itself unimplemented; no model asset
or fabricated neural output is provided. SearchContext has fields but the inspected
source did not implement personalization boosts. Source signal bandit/rewards are
ported; the skill-candidate aggregation policy is explicitly new integration logic.
Random streams and unordered Rust hash-map ties are compared statistically or by
sets/ranking constraints, not fixed-byte identity.

The SQLite schema intentionally unifies immutable Python skill versions, runs,
feedback and transactional source projections. It is not a drop-in reader for an
existing upstream .db. Use native SkillSpec JSON interchange. Source mutable version
strings map to immutable Python local revisions; explicit dependency constraints use
PEP440 as an integration extension. Global JSON snapshots are additional exports,
not native archive formats. Git metadata.yaml contains JSON (valid YAML), avoiding
an unnecessary YAML parser. Unknown JSON extension fields survive interchange.
Source rollback/HEAD-evidence bugs are intentionally corrected, documented in the
storage audit, and covered by crash recovery tests. Original schema migrations were
executed as audit evidence, not used as this package's schema.

## Runtime and durability

Results are cached within graph/run history and after local repair, not globally
across unrelated runs. A patch conservatively invalidates affected descendants while
preserving other verified results. Embeddings are computed on search; no persistent
ANN/vector cache is claimed. SQLite feedback persists bandit learning by replay.

Persistence/idempotency keys do not guarantee exactly-once external effects. A
non-idempotent timeout/cancel may have an unknown outcome, requiring explicit
resume(retry_unknown=True) or host reconciliation. Running-node recovery retains
the attempt key. Verification cancellation retains raw output for verification-only
recovery. Callers must enforce external idempotency. There is a same-runtime graph
execution guard, but no distributed cross-process run lease.

Git and SQLite use recoverable phased transactions, not a shared atomic commit.
Archive batch import preflights constraints but commits per skill; a later I/O failure
can leave earlier skills confirmed and the failing skill recoverable. Recovery uses
an exclusive POSIX flock. Windows lock portability is not implemented or tested.
Git is optional; when enabled it requires the system git executable. Standard SQLite
requires FTS5. Pydantic/jsonschema dependencies can ship compiled wheels; running the
Python package requires no JS runtime, Rust toolchain or Rust subprocess.

## Evidence

All Python tests, lint, strict typing, editable installation, wheel/sdist build and
examples are actually run as recorded in verification.md. No test is removed,
skipped or xfailed to obtain a passing result. Source Rust harnesses isolate specific
algorithms using small serde/storage boundary substitutes; their success does not
claim full Cargo integration equivalence. No push/deployment/remote repository has
been created. File modification and source revision records accompany the project.
