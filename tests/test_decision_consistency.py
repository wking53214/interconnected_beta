"""A Decision cannot say one thing about its triggering Keys and another about its confidence basis.

`confidence_basis` is derived from `triggered_by_keys` (keys present means "keys", none means "absence"). It is kept
out of every digest on purpose, so nothing downstream can see it go wrong. The only defence is that it cannot be
wrong: it is derived when omitted, refused when it contradicts the keys, and re-checked by `validate()` for a
Decision that skipped __post_init__ (unpickled, or built with object.__new__).
"""

import dataclasses
import math
from datetime import datetime

import pytest
from zeta import Combination, Key, KeySet, LockEvaluator, LockRegistry, LockSpec

from beta import Decision, DecisionEngine, DecisionRule, DecisionRuleRegistry

T0 = datetime(2026, 1, 1, 12, 0, 0)


def make(**over):
    base = dict(
        entity_id="p1", decision_id="r", decision="ESCALATE", timestamp=T0, confidence=0.9,
        triggered_by_locks=("sepsis_lock",), triggered_by_keys=("septic_shock",),
    )
    base.update(over)
    return Decision(**base)


def engine_decision(present: bool = True):
    locks = LockRegistry([LockSpec(lock_id="sepsis_lock", required_keys=("septic_shock",), combination=Combination.OR)])
    rules = DecisionRuleRegistry([
        DecisionRule(decision_id="escalate", decision="ESCALATE", open_locks=("sepsis_lock",), priority=10),
        DecisionRule(decision_id="safe", decision="SAFE", closed_locks=("sepsis_lock",), priority=0),
    ])
    keys = KeySet([Key(name="septic_shock", present=present, confidence=0.8)])
    results = LockEvaluator(locks).evaluate_all("p1", keys, T0)
    return DecisionEngine(rules, locks).decide("p1", keys, results, T0)


# --- valid and omitted -----------------------------------------------------------------------------------------

def test_matching_basis_is_accepted():
    assert make(confidence_basis="keys").confidence_basis == "keys"
    assert make(triggered_by_keys=(), confidence_basis="absence").confidence_basis == "absence"


def test_an_omitted_basis_is_derived_from_the_keys():
    assert make().confidence_basis == "keys"
    assert make(triggered_by_keys=()).confidence_basis == "absence"


def test_the_engine_always_produces_a_consistent_decision():
    for present in (True, False):
        d = engine_decision(present)
        assert d.confidence_basis == ("keys" if d.triggered_by_keys else "absence")
        d.validate()


# --- contradictory ---------------------------------------------------------------------------------------------

def test_a_basis_that_contradicts_the_keys_is_refused_at_construction():
    with pytest.raises(ValueError, match="triggered_by_keys implies 'keys'"):
        make(confidence_basis="absence")
    with pytest.raises(ValueError, match="triggered_by_keys implies 'absence'"):
        make(triggered_by_keys=(), confidence_basis="keys")


def test_an_unknown_basis_is_refused():
    with pytest.raises(ValueError, match="confidence_basis"):
        make(confidence_basis="trust-me")


def test_altering_the_keys_without_the_basis_is_refused():
    absent = make(triggered_by_keys=())
    with pytest.raises(ValueError, match="implies 'keys'"):
        dataclasses.replace(absent, triggered_by_keys=("septic_shock",))
    keyed = make()
    with pytest.raises(ValueError, match="implies 'absence'"):
        dataclasses.replace(keyed, triggered_by_keys=())


def test_altering_the_keys_and_asking_for_a_fresh_derivation_works():
    keyed = make()
    again = dataclasses.replace(keyed, triggered_by_keys=(), confidence_basis="")
    assert again.confidence_basis == "absence"


# --- a Decision that skipped __post_init__ is caught by validate() ---------------------------------------------

def _bypassed(**fields):
    d = object.__new__(Decision)
    base = dict(
        entity_id="p1", decision_id="r", decision="ESCALATE", timestamp=T0, confidence=0.9,
        triggered_by_locks=("sepsis_lock",), triggered_by_keys=("septic_shock",), newly_triggered_locks=(),
        decision_fingerprint="", audit_hash="", reasoning="", reversal_conditions=(), instructions="",
        confidence_basis="keys",
    )
    base.update(fields)
    for name, value in base.items():
        object.__setattr__(d, name, value)
    return d


def test_validate_catches_a_contradiction_that_bypassed_construction():
    bad = _bypassed(confidence_basis="absence")
    with pytest.raises(ValueError, match="implies 'keys'"):
        bad.validate()


def test_validate_passes_a_consistent_decision():
    _bypassed().validate()


@pytest.mark.parametrize("bad", [float("nan"), math.inf, -math.inf, 1.5, -0.1, True, "high", None])
def test_validate_refuses_a_confidence_that_is_not_a_finite_number_in_range(bad):
    with pytest.raises(ValueError, match="confidence must be a finite number in"):
        make(confidence=bad).validate()


def test_construction_alone_does_not_judge_confidence():
    """Only the basis is checked at construction; the confidence range is validate()'s job. Existing callers and
    the CNS connector tests build out-of-range confidences on purpose to see them refused at binding."""
    assert make(confidence=5.0).confidence == 5.0


# --- the fingerprint, opt in ----------------------------------------------------------------------------------

def test_fingerprint_check_passes_for_an_engine_decision():
    engine_decision().validate(check_fingerprint=True)


def test_fingerprint_check_catches_altered_keys_with_a_stale_fingerprint():
    d = engine_decision()
    forged = dataclasses.replace(d, triggered_by_keys=("ghost",))
    forged.validate()  # internally consistent basis, so the default check is satisfied
    with pytest.raises(ValueError, match="decision_fingerprint does not match"):
        forged.validate(check_fingerprint=True)


def test_fingerprint_check_refuses_an_empty_fingerprint():
    with pytest.raises(ValueError, match="no decision_fingerprint"):
        make().validate(check_fingerprint=True)


# --- validate() judges the types too: a Decision with a str where a tuple belongs is not a Decision ---------------

@pytest.mark.parametrize("field, bad", [
    ("entity_id", None), ("entity_id", 7), ("decision_id", None), ("decision", b"ESCALATE"),
    ("triggered_by_keys", "septic_shock"), ("triggered_by_locks", "sepsis_lock"), ("newly_triggered_locks", "x"),
    ("triggered_by_keys", (1, 2)), ("reversal_conditions", "closes"), ("reasoning", b"bytes"), ("instructions", None),
    ("decision_fingerprint", 5), ("timestamp", "2026-01-01"), ("timestamp", None),
])
def test_validate_refuses_a_field_of_the_wrong_type(field, bad):
    over = {field: bad}
    if field == "triggered_by_keys":
        over["confidence_basis"] = ""  # let construction derive, so it is validate() that must refuse
    with pytest.raises(ValueError, match=f"Decision.{field} must be"):
        make(**over).validate()


def test_validate_accepts_lists_for_the_tuple_fields_since_json_gives_lists():
    d = make()
    object.__setattr__(d, "triggered_by_locks", ["sepsis_lock"])
    d.validate()
