from __future__ import annotations

from typing import Any


def ensure_world_faction_statuses(state: dict[str, Any]) -> None:
    world = state.setdefault("world", {})
    world.setdefault(
        "faction_statuses",
        {
            "corporate": "idle",
            "police": "idle",
            "black_market": "idle",
        },
    )


def _trace_to_attention(trace_pct: int) -> str:
    # Mirrors engine trace tiers.
    if trace_pct <= 25:
        return "idle"
    if trace_pct <= 50:
        return "aware"
    if trace_pct <= 75:
        return "investigated"
    return "manhunt"


def sync_faction_statuses_from_trace(state: dict[str, Any]) -> None:
    ensure_world_faction_statuses(state)
    trace = state.get("trace", {}) or {}
    try:
        pct = int(trace.get("trace_pct", 0) or 0)
    except Exception:
        pct = 0
    attention = _trace_to_attention(pct)
    statuses = state["world"]["faction_statuses"]

    # v1: police is the primary audience; other factions mirror for narrative coherence.
    for k in ("corporate", "police", "black_market"):
        statuses[k] = attention if k != "police" else attention

