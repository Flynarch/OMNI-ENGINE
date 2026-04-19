from __future__ import annotations

from engine.core.error_taxonomy import log_swallowed_exception
from typing import Any


def _label(level: int) -> str:
    if level >= 80:
        return "high"
    if level >= 45:
        return "med"
    if level >= 15:
        return "low"
    return "none"


def _get_bucket(state: dict[str, Any], root_key: str) -> dict[str, Any]:
    p = state.get("player", {}) or {}
    loc = str(p.get("location", "") or "").strip().lower()
    world = state.get("world", {}) or {}
    root = world.get(root_key, {}) if isinstance(world, dict) else {}
    if not (isinstance(root, dict) and loc):
        return {}
    loc_map = root.get(loc) if isinstance(root.get(loc), dict) else None
    if not isinstance(loc_map, dict):
        return {}
    row = loc_map.get("__all__") if isinstance(loc_map.get("__all__"), dict) else None
    return row if isinstance(row, dict) else {}


def get_heat_brief(state: dict[str, Any]) -> dict[str, Any]:
    row = _get_bucket(state, "heat_map")
    try:
        lv = int(row.get("level", 0) or 0)
    except Exception as _omni_sw_34:
        log_swallowed_exception('engine/social/suspicion_ui.py:34', _omni_sw_34)
        lv = 0
    try:
        until = int(row.get("until_day", 0) or 0)
    except Exception as _omni_sw_38:
        log_swallowed_exception('engine/social/suspicion_ui.py:38', _omni_sw_38)
        until = 0
    rs = row.get("reasons", [])
    if not isinstance(rs, list):
        rs = []
    reasons = [str(x) for x in rs[:4] if isinstance(x, str) and x.strip()]
    return {"label": _label(lv), "reasons": reasons, "until_day": int(until), "level": int(lv)}


def get_suspicion_brief(state: dict[str, Any]) -> dict[str, Any]:
    row = _get_bucket(state, "suspicion")
    try:
        lv = int(row.get("level", 0) or 0)
    except Exception as _omni_sw_51:
        log_swallowed_exception('engine/social/suspicion_ui.py:51', _omni_sw_51)
        lv = 0
    try:
        until = int(row.get("until_day", 0) or 0)
    except Exception as _omni_sw_55:
        log_swallowed_exception('engine/social/suspicion_ui.py:55', _omni_sw_55)
        until = 0
    rs = row.get("reasons", [])
    if not isinstance(rs, list):
        rs = []
    reasons = [str(x) for x in rs[:4] if isinstance(x, str) and x.strip()]
    return {"label": _label(lv), "reasons": reasons, "until_day": int(until), "level": int(lv)}

