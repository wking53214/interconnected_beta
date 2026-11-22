"""The trust boundary between zeta's lock results and beta's Decision.

Before this change, decide() accepted any LockResults a caller built. With an empty KeySet and two hand-typed "closed"
results it returned DISCHARGE_SAFE at confidence 1.0. A real zeta evaluation of an empty KeySet did the same, because
a Key nobody reported reads to zeta exactly like a Key checked and found absent.

Now:
  - decide_from_keys evaluates the locks itself and refuses a KeySet that does not report every required Key, before
    any lock state changes;
  - decide refuses hand-fed lock results unless test_only=True, and stamps that Decision "supplied-test";
  - an evaluated Decision records digests that let anyone holding the prior lock state and the KeySet replay it.
"""
import dataclasses
from datetime import datetime, timedelta

import pytest
from zeta import Combination, Key, KeySet, LockRegistry, LockResult, LockSpec, LockStateStore

from beta import (
    Evaluation,
    PROVENANCE_EVALUATED,
    PROVENANCE_SUPPLIED_TEST,
    DecisionEngine,
    DecisionRule,
    DecisionRuleRegistry,
    MissingEvidenceError,
    NoMatchingRuleError,
    SuppliedLockResultsRefused,
    content_fingerprint,
    lock_results_digest,
)
from beta.engine import EVALUATOR

T0 = datetime(2026, 11, 22, 8, 0, 0)
SEPSIS = ("septic_shock", "respiratory_distress")
VITALS = ("fever", "tachycardia")


def locks():
    return LockRegistry([
        LockSpec(lock_id="sepsis_lock", required_keys=SEPSIS, combination=Combination.OR,
                 dwell_threshold=3, force=True),
        LockSpec(lock_id="abnormal_vitals_lock", required_keys=VITALS, combination=Combination.OR,
                 dwell_threshold=2),
    ])


def rules():
    return DecisionRuleRegistry([
        DecisionRule(decision_id="escalate", decision="ESCALATE", open_locks=("sepsis_lock",), priority=10),
        DecisionRule(decision_id="hold", decision="HOLD", open_locks=("abnormal_vitals_lock",),
                     closed_locks=("sepsis_lock",), priority=5),
        DecisionRule(decision_id="discharge", decision="DISCHARGE_SAFE",
                     closed_locks=("sepsis_lock", "abnormal_vitals_lock"), priority=0),
    ])


def engine(store=None):
    registry = locks()
    return DecisionEngine(rules(), registry, store)


def reading(**present):
    """A complete KeySet: every required Key reported, present only where named."""
    return KeySet([Key(name=n, present=bool(present.get(n, False))) for n in SEPSIS + VITALS])


CLOSED = {
    "sepsis_lock": LockResult(lock_id="sepsis_lock", open=False, changed=False, forced=False),
    "abnormal_vitals_lock": LockResult(lock_id="abnormal_vitals_lock", open=False, changed=False, forced=False),
}


# ------------------------------------------------------------------ the hand-in slot is closed

def test_hand_typed_all_clear_results_are_refused_by_default():
    with pytest.raises(SuppliedLockResultsRefused, match="decide_from_keys"):
        engine().decide("p1", KeySet([]), CLOSED, T0)


@pytest.mark.parametrize("flag", [1, "yes", "True", None])
def test_only_the_literal_true_opens_the_test_path(flag):
    with pytest.raises(SuppliedLockResultsRefused):
        engine().decide("p1", KeySet([]), CLOSED, T0, test_only=flag)


def test_the_test_path_still_decides_but_stamps_the_decision():
    d = engine().decide("p1", KeySet([]), CLOSED, T0, test_only=True)
    assert d.decision == "DISCHARGE_SAFE"
    assert d.provenance == PROVENANCE_SUPPLIED_TEST
    assert d.prior_state_digest == ""
    assert len(d.lock_results_digest) == 64
    d.validate(check_fingerprint=True)


def test_relabelling_a_test_decision_as_evaluated_is_caught():
    d = engine().decide("p1", KeySet([]), CLOSED, T0, test_only=True)
    relabelled = dataclasses.replace(d, provenance=PROVENANCE_EVALUATED, prior_state_digest="a" * 64)
    with pytest.raises(ValueError, match="content_fingerprint"):
        relabelled.validate(check_fingerprint=True)


def test_an_unknown_provenance_is_refused():
    d = engine().decide("p1", KeySet([]), CLOSED, T0, test_only=True)
    with pytest.raises(ValueError, match="provenance"):
        dataclasses.replace(d, provenance="trusted").validate()


# ------------------------------------------------------------------ missing evidence means no decision

def test_an_empty_keyset_is_refused_not_discharged():
    e = engine()
    with pytest.raises(MissingEvidenceError, match="septic_shock"):
        e.decide_from_keys("p1", KeySet([]), T0)
    assert e.state_store.snapshot("p1") == {}  # refused before any lock state existed


def test_one_unreported_key_is_enough_to_refuse():
    keys = KeySet([Key(name=n, present=False) for n in SEPSIS + VITALS if n != "tachycardia"])
    with pytest.raises(MissingEvidenceError, match="tachycardia"):
        engine().decide_from_keys("p1", keys, T0)


def test_checked_and_clear_is_a_real_discharge():
    d = engine().decide_from_keys("p1", reading(), T0)
    assert d.decision == "DISCHARGE_SAFE"
    assert d.provenance == PROVENANCE_EVALUATED
    d.validate(check_fingerprint=True)


def test_missing_readings_do_not_count_as_clean_readings_toward_closing_a_lock():
    e = engine()
    assert e.decide_from_keys("p1", reading(septic_shock=True), T0).decision == "ESCALATE"
    for i in range(1, 4):  # three empty observations: refused, and they must not advance the closing dwell
        with pytest.raises(MissingEvidenceError):
            e.decide_from_keys("p1", KeySet([]), T0 + timedelta(hours=i))
    # One genuine clean reading is one of the three sepsis_lock needs to close: still escalated.
    assert e.decide_from_keys("p1", reading(), T0 + timedelta(hours=4)).decision == "ESCALATE"


# ------------------------------------------------------------------ one step, and replayable

def test_a_failed_decision_puts_the_lock_state_back():
    only_when_clear = DecisionRuleRegistry([
        DecisionRule(decision_id="clear", decision="CLEAR", closed_locks=("sepsis_lock",)),
    ])
    e = DecisionEngine(only_when_clear, locks())
    e.decide_from_keys("p1", reading(), T0)
    before = e.state_store.snapshot("p1")
    with pytest.raises(NoMatchingRuleError):  # sepsis forces open, and no rule covers an open sepsis_lock
        e.decide_from_keys("p1", reading(septic_shock=True), T0 + timedelta(hours=1))
    assert e.state_store.snapshot("p1") == before
    # The same observation, retried under rules that cover it, counts once: sepsis opens now, not before.
    assert engine(e.state_store).decide_from_keys(
        "p1", reading(septic_shock=True), T0 + timedelta(hours=1)).decision == "ESCALATE"


def test_anyone_with_the_prior_state_and_the_keys_can_replay_the_evaluation():
    original = engine()
    original.decide_from_keys("p1", reading(fever=True), T0)
    prior = original.state_store.snapshot("p1")
    keys = reading(fever=True, tachycardia=True)
    recorded = original.decide_from_keys("p1", keys, T0 + timedelta(hours=1))

    store = LockStateStore()
    store.restore("p1", prior)
    replayed = engine(store).decide_from_keys("p1", keys, T0 + timedelta(hours=1))

    assert replayed.prior_state_digest == recorded.prior_state_digest
    assert replayed.lock_results_digest == recorded.lock_results_digest
    assert replayed.content_fingerprint == recorded.content_fingerprint == content_fingerprint(recorded)


def test_a_different_prior_state_gives_a_different_record():
    a = engine().decide_from_keys("p1", reading(fever=True), T0)
    e = engine()
    e.decide_from_keys("p1", reading(fever=True), T0 - timedelta(hours=1))
    b = e.decide_from_keys("p1", reading(fever=True), T0)
    assert a.prior_state_digest != b.prior_state_digest
    assert a.content_fingerprint != b.content_fingerprint


def test_decide_from_keys_wants_a_real_keyset():
    with pytest.raises(TypeError):
        engine().decide_from_keys("p1", {"fever": True}, T0)


# ------------------------------------------------------------------ the results are an output, not an input

def test_evaluate_and_decide_returns_the_results_the_decision_rests_on():
    ev = engine().evaluate_and_decide("p1", reading(fever=True), T0)
    assert isinstance(ev, Evaluation)
    assert set(ev.lock_results) == {"sepsis_lock", "abnormal_vitals_lock"}
    assert ev.decision.lock_results_digest == lock_results_digest(ev.lock_results, EVALUATOR)
    assert all(r.entity_id == "p1" and r.keyset_fingerprint for r in ev.lock_results.values())


def test_handing_the_returned_results_back_is_refused_like_any_others():
    e = engine()
    ev = e.evaluate_and_decide("p1", reading(fever=True), T0)
    with pytest.raises(SuppliedLockResultsRefused):
        e.decide("p1", reading(fever=True), ev.lock_results, T0)


def test_editing_the_returned_results_does_not_touch_the_engine():
    e = engine()
    ev = e.evaluate_and_decide("p1", reading(septic_shock=True), T0)
    ev.lock_results.clear()
    assert e.state_store.snapshot("p1")["sepsis_lock"].open is True
