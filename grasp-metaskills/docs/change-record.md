# Repository change record

Added one standalone project directory: `grasp-metaskills/`. Existing application
code and personal Vault notes were not modified. The MIT GraSP and historical MIT MetaSkills audit checkouts are
retained alongside the project; the later restricted revision was excluded. Neither checkout is part of the Python distribution.

No project Git commit, push, deployment or remote repository was created. Automated
Git-history tests make commits only in isolated pytest temporary repositories.

New code: contracts, compiler, retrieval, registry, runtime, verification, repair,
explicit metadata adapters, provider protocols, public exports and py.typed marker.
New tests: unit, whole-system integration, upstream GraSP Golden and Hypothesis
invariants. New artifacts: pyproject.toml, README, offline example, source mapping,
architecture/API/compatibility/license/limitations/verification documents and MIT
license/NOTICE files.

Independent review found and regression tests reproduced issues in parameter capture,
replacement required inputs, exact version matching, unknown-outcome idempotency,
blocked-descendant recovery and cancellation. These were corrected before final
validation. InsertPrereq's original two-edge patch was checked by a Golden Test.
Comments/docstrings explain provenance, trusted capability boundaries, one-pass
binding, uncertain side-effect recovery and conservative cache invalidation.

## Historical MIT MetaSkills integration (supersedes initial blocker notes)

License history found standard-MIT commit dcd3fb55, immediately before the rider.
That source checkout is now retained alongside GraSP; later restricted source is
excluded. Added source-derived spec mapping, capability resolver, content composition,
hash/vector/RRF/filter algorithms, bandit/rewards and per-skill Git transaction
protocol. The production SkillRegistry inherits its single-store archive adapter;
its compiler/runtime/repair now use these same definitions and feedback.

Independent integration review reproduced and fixed native hash revision rollback,
layer projection loss and JSON import bypassing Git. Added native registration,
source discovery, capability compilation, version pinning, real executor failure,
Substitute reuse, persistent feedback/bandit and recovery integration regressions.
Documentation and NOTICE now identify both actual compatible source revisions.
