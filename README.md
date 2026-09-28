# interconnected_beta

Lock states + Keys → a governed **Decision** with narrative — the third
stage of the pipeline: `alpha` detects Keys, `zeta` evaluates Locks,
`beta` decides, and explains why.

## Why this exists

Same extraction discipline as `zeta` and `alpha`, but beta's story has
two parts, not one.

### Part 1: extracted (the verdict shape, reinvented three times)

`FusedVerdict` is defined near-identically three times in the source,
for three unrelated domains, none importing from the others:

| Domain | File | Notable extra field |
|---|---|---|
| Clinical/pediatric | `observe_consolidated.py:82-97` | `decision_fingerprint` |
| Driving safety | `drive_safety_module.py:89-99` | (the minimal base shape) |
| Ascent/altitude compute | `ascent_compute_module.py:102-113` | `reserve_factor` |

All three share: `risk_score`, `regime`, `confidence`, `entropy`,
`active_engines`, `triggered_rules`, `timestamp`, `audit_hash`,
`escalation_required`. `beta.Decision` generalizes that shared core —
adapted from a risk-score model to zeta's Lock-based model (see field
mapping in `beta/verdict.py`'s docstring) — instead of leaving three
domains to keep maintaining separate near-copies.

Also extracted, verbatim: `decision_fingerprint` (`observe_consolidated.py:
236-244`) — a reproducible, wall-clock-free SHA256 of a decision's own
inputs, deliberately distinct from `audit_hash` (the ledger's chained,
tamper-evident hash, which needs ledger state that only exists once
something is recorded — `interconnected_delta`'s job, not beta's).

Also extended: `PERCEIVE`'s `ConsensusEngine.evaluate` geometric-mean
confidence (`perceive_consolidated.py:502`) — beta averages the
confidence of whichever Keys actually triggered the matched rule's
`open_locks`. One deliberate deviation from the source, not an
extraction: `ConsensusEngine` returns `0.0` when there's nothing to
average ("no gates evaluated" is an error there). Beta returns `1.0`
instead, because a rule can legitimately match on the *absence* of
danger Keys alone (all requirements in `closed_locks`, nothing in
`open_locks`) — that's a clean match, not "no confidence in anything."

### Part 2: new (the narrative — not present anywhere in the source)

`reasoning`, `reversal_conditions`, `instructions` were searched for
across `observe_consolidated.py`, `perceive_consolidated.py`,
`drive_safety_module.py`, and `ascent_compute_module.py`. None of the
four has anything resembling them. This is the actual gap this whole
project set out to close — a governed decision that can explain *why*
it was made, *what would change it*, and *what should happen next* —
not something being generalized from existing code.

## Design choices worth knowing about

- **Declarative rules, not callables.** `DecisionRule` is two sets of
  lock names (`open_locks`, `closed_locks`), not a Python predicate —
  same tradeoff `zeta.LockSpec` made with `AND`/`OR`/`N_OF_M` instead of
  arbitrary boolean expressions. A rule can be printed and audited
  without executing code.
- **Fail closed on unevaluated locks.** A rule requiring a lock to be
  open (or closed) that was never evaluated does **not** match — an
  unknown state is neither confirmed-open nor confirmed-closed. Matches
  the fail-closed posture already used elsewhere in this system (e.g.
  `sentinel_os`'s cassette loader).
- **Ambiguity is an error, not a coin flip.** If more than one rule
  matches at the same (highest) priority, `DecisionEngine.decide()`
  raises `AmbiguousRuleError` rather than picking one arbitrarily.

## API

```python
from datetime import datetime
from zeta import Combination, LockEvaluator, LockRegistry, LockSpec
from beta import DecisionEngine, DecisionRule, DecisionRuleRegistry

lock_registry = LockRegistry([
    LockSpec(lock_id="sepsis_lock",
             required_keys=("septic_shock", "respiratory_distress"),
             combination=Combination.OR, dwell_threshold=1, force=True),
])
decision_registry = DecisionRuleRegistry([
    DecisionRule(
        decision_id="escalate_sepsis", decision="ESCALATE",
        open_locks=("sepsis_lock",), priority=10,
        reasoning_template="{decision}: {open_locks} open",
        reversal_conditions=("sepsis_lock closes",),
        instructions="Go to emergency room immediately.",
    ),
])

lock_evaluator = LockEvaluator(lock_registry)
decision_engine = DecisionEngine(decision_registry, lock_registry)

keys = ...  # a zeta.KeySet, e.g. from alpha.observe(vitals)
lock_results = lock_evaluator.evaluate_all("patient_1", keys, datetime.now())
decision = decision_engine.decide("patient_1", keys, lock_results, datetime.now())

print(decision.decision, decision.reasoning, decision.instructions)
```

See `examples/pediatric_discharge.py` for the full alpha → zeta → beta
pipeline on a realistic timeline.

## Where this fits

```
interconnected_alpha  -- raw vitals -> named Keys
interconnected_zeta   -- Keys -> Locks -> open/closed decisions
interconnected_beta   -- (this repo) Lock states -> a Decision + narrative
interconnected_delta  -- records the decision, tracks execution, verifies outcome
```

## Tests

```
pip install -e ".[dev]"
pytest
```

30 tests. Depends only on `zeta` — no other external packages.
