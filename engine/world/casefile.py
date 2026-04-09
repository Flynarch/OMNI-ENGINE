from __future__ import annotations

from typing import Any


def append_casefile(state: dict[str, Any], entry: dict[str, Any]) -> None:
    """Append a bounded casefile entry under world.casefile for audit/replay."""
    if not isinstance(entry, dict) or not entry:
        return
    world = state.setdefault("world", {})
    if not isinstance(world, dict):
        return
    cf = world.setdefault("casefile", [])
    if not isinstance(cf, list):
        cf = []
        world["casefile"] = cf

    meta = state.get("meta", {}) or {}
    try:
        day = int(meta.get("day", 1) or 1)
    except Exception:
        day = 1
    try:
        tmin = int(meta.get("time_min", 0) or 0)
    except Exception:
        tmin = 0

    # Normalize keys and keep entries small/stable.
    row = {
        "day": int(entry.get("day", day) or day),
        "time_min": int(entry.get("time_min", tmin) or tmin),
        "kind": str(entry.get("kind", "") or "").strip(),
        "scene_type": str(entry.get("scene_type", "") or "").strip(),
        "event_type": str(entry.get("event_type", "") or "").strip(),
        "location": str(entry.get("location", "") or "").strip().lower(),
        "district": str(entry.get("district", "") or "").strip().lower(),
        "summary": str(entry.get("summary", "") or "").strip()[:220],
        "tags": list(entry.get("tags", []) or [])[:12],
        "meta": entry.get("meta") if isinstance(entry.get("meta"), dict) else {},
    }

    cf.append(row)
    world["casefile"] = cf[-80:]


def summarize_casefile(state: dict[str, Any], n: int = 6) -> list[dict[str, Any]]:
    """Return last n casefile entries (for UI/debugging)."""
    world = state.get("world", {}) or {}
    cf = (world.get("casefile", []) or []) if isinstance(world, dict) else []
    if not isinstance(cf, list) or not cf:
        return []
    try:
        nn = int(n or 6)
    except Exception:
        nn = 6
    nn = max(0, min(20, nn))
    out: list[dict[str, Any]] = []
    for it in cf[-nn:]:
        if isinstance(it, dict):
            out.append(it)
    return out

