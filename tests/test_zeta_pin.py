"""The zeta dependency in pyproject.toml is pinned to a reviewed commit.

beta depends on zeta by git URL. Unpinned, that URL installs whatever zeta's
default branch holds on the day; pinned, every install gets the same code,
which is the code these tests ran against. The constant here moves with the
pin, and moving either is a reviewed change.
"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# The zeta commit the runtime dependency installs. Moving it is a reviewed change.
EXPECTED_ZETA_PIN = "4ba70f621ef40d53a5004809a569303707788cd0"


# pyproject is read as text: tomllib needs Python 3.11 and the floor here is 3.9.

def _runtime_dependencies() -> list:
    text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    body, inside = [], False
    for line in text.splitlines():
        header = re.match(r"^\[([^\]]+)\]\s*$", line)
        if header:
            inside = header.group(1).strip() == "project"
        elif inside:
            body.append(line)
    found = re.search(r"^dependencies\s*=\s*\[(.*?)\]\s*$", "\n".join(body), re.S | re.M)
    assert found, "no `dependencies = [...]` in [project]"
    return re.findall(r'"([^"]*)"', re.sub(r"^\s*#.*$", "", found.group(1), flags=re.M))


def test_zeta_is_pinned_to_the_reviewed_commit():
    zeta = [d for d in _runtime_dependencies() if re.match(r"\s*zeta\b", d)]
    assert len(zeta) == 1, zeta
    found = re.fullmatch(
        r"zeta @ git\+https://github\.com/wking53214/interconnected_zeta(?:\.git)?@([0-9a-f]{40})", zeta[0]
    )
    assert found is not None, zeta[0]
    assert found.group(1) == EXPECTED_ZETA_PIN
