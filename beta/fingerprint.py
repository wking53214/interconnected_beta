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
