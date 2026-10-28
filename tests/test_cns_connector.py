"""beta's Decision made bindable to CNS verdicts (binding only, no gate).

These skip where ``cns`` is not installed. CI installs the extra and sets
BETA_REQUIRE_CNS=1, so there they cannot skip.
"""
import dataclasses
import math
import os
from datetime import datetime, timedelta, timezone

import pytest
from zeta import Combination, Key, KeySet, LockEvaluator, LockRegistry, LockSpec

if os.environ.get("BETA_REQUIRE_CNS") == "1":  # CI: a missing cns is a failure, not a skip
    import cns.gate as gate
else:
    gate = pytest.importorskip("cns.gate")

from beta import Decision, DecisionEngine, DecisionRule, DecisionRuleRegistry  # noqa: E402
from beta.cns_connector import (  # noqa: E402
    DECISION_SUBJECT, CnsNotInstalled, binds, cns_available, decision_content, decision_digest)

T0 = datetime(2026, 1, 1, 12, 0, 0)


# ------------------------------------------------------------ a real decision, from the real engine

def lock_registry():
    return LockRegistry([
        LockSpec(lock_id="sepsis_lock", required_keys=("septic_shock", "respiratory_distress"),
                 combination=Combination.OR, dwell_threshold=1, force=True),
        LockSpec(lock_id="abnormal_vitals_lock", required_keys=("fever", "tachycardia"),
                 combination=Combination.OR, dwell_threshold=1, force=True),
    ])


def rules():
    return DecisionRuleRegistry([
        DecisionRule(decision_id="escalate_sepsis", decision="ESCALATE", open_locks=("sepsis_lock",),
                     priority=10, reasoning_template="Escalating: {decision} due to {open_locks}",
                     reversal_conditions=("sepsis_lock closes", "clinician overrides"),
                     instructions="Go to emergency room immediately."),
        DecisionRule(decision_id="hold_abnormal", decision="HOLD", open_locks=("abnormal_vitals_lock",),
                     closed_locks=("sepsis_lock",), priority=5, instructions="Continue monitoring."),
        DecisionRule(decision_id="discharge_safe", decision="DISCHARGE_SAFE",
                     closed_locks=("sepsis_lock", "abnormal_vitals_lock"), priority=0,
                     instructions="Discharge with standard follow-up."),
    ])


def decide(present, entity_id="patient1", when=T0):
    """Lock results from zeta, keys from the caller, a Decision from beta."""
    registry = lock_registry()
    keys = KeySet([Key(name=name, present=True, confidence=conf) for name, conf in present])
    results = LockEvaluator(registry).evaluate_all(entity_id, keys, when)
    return DecisionEngine(rules(), registry).decide(entity_id, keys, results, when)


@pytest.fixture
def base():
    return decide([("septic_shock", 0.95), ("respiratory_distress", 0.5)])


def result_for(subject, digest):
    """A bound verdict, issued the way a real gate would record what it judged."""
    return gate.GateResult(gate="test.gate", position=gate.GatePosition.OMEGA, outcome=gate.GateOutcome.PASS,
                           reason="issued for the test", subject=subject, subject_digest=digest)


def only_cns_types(value):
    """True iff every leaf is a type cns.gate.subject_digest accepts, and dict keys are str."""
    if value is None or isinstance(value, (str, int, float, bool)):
        return True
    if isinstance(value, list):
        return all(only_cns_types(v) for v in value)
    if isinstance(value, dict):
        return all(isinstance(k, str) and only_cns_types(v) for k, v in value.items())
    return False


# ------------------------------------------------------------ the real engine, end to end

def test_the_decision_comes_from_real_locks_and_keys(base):
    assert isinstance(base, Decision) and base.decision == "ESCALATE"
    assert base.triggered_by_keys == ("septic_shock",) and base.decision_fingerprint


def test_the_three_real_outcomes_have_three_digests_and_each_verdict_binds_only_its_own():
    escalate = decide([("septic_shock", 0.95)])
    hold = decide([("fever", 0.8)])
    discharge = decide([])
    assert [d.decision for d in (escalate, hold, discharge)] == ["ESCALATE", "HOLD", "DISCHARGE_SAFE"]
    digests = {decision_digest(d) for d in (escalate, hold, discharge)}
    assert len(digests) == 3
    verdict = result_for(DECISION_SUBJECT, decision_digest(hold))
    assert binds(verdict, hold)
    assert not binds(verdict, escalate) and not binds(verdict, discharge)


def test_a_verdict_survives_the_decision_being_recomputed_from_the_same_inputs():
    first = decide([("septic_shock", 0.95), ("respiratory_distress", 0.5)])
    again = decide([("respiratory_distress", 0.5), ("septic_shock", 0.95)])  # keys supplied in another order
    verdict = result_for(DECISION_SUBJECT, decision_digest(first))
    assert binds(verdict, again)


def test_a_verdict_stops_binding_when_the_inputs_differ():
    verdict = result_for(DECISION_SUBJECT, decision_digest(decide([("septic_shock", 0.95)])))
    assert not binds(verdict, decide([("septic_shock", 0.90)]))                 # confidence moved
    assert not binds(verdict, decide([("septic_shock", 0.95)], entity_id="patient2"))
    assert not binds(verdict, decide([("septic_shock", 0.95)], when=T0 + timedelta(seconds=1)))


# ------------------------------------------------------------ digest

def test_the_digest_is_cns_subject_digest_of_the_content(base):
    assert decision_digest(base) == gate.subject_digest(decision_content(base))
    assert len(decision_digest(base)) == 64


def test_the_digest_is_deterministic(base):
    again = decide([("septic_shock", 0.95), ("respiratory_distress", 0.5)])
    assert decision_content(base) == decision_content(again)
    assert decision_digest(base) == decision_digest(again) == decision_digest(base)


def test_the_digest_is_not_beta_s_own_fingerprint(base):
    assert decision_digest(base) != base.decision_fingerprint


BOUND_CHANGES = {
    "entity_id": "patient2",
    "decision_id": "other_rule",
    "decision": "HOLD",
    "timestamp": T0 + timedelta(seconds=1),
    "confidence": 0.5,
    "triggered_by_locks": ("sepsis_lock", "extra_lock"),
    "triggered_by_keys": ("septic_shock", "extra_key"),
    "newly_triggered_locks": ("sepsis_lock", "abnormal_vitals_lock"),
    "decision_fingerprint": "0" * 64,
    "reasoning": "a different explanation",
    "reversal_conditions": ("sepsis_lock closes",),
    "instructions": "Do something else.",
}
NOT_BOUND = {"audit_hash", "confidence_basis"}


def test_every_decision_field_is_either_bound_or_deliberately_not():
    names = {f.name for f in dataclasses.fields(Decision)}
    assert names == set(BOUND_CHANGES) | NOT_BOUND
    assert set(decision_content(Decision("e", "d", "x", T0, 1.0))) == set(BOUND_CHANGES)


@pytest.mark.parametrize("name", sorted(BOUND_CHANGES))
def test_the_digest_changes_when_any_bound_field_changes(base, name):
    changed = dataclasses.replace(base, **{name: BOUND_CHANGES[name]})
    assert changed != base
    assert decision_digest(changed) != decision_digest(base)
    assert not binds(result_for(DECISION_SUBJECT, decision_digest(base)), changed)


# ------------------------------------------------------------ what does not matter

def test_the_order_of_set_like_fields_does_not_change_the_digest(base):
    shuffled = dataclasses.replace(
        base,
        triggered_by_locks=("sepsis_lock", "abnormal_vitals_lock", "zz"),
        triggered_by_keys=("b", "a", "c"),
        newly_triggered_locks=("y", "x"))
    ordered = dataclasses.replace(
        base,
        triggered_by_locks=("abnormal_vitals_lock", "sepsis_lock", "zz"),
        triggered_by_keys=("a", "b", "c"),
        newly_triggered_locks=("x", "y"))
    assert decision_digest(shuffled) == decision_digest(ordered)
    assert decision_content(shuffled)["triggered_by_keys"] == ["a", "b", "c"]


def test_the_order_of_reversal_conditions_is_authored_narrative_and_does_matter(base):
    swapped = dataclasses.replace(base, reversal_conditions=tuple(reversed(base.reversal_conditions)))
    assert len(base.reversal_conditions) == 2
    assert decision_digest(swapped) != decision_digest(base)


def test_the_audit_hash_a_ledger_stamps_later_does_not_unbind_a_verdict(base):
    verdict = result_for(DECISION_SUBJECT, decision_digest(base))
    recorded = dataclasses.replace(base, audit_hash="f" * 64)
    assert decision_digest(recorded) == decision_digest(base)
    assert binds(verdict, recorded)


def test_an_int_and_a_float_confidence_bind_alike():
    as_int = Decision("e", "d", "x", T0, confidence=1)
    as_float = Decision("e", "d", "x", T0, confidence=1.0)
    assert decision_digest(as_int) == decision_digest(as_float)
    assert decision_digest(Decision("e", "d", "x", T0, confidence=0.0)) == \
        decision_digest(Decision("e", "d", "x", T0, confidence=-0.0))


def test_the_same_instant_in_two_offsets_is_one_digest_and_naive_differs_from_aware():
    utc = Decision("e", "d", "x", datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc), 1.0)
    plus_one = Decision("e", "d", "x", datetime(2026, 1, 1, 13, 0, tzinfo=timezone(timedelta(hours=1))), 1.0)
    naive = Decision("e", "d", "x", datetime(2026, 1, 1, 12, 0), 1.0)
    assert decision_digest(utc) == decision_digest(plus_one)
    assert decision_digest(naive) != decision_digest(utc)


def test_the_content_is_a_copy_and_mutating_it_does_not_touch_the_decision(base):
    content = decision_content(base)
    content["triggered_by_keys"].append("tampered")
    content["reversal_conditions"].clear()
    assert decision_content(base)["reversal_conditions"] == list(base.reversal_conditions)
    assert "tampered" not in decision_content(base)["triggered_by_keys"]


# ------------------------------------------------------------ content shape

def test_the_content_holds_only_types_cns_accepts(base):
    content = decision_content(base)
    assert isinstance(content, dict) and only_cns_types(content)
    assert isinstance(content["timestamp"], str) and isinstance(content["confidence"], float)
    assert all(isinstance(content[k], list) for k in
               ("triggered_by_locks", "triggered_by_keys", "newly_triggered_locks", "reversal_conditions"))


def test_the_content_names_the_decision(base):
    content = decision_content(base)
    assert content["entity_id"] == "patient1" and content["decision"] == "ESCALATE"
    assert content["decision_fingerprint"] == base.decision_fingerprint
    assert content["reasoning"] == base.reasoning and content["instructions"] == base.instructions


@pytest.mark.parametrize("bad", [math.nan, math.inf, -math.inf])
def test_a_confidence_that_cannot_be_bound_is_refused_not_hashed(bad):
    with pytest.raises(TypeError):
        decision_digest(Decision("e", "d", "x", T0, confidence=bad))


@pytest.mark.parametrize("field, value", [("confidence", "high"), ("confidence", None), ("confidence", True),
                                          ("timestamp", "2026-01-01"), ("timestamp", None)])
def test_a_decision_with_a_malformed_field_is_a_type_error(field, value):
    broken = dataclasses.replace(Decision("e", "d", "x", T0, 1.0), **{field: value})
    with pytest.raises(TypeError):
        decision_content(broken)


# ------------------------------------------------------------ wrong types

@pytest.mark.parametrize("bad", [None, "ESCALATE", 7, {"entity_id": "patient1"}, ["x"], object(),
                                 DecisionRule(decision_id="r", decision="D", open_locks=("l",))])
def test_something_that_is_not_a_decision_is_a_type_error(bad):
    with pytest.raises(TypeError, match="beta.Decision"):
        decision_content(bad)
    with pytest.raises(TypeError, match="beta.Decision"):
        decision_digest(bad)
    with pytest.raises(TypeError, match="beta.Decision"):
        binds(result_for(DECISION_SUBJECT, "x"), bad)


def test_a_decision_like_object_is_not_a_decision():
    class Lookalike:
        def __getattr__(self, name):
            return "x"

    with pytest.raises(TypeError):
        decision_content(Lookalike())


@pytest.mark.parametrize("bad", [None, "PASS", {"subject": DECISION_SUBJECT}, object()])
def test_a_result_that_is_not_a_gate_result_is_a_type_error(base, bad):
    with pytest.raises(TypeError, match="GateResult"):
        binds(bad, base)


# ------------------------------------------------------------ binds

def test_binds_is_true_for_the_decision_the_result_was_issued_against(base):
    assert binds(result_for(DECISION_SUBJECT, decision_digest(base)), base) is True


def test_binds_is_false_for_a_different_decision(base):
    other = dataclasses.replace(base, instructions="Wait.")
    assert binds(result_for(DECISION_SUBJECT, decision_digest(base)), other) is False


def test_binds_is_false_for_an_unbound_or_hand_built_result(base):
    hand_built = gate.GateResult(gate="x", position=gate.GatePosition.OMEGA, outcome=gate.GateOutcome.PASS)
    assert not hand_built.bound() and binds(hand_built, base) is False
    assert binds(result_for("", decision_digest(base)), base) is False
    assert binds(result_for(DECISION_SUBJECT, ""), base) is False
    assert binds(result_for("", ""), base, subject="") is False
    # a result with the right digest but no subject records nothing it can be held to, even against an empty label
    assert binds(result_for("", decision_digest(base)), base, subject="") is False


def test_binds_checks_the_subject_label(base):
    digest = decision_digest(base)
    assert binds(result_for("something.else", digest), base) is False
    assert binds(result_for("something.else", digest), base, subject="something.else") is True
    assert binds(result_for(DECISION_SUBJECT, digest), base, subject="something.else") is False


def test_binds_does_not_depend_on_the_outcome(base):
    digest = decision_digest(base)
    for outcome in gate.GateOutcome:
        verdict = gate.GateResult(gate="g", position=gate.GatePosition.OMEGA, outcome=outcome,
                                  subject=DECISION_SUBJECT, subject_digest=digest)
        assert binds(verdict, base) is True


def test_the_subject_label_is_stable():
    assert DECISION_SUBJECT == "beta.decision"


# ------------------------------------------------------------ availability

def test_cns_is_available_here_and_the_error_type_is_an_import_error():
    assert cns_available() is True
    assert issubclass(CnsNotInstalled, ImportError)
