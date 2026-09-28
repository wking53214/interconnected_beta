"""DecisionEngine: Lock states + Keys -> a governed Decision with narrative.

Ties together zeta's output (Dict[lock_id, LockResult]) and beta's own
declarative rules (DecisionRuleRegistry) to produce a Decision. Needs the
originating KeySet and the LockRegistry too -- not just the LockResults
-- because "which specific Keys triggered this" requires knowing each
matched rule's locks' required_keys (from the registry) cross-referenced
against which of those Keys are actually present (from the KeySet).
LockResult itself carries no reference back to its required_keys.

Confidence extends PERCEIVE's ConsensusEngine.evaluate geometric-mean
approach (perceive_consolidated.py:502: `math.prod(confidences) **
(1/len(confidences))`) -- extracted faithfully for the case where there
ARE triggering Keys to average. One deliberate deviation, not an
extraction: ConsensusEngine returns confidence=0.0 when there's nothing
to average ("no gates evaluated" is treated as a genuine error there).
Here, a rule can legitimately match on absence of evidence alone (all
its requirements are in closed_locks, no open_locks at all -- e.g. "safe
to discharge" triggered by the ABSENCE of any danger Lock, not the
presence of a recovery Key). That's not an error state, so this engine
returns confidence=1.0 for that case instead of 0.0 -- full confidence
in a cleanly-matched absence, not "no confidence in anything."
"""

import math
from datetime import datetime
from typing import Dict, List

from zeta import KeySet, LockRegistry, LockResult

from .fingerprint import decision_fingerprint
from .rules import DecisionRule, DecisionRuleRegistry
from .verdict import Decision


class NoMatchingRuleError(Exception):
    """No DecisionRule's requirements are satisfied by the current Lock state."""


class AmbiguousRuleError(Exception):
    """More than one DecisionRule matched at the same (highest) priority."""


def _geometric_mean(confidences: List[float]) -> float:
    if not confidences:
        return 1.0
    return math.prod(confidences) ** (1.0 / len(confidences))


class DecisionEngine:
    def __init__(self, rules: DecisionRuleRegistry, lock_registry: LockRegistry) -> None:
        self.rules = rules
        self.lock_registry = lock_registry

    def _select_rule(self, lock_results: Dict[str, LockResult]) -> DecisionRule:
        matching = [r for r in self.rules.all() if r.matches(lock_results)]
        if not matching:
            raise NoMatchingRuleError(
                "No decision rule's requirements are satisfied by the current lock state "
                f"({ {lid: lr.open for lid, lr in lock_results.items()} })"
            )
        max_priority = max(r.priority for r in matching)
        top = [r for r in matching if r.priority == max_priority]
        if len(top) > 1:
            raise AmbiguousRuleError(
                f"Multiple decision rules matched at priority {max_priority}: "
                f"{sorted(r.decision_id for r in top)}"
            )
        return top[0]

    def decide(
        self,
        entity_id: str,
        keys: KeySet,
        lock_results: Dict[str, LockResult],
        timestamp: datetime,
    ) -> Decision:
        rule = self._select_rule(lock_results)

        # Which specific Keys triggered this: present Keys required by any
        # of the matched rule's open_locks. closed_locks contribute no
        # positive Key evidence -- their contribution is the ABSENCE of
        # their required Keys, which has no confidence value to average.
        triggering_key_names = set()
        for lock_id in rule.open_locks:
            spec = self.lock_registry.get(lock_id)
            triggering_key_names.update(k for k in spec.required_keys if keys.is_present(k))

        sorted_keys = sorted(triggering_key_names)
        confidences = [keys.get(k).confidence for k in sorted_keys]
        confidence = _geometric_mean(confidences)

        all_triggered_locks = tuple(sorted(set(rule.open_locks) | set(rule.closed_locks)))

        reasoning = rule.reasoning_template.format(
            decision=rule.decision,
            open_locks=list(rule.open_locks),
            closed_locks=list(rule.closed_locks),
        )

        fingerprint = decision_fingerprint({
            "entity_id": entity_id,
            "decision_id": rule.decision_id,
            "decision": rule.decision,
            "triggered_by_locks": list(all_triggered_locks),
            "triggered_by_keys": sorted_keys,
        })

        return Decision(
            entity_id=entity_id,
            decision_id=rule.decision_id,
            decision=rule.decision,
            timestamp=timestamp,
            confidence=confidence,
            triggered_by_locks=all_triggered_locks,
            triggered_by_keys=tuple(sorted_keys),
            decision_fingerprint=fingerprint,
            reasoning=reasoning,
            reversal_conditions=rule.reversal_conditions,
            instructions=rule.instructions,
        )
