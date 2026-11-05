"""Decision.content_fingerprint: a keyless fingerprint over 13 fields (C7).

decision_fingerprint still covers five inputs and is unchanged. content_fingerprint additionally covers the
timestamp, confidence, newly triggered locks, narrative, confidence basis and KeySet lineage. It catches a partial
edit of a Decision; it cannot stop someone who edits the fields and recomputes it.
"""
import dataclasses
import hashlib
import json
from datetime import datetime, timedelta

import pytest
from zeta import Combination, Key, KeySet, LockEvaluator, LockRegistry, LockSpec

from beta import Decision, DecisionEngine, DecisionRule, DecisionRuleRegistry, canonical_decision, content_fingerprint
from beta.cns_connector import decision_content
from beta.fingerprint import decision_fingerprint

T0 = datetime(2026, 1, 1, 12, 0, 0)

COVERED = (
    "entity_id", "decision_id", "decision", "timestamp", "confidence", "triggered_by_locks", "triggered_by_keys",
    "newly_triggered_locks", "reasoning", "reversal_conditions", "instructions", "confidence_basis",
    "keyset_fingerprint",
)
OLD_COVERED = {"entity_id", "decision_id", "decision", "triggered_by_locks", "triggered_by_keys"}
EXCLUDED = {"audit_hash", "decision_fingerprint", "content_fingerprint"}


def engine_decision():
    locks = LockRegistry([LockSpec(lock_id="sepsis_lock", required_keys=("septic_shock",), combination=Combination.OR)])
    rules = DecisionRuleRegistry([
        DecisionRule(decision_id="escalate", decision="ESCALATE", open_locks=("sepsis_lock",), priority=10,
                     reversal_conditions=("sepsis_lock closes",), instructions="Call the team."),
        DecisionRule(decision_id="safe", decision="SAFE", closed_locks=("sepsis_lock",), priority=0),
    ])
    keys = KeySet([Key(name="septic_shock", present=True, confidence=0.8)])
    results = LockEvaluator(locks).evaluate_all("p1", keys, T0)
    return DecisionEngine(rules, locks).decide("p1", keys, results, T0)


def old_check_passes(d):
    want = decision_fingerprint({
        "entity_id": d.entity_id, "decision_id": d.decision_id, "decision": d.decision,
        "triggered_by_locks": list(d.triggered_by_locks), "triggered_by_keys": list(d.triggered_by_keys),
    })
    return d.decision_fingerprint == want


MUTATED = {
    "entity_id": "p2",
    "decision_id": "other",
    "decision": "HOLD",
    "timestamp": T0 + timedelta(seconds=1),
    "confidence": 0.5,
    "triggered_by_locks": ("sepsis_lock", "extra_lock"),
    "triggered_by_keys": ("ghost",),
    "newly_triggered_locks": ("sepsis_lock", "extra_lock"),
    "reasoning": "edited narrative",
    "reversal_conditions": ("edited",),
    "instructions": "Do nothing.",
    "confidence_basis": "absence",
    "keyset_fingerprint": "d" * 64,
}


def test_the_mutation_table_covers_exactly_the_thirteen_fields():
    assert set(MUTATED) == set(COVERED) and len(COVERED) == 13
    assert set(canonical_decision(engine_decision())) == set(COVERED)
    names = {f.name for f in dataclasses.fields(Decision)}
    assert names - set(COVERED) == EXCLUDED


def test_the_engine_sets_it_and_it_validates():
    d = engine_decision()
    assert len(d.content_fingerprint) == 64
    assert d.content_fingerprint == content_fingerprint(d)
    d.validate(check_fingerprint=True)


def test_the_value_is_the_documented_construction():
    d = engine_decision()
    payload = {"domain": "beta-decision-content/1", **canonical_decision(d)}
    want = hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    assert d.content_fingerprint == want
    assert canonical_decision(d)["timestamp"] == T0.isoformat()


# confidence_basis cannot be changed through construction (it is refused), so it has its own bypass test below.
@pytest.mark.parametrize("name", [n for n in COVERED if n != "confidence_basis"])
def test_mutating_any_covered_field_is_rejected_by_the_content_check(name):
    d = engine_decision()
    assert d.keyset_fingerprint
    forged = dataclasses.replace(d, **{name: MUTATED[name]}, **({"confidence_basis": ""} if name == "triggered_by_keys" else {}))
    assert getattr(forged, name) != getattr(d, name) or name == "triggered_by_keys"
    if name in OLD_COVERED:
        assert not old_check_passes(forged)  # the older check sees these five too
    else:
        assert old_check_passes(forged)  # the older check alone would accept the edit
    with pytest.raises(ValueError):
        forged.validate(check_fingerprint=True)


@pytest.mark.parametrize("name", sorted(set(COVERED) - OLD_COVERED - {"confidence_basis"}))
def test_the_uncovered_by_old_fields_are_refused_with_the_content_message(name):
    forged = dataclasses.replace(engine_decision(), **{name: MUTATED[name]})
    assert old_check_passes(forged)
    with pytest.raises(ValueError, match="Decision.content_fingerprint does not match the Decision's own fields"):
        forged.validate(check_fingerprint=True)


def test_a_mutated_confidence_basis_that_bypassed_construction_is_refused():
    d = engine_decision()
    object.__setattr__(d, "confidence_basis", "absence")
    assert old_check_passes(d)
    with pytest.raises(ValueError):
        d.validate(check_fingerprint=True)
    # and the fingerprint alone distinguishes it, whatever else validate() says
    assert content_fingerprint(d) != engine_decision().content_fingerprint


@pytest.mark.parametrize("name", sorted(EXCLUDED - {"content_fingerprint"}))
def test_the_excluded_fields_do_not_move_the_fingerprint(name):
    d = engine_decision()
    changed = dataclasses.replace(d, **{name: "a" * 64})
    assert content_fingerprint(changed) == d.content_fingerprint


def test_a_legacy_decision_with_no_content_fingerprint_still_validates():
    d = dataclasses.replace(engine_decision(), content_fingerprint="")
    assert d.content_fingerprint == ""
    d.validate(check_fingerprint=True)


def test_it_is_deterministic_across_calls_and_key_insertion_order():
    a, b = engine_decision(), engine_decision()
    assert a.content_fingerprint == b.content_fingerprint == content_fingerprint(a)
    shuffled = dict(reversed(list(canonical_decision(a).items())))
    payload = {"domain": "beta-decision-content/1", **shuffled}
    assert hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest() == a.content_fingerprint


def test_decision_fingerprint_is_unchanged():
    d = engine_decision()
    assert old_check_passes(d)
    pinned = decision_fingerprint({"a": 1})
    assert pinned == hashlib.sha256(b'{"a": 1}').hexdigest()
    legacy = Decision("p1", "r", "X", T0, 1.0, decision_fingerprint="f" * 64)
    assert legacy.decision_fingerprint == "f" * 64 and legacy.content_fingerprint == ""


def test_decision_content_has_no_content_fingerprint_key_when_empty_and_carries_it_when_set():
    d = engine_decision()
    assert decision_content(d)["content_fingerprint"] == d.content_fingerprint
    legacy = dataclasses.replace(d, content_fingerprint="")
    assert "content_fingerprint" not in decision_content(legacy)
    plain = Decision("e", "d", "x", T0, 1.0)
    assert set(decision_content(plain)) == set(decision_content(dataclasses.replace(plain, content_fingerprint="")))
    assert "content_fingerprint" not in decision_content(plain)


def test_a_non_str_content_fingerprint_is_refused_by_validate():
    d = engine_decision()
    object.__setattr__(d, "content_fingerprint", 5)
    with pytest.raises(ValueError, match="content_fingerprint must be a str"):
        d.validate()
