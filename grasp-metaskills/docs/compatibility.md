# Compatibility and semantic differences

The pinned GraSP JavaScript core, not the paper or an auxiliary repository, is the
source baseline. Python uses structured exceptions instead of `{ok:false,reason}`
objects and Pydantic models instead of mutable untyped objects.

| Area | Preserved | Explicit difference |
|---|---|---|
| Predicates | Exact case-sensitive string equality, whole-word parameter binding | Recursive goal matching checks repeated variables/constants; single-pass substitution fixes upstream argument-name capture |
| Relevance | Backwards effect/precondition closure | Deterministic automatic goal planning can find prerequisites without a hand proposal |
| Edges | State/Data/Order distinctions, hard-cycle rejection, noncycling soft order hints | Real schema bindings are explicit named output references; unary predicate hints alone do not provide runtime data |
| Goal binding | Source's known-parameter goal normalization | No implicit interpretation of natural language as contract |
| Missing facts | Compatibility mode can retain a graph requiring runtime InsertPrereq | Strict compiler rejects missing facts by default |
| Retrieval | Jaccard, epsilon-smoothed distributions, memory mixture, JSD, confidence formula and threshold route | Routing confidence is advisory metadata; explicit goals use deterministic planning even at low confidence, with no fabricated ReAct execution |
| Execution | Scheduler owns states, stable idempotency keys, raw result persisted before verification | Independent ready nodes run concurrently; timeout/retry and durable recovery extended |
| Verification | Preconditions and effects must be observed | JSON Schema and custom validators added; no default effects manufactured from declarations |
| Repair | Actual five operator names and failure-specific order | Transactional revalidation, new version, affected-descendant invalidation and audit; parameterized Substitute can derive arguments from a fully binding effect |
| Versions | Not supplied by the GraSP core | Registry versions embedded in each graph node; immutable stored history |
| Source adapters | Manifest and simple explicit frontmatter | No DSH, host scope, UI/MCP or prose-to-contract inference |
| Storage | Serializable plans and episodes | New SQLite registry/state store, optional Git history |
| MetaSkills definitions | Historical MIT SkillSpec, capabilities, sections, composition | Unified immutable Skill and explicit GraSP extension fields |
| MetaSkills retrieval | Hash embedder, f32 RRF, filters, vector primitives, bandit/rewards | FTS5 replaces Tantivy; deterministic tie ordering; candidate aggregation is integration policy |
| MetaSkills storage | Per-skill archive files and phased journal protocol | New unified SQLite schema; safer rollback and exact Git commit matching; metadata JSON is valid YAML |
| MetaSkills versions | Native declaration retained as arbitrary string | Python local immutable revisions; PEP440 explicit dependency constraints are integration extensions |

Upstream `h` (neighborhood radius) and `pMax` (global replan) are declared parameters
but not enforced by its repairWith/operator code. This package does not invent a
radius algorithm or global replanner and claim it was ported. GraSP optimization
means its backward relevance filtering, not an invented optimal planner or generic
transitive reduction. The deterministic search is bounded and is not a complete
symbolic planner for arbitrary state changes, deletions or unbounded action loops.

Git and SQLite cannot be committed in a single cross-system atomic transaction;
the registry's actual ordering and error behavior are documented in its API.
JSON Schema compatibility is conservative and partial; runtime validation remains
authoritative for actual values.
