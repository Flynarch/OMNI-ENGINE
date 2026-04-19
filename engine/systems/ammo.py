"""Loose ammo stored in inventory.item_quantities (rounds per ammo item_id)."""

from __future__ import annotations

from engine.core.error_taxonomy import log_swallowed_exception
from typing import Any


def _clamp_int(v: Any, lo: int, hi: int, default: int) -> int:
    try:
        x = int(v)
    except Exception as _omni_sw_11:
        log_swallowed_exception('engine/systems/ammo.py:11', _omni_sw_11)
        return int(default)
    return max(lo, min(hi, x))


def item_row(state: dict[str, Any], item_id: str) -> dict[str, Any] | None:
    item_id = str(item_id or "").strip()
    if not item_id:
        return None
    idx = ((state.get("world", {}) or {}).get("content_index", {}) or {}) if isinstance(state, dict) else {}
    items = idx.get("items", {}) if isinstance(idx, dict) else {}
    row = items.get(item_id) if isinstance(items, dict) else None
    return row if isinstance(row, dict) else None


def item_is_ammo(state: dict[str, Any], item_id: str) -> bool:
    row = item_row(state, item_id)
    if not row:
        return False
    tags = row.get("tags", [])
    if not isinstance(tags, list):
        return False
    tags_l = [str(x).lower() for x in tags if isinstance(x, str)]
    return "ammo" in tags_l


def rounds_per_purchase(state: dict[str, Any], item_id: str) -> int:
    row = item_row(state, item_id)
    if not row:
        return 50
    return _clamp_int(row.get("rounds_per_box", 50), 1, 99999, 50)
