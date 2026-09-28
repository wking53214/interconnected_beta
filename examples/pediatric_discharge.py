"""Worked example: raw vitals -> alpha detects Keys -> zeta evaluates Locks
-> beta produces a governed Decision with narrative.

Run: PYTHONPATH=.:/path/to/interconnected_zeta:/path/to/interconnected_alpha python3 examples/pediatric_discharge.py

The full pipeline, end to end. This is the same clinical timeline used in
zeta's and alpha's own examples -- here it produces an actual governed
Decision (with reasoning, reversal conditions, and instructions) instead
of raw Lock states.
"""

from datetime import datetime, timedelta

from zeta import Combination, LockEvaluator, LockRegistry, LockSpec

from alpha import VitalsObservation, observe

from beta import DecisionEngine, DecisionRule, DecisionRuleRegistry


def build_lock_registry() -> LockRegistry:
    return LockRegistry([
        LockSpec(
            lock_id="sepsis_lock",
            required_keys=("septic_shock", "respiratory_distress", "hypovolemic_shock"),
            combination=Combination.OR,
            dwell_threshold=1,
            force=True,
            lock_seconds=3600,
        ),
        LockSpec(
            lock_id="abnormal_vitals_lock",
            required_keys=("tachycardia", "fever", "tachypnea"),
            combination=Combination.OR,
            dwell_threshold=2,  # requires 2 consecutive confirming readings either direction
        ),
    ])


def build_decision_registry() -> DecisionRuleRegistry:
    return DecisionRuleRegistry([
        DecisionRule(
            decision_id="escalate_sepsis",
            decision="ESCALATE",
            open_locks=("sepsis_lock",),
            priority=10,
            reasoning_template="{decision}: sepsis pattern detected ({open_locks} open)",
            reversal_conditions=("sepsis_lock closes (danger signs resolve for 1 confirming reading)",),
            instructions="Go to emergency room immediately. Do not wait.",
        ),
        DecisionRule(
            decision_id="hold_abnormal",
            decision="HOLD",
            open_locks=("abnormal_vitals_lock",),
            closed_locks=("sepsis_lock",),
            priority=5,
            reasoning_template="{decision}: abnormal vitals present but no sepsis pattern",
            reversal_conditions=(
                "abnormal_vitals_lock closes -> re-evaluate for discharge",
                "sepsis_lock opens -> escalate immediately",
            ),
            instructions="Continue inpatient monitoring. Recheck vitals in 4 hours.",
        ),
        DecisionRule(
            decision_id="discharge_safe",
            decision="DISCHARGE_SAFE",
            closed_locks=("sepsis_lock", "abnormal_vitals_lock"),
            priority=0,
            reasoning_template="{decision}: no danger locks open, vitals within normal range",
            reversal_conditions=(
                "fever returns above threshold for 2 consecutive readings -> return to hospital",
                "lethargy or poor feeding observed -> return to hospital",
            ),
            instructions="Discharge with written warning-sign sheet. Follow-up clinic visit in 48h.",
        ),
    ])


def main():
    lock_registry = build_lock_registry()
    lock_evaluator = LockEvaluator(lock_registry)
    decision_registry = build_decision_registry()
    decision_engine = DecisionEngine(decision_registry, lock_registry)

    t0 = datetime(2026, 10, 1, 8, 0, 0)
    patient = "patient_14mo_001"

    # (hour, HR, O2, RR, temp, age_months)
    timeline = [
        (0, 148, 90.0, 36, 39.6, 14),
        (2, 145, 91.0, 34, 39.2, 14),
        (14, 118, 96.0, 26, 38.0, 14),
        (18, 100, 97.0, 22, 37.2, 14),
        (26, 96, 98.0, 22, 37.0, 14),
    ]

    for hour, hr, o2, rr, temp, age in timeline:
        ts = t0 + timedelta(hours=hour)
        vitals = VitalsObservation(heart_rate=hr, oxygen_saturation=o2, respiratory_rate=rr,
                                    temperature=temp, age_months=age)
        keys = observe(vitals)
        lock_results = lock_evaluator.evaluate_all(patient, keys, ts)

        print(f"\n{'='*70}\nT+{hour}h  HR={hr} O2={o2}% RR={rr} temp={temp}")
        print(f"Keys: {sorted(keys.names_present()) or '(none)'}")
        print(f"Locks: {[(lid, r.open) for lid, r in lock_results.items()]}")

        try:
            decision = decision_engine.decide(patient, keys, lock_results, ts)
        except Exception as e:
            print(f"  No decision yet: {e}")
            continue

        print(f"\nDECISION: {decision.decision}  (confidence={decision.confidence:.2f})")
        print(f"  Reasoning: {decision.reasoning}")
        print(f"  Reversal conditions: {list(decision.reversal_conditions)}")
        print(f"  Instructions: {decision.instructions}")
        print(f"  Fingerprint: {decision.decision_fingerprint[:16]}...")


if __name__ == "__main__":
    main()
