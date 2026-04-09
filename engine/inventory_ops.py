from __future__ import annotations

from typing import Any


def apply_inventory_ops(state: dict[str, Any], action_ctx: dict[str, Any]) -> None:
    """Apply safe micro-operations suggested by intent resolver.

    Deterministic: mutates inventory and increases action_ctx['instant_minutes'] as time cost.
    """

    inv = state.setdefault("inventory", {})
    inv.setdefault("r_hand", "-")
    inv.setdefault("l_hand", "-")
    inv.setdefault("bag_contents", [])
    inv.setdefault("pocket_contents", [])
    world = state.setdefault("world", {})
    world.setdefault("nearby_items", [])
    inv.setdefault("pocket_capacity", 4)
    inv.setdefault("bag_capacity", 12)
    inv.setdefault("item_sizes", {})

    ops = action_ctx.get("inventory_ops")
    if not isinstance(ops, list) or not ops:
        return

    applied: list[str] = []
    extra_minutes = 0

    def _item_size(name: str) -> int:
        sizes = inv.get("item_sizes")
        if isinstance(sizes, dict):
            try:
                v = int(sizes.get(name, 1) or 1)
            except Exception:
                v = 1
            return max(1, min(6, v))
        return 1

    def _used_capacity(items: Any) -> int:
        if not isinstance(items, list):
            return 0
        total = 0
        for it in items:
            total += _item_size(str(it))
        return total

    for raw in ops[:8]:
        if not isinstance(raw, dict):
            continue

        op = str(raw.get("op", "")).strip().lower()
        try:
            tcm = int(raw.get("time_cost_min", 1) or 1)
        except Exception:
            tcm = 1
        tcm = max(0, min(15, tcm))

        if op == "swap_hands":
            inv["r_hand"], inv["l_hand"] = inv.get("l_hand", "-"), inv.get("r_hand", "-")
            applied.append("swap_hands")
            extra_minutes += tcm
            continue

        if op == "pickup":
            item_id = str(raw.get("item_id", "")).strip()
            to = str(raw.get("to", "bag") or "bag").strip().lower()
            if to not in ("pocket", "bag"):
                to = "bag"

            nearby = world.get("nearby_items", [])
            if not isinstance(nearby, list) or not item_id:
                applied.append("pickup_failed:no_nearby_or_missing_id")
                continue

            found_index = None
            found_item_label = None
            for idx, elem in enumerate(nearby):
                if isinstance(elem, dict):
                    eid = str(elem.get("id", "") or elem.get("item_id", "") or elem.get("name", "")).strip()
                    if eid == item_id:
                        found_index = idx
                        found_item_label = str(elem.get("name", item_id))
                        break
                else:
                    if str(elem).strip() == item_id:
                        found_index = idx
                        found_item_label = str(elem)
                        break

            if found_index is None:
                applied.append(f"pickup_failed:not_found:{item_id}")
                continue

            # Store the stable id in inventory, not the display name, so item_sizes
            # and later references remain consistent.
            item = item_id
            size = _item_size(item_id)
            pocket_used = _used_capacity(inv.get("pocket_contents"))
            bag_used = _used_capacity(inv.get("bag_contents"))
            pocket_cap = int(inv.get("pocket_capacity", 4) or 4)
            bag_cap = int(inv.get("bag_capacity", 12) or 12)

            placed_to = None
            if to == "pocket" and pocket_used + size <= pocket_cap:
                inv.setdefault("pocket_contents", [])
                if isinstance(inv.get("pocket_contents"), list):
                    inv["pocket_contents"].append(item)
                placed_to = "pocket"
            elif bag_used + size <= bag_cap:
                inv.setdefault("bag_contents", [])
                if isinstance(inv.get("bag_contents"), list):
                    inv["bag_contents"].append(item)
                placed_to = "bag"

            if placed_to is None:
                applied.append(f"pickup_failed:no_capacity:{item_id}")
                continue

            # Remove from nearby list after pickup.
            try:
                del nearby[found_index]
            except Exception:
                pass

            label = found_item_label or item_id
            applied.append(f"pickup:{item_id}->{placed_to}:{label}")
            extra_minutes += tcm
            continue

        if op in ("stow", "drop"):
            frm = str(raw.get("from", "")).strip()
            if frm not in ("r_hand", "l_hand"):
                continue
            item = str(inv.get(frm, "-"))
            if not item or item == "-":
                continue

            if op == "drop":
                inv[frm] = "-"
                # Dropping into the world makes the item collectible again.
                # We mirror as a simple nearby_items entry (id/name).
                nearby = world.get("nearby_items", [])
                if not isinstance(nearby, list):
                    nearby = []
                    world["nearby_items"] = nearby

                if all(
                    not (isinstance(x, dict) and (x.get("id") == item or x.get("item_id") == item))
                    and not (isinstance(x, str) and x == item)
                    for x in nearby
                ):
                    nearby.append({"id": item, "name": item})
                applied.append(f"drop:{frm}:{item}")
                extra_minutes += tcm
                continue

            to = str(raw.get("to", "")).strip().lower()
            if to not in ("pocket", "bag"):
                to = "bag"
            size = _item_size(item)
            pocket_used = _used_capacity(inv.get("pocket_contents"))
            bag_used = _used_capacity(inv.get("bag_contents"))
            pocket_cap = int(inv.get("pocket_capacity", 4) or 4)
            bag_cap = int(inv.get("bag_capacity", 12) or 12)

            placed_to = None
            if to == "pocket" and pocket_used + size <= pocket_cap:
                inv.setdefault("pocket_contents", [])
                if isinstance(inv.get("pocket_contents"), list):
                    inv["pocket_contents"].append(item)
                placed_to = "pocket"
            elif bag_used + size <= bag_cap:
                inv.setdefault("bag_contents", [])
                if isinstance(inv.get("bag_contents"), list):
                    inv["bag_contents"].append(item)
                placed_to = "bag"

            if placed_to is None:
                applied.append(f"stow_failed:{frm}:{item}")
                continue

            inv[frm] = "-"
            applied.append(f"stow:{frm}->{placed_to}:{item}")
            extra_minutes += tcm
            continue

        if op == "equip_weapon":
            wid = str(raw.get("weapon_id", "")).strip()
            weapons = inv.get("weapons")
            if not wid or not isinstance(weapons, dict) or wid not in weapons:
                applied.append("equip_failed")
                continue
            inv["active_weapon_id"] = wid
            applied.append(f"equip_weapon:{wid}")
            extra_minutes += tcm
            continue

    if applied:
        action_ctx.setdefault("auto_micro_actions", []).extend(applied)
        action_ctx["instant_minutes"] = int(action_ctx.get("instant_minutes", 2) or 2) + int(extra_minutes)
        if extra_minutes > 0:
            action_ctx.setdefault("time_breakdown", []).append({"label": "inventory_ops", "minutes": int(extra_minutes)})

