from datetime import datetime

import pytest
from zeta import LockResult

from beta.rules import DecisionRule, DecisionRuleRegistry


def lr(open_, changed=False, forced=False, reasons=None):
    return LockResult(lock_id="x", open=open_, changed=changed, forced=forced, reasons=reasons or [])


# --- DecisionRule validation ---

def test_rule_requires_decision_id():
    with pytest.raises(ValueError):
        DecisionRule(decision_id="", decision="X", open_locks=("a",))


def test_rule_requires_decision_value():
    with pytest.raises(ValueError):
        DecisionRule(decision_id="r1", decision="", open_locks=("a",))


def test_rule_requires_at_least_one_lock_requirement():
    with pytest.raises(ValueError):
        DecisionRule(decision_id="r1", decision="X")


def test_rule_rejects_lock_in_both_open_and_closed():
    with pytest.raises(ValueError):
        DecisionRule(decision_id="r1", decision="X", open_locks=("a",), closed_locks=("a",))


# --- matches() ---

def test_matches_true_when_all_open_locks_are_open():
    rule = DecisionRule(decision_id="r1", decision="ESCALATE", open_locks=("sepsis_lock",))
    assert rule.matches({"sepsis_lock": lr(True)}) is True


def test_matches_false_when_required_open_lock_is_closed():
    rule = DecisionRule(decision_id="r1", decision="ESCALATE", open_locks=("sepsis_lock",))
    assert rule.matches({"sepsis_lock": lr(False)}) is False


def test_matches_true_when_all_closed_locks_are_closed():
    rule = DecisionRule(decision_id="r1", decision="DISCHARGE", closed_locks=("sepsis_lock",))
    assert rule.matches({"sepsis_lock": lr(False)}) is True


def test_matches_false_when_required_closed_lock_is_open():
    rule = DecisionRule(decision_id="r1", decision="DISCHARGE", closed_locks=("sepsis_lock",))
    assert rule.matches({"sepsis_lock": lr(True)}) is False


def test_matches_combines_open_and_closed_requirements():
    rule = DecisionRule(
        decision_id="r1", decision="X",
        open_locks=("a",), closed_locks=("b",),
    )
    assert rule.matches({"a": lr(True), "b": lr(False)}) is True
    assert rule.matches({"a": lr(True), "b": lr(True)}) is False
    assert rule.matches({"a": lr(False), "b": lr(False)}) is False


def test_matches_fail_closed_when_open_lock_not_evaluated():
    # A required-open lock that was never evaluated must not silently
    # count as "open" -- fail closed (matches philosophy of the rest of
    # this system: never assume evidence exists that wasn't checked).
    rule = DecisionRule(decision_id="r1", decision="X", open_locks=("never_evaluated",))
    assert rule.matches({}) is False


def test_matches_fail_closed_when_closed_lock_not_evaluated():
    # Equally: a required-closed lock that was never evaluated must not
    # silently count as "closed" either -- unknown is neither.
    rule = DecisionRule(decision_id="r1", decision="X", closed_locks=("never_evaluated",))
    assert rule.matches({}) is False


# --- DecisionRuleRegistry ---

def test_registry_register_and_get():
    rule = DecisionRule(decision_id="r1", decision="X", open_locks=("a",))
    registry = DecisionRuleRegistry([rule])
    assert registry.get("r1") is rule
    assert "r1" in registry
    assert len(registry) == 1


def test_registry_duplicate_rejected():
    registry = DecisionRuleRegistry([DecisionRule(decision_id="r1", decision="X", open_locks=("a",))])
    with pytest.raises(ValueError):
        registry.register(DecisionRule(decision_id="r1", decision="Y", open_locks=("b",)))


def test_registry_unknown_raises_keyerror():
    registry = DecisionRuleRegistry()
    with pytest.raises(KeyError):
        registry.get("nope")
