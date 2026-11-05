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

import math
import re
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
    # Geometric mean of the Keys necessary to satisfy the matched rule. For an
    # absence-only match (no triggering Keys) the value is
    # beta.engine.ABSENCE_CONFIDENCE and is not a calibrated probability;
    # confidence_basis says which case applies.
    confidence: float
    triggered_by_locks: Tuple[str, ...] = field(default_factory=tuple)
    triggered_by_keys: Tuple[str, ...] = field(default_factory=tuple)
    newly_triggered_locks: Tuple[str, ...] = field(default_factory=tuple)
    decision_fingerprint: str = ""  # reproducible; see fingerprint.py
    audit_hash: str = ""  # left for interconnected_delta's ledger to populate

    # --- New: the narrative layer, not present anywhere in the source ---
    reasoning: str = ""
    reversal_conditions: Tuple[str, ...] = field(default_factory=tuple)
    instructions: str = ""

    # "keys" when confidence averaged triggering Keys, "absence" when the
    # matched rule contributed none. Not part of decision_fingerprint or
    # the CNS digest, so existing digests are unchanged. It is derived from
    # triggered_by_keys, and because no digest sees it, it must never be wrong:
    # "" (the default) means "derive it", and a value that contradicts the keys
    # is refused at construction and by validate().
    confidence_basis: str = ""

    # Fingerprint (zeta's KeySet.fingerprint) of the KeySet the lock results this Decision rests on were evaluated
    # from, set by DecisionEngine.decide when every result recorded one and it matched the KeySet decide was given.
    # "" means the Decision is unbound to a KeySet (hand-built lock results, or an older zeta). Not part of
    # decision_fingerprint, so existing fingerprints are unchanged.
    keyset_fingerprint: str = ""

    # SHA-256 over the 13 fields beta.fingerprint.canonical_decision lists (domain "beta-decision-content/1"), set by
    # DecisionEngine.decide. "" means a legacy or hand-built Decision that records none. Unlike decision_fingerprint
    # (5 inputs, unchanged) it covers the narrative, confidence, timestamp and lineage. Keyless: it catches a partial
    # edit, not a forger who recomputes it.
    content_fingerprint: str = ""

    def __post_init__(self) -> None:
        # A list given for a tuple field becomes a tuple, so later mutation of the caller's list cannot reach a
        # frozen Decision. Only a real list is converted; anything else is left for validate() to judge.
        for name in ("triggered_by_locks", "triggered_by_keys", "newly_triggered_locks", "reversal_conditions"):
            if isinstance(getattr(self, name), list):
                object.__setattr__(self, name, tuple(getattr(self, name)))
        expected = self._derived_basis()
        if self.confidence_basis == "":
            object.__setattr__(self, "confidence_basis", expected)
        elif self.confidence_basis != expected:
            raise ValueError(
                f"Decision.confidence_basis is {self.confidence_basis!r} but "
                f"triggered_by_keys implies {expected!r}"
            )

    def _derived_basis(self) -> str:
        return "keys" if self.triggered_by_keys else "absence"

    def validate(self, *, check_fingerprint: bool = False) -> None:
        """Raise ValueError unless this Decision is internally consistent.

        __post_init__ does not run for a Decision that is unpickled or built with
        object.__new__, so a recorder calls this at its boundary. Checks the basis
        against the keys, that every field has exactly its type (a str where a tuple belongs would otherwise be
        recorded as its characters, and a str, float or datetime subclass can print one value while holding another,
        so subclasses and bool are refused), and that confidence is a finite number in [0, 1]. With
        check_fingerprint=True it also recomputes decision_fingerprint from the
        Decision's own fields; that is opt in because a fingerprint is only
        meaningful for a Decision the engine produced.
        """
        for name in ("entity_id", "decision_id", "decision", "decision_fingerprint", "reasoning", "instructions",
                     "content_fingerprint", "keyset_fingerprint"):
            if type(getattr(self, name)) is not str:
                raise ValueError(f"Decision.{name} must be a str; got {type(getattr(self, name)).__name__}")
        for name in ("triggered_by_locks", "triggered_by_keys", "newly_triggered_locks", "reversal_conditions"):
            value = getattr(self, name)
            if type(value) not in (tuple, list) or not all(type(item) is str for item in value):
                raise ValueError(f"Decision.{name} must be a tuple of str; got {value!r}")
        if type(self.timestamp) is not datetime:
            raise ValueError(f"Decision.timestamp must be a datetime; got {type(self.timestamp).__name__}")
        fp = self.keyset_fingerprint
        if fp and not re.fullmatch(r"[0-9a-f]{64}", fp):
            raise ValueError(f"Decision.keyset_fingerprint must be empty or a full lowercase SHA-256; got {fp!r}")
        c = self.confidence
        try:
            bad_confidence = (
                type(c) not in (int, float) or not math.isfinite(c) or not (0.0 <= c <= 1.0)
            )
        except (OverflowError, TypeError):  # an int too large for a float, or a subclass that refuses comparison
            bad_confidence = True
        if bad_confidence:
            raise ValueError(f"Decision.confidence must be a finite number in [0, 1]; got {c!r}")
        expected = self._derived_basis()
        if self.confidence_basis != expected:
            raise ValueError(
                f"Decision.confidence_basis is {self.confidence_basis!r} but "
                f"triggered_by_keys implies {expected!r}"
            )
        if check_fingerprint:
            if not self.decision_fingerprint:
                raise ValueError("Decision has no decision_fingerprint to check")
            from .fingerprint import decision_fingerprint

            want = decision_fingerprint({
                "entity_id": self.entity_id,
                "decision_id": self.decision_id,
                "decision": self.decision,
                "triggered_by_locks": list(self.triggered_by_locks),
                "triggered_by_keys": list(self.triggered_by_keys),
            })
            if self.decision_fingerprint != want:
                raise ValueError("Decision.decision_fingerprint does not match the Decision's own fields")
            if self.content_fingerprint:  # empty is a legacy Decision: accepted
                from .fingerprint import content_fingerprint

                if self.content_fingerprint != content_fingerprint(self):
                    raise ValueError("Decision.content_fingerprint does not match the Decision's own fields")
