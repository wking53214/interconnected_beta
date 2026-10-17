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
the decision was later recorded. The set-like fields (``triggered_by_locks``,
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
from datetime import datetime, timezone
from types import ModuleType
from typing import Any, Dict

from .verdict import Decision

__all__ = [
    "CnsNotInstalled",
    "DECISION_SUBJECT",
    "binds",
    "cns_available",
    "decision_content",
    "decision_digest",
]

INSTALL_HINT = "pip install 'beta[cns] @ git+https://github.com/wking53214/interconnected_beta'"

DECISION_SUBJECT = "beta.decision"


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


def decision_content(decision: Decision) -> Dict[str, Any]:
    """The deterministic content a CNS verdict about ``decision`` is bound to.

    Only str, int, float, bool, None, list and dict with str keys, the types
    ``cns.gate.subject_digest`` accepts. Needs no CNS to build. Raises
    ``TypeError`` for anything that is not a :class:`beta.Decision`.
    """
    if not isinstance(decision, Decision):
        raise TypeError(f"expected a beta.Decision; got {type(decision).__name__}")
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


def decision_digest(decision: Decision) -> str:
    """``cns.gate.subject_digest`` of :func:`decision_content`.

    A separate binding from ``Decision.decision_fingerprint``, which is
    untouched. Pass it, with ``DECISION_SUBJECT``, to ``GateResult.binds``.
    """
    content = decision_content(decision)
    return _cns_gate().subject_digest(content)


def binds(result: Any, decision: Decision, *, subject: str = DECISION_SUBJECT) -> bool:
    """Whether ``result`` (a ``cns.gate.GateResult``) was issued against exactly ``decision``.

    False for a different decision, for a different ``subject`` label, and for
    a result that records no subject or digest (an unbound or hand-built one).
    Says nothing about what the verdict was.
    """
    gate = _cns_gate()
    if not isinstance(result, gate.GateResult):
        raise TypeError(f"expected a cns.gate.GateResult; got {type(result).__name__}")
    return bool(result.binds(subject, decision_digest(decision)))
