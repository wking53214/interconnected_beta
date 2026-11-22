"""With a lock result checker plugged in, beta refuses unsigned or badly signed lock results and decides nothing.

The operator's signer here is HMAC-SHA256 over a test key (stdlib only), standing in for Ed25519 or a KMS.
"""
import dataclasses
import hashlib
import hmac
from datetime import datetime, timedelta

import pytest
from zeta import Combination, Key, KeySet, LockRegistry, LockSpec

from beta import (
    DecisionEngine,
    DecisionRule,
    DecisionRuleRegistry,
    LockResultSignatureError,
    lock_result_signature_ok,
    lock_results_digest,
)
from beta.engine import EVALUATOR

T0 = datetime(2026, 11, 22, 8, 0, 0)
SEPSIS = ("septic_shock", "respiratory_distress")


def hmac_pair(key=b"operator-test-key"):
    def sign(data):
        return hmac.new(key, data, hashlib.sha256).digest()

    def verify(data, signature):
        return hmac.compare_digest(hmac.new(key, data, hashlib.sha256).digest(), signature)

    return sign, verify


def locks():
    return LockRegistry([
        LockSpec(lock_id="sepsis_lock", required_keys=SEPSIS, combination=Combination.OR, force=True),
        LockSpec(lock_id="vitals_lock", required_keys=("fever",), dwell_threshold=2),
    ])


def rules():
    return DecisionRuleRegistry([
        DecisionRule(decision_id="escalate", decision="ESCALATE", open_locks=("sepsis_lock",), priority=10),
        DecisionRule(decision_id="hold", decision="HOLD", open_locks=("vitals_lock",), closed_locks=("sepsis_lock",),
                     priority=5),
        DecisionRule(decision_id="discharge", decision="DISCHARGE_SAFE", closed_locks=("sepsis_lock", "vitals_lock")),
    ])


def keys(shock=False, fever=False):
    return KeySet([Key(name="septic_shock", present=shock, reason="r1"),
                   Key(name="respiratory_distress", present=False, reason="r2"),
                   Key(name="fever", present=fever, reason="r3")])


def test_no_signer_and_no_checker_behaves_as_before():
    plain = DecisionEngine(rules(), locks()).evaluate_and_decide("p1", keys(shock=True), T0)
    assert plain.decision.decision == "ESCALATE"
    assert all(r.signature == b"" for r in plain.lock_results.values())


def test_a_signed_run_with_a_checker_decides_and_every_result_verifies():
    sign, verify = hmac_pair()
    ev = DecisionEngine(rules(), locks(), lock_result_signer=sign,
                        lock_result_verifier=verify).evaluate_and_decide("p1", keys(shock=True), T0)
    assert ev.decision.decision == "ESCALATE"
    assert all(lock_result_signature_ok(r, verify) for r in ev.lock_results.values())


def test_signing_changes_neither_the_decision_nor_its_digests():
    sign, verify = hmac_pair()
    plain = DecisionEngine(rules(), locks()).evaluate_and_decide("p1", keys(shock=True), T0).decision
    signed = DecisionEngine(rules(), locks(), lock_result_signer=sign,
                            lock_result_verifier=verify).evaluate_and_decide("p1", keys(shock=True), T0).decision
    assert signed == plain


def test_a_checker_with_no_signer_refuses_before_any_lock_state_changes():
    _, verify = hmac_pair()
    engine = DecisionEngine(rules(), locks(), lock_result_verifier=verify)
    calls = []
    real = engine.lock_evaluator.evaluate_all
    engine.lock_evaluator.evaluate_all = lambda *a, **k: calls.append(a) or real(*a, **k)
    with pytest.raises(LockResultSignatureError, match="no signer"):
        engine.evaluate_and_decide("p1", keys(shock=True), T0)
    assert calls == [] and engine.state_store.snapshot("p1") == {}


def test_a_signature_from_the_wrong_key_is_refused_and_the_lock_states_are_put_back():
    sign, _ = hmac_pair(b"attacker")
    _, verify = hmac_pair(b"operator")
    engine = DecisionEngine(rules(), locks(), lock_result_signer=sign, lock_result_verifier=verify)
    before = engine.state_store.snapshot("p1")
    with pytest.raises(LockResultSignatureError, match="does not check out: sepsis_lock, vitals_lock"):
        engine.evaluate_and_decide("p1", keys(shock=True, fever=True), T0)
    assert engine.state_store.snapshot("p1") == before


def test_after_a_refusal_a_good_retry_counts_the_observation_once():
    sign, verify = hmac_pair()
    state = {"good": False}
    bad_sign = hmac_pair(b"attacker")[0]
    engine = DecisionEngine(rules(), locks(), lock_result_signer=lambda d: (sign if state["good"] else bad_sign)(d),
                            lock_result_verifier=verify)
    with pytest.raises(LockResultSignatureError):
        engine.decide_from_keys("p1", keys(fever=True), T0)
    state["good"] = True
    ev = engine.evaluate_and_decide("p1", keys(fever=True), T0)
    assert ev.lock_results["vitals_lock"].open is False and "1/2" in ev.lock_results["vitals_lock"].reasons[0]


def test_a_signer_that_returns_garbage_is_refused_and_puts_the_lock_states_back():
    _, verify = hmac_pair()
    engine = DecisionEngine(rules(), locks(), lock_result_signer=lambda d: "not bytes", lock_result_verifier=verify)
    with pytest.raises(TypeError):
        engine.evaluate_and_decide("p1", keys(shock=True), T0)
    assert engine.state_store.snapshot("p1") == {}


def supplied(engine, shock=True):
    """Lock results a caller evaluated elsewhere, for the test path."""
    return DecisionEngine(rules(), locks(), lock_result_signer=engine["sign"]).evaluate_and_decide(
        "p1", keys(shock=shock), T0).lock_results


def test_the_test_path_also_refuses_unsigned_and_tampered_results():
    sign, verify = hmac_pair()
    engine = DecisionEngine(rules(), locks(), lock_result_verifier=verify)
    good = supplied({"sign": sign})
    assert engine.decide("p1", keys(shock=True), good, T0, test_only=True).decision == "ESCALATE"

    unsigned = {k: dataclasses.replace(v, signature=b"") for k, v in good.items()}
    with pytest.raises(LockResultSignatureError, match="unsigned: sepsis_lock, vitals_lock"):
        engine.decide("p1", keys(shock=True), unsigned, T0, test_only=True)

    flipped = dict(good, sepsis_lock=dataclasses.replace(good["sepsis_lock"], open=False))
    with pytest.raises(LockResultSignatureError, match="does not check out: sepsis_lock$|does not check out: sepsis_lock;"):
        engine.decide("p1", keys(shock=True), flipped, T0, test_only=True)


def test_a_hand_built_result_cannot_pass_a_checker():
    _, verify = hmac_pair()
    engine = DecisionEngine(rules(), locks(), lock_result_verifier=lambda d, s: True)
    good = supplied({"sign": hmac_pair()[0]})
    forged = {k: dataclasses.replace(v, entity_id="", signature=b"x") for k, v in good.items()}
    with pytest.raises(LockResultSignatureError):
        engine.decide("p1", keys(shock=True), forged, T0, test_only=True)


def test_signer_and_checker_must_be_callable():
    with pytest.raises(TypeError, match="lock_result_signer"):
        DecisionEngine(rules(), locks(), lock_result_signer=b"key")
    with pytest.raises(TypeError, match="lock_result_verifier"):
        DecisionEngine(rules(), locks(), lock_result_verifier="pubkey")


def test_the_digest_a_decision_records_still_matches_the_signed_results():
    sign, verify = hmac_pair()
    ev = DecisionEngine(rules(), locks(), lock_result_signer=sign,
                        lock_result_verifier=verify).evaluate_and_decide("p1", keys(shock=True), T0)
    assert ev.decision.lock_results_digest == lock_results_digest(ev.lock_results, EVALUATOR)
