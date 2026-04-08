from __future__ import annotations

from typing import Any

from engine.rng import det_roll_1_100


def _norm(loc: str) -> str:
    return str(loc or "").strip().lower()


def ensure_weather(state: dict[str, Any], loc: str, day: int) -> dict[str, Any]:
    world = state.setdefault("world", {})
    locs = world.setdefault("locations", {})
    if not isinstance(locs, dict):
        locs = {}
        world["locations"] = locs
    k = _norm(loc)
    locs.setdefault(k, {})
    slot = locs.get(k)
    if not isinstance(slot, dict):
        slot = {}
        locs[k] = slot
    slot.setdefault("weather", {})
    w = slot.get("weather")
    if isinstance(w, dict) and int(w.get("day", 0) or 0) == int(day):
        return w

    meta = state.get("meta", {}) or {}
    seed = str(meta.get("world_seed", "") or meta.get("seed_pack", "") or "")
    roll = det_roll_1_100(seed, "weather", k, int(day))
    if roll <= 10:
        kind = "storm"
    elif roll <= 30:
        kind = "rain"
    elif roll <= 45:
        kind = "fog"
    elif roll <= 60:
        kind = "windy"
    else:
        kind = "clear"
    w2 = {"day": int(day), "kind": kind}
    slot["weather"] = w2
    locs[k] = slot
    world["locations"] = locs
    return w2


def travel_minutes_modifier(weather_kind: str) -> int:
    k = str(weather_kind or "").lower()
    if k == "storm":
        return 25
    if k == "rain":
        return 12
    if k == "fog":
        return 10
    if k == "windy":
        return 6
    return 0


def stealth_bonus(weather_kind: str) -> int:
    k = str(weather_kind or "").lower()
    if k in ("rain", "fog"):
        return +6
    if k == "storm":
        return +4
    return 0

