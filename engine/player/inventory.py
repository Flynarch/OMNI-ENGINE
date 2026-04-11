from __future__ import annotations

from engine.systems.combat import get_active_weapon


def update_inventory(state: dict, action_ctx: dict) -> None:
    inv = state.setdefault("inventory", {})
    inv.setdefault("r_hand", "-")
    inv.setdefault("l_hand", "-")
    inv.setdefault("worn", "-")
    inv.setdefault("pocket_capacity", 4)
    inv.setdefault("pocket_contents", [])
    inv.setdefault("bag_capacity", 12)
    inv.setdefault("bag_contents", [])
    inv.setdefault("item_sizes", {})
    inv.setdefault("weapons", {})
    inv.setdefault("active_weapon_id", "")
    inv.setdefault("vehicles", {})
    inv.setdefault("active_vehicle_id", "")
    pl = state.setdefault("player", {})
    if isinstance(pl, dict):
        a = pl.get("assets")
        if not isinstance(a, dict):
            pl["assets"] = {"version": 1, "entries": []}
        else:
            a.setdefault("version", 1)
            a.setdefault("entries", [])
    flags = state.setdefault("flags", {})
    flags["equip_cost_active"] = bool(action_ctx.get("needs_bag_equip", False))

    # Jam clear requires one full turn + at least one free hand.
    if action_ctx.get("attempt_clear_jam"):
        free_hand = inv.get("r_hand", "-") == "-" or inv.get("l_hand", "-") == "-"
        if free_hand and flags.get("weapon_jammed"):
            flags["weapon_jammed"] = False
            flags["jam_clear_success"] = True
            aw = get_active_weapon(inv)
            if isinstance(aw, dict):
                aw["jammed"] = False
        else:
            flags["jam_clear_success"] = False

    # Mirror active weapon label into r_hand for readability, but NEVER override a real held item.
    active_id = str(inv.get("active_weapon_id", "")).strip()
    if inv.get("r_hand", "-") in ("-", "", None) and active_id and isinstance(inv.get("weapons"), dict) and active_id in inv["weapons"]:
        w = inv["weapons"][active_id]
        inv["r_hand"] = str(w.get("name", active_id))

    # Normalize quantities (clamp non-negative, coerce types) once per turn.
    try:
        from engine.player.inventory_norm import normalize_item_quantities

        normalize_item_quantities(state)
    except Exception:
        pass
