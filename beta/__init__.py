"""beta: Lock states + Keys -> a governed Decision with narrative.

Ties zeta's Locks to a declarative rule set and produces a Decision that
carries not just a verdict but WHY (reasoning), WHEN it would change
(reversal_conditions), and WHAT should happen next (instructions) -- the
narrative layer identified throughout this project as missing from the
source entirely (see verdict.py's provenance notes).

See beta/verdict.py, beta/rules.py, beta/engine.py, beta/fingerprint.py
for what's extracted from the source (the fused verdict shape, reinvented
three times; the decision_fingerprint algorithm; the consensus
confidence approach) versus what's new (the narrative fields, the
declarative DecisionRule matching, the fail-closed treatment of
unevaluated locks).
"""

from .verdict import Decision
from .rules import DecisionRule, DecisionRuleRegistry
from .engine import DecisionEngine, NoMatchingRuleError, AmbiguousRuleError
from .fingerprint import decision_fingerprint

__all__ = [
    "Decision",
    "DecisionRule",
    "DecisionRuleRegistry",
    "DecisionEngine",
    "NoMatchingRuleError",
    "AmbiguousRuleError",
    "decision_fingerprint",
]

__version__ = "0.1.0"
