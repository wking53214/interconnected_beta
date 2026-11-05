"""A Decision carries exact built-in types, and decide() never returns one that does not.

A str or float subclass can print one value and hold another (an overridden __format__, __str__, __repr__ or
__float__), so a renderer and a hasher would see different text. validate() therefore requires exact types, and
DecisionEngine.decide validates the Decision it builds before handing it back, so a subclass planted in a
DecisionRule configuration cannot come out as a valid, fingerprinted Decision.
"""

from datetime import datetime

import pytest
from zeta import Combination, Key, KeySet, LockEvaluator, LockRegistry, LockSpec

from beta import Decision, DecisionEngine, DecisionRule, DecisionRuleRegistry

T0 = datetime(2026, 1, 1, 12, 0, 0)


class LyingStr(str):
    def __format__(self, spec):
        return "Emergency room now."

    def __str__(self):
        return "Emergency room now."


class LyingFloat(float):
    def __repr__(self):
        return "0.99"

    def __float__(self):
        return 0.99


class LyingTime(datetime):
    def isoformat(self, *a, **k):
        return "2026-10-01T08:00:00"


def make(**over):
    base = dict(
        entity_id="p1", decision_id="r", decision="ESCALATE", timestamp=T0, confidence=0.9,
        triggered_by_locks=("sepsis_lock",), triggered_by_keys=("septic_shock",),
    )
    base.update(over)
    return Decision(**base)


def engine_with(**rule_over):
    locks = LockRegistry([LockSpec(lock_id="sepsis_lock", required_keys=("septic_shock",), combination=Combination.OR)])
    fields = dict(decision_id="escalate", decision="ESCALATE", open_locks=("sepsis_lock",), priority=10)
    fields.update(rule_over)
    rules = DecisionRuleRegistry([DecisionRule(**fields)])
    keys = KeySet([Key(name="septic_shock", present=True, confidence=0.8)])
    results = LockEvaluator(locks).evaluate_all("p1", keys, T0)
    return DecisionEngine(rules, locks), keys, results


def test_the_reproduced_attack_a_str_subclass_in_a_rule_does_not_come_out_of_decide():
    engine, keys, results = engine_with(instructions=LyingStr("Send home."))
    with pytest.raises(ValueError, match="instructions must be a str"):
        engine.decide("p1", keys, results, T0)


@pytest.mark.parametrize("field", ["decision_id", "decision", "instructions"])
def test_a_str_subclass_in_any_rule_text_is_refused_by_decide(field):
    engine, keys, results = engine_with(**{field: LyingStr("x")})
    with pytest.raises(ValueError, match=f"{field} must be a str"):
        engine.decide("p1", keys, results, T0)


def test_a_str_subclass_in_reversal_conditions_is_refused_by_decide():
    engine, keys, results = engine_with(reversal_conditions=("ok", LyingStr("x")))
    with pytest.raises(ValueError, match="reversal_conditions"):
        engine.decide("p1", keys, results, T0)


def test_an_ordinary_rule_still_decides_and_validates():
    engine, keys, results = engine_with(instructions="Go.", reversal_conditions=("closes",))
    d = engine.decide("p1", keys, results, T0)
    d.validate(check_fingerprint=True)
    assert type(d.instructions) is str


@pytest.mark.parametrize("field", ["entity_id", "decision_id", "decision", "reasoning", "instructions",
                                   "decision_fingerprint", "content_fingerprint", "keyset_fingerprint"])
def test_validate_refuses_a_str_subclass_field(field):
    with pytest.raises(ValueError, match=f"{field} must be a str"):
        make(**{field: LyingStr("")}).validate()


@pytest.mark.parametrize("field", ["triggered_by_locks", "triggered_by_keys", "newly_triggered_locks",
                                   "reversal_conditions"])
def test_validate_refuses_a_str_subclass_tuple_element(field):
    over = {field: (LyingStr("a"),)}
    if field == "triggered_by_keys":
        over["confidence_basis"] = "keys"
    with pytest.raises(ValueError, match=field):
        make(**over).validate()


def test_validate_refuses_a_float_subclass_confidence():
    with pytest.raises(ValueError, match="confidence"):
        make(confidence=LyingFloat(0.01)).validate()


def test_validate_refuses_a_datetime_subclass_timestamp():
    with pytest.raises(ValueError, match="timestamp must be a datetime"):
        make(timestamp=LyingTime(2026, 1, 1)).validate()


def test_validate_still_accepts_int_and_float_confidence():
    make(confidence=1).validate()
    make(confidence=0.5).validate()
