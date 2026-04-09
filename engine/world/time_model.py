from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class TechEpoch:
    name: str
    translator_level: str  # none|basic|good|advanced
    translator_quality: int  # 0..100 baseline


def sim_year_from_state(state: dict[str, Any]) -> int:
    """Compute simulation year from player.year and meta.day.

    Year advances every 365 sim-days.
    """
    p = state.get("player", {}) or {}
    meta = state.get("meta", {}) or {}
    try:
        start_year = int(p.get("year", 2025) or 2025)
    except Exception:
        start_year = 2025
    try:
        day = int(meta.get("day", 1) or 1)
    except Exception:
        day = 1
    return int(start_year + max(0, (day - 1)) // 365)


def tech_epoch_for_year(year: int, tech_progress: float = 0.0) -> TechEpoch:
    """Real-world leaning translator tech availability."""
    try:
        y = int(year)
    except Exception:
        y = 2025
    try:
        tp = float(tech_progress or 0.0)
    except Exception:
        tp = 0.0
    # tech_progress shifts effective year slightly (player/world influence hook).
    eff = int(round(y + max(-30.0, min(30.0, tp)) * 0.5))

    if eff <= 1999:
        return TechEpoch(name="pre_digital", translator_level="none", translator_quality=0)
    if eff <= 2009:
        return TechEpoch(name="early_web", translator_level="basic", translator_quality=25)
    if eff <= 2016:
        return TechEpoch(name="smartphone_era", translator_level="basic", translator_quality=38)
    if eff <= 2022:
        return TechEpoch(name="neural_mt", translator_level="good", translator_quality=60)
    if eff <= 2028:
        return TechEpoch(name="assistants", translator_level="good", translator_quality=72)
    return TechEpoch(name="near_future", translator_level="advanced", translator_quality=85)


def cache_sim_time(state: dict[str, Any]) -> dict[str, Any]:
    """Cache sim year and epoch fields in meta for UI/debug."""
    meta = state.setdefault("meta", {})
    world = state.setdefault("world", {})
    try:
        tech_progress = float((world.get("tech_progress", 0.0) if isinstance(world, dict) else 0.0) or 0.0)
    except Exception:
        tech_progress = 0.0

    y = sim_year_from_state(state)
    ep = tech_epoch_for_year(y, tech_progress=tech_progress)
    meta["sim_year"] = int(y)
    meta["tech_epoch"] = {"name": ep.name, "translator_level": ep.translator_level, "translator_quality": ep.translator_quality}
    return meta

