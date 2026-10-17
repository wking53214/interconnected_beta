"""beta is independent of CNS, and these tests hold whether or not CNS is installed.

Each runs in a fresh interpreter in which ``cns`` is blocked outright
(``sys.modules['cns'] = None`` makes any import of it fail), so the result does not
depend on what the test environment happens to contain. They never skip.
"""
import ast
import os
import subprocess
import sys
import textwrap
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "beta"
BLOCK = "import sys; sys.modules['cns'] = None; sys.modules['cns.gate'] = None\n"
# The subprocess needs the same import path as this run (beta's own root, and zeta, wherever they live).
ENV = {
    "PYTHONPATH": os.pathsep.join([str(ROOT)] + [p for p in os.environ.get("PYTHONPATH", "").split(os.pathsep) if p]),
    "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
    "PYTHONDONTWRITEBYTECODE": "1",
}


def run(code: str, *, block: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, "-c", (BLOCK if block else "") + textwrap.dedent(code)],
                          capture_output=True, text=True, env=ENV, timeout=120)


def ok(done: subprocess.CompletedProcess) -> None:
    assert done.returncode == 0, done.stderr
    assert done.stdout.strip().endswith("ok"), done.stdout


def test_the_package_and_its_connector_import_with_cns_blocked():
    ok(run("import beta, beta.cns_connector; print('ok')"))


def test_the_engine_still_does_its_job_with_cns_blocked():
    ok(run("""
        from datetime import datetime
        from zeta import Combination, Key, KeySet, LockEvaluator, LockRegistry, LockSpec
        from beta import DecisionEngine, DecisionRule, DecisionRuleRegistry
        t0 = datetime(2026, 1, 1, 12, 0, 0)
        locks = LockRegistry([LockSpec(lock_id="sepsis_lock", required_keys=("septic_shock",),
                                       combination=Combination.OR, dwell_threshold=1, force=True)])
        rules = DecisionRuleRegistry([DecisionRule(decision_id="escalate", decision="ESCALATE",
                                                   open_locks=("sepsis_lock",), priority=1)])
        keys = KeySet([Key(name="septic_shock", present=True, confidence=0.9)])
        results = LockEvaluator(locks).evaluate_all("patient1", keys, t0)
        decision = DecisionEngine(rules, locks).decide("patient1", keys, results, t0)
        assert decision.decision == "ESCALATE" and decision.decision_fingerprint, decision
        print('ok')
    """))


def test_the_connector_says_what_is_missing_when_cns_is_blocked():
    ok(run("""
        from datetime import datetime
        from beta import Decision
        from beta.cns_connector import CnsNotInstalled, binds, cns_available, decision_content, decision_digest
        decision = Decision("e", "d", "x", datetime(2026, 1, 1), 1.0)
        assert cns_available() is False
        assert decision_content(decision)["entity_id"] == "e"   # building content needs no cns
        for call in (lambda: decision_digest(decision), lambda: binds(object(), decision)):
            try:
                call()
            except CnsNotInstalled as e:
                assert isinstance(e, ImportError)
                assert "beta[cns]" in str(e) and "pip install" in str(e), str(e)
            else:
                raise SystemExit("worked without cns")
        print('ok')
    """))


def test_importing_the_package_does_not_load_cns_even_when_it_is_installed():
    ok(run("""
        import sys
        import beta, beta.cns_connector
        assert not [m for m in sys.modules if m == "cns" or m.startswith("cns.")], "cns was loaded"
        print('ok')
    """, block=False))


def test_no_module_of_the_package_imports_cns_by_statement():
    offenders = {}
    sources = sorted(PACKAGE.glob("*.py"))
    assert PACKAGE / "cns_connector.py" in sources
    for path in sources:
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            names = [a.name for a in node.names] if isinstance(node, ast.Import) else \
                [node.module] if isinstance(node, ast.ImportFrom) and node.level == 0 and node.module else []
            bad = [n for n in names if n == "cns" or n.startswith("cns.")]
            if bad:
                offenders.setdefault(path.name, []).extend(bad)
    assert offenders == {}
