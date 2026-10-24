# MetaSkills recommendation audit

Source pinned to MIT commit `dcd3fb55cabb438dc200f9b7c784ca14c08135ce`. Only that checkout was read. The port is in `metaskills_recommendation.py`.

The source `suggestions/mod.rs` only reexports utilities; it does not define candidate skill sorting. This port therefore implements the actual source signal-learning algorithm without attributing a new Jaccard skill-ranking heuristic to MetaSkills.

* `suggestions/bandit/rewards.rs`: `compute_reward`, `compute_contextual_reward`, `aggregate_rewards`, `feedback_weight`, `legacy_reward_to_f32` are ported with f32 rounding at each arithmetic step. Duration, loaded, ignored, explicit, star rating, and task success/duration signals retain the source formulas. Source star values are u8 and are **not** clamped to 1–5: ratings outside that documented scale can yield rewards outside 0–1; the port preserves it.
* `types.rs`: all eight signal kinds, Beta(1,1) default prior, invalid-parameter fallback, decayed observations, posterior estimated probability, weight normalization, and zero-weight uniform fallback are ported. Arms retain successes, failures, estimated probability, UCB, last-selection timestamp and decay.
* `bandit.rs`: posterior Thompson samples, optional sequential context modifiers, normalization, total-selection increments, deterministic estimated weights, binary update and UCB bonus are ported. `exploration_factor` affects UCB bookkeeping; the original selection method samples Beta rather than consulting UCB. `min_observations` and `persist_frequency` are retained config fields but do not influence these source methods.
* `context.rs`: ordered context keys, multiplier-then-bonus adjustment, nonnegative clamp, observation count, learning step .05, and bonus clamp [-.5,.5] are ported.

The transport/storage `save/load` methods and suggestion cooldown/session tracking are outside this port's scope. The registry must persist explicit posterior/context state if cross-process learning is needed; an in-memory bandit must not be described as durable learning.

Python's injected `random.Random.betavariate` implements the same Beta sampling distribution but uses a different random algorithm/stream from Rust `rand_distr`; seeded draws are reproducible within this port, not bitwise comparable to Rust draws. Tests assert posterior formulas, sample support, normalized weights, deterministic estimated weights and a 10,000-sample Beta(8,2) mean. Iteration uses the original `SignalType::all` order.

An isolated offline Rust harness copied original `rewards.rs`, omitting only serde derives/import and the crate-bound legacy wrapper. Built with rustc 1.95.0, it printed `0.64`, `0.7744`, `0.87999994` for used(3), contextual used(3,.9,top), and aggregate(helpful,used(3)); successful tasks at 0/60/600 seconds printed `.9/.88/.7`. Golden tests match these Rust f32 values exactly. The aggregate value's last bit is deliberately preserved rather than rounding it to .88.

Validation: `PYTHONPATH=src .venv/bin/python -m pytest tests/golden/test_metaskills_recommendation.py tests/unit/test_metaskills_recommendation.py -q` (6 passing). Named original cases are recorded in the golden module.

## Runtime integration

Keep one `SignalBandit` instance attached to a registry/runtime lifecycle, with `SuggestionContext` captured when candidates are suggested. `select_weights(context)` supplies the eight learned signal weights. The caller may apply them to explicitly computed candidate signal features; candidate feature extraction/scoring belongs to that integration and is not implemented in these audited upstream files. `estimated_weights` offers stable diagnostic weights without sampling or incrementing selections.

After an executed node receives verified success/failure, call `update(signal, Reward.SUCCESS/FAILURE, captured_context)` for the signal(s) whose recommendation influenced selection; preserve this attribution in recommendation metadata. Task feedback can additionally be represented as `SkillFeedback('task_completed', success=..., duration_seconds=...)` and recorded through `compute_reward`. The upstream bandit update accepts a **binary Reward**, while the reward helpers return a numeric value. No threshold conversion is invented here: choose any numeric-to-binary mapping explicitly in an adapter and document it. Avoid treating failure of an unrelated execution dependency as evidence against every recommendation signal.

## Registry integration delivered

`SkillRegistry.recommend` now delegates to `registry_recommendation.recommend_skills`. The application's explicit extension combines reciprocal lexical/semantic candidate ranks and direct dependency relations using the source band's deterministic estimated signal weights; the previous Jaccard policy is removed. This extension is not attributed to an upstream candidate-ranking implementation.

`feedback_bandit(db)` replays existing SQLite `feedback` rows in id order. Only source signals named by `details.recommendation_signals` are updated; `details.recommendation_context` optionally supplies captured string context fields. Unattributed outcomes do not change every arm. Reopening the registry reconstructs exactly the same posterior and context modifiers, avoiding a second mutable state table. `task_feedback_reward(success, duration_seconds)` exposes the upstream numeric reward formula separately. Binary verification results remain binary for source bandit updates.

`registry.last_search_signals` captures the returned search candidates' actual lexical/semantic signal membership. The compiler snapshots that map in graph metadata immediately after discovery so later searches cannot overwrite attribution. Runtime feedback can copy the map entry for its skill into `details.recommendation_signals`.
