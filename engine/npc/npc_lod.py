from __future__ import annotations

import hashlib
from typing import Any

from engine.npc.npc_utility_ai import get_npc_lod_config, run_active_tick_for_npc_lod


def _norm(s: Any) -> str:
    return str(s or "").strip().lower()


def _det_roll_1_100(*parts: Any) -> int:
    raw = "|".join(str(p) for p in parts)
    h = hashlib.md5(raw.encode("utf-8", errors="ignore")).hexdigest()
    return (int(h[:8], 16) % 100) + 1


def _belief_pair(npc: dict[str, Any]) -> tuple[int, int]:
    bs = npc.get("belief_summary") or {}
    if not isinstance(bs, dict):
        return (0, 50)
    try:
        sus = int(bs.get("suspicion", 0) or 0)
    except Exception:
        sus = 0
    try:
        rep = int(bs.get("respect", 50) or 50)
    except Exception:
        rep = 50
    return (max(0, min(100, sus)), max(0, min(100, rep)))


def _alarm(npc: dict[str, Any]) -> int:
    try:
        fear = int(npc.get("fear", 10) or 10)
    except Exception:
        fear = 10
    try:
        surprise = int(npc.get("surprise", 0) or 0)
    except Exception:
        surprise = 0
    return max(0, min(100, int(round((fear + surprise) / 2))))


def _is_active_npc(name: str, npc: dict[str, Any], *, player_loc: str, cfg: dict[str, int]) -> bool:
    if not isinstance(npc, dict):
        return False
    loc = _norm(npc.get("current_location", "")) or _norm(npc.get("home_location", ""))
    if loc and player_loc and loc == player_loc:
        return True
    activity = _norm(npc.get("active_status", ""))
    if activity in ("investigated", "dikejar", "chased", "manhunt"):
        return True
    tags = npc.get("status_tags")
    if isinstance(tags, list):
        tagsn = {_norm(x) for x in tags if isinstance(x, str)}
        if {"investigated", "dikejar", "chased", "manhunt"} & tagsn:
            return True
    sus, _ = _belief_pair(npc)
    if sus >= int(cfg.get("active_suspicion_gte", 65) or 65):
        return True
    if _alarm(npc) >= int(cfg.get("active_alarm_gte", 70) or 70):
        return True
    _ = name
    return False


def _background_bucket(name: str, npc: dict[str, Any], *, cfg: dict[str, int]) -> int:
    lo = int(cfg.get("background_tick_min_turns", 5) or 5)
    hi = int(cfg.get("background_tick_max_turns", 10) or 10)
    lo = max(1, min(lo, hi))
    hi = max(lo, hi)
    span = hi - lo + 1
    pick = (_det_roll_1_100("npc_lod_bucket", name, _norm(npc.get("role", ""))) - 1) % span
    return lo + pick


def _apply_background_tick(state: dict[str, Any], *, name: str, npc: dict[str, Any], day: int, turn: int) -> str:
    econ = npc.setdefault("economy", {})
    if not isinstance(econ, dict):
        econ = {}
        npc["economy"] = econ
    cash = int(econ.get("cash", 0) or 0)
    stability = int(econ.get("stability", 50) or 50)
    roll = _det_roll_1_100("npc_lod_bg", day, turn, name)
    if roll <= 58:
        cash += 2
        outcome = "work_success"
    elif roll <= 88:
        cash = max(0, cash - 1)
        outcome = "work_fail"
    else:
        stability = max(0, min(100, stability - 1))
        outcome = "minor_event"
    econ["cash"] = int(max(0, min(500000, cash)))
    econ["stability"] = int(max(0, min(100, stability)))
    econ["last_bg_tick_turn"] = int(turn)
    econ["last_bg_outcome"] = str(outcome)
    up = npc.setdefault("utility_planner", {})
    if isinstance(up, dict):
        up["lod_mode"] = "background"
        up["last_background_tick_turn"] = int(turn)
    npc["economy"] = econ
    return outcome


def tick_npc_lod(state: dict[str, Any], action_ctx: dict[str, Any]) -> dict[str, int]:
    """LOD tick for NPC simulation:
    - ActiveTick: every turn for relevant NPCs.
    - BackgroundTick: every 5-10 turns for distant NPCs.
    """
    npcs = state.get("npcs", {}) or {}
    if not isinstance(npcs, dict) or not npcs:
        return {"active": 0, "background": 0}
    meta = state.get("meta", {}) or {}
    day = int(meta.get("day", 1) or 1)
    turn = int(meta.get("turn", 0) or 0)
    player_loc = _norm((state.get("player", {}) or {}).get("location", ""))
    cfg = get_npc_lod_config()

    active = 0
    background = 0
    for name in sorted([str(k) for k in npcs.keys() if isinstance(k, str)])[:240]:
        npc = npcs.get(name)
        if not isinstance(npc, dict) or npc.get("alive") is False:
            continue
        if _is_active_npc(name, npc, player_loc=player_loc, cfg=cfg):
            run_active_tick_for_npc_lod(state, npc_name=name, npc=npc, day=day, turn=turn)
            active += 1
            continue
        bucket = _background_bucket(name, npc, cfg=cfg)
        if bucket > 0 and turn % bucket == 0:
            _apply_background_tick(state, name=name, npc=npc, day=day, turn=turn)
            background += 1
    state.setdefault("meta", {})["npc_lod_last_counts"] = {"active": int(active), "background": int(background)}
    _ = action_ctx
    return {"active": int(active), "background": int(background)}

