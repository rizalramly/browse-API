"""Classification gate (plan 3.2): sensitive queries fail closed, provably."""
from pathlib import Path

import pytest

from app.policy import PolicyGate

REPO_POLICY = Path(__file__).parent.parent / "policy" / "sensitive.yml"


def test_shipped_policy_file_loads_with_rules() -> None:
    gate = PolicyGate.from_file(REPO_POLICY)
    assert gate.rule_count > 0


@pytest.mark.parametrize(
    ("query", "category"),
    [
        ("scada network diagram", "grid-operations"),
        ("SCADA vendor comparison", "grid-operations"),  # case-insensitive
        ("dokumen sulit tnb", "confidential-markers"),
        ("tender evaluation committee members", "procurement"),
        ("tnb security vulnerabilities 2026", "security"),
        ("janamanjung plant outage report", "named-assets"),
    ],
)
def test_seed_patterns_match(query: str, category: str) -> None:
    gate = PolicyGate.from_file(REPO_POLICY)
    assert gate.check(query) == category


@pytest.mark.parametrize(
    "query",
    [
        "attention is all you need",
        "malaysia electricity tariff 2026",       # public info stays searchable
        "how do power grids work",                 # generic, not ops-specific
        "kapar beach directions",                  # asset name without incident terms
    ],
)
def test_benign_queries_pass(query: str) -> None:
    gate = PolicyGate.from_file(REPO_POLICY)
    assert gate.check(query) is None


def test_missing_policy_file_yields_empty_gate() -> None:
    gate = PolicyGate.from_file("does/not/exist.yml")
    assert gate.rule_count == 0
    assert gate.check("scada") is None


def test_gate_from_inline_rules(tmp_path: Path) -> None:
    policy = tmp_path / "p.yml"
    policy.write_text(
        "version: 1\ncategories:\n  test-cat:\n    - '\\bforbidden\\b'\n", encoding="utf-8"
    )
    gate = PolicyGate.from_file(policy)
    assert gate.check("this is FORBIDDEN knowledge") == "test-cat"
    assert gate.check("fine query") is None
