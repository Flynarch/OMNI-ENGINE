from __future__ import annotations

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
        from engine.core.factions import sync_faction_statuses_from_trace

        sync_faction_statuses_from_trace(state)
    except Exception:
        pass
