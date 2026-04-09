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


def ensure_informants(state: dict[str, Any]) -> dict[str, Any]:
    """Ensure world.informants exists; caller can override entries in tests."""
    world = state.setdefault("world", {})
    inf = world.get("informants")
    if not isinstance(inf, dict):
        inf = {}
        world["informants"] = inf
    return inf


def seed_informant_roster(state: dict[str, Any], *, loc: str = "", district: str = "") -> dict[str, Any]:
    """Ensure a small informant roster exists for a location.

    This is intentionally lightweight: picks from existing NPCs (if any),
    otherwise keeps roster empty. Tests or content packs can seed NPCs.
    """
    loc0 = _norm(loc) or _norm((state.get("player", {}) or {}).get("location", ""))
    did0 = _norm(district) or _norm((state.get("player", {}) or {}).get("district", ""))
    world = state.setdefault("world", {})
    roster = world.get("informant_roster")
    if not isinstance(roster, dict):
        roster = {}
        world["informant_roster"] = roster

    if not loc0:
        return {"ok": False, "reason": "no_location"}

    key = loc0 + ("|" + did0 if did0 else "")
    if key in roster and isinstance(roster.get(key), dict):
        return {"ok": True, "key": key, "count": len((roster.get(key) or {}).get("names", []) or [])}

    npcs = state.get("npcs", {}) or {}
    names: list[str] = []
    if isinstance(npcs, dict):
        # Prefer NPCs whose home/current location matches player loc.
        for nm, row in list(npcs.items())[:250]:
            if not isinstance(nm, str) or not isinstance(row, dict):
                continue
            hl = _norm(row.get("home_location", ""))
            cl = _norm(row.get("current_location", ""))
            if loc0 and (hl == loc0 or cl == loc0):
                names.append(nm)
        if not names:
            names = [str(n) for n in list(npcs.keys())[:80] if isinstance(n, str)]

    # Deterministically pick up to 6 candidates and create default profiles.
    meta = state.get("meta", {}) or {}
    day = int(meta.get("day", 1) or 1)
    turn = int(meta.get("turn", 0) or 0)
    picked: list[str] = []
    if names:
        uniq = sorted(set([str(n) for n in names if str(n).strip()]))
        for i in range(min(6, len(uniq))):
            idx = (_det_roll_1_100(day, turn, "seed_inf", loc0, did0, i) - 1) % len(uniq)
            cand = uniq[idx]
            if cand not in picked:
                picked.append(cand)

    inf = ensure_informants(state)
    for nm in picked:
        if nm not in inf:
            npc = (npcs.get(nm) if isinstance(npcs, dict) else None) or {}
            npc = npc if isinstance(npc, dict) else {}
            inf[nm] = _default_profile_from_npc(npc)

    roster[key] = {"location": loc0, "district": did0, "names": picked}
    world["informant_roster"] = roster
    world["informants"] = inf
    return {"ok": True, "key": key, "count": len(picked), "names": list(picked)}


def _affiliation_for_npc(npc: dict[str, Any]) -> str:
    role = _norm(npc.get("role", ""))
    if any(x in role for x in ("police", "cop", "detective", "officer")):
        return "police"
    if any(x in role for x in ("corp", "security", "sec", "agent")):
        return "corporate"
    return "civilian"


def _default_profile_from_npc(npc: dict[str, Any]) -> dict[str, Any]:
    # Keep defaults conservative; tests can override with reliability=100.
    return {
        "affiliation": _affiliation_for_npc(npc),
        "reliability": 50,
        "greed": 40,
        "last_tip_turn": -999,
    }


def _tip_suspicion(category: str, *, hop: int, trust: int) -> int:
    cat = _norm(category)
    base = 50
    if cat in ("hack", "stealth", "combat"):
        base += 8
    if cat in ("wealth", "social"):
        base += 2
    base += 3 * max(0, int(hop))
    base += int((50 - int(trust)) / 5)  # low trust increases
    return _clamp(base, 0, 100)


def maybe_queue_informant_tip(
    state: dict[str, Any],
    *,
    from_npc: str,
    to_npc: str,
    rumor: str,
    category: str,
    hop: int,
) -> dict[str, Any]:
    """Deterministically decide if the recipient NPC files a tip."""
    inf = ensure_informants(state)
    npcs = state.get("npcs", {}) or {}
    npc = npcs.get(to_npc) if isinstance(npcs, dict) else None
    npc = npc if isinstance(npc, dict) else {}

    prof = inf.get(to_npc)
    if not isinstance(prof, dict):
        prof = _default_profile_from_npc(npc)
        inf[to_npc] = dict(prof)

    meta = state.get("meta", {}) or {}
    day = int(meta.get("day", 1) or 1)
    time_min = int(meta.get("time_min", 0) or 0)
    turn = int(meta.get("turn", 0) or 0)

    # Cooldown: don't tip every hop.
    try:
        last_tip = int(prof.get("last_tip_turn", -999) or -999)
    except Exception:
        last_tip = -999
    if turn - last_tip < 3:
        return {"queued": False, "reason": "cooldown"}

    try:
        reliability = int(prof.get("reliability", 50) or 50)
    except Exception:
        reliability = 50
    reliability = _clamp(reliability, 0, 100)

    mem = ((state.get("world", {}) or {}).get("social_memory", {}) or {}) if isinstance((state.get("world", {}) or {}).get("social_memory", {}), dict) else {}
    trust = 50
    try:
        if isinstance(mem.get(to_npc), dict):
            trust = int((mem.get(to_npc) or {}).get("trust_in_player", 50) or 50)
    except Exception:
        trust = 50
    trust = _clamp(trust, 0, 100)

    chance = _clamp(int(reliability * 0.7 + (50 - trust) * 0.6 + max(0, int(hop)) * 6), 0, 95)
    r = _det_roll_1_100(day, turn, time_min, "informant_tip", to_npc, from_npc, category, hop, rumor[:40])
    if r > chance:
        return {"queued": False, "reason": "no_tip", "roll": r, "chance": chance}

    loc = _norm((state.get("player", {}) or {}).get("location", ""))
    did = _norm((state.get("player", {}) or {}).get("district", ""))
    aff = _norm(prof.get("affiliation", "")) or _affiliation_for_npc(npc)
    sus = _tip_suspicion(category, hop=int(hop), trust=int(trust))

    payload = {
        "reporter": str(to_npc),
        "affiliation": aff,
        "suspicion": int(sus),
        "origin_location": loc,
        "district": did,
        "meta": {"from_npc": str(from_npc), "to_npc": str(to_npc), "category": str(category), "hop": int(hop), "rumor": str(rumor)[:160]},
    }
    pe = state.setdefault("pending_events", [])
    if isinstance(pe, list):
        pe.append(
            {
                "event_type": "informant_tip",
                "title": "Informant Tip",
                "due_day": int(day),
                "due_time": min(1439, int(time_min) + 2),
                "triggered": False,
                "payload": payload,
            }
        )
    prof["last_tip_turn"] = int(turn)
    inf[to_npc] = dict(prof)
    return {"queued": True, "reporter": to_npc, "affiliation": aff, "suspicion": sus}

