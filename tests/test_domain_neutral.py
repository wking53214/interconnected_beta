"""The package describes a generic decision engine: no domain's vocabulary appears in its code or comments as an example.

Provenance is kept on purpose: lines that say where something was extracted from (they name OBSERVE or observe_consolidated.py) may use the
original system's words, because that is true history. Tests and examples may use domain strings as data; this guard covers only the package.
"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOMAIN_WORDS = re.compile(r"patient|sepsis|septic|discharge|vitals?\b|tachy|fever|hypovol|respiratory|oxygen|neonat|infant", re.IGNORECASE)
PROVENANCE = re.compile(r"OBSERVE|observe_consolidated")


def test_the_package_uses_no_domain_example_outside_provenance_lines():
    offenders = []
    for path in sorted((ROOT / "beta").glob("*.py")):
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if DOMAIN_WORDS.search(line) and not PROVENANCE.search(line):
                offenders.append(f"{path.name}:{number}: {line.strip()}")
    assert not offenders, offenders


def test_the_readme_names_no_domain_vocabulary_for_decision_values():
    """Decision values are free-form strings the rule author picks; the README's own examples use neutral ones."""
    text = (ROOT / "README.md").read_text(encoding="utf-8")
    offenders = [line.strip() for line in text.splitlines()
                 if re.search(r"DISCHARGE|discharge", line) and not PROVENANCE.search(line)]
    assert not offenders, offenders
