"""decision_fingerprint: reproducible hash of a decision's own inputs.

Extracted verbatim (same algorithm, same wall-clock-free contract) from
observe_consolidated.py:236-244. Deliberately separate from audit_hash,
which is the ledger's chained, tamper-evident hash and requires ledger
state (the previous entry) that only exists once something is actually
recorded -- interconnected_delta's job, not beta's. This fingerprint
needs no external state: identical inputs always produce an identical
hash, in-process or across runs, which is what makes it useful for
forensic replay ("did this decision definitely come from these exact
inputs?") independent of whether or when it was ever recorded anywhere.
"""

import hashlib
import json
from datetime import datetime
from typing import Any, Dict, Mapping, Optional


def decision_fingerprint(data: Dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(data, sort_keys=True, default=str).encode()).hexdigest()


CONTENT_DOMAIN = "beta-decision-content/2"


def canonical_decision(decision: Any) -> Dict[str, Any]:
    """The 16 Decision fields ``content_fingerprint`` covers, as plain JSON-ready values.

    Covered: entity_id, decision_id, decision, timestamp (as its isoformat string), confidence,
    triggered_by_locks, triggered_by_keys, newly_triggered_locks, reasoning, reversal_conditions, instructions,
    confidence_basis, keyset_fingerprint, provenance, lock_results_digest, prior_state_digest. The tuple fields
    become lists in the order held.

    Domain "beta-decision-content/2" (was /1 with the first 13 fields). provenance is covered so a Decision built
    from hand-fed lock results ("supplied-test") cannot be relabelled "evaluated" without the fingerprint changing.

    Excluded on purpose:
      - audit_hash: a pointer the ledger stage writes after the Decision exists; covering it would make the
        fingerprint change merely because the Decision was recorded.
      - decision_fingerprint: the older, separate identity of the Decision's inputs, left unchanged.
      - content_fingerprint: the value being computed.
    """
    return {
        "entity_id": decision.entity_id,
        "decision_id": decision.decision_id,
        "decision": decision.decision,
        "timestamp": decision.timestamp.isoformat(),
        "confidence": decision.confidence,
        "triggered_by_locks": list(decision.triggered_by_locks),
        "triggered_by_keys": list(decision.triggered_by_keys),
        "newly_triggered_locks": list(decision.newly_triggered_locks),
        "reasoning": decision.reasoning,
        "reversal_conditions": list(decision.reversal_conditions),
        "instructions": decision.instructions,
        "confidence_basis": decision.confidence_basis,
        "keyset_fingerprint": decision.keyset_fingerprint,
        "provenance": decision.provenance,
        "lock_results_digest": decision.lock_results_digest,
        "prior_state_digest": decision.prior_state_digest,
    }


def content_fingerprint(decision: Any) -> str:
    """SHA-256 over :func:`canonical_decision` under the domain ``beta-decision-content/1``.

    Keyless: it detects a partial edit of a Decision, not someone who edits and recomputes it.
    """
    payload = {"domain": CONTENT_DOMAIN, **canonical_decision(decision)}
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


LOCK_RESULTS_DOMAIN = "beta-lock-results/1"
LOCK_STATE_DOMAIN = "beta-lock-state/1"


def _sha(payload: Dict[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("ascii")
    ).hexdigest()


def _moment(value: Optional[datetime]) -> Optional[str]:
    return None if value is None else value.isoformat()


def lock_results_digest(lock_results: Mapping[str, Any], evaluator: str) -> str:
    """SHA-256 of exactly the lock results a Decision rests on, under ``beta-lock-results/1``.

    Covers, per lock in id order: open, changed, forced, stale, reasons, keyset_fingerprint and entity_id, plus the
    name and version of the evaluator that produced them. This is the value a later step can have zeta sign. Keyless
    on its own: it identifies the results, it does not prove who produced them.
    """
    rows = [
        {
            "lock_id": lock_id,
            "open": bool(r.open),
            "changed": bool(r.changed),
            "forced": bool(r.forced),
            "stale": bool(getattr(r, "stale", False)),
            "reasons": [str(x) for x in getattr(r, "reasons", [])],
            "keyset_fingerprint": str(getattr(r, "keyset_fingerprint", "")),
            "entity_id": str(getattr(r, "entity_id", "")),
        }
        for lock_id, r in sorted(lock_results.items())
    ]
    return _sha({"domain": LOCK_RESULTS_DOMAIN, "evaluator": evaluator, "results": rows})


def lock_state_digest(states: Mapping[str, Any]) -> str:
    """SHA-256 of an entity's lock states (a zeta LockStateStore snapshot), under ``beta-lock-state/1``.

    Recorded as the state BEFORE an evaluation, so anyone holding that state and the KeySet can re-run zeta and check
    they get the same lock results. Covers every LockState field, including last_observed_at.
    """
    rows = [
        {
            "lock_id": lock_id,
            "open": bool(st.open),
            "pending_open": st.pending_open,
            "pending_since_count": int(st.pending_since_count),
            "locked_until": _moment(st.locked_until),
            "opened_at": _moment(st.opened_at),
            "forced": bool(st.forced),
            "last_observed_at": _moment(getattr(st, "last_observed_at", None)),
        }
        for lock_id, st in sorted(states.items())
    ]
    return _sha({"domain": LOCK_STATE_DOMAIN, "states": rows})
