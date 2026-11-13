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
to proceed" triggered by the ABSENCE of any danger Lock, not the
presence of a recovery Key). That's not an error state, so this engine
returns confidence=1.0 for that case instead of 0.0 -- full confidence
in a cleanly-matched absence, not "no confidence in anything."

Which Keys are "necessary" for a lock's confidence depends on its
combination (adversarial review caught the original version averaging
EVERY present required_key regardless of combination -- so an OR lock
satisfied by one strong Key plus one incidentally-also-present
zero-confidence Key got its confidence dragged to exactly 0.0, even
though the zero-confidence Key wasn't needed to open it at all):
  - AND: every present required_key was necessary -> average all of them.
  - OR: only the single strongest present Key was necessary (OR needs
    just one) -> credit only the max-confidence present Key.
  - N_OF_M: only the top `n` strongest present Keys were necessary ->
    credit only those.
"""

import math
import dataclasses
from datetime import datetime
from typing import Dict, List, Set

from zeta import Combination, KeySet, LockRegistry, LockResult, LockSpec

from .fingerprint import content_fingerprint, decision_fingerprint
from .rules import DecisionRule, DecisionRuleRegistry
from .verdict import Decision


# Confidence reported when a rule matches on absence alone (no triggering
# Keys to average). A statement of a clean match, not a calibrated
# probability; Decision.confidence_basis says when it was used.
ABSENCE_CONFIDENCE = 1.0


class NoMatchingRuleError(Exception):
    """No DecisionRule's requirements are satisfied by the current Lock state."""


class AmbiguousRuleError(Exception):
    """More than one DecisionRule matched at the same (highest) priority."""


class EntityMismatchError(ValueError):
    """A lock result records an entity other than the one decide was asked about.

    Fail closed: another entity's lock states under this entity's id would read as this entity's evidence. A
    result that records no entity (hand-built, or from an older zeta) is accepted, as before.
    """


class UnknownLockError(Exception):
    """A DecisionRule references a lock_id absent from the supplied LockRegistry."""


class KeySetMismatchError(Exception):
    """The lock results decide was given were evaluated from a different KeySet than the one it was given.

    Fail closed: a Decision built from keys and lock results of different evidence reads as sound and is about
    nobody's evidence (it can ESCALATE with no triggering Keys and full confidence).
    """


class StaleLockResultError(Exception):
    """A supplied LockResult was refused by zeta as stale, so it describes no new observation.

    Fail closed: a stale result carries the unchanged earlier lock state, and a Decision built on it would read
    as a fresh judgement of readings zeta declined to apply. The caller decides whether to retry.
    """


def _geometric_mean(confidences: List[float]) -> float:
    if not confidences:
        return ABSENCE_CONFIDENCE
    return math.prod(confidences) ** (1.0 / len(confidences))


def _keys_necessary_for_lock(spec: LockSpec, keys: KeySet) -> Set[str]:
    present_required = [k for k in spec.required_keys if keys.is_present(k)]
    if not present_required:
        return set()

    if spec.combination == Combination.AND:
        return set(present_required)

    if spec.combination == Combination.OR:
        best = max(present_required, key=lambda k: keys.get(k).confidence)
        return {best}

    if spec.combination == Combination.N_OF_M:
        n = spec.n or 0
        ranked = sorted(present_required, key=lambda k: keys.get(k).confidence, reverse=True)
        return set(ranked[:n])

    raise ValueError(f"Lock '{spec.lock_id}': unknown combination {spec.combination!r}")


class DecisionEngine:
    def __init__(self, rules: DecisionRuleRegistry, lock_registry: LockRegistry) -> None:
        self.rules = rules
        self.lock_registry = lock_registry
        self._validate_rules_reference_known_locks()

    def _validate_rules_reference_known_locks(self) -> None:
        for rule in self.rules.all():
            for lock_id in set(rule.open_locks) | set(rule.closed_locks):
                if lock_id not in self.lock_registry:
                    raise UnknownLockError(
                        f"Decision rule '{rule.decision_id}' references lock '{lock_id}', "
                        f"which is not in the supplied LockRegistry"
                    )

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

    @staticmethod
    def _check_lineage(keys: KeySet, lock_results: Dict[str, LockResult]) -> str:
        """The fingerprint of the KeySet every lock result was evaluated from, or "" if none recorded one.

        Raises KeySetMismatchError when a result recorded a different KeySet than the one given, or when only some
        results recorded one (a half-bound run cannot be trusted either way).
        """
        recorded = {lid: lr.keyset_fingerprint for lid, lr in lock_results.items()}
        if not any(recorded.values()):
            return ""
        unrecorded = sorted(lid for lid, fp in recorded.items() if not fp)
        if unrecorded:
            raise KeySetMismatchError(
                "some lock results record a KeySet fingerprint and some do not "
                f"(none recorded for: {', '.join(unrecorded)}); the run is half bound"
            )
        fingerprint = getattr(keys, "fingerprint", None)
        if not callable(fingerprint):
            raise KeySetMismatchError(
                "the lock results record the KeySet they came from but this KeySet cannot fingerprint itself"
            )
        want = fingerprint()
        foreign = sorted(lid for lid, fp in recorded.items() if fp != want)
        if foreign:
            raise KeySetMismatchError(
                f"lock result(s) evaluated from a different KeySet than the one given: {', '.join(foreign)}"
            )
        return want

    def decide(
        self,
        entity_id: str,
        keys: KeySet,
        lock_results: Dict[str, LockResult],
        timestamp: datetime,
    ) -> Decision:
        if not isinstance(timestamp, datetime):
            raise TypeError(f"timestamp must be a datetime, got {type(timestamp).__name__}")
        for lock_id, lock_result in lock_results.items():
            if lock_result.lock_id != lock_id:
                raise ValueError(
                    f"lock_results[{lock_id!r}] carries a LockResult for {lock_result.lock_id!r}; "
                    f"a lock result must be filed under its own lock id"
                )

        foreign = sorted(
            (lock_id, lock_result.entity_id) for lock_id, lock_result in lock_results.items()
            if getattr(lock_result, "entity_id", "") and lock_result.entity_id != entity_id
        )
        if foreign:
            raise EntityMismatchError(
                f"decide was asked about entity {entity_id!r} but lock result(s) record another entity: "
                + ", ".join(f"{lock_id} is about {other!r}" for lock_id, other in foreign)
            )

        stale = sorted(lock_id for lock_id, lock_result in lock_results.items() if lock_result.stale)
        if stale:
            raise StaleLockResultError(
                f"zeta refused the observation behind lock result(s) as stale: {', '.join(stale)}; "
                f"no Decision is made from a refused observation"
            )

        keyset_fingerprint = self._check_lineage(keys, lock_results)

        rule = self._select_rule(lock_results)

        # Which specific Keys triggered this: only the Keys actually
        # NECESSARY to satisfy each of the matched rule's open_locks (see
        # _keys_necessary_for_lock -- this depends on each lock's
        # combination, not just "present and required"). closed_locks
        # contribute no positive Key evidence -- their contribution is the
        # ABSENCE of their required Keys, which has no confidence to average.
        triggering_key_names: Set[str] = set()
        for lock_id in rule.open_locks:
            spec = self.lock_registry.get(lock_id)
            triggering_key_names.update(_keys_necessary_for_lock(spec, keys))

        sorted_keys = sorted(triggering_key_names)
        confidences = [keys.get(k).confidence for k in sorted_keys]
        confidence = _geometric_mean(confidences)
        confidence_basis = "keys" if confidences else "absence"

        all_triggered_locks = tuple(sorted(set(rule.open_locks) | set(rule.closed_locks)))

        # Which of those locks CHANGED state this evaluation (LockResult.changed)
        # -- the closest faithful analogue to the source's escalation_required
        # ("a NEW escalation this cycle," not "still in an escalated state
        # from before"). Unlike the source's stateful EscalationPolicy dwell/
        # cooldown machinery, this doesn't require beta to hold any state of
        # its own -- zeta's LockResult already carries it.
        newly_triggered_locks = tuple(sorted(
            lock_id for lock_id in all_triggered_locks
            if lock_results.get(lock_id) is not None and lock_results[lock_id].changed
        ))

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

        decision = Decision(
            entity_id=entity_id,
            decision_id=rule.decision_id,
            decision=rule.decision,
            timestamp=timestamp,
            confidence=confidence,
            triggered_by_locks=all_triggered_locks,
            triggered_by_keys=tuple(sorted_keys),
            newly_triggered_locks=newly_triggered_locks,
            decision_fingerprint=fingerprint,
            reasoning=reasoning,
            reversal_conditions=rule.reversal_conditions,
            instructions=rule.instructions,
            confidence_basis=confidence_basis,
            keyset_fingerprint=keyset_fingerprint,
        )
        # A rule or Key configured with a str or float subclass must not come out as a valid Decision.
        decision.validate()
        decision = dataclasses.replace(decision, content_fingerprint=content_fingerprint(decision))
        decision.validate(check_fingerprint=True)
        return decision
