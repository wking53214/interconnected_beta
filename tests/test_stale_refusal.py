"""A lock result zeta refused as stale never becomes a Decision.

zeta answers an observation older than the newest it applied with `stale=True` and leaves the lock state alone.
Without this check beta read such a result like any other: replayed old sick readings, refused by zeta, came out
of beta as a recorded DISCHARGE_SAFE built from the unchanged earlier state.
"""

from datetime import datetime, timedelta

import pytest
from zeta import Combination, Key, KeySet, LockEvaluator, LockRegistry, LockSpec

from beta import DecisionEngine, DecisionRule, DecisionRuleRegistry
from beta import StaleLockResultError

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


SICK = KeySet([Key(name="septic_shock", present=True), Key(name="fever", present=True)])
WELL = KeySet([Key(name="septic_shock", present=False), Key(name="fever", present=False)])


def test_replayed_old_readings_do_not_become_a_discharge():
    locks, engine = build()
    ev = LockEvaluator(locks)
    ev.evaluate_all("p1", WELL, T0)  # the newest applied observation: all closed
    stale = ev.evaluate_all("p1", SICK, T0 - timedelta(hours=2))  # a late replay of old sick readings
    assert all(r.stale for r in stale.values()) and not any(r.open for r in stale.values())
    with pytest.raises(StaleLockResultError, match="sepsis_lock"):
        engine.decide("p1", SICK, stale, T0)


def test_one_stale_result_among_fresh_ones_still_refuses():
    locks, engine = build()
    ev = LockEvaluator(locks)
    fresh = ev.evaluate_all("p1", WELL, T0)
    ev.evaluate("p1", SICK, "other_lock", T0 + timedelta(hours=1))  # moves other_lock's newest time forward
    mixed = dict(fresh)
    mixed["other_lock"] = ev.evaluate("p1", SICK, "other_lock", T0)  # older than what other_lock applied
    assert mixed["other_lock"].stale and not mixed["sepsis_lock"].stale
    with pytest.raises(StaleLockResultError, match="other_lock"):
        engine.decide("p1", WELL, mixed, T0)


def test_the_error_names_every_stale_lock_in_order():
    locks, engine = build()
    ev = LockEvaluator(locks)
    ev.evaluate_all("p1", WELL, T0)
    stale = ev.evaluate_all("p1", SICK, T0 - timedelta(minutes=1))
    with pytest.raises(StaleLockResultError) as caught:
        engine.decide("p1", SICK, stale, T0)
    assert "other_lock, sepsis_lock" in str(caught.value)


def test_fresh_results_still_decide():
    locks, engine = build()
    fresh = LockEvaluator(locks).evaluate_all("p1", SICK, T0)
    assert engine.decide("p1", SICK, fresh, T0).decision == "ESCALATE"


def test_the_same_timestamp_is_not_stale_and_still_decides():
    locks, engine = build()
    ev = LockEvaluator(locks)
    ev.evaluate_all("p1", SICK, T0)
    again = ev.evaluate_all("p1", SICK, T0)
    assert not any(r.stale for r in again.values())
    assert engine.decide("p1", SICK, again, T0).decision == "ESCALATE"
