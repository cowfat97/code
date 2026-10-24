# Actual verification record

Date: 2026-10-21. Python 3.12.13, pytest 9.1.1, Ruff 0.17.1, mypy 2.4.0.
No tests were deleted or marked xfail/skip to obtain passing results.

## Python suite

The final suite contains **181 collected test cases**: unit 90, integration 59,
Golden 28, property directory 4. Two further Hypothesis tests live in integration,
so six test functions generate property trials. No tests were deleted/skipped/xfail.

| Required invariant | Evidence |
|---|---|
| Compiled DAG is acyclic; references valid | generated compilation/topological/reference assertions |
| Missing preconditions prevent execution | integration/test_runtime.py generated facts |
| Repair cannot introduce invalid dependencies | generated invalid replacement; capability/schema/version rejection |
| Unaffected valid results reusable | generated branch retention and real native Substitute/recovery |
| Versions remain fixed | generated registry updates, execution-time updates, native same-declaration revisions |
| Recovery preserves confirmed results | generated resume, SQLite close/reopen, raw-result recovery, native archive crashes |

Commands actually run against editable installation outside the sync folder,
without PYTHONPATH:

```bash
/tmp/grasp-metaskills-install-verify/bin/python -m pip install -e '.[dev]'
/tmp/grasp-metaskills-install-verify/bin/python -m pytest -q
.venv/bin/ruff check src tests examples
.venv/bin/python -m mypy src/grasp_metaskills
```

Results: `181 passed`; `All checks passed!`;
`Success: no issues found in 18 source files`.

Generated examples run inside Hypothesis are additional trials, not counted as
separate pytest test cases. UUIDs and timestamps are compared structurally, not
byte-for-byte. Retrieval floating points are compared to the original four decimal
expectations; edges and operator patch shape are exact.

## End-to-end scenarios

`tests/integration/test_system.py` runs actual registry/compiler/runtime/repair paths:
multiple-skill composition, candidate backtracking, barrier-verified parallelism,
missing preconditions, Schema conflict, executor failure/retry, input/output/effect
verification failure, successful Substitute with retained independent results,
failed bounded repair with audit, SQLite close/reopen, version update during execution,
registry FTS result influencing compilation, InsertPrereq, timeout with/without
idempotence, cancellation and uncertain-outcome recovery. Tests additionally verify
required custom rules, stale input cache invalidation, same-key external action
recovery and verification-only recovery of a persisted raw result.

## Upstream baseline

The pinned MIT GraSP repository's actual scripts were executed with Node v26.10.0:

- `node test/verify.js`: all checks passed; apple state/data edges, InsertPrereq,
  lMax=0, hallucination guard, frontmatter commas and confidence .4831/.9009.
- `node test/stage-b-executor.js`: serial chain, failure blocking, immutable success,
  stable attempt keys and persistence checks passed.
- `node test/integration-real-skills.js`: shared predicate chain and repair checks passed.
- `node test/stage-a-persistence.js`: inference-cache and explicit metadata checks passed.

Python Golden Tests are extracted from verify.js and stage-b-executor.js. The
host-specific LLM inference-cache adapter tested by stage A is excluded, not falsely
counted as a Python port. Historical MIT MetaSkills source was actually executed in isolated Rust harnesses:

- original core/dependencies.rs algorithm/test bodies: **12 passed**;
- original core/resolution.rs algorithm/test bodies: **23 passed**;
- original hash embedder functions: four vectors frozen in Golden Tests, exact f32 bits;
- original reward functions: .64/.7744/.87999994 and .9/.88/.7 source results.

Serde derives/crate storage boundaries were replaced with minimal boundary structs
for standalone rustc compilation. This is not a full Cargo build or original serde/
storage integration claim. Source scripts/binaries were audit artifacts under /tmp,
not Python runtime dependencies. Actual twelve original SQLite migrations were also
executed: user_version=12, integrity_check=ok. Detailed methods and source-case names
are in metaskills-*-audit.md. The later rider revision was not used.

## Installation, distribution and example

Actually ran:

```bash
python -m pip install -e '.[dev]'
python examples/offline.py
UV_CACHE_DIR=/tmp/grasp-metaskills-uv-cache uv build --python .venv/bin/python --no-build-isolation
```

Editable installation succeeded with normal build isolation. The generic arithmetic
example returned `status: succeeded`, emit value 3, scale value 6, and 18 trace events.
An earlier no-build-isolation editable attempt failed because optional backend
`editables` was absent; normal pip isolation resolved it. This was not hidden as a
successful install.

The workspace is in a synced macOS folder. Its local .venv .pth files repeatedly
acquired UF_HIDDEN, and Python skipped those files. A fresh environment outside the
sync folder was therefore created at /tmp/grasp-metaskills-install-verify; standard
editable installation, imports, example and the whole suite passed there. README
places the user's environment outside sync folders for the same reason.

Both sdist and pure-Python wheel are built. Archive checks confirm MIT/NOTICE files,
Python source and py.typed; sdist includes source mappings, limitations, example and
tests. No JS/Rust source or executables are included in the wheel. Optional Git
archive/history is the only subprocess capability in library source; it runs when
Git storage is explicitly configured or its history methods are called. Default skill execution is an injected Python protocol.

## Review and source integrity

Independent read-only review identified parameter capture, incomplete replacement
input checks, bare version parsing, unknown-attempt key reuse and blocked recovery.
Regression tests were observed failing, then fixed and rerun. Further tests cover
actual cancellation and exact original two-edge InsertPrereq shape. No project
commit/push was made. Source/test hashes are in source-checksums.txt; repository
changes are described in change-record.md. Distribution checksums are in dist/SHA256SUMS.

## Final integrated review

Independent source-aware review reproduced three new cross-module issues: digest
lexical ordering could select an older native revision; layer was lost between
pending/finalization/filtering; JSON import bypassed Git transactions. Regression
tests now cover all three, layer-schema migration, finalized-phase recovery and
archived dependency-order import/deletion. Native end-to-end tests additionally
exercise immutable historical snapshots, real execution failure, local substitution
with retained provider results, persisted recommendation signal attribution, source
bandit replay and hybrid discovery directly entering graph compilation.

A restricted-network pip attempt initially failed fetching build dependencies. The
normal network-enabled retry succeeded. UV used an explicit /tmp cache because the
default user cache is outside workspace permissions. These environment failures
were resolved without weakening tests or installation requirements.

Final wheel installation is additionally tested using pip --no-deps --target into
`/tmp/grasp-metaskills-wheel-final`, with PYTHONPATH pointing to that installed
wheel tree ahead of editable source. The full 181-test suite passes against that
installed wheel. Wheel and sdist contain both original MIT grants and NOTICE;
no .js/.ts/.rs/.so/.dylib/.exe package payload is present. The example succeeds
against installed code. Final source and artifact hashes are regenerated below.
