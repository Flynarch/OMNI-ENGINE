"""W2-1: macro faction report — deterministic aggregates (power/stability, 3d delta, heat, ripples)."""
from __future__ import annotations

from engine.core.error_taxonomy import log_swallowed_exception
from typing import Any

# Canonical display order; unknown faction keys sort after these.
_KNOWN_ORDER = ("corporate", "police", "black_market")


def _clamp_int(v: Any, lo: int, hi: int) -> int:
    try:
        return max(lo, min(hi, int(v)))
    except Exception as _omni_sw_13:
        log_swallowed_exception('engine/world/faction_report.py:13', _omni_sw_13)
        return (lo + hi) // 2


def _faction_ids(world: dict[str, Any]) -> list[str]:
    fac = world.get("factions", {}) or {}
    if not isinstance(fac, dict):
        return list(_KNOWN_ORDER)
    keys = [str(k) for k in fac.keys() if isinstance(k, str)]
    known = [k for k in _KNOWN_ORDER if k in keys]
    rest = sorted(k for k in keys if k not in _KNOWN_ORDER)
    return known + rest


def ensure_factions_shape(state: dict[str, Any]) -> dict[str, Any]:
    """Normalize world.factions rows; safe on partial/missing data."""
    world = state.setdefault("world", {})
    if not isinstance(world, dict):
        world = {}
        state["world"] = world
    factions = world.setdefault("factions", {})
    if not isinstance(factions, dict):
        factions = {}
        world["factions"] = factions
    for fid in _KNOWN_ORDER:
        row = factions.get(fid)
        if not isinstance(row, dict):
            row = {}
            factions[fid] = row
        row["power"] = _clamp_int(row.get("power", 50), 0, 100)
        row["stability"] = _clamp_int(row.get("stability", 50), 0, 100)
    for fname, row in list(factions.items()):
        if not isinstance(fname, str) or not isinstance(row, dict):
            continue
        if fname in _KNOWN_ORDER:
            continue
        row["power"] = _clamp_int(row.get("power", 50), 0, 100)
        row["stability"] = _clamp_int(row.get("stability", 50), 0, 100)
        factions[fname] = row
    return factions


def _snapshot_factions(world: dict[str, Any]) -> dict[str, dict[str, int]]:
    fac = world.get("factions", {}) or {}
    if not isinstance(fac, dict):
        return {}
    out: dict[str, dict[str, int]] = {}
    for fid in _faction_ids(world):
        row = fac.get(fid)
        if not isinstance(row, dict):
            out[fid] = {"power": 50, "stability": 50}
            continue
        out[fid] = {
            "power": _clamp_int(row.get("power", 50), 0, 100),
            "stability": _clamp_int(row.get("stability", 50), 0, 100),
        }
    return out


def maybe_record_faction_daily_snapshot(state: dict[str, Any]) -> None:
    """Append one snapshot per calendar day (first world_tick of that day)."""
    meta = state.get("meta", {}) or {}
    try:
        day = int(meta.get("day", 1) or 1)
    except Exception as _omni_sw_77:
        log_swallowed_exception('engine/world/faction_report.py:77', _omni_sw_77)
        day = 1
    world = state.setdefault("world", {})
    if not isinstance(world, dict):
        return
    ensure_factions_shape(state)
    try:
        last = int(world.get("faction_macro_history_last_day", 0) or 0)
    except Exception as _omni_sw_85:
        log_swallowed_exception('engine/world/faction_report.py:85', _omni_sw_85)
        last = 0
    if day == last:
        return
    world["faction_macro_history_last_day"] = int(day)
    hist = world.setdefault("faction_macro_history", [])
    if not isinstance(hist, list):
        hist = []
        world["faction_macro_history"] = hist
    snap = _snapshot_factions(world)
    hist.append({"day": int(day), "factions": snap})
    while len(hist) > 10:
        hist.pop(0)


def _ref_snapshot_for_delta(state: dict[str, Any], *, cur_day: int, lookback: int = 3) -> dict[str, dict[str, int]] | None:
    world = state.get("world", {}) or {}
    if not isinstance(world, dict):
        return None
    hist = world.get("faction_macro_history", [])
    if not isinstance(hist, list) or not hist:
        return None
    target_day = int(cur_day) - int(lookback)
    best: dict[str, Any] | None = None
    best_d = -1
    for h in hist:
        if not isinstance(h, dict):
            continue
        try:
            d = int(h.get("day", 0) or 0)
        except Exception as _omni_sw_115:
            log_swallowed_exception('engine/world/faction_report.py:115', _omni_sw_115)
            continue
        if d <= target_day and d > best_d:
            fac = h.get("factions")
            if isinstance(fac, dict):
                best = fac
                best_d = d
    if not best or not isinstance(best, dict):
        return None
    out: dict[str, dict[str, int]] = {}
    for fid, row in best.items():
        if not isinstance(fid, str) or not isinstance(row, dict):
            continue
        out[fid] = {
            "power": _clamp_int(row.get("power", 50), 0, 100),
            "stability": _clamp_int(row.get("stability", 50), 0, 100),
        }
    return out or None


def _max_heat_at_location(state: dict[str, Any], loc: str) -> int:
    lk = str(loc or "").strip().lower()
    if not lk:
        return 0
    world = state.get("world", {}) or {}
    if not isinstance(world, dict):
        return 0
    hm = world.get("heat_map", {})
    if not isinstance(hm, dict):
        return 0
    loc_map = hm.get(lk)
    if not isinstance(loc_map, dict):
        return 0
    best = 0
    for _sk, row in loc_map.items():
        if not isinstance(row, dict):
            continue
        try:
            best = max(best, int(row.get("level", 0) or 0))
        except Exception as _omni_sw_154:
            log_swallowed_exception('engine/world/faction_report.py:154', _omni_sw_154)
            continue
    return max(0, min(100, best))


def append_faction_ripple_impact(state: dict[str, Any], rp: dict[str, Any], deltas: dict[str, dict[str, int]]) -> None:
    """Bounded log of ripple-originated faction stat changes (for macro report)."""
    if not isinstance(rp, dict) or not deltas:
        return
    world = state.setdefault("world", {})
    if not isinstance(world, dict):
        return
    meta = state.get("meta", {}) or {}
    try:
        day = int(meta.get("day", 1) or 1)
    except Exception as _omni_sw_169:
        log_swallowed_exception('engine/world/faction_report.py:169', _omni_sw_169)
        day = 1
    log = world.setdefault("faction_impact_log", [])
    if not isinstance(log, list):
        log = []
        world["faction_impact_log"] = log
    entry = {
        "day": day,
        "kind": str(rp.get("kind", "") or "")[:64],
        "text": str(rp.get("text", "") or "")[:160],
        "origin_location": str(rp.get("origin_location", "") or "").strip().lower()[:80],
        "origin_faction": str(rp.get("origin_faction", "") or "").strip().lower()[:32],
        "deltas": {k: dict(v) for k, v in deltas.items() if isinstance(k, str) and isinstance(v, dict)},
    }
    log.append(entry)
    while len(log) > 80:
        log.pop(0)


def build_faction_macro_report(state: dict[str, Any], *, full: bool = False) -> dict[str, Any]:
    """Structured report for UI/tests; deterministic given state."""
    ensure_factions_shape(state)
    world = state.setdefault("world", {})
    if not isinstance(world, dict):
        world = {}
        state["world"] = world
    meta = state.get("meta", {}) or {}
    try:
        cur_day = int(meta.get("day", 1) or 1)
    except Exception as _omni_sw_198:
        log_swallowed_exception('engine/world/faction_report.py:198', _omni_sw_198)
        cur_day = 1

    statuses = world.get("faction_statuses", {}) or {}
    if not isinstance(statuses, dict):
        statuses = {}

    ref = _ref_snapshot_for_delta(state, cur_day=cur_day, lookback=3)
    now_snap = _snapshot_factions(world)

    factions_out: list[dict[str, Any]] = []
    for fid in _faction_ids(world):
        row = now_snap.get(fid, {"power": 50, "stability": 50})
        st = str(statuses.get(fid, "idle") or "idle")
        d_pw = None
        d_st = None
        if ref and fid in ref:
            d_pw = int(row["power"]) - int(ref[fid]["power"])
            d_st = int(row["stability"]) - int(ref[fid]["stability"])
        factions_out.append(
            {
                "id": fid,
                "power": int(row["power"]),
                "stability": int(row["stability"]),
                "attention": st,
                "delta3d_power": d_pw,
                "delta3d_stability": d_st,
            }
        )

    log = world.get("faction_impact_log", [])
    if not isinstance(log, list):
        log = []

    min_day = cur_day - 3
    recent = [e for e in log if isinstance(e, dict) and int(e.get("day", 0) or 0) >= min_day]

    def _heat_for_faction(fid: str) -> tuple[int, str]:
        candidates: list[tuple[int, str]] = []
        for e in recent:
            origin = str(e.get("origin_location", "") or "").strip().lower()
            if not origin:
                continue
            of = str(e.get("origin_faction", "") or "").strip().lower()
            deltas = e.get("deltas") if isinstance(e.get("deltas"), dict) else {}
            touched = isinstance(deltas, dict) and fid in deltas
            if touched or of == fid:
                h = _max_heat_at_location(state, origin)
                candidates.append((h, origin))
        if not candidates:
            return (0, "")
        candidates.sort(key=lambda x: (-x[0], x[1]))
        return candidates[0]

    hot_spots: dict[str, dict[str, Any]] = {}
    for frow in factions_out:
        fid = str(frow["id"])
        hv, loc = _heat_for_faction(fid)
        hot_spots[fid] = {"location": loc, "heat": hv}

    def _top_causes(fid: str, limit: int) -> list[dict[str, Any]]:
        scored: list[tuple[int, int, str, dict[str, Any]]] = []
        seen_text: set[str] = set()
        for e in recent:
            if not isinstance(e, dict):
                continue
            deltas = e.get("deltas") if isinstance(e.get("deltas"), dict) else {}
            if not isinstance(deltas, dict) or fid not in deltas:
                continue
            d0 = deltas.get(fid)
            if not isinstance(d0, dict):
                continue
            mag = 0
            for _k, dv in d0.items():
                try:
                    mag += abs(int(dv))
                except Exception as _omni_sw_274:
                    log_swallowed_exception('engine/world/faction_report.py:274', _omni_sw_274)
                    continue
            txt = str(e.get("text", "") or "")
            sig = f"{e.get('kind','')}|{txt[:48]}"
            if sig in seen_text:
                continue
            seen_text.add(sig)
            try:
                ed = int(e.get("day", 0) or 0)
            except Exception as _omni_sw_283:
                log_swallowed_exception('engine/world/faction_report.py:283', _omni_sw_283)
                ed = 0
            scored.append((ed, mag, txt, e))
        scored.sort(key=lambda x: (-x[0], -x[1], x[2]))
        out: list[dict[str, Any]] = []
        for _ed, _mg, _tx, e in scored[:limit]:
            out.append(
                {
                    "day": int(e.get("day", 0) or 0),
                    "kind": str(e.get("kind", "") or ""),
                    "text": str(e.get("text", "") or "")[:200],
                }
            )
        return out

    top_by_faction: dict[str, list[dict[str, Any]]] = {}
    for frow in factions_out:
        fid = str(frow["id"])
        top_by_faction[fid] = _top_causes(fid, 3 if full else 3)

    compact = {
        "day": cur_day,
        "factions": [
            {
                "id": f["id"],
                "power": f["power"],
                "stability": f["stability"],
                "attention": f["attention"],
                "d_pw": f["delta3d_power"],
                "d_st": f["delta3d_stability"],
            }
            for f in factions_out
        ],
        "hot": {k: {"loc": v["location"], "heat": v["heat"]} for k, v in hot_spots.items()},
    }
    if full:
        return {
            **compact,
            "ref_ok": ref is not None,
            "top_causes": top_by_faction,
        }
    return compact


def faction_report_fingerprint(state: dict[str, Any], *, full: bool = False) -> str:
    """Stable string for verify.py (sorted JSON)."""
    import json

    pkg = build_faction_macro_report(state, full=full)
    return json.dumps(pkg, sort_keys=True, separators=(",", ":"))
