"""beta's own copy of the lock-result signing rules, so beta checks a signature over bytes it built itself.

beta holds no key and signs nothing. It rebuilds the exact bytes zeta signs a LockResult over and hands them, with the
signature, to the ``verify`` callable the operator supplies. Building the bytes here, not calling zeta's builder, means a
changed or replaced zeta builder cannot make a forged result check out.

The rules are a byte-for-byte copy of interconnected_delta's ``delta.signing`` (and of ``zeta.signing``): a domain label
of the form ``<repo>-<object>-signature/<version>`` plus a newline, then canonical ASCII JSON (sorted keys, no spaces,
``ensure_ascii``, no NaN), with every string checked as strict UTF-8 first. ``tests/test_signing.py`` holds this copy
to zeta's output and to DELTA's ``strict_utf8``.

This module imports nothing from CNS and nothing cryptographic.
"""
import json
from collections.abc import Callable

from zeta import LockResult

LOCK_RESULT_SIGNATURE_DOMAIN = b"zeta-lock-result-signature/1\n"
LOCK_RESULT_SCHEMA = "zeta-lock-result/1"

_STR_FIELDS = ("lock_id", "keyset_fingerprint", "entity_id")
_BOOL_FIELDS = ("open", "changed", "forced", "stale")


def strict_utf8(name: str, value: str) -> None:
    """``ValueError`` naming ``name`` unless ``value`` encodes as strict UTF-8 (so no lone or paired surrogates).

    ``ensure_ascii`` JSON writes an astral character and the surrogate pair of two code points the same way, so
    without this two different strings would share one signing input."""
    try:
        value.encode("utf-8")
    except UnicodeEncodeError:
        raise ValueError(f"{name} does not encode as strict UTF-8 (a surrogate code point is not a character)") from None


def lock_result_signing_input(result: LockResult) -> bytes:
    """The exact bytes zeta signs a lock result over, rebuilt here. Same rules and refusals as zeta's builder: an exact
    ``LockResult``, exact field types, and a non-empty ``lock_id``, ``entity_id`` and ``keyset_fingerprint``."""
    if type(result) is not LockResult:
        raise TypeError(f"a lock result is an exact LockResult; got {type(result).__name__}")
    body: dict = {"schema": LOCK_RESULT_SCHEMA}
    for name in _STR_FIELDS:
        value = getattr(result, name)
        if type(value) is not str:
            raise TypeError(f"lock result field {name} must be an exact str; got {type(value).__name__}")
        if not value:
            raise ValueError(f"lock result field {name} must be non-empty to be signed")
        strict_utf8(f"lock result field {name}", value)
        body[name] = value
    for name in _BOOL_FIELDS:
        value = getattr(result, name)
        if type(value) is not bool:
            raise TypeError(f"lock result field {name} must be an exact bool; got {type(value).__name__}")
        body[name] = value
    reasons = result.reasons
    if type(reasons) is not list:
        raise TypeError(f"lock result field reasons must be an exact list; got {type(reasons).__name__}")
    for i, reason in enumerate(reasons):
        if type(reason) is not str:
            raise TypeError(f"lock result field reasons[{i}] must be an exact str; got {type(reason).__name__}")
        strict_utf8(f"lock result field reasons[{i}]", reason)
    body["reasons"] = list(reasons)
    text = json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False)
    return LOCK_RESULT_SIGNATURE_DOMAIN + text.encode("ascii")


def lock_result_signature_ok(result: LockResult, verify: Callable[[bytes, bytes], bool]) -> bool:
    """Whether ``result.signature`` checks out under ``verify``: ``verify(signing_input, signature)`` must answer
    exactly ``True``. A missing or non-``bytes`` signature, a result that cannot be signed, any other answer and any
    exception from ``verify`` are all ``False``."""
    if not callable(verify):
        raise TypeError(f"verify must be callable; got {type(verify).__name__}")
    signature = getattr(result, "signature", b"")
    if type(signature) is not bytes or not signature:
        return False
    try:
        data = lock_result_signing_input(result)
    except (TypeError, ValueError):
        return False
    try:
        return verify(data, signature) is True
    except Exception:
        return False
