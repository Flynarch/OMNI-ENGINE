"""Centralized helpers for high-churn narrative/state fields (mutation gateway).

Prefer these over ad-hoc writes when adding new systems so audit/journal can hook one place.
"""

from __future__ import annotations

from typing import Any


def append_world_note(state: dict[str, Any], text: str, *, max_notes: int = 400) -> None:
    s = str(text or "").strip()
    if not s:
        return
    notes = state.setdefault("world_notes", [])
    if not isinstance(notes, list):
        return
    notes.append(s if len(s) <= 500 else (s[:497] + "..."))
    if len(notes) > max_notes:
        del notes[: len(notes) - max_notes]


def set_trace_pct(state: dict[str, Any], value: int, *, clamp: bool = True) -> None:
    tr = state.setdefault("trace", {})
    if not isinstance(tr, dict):
        return
    try:
        v = int(value)
    except (TypeError, ValueError):
        return
    if clamp:
        v = max(0, min(100, v))
    tr["trace_pct"] = v


def bump_trace_pct(state: dict[str, Any], delta: int, *, clamp: bool = True) -> None:
    tr = state.setdefault("trace", {})
    if not isinstance(tr, dict):
        return
    try:
        cur = int(tr.get("trace_pct", 0) or 0)
    except (TypeError, ValueError):
        cur = 0
    set_trace_pct(state, cur + int(delta), clamp=clamp)
