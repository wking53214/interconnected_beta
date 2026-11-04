"""beta binds a Decision to one pipeline run: its context, and the digests of the inputs it was made from.

Context and lineage are optional and present only when supplied, so every digest made without them is unchanged
(that is held by test_cns_connector.py). With a context, beta refuses to bind a Decision that is about another
entity, that cites a lock it has no lock-result digest for, or whose lineage is missing or malformed.

These skip where ``cns`` is not installed. CI installs the extra and sets BETA_REQUIRE_CNS=1, so there they cannot skip.
"""
import os
from datetime import datetime

import pytest

if os.environ.get("BETA_REQUIRE_CNS") == "1":  # CI: a missing cns is a failure, not a skip
    import cns.gate as gate
else:
    gate = pytest.importorskip("cns.gate")

from beta import Decision  # noqa: E402
from beta.cns_connector import (  # noqa: E402
    CONTEXT_SCHEMA, DECISION_SUBJECT, binds, decision_content, decision_digest)

T0 = datetime(2026, 1, 1, 12, 0, 0)


def d(label):
    return gate.subject_digest({"label": label})


def decision(**over):
    base = dict(entity_id="p1", decision_id="r", decision="ESCALATE", timestamp=T0, confidence=0.9,
                triggered_by_locks=("sepsis_lock",), triggered_by_keys=("septic_shock",),
                decision_fingerprint="f" * 64)
    base.update(over)
    return Decision(**base)


CTX = {"schema": CONTEXT_SCHEMA, "entity_id": "p1", "event_id": "ev-1", "run_id": "run-1"}


def lineage(**over):
    base = dict(context=dict(CTX), keyset_digest=d("keys"), lock_result_digests={"sepsis_lock": d("sepsis")})
    base.update(over)
    return base


def test_without_a_context_the_content_carries_no_context_or_lineage():
    content = decision_content(decision())
    assert not {"context", "keyset_digest", "lock_result_digests"} & set(content)


def test_with_a_context_the_content_carries_it_and_the_lineage_sorted():
    content = decision_content(decision(), **lineage(lock_result_digests={"z_lock": d("z"), "sepsis_lock": d("s")}))
    assert content["context"] == CTX and content["keyset_digest"] == d("keys")
    assert list(content["lock_result_digests"]) == ["sepsis_lock", "z_lock"]
    assert decision_digest(decision(), **lineage()) != decision_digest(decision())


@pytest.mark.parametrize("change", [
    {"context": {**CTX, "event_id": "ev-2"}},
    {"context": {**CTX, "run_id": "run-2"}},
    {"keyset_digest": d("other keys")},
    {"lock_result_digests": {"sepsis_lock": d("another lock result")}},
])
def test_any_change_to_the_context_or_the_lineage_changes_the_digest(change):
    assert decision_digest(decision(), **lineage()) != decision_digest(decision(), **lineage(**change))


def test_a_decision_about_another_entity_is_refused():
    with pytest.raises(ValueError, match="Decision is about 'p2' but the context is about 'p1'"):
        decision_content(decision(entity_id="p2"), **lineage())


def test_a_decision_citing_a_lock_with_no_lock_result_digest_is_refused():
    with pytest.raises(ValueError, match="no lock result digest.*sepsis_lock"):
        decision_content(decision(), **lineage(lock_result_digests={"other_lock": d("o")}))


def test_a_context_without_its_lineage_is_refused():
    with pytest.raises(ValueError, match="needs keyset_digest and lock_result_digests"):
        decision_content(decision(), context=dict(CTX))
    with pytest.raises(ValueError, match="needs keyset_digest and lock_result_digests"):
        decision_content(decision(), context=dict(CTX), keyset_digest=d("keys"))
    with pytest.raises(ValueError, match="needs keyset_digest and lock_result_digests"):
        decision_content(decision(), **lineage(lock_result_digests={}))


def test_lineage_without_a_context_is_refused():
    with pytest.raises(ValueError, match="lineage digests need a context"):
        decision_content(decision(), keyset_digest=d("keys"))
    with pytest.raises(ValueError, match="lineage digests need a context"):
        decision_content(decision(), lock_result_digests={"sepsis_lock": d("s")})


@pytest.mark.parametrize("bad, exc, match", [
    ({k: v for k, v in CTX.items() if k != "run_id"}, ValueError, "exactly"),
    ({**CTX, "extra": "x"}, ValueError, "exactly"),
    ({**CTX, "run_id": ""}, ValueError, "non-empty"),
    ({**CTX, "run_id": 7}, TypeError, "must be a str"),
    ({**CTX, "schema": "spine-context/99"}, ValueError, "unsupported context schema"),
    ("not a mapping", TypeError, "mapping"),
])
def test_a_malformed_context_is_refused(bad, exc, match):
    with pytest.raises(exc, match=match):
        decision_content(decision(), **lineage(context=bad))


@pytest.mark.parametrize("bad, exc", [("A" * 64, ValueError), ("abc", ValueError), (b"x", TypeError), (None, None)])
def test_a_malformed_digest_is_refused(bad, exc):
    if exc is None:  # None for keyset_digest is "not supplied", which a context refuses as missing lineage
        with pytest.raises(ValueError, match="needs keyset_digest"):
            decision_content(decision(), **lineage(keyset_digest=bad))
        return
    with pytest.raises(exc):
        decision_content(decision(), **lineage(keyset_digest=bad))
    with pytest.raises(exc):
        decision_content(decision(), **lineage(lock_result_digests={"sepsis_lock": bad}))


def test_binds_checks_a_verdict_issued_against_the_run_bound_decision():
    verdict = gate.GateResult(gate="g", position=gate.GatePosition.OMEGA, outcome=gate.GateOutcome.PASS,
                              reason="issued for the test", subject=DECISION_SUBJECT,
                              subject_digest=decision_digest(decision(), **lineage()))
    assert binds(verdict, decision(), **lineage())
    assert not binds(verdict, decision())  # the lenient digest is a different binding
    assert not binds(verdict, decision(), **lineage(context={**CTX, "run_id": "run-2"}))
