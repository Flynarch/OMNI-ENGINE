"""W2-3: lightweight NPC daily goals — bounded, deterministic, one tick per calendar day."""
from __future__ import annotations

import hashlib
from typing import Any

from engine.core.error_taxonomy import log_swallowed_exception
from engine.social.ripple_queue import enqueue_ripple
from engine.world.heat import bump_heat

GOAL_TYPES = ("earn_money", "spread_influence", "reduce_heat")


def _h(*parts: Any) -> int:
    s = "|".join(str(p) for p in parts)
    return int(hashlib.md5(s.encode("utf-8", errors="ignore")).hexdigest()[:8], 16)


def _ensure_agenda(npc: dict[str, Any]) -> dict[str, Any]:
    ag = npc.setdefault("w2_agenda", {})
    if not isinstance(ag, dict):
        ag = {}
        npc["w2_agenda"] = ag
    ag.setdefault("daily_goal", "")
    ag.setdefault("goal_progress", 0)
    ag.setdefault("goal_deadline_day", 0)
    ag.setdefault("goal_outcome", "")
    return ag


def _pick_goal(npc_name: str, day: int, seed_pack: str) -> tuple[str, int]:
    h = _h("ag_goal", seed_pack, day, npc_name) % 3
    goal = GOAL_TYPES[h]
    span = 2 + (_h("ag_span", seed_pack, day, npc_name) % 3)
    return goal, int(span)


def tick_npc_agendas_daily(state: dict[str, Any], *, day: int) -> dict[str, int]:
    """Advance or assign agendas; max 3 ripples/day from spread_influence."""
    world = state.setdefault("world", {})
    if not isinstance(world, dict):
        return {"npcs": 0, "ripples": 0, "completed": 0}
    try:
        last = int(world.get("last_npc_agenda_day", 0) or 0)
    except Exception as _omni_sw_41:
        log_swallowed_exception('engine/npc/npc_agenda.py:41', _omni_sw_41)
        last = 0
    if last == int(day):
        return {"npcs": 0, "ripples": 0, "completed": 0, "skipped": 1}
    world["last_npc_agenda_day"] = int(day)

    meta = state.get("meta", {}) or {}
    seed = str(meta.get("seed_pack", "") or meta.get("world_seed", "") or "")
    npcs = state.get("npcs", {}) or {}
    if not isinstance(npcs, dict):
        return {"npcs": 0, "ripples": 0, "completed": 0}

    ripples_left = 3
    stats = {"npcs": 0, "ripples": 0, "completed": 0}
    names = sorted([str(n) for n in npcs.keys() if isinstance(n, str)])[:80]

    for nm in names:
        npc = npcs.get(nm)
        if not isinstance(npc, dict):
            continue
        if npc.get("alive") is False:
            continue
        ag = _ensure_agenda(npc)
        gd = int(ag.get("goal_deadline_day", 0) or 0)
        goal = str(ag.get("daily_goal", "") or "")

        if not goal or gd < int(day):
            g, span = _pick_goal(nm, int(day), seed)
            ag["daily_goal"] = g
            ag["goal_progress"] = 0
            ag["goal_deadline_day"] = int(day) + int(span)
            ag["goal_outcome"] = ""
            goal = g

        prog = int(ag.get("goal_progress", 0) or 0)
        prev_prog = prog
        if goal == "earn_money":
            prog += 12 + (_h("em", seed, day, nm) % 10)
        elif goal == "spread_influence":
            prog += 8 + (_h("si", seed, day, nm) % 8)
        elif goal == "reduce_heat":
            prog += 10 + (_h("rh", seed, day, nm) % 12)
            loc = str(npc.get("current_location", "") or npc.get("home_location", "") or "").strip().lower()
            if loc and prev_prog < 40 <= prog:
                try:
                    bump_heat(state, loc=loc, delta=-2, reason="npc_agenda_cool", ttl_days=3)
                except Exception as _omni_sw_89:
                    log_swallowed_exception('engine/npc/npc_agenda.py:89', _omni_sw_89)
        ripple_prog = int(prog)
        ag["goal_progress"] = int(prog)
        deadline = int(ag.get("goal_deadline_day", 0) or 0)

        if goal == "spread_influence" and ripples_left > 0 and ripple_prog >= 55 and _h("ripple", seed, day, nm) % 5 != 0:
            try:
                loc = str(npc.get("current_location", "") or npc.get("home_location", "") or "").strip().lower()
                if loc:
                    enqueue_ripple(
                        state,
                        {
                            "kind": "npc_agenda_influence",
                            "text": f"{nm} spreads local talk (agenda).",
                            "triggered_day": int(day),
                            "surface_day": int(day),
                            "surface_time": min(1439, 15 * 60),
                            "surfaced": False,
                            "propagation": "local_witness",
                            "visibility": "local",
                            "origin_location": loc,
                            "origin_faction": "",
                            "witnesses": [],
                            "surface_attempts": 0,
                            "meta": {"npc": nm, "goal": "spread_influence"},
                        },
                    )
                    ripples_left -= 1
                    stats["ripples"] += 1
            except Exception as _omni_sw_122:
                log_swallowed_exception('engine/npc/npc_agenda.py:122', _omni_sw_122)
        prog = int(ag.get("goal_progress", 0) or 0)
        if prog >= 100:
            ag["goal_outcome"] = "success"
            ag["daily_goal"] = ""
            ag["goal_deadline_day"] = 0
            ag["goal_progress"] = 0
            stats["completed"] += 1
        elif int(day) > deadline and deadline > 0:
            ag["goal_outcome"] = "failed"
            ag["daily_goal"] = ""
            ag["goal_deadline_day"] = 0
            ag["goal_progress"] = 0

        npc["w2_agenda"] = ag
        npcs[nm] = npc
        stats["npcs"] += 1

    state["npcs"] = npcs
    world["last_npc_agenda_day"] = int(day)
    state["world"] = world
    return stats


def ensure_npc_has_agenda_fields(npc: dict[str, Any]) -> None:
    _ensure_agenda(npc)
