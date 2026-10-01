# interconnected_beta (β)

Lock states + Keys → a governed **Decision with narrative**. Version `0.1.0`. Depends on [`interconnected_zeta`](https://github.com/wking53214/interconnected_zeta). Python ≥ 3.9.

## 1. Pipeline Position & Role

**DECISION.** Third stage of the extracted spine.

```text
α Alpha (Keys) → ζ Zeta (Locks) → β Beta (this repo) → δ Delta (custody)
```

**Policy approval is not authorization.** This layer produces a decision and an explanation. It does not issue human authority to execute.

## 2. Full System Scope & Architectural Depth

Two parts: extracted verdict shape, and a narrative layer that **does not exist in the source**.

### Extracted (verdict shape, reinvented three times)

`FusedVerdict` appears near-identically in three modules of the source codebase. Shared fields: `risk_score`, `regime`, `confidence`, `entropy`, `active_engines`, `triggered_rules`, `timestamp`, `audit_hash`, `escalation_required`.

`beta.Decision` does **not** reproduce all nine:

| Source field | β treatment |
|---|---|
| `confidence`, `timestamp` | Kept |
| `audit_hash` | Distinct from `decision_fingerprint`. Audit hash is a ledger concern (δ). |
| `risk_score` + `regime` | Collapsed into free-form `decision: str`. Simplification, not a lossless rename. No 4-level ordinal. |
| `triggered_rules` | Rough analogue: `triggered_by_keys` / `triggered_by_locks` (bare names, not full messages) |
| `escalation_required` | **Not** a field match. Source is stateful per-entity `EscalationPolicy`. Engine is stateless per call. Nearest analogue: `newly_triggered_locks` from `LockResult.changed`. |
| `entropy`, `active_engines` | **Dropped.** Belong to multi-engine fusion α does not perform. |

`decision_fingerprint` is extracted from the source codebase: SHA-256 of the decision's own inputs, wall-clock-free, distinct from the ledger chain hash.

Confidence: geometric-mean analogue over Keys **necessary** to satisfy each matched rule's `open_locks` combination (AND/OR/N_OF_M). Averaging every present-and-required Key would let an incidental zero-confidence Key zero out an OR lock. Deliberate deviation: source `ConsensusEngine` returns `0.0` when nothing was evaluated; β returns `1.0` when a rule matches on *absence* of danger (all `closed_locks`).

### New (narrative, not present in any of the four source modules)

`reasoning`, `reversal_conditions`, `instructions` were searched for across those four sources. None has them. This is the gap the project set out to close.

### Engine

- `DecisionRule`: `decision_id`, `decision`, `open_locks`, `closed_locks`, `priority`, templates for narrative. **Declarative, not callables.** Auditable without executing code.
- Fail-closed on unevaluated locks: a rule requiring a lock open/closed that was never evaluated does **not** match.
- Ambiguity is an error: two rules at the same highest priority → `AmbiguousRuleError`, not a coin flip.
- Registry consistency at construction: unknown lock names → `UnknownLockError`.
- No matching rule → `NoMatchingRuleError`.

`DecisionEngine` is **stateless per call**. Lock dwell/cooldown lives in ζ.

## 3. What It Does NOT Do / Non-Goals

- Does **not** issue authorization, grants, or execution receipts.
- Does **not** execute. No callables on rules.
- Does **not** persist. Fingerprint is recomputable; chain hash is δ's job.
- Does **not** perform post-decision agent routing.
- Does **not** reproduce the source's risk fusion, entropy, or engine selection.
- Does **not** substitute for PERCEIVE's six-gate consensus.
- **Not thread-safe** (`DecisionRuleRegistry.register`).

## 4. Brutally Honest Current Status & Gaps

| Gap | Detail |
|---|---|
| Not on live decision path | Another component, in a separate private repository, takes live decisions without `DecisionEngine`. Dual decision path. |
| Narrative templates | String templates, not a proof that reversal conditions are machine-checked later. δ obligations are a separate mechanism. |
| Unpinned zeta git dependency | Default-branch drift. |
| `decision: str` | Free-form. No closed vocabulary (`ESCALATE`/`HOLD`/`DISCHARGE` is convention, not schema). |
| No identity / actor | `entity_id` is a string. No actor registry. |
| Stateless engine | Cannot itself debounce. Relies on ζ. If caller bypasses ζ and feeds synthetic `LockResult`s, β will decide. |

36 tests. `pip install -e ".[dev]" && pytest`.

## 5. Core Invariants & Guarantees

- Fail-closed on unknown or unevaluated locks.
- Ambiguous highest-priority match raises.
- Fingerprint is a SHA-256 of canonical decision inputs (recomputable, no wall-clock).
- Only Keys actually needed by each lock's combination contribute to confidence.
- Policy permission ≠ authorization (stated in the type, not enforced by a grant check — there is none).

## 6. Inputs, Outputs & Type Contracts

```python
from beta import DecisionEngine, DecisionRule, DecisionRuleRegistry, Decision
# Decision fields:
#   entity_id, decision_id, decision: str
#   confidence: float, timestamp: datetime
#   triggered_by_keys, triggered_by_locks, newly_triggered_locks
#   decision_fingerprint: str
#   reasoning: str, reversal_conditions: tuple[str, ...], instructions: str
```

`decide(entity_id, keys, lock_results, timestamp) -> Decision`

## 7. Stack Integration Topology

```text
α KeySet + ζ Dict[lock_id, LockResult]
        → β.DecisionEngine.decide → Decision
                                      → δ.DecisionLedger.append
                                      → δ.DecisionObligationTracker.open_for_decision
```

Custody: [`interconnected_delta`](https://github.com/wking53214/interconnected_delta).

Apache-2.0.
