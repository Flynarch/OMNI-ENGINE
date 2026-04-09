from __future__ import annotations

from typing import Any


def _brief(state: dict[str, Any]) -> tuple[str, str, int, int]:
    p = state.get("player", {}) or {}
    loc = str(p.get("location", "") or "").strip().lower()
    did = str(p.get("district", "") or "").strip().lower()
    meta = state.get("meta", {}) or {}
    try:
        day = int(meta.get("day", 1) or 1)
    except Exception:
        day = 1
    try:
        tmin = int(meta.get("time_min", 0) or 0)
    except Exception:
        tmin = 0
    return (loc, did, day, tmin)


def _local_level(world: dict[str, Any], root_key: str, loc: str) -> int:
    root = world.get(root_key, {}) if isinstance(world.get(root_key), dict) else {}
    if not (isinstance(root, dict) and loc):
        return 0
    loc_map = root.get(loc) if isinstance(root.get(loc), dict) else None
    if not isinstance(loc_map, dict):
        return 0
    row = loc_map.get("__all__") if isinstance(loc_map.get("__all__"), dict) else None
    if not isinstance(row, dict):
        return 0
    try:
        return int(row.get("level", 0) or 0)
    except Exception:
        return 0


def schedule_travel_encounters(state: dict[str, Any], action_ctx: dict[str, Any]) -> dict[str, Any]:
    """Deterministically schedule at most one travel encounter event based on heat/suspicion/trace."""
    if str(action_ctx.get("action_type", "") or "") != "travel":
        return {"scheduled": False, "reason": "not_travel"}
    flags = state.get("flags", {}) or {}
    if isinstance(flags, dict) and not bool(flags.get("scenes_enabled", True)):
        return {"scheduled": False, "reason": "scenes_disabled"}
    if isinstance(state.get("active_scene"), dict):
        return {"scheduled": False, "reason": "scene_active"}

    loc, did, day, tmin = _brief(state)
    world = state.get("world", {}) or {}
    if not (isinstance(world, dict) and loc):
        return {"scheduled": False, "reason": "no_location"}

    # Gate: at most one scheduled travel encounter per (day,turn).
    meta = state.get("meta", {}) or {}
    try:
        turn = int(meta.get("turn", 0) or 0)
    except Exception:
        turn = 0
    sched = world.setdefault("encounter_sched", {})
    if not isinstance(sched, dict):
        sched = {}
        world["encounter_sched"] = sched
    key = f"travel:{day}:{turn}"
    if key in sched:
        return {"scheduled": False, "reason": "already_scheduled"}

    heat = _local_level(world, "heat_map", loc)
    susp = _local_level(world, "suspicion", loc)
    try:
        trace = int((state.get("trace", {}) or {}).get("trace_pct", 0) or 0)
    except Exception:
        trace = 0

    # Deterministic score -> choose encounter type.
    score = int(heat * 0.6 + susp * 0.8 + trace * 0.3)
    if score < 55:
        return {"scheduled": False, "reason": "low_score", "score": score}

    # Optional border control override when destination country has strict borders (year-aware).
    dest = str(action_ctx.get("travel_destination", "") or "").strip().lower()
    bc = 0
    if dest:
        try:
            from engine.world.atlas import ensure_country_history_idx, ensure_location_profile

            meta = state.get("meta", {}) or {}
            sy = int(meta.get("sim_year", 0) or 0)
            prof = ensure_location_profile(state, dest)
            c = str((prof.get("country") if isinstance(prof, dict) else "") or "").strip().lower()
            if c:
                hi = ensure_country_history_idx(state, c, sim_year=sy)
                bc = int((hi.get("border_controls", 0) if isinstance(hi, dict) else 0) or 0)
        except Exception:
            bc = 0

    # Pick one event type (traffic_stop simpler, vehicle_search harsher).
    # Border control is preferred if borders are strict enough.
    event_type = "border_control" if bc >= 60 else ("traffic_stop" if score < 85 else "vehicle_search")
    due_time = min(1439, int(tmin) + 1)
    payload = {
        "location": loc,
        "district": did,
        "score": int(score),
        "heat": int(heat),
        "suspicion": int(susp),
        "trace": int(trace),
        "travel_destination": dest,
        "border_controls": int(bc),
    }
    pe = state.setdefault("pending_events", [])
    if isinstance(pe, list):
        pe.append({"event_type": event_type, "title": f"Travel Encounter — {event_type}", "due_day": int(day), "due_time": int(due_time), "triggered": False, "payload": payload})
    sched[key] = {"event_type": event_type, "due_day": int(day), "due_time": int(due_time)}
    world["encounter_sched"] = sched
    return {"scheduled": True, "event_type": event_type, "score": score}

