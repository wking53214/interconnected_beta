from datetime import datetime

import pytest
from zeta import Combination, Key, KeySet, LockEvaluator, LockRegistry, LockSpec

from beta.engine import AmbiguousRuleError, DecisionEngine, NoMatchingRuleError
from beta.rules import DecisionRule, DecisionRuleRegistry

T0 = datetime(2026, 1, 1, 12, 0, 0)


def build_lock_registry():
    return LockRegistry([
        LockSpec(
            lock_id="sepsis_lock",
            required_keys=("septic_shock", "respiratory_distress"),
            combination=Combination.OR,
            dwell_threshold=1,
            force=True,
        ),
        LockSpec(
            lock_id="abnormal_vitals_lock",
            required_keys=("fever", "tachycardia"),
            combination=Combination.OR,
            dwell_threshold=1,
            force=True,
        ),
    ])


def build_decision_registry():
    return DecisionRuleRegistry([
        DecisionRule(
            decision_id="escalate_sepsis",
            decision="ESCALATE",
            open_locks=("sepsis_lock",),
            priority=10,
            reasoning_template="Escalating: {decision} due to open locks {open_locks}",
            reversal_conditions=("sepsis_lock closes",),
            instructions="Go to emergency room immediately.",
        ),
        DecisionRule(
            decision_id="hold_abnormal",
            decision="HOLD",
            open_locks=("abnormal_vitals_lock",),
            closed_locks=("sepsis_lock",),
            priority=5,
            reasoning_template="Holding: {decision}",
            instructions="Continue monitoring.",
        ),
        DecisionRule(
            decision_id="discharge_safe",
            decision="DISCHARGE_SAFE",
            closed_locks=("sepsis_lock", "abnormal_vitals_lock"),
            priority=0,
            reasoning_template="Safe to discharge: all danger locks closed",
            instructions="Discharge with standard follow-up.",
        ),
    ])


def evaluate(vitals_keys):
    lock_registry = build_lock_registry()
    evaluator = LockEvaluator(lock_registry)
    keys = KeySet(vitals_keys)
    results = evaluator.evaluate_all("patient1", keys, T0)
    return lock_registry, keys, results


# --- Basic decision selection ---

def test_escalate_when_sepsis_lock_opens():
    lock_registry, keys, results = evaluate([
        Key(name="septic_shock", present=True, confidence=0.95),
    ])
    engine = DecisionEngine(build_decision_registry(), lock_registry)
    decision = engine.decide("patient1", keys, results, T0)

    assert decision.decision == "ESCALATE"
    assert decision.decision_id == "escalate_sepsis"
    assert "septic_shock" in decision.triggered_by_keys
    assert decision.instructions == "Go to emergency room immediately."


def test_discharge_safe_when_all_danger_locks_closed():
    lock_registry, keys, results = evaluate([
        Key(name="septic_shock", present=False),
        Key(name="respiratory_distress", present=False),
        Key(name="fever", present=False),
        Key(name="tachycardia", present=False),
    ])
    engine = DecisionEngine(build_decision_registry(), lock_registry)
    decision = engine.decide("patient1", keys, results, T0)

    assert decision.decision == "DISCHARGE_SAFE"
    assert decision.triggered_by_keys == ()  # no positive evidence, absence-based
    assert decision.confidence == 1.0


def test_hold_when_abnormal_but_not_septic():
    lock_registry, keys, results = evaluate([
        Key(name="fever", present=True, confidence=0.9),
        Key(name="septic_shock", present=False),
        Key(name="respiratory_distress", present=False),
    ])
    engine = DecisionEngine(build_decision_registry(), lock_registry)
    decision = engine.decide("patient1", keys, results, T0)

    assert decision.decision == "HOLD"


# --- Priority resolution ---

def test_higher_priority_rule_wins_when_multiple_match():
    # sepsis_lock open makes BOTH escalate_sepsis (open_locks=sepsis_lock)
    # match -- hold_abnormal requires sepsis_lock CLOSED so it can't also
    # match here. Use a dedicated pair of rules to force a real overlap.
    lock_registry = build_lock_registry()
    decision_registry = DecisionRuleRegistry([
        DecisionRule(decision_id="high", decision="A", open_locks=("sepsis_lock",), priority=10),
        DecisionRule(decision_id="low", decision="B", open_locks=("sepsis_lock",), priority=1),
    ])
    evaluator = LockEvaluator(lock_registry)
    keys = KeySet([Key(name="septic_shock", present=True)])
    results = evaluator.evaluate_all("patient1", keys, T0)

    engine = DecisionEngine(decision_registry, lock_registry)
    decision = engine.decide("patient1", keys, results, T0)
    assert decision.decision == "A"


def test_ambiguous_same_priority_raises():
    lock_registry = build_lock_registry()
    decision_registry = DecisionRuleRegistry([
        DecisionRule(decision_id="r1", decision="A", open_locks=("sepsis_lock",), priority=5),
        DecisionRule(decision_id="r2", decision="B", open_locks=("sepsis_lock",), priority=5),
    ])
    evaluator = LockEvaluator(lock_registry)
    keys = KeySet([Key(name="septic_shock", present=True)])
    results = evaluator.evaluate_all("patient1", keys, T0)

    engine = DecisionEngine(decision_registry, lock_registry)
    with pytest.raises(AmbiguousRuleError):
        engine.decide("patient1", keys, results, T0)


def test_no_matching_rule_raises():
    lock_registry = LockRegistry([
        LockSpec(lock_id="orphan_lock", required_keys=("nothing_relevant",), dwell_threshold=1),
    ])
    decision_registry = DecisionRuleRegistry([
        DecisionRule(decision_id="r1", decision="A", open_locks=("orphan_lock",)),
    ])
    evaluator = LockEvaluator(lock_registry)
    keys = KeySet([Key(name="nothing_relevant", present=False)])
    results = evaluator.evaluate_all("patient1", keys, T0)

    engine = DecisionEngine(decision_registry, lock_registry)
    with pytest.raises(NoMatchingRuleError):
        engine.decide("patient1", keys, results, T0)


# --- Confidence aggregation ---

def test_confidence_is_geometric_mean_of_triggering_keys():
    lock_registry = LockRegistry([
        LockSpec(lock_id="l1", required_keys=("a", "b"), combination=Combination.AND, dwell_threshold=1),
    ])
    decision_registry = DecisionRuleRegistry([
        DecisionRule(decision_id="r1", decision="X", open_locks=("l1",)),
    ])
    evaluator = LockEvaluator(lock_registry)
    keys = KeySet([
        Key(name="a", present=True, confidence=0.8),
        Key(name="b", present=True, confidence=0.5),
    ])
    results = evaluator.evaluate_all("patient1", keys, T0)

    engine = DecisionEngine(decision_registry, lock_registry)
    decision = engine.decide("patient1", keys, results, T0)

    expected = (0.8 * 0.5) ** 0.5
    assert decision.confidence == pytest.approx(expected)


def test_confidence_only_counts_present_keys_in_or_lock():
    # OR-combination lock: only ONE of the two keys needs to be present
    # to open the lock. Confidence should reflect only the key(s) that
    # were actually present, not the absent one.
    lock_registry = LockRegistry([
        LockSpec(lock_id="l1", required_keys=("a", "b"), combination=Combination.OR, dwell_threshold=1),
    ])
    decision_registry = DecisionRuleRegistry([
        DecisionRule(decision_id="r1", decision="X", open_locks=("l1",)),
    ])
    evaluator = LockEvaluator(lock_registry)
    keys = KeySet([
        Key(name="a", present=True, confidence=0.7),
        Key(name="b", present=False, confidence=0.3),
    ])
    results = evaluator.evaluate_all("patient1", keys, T0)

    engine = DecisionEngine(decision_registry, lock_registry)
    decision = engine.decide("patient1", keys, results, T0)

    assert decision.confidence == pytest.approx(0.7)
    assert decision.triggered_by_keys == ("a",)


# --- Fingerprint determinism ---

def test_fingerprint_deterministic_for_identical_inputs():
    lock_registry, keys, results = evaluate([Key(name="septic_shock", present=True)])
    engine = DecisionEngine(build_decision_registry(), lock_registry)

    d1 = engine.decide("patient1", keys, results, T0)
    d2 = engine.decide("patient1", keys, results, T0)
    assert d1.decision_fingerprint == d2.decision_fingerprint


def test_fingerprint_differs_for_different_entity():
    lock_registry, keys, results = evaluate([Key(name="septic_shock", present=True)])
    engine = DecisionEngine(build_decision_registry(), lock_registry)

    d1 = engine.decide("patient1", keys, results, T0)
    d2 = engine.decide("patient2", keys, results, T0)
    assert d1.decision_fingerprint != d2.decision_fingerprint


def test_fingerprint_ignores_timestamp():
    # Matches the source contract (observe_consolidated.py:236-244):
    # decision_fingerprint is deliberately wall-clock-free.
    from datetime import timedelta
    lock_registry, keys, results = evaluate([Key(name="septic_shock", present=True)])
    engine = DecisionEngine(build_decision_registry(), lock_registry)

    d1 = engine.decide("patient1", keys, results, T0)
    d2 = engine.decide("patient1", keys, results, T0 + timedelta(days=1))
    assert d1.decision_fingerprint == d2.decision_fingerprint


# --- Narrative fields pass through untouched ---

def test_reversal_conditions_and_instructions_carried_from_rule():
    lock_registry, keys, results = evaluate([Key(name="septic_shock", present=True)])
    engine = DecisionEngine(build_decision_registry(), lock_registry)
    decision = engine.decide("patient1", keys, results, T0)

    assert decision.reversal_conditions == ("sepsis_lock closes",)
    assert "emergency room" in decision.instructions
