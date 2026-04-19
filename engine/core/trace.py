from __future__ import annotations

from engine.core.error_taxonomy import log_swallowed_exception
from engine.core.factions import sync_faction_statuses_from_trace
from engine.systems.disguise import ensure_disguise
from typing import Any


def get_trace_tier(state: dict[str, Any]) -> dict[str, Any]:
    """Security / mobility tier from trace_pct (deterministic, no RNG).

    Tier IDs: Ghost, Flagged, Wanted, Lockdown.
    Friction multipliers apply to travel time (and optional cash hooks).

    Boundaries (strict ``>`` where specified in design):
    - Ghost: 0–25
    - Flagged: 26–50
    - Wanted: 51–75 (multiplier 1.2)
    - Lockdown: 76–100 (multiplier 2.0)
    """
    tr = state.get("trace", {}) or {}
    if not isinstance(tr, dict):
        pct = 0
    else:
        try:
            pct = int(tr.get("trace_pct", 0) or 0)
        except Exception as _omni_sw_24:
            log_swallowed_exception('engine/core/trace.py:24', _omni_sw_24)
            pct = 0
    pct = max(0, min(100, pct))
    if pct > 75:
        return {"tier_id": "Lockdown", "friction_multiplier": 2.0, "trace_pct": pct}
    if pct > 50:
        return {"tier_id": "Wanted", "friction_multiplier": 1.2, "trace_pct": pct}
    if pct > 25:
        return {"tier_id": "Flagged", "friction_multiplier": 1.0, "trace_pct": pct}
    return {"tier_id": "Ghost", "friction_multiplier": 1.0, "trace_pct": pct}


def apply_trace_travel_friction(state: dict[str, Any], base_minutes: int) -> tuple[int, bool]:
    """Scale travel minutes by ``get_trace_tier`` friction. Returns (new_minutes, applied)."""
    tier = get_trace_tier(state)
    try:
        mult = float(tier.get("friction_multiplier", 1.0) or 1.0)
    except Exception as _omni_sw_41:
        log_swallowed_exception('engine/core/trace.py:41', _omni_sw_41)
        mult = 1.0
    b = max(1, int(base_minutes))
    if mult <= 1.0:
        return b, False
    new_m = max(1, int(round(b * mult)))
    return new_m, new_m > b


def fmt_trace_monitor_ui(state: dict[str, Any]) -> str:
    """Single HUD string: ``pct% [TierId]`` (for prompts/tests/UI helpers)."""
    t = get_trace_tier(state)
    return f"{int(t.get('trace_pct', 0) or 0)}% [{t.get('tier_id', 'Ghost')}]"


def apply_npc_snitch_report_trace(state: dict[str, Any], npc_id: str) -> int:
    """Raise trace after an NPC files a report with authorities (deterministic).

    - Disguise **active**: +5 trace (weak lead).
    - No disguise: +20 trace (positive ID).

    Returns the delta applied (after clamp).
    """
    _ = npc_id  # reserved for future per-NPC modifiers / news attribution
    tr = state.setdefault("trace", {})
    if not isinstance(tr, dict):
        tr = {}
        state["trace"] = tr
    pct = int(tr.get("trace_pct", 0) or 0)
    d = ensure_disguise(state)
    active = bool(d.get("active"))
    delta = 5 if active else 20
    pct = max(0, min(100, pct + int(delta)))
    tr["trace_pct"] = pct
    tr["trace_status"] = "Ghost" if pct <= 25 else "Flagged" if pct <= 50 else "Investigated" if pct <= 75 else "Manhunt"
    try:
        sync_faction_statuses_from_trace(state)
    except Exception as _omni_sw_82:
        log_swallowed_exception('engine/core/trace.py:82', _omni_sw_82)
    return int(delta)


def update_trace(state: dict, action_ctx: dict) -> None:
    tr = state.setdefault("trace", {})
    pct = int(tr.get("trace_pct", 0))
    year = int(state.get("player", {}).get("year", 2025) or 2025)
    if year < 1990:
        inactive_days = int(action_ctx.get("inactive_days", 0))
        pct = max(0, pct - (inactive_days // 7) * 5)
    if action_ctx.get("alias_cross_context"):
        pct += 8
    pct = max(0, min(100, pct))
    tr["trace_pct"] = pct
    tr["trace_status"] = "Ghost" if pct <= 25 else "Flagged" if pct <= 50 else "Investigated" if pct <= 75 else "Manhunt"

    # Mirror trace tiers into faction attention tiers.
    try:
        sync_faction_statuses_from_trace(state)
    except Exception as _omni_sw_105:
        log_swallowed_exception('engine/core/trace.py:105', _omni_sw_105)