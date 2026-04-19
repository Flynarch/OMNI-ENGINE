from __future__ import annotations

from engine.core.error_taxonomy import log_swallowed_exception
from engine.systems.scene_roll import scene_rng
from typing import Any


def _inv_carried_ids(state: dict[str, Any]) -> list[str]:
    inv = state.get("inventory", {}) or {}
    if not isinstance(inv, dict):
        return []
    out: list[str] = []
    for k in ("bag_contents", "pocket_contents"):
        arr = inv.get(k, [])
        if isinstance(arr, list):
            for x in arr[:200]:
                s = str(x or "").strip()
                if s:
                    out.append(s)
    for k in ("r_hand", "l_hand", "worn"):
        v = str(inv.get(k, "") or "").strip()
        if v and v != "-":
            out.append(v)
    # de-dupe preserve order
    seen: set[str] = set()
    uniq: list[str] = []
    for x in out:
        if x not in seen:
            uniq.append(x)
            seen.add(x)
    return uniq


def list_concealable_items(state: dict[str, Any]) -> list[str]:
    """Return carried item ids that can be concealed/dumped (simple v1)."""
    return _inv_carried_ids(state)


def _conceal_map(state: dict[str, Any]) -> dict[str, Any]:
    world = state.setdefault("world", {})
    if not isinstance(world, dict):
        return {}
    cm = world.setdefault("conceal", {})
    if not isinstance(cm, dict):
        cm = {}
        world["conceal"] = cm
    return cm


def apply_conceal(state: dict[str, Any], *, item_id: str, method: str = "body") -> dict[str, Any]:
    """Mark an item as concealed for search resolution (does not move inventory)."""
    iid = str(item_id or "").strip()
    if not iid:
        return {"ok": False, "reason": "missing_item_id"}
    if iid not in _inv_carried_ids(state):
        return {"ok": False, "reason": "not_carried"}
    cm = _conceal_map(state)
    cm[iid] = {"method": str(method or "body"), "since_turn": int((state.get("meta", {}) or {}).get("turn", 0) or 0)}
    return {"ok": True, "item_id": iid, "method": str(method or "body")}


def apply_dump(state: dict[str, Any], *, item_id: str) -> dict[str, Any]:
    """Remove an item from carried inventory (bag/pocket/hands/worn)."""
    iid = str(item_id or "").strip()
    if not iid:
        return {"ok": False, "reason": "missing_item_id"}
    inv = state.get("inventory", {}) if isinstance(state.get("inventory"), dict) else {}
    if not isinstance(inv, dict):
        return {"ok": False, "reason": "invalid_inventory"}
    removed = 0
    for k in ("r_hand", "l_hand", "worn"):
        if str(inv.get(k, "") or "").strip() == iid:
            inv[k] = "-"
            removed += 1
    for k in ("bag_contents", "pocket_contents"):
        arr = inv.get(k, [])
        if not isinstance(arr, list) or not arr:
            continue
        kept: list[str] = []
        for x in arr:
            s = str(x or "").strip()
            if s == iid and removed == 0:
                removed += 1
                continue
            kept.append(s)
        inv[k] = [x for x in kept if x]
    state["inventory"] = inv
    if removed <= 0:
        return {"ok": False, "reason": "not_found"}
    # Also remove conceal mark if any.
    try:
        cm = _conceal_map(state)
        cm.pop(iid, None)
    except Exception as _omni_sw_92:
        log_swallowed_exception('engine/systems/search_conceal.py:92', _omni_sw_92)
    return {"ok": True, "item_id": iid, "removed": int(removed)}


def resolve_search(
    state: dict[str, Any],
    *,
    scene_id: str,
    scene_type: str,
    intensity: int,
    salt: str,
) -> dict[str, Any]:
    """Deterministically decide which carried items are found vs missed."""
    intensity = max(0, min(100, int(intensity or 0)))
    carried = _inv_carried_ids(state)
    cm = _conceal_map(state)
    found: list[str] = []
    missed: list[str] = []
    for iid in carried[:40]:
        conceal_bonus = 0
        if isinstance(cm, dict) and isinstance(cm.get(iid), dict):
            # Conceal bonus reduces chance of being found.
            conceal_bonus = 25
            m = str((cm.get(iid) or {}).get("method", "body") or "body").lower()
            if m in ("bag", "container"):
                conceal_bonus = 15
        # Found chance is intensity minus conceal bonus.
        chance = max(5, min(95, intensity - conceal_bonus))
        r = scene_rng(state, scene_id=scene_id, scene_type=scene_type, salt=f"{salt}|{iid}")
        if r < chance:
            found.append(iid)
        else:
            missed.append(iid)
    return {"found": found, "missed": missed, "intensity": int(intensity)}

