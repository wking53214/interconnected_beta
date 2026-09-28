"""DecisionRule / DecisionRuleRegistry: declarative Lock-state -> Decision mapping.

Same declarative-registry philosophy as zeta.LockSpec/LockRegistry (data,
not code, so a decision can be audited by reading a table rather than
tracing Python control flow) applied one layer up: zeta answers "which
Locks are open," beta answers "given these Locks' states, what's the
governed decision, and why."

Deliberately NOT a Callable[[...], bool] predicate. Keeping rules to two
declared sets (locks that must be open, locks that must be closed) means
every rule can be printed, diffed, and reasoned about without executing
Python -- the same tradeoff zeta made with AND/OR/N_OF_M instead of
arbitrary boolean expressions.
"""

from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Tuple

from zeta import LockResult


@dataclass(frozen=True)
class DecisionRule:
    decision_id: str
    decision: str

    # ALL locks named here must be open / closed for this rule to match.
    # (An empty tuple is a vacuous "no requirement" on that side.)
    open_locks: Tuple[str, ...] = ()
    closed_locks: Tuple[str, ...] = ()

    # When multiple rules match the same Lock state, the highest-priority
    # match wins. Two matching rules at the same priority is treated as
    # an ambiguous rule set and raises rather than silently picking one
    # (see engine.py) -- the same "fail loud, not silent" stance zeta's
    # validation takes.
    priority: int = 0

    reasoning_template: str = "{decision}: locks open={open_locks}, closed={closed_locks}"
    reversal_conditions: Tuple[str, ...] = ()
    instructions: str = ""

    def __post_init__(self) -> None:
        if not self.decision_id:
            raise ValueError("decision_id must be non-empty")
        if not self.decision:
            raise ValueError(f"Rule '{self.decision_id}': decision must be non-empty")
        if not self.open_locks and not self.closed_locks:
            raise ValueError(
                f"Rule '{self.decision_id}': must require at least one open or closed lock"
            )
        overlap = set(self.open_locks) & set(self.closed_locks)
        if overlap:
            raise ValueError(
                f"Rule '{self.decision_id}': lock(s) {sorted(overlap)} listed as both "
                f"open_locks and closed_locks -- a lock cannot be required both ways"
            )

    def matches(self, lock_results: Dict[str, LockResult]) -> bool:
        for lock_id in self.open_locks:
            result = lock_results.get(lock_id)
            if result is None or not result.open:
                return False
        for lock_id in self.closed_locks:
            result = lock_results.get(lock_id)
            if result is None or result.open:
                return False
        return True


class DecisionRuleRegistry:
    def __init__(self, rules: Iterable[DecisionRule] = ()) -> None:
        self._rules: Dict[str, DecisionRule] = {}
        for r in rules:
            self.register(r)

    def register(self, rule: DecisionRule) -> None:
        if rule.decision_id in self._rules:
            raise ValueError(f"Decision rule '{rule.decision_id}' already registered")
        self._rules[rule.decision_id] = rule

    def get(self, decision_id: str) -> DecisionRule:
        try:
            return self._rules[decision_id]
        except KeyError:
            raise KeyError(f"Unknown decision rule '{decision_id}'") from None

    def all(self) -> List[DecisionRule]:
        return list(self._rules.values())

    def __len__(self) -> int:
        return len(self._rules)

    def __contains__(self, decision_id: str) -> bool:
        return decision_id in self._rules
