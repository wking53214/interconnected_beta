# interconnected_beta (β)

Lock states + Keys → a governed **Decision with narrative**. Version `0.1.0`. Depends on [`interconnected_zeta`](https://github.com/wking53214/interconnected_zeta). Python ≥ 3.10.

## Role Within ≡TACK

- **What it is.** The decision stage of the small reference spine: lock states and Keys in, a Decision with a written explanation out.
- **Authority matrix.** Evaluation and evidence generation (the decision and its fingerprints). It does not define policy beyond its declarative rules, enforce, authorize or authenticate. Policy approval is not authorization (section 1).
- **Owns.** Declarative decision rules, the engine, the `Decision` shape, and its fingerprints.
- **Does not own.** The lock evaluation logic (zeta, which beta now runs itself on the normal path), key detection (alpha), custody (delta), execution, and who the entity is.
- **Depends on.** `zeta`, pinned by git commit. CNS is optional.
- **Depended on by.** delta consumes `Decision` per the delta README (not re-checked here).
- **Fail behavior.** Closed on bad config: an unevaluated lock never matches, ambiguous rules at the same priority raise, and no matching rule raises. Closed to hand-fed `LockResult`s: `decide` refuses them unless the caller passes `test_only=True`, and that Decision is stamped `provenance` `"supplied-test"`. The normal path, `decide_from_keys`, evaluates the locks itself and refuses a KeySet that does not report every Key a lock requires (see "Trust boundary" below). Open, by design, on any lock no rule names: a rule matches on the locks it lists and ignores every other lock, so a rule that requires only `lock_a` closed returned its decision, with confidence 1.0, while `lock_b` was open (EXECUTED 2026-11-17). A rule set must name every lock that should block a decision. Two rules at the same priority are refused only at decide time, when both match, not when the engine is built (EXECUTED 2026-11-17). The content fingerprint is keyless, so someone who edits fields and recomputes it is not caught.

Status: library, version 0.1.0. EXECUTED 2026-11-17 at `9c0d717`, Python 3.13, in a fresh environment: `pip install -e ".[dev]" && pytest` gives 173 passed, 2 skipped (the two need CNS). With the `cns` extra installed and `BETA_REQUIRE_CNS=1`, which is how CI's second job runs, 260 passed and none skipped. Not run: GitHub CI, Python 3.10 to 3.12. On branch `beta/evaluate-locks-itself` (2026-11-22, Python 3.13, CNS installed, `BETA_REQUIRE_CNS=1`): 285 passed (EXECUTED). Against that branch, CNS `chains/spine_run.py` (192 scenarios) fails 170 and passes 22; every failure traced to `decide` refusing hand-fed lock results (EXECUTED), so the harness needs moving to `decide_from_keys`. On branch `beta/check-signed-lock-results` (2026-11-22, Python 3.13, zeta `0ab30b2`): 228 passed, 2 skipped without CNS; with CNS and `BETA_REQUIRE_CNS=1`, 320 passed (EXECUTED). On branch `cns-4.2.0` (2026-11-27, Python 3.11, zeta `3ab587a`, CNS v4.2.0): 228 passed, 2 skipped without CNS; with CNS and `BETA_REQUIRE_CNS=1`, 320 passed (EXECUTED).

## Trust boundary (lock results)

Found by an independent review on 2026-11-21 (EXECUTED): `decide` accepted lock results built by hand. With no evidence (an empty KeySet) and two hand-typed "closed" results, the bundled clinical example returned its all-clear decision at confidence 1.0. A real zeta evaluation of an empty KeySet did the same, because a Key nobody reported looks to zeta exactly like a Key that was checked and found absent.

What changed:

- **`decide_from_keys(entity_id, keys, timestamp)` is the normal path.** The engine holds its own zeta `LockEvaluator` over its own `LockRegistry` (and an optional `LockStateStore` passed to `DecisionEngine(rules, lock_registry, state_store)`) and evaluates the locks itself. There is no argument through which lock results can be handed in.
- **The results are an output.** `evaluate_and_decide(entity_id, keys, timestamp)` returns an `Evaluation` with the `Decision` and a copy of the lock results the engine evaluated, for a caller that must bind or record them (CNS, delta). `decision.lock_results_digest` covers exactly those results. Handing them back to `decide` is refused like any other lock results. `decide_from_keys` returns only the Decision.
- **Missing evidence means no decision.** Before evaluating, it raises `MissingEvidenceError` if the KeySet does not report every Key some lock requires. Report a Key that was checked and not found with `present=False`. Lock state is not touched, so missing readings never count toward closing a lock.
- **One step.** If deciding raises after evaluation, the entity's lock states are put back, so a retry counts once (zeta's own rule for `evaluate_all`).
- **Replayable record.** An evaluated Decision records `provenance` `"evaluated"`, `lock_results_digest` (SHA-256 of the lock results it rests on, domain `beta-lock-results/1`, naming the evaluator) and `prior_state_digest` (SHA-256 of the entity's lock states just before the evaluation, domain `beta-lock-state/1`). Anyone holding that prior state and the KeySet can re-run the engine and get the same digests and `content_fingerprint` (tested).
- **Hand-fed results are test-only.** `decide(entity_id, keys, lock_results, timestamp)` raises `SuppliedLockResultsRefused` unless `test_only=True` (only the literal `True`). That Decision records `provenance` `"supplied-test"`, a `lock_results_digest` and no `prior_state_digest`, and must never be acted on or recorded as real. This path does not apply the evidence check, because it exists to test rule logic in isolation.

Limits (INFERRED unless marked):

- Anyone who can run code in this process can still pass a rigged `LockStateStore`, call the test path, or edit a Decision and recompute its keyless fingerprints. The `provenance` stamp makes the test path visible; it does not prevent it.
- The digests identify results; they do not prove who produced them. Signed lock results (next section) prove who held the signer; an outside record is delta's.
- delta at its current pin does not record `provenance` or the two lock digests in its ledger, and does not refuse `"supplied-test"` Decisions. That needs a delta change.
- CNS's `chains/spine_run.py` calls `decide` with lock results and will be refused against this version until it moves to `decide_from_keys` or passes `test_only=True` deliberately.
- A Key reported `present=True` below the KeySet's `min_confidence` counts as reported and not present, per zeta.

## 1. Pipeline Position & Role

**DECISION.** Third stage of the extracted spine.

```text
α Alpha (Keys) → ζ Zeta (Locks) → β Beta (this repo) → δ Delta (custody)
```

The order above is the design order. CNS's script `chains/spine_run.py` runs all four repos in this order (EXECUTED 2026-11-17: exit 0 against the four mains). observe-perceive's orchestrator does not call them.

**Policy approval is not authorization.** This layer produces a decision and an explanation. It does not issue human authority to execute.

## 2. Full System Scope & Architectural Depth

Two parts: extracted verdict shape, and a narrative layer that **does not exist in the source**.

### Extracted (verdict shape, reinvented three times)

`FusedVerdict` appears near-identically in clinical OBSERVE, driving safety, and ascent/altitude compute. Shared fields: `risk_score`, `regime`, `confidence`, `entropy`, `active_engines`, `triggered_rules`, `timestamp`, `audit_hash`, `escalation_required`.

`beta.Decision` does **not** reproduce all nine:

| Source field | β treatment |
|---|---|
| `confidence`, `timestamp` | Kept |
| `audit_hash` | Distinct from `decision_fingerprint`. Audit hash is a ledger concern (δ). |
| `risk_score` + `regime` | Collapsed into free-form `decision: str`. Simplification, not a lossless rename. No 4-level ordinal. |
| `triggered_rules` | Rough analogue: `triggered_by_keys` / `triggered_by_locks` (bare names, not full messages) |
| `escalation_required` | **Not** a field match. Source is stateful per-entity `EscalationPolicy`. Engine is stateless per call. Nearest analogue: `newly_triggered_locks` from `LockResult.changed`. |
| `entropy`, `active_engines` | **Dropped.** Belong to multi-engine fusion α does not perform. |

`decision_fingerprint` is extracted from OBSERVE (`observe_consolidated.py:236-244`): SHA-256 of the decision's own inputs, wall-clock-free, distinct from the ledger chain hash.

Confidence: geometric-mean analogue over Keys **necessary** to satisfy each matched rule's `open_locks` combination (AND/OR/N_OF_M). Averaging every present-and-required Key would let an incidental zero-confidence Key zero out an OR lock. Deliberate deviation: source `ConsensusEngine` returns `0.0` when nothing was evaluated; β returns `1.0` when no Key is necessary to the match (`confidence_basis` `"absence"`, `triggered_by_keys` empty). That covers a rule that matches on *absence* of danger (all `closed_locks`), and also a rule that matches an **open** lock with no present required Key: a lock latched open by ζ's `lock_seconds` cooldown (or opened earlier and still latched) stays open while the Keys have gone, so `decide()` returns, for example, `ESCALATE` with confidence `1.0`, basis `"absence"` and no keys. The latch is ζ's documented design and β does not look at it; the reason ("In cooldown until ...") is in the `LockResult`, not in the `Decision`. `1.0` here is not a calibrated probability. Read `confidence_basis` with `triggered_by_locks`, not as a statement about closed locks.

### New (narrative, not present in OBSERVE/PERCEIVE/drive/ascent)

`reasoning`, `reversal_conditions`, `instructions` were searched for across those four sources. None has them. This is the gap the project set out to close.

### Engine

- `DecisionRule`: `decision_id`, `decision`, `open_locks`, `closed_locks`, `priority`, templates for narrative. **Declarative, not callables.** Auditable without executing code.
- Fail-closed on unevaluated locks: a rule requiring a lock open/closed that was never evaluated does **not** match.
- Ambiguity is an error: two rules at the same highest priority → `AmbiguousRuleError`, not a coin flip.
- Registry consistency at construction: unknown lock names → `UnknownLockError`.
- No matching rule → `NoMatchingRuleError`.

`DecisionEngine` is **stateless per call**. Lock dwell/cooldown lives in ζ.

## Signed lock results

zeta can sign every lock result through a signer the operator plugs in (see interconnected_zeta's README). beta can
check those signatures and refuse to decide on anything that fails.

```python
engine = DecisionEngine(rules, registry, lock_result_signer=private_key.sign, lock_result_verifier=verify)
```

- **With a checker plugged in** (`lock_result_verifier`, the operator's verify callable), every lock result must carry a
  signature that checks out. A missing or failing one raises `LockResultSignatureError`, naming the locks, and no
  Decision is made. This holds on both paths, including the test path.
  - With a checker and **no signer**, every result would be unsigned, so the engine refuses before it evaluates
    anything: lock state is never touched.
  - With both, zeta signs while it evaluates, so the check comes right after. It runs inside the all-or-nothing step:
    on a refusal the entity's lock states are put back, and a retry with a working signer counts the observation once.
- **With no checker** (the default) nothing is checked and behaviour is exactly as before. That setup is
  **unprotected**: anyone who can build a `LockResult` can feed the test path, and nothing proves who produced a result.
- **beta builds the signed bytes itself.** `beta/signing.py` keeps its own copy of the signing rules (domain label
  `zeta-lock-result-signature/1`, canonical ASCII JSON, strict UTF-8), byte for byte the same as zeta's and
  interconnected_delta's. `tests/test_signing.py` proves it against zeta's output and DELTA's `strict_utf8` source. So
  a changed zeta builder cannot make a forged result check out.
- **Signing changes no Decision.** The signature is not in `lock_results_digest` or `content_fingerprint`, so a signed
  run produces the same Decision and digests as an unsigned one (tested).

Limits, plainly:

- **In-process forgery.** The signer runs in the same program. Any code there that can call it can sign a lock result
  no evaluation produced, and the checker will accept it. A signature proves who held the signer, not that the
  evaluation was honest. A separate signer process is the next step.
- **No freshness in the signature.** A lock result has no time field. The Decision's timestamp,
  `lock_results_digest` and `prior_state_digest`, and delta's ledger, carry the time.
- **No key management.** Trust, rotation and revocation belong to the operator's callables.

## 3. What It Does NOT Do / Non-Goals

- Does **not** issue authorization, grants, or execution receipts.
- Does **not** execute. No callables on rules.
- Does **not** persist. Fingerprint is recomputable; chain hash is δ's job.
- Does **not** perform post-decision agent routing.
- Does **not** reproduce OBSERVE risk fusion, entropy, or engine selection.
- Does **not** substitute for PERCEIVE's six-gate consensus (observe-perceive still runs PERCEIVE).
- **Not thread-safe** (`DecisionRuleRegistry.register`).

## 4. Brutally Honest Current Status & Gaps

| Gap | Detail |
|---|---|
| Not on the orchestrator path | observe-perceive `GovernanceOrchestrator` uses PERCEIVE + Conservation Kernel + `execution_guard`, not `DecisionEngine`. Dual decision path. |
| Narrative templates | String templates, not a proof that reversal conditions are machine-checked later. δ obligations are a separate mechanism. |
| Git dependency | `zeta` is pinned by commit in `pyproject.toml` (`tests/test_zeta_pin.py` holds the pin), so moving it is a reviewed change. It is a git dependency, not on a package index. |
| Inputs are only partly checked (test path) | `decide(entity_id, keys, lock_results, timestamp, test_only=True)` takes its arguments independently; the normal path `decide_from_keys` does not take lock results at all (see "Trust boundary"). It now checks that the lock results were evaluated from the KeySet it is given: each `LockResult` records zeta's fingerprint of its KeySet, and `decide` raises `KeySetMismatchError` when one differs or when only some record one (well keys with a sick patient's results used to return ESCALATE with no triggering Keys and full confidence). It now also checks the entity: a lock result that records an entity other than the one given raises `EntityMismatchError` (a `ValueError`, naming both ids), and a result that records none (hand-built, or from an older zeta) is accepted. It still does not check the time of the lock results, and results that record no fingerprint (hand-built, or from an older zeta) still decide, with the Decision recording `keyset_fingerprint` "" so it cannot claim a KeySet. The fingerprint is a fact computed by zeta, not a signature: someone who controls the evaluation can lie. Binding (`context`, below) adds the entity and the lineage digests. |
| `decision: str` | Free-form. No closed vocabulary (`ESCALATE`/`HOLD`/`CLEAR` is convention, not schema). |
| No identity / actor | `entity_id` is a string. No actor registry. |
| Lock state in memory | The engine runs ζ itself and keeps lock state in a ζ `LockStateStore`, in memory unless the caller supplies and persists one. Hand-fed `LockResult`s are refused except with `test_only=True`. |

### Decision consistency and stale input

- `Decision.confidence_basis` is derived from `triggered_by_keys` (`"keys"` when there are any, `"absence"` when there are none). It is left out of every digest, so it must never be wrong: the default `""` derives it, a value that contradicts the keys raises `ValueError` at construction, and `Decision.validate()` re-checks it (and that every field has exactly its type, so a `str` where a tuple belongs is refused, as is a `str`, `float` or `datetime` subclass or a `bool` confidence, which can print one value while holding another; `DecisionEngine.decide` calls `validate()` on the Decision it builds, so a subclass planted in a `DecisionRule` is refused there, and that `confidence` is a finite number in [0, 1]) for a Decision that skipped `__post_init__` (unpickled, `object.__new__`). `validate()` also requires `confidence_basis` and `audit_hash` to be exact `str` (a subclass, `None`, `int` or `bytes` is refused with a `ValueError` naming the field). `validate(check_fingerprint=True)` also recomputes `decision_fingerprint`. Construction itself checks only the basis. δ calls `validate()` before it records anything. `dataclasses.replace` on a Decision that changes `triggered_by_keys` must pass `confidence_basis=""` to re-derive.
- **Two fingerprints, two scopes.** `decision_fingerprint` still covers exactly five fields: `entity_id`, `decision_id`, `decision`, `triggered_by_locks`, `triggered_by_keys`. It is unchanged. `content_fingerprint` (set by both engine paths, domain `beta-decision-content/2`, SHA-256 of canonical JSON with sorted keys and compact separators) covers 16: those five plus `timestamp` (as its isoformat string), `confidence`, `newly_triggered_locks`, `reasoning`, `reversal_conditions`, `instructions`, `confidence_basis`, `keyset_fingerprint`, `provenance`, `lock_results_digest` and `prior_state_digest`. Domain `/1` covered the first 13; the domain changed with the field set, so every fingerprint made under `/1` differs under `/2`. `canonical_decision(decision)` returns exactly what is hashed. Excluded on purpose: `audit_hash` (a pointer the ledger stage writes after the Decision exists, so covering it would change the fingerprint merely because the Decision was recorded), `decision_fingerprint` (the older, separate identity) and `content_fingerprint` itself. `validate(check_fingerprint=True)` recomputes it when it is non-empty and raises `ValueError` on a mismatch; an empty one is a legacy Decision and is accepted. `beta.cns_connector.decision_content` carries it only when set, so every legacy digest is unchanged. Tests edit each of the 16 fields of an engine-made Decision and show the check refuses it, including the 8 fields `decision_fingerprint` alone would not notice.
- **Keyless limit.** `content_fingerprint` uses no key. It catches a partial edit (one field changed, the stored fingerprint left as it was). It does not stop someone who edits fields and recomputes the fingerprint, and it is not a signature or an authenticity claim.
- `Decision` converts a `list` given for `triggered_by_locks`, `triggered_by_keys`, `newly_triggered_locks` or `reversal_conditions` to a tuple, so later changes to the caller's list do not reach it. `validate()` reports a `confidence` that cannot be compared as a float (for example `10**400`) as a `ValueError`, not an `OverflowError`.
- A decided `Decision` carries `keyset_fingerprint`, the KeySet its lock results were evaluated from (outside `decision_fingerprint`, so existing fingerprints are unchanged; `validate()` requires it to be empty or a full lowercase SHA-256). Under a `context` a Decision that records none is refused.
- `decide` raises `StaleLockResultError` when any supplied `LockResult` has `stale=True`, naming the locks: zeta refused that observation, so no Decision is made from it. Retrying is the caller's.
- A frozen dataclass is not a security boundary: `object.__setattr__` can still change a Decision in memory. The recording boundary re-validates; in-process use is not protected.

`pip install -e ".[dev]" && pytest`. Current counts are in the Status line at the top; the "36 tests" figure that stood here was out of date.

## 5. Core Invariants & Guarantees

- Fail-closed on unknown or unevaluated locks.
- Ambiguous highest-priority match raises.
- Fingerprint is a SHA-256 of canonical decision inputs (recomputable, no wall-clock).
- Only Keys actually needed by each lock's combination contribute to confidence.
- Policy permission ≠ authorization (stated in the type, not enforced by a grant check, there is none).

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

`decide_from_keys(entity_id, keys, timestamp) -> Decision` (normal path)

`evaluate_and_decide(entity_id, keys, timestamp) -> Evaluation(decision, lock_results)` (normal path, with the evaluated lock results as an output)

`decide(entity_id, keys, lock_results, timestamp, *, test_only=True) -> Decision` (tests only; refused without `test_only=True`)

## 7. Stack Integration Topology

```text
α KeySet
        → β.DecisionEngine.decide_from_keys (runs ζ itself) → Decision
                                      → δ.DecisionLedger.append
                                      → δ.DecisionObligationTracker.open_for_decision
```

Who runs this order: CNS's script `chains/spine_run.py`, not observe-perceive's orchestrator (see section 1 for the evidence).

Hub that does **not** import β: [`observe-perceive`](https://github.com/wking53214/observe-perceive).  
Custody: [`interconnected_delta`](https://github.com/wking53214/interconnected_delta).

## Optional CNS connection

beta does not need CNS. It has no runtime dependency on it, nothing in the package imports it when it loads, and the engine never touches it (`tests/test_cns_independence.py` checks this with CNS blocked). `beta/cns_connector.py` is the one place that knows CNS exists. Install it with `pip install 'beta[cns] @ git+https://github.com/wking53214/interconnected_beta'`; without CNS its functions raise `CnsNotInstalled` and nothing else changes.

What it does is make a `Decision` **bindable**. `decision_content(decision)` returns the deterministic content of a Decision (every field except `audit_hash`, which a ledger stamps after the fact; the set-like lock and key tuples are sorted so order cannot change the digest), `decision_digest(decision)` is `cns.gate.subject_digest` over it, and `binds(result, decision)` says whether a `cns.gate.GateResult` was issued against exactly that Decision. A verdict about one Decision does not bind to another.

**Binding a Decision to a run.** Pass `context=` (exactly `schema` `"spine-context/1"`, `entity_id`, `event_id`, `run_id`, all non-empty strings), `keyset_digest=` and `lock_result_digests=` (lock id to digest) to `decision_content`, `decision_digest` or `binds`; all three or none. The Decision must be about the context's entity and every lock it cites must have a lock-result digest, or the connector raises. The content gains `context`, `keyset_digest` and `lock_result_digests`. Without them every existing digest is unchanged.

It is **binding only**, and deliberately not a gate. There is no mapping from a Decision to `PASS`, `RETRY` or `TERMINAL_BREACH`: a Decision is a governed recommendation, and turning it into a gate outcome would invent a meaning beta does not have. Whoever issues a verdict about a Decision owns that meaning; this only lets them say which Decision it was about.

The CNS digest is separate from `decision_fingerprint`, which is unchanged and unaware of CNS. The fingerprint hashes the inputs that produced a decision; the CNS digest binds the whole output, narrative and confidence included.

Apache-2.0.
