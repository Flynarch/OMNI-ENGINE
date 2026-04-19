"""Trace / heat pressure when acquiring contraband (shop or pickup)."""

from __future__ import annotations

from typing import Any

from engine.core.error_taxonomy import log_swallowed_exception
from engine.core.factions import sync_faction_statuses_from_trace
from engine.world.districts import get_district


def _item_tags(state: dict[str, Any], item_id: str) -> list[str]:
    idx = (state.get("world", {}) or {}).get("content_index", {}) or {}
    items = idx.get("items", {}) if isinstance(idx, dict) else {}
    row = items.get(item_id) if isinstance(items, dict) else None
    if not isinstance(row, dict):
        return []
    t = row.get("tags", [])
    if not isinstance(t, list):
        return []
    return [str(x).lower() for x in t if isinstance(x, str)]


def _is_contraband_for_heat(tags: list[str]) -> bool:
    if "illegal_in_many_regions" in tags or "contraband" in tags:
        return True
    if "firearm" in tags and ("weapons" in tags or "weapon" in tags):
        return True
    if "ammo" in tags and "restricted" in tags:
        return True
    return False


def apply_contraband_acquire_pressure(state: dict[str, Any], item_id: str, *, via: str) -> int:
    """Bump trace when buying/picking up hot goods. Returns delta applied (0 if skipped)."""
    item_id = str(item_id or "").strip()
    if not item_id:
        return 0
    tags = _item_tags(state, item_id)
    if not _is_contraband_for_heat(tags):
        return 0

    delta = 5
    world = state.get("world", {}) or {}
    loc = str((state.get("player", {}) or {}).get("location", "") or "").strip().lower()
    slot = (world.get("locations", {}) or {}).get(loc) if loc else None
    loc_tags: list[str] = []
    if isinstance(slot, dict):
        lt = slot.get("tags", [])
        if isinstance(lt, list):
            loc_tags = [str(x).lower() for x in lt if isinstance(x, str)]

    if "police_sweep" in loc_tags:
        delta += 8
    if "surveillance_high" in loc_tags:
        delta += 4
    # District police presence amplifies "carry/buy risk" in a grounded way.
    try:
        p = state.get("player", {}) or {}
        loc = str(p.get("location", "") or "").strip().lower()
        did = str(p.get("district", "") or "").strip().lower()
        if loc and did:
            d = get_district(state, loc, did)
            if isinstance(d, dict):
                pp = int(d.get("police_presence", 0) or 0)
                if pp >= 4:
                    delta += 6
                elif pp == 3:
                    delta += 3
    except Exception as _omni_sw_68:
        log_swallowed_exception('engine/systems/illegal_trade.py:68', _omni_sw_68)
    statuses = (world.get("faction_statuses", {}) or {}) if isinstance(world, dict) else {}
    pol = str(statuses.get("police", "idle") or "idle").lower()
    if pol == "aware":
        delta += 4
    elif pol == "investigated":
        delta += 8
    elif pol == "manhunt":
        delta += 12

    if str(via or "").lower() == "pickup":
        delta = max(1, int(delta * 0.85))

    delta = max(0, min(28, int(delta)))
    tr = state.setdefault("trace", {})
    pct = int(tr.get("trace_pct", 0) or 0)
    pct = max(0, min(100, pct + delta))
    tr["trace_pct"] = pct
    if pct <= 25:
        st = "Ghost"
    elif pct <= 50:
        st = "Flagged"
    elif pct <= 75:
        st = "Investigated"
    else:
        st = "Manhunt"
    tr["trace_status"] = st

    try:
        sync_faction_statuses_from_trace(state)
    except Exception as _omni_sw_102:
        log_swallowed_exception('engine/systems/illegal_trade.py:102', _omni_sw_102)
    state.setdefault("world_notes", []).append(
        f"[Heat] Contraband acquire via={via} item={item_id} trace_delta=+{delta} (now {pct}%)"
    )
    return int(delta)
