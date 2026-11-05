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
from typing import Any, Dict


def decision_fingerprint(data: Dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(data, sort_keys=True, default=str).encode()).hexdigest()


CONTENT_DOMAIN = "beta-decision-content/1"


def canonical_decision(decision: Any) -> Dict[str, Any]:
    """The 13 Decision fields ``content_fingerprint`` covers, as plain JSON-ready values.

    Covered: entity_id, decision_id, decision, timestamp (as its isoformat string), confidence,
    triggered_by_locks, triggered_by_keys, newly_triggered_locks, reasoning, reversal_conditions, instructions,
    confidence_basis, keyset_fingerprint. The tuple fields become lists in the order held.

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
    }


def content_fingerprint(decision: Any) -> str:
    """SHA-256 over :func:`canonical_decision` under the domain ``beta-decision-content/1``.

    Keyless: it detects a partial edit of a Decision, not someone who edits and recomputes it.
    """
    payload = {"domain": CONTENT_DOMAIN, **canonical_decision(decision)}
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
