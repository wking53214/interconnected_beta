"""Optional, binding-only connector to CNS (``cns.gate``).

beta is independent. It has no runtime dependency on CNS, imports nothing from
CNS when it loads, and its whole suite passes with CNS absent. This module is
the one place that knows CNS exists, and it asks for CNS only when one of its
functions is called. Without CNS installed those calls raise
:class:`CnsNotInstalled` with the install command; nothing else in beta is
affected.

What this binds
---------------
CNS's shared gate contract is ``cns.gate.GateResult``. A result that records a
``subject`` and a ``subject_digest`` can later be checked against the content it
was issued for: ``GateResult.binds(subject, digest)`` is true only when the
verdict was issued against exactly that content. This module makes a
:class:`beta.Decision` bindable in that way, so that a CNS verdict about a
decision can be checked against the decision.

Binding only
------------
This is deliberately not a gate and it invents no verdict. There is no mapping
from a Decision to ``PASS``, ``RETRY`` or ``TERMINAL_BREACH``. A Decision is a
governed recommendation ("ESCALATE", "HOLD", "DISCHARGE_SAFE" are conventions
a rule author picks, see the README), and turning it into a gate outcome would
assign it a meaning beta does not have. Whoever issues a verdict about a
decision owns that meaning; this module only lets them say which decision it
was about.

Separate from beta's own fingerprint
------------------------------------
``Decision.decision_fingerprint`` is beta's own SHA-256 of the inputs that
produced a decision (entity, rule, triggering locks and keys). It is untouched
by this module and unaware of it. The digest here is an additional, separate
binding: ``cns.gate.subject_digest`` over the whole Decision as an output,
including the narrative, the confidence, the timestamp and the fingerprint
itself. The two answer different questions and neither replaces the other.

What the content holds, and what it leaves out
----------------------------------------------
Every field of a Decision is bound except ``audit_hash``, which is a pointer
into a ledger that beta never fills (the ledger stage stamps it after the
decision exists). Binding it would make a verdict stop matching merely because
the decision was later recorded. ``confidence_basis`` is not bound either: it
is derived from fields that already are (an empty ``triggered_by_keys`` means
an absence-only match), and leaving it out keeps every existing digest
stable. The set-like fields (``triggered_by_locks``,
``triggered_by_keys``, ``newly_triggered_locks``) are sorted so order cannot
change the digest. ``reversal_conditions`` keeps its order: it is authored
narrative. ``confidence`` is rendered as a float, so ``1`` and ``1.0`` bind
alike (CNS tells an int from a float). A timezone-aware timestamp is rendered
in UTC, so the same instant bound from two offsets is one digest; a naive and
an aware timestamp stay distinct. A NaN or infinite confidence cannot be bound
and raises ``TypeError`` from CNS.

Install with the extra:
``pip install 'beta[cns] @ git+https://github.com/wking53214/interconnected_beta'``.
"""

import importlib
import re
from collections.abc import Mapping
from datetime import datetime, timezone
from types import ModuleType
from typing import Any, Dict, Optional

from .verdict import Decision

__all__ = [
    "CONTEXT_SCHEMA",
    "CnsNotInstalled",
    "DECISION_SUBJECT",
    "binds",
    "cns_available",
    "decision_content",
    "decision_digest",
]

INSTALL_HINT = "pip install 'beta[cns] @ git+https://github.com/wking53214/interconnected_beta'"

DECISION_SUBJECT = "beta.decision"

# One pipeline run, named the same way by every stage's connector (CNS publishes the contract in
# cns_composition.pipeline_context and holds the four copies to it). A plain mapping, so beta imports nothing.
CONTEXT_SCHEMA = "spine-context/1"
_CONTEXT_FIELDS = ("schema", "entity_id", "event_id", "run_id")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class CnsNotInstalled(ImportError):
    """Raised by this module's functions when ``cns`` cannot be imported."""


def _cns_gate() -> ModuleType:
    """Import ``cns.gate`` on demand, or say exactly what is missing."""
    try:
        return importlib.import_module("cns.gate")
    except ImportError as exc:
        raise CnsNotInstalled(
            "beta.cns_connector needs the CNS package (cns.gate), which is not "
            f"installed. Install it with: {INSTALL_HINT}. beta itself works "
            "without it."
        ) from exc


def cns_available() -> bool:
    """Whether the CNS gate contract can be imported in this environment."""
    try:
        _cns_gate()
    except CnsNotInstalled:
        return False
    return True


def _instant(value: Any) -> str:
    """ISO text of a timestamp; an aware one is rendered in UTC."""
    if not isinstance(value, datetime):
        raise TypeError(f"a Decision timestamp must be a datetime; got {type(value).__name__}")
    if value.tzinfo is not None and value.utcoffset() is not None:
        value = value.astimezone(timezone.utc)
    return value.isoformat()


def _number(value: Any, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"a Decision {label} must be a number; got {type(value).__name__}")
    return float(value)


def _context(context: Any) -> Dict[str, str]:
    """A validated copy of a pipeline context: exactly the four fields, all non-empty strings, a known schema."""
    if not isinstance(context, Mapping):
        raise TypeError(f"a pipeline context must be a mapping; got {type(context).__name__}")
    if set(context) != set(_CONTEXT_FIELDS):
        raise ValueError(f"a pipeline context has exactly the fields {list(_CONTEXT_FIELDS)}; got {sorted(map(str, context))}")
    for name in _CONTEXT_FIELDS:
        if not isinstance(context[name], str):
            raise TypeError(f"context field {name} must be a str; got {type(context[name]).__name__}")
        if not context[name]:
            raise ValueError(f"context field {name} must be non-empty")
    if context["schema"] != CONTEXT_SCHEMA:
        raise ValueError(f"unsupported context schema {context['schema']!r}; this connector speaks {CONTEXT_SCHEMA!r}")
    return {name: context[name] for name in _CONTEXT_FIELDS}


def _digest(value: Any, what: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{what} must be a str digest; got {type(value).__name__}")
    if not _SHA256.match(value):
        raise ValueError(f"{what} is not a full lowercase SHA-256 digest")
    return value


def decision_content(
    decision: Decision,
    *,
    context: Optional[Mapping] = None,
    keyset_digest: Optional[str] = None,
    lock_result_digests: Optional[Mapping] = None,
) -> Dict[str, Any]:
    """The deterministic content a CNS verdict about ``decision`` is bound to.

    Only str, int, float, bool, None, list and dict with str keys, the types
    ``cns.gate.subject_digest`` accepts. Needs no CNS to build. Raises
    ``TypeError`` for anything that is not a :class:`beta.Decision`.

    ``context``, ``keyset_digest`` and ``lock_result_digests`` bind the Decision to one pipeline run and to the
    exact inputs it was made from. All three come together or not at all, and with them the content gains
    ``context``, ``keyset_digest`` and ``lock_result_digests``; without them the content is exactly what it
    always was. The Decision must be about the context's entity, and every lock it cites must have a lock-result
    digest.
    """
    if not isinstance(decision, Decision):
        raise TypeError(f"expected a beta.Decision; got {type(decision).__name__}")
    content = _decision_content(decision)
    if context is None:
        if keyset_digest is not None or lock_result_digests is not None:
            raise ValueError("lineage digests need a context")
        return content
    ctx = _context(context)
    if keyset_digest is None or not lock_result_digests:
        raise ValueError("a context needs keyset_digest and lock_result_digests")
    if not isinstance(lock_result_digests, Mapping):
        raise TypeError(f"lock_result_digests must be a mapping; got {type(lock_result_digests).__name__}")
    if decision.entity_id != ctx["entity_id"]:
        raise ValueError(f"the Decision is about {decision.entity_id!r} but the context is about {ctx['entity_id']!r}")
    locks = {}
    for lock_id, digest in lock_result_digests.items():
        if not isinstance(lock_id, str):
            raise TypeError(f"a lock_result_digests key must be a str; got {type(lock_id).__name__}")
        locks[lock_id] = _digest(digest, f"the lock result digest for {lock_id!r}")
    missing = sorted(set(decision.triggered_by_locks) - set(locks))
    if missing:
        raise ValueError(f"the Decision cites lock(s) with no lock result digest: {', '.join(missing)}")
    content["context"] = ctx
    content["keyset_digest"] = _digest(keyset_digest, "keyset_digest")
    content["lock_result_digests"] = {k: locks[k] for k in sorted(locks)}
    return content


def _decision_content(decision: Decision) -> Dict[str, Any]:
    return {
        "entity_id": decision.entity_id,
        "decision_id": decision.decision_id,
        "decision": decision.decision,
        "timestamp": _instant(decision.timestamp),
        "confidence": _number(decision.confidence, "confidence"),
        "triggered_by_locks": sorted(decision.triggered_by_locks),
        "triggered_by_keys": sorted(decision.triggered_by_keys),
        "newly_triggered_locks": sorted(decision.newly_triggered_locks),
        "decision_fingerprint": decision.decision_fingerprint,
        "reasoning": decision.reasoning,
        "reversal_conditions": list(decision.reversal_conditions),
        "instructions": decision.instructions,
    }


def decision_digest(decision: Decision, **run: Any) -> str:
    """``cns.gate.subject_digest`` of :func:`decision_content`.

    A separate binding from ``Decision.decision_fingerprint``, which is
    untouched. Pass it, with ``DECISION_SUBJECT``, to ``GateResult.binds``. The keyword arguments are
    :func:`decision_content`'s ``context``, ``keyset_digest`` and ``lock_result_digests``.
    """
    content = decision_content(decision, **run)
    return _cns_gate().subject_digest(content)


def binds(result: Any, decision: Decision, *, subject: str = DECISION_SUBJECT, **run: Any) -> bool:
    """Whether ``result`` (a ``cns.gate.GateResult``) was issued against exactly ``decision``.

    False for a different decision, for a different ``subject`` label, and for
    a result that records no subject or digest (an unbound or hand-built one).
    Says nothing about what the verdict was.
    """
    gate = _cns_gate()
    if not isinstance(result, gate.GateResult):
        raise TypeError(f"expected a cns.gate.GateResult; got {type(result).__name__}")
    return bool(result.binds(subject, decision_digest(decision, **run)))
