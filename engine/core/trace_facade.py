"""Typed-ish trace view; delegates to mutation_gateway for writes."""

from __future__ import annotations

from typing import Any


class TraceFacade:
    __slots__ = ("_state",)

    def __init__(self, state: dict[str, Any]) -> None:
        self._state = state

    def pct(self) -> int:
        tr = self._state.get("trace", {}) or {}
        try:
            return int(tr.get("trace_pct", 0) or 0)
        except (TypeError, ValueError):
            return 0

    def bump(self, delta: int) -> None:
        from engine.core.mutation_gateway import bump_trace_pct

        bump_trace_pct(self._state, delta)
