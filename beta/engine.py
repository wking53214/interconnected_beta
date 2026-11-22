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

Where lock results come from (the trust boundary):
  - decide_from_keys(entity_id, keys, timestamp) is the normal path. The
    engine runs zeta's LockEvaluator itself, over its own LockRegistry and
    its own LockStateStore, so there is no slot through which lock results
    can be handed in. Before it evaluates anything it refuses a KeySet that
    does not report every Key some lock requires (present or not), so
    "never checked" is not read as "checked and clear". The Decision records
    provenance "evaluated", a digest of the lock results and a digest of the
    lock states just before the evaluation, so the evaluation can be replayed.
  - decide(entity_id, keys, lock_results, timestamp, test_only=True) accepts
    hand-fed lock results, for tests only. Without test_only=True it refuses.
    Its Decision records provenance "supplied-test" and must never be acted on
    or recorded as a real one. It does not apply the evidence completeness
    check, because it exists to exercise rule logic in isolation.
  Signed lock results: an engine built with lock_result_verifier (the
  operator's verify callable) refuses, with LockResultSignatureError, any lock
  result whose signature is missing or does not check out, on both paths, and
  makes no Decision. beta rebuilds the signed bytes itself (beta.signing). With
  a verifier and no lock_result_signer, the engine refuses before it evaluates
  anything; otherwise the refusal comes after zeta signs, inside the
  all-or-nothing step, so the entity's lock states are put back. With no
  verifier (the default) nothing is checked, as before, and that setup is
  unprotected.
  Limits: anyone who can run code in this process can still construct a
  rigged LockStateStore, call the test path, or call the signer; the
  provenance stamp makes the second visible but does not prevent it, and a
  signature proves who held the signer, not that the evaluation was honest
  (a separate signer process is the next step). An outside record of what was
  decided is delta's.
"""

import math
import dataclasses
from datetime import datetime
from typing import Callable, Dict, List, Optional, Set

import zeta
from zeta import Combination, KeySet, LockEvaluator, LockRegistry, LockResult, LockSpec, LockStateStore

from .fingerprint import content_fingerprint, decision_fingerprint, lock_results_digest, lock_state_digest
from .rules import DecisionRule, DecisionRuleRegistry
from .signing import lock_result_signature_ok
from .verdict import PROVENANCE_EVALUATED, PROVENANCE_SUPPLIED_TEST, Decision

# Named in lock_results_digest so a digest says which evaluator produced the results it covers.
EVALUATOR = f"zeta/{getattr(zeta, '__version__', 'unknown')}"


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


@dataclasses.dataclass(frozen=True)
class Evaluation:
    """What decide_from_keys produced: the Decision and the lock results the engine evaluated for it.

    The lock results are an OUTPUT, for a caller that must bind or record them (CNS, delta). Handing them back to the
    engine is refused like any other lock results. ``decision.lock_results_digest`` is the digest of exactly these, so a
    consumer can check a copy against the Decision (``beta.lock_results_digest(results, beta.engine.EVALUATOR)``).
    """

    decision: Decision
    lock_results: Dict[str, LockResult]


class SuppliedLockResultsRefused(Exception):
    """decide was handed lock results without test_only=True.

    Fail closed: lock results built outside the engine are paperwork the engine cannot check. The normal path is
    decide_from_keys, where the engine evaluates the locks itself. Hand-fed results are accepted only with
    test_only=True, and the Decision is stamped provenance "supplied-test".
    """


class LockResultSignatureError(Exception):
    """A verifier is plugged in and a lock result's signature is missing or does not check out.

    Fail closed: no Decision is made. On the normal path the entity's lock states are put back (or, with no signer,
    never touched), so a retry with a working signer counts the observation once.
    """


class MissingEvidenceError(Exception):
    """The KeySet does not report a Key that some lock requires.

    Fail closed: a Key that was never reported reads to zeta exactly like a Key that was checked and found absent, so
    a closed lock (and a "safe" Decision) could rest on evidence nobody collected. Report every required Key, with
    present=False when it was checked and not found. Raised before any lock state changes.
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
    def __init__(
        self,
        rules: DecisionRuleRegistry,
        lock_registry: LockRegistry,
        state_store: Optional[LockStateStore] = None,
        *,
        lock_result_signer: Optional[Callable[[bytes], bytes]] = None,
        lock_result_verifier: Optional[Callable[[bytes, bytes], bool]] = None,
    ) -> None:
        # lock_result_signer is handed to zeta's evaluator, which signs every result with it. lock_result_verifier is
        # the operator's checker; with one plugged in, unsigned or badly signed lock results are refused. Both default
        # to None: nothing signed, nothing checked, behaviour as before.
        for name, fn in (("lock_result_signer", lock_result_signer), ("lock_result_verifier", lock_result_verifier)):
            if fn is not None and not callable(fn):
                raise TypeError(f"{name} must be callable or None; got {type(fn).__name__}")
        self.rules = rules
        self.lock_registry = lock_registry
        self._validate_rules_reference_known_locks()
        self.lock_result_verifier = lock_result_verifier
        # The engine's own evaluator, over the same registry its rules were checked against. state_store lets a caller
        # keep lock state across engines or restarts; it is trusted (see the module docstring's limits).
        self.lock_evaluator = LockEvaluator(lock_registry, state_store, signer=lock_result_signer)

    @property
    def state_store(self) -> LockStateStore:
        return self.lock_evaluator.state_store

    def _check_evidence_complete(self, keys: KeySet) -> None:
        missing = sorted(
            (spec.lock_id, name)
            for spec in self.lock_registry.all()
            for name in spec.required_keys
            if keys.get(name) is None
        )
        if missing:
            raise MissingEvidenceError(
                "the KeySet does not report Key(s) a lock requires, so their absence was never checked: "
                + ", ".join(f"{name} (for {lock_id})" for lock_id, name in missing)
                + "; report each one, with present=False if it was checked and not found"
            )

    def _check_signatures(self, lock_results: Dict[str, LockResult]) -> None:
        if self.lock_result_verifier is None:
            return
        missing = sorted(lid for lid, lr in lock_results.items() if not getattr(lr, "signature", b""))
        bad = sorted(lid for lid, lr in lock_results.items()
                     if lid not in missing and not lock_result_signature_ok(lr, self.lock_result_verifier))
        if missing or bad:
            raise LockResultSignatureError(
                "a lock result signature checker is plugged in and lock result(s) failed it"
                + (f"; unsigned: {', '.join(missing)}" if missing else "")
                + (f"; signature does not check out: {', '.join(bad)}" if bad else "")
                + "; no Decision is made"
            )

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

    def decide_from_keys(self, entity_id: str, keys: KeySet, timestamp: datetime) -> Decision:
        """The normal path: evaluate the locks from ``keys`` here, then decide. See evaluate_and_decide."""
        return self.evaluate_and_decide(entity_id, keys, timestamp).decision

    def evaluate_and_decide(self, entity_id: str, keys: KeySet, timestamp: datetime) -> Evaluation:
        """Evaluate the locks from ``keys`` here, decide, and return both the Decision and the lock results.

        Refuses before touching any lock state if ``keys`` does not report every Key a lock requires. The evaluation
        and the Decision are one step: if deciding raises, the entity's lock states are put back, so a retry of the
        same observation counts once (zeta's own rule for evaluate_all).
        """
        if not isinstance(timestamp, datetime):
            raise TypeError(f"timestamp must be a datetime, got {type(timestamp).__name__}")
        if not isinstance(keys, KeySet):
            raise TypeError(f"keys must be a zeta KeySet, got {type(keys).__name__}")
        if self.lock_result_verifier is not None and self.lock_evaluator.signer is None:
            raise LockResultSignatureError(
                "a lock result signature checker is plugged in but no signer is, so every lock result would be "
                "unsigned; refused before any lock state changes, no Decision is made"
            )
        self._check_evidence_complete(keys)
        store = self.state_store
        with store.lock:
            before = store.snapshot(entity_id)
            prior = lock_state_digest(before)
            try:
                lock_results = self.lock_evaluator.evaluate_all(entity_id, keys, timestamp)
                decision = self._decide(entity_id, keys, lock_results, timestamp,
                                        provenance=PROVENANCE_EVALUATED, prior_state_digest=prior)
                return Evaluation(decision=decision, lock_results=dict(lock_results))
            except BaseException:
                store.restore(entity_id, before)
                raise

    def decide(
        self,
        entity_id: str,
        keys: KeySet,
        lock_results: Dict[str, LockResult],
        timestamp: datetime,
        *,
        test_only: bool = False,
    ) -> Decision:
        """TEST ONLY: decide from lock results handed in by the caller.

        Refused unless ``test_only=True``. The Decision is stamped provenance "supplied-test". Use decide_from_keys for
        any Decision that will be acted on or recorded.
        """
        if test_only is not True:
            raise SuppliedLockResultsRefused(
                "decide does not accept lock results it did not evaluate; use decide_from_keys(entity_id, keys, "
                "timestamp). Hand-fed lock results are for tests only: pass test_only=True, and the Decision is "
                "stamped provenance 'supplied-test'"
            )
        return self._decide(entity_id, keys, lock_results, timestamp,
                            provenance=PROVENANCE_SUPPLIED_TEST, prior_state_digest="")

    def _decide(
        self,
        entity_id: str,
        keys: KeySet,
        lock_results: Dict[str, LockResult],
        timestamp: datetime,
        *,
        provenance: str,
        prior_state_digest: str,
    ) -> Decision:
        if not isinstance(timestamp, datetime):
            raise TypeError(f"timestamp must be a datetime, got {type(timestamp).__name__}")
        self._check_signatures(lock_results)
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
            provenance=provenance,
            lock_results_digest=lock_results_digest(lock_results, EVALUATOR),
            prior_state_digest=prior_state_digest,
        )
        # A rule or Key configured with a str or float subclass must not come out as a valid Decision.
        decision.validate()
        decision = dataclasses.replace(decision, content_fingerprint=content_fingerprint(decision))
        decision.validate(check_fingerprint=True)
        return decision
