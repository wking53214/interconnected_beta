"""decide() refuses lock results that record a different entity than the one it is asked about (C11)."""
import dataclasses
from datetime import datetime

import pytest
from zeta import Combination, Key, KeySet, LockEvaluator, LockRegistry, LockSpec

from beta import DecisionEngine, DecisionRule, DecisionRuleRegistry, EntityMismatchError

T0 = datetime(2026, 1, 1, 12, 0, 0)


def build():
    locks = LockRegistry([LockSpec(lock_id="sepsis_lock", required_keys=("septic_shock",), combination=Combination.OR)])
    rules = DecisionRuleRegistry([
        DecisionRule(decision_id="escalate", decision="ESCALATE", open_locks=("sepsis_lock",), priority=10),
        DecisionRule(decision_id="safe", decision="SAFE", closed_locks=("sepsis_lock",), priority=0),
    ])
    keys = KeySet([Key(name="septic_shock", present=True, confidence=0.8)])
    return DecisionEngine(rules, locks), keys, LockEvaluator(locks)


def test_results_for_another_entity_are_refused_and_both_ids_are_named():
    engine, keys, evaluator = build()
    results = evaluator.evaluate_all("patient_sick", keys, T0)
    assert results["sepsis_lock"].entity_id == "patient_sick"
    with pytest.raises(EntityMismatchError) as err:
        engine.decide("patient_well", keys, results, T0)
    assert "patient_well" in str(err.value) and "patient_sick" in str(err.value)
    assert isinstance(err.value, ValueError)


def test_results_with_no_entity_are_accepted_as_legacy():
    engine, keys, evaluator = build()
    results = {k: dataclasses.replace(v, entity_id="") for k, v in evaluator.evaluate_all("p1", keys, T0).items()}
    assert engine.decide("anyone", keys, results, T0).decision == "ESCALATE"


def test_matching_entity_is_accepted():
    engine, keys, evaluator = build()
    assert engine.decide("p1", keys, evaluator.evaluate_all("p1", keys, T0), T0).entity_id == "p1"


def test_one_foreign_result_among_matching_ones_is_enough_to_refuse():
    engine, keys, evaluator = build()
    results = evaluator.evaluate_all("p1", keys, T0)
    results["sepsis_lock"] = dataclasses.replace(results["sepsis_lock"], entity_id="p2")
    with pytest.raises(EntityMismatchError, match="p2"):
        engine.decide("p1", keys, results, T0)
