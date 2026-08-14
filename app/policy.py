"""Egress classification gate (improvement plan 3.2).

Classifies each query BEFORE any cache read or provider call. A match means
the query is sensitive: the request fails closed with 403 — it never reaches
genxng's upstream engines or any commercial provider, is never cached, and
is never charged. Only the matched category is ever logged, not the query.
"""
import logging
import re
from functools import lru_cache
from pathlib import Path

import yaml

from app.config import get_settings

logger = logging.getLogger(__name__)


class PolicyBlockedError(Exception):
    """Raised when a query matches the sensitive deny-list."""

    def __init__(self, category: str) -> None:
        super().__init__(f"query blocked by policy (category: {category})")
        self.category = category


class PolicyGate:
    def __init__(self, rules: list[tuple[str, re.Pattern[str]]]) -> None:
        self._rules = rules

    @classmethod
    def from_file(cls, path: str | Path) -> "PolicyGate":
        file = Path(path)
        if not file.exists():
            # Missing file means an empty deny-list, loudly: the gate is a
            # governance control, so its absence must be visible in logs.
            logger.warning("policy file not found; classification gate is EMPTY",
                           extra={"policy_path": str(file)})
            return cls([])
        data = yaml.safe_load(file.read_text(encoding="utf-8")) or {}
        rules: list[tuple[str, re.Pattern[str]]] = []
        for category, patterns in (data.get("categories") or {}).items():
            for pattern in patterns or []:
                rules.append((str(category), re.compile(pattern, re.IGNORECASE)))
        logger.info("policy gate loaded", extra={"rules": len(rules),
                                                 "policy_path": str(file)})
        return cls(rules)

    @property
    def rule_count(self) -> int:
        return len(self._rules)

    def check(self, query: str) -> str | None:
        """Return the matched category for a sensitive query, else None."""
        for category, pattern in self._rules:
            if pattern.search(query):
                return category
        return None


@lru_cache
def get_policy_gate() -> PolicyGate:
    return PolicyGate.from_file(get_settings().policy_path)
