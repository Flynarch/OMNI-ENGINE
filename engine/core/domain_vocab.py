"""Canonical domain / action vocabulary (roadmap: unified domain vocabulary).

Use these constants for LLM normalization, telemetry, and integration contracts.
"""

from __future__ import annotations

from typing import Final, FrozenSet

CANONICAL_DOMAINS: Final[FrozenSet[str]] = frozenset(
    {"evasion", "combat", "social", "hacking", "medical", "driving", "stealth", "other"}
)
CANONICAL_ACTION_TYPES: Final[FrozenSet[str]] = frozenset(
    {"instant", "combat", "travel", "sleep", "rest", "talk", "investigate", "use_item", "custom"}
)
CANONICAL_EFFECT_KEYS: Final[tuple[str, ...]] = (
    "trace_delta",
    "cash_delta",
    "rep_delta",
    "time_cost",
    "inventory_change",
    "ffci_feasibility_block",
    "intent_plan_blocked",
)
