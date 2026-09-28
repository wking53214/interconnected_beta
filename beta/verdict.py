"""Decision: the governed output of beta, extracted from a shape
reinvented three times in the source, plus a genuinely new narrative
layer that exists nowhere in the source.

EXTRACTED (the core verdict shape):
`FusedVerdict` is defined near-identically three times, for three
different domains, none importing from the others:
  - observe_consolidated.py:82-97   (clinical/pediatric — the fullest version)
  - drive_safety_module.py:89-99    (driving safety — the minimal base shape)
  - ascent_compute_module.py:102-113 (ascent/altitude compute — adds reserve_factor)

All three share: risk_score, regime, confidence, entropy, active_engines,
triggered_rules, timestamp, audit_hash, escalation_required. Decision
generalizes that common core (renamed to fit a Lock-based, not a
risk-score-based, decision model -- see field mapping in the docstring
below) instead of leaving three domains to each maintain their own copy.

Also extracted: the `audit_hash` vs. `decision_fingerprint` distinction
from observe_consolidated.py:90-94 -- `audit_hash` is the ledger's
chained, tamper-evident hash (requires previous-entry state that only
exists once something is actually recorded — interconnected_delta's
job, not beta's); `decision_fingerprint` is a reproducible hash of the
decision's own inputs, computable here with no external state, so this
module computes that and leaves audit_hash for delta to fill in.

NOT extracted, because nothing in the source has it: `reasoning`,
`reversal_conditions`, `instructions` are new. observe_consolidated.py,
perceive_consolidated.py, drive_safety_module.py, and
ascent_compute_module.py were all searched for anything resembling a
narrative/reasoning/reversal/instructions field -- none exists anywhere
in the source. That's the actual gap this whole project set out to
close (see interconnected_zeta and interconnected_alpha's own
provenance notes on "the why problem"), not an extraction.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Tuple


@dataclass(frozen=True)
class Decision:
    entity_id: str
    decision_id: str  # which DecisionRule matched (beta/rules.py)
    decision: str  # the verdict value, e.g. "ESCALATE", "DISCHARGE_SAFE"
    timestamp: datetime

    # --- Extracted core (generalizes the 3x-duplicated FusedVerdict shape) ---
    confidence: float  # geometric mean of triggering Keys' confidence (see engine.py)
    triggered_by_locks: Tuple[str, ...] = field(default_factory=tuple)
    triggered_by_keys: Tuple[str, ...] = field(default_factory=tuple)
    decision_fingerprint: str = ""  # reproducible; see fingerprint.py
    audit_hash: str = ""  # left for interconnected_delta's ledger to populate

    # --- New: the narrative layer, not present anywhere in the source ---
    reasoning: str = ""
    reversal_conditions: Tuple[str, ...] = field(default_factory=tuple)
    instructions: str = ""
