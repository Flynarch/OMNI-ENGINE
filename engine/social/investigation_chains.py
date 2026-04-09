from __future__ import annotations

import hashlib
from typing import Any


def _norm(x: Any) -> str:
    return str(x or "").strip().lower()


def _clamp(v: int, lo: int, hi: int) -> int:
    return max(lo, min(hi, int(v)))


def _det_roll_1_100(*parts: Any) -> int:
    s = "|".join([str(p) for p in parts])
    h = hashlib.md5(s.encode("utf-8", errors="ignore")).hexdigest()
    return (int(h[:8], 16) % 100) + 1


def _sched_gate(world: dict[str, Any], key: str) -> bool:
    g = world.setdefault("investigation_sched", {})
    if not isinstance(g, dict):
        g = {}
        world["investigation_sched"] = g
    if key in g:
        return False
    g[key] = True
    world["investigation_sched"] = g
    return True


def handle_informant_tip(state: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    """Convert an informant tip into investigation pressure + follow-up events."""
    meta = state.get("meta", {}) or {}
    day = int(meta.get("day", 1) or 1)
    time_min = int(meta.get("time_min", 0) or 0)
    turn = int(meta.get("turn", 0) or 0)
    world = state.setdefault("world", {})

    reporter = str(payload.get("reporter", "unknown") or "unknown")
    aff = _norm(payload.get("affiliation", "")) or "civilian"
    loc = _norm(payload.get("origin_location", "")) or _norm((state.get("player", {}) or {}).get("location", ""))
    did = _norm(payload.get("district", "")) or _norm((state.get("player", {}) or {}).get("district", ""))
    try:
        sus = int(payload.get("suspicion", 55) or 55)
    except Exception:
        sus = 55
    sus = _clamp(sus, 0, 100)

    # Casefile audit (tip received).
    try:
        from engine.world.casefile import append_casefile

        append_casefile(
            state,
            {
                "kind": "informant_tip",
                "scene_type": "",
                "event_type": "informant_tip",
                "location": loc,
                "district": did,
                "summary": f"Informant tip filed by {reporter} (aff={aff}, sus={sus})",
                "tags": ["informant", aff],
                "meta": {"reporter": reporter, "affiliation": aff, "suspicion": int(sus)},
            },
        )
    except Exception:
        pass

    # Pressure bumps (local).
    try:
        from engine.world.heat import bump_heat, bump_suspicion

        if loc:
            bump_suspicion(state, loc=loc, delta=max(1, int((sus - 45) / 12)), reason="informant_tip", ttl_days=2)
            bump_heat(state, loc=loc, delta=1, reason="informant_tip", ttl_days=6)
    except Exception:
        pass

    # Always schedule an npc_report so existing pipeline (trace bump + ripple) triggers.
    pe = state.setdefault("pending_events", [])
    if isinstance(pe, list):
        pe.append(
            {
                "event_type": "npc_report",
                "title": "NPC Report",
                "due_day": int(day),
                "due_time": min(1439, int(time_min) + 3),
                "triggered": False,
                "payload": {
                    "reporter": reporter,
                    "affiliation": aff if aff in ("police", "corporate") else "police",
                    "suspicion": int(sus),
                    "origin_location": loc,
                    "meta": {"source": "informant_tip"},
                },
            }
        )

    # Follow-up chain: depending on strength, schedule a sweep or a targeted stop/search.
    if not loc:
        return {"ok": True, "scheduled_followups": 0}

    # Gate: at most one follow-up per location per day.
    if not _sched_gate(world, f"{loc}:{day}:followup"):
        return {"ok": True, "scheduled_followups": 0, "reason": "gated"}

    r = _det_roll_1_100(day, turn, time_min, "followup", loc, reporter, aff, sus)
    followups = 0

    # Deterministic selection:
    # - High suspicion => sweep (scene-backed checkpoint_sweep).
    # - Otherwise => if player is traveling soon, traffic_stop/vehicle_search will also exist; but this is a direct pressure event.
    if sus >= 80 or (sus >= 70 and r <= 60):
        pe.append(
            {
                "event_type": "police_sweep",
                "title": "Police Sweep",
                "due_day": int(day),
                "due_time": min(1439, int(time_min) + 25),
                "triggered": False,
                "payload": {"location": loc, "attention": "investigated", "source": "informant_tip"},
            }
        )
        followups += 1
    else:
        et = "traffic_stop" if sus < 85 else "vehicle_search"
        pe.append(
            {
                "event_type": et,
                "title": "Investigation Stop",
                "due_day": int(day),
                "due_time": min(1439, int(time_min) + 10),
                "triggered": False,
                "payload": {"location": loc, "district": did, "score": int(55 + sus // 2), "source": "informant_tip"},
            }
        )
        followups += 1

    return {"ok": True, "scheduled_followups": int(followups)}

