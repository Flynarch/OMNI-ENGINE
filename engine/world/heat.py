from __future__ import annotations

from typing import Any


def _loc_district(state: dict[str, Any], *, loc: str = "", district: str = "") -> tuple[str, str]:
    p = state.get("player", {}) or {}
    loc0 = str(loc or (p.get("location", "") or "")).strip().lower()
    did0 = str(district or (p.get("district", "") or "")).strip().lower()
    return (loc0, did0)


def _ensure_bucket(world: dict[str, Any], root_key: str, loc: str, scope_key: str) -> dict[str, Any]:
    root = world.setdefault(root_key, {})
    if not isinstance(root, dict):
        root = {}
        world[root_key] = root
    loc_map = root.setdefault(loc, {})
    if not isinstance(loc_map, dict):
        loc_map = {}
        root[loc] = loc_map
    row = loc_map.setdefault(scope_key, {"level": 0, "until_day": 0, "reasons": [], "last_update_day": 0})
    if not isinstance(row, dict):
        row = {"level": 0, "until_day": 0, "reasons": [], "last_update_day": 0}
        loc_map[scope_key] = row
    row.setdefault("level", 0)
    row.setdefault("until_day", 0)
    row.setdefault("reasons", [])
    row.setdefault("last_update_day", 0)
    return row


def bump_heat(
    state: dict[str, Any],
    *,
    loc: str = "",
    district: str = "",
    delta: int,
    reason: str,
    ttl_days: int = 5,
    scope: str = "__all__",
) -> dict[str, Any]:
    """Deterministically bump local heat (0..100) and extend TTL."""
    loc0, did0 = _loc_district(state, loc=loc, district=district)
    if not loc0:
        return {"ok": False, "reason": "no_location"}
    meta = state.get("meta", {}) or {}
    try:
        day = int(meta.get("day", 1) or 1)
    except Exception:
        day = 1
    try:
        ttl = int(ttl_days or 0)
    except Exception:
        ttl = 0
    ttl = max(0, min(30, ttl))

    world = state.setdefault("world", {})
    if not isinstance(world, dict):
        return {"ok": False, "reason": "invalid_world"}
    scope_key = str(scope or "__all__")
    if scope_key != "__all__" and did0:
        scope_key = did0
    row = _ensure_bucket(world, "heat_map", loc0, scope_key)
    try:
        lv0 = int(row.get("level", 0) or 0)
    except Exception:
        lv0 = 0
    lv1 = max(0, min(100, lv0 + int(delta)))
    row["level"] = int(lv1)
    row["last_update_day"] = int(day)
    row["until_day"] = max(int(row.get("until_day", 0) or 0), int(day) + ttl)
    rs = row.get("reasons", [])
    if not isinstance(rs, list):
        rs = []
    r = str(reason or "").strip()
    if r:
        if r in rs:
            rs.remove(r)
        rs.insert(0, r)
    row["reasons"] = rs[:8]
    return {"ok": True, "loc": loc0, "scope": scope_key, "before": lv0, "after": lv1}


def bump_suspicion(
    state: dict[str, Any],
    *,
    loc: str = "",
    district: str = "",
    delta: int,
    reason: str,
    ttl_days: int = 2,
    scope: str = "__all__",
) -> dict[str, Any]:
    """Deterministically bump local suspicion (0..100) and extend TTL."""
    loc0, did0 = _loc_district(state, loc=loc, district=district)
    if not loc0:
        return {"ok": False, "reason": "no_location"}
    meta = state.get("meta", {}) or {}
    try:
        day = int(meta.get("day", 1) or 1)
    except Exception:
        day = 1
    try:
        ttl = int(ttl_days or 0)
    except Exception:
        ttl = 0
    ttl = max(0, min(14, ttl))

    world = state.setdefault("world", {})
    if not isinstance(world, dict):
        return {"ok": False, "reason": "invalid_world"}
    scope_key = str(scope or "__all__")
    if scope_key != "__all__" and did0:
        scope_key = did0
    row = _ensure_bucket(world, "suspicion", loc0, scope_key)
    try:
        lv0 = int(row.get("level", 0) or 0)
    except Exception:
        lv0 = 0
    lv1 = max(0, min(100, lv0 + int(delta)))
    row["level"] = int(lv1)
    row["last_update_day"] = int(day)
    row["until_day"] = max(int(row.get("until_day", 0) or 0), int(day) + ttl)
    rs = row.get("reasons", [])
    if not isinstance(rs, list):
        rs = []
    r = str(reason or "").strip()
    if r:
        if r in rs:
            rs.remove(r)
        rs.insert(0, r)
    row["reasons"] = rs[:8]
    return {"ok": True, "loc": loc0, "scope": scope_key, "before": lv0, "after": lv1}


def decay_heat_and_suspicion(state: dict[str, Any], *, cur_day: int) -> None:
    """Daily decay for heat/suspicion (deterministic)."""
    world = state.get("world", {}) or {}
    if not isinstance(world, dict):
        return
    # ensure maps exist
    hm = world.get("heat_map", {}) if isinstance(world.get("heat_map"), dict) else {}
    sp = world.get("suspicion", {}) if isinstance(world.get("suspicion"), dict) else {}

    def _decay_map(m: dict[str, Any], *, decay_per_day: int) -> dict[str, Any]:
        out = m
        for loc, loc_map in list(m.items())[:200]:
            if not isinstance(loc_map, dict):
                continue
            for sk, row in list(loc_map.items())[:20]:
                if not isinstance(row, dict):
                    continue
                try:
                    until = int(row.get("until_day", 0) or 0)
                except Exception:
                    until = 0
                try:
                    lv = int(row.get("level", 0) or 0)
                except Exception:
                    lv = 0
                if until and cur_day > until:
                    row["level"] = 0
                    row["reasons"] = []
                else:
                    row["level"] = max(0, lv - decay_per_day)
                loc_map[sk] = row
            out[loc] = loc_map
        return out

    world["heat_map"] = _decay_map(hm, decay_per_day=2)
    world["suspicion"] = _decay_map(sp, decay_per_day=5)
    # Relationship relief: strong allies/close friends can cool local heat a bit.
    try:
        from engine.npc.relationship import get_top_relationships

        rels = get_top_relationships(state, limit=8)
        relief = 0
        for _nm, rel in rels:
            t = str(rel.get("type", "") or "").lower()
            if t in ("ally", "close_friend", "friend", "partner"):
                st = int(rel.get("strength", 50) or 50)
                relief = max(relief, max(1, min(4, st // 30)))
        if relief > 0:
            loc0 = str(((state.get("player", {}) or {}).get("location", "") or "")).strip().lower()
            did0 = str(((state.get("player", {}) or {}).get("district", "") or "")).strip().lower()
            hm2 = world.get("heat_map", {}) if isinstance(world.get("heat_map"), dict) else {}
            if isinstance(hm2, dict) and loc0 and isinstance(hm2.get(loc0), dict):
                loc_map = hm2.get(loc0) or {}
                for scope in ("__all__", did0):
                    if not scope:
                        continue
                    row = loc_map.get(scope)
                    if isinstance(row, dict):
                        try:
                            lv = int(row.get("level", 0) or 0)
                        except Exception:
                            lv = 0
                        row["level"] = max(0, lv - int(relief))
                        loc_map[scope] = row
                hm2[loc0] = loc_map
                world["heat_map"] = hm2
    except Exception:
        pass

