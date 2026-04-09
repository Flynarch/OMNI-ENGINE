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


def _get_cash(state: dict[str, Any]) -> int:
    eco = state.get("economy", {}) if isinstance(state.get("economy"), dict) else {}
    try:
        return int(eco.get("cash", 0) or 0)
    except Exception:
        return 0


def _set_cash(state: dict[str, Any], v: int) -> None:
    eco = state.get("economy", {}) if isinstance(state.get("economy"), dict) else {}
    eco["cash"] = int(v)
    state["economy"] = eco


def _profile(state: dict[str, Any], npc_name: str) -> dict[str, Any] | None:
    world = state.get("world", {}) or {}
    inf = world.get("informants")
    if not isinstance(inf, dict):
        return None
    row = inf.get(npc_name)
    return row if isinstance(row, dict) else None


def pay_informant(state: dict[str, Any], npc_name: str, amount: int) -> dict[str, Any]:
    nm = str(npc_name)
    amt = int(amount or 0)
    if amt <= 0:
        return {"ok": False, "reason": "invalid_amount"}
    prof = _profile(state, nm)
    if not isinstance(prof, dict):
        return {"ok": False, "reason": "not_informant"}
    cash = _get_cash(state)
    if cash < amt:
        return {"ok": False, "reason": "insufficient_cash", "need": amt, "cash": cash}
    _set_cash(state, cash - amt)
    try:
        rel = int(prof.get("reliability", 50) or 50)
    except Exception:
        rel = 50
    rel2 = _clamp(rel + max(1, amt // 250), 0, 100)
    prof["reliability"] = rel2
    # Paying reduces immediate chance of backlash slightly (modeled via greed).
    try:
        greed = int(prof.get("greed", 40) or 40)
    except Exception:
        greed = 40
    prof["greed"] = _clamp(greed + 1, 0, 100)
    state.setdefault("world", {}).setdefault("informants", {})[nm] = dict(prof)
    return {"ok": True, "cash_delta": -amt, "reliability_before": rel, "reliability_after": rel2}


def burn_informant(state: dict[str, Any], npc_name: str) -> dict[str, Any]:
    nm = str(npc_name)
    world = state.setdefault("world", {})
    inf = world.get("informants")
    if not isinstance(inf, dict) or nm not in inf:
        return {"ok": False, "reason": "not_informant"}

    meta = state.get("meta", {}) or {}
    day = int(meta.get("day", 1) or 1)
    turn = int(meta.get("turn", 0) or 0)
    time_min = int(meta.get("time_min", 0) or 0)

    prof = inf.get(nm) if isinstance(inf.get(nm), dict) else {}
    aff = _norm((prof or {}).get("affiliation", "")) or "civilian"
    try:
        rel = int((prof or {}).get("reliability", 50) or 50)
    except Exception:
        rel = 50

    # Deterministic backlash chance: high reliability informants can retaliate when burned.
    backlash_chance = _clamp(int(rel * 0.6 + (30 if aff in ("police", "corporate") else 15)), 0, 90)
    r = _det_roll_1_100(day, turn, time_min, "burn", nm, aff, rel)

    # Remove from informants and roster.
    del inf[nm]
    world["informants"] = inf
    roster = world.get("informant_roster")
    if isinstance(roster, dict):
        for k, row in list(roster.items())[:200]:
            if not isinstance(row, dict):
                continue
            names = row.get("names")
            if isinstance(names, list) and nm in names:
                row["names"] = [x for x in names if x != nm]
                roster[k] = row
        world["informant_roster"] = roster

    scheduled = False
    if r <= backlash_chance:
        loc = _norm((state.get("player", {}) or {}).get("location", ""))
        pe = state.setdefault("pending_events", [])
        if isinstance(pe, list):
            pe.append(
                {
                    "event_type": "npc_report",
                    "title": "NPC Report",
                    "due_day": int(day),
                    "due_time": min(1439, int(time_min) + 5),
                    "triggered": False,
                    "payload": {"reporter": nm, "affiliation": aff, "suspicion": 70, "origin_location": loc, "meta": {"source": "burn_informant"}},
                }
            )
            scheduled = True

    return {"ok": True, "backlash_roll": r, "backlash_chance": backlash_chance, "backlash_scheduled": scheduled}

