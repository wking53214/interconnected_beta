"""decide() refuses lock results that were evaluated from a different KeySet than the one it is given.

Before this, decide(entity, keys, lock_results, ...) took its arguments independently: with well keys and a sick
patient's lock results it returned ESCALATE with no triggering keys, confidence 1.0 and basis "absence", a Decision
that reads as sound and is about nobody's evidence. Zeta now records the fingerprint of the KeySet each result came
from; decide compares it with the KeySet it was handed, and a Decision records which KeySet it was made from.
"""
from dataclasses import replace
from datetime import datetime

import pytest
from zeta import Combination, Key, KeySet, LockEvaluator, LockRegistry, LockResult, LockSpec

from beta import Decision, DecisionEngine, DecisionRule, DecisionRuleRegistry, KeySetMismatchError

T0 = datetime(2026, 1, 1, 12, 0, 0)


def build():
    locks = LockRegistry([
        LockSpec(lock_id="sepsis_lock", required_keys=("septic_shock",), combination=Combination.OR),
        LockSpec(lock_id="other_lock", required_keys=("fever",), combination=Combination.OR),
    ])
    rules = DecisionRuleRegistry([
        DecisionRule(decision_id="escalate", decision="ESCALATE", open_locks=("sepsis_lock",), priority=10),
        DecisionRule(decision_id="safe", decision="DISCHARGE_SAFE", closed_locks=("sepsis_lock",), priority=0),
    ])
    return locks, DecisionEngine(rules, locks)


def keys(present, reason="r"):
    return KeySet([Key(name="septic_shock", present=present, reason=reason), Key(name="fever", present=False, reason=reason)])


SICK, WELL = keys(True), keys(False)


def results_for(ks, entity="p1"):
    locks, _ = build()
    return LockEvaluator(locks).evaluate_all(entity, ks, T0)


def test_matching_keys_and_results_decide_and_the_decision_records_the_keyset():
    _, engine = build()
    d = engine.decide("p1", SICK, results_for(SICK), T0)
    assert d.decision == "ESCALATE" and d.keyset_fingerprint == SICK.fingerprint()
    d.validate()


def test_well_keys_with_a_sick_patients_results_are_refused_not_decided():
    """The reproduced attack: this used to return ESCALATE, keys (), confidence 1.0, basis 'absence'."""
    _, engine = build()
    with pytest.raises(KeySetMismatchError, match="evaluated from a different KeySet.*sepsis_lock"):
        engine.decide("p1", WELL, results_for(SICK), T0)


def test_the_same_present_keys_from_other_readings_are_still_a_different_keyset():
    _, engine = build()
    with pytest.raises(KeySetMismatchError):
        engine.decide("p1", keys(True, reason="HR 149"), results_for(keys(True, reason="HR 148")), T0)


def test_one_foreign_result_among_matching_ones_is_named():
    _, engine = build()
    res = dict(results_for(SICK))
    res["other_lock"] = results_for(WELL)["other_lock"]
    with pytest.raises(KeySetMismatchError) as caught:
        engine.decide("p1", SICK, res, T0)
    assert "other_lock" in str(caught.value) and "sepsis_lock" not in str(caught.value)


def test_a_mix_of_results_that_record_a_fingerprint_and_results_that_do_not_is_refused():
    _, engine = build()
    res = dict(results_for(SICK))
    res["other_lock"] = replace(res["other_lock"], keyset_fingerprint="")
    with pytest.raises(KeySetMismatchError, match="some lock results record a KeySet fingerprint and some do not"):
        engine.decide("p1", SICK, res, T0)


def test_results_that_record_no_fingerprint_at_all_still_decide_but_the_decision_says_it_is_unbound():
    """Hand-built results (or an older zeta) keep working; they just cannot claim a KeySet."""
    _, engine = build()
    bare = {lid: LockResult(lock_id=lid, open=r.open, changed=r.changed, forced=r.forced) for lid, r in results_for(SICK).items()}
    d = engine.decide("p1", SICK, bare, T0)
    assert d.decision == "ESCALATE" and d.keyset_fingerprint == ""


def test_a_stale_result_is_still_refused_first():
    from beta import StaleLockResultError

    _, engine = build()
    res = {lid: replace(r, stale=True) for lid, r in results_for(SICK).items()}
    with pytest.raises(StaleLockResultError):
        engine.decide("p1", SICK, res, T0)


def test_validate_checks_the_recorded_keyset_fingerprint_is_empty_or_a_full_sha256():
    d = Decision(entity_id="p1", decision_id="r", decision="X", timestamp=T0, confidence=1.0,
                 triggered_by_locks=("l",), triggered_by_keys=("k",), keyset_fingerprint=SICK.fingerprint())
    d.validate()
    for bad in ("short", "A" * 64, "a" * 64 + "\n", 5):
        with pytest.raises(ValueError, match="keyset_fingerprint"):
            replace(d, keyset_fingerprint=bad).validate()
    replace(d, keyset_fingerprint="").validate()
