"""beta: Lock states + Keys -> a governed Decision with narrative.

Ties zeta's Locks to a declarative rule set and produces a Decision that
carries not just a verdict but WHY (reasoning), WHEN it would change
(reversal_conditions), and WHAT should happen next (instructions) -- the
narrative layer identified throughout this project as missing from the
source entirely (see verdict.py's provenance notes).

See beta/verdict.py, beta/rules.py, beta/engine.py, beta/fingerprint.py
for what's extracted from the source (the FusedVerdict shape, reinvented
three times; the decision_fingerprint algorithm; the ConsensusEngine
confidence approach) versus what's new (the narrative fields, the
declarative DecisionRule matching, the fail-closed treatment of
unevaluated locks).
"""

from .verdict import Decision
from .rules import DecisionRule, DecisionRuleRegistry
from .engine import (DecisionEngine, EntityMismatchError, NoMatchingRuleError, AmbiguousRuleError, KeySetMismatchError,
                     StaleLockResultError, SuppliedLockResultsRefused, MissingEvidenceError, Evaluation,
                     LockResultSignatureError)
from .fingerprint import (canonical_decision, content_fingerprint, decision_fingerprint, lock_results_digest,
                          lock_state_digest)
from .verdict import PROVENANCE_EVALUATED, PROVENANCE_SUPPLIED_TEST
from .signing import lock_result_signature_ok, lock_result_signing_input

__all__ = [
    "Decision",
    "DecisionRule",
    "DecisionRuleRegistry",
    "DecisionEngine",
    "EntityMismatchError",
    "NoMatchingRuleError",
    "AmbiguousRuleError",
    "KeySetMismatchError",
    "StaleLockResultError",
    "SuppliedLockResultsRefused",
    "MissingEvidenceError",
    "Evaluation",
    "LockResultSignatureError",
    "PROVENANCE_EVALUATED",
    "PROVENANCE_SUPPLIED_TEST",
    "lock_results_digest",
    "lock_state_digest",
    "decision_fingerprint",
    "content_fingerprint",
    "canonical_decision",
    "lock_result_signing_input",
    "lock_result_signature_ok",
]

__version__ = "0.1.0"
