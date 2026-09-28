"""Decision: the governed output of beta, extracted from a shape
reinvented three times in the source, plus a genuinely new narrative
layer that exists nowhere in the source.

EXTRACTED (the core verdict shape): `FusedVerdict` is defined
near-identically three times, for three different domains, none
importing from the others:
  - observe_consolidated.py:82-97   (clinical/pediatric — the fullest version)
  - drive_safety_module.py:89-99    (driving safety — the minimal base shape)
  - ascent_compute_module.py:102-113 (ascent/altitude compute — adds reserve_factor)

All three share 9 fields: risk_score, regime, confidence, entropy,
active_engines, triggered_rules, timestamp, audit_hash,
escalation_required. Decision does NOT reproduce all nine — an earlier
version of this docstring claimed a "field mapping below" that didn't
actually exist; adversarial review caught the gap. Here is the real,
field-by-field accounting:

  | FusedVerdict field   | Decision equivalent                          |
  |----------------------|-----------------------------------------------|
  | confidence            | confidence (same geometric-mean approach)     |
  | timestamp              | timestamp                                    |
  | audit_hash             | audit_hash (left empty; delta's ledger fills it) |
  | risk_score + regime    | collapsed into one free-form `decision: str`. |
  |                        | No continuous score, no 4-level ordinal enum  |
  |                        | — whoever authors a DecisionRule picks the    |
  |                        | string. This is a real simplification, not a  |
  |                        | lossless rename.                              |
  | triggered_rules        | roughly analogous to triggered_by_keys /      |
  |                        | triggered_by_locks, but those are bare NAMES  |
  |                        | (key/lock ids), not the source's full         |
  |                        | human-readable message strings.               |
  | escalation_required    | NOT a field-for-field match. The source means |
  |                        | "a NEW escalation this cycle," backed by a    |
  |                        | stateful per-entity EscalationPolicy with     |
  |                        | dwell counting and a cooldown lock             |
  |                        | (observe_consolidated.py:846-889 and          |
  |                        | equivalents in the other two files). beta's   |
  |                        | DecisionEngine is stateless per call and has  |
  |                        | no such machinery of its own. The closest     |
  |                        | analogue is `newly_triggered_locks`, sourced  |
  |                        | from zeta's LockResult.changed (zeta's Locks  |
  |                        | already carry dwell/cooldown state, so this   |
  |                        | is real information, not a stand-in) — but it |
  |                        | answers "which locks changed," not "is this   |
  |                        | escalation cycle new," which is a narrower    |
  |                        | question than the source's field answers.     |
  | entropy                | DROPPED. In all three sources this drives     |
  |                        | adaptive engine selection (a >0.6 threshold   |
  |                        | decides whether to run additional risk        |
  |                        | engines next call — e.g.                       |
  |                        | observe_consolidated.py:1201-1203). beta has  |
  |                        | no multi-engine fusion step for it to         |
  |                        | describe — alpha runs all detectors always,   |
  |                        | it doesn't adaptively select a subset. No     |
  |                        | Decision field stands in for this.            |
  | active_engines          | DROPPED. Records which of several parallel    |
  |                        | risk-scoring engines contributed, for audit   |
  |                        | (e.g. drive_safety_module.py:707). beta has   |
  |                        | no multi-engine fusion step either — Locks    |
  |                        | are evaluated deterministically from Keys,    |
  |                        | not selected adaptively. No Decision field    |
  |                        | stands in for this.                           |

Also extracted: the `audit_hash` vs. `decision_fingerprint` distinction
from observe_consolidated.py:90-94 — `audit_hash` is the ledger's
chained, tamper-evident hash (requires previous-entry state that only
exists once something is actually recorded — interconnected_delta's
job, not beta's); `decision_fingerprint` is a reproducible hash of the
decision's own inputs, computable here with no external state.

NOT extracted, because nothing in the source has it: `reasoning`,
`reversal_conditions`, `instructions` are new. observe_consolidated.py,
perceive_consolidated.py, drive_safety_module.py, and
ascent_compute_module.py were all searched for anything resembling a
narrative/reasoning/reversal/instructions field — none exists anywhere
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

    # --- Extracted core (see field-mapping table above) ---
    confidence: float  # geometric mean of the Keys necessary to satisfy the matched rule
    triggered_by_locks: Tuple[str, ...] = field(default_factory=tuple)
    triggered_by_keys: Tuple[str, ...] = field(default_factory=tuple)
    newly_triggered_locks: Tuple[str, ...] = field(default_factory=tuple)
    decision_fingerprint: str = ""  # reproducible; see fingerprint.py
    audit_hash: str = ""  # left for interconnected_delta's ledger to populate

    # --- New: the narrative layer, not present anywhere in the source ---
    reasoning: str = ""
    reversal_conditions: Tuple[str, ...] = field(default_factory=tuple)
    instructions: str = ""
