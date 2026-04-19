from __future__ import annotations

from engine.core.error_taxonomy import log_swallowed_exception
from typing import Any

from engine.core.rng import det_roll_1_100
from engine.systems.hacking import _cash_apply, _has_any_tool, _inv_tokens, ensure_hacking_heat


def _has_hack_equipment(state: dict[str, Any]) -> bool:
    inv = state.get("inventory", {}) or {}
    if not isinstance(inv, dict):
        return False
    # Minimal compute/hacking capability.
    return _has_any_tool(inv, ("laptop", "laptop_basic", "cyberdeck", "deck", "terminal"))


def deterministic_hack_roll_1_100(state: dict[str, Any], *, target_type: str) -> int:
    """Deterministic roll for the targeted `HACK <target>` command (tests may import this)."""
    meta = state.get("meta", {}) or {}
    seed = str(meta.get("world_seed", "") or meta.get("seed_pack", "") or "").strip() or "seed"
    day = int(meta.get("day", 1) or 1)
    turn = int(meta.get("turn", 0) or 0)
    loc = str((state.get("player", {}) or {}).get("location", "") or "").strip().lower()
    who = str((state.get("player", {}) or {}).get("name", "__player__") or "__player__")
    return int(det_roll_1_100(seed, day, turn, loc, who, "HACK", str(target_type or ""), "targeted_hack_v1"))


def _hacking_level(state: dict[str, Any]) -> int:
    skills = state.get("skills", {}) or {}
    if not isinstance(skills, dict):
        return 1
    row = skills.get("hacking")
    if not isinstance(row, dict):
        return 1
    try:
        return max(1, int(row.get("level", 1) or 1))
    except Exception as _omni_sw_37:
        log_swallowed_exception('engine/systems/targeted_hacking.py:37', _omni_sw_37)
        return 1


def execute_hack(state: dict[str, Any], target_type: str) -> dict[str, Any]:
    """Targeted hacking action: validates equipment, resolves success, applies rewards and trace risk."""
    tgt = str(target_type or "").strip().lower()
    if tgt not in ("atm", "corp_server", "police_archive"):
        return {"ok": False, "reason": "invalid_target"}
    meta = state.setdefault("meta", {})
    if not isinstance(meta, dict):
        meta = {}
        state["meta"] = meta
    try:
        hacks_before = int(meta.get("daily_hacks_attempted", 0) or 0)
    except Exception as _omni_sw_52:
        log_swallowed_exception('engine/systems/targeted_hacking.py:52', _omni_sw_52)
        hacks_before = 0
    # Each prior attempt increases effective failure pressure by 10%.
    fatigue_penalty = max(0, int(hacks_before) * 10)
    if not _has_hack_equipment(state):
        meta["daily_hacks_attempted"] = int(hacks_before + 1)
        state.setdefault("world_notes", []).append(f"[Cyber] Missing equipment for hacking {tgt}.")
        return {"ok": False, "reason": "missing_equipment"}

    lvl = _hacking_level(state)
    diff = 3 if tgt == "atm" else 6 if tgt == "corp_server" else 9
    chance = 35 + (lvl - 1) * 7 - diff * 4 - fatigue_penalty
    chance = max(5, min(90, int(chance)))
    roll = deterministic_hack_roll_1_100(state, target_type=tgt)
    success = int(roll) <= int(chance)
    meta["daily_hacks_attempted"] = int(hacks_before + 1)

    econ = state.setdefault("economy", {})
    tr = state.setdefault("trace", {})
    world = state.setdefault("world", {})
    if not isinstance(world, dict):
        world = {}
        state["world"] = world
    fh = world.setdefault("faction_heat", {})
    if not isinstance(fh, dict):
        fh = {}
        world["faction_heat"] = fh
    fh.setdefault("corporate", 0)
    fh.setdefault("police", 0)
    try:
        tp = int(tr.get("trace_pct", 0) or 0)
    except Exception as _omni_sw_83:
        log_swallowed_exception('engine/systems/targeted_hacking.py:83', _omni_sw_83)
        tp = 0

    # Heat map keys (loc|corporate/police/black_market) serve as "cyber heat".
    try:
        hh = ensure_hacking_heat(state)
        loc = str((state.get("player", {}) or {}).get("location", "") or "").strip().lower()
        key = f"{loc}|{'corporate' if tgt == 'corp_server' else 'police' if tgt == 'police_archive' else 'black_market'}".strip("|")
        row = hh.setdefault(key, {"heat": 0, "noise": 0, "signal": 0})
        if isinstance(row, dict):
            row["heat"] = int(min(100, int(row.get("heat", 0) or 0) + (10 if tgt == "corp_server" else 14 if tgt == "police_archive" else 6)))
            row["noise"] = int(min(100, int(row.get("noise", 0) or 0) + (12 if tgt != "atm" else 6)))
            row["signal"] = int(min(100, int(row.get("signal", 0) or 0) + (8 if tgt != "atm" else 4)))
            hh[key] = row
    except Exception as _omni_sw_97:
        log_swallowed_exception('engine/systems/targeted_hacking.py:97', _omni_sw_97)
    if success:
        payout = 0
        if tgt == "atm":
            payout = 250 + (lvl * 40)
            _cash_apply(econ, payout)
        elif tgt == "corp_server":
            payout = 900 + (lvl * 120)
            _cash_apply(econ, payout)
            try:
                fh["corporate"] = int(fh.get("corporate", 0) or 0) + 20
            except Exception as _omni_sw_110:
                log_swallowed_exception('engine/systems/targeted_hacking.py:110', _omni_sw_110)
                fh["corporate"] = 20
            state.setdefault("world_notes", []).append("[Cyber] Corporate trace detected. Corporate heat increased.")
        else:
            tr["trace_pct"] = max(0, min(100, tp - 15))
        state.setdefault("world_notes", []).append(f"[Cyber] Successfully breached {tgt}.")
        return {
            "ok": True,
            "success": True,
            "target_type": tgt,
            "roll": int(roll),
            "chance": int(chance),
            "payout_cash": int(payout),
            "daily_hacks_attempted": int(meta.get("daily_hacks_attempted", 0) or 0),
        }

    tr["trace_pct"] = max(0, min(100, tp + 15))
    if tgt == "police_archive":
        try:
            fh["police"] = int(fh.get("police", 0) or 0) + 20
        except Exception as _omni_sw_130:
            log_swallowed_exception('engine/systems/targeted_hacking.py:130', _omni_sw_130)
            fh["police"] = 20
    state.setdefault("world_notes", []).append(f"[Cyber] Intrusion detected at {tgt}. Connection traced!")
    return {
        "ok": True,
        "success": False,
        "target_type": tgt,
        "roll": int(roll),
        "chance": int(chance),
        "payout_cash": 0,
        "daily_hacks_attempted": int(meta.get("daily_hacks_attempted", 0) or 0),
    }

