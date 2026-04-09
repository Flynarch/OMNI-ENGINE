"""Magazine reload from loose rounds in inventory.item_quantities."""

from __future__ import annotations

from typing import Any

from engine.systems.combat import get_active_weapon


def try_reload(state: dict[str, Any]) -> dict[str, Any]:
    """Move compatible reserve rounds into the active firearm's magazine (deterministic, no roll)."""
    inv = state.setdefault("inventory", {})
    w = get_active_weapon(inv)
    if not isinstance(w, dict) or str(w.get("kind", "")).lower() != "firearm":
        return {"ok": False, "reason": "no_firearm_active"}
    if bool(w.get("jammed")):
        return {"ok": False, "reason": "jammed_clear_first"}
    cap = int(w.get("mag_capacity", 0) or 0)
    cur = int(w.get("ammo", 0) or 0)
    need = max(0, cap - cur)
    if need <= 0:
        return {"ok": False, "reason": "mag_full"}

    aid = str(w.get("ammo_item_id", "ammo_9mm") or "ammo_9mm").strip()
    if not aid:
        return {"ok": False, "reason": "no_ammo_type"}

    iq = inv.setdefault("item_quantities", {})
    if not isinstance(iq, dict):
        iq = {}
        inv["item_quantities"] = iq
    have = int(iq.get(aid, 0) or 0)
    take = min(need, have)
    if take <= 0:
        return {"ok": False, "reason": "no_reserve_ammo", "ammo_item_id": aid}

    iq[aid] = max(0, have - take)
    w["ammo"] = cur + take
    return {
        "ok": True,
        "loaded": int(take),
        "ammo_item_id": aid,
        "reserve_after": int(iq[aid]),
        "mag_after": int(w["ammo"]),
    }
