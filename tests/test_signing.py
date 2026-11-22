"""beta's own copy of the lock-result signing rules: the same bytes as zeta's builder, and DELTA's rules.

The operator's signer here is HMAC-SHA256 over a test key (stdlib only), standing in for Ed25519 or a KMS.
"""
import dataclasses
import hashlib
import hmac
import inspect
import json
import re
from datetime import datetime, timedelta

import pytest

import zeta
import zeta.signing as zeta_signing
from zeta import Combination, Key, KeySet, LockEvaluator, LockRegistry, LockResult, LockSpec

import beta
from beta import signing
from beta.signing import LOCK_RESULT_SIGNATURE_DOMAIN, lock_result_signature_ok, lock_result_signing_input, strict_utf8

T0 = datetime(2026, 1, 1, 12, 0, 0)

# delta.signing.strict_utf8 at interconnected_delta b85e46c, verbatim. beta's copy must match it character for character.
DELTA_STRICT_UTF8_SOURCE = '''def strict_utf8(name: str, value: str) -> None:
    """``ValueError`` naming ``name`` unless ``value`` encodes as strict UTF-8 (so no lone or paired surrogates).

    ``ensure_ascii`` JSON writes an astral character and the surrogate pair of two code points the same way, so
    without this two different strings would share one signing input."""
    try:
        value.encode("utf-8")
    except UnicodeEncodeError:
        raise ValueError(f"{name} does not encode as strict UTF-8 (a surrogate code point is not a character)") from None
'''
DOMAIN_SHAPE = re.compile(rb"^[a-z]+-[a-z]+(-[a-z]+)*-signature/[0-9]+\n$")


def hmac_pair(key=b"operator-test-key"):
    def sign(data):
        return hmac.new(key, data, hashlib.sha256).digest()

    def verify(data, signature):
        return hmac.compare_digest(hmac.new(key, data, hashlib.sha256).digest(), signature)

    return sign, verify


def a_result(**overrides):
    base = dict(lock_id="hazard", open=True, changed=True, forced=False, reasons=["r"], stale=False,
                keyset_fingerprint="f" * 64, entity_id="p1")
    base.update(overrides)
    return LockResult(**base)


def evaluated_results():
    registry = LockRegistry([
        LockSpec(lock_id="hazard", required_keys=("a", "b"), combination=Combination.OR, force=True, lock_seconds=60),
        LockSpec(lock_id="clear", required_keys=("a", "b"), dwell_threshold=2),
    ])
    ev = LockEvaluator(registry)
    out = []
    for i, (a, b) in enumerate([(True, False), (False, False), (True, True), (True, True), (False, True)]):
        ks = KeySet([Key(name="a", present=a, reason=f"café {i}"), Key(name="b", present=b, reason="\U0001f600")])
        out.extend(ev.evaluate_all(f"p{i % 2}", ks, T0 + timedelta(seconds=30 * i)).values())
    out.append(ev.evaluate("p0", ks, "clear", T0))  # stale
    return out


def test_the_rules_are_exported_from_the_package():
    for name in ("lock_result_signing_input", "lock_result_signature_ok"):
        assert name in beta.__all__ and getattr(beta, name) is getattr(signing, name)


def test_strict_utf8_is_delta_s_copy_character_for_character():
    assert inspect.getsource(strict_utf8) == DELTA_STRICT_UTF8_SOURCE


def test_the_domain_label_is_zeta_s_and_has_delta_s_shape():
    assert LOCK_RESULT_SIGNATURE_DOMAIN == zeta_signing.LOCK_RESULT_SIGNATURE_DOMAIN
    assert DOMAIN_SHAPE.match(LOCK_RESULT_SIGNATURE_DOMAIN)
    assert DOMAIN_SHAPE.match(b"delta-ledger-receipt-signature/1\n")


def test_beta_builds_the_same_bytes_as_zeta_for_every_evaluated_result():
    results = evaluated_results()
    assert any(r.stale for r in results) and any(r.forced for r in results)
    for r in results:
        assert lock_result_signing_input(r) == zeta_signing.lock_result_signing_input(r)


def test_the_body_is_delta_s_canonical_ascii_json():
    data = lock_result_signing_input(a_result(reasons=["café"]))
    body = json.loads(data[len(LOCK_RESULT_SIGNATURE_DOMAIN):])
    assert data[len(LOCK_RESULT_SIGNATURE_DOMAIN):] == json.dumps(
        body, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False).encode("ascii")


@pytest.mark.parametrize("overrides", [
    {"entity_id": ""}, {"keyset_fingerprint": ""}, {"lock_id": ""}, {"open": 1}, {"reasons": ("r",)},
    {"reasons": ["\ud800"]}, {"entity_id": 3},
])
def test_beta_refuses_what_zeta_refuses(overrides):
    bad = a_result(**overrides)
    with pytest.raises((TypeError, ValueError)) as ours:
        lock_result_signing_input(bad)
    with pytest.raises((TypeError, ValueError)) as theirs:
        zeta_signing.lock_result_signing_input(bad)
    assert type(ours.value) is type(theirs.value)


def test_a_subclass_is_refused():
    class Sneaky(LockResult):
        pass

    with pytest.raises(TypeError):
        lock_result_signing_input(Sneaky(**dataclasses.asdict(a_result())))


def test_a_signature_zeta_made_checks_out_here_and_a_tampered_one_does_not():
    sign, verify = hmac_pair()
    signed = dataclasses.replace(a_result(), signature=zeta.sign_lock_result(a_result(), sign))
    assert lock_result_signature_ok(signed, verify) is True
    assert lock_result_signature_ok(dataclasses.replace(signed, open=False), verify) is False
    assert lock_result_signature_ok(dataclasses.replace(signed, entity_id="p2"), verify) is False
    assert lock_result_signature_ok(signed, hmac_pair(b"other")[1]) is False


@pytest.mark.parametrize("signature", [b"", "sig", bytearray(b"sig"), None])
def test_a_missing_or_wrong_typed_signature_is_false(signature):
    assert lock_result_signature_ok(a_result(signature=signature), lambda d, s: True) is False


def test_a_verifier_that_raises_or_answers_truthy_is_false():
    def raises(d, s):
        raise RuntimeError("boom")

    assert lock_result_signature_ok(a_result(signature=b"x"), raises) is False
    assert lock_result_signature_ok(a_result(signature=b"x"), lambda d, s: 1) is False
    with pytest.raises(TypeError):
        lock_result_signature_ok(a_result(signature=b"x"), None)
