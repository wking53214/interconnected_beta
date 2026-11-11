"""Decision.validate() requires exact str for confidence_basis and audit_hash (Step 1, N6)."""

from datetime import datetime

import pytest
from zeta import Combination, Key, KeySet, LockEvaluator, LockRegistry, LockSpec

from beta import Decision, DecisionEngine, DecisionRule, DecisionRuleRegistry

T0 = datetime(2026, 1, 1, 12, 0, 0)


class SubStr(str):
    pass


def make(**over):
    base = dict(
        entity_id="p1", decision_id="r", decision="ESCALATE", timestamp=T0, confidence=0.9,
        triggered_by_locks=("sepsis_lock",), triggered_by_keys=("septic_shock",),
    )
    base.update(over)
    return Decision(**base)


def planted(name, value):
    d = make()
    object.__setattr__(d, name, value)
    return d


def test_str_subclass_basis_is_refused_by_validate():
    d = make(confidence_basis=SubStr("keys"))
    with pytest.raises(ValueError, match="confidence_basis"):
        d.validate()


def test_str_subclass_audit_hash_is_refused_by_validate():
    d = make(audit_hash=SubStr("abc"))
    with pytest.raises(ValueError, match="audit_hash"):
        d.validate()


@pytest.mark.parametrize("value", [1, None, b"keys"])
def test_non_str_basis_is_refused_by_validate(value):
    with pytest.raises(ValueError, match="confidence_basis"):
        planted("confidence_basis", value).validate()


@pytest.mark.parametrize("value", [1, None, b""])
def test_non_str_audit_hash_is_refused_by_validate(value):
    with pytest.raises(ValueError, match="audit_hash"):
        planted("audit_hash", value).validate()


def test_legacy_decision_with_defaults_still_validates():
    d = make()
    assert d.audit_hash == "" and d.confidence_basis == "keys"
    d.validate()
    make(triggered_by_keys=()).validate()


def test_engine_produced_decision_still_validates():
    locks = LockRegistry([LockSpec(lock_id="sepsis_lock", required_keys=("septic_shock",), combination=Combination.OR)])
    rules = DecisionRuleRegistry([DecisionRule(decision_id="e", decision="ESCALATE", open_locks=("sepsis_lock",), priority=10)])
    keys = KeySet([Key(name="septic_shock", present=True, confidence=0.8)])
    results = LockEvaluator(locks).evaluate_all("p1", keys, T0)
    decision = DecisionEngine(rules, locks).decide("p1", keys, results, T0)
    decision.validate()
    assert type(decision.confidence_basis) is str and type(decision.audit_hash) is str
