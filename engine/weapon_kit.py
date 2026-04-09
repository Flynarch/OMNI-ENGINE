"""Normalize weapon records in inventory.weapons when buying/picking up weapon items.

Without this, bag only stores item_id strings and combat sees no ammo/kind until someone
manually edits `weapons` — buys/pickups should seed kind, ammo, capacity, condition."""

from __future__ import annotations

from typing import Any


def _tags(state: dict[str, Any], item_id: str) -> list[str]:
    idx = (state.get("world", {}) or {}).get("content_index", {}) or {}
    items = idx.get("items", {}) if isinstance(idx, dict) else {}
    row = items.get(item_id) if isinstance(items, dict) else None
    if not isinstance(row, dict):
        return []
    t = row.get("tags", [])
    if not isinstance(t, list):
        return []
    return [str(x).lower() for x in t if isinstance(x, str)]


def _item_row(state: dict[str, Any], item_id: str) -> dict[str, Any] | None:
    idx = (state.get("world", {}) or {}).get("content_index", {}) or {}
    items = idx.get("items", {}) if isinstance(idx, dict) else None
    if not isinstance(items, dict):
        return None
    r = items.get(item_id)
    return r if isinstance(r, dict) else None


def _infer_kind_from_id(item_id: str) -> str | None:
    s = item_id.lower()
    if any(k in s for k in ("pistol", "gun", "rifle", "smg", "shotgun", "revolver", "firearm", "9mm", "45acp")):
        return "firearm"
    if any(k in s for k in ("knife", "blade", "machete", "baton", "sword", "cleaver", "crowbar")):
        return "melee"
    return None


def _classify_kind(tags: list[str], item_id: str, wprof: dict[str, Any]) -> str | None:
    if isinstance(wprof, dict) and str(wprof.get("kind") or "").strip():
        k = str(wprof.get("kind")).strip().lower()
        if k in ("firearm", "melee"):
            return k
    if any(t in tags for t in ("firearm", "pistol", "rifle", "smg", "shotgun")):
        return "firearm"
    if any(t in tags for t in ("melee", "knife", "blade", "blunt_melee")):
        return "melee"
    if "weapons" in tags or "weapon" in tags:
        return _infer_kind_from_id(item_id) or "melee"
    return _infer_kind_from_id(item_id)


def ensure_weapon_for_item(state: dict[str, Any], item_id: str, *, display_name: str | None = None, source: str = "") -> bool:
    """If item_id is weapon-class, ensure inventory.weapons[item_id] exists with combat fields.

    Returns True if a weapon entry was created/updated.
    """
    item_id = str(item_id or "").strip()
    if not item_id:
        return False

    row = _item_row(state, item_id)
    tags = _tags(state, item_id)
    wprof: dict[str, Any] = {}
    if isinstance(row, dict) and isinstance(row.get("weapon"), dict):
        wprof = row["weapon"]

    kind = _classify_kind(tags, item_id, wprof)
    if kind is None:
        return False

    name = display_name or (str(row.get("name")) if isinstance(row, dict) and row.get("name") else item_id)

    inv = state.setdefault("inventory", {})
    weapons = inv.setdefault("weapons", {})
    existing = weapons.get(item_id) if isinstance(weapons.get(item_id), dict) else {}

    if kind == "firearm":
        cap = int(wprof.get("mag_capacity", 12) or 12) if wprof else 12
        cap = max(1, min(60, cap))
        fill = int(wprof.get("ammo", cap) or cap) if wprof else cap
        fill = max(0, min(cap, fill))
        tier = int(wprof.get("condition_tier", 2) or 2)
        tier = max(1, min(5, tier))
        base = {
            "name": str(name),
            "kind": "firearm",
            "ammo": fill,
            "mag_capacity": cap,
            "condition_tier": tier,
            "use_count": int(existing.get("use_count", 0) or 0),
            "jammed": bool(existing.get("jammed", False)),
        }
        src = str(source or "").lower()
        if existing and src == "buy":
            cur = int(existing.get("ammo", 0) or 0)
            ecap = int(existing.get("mag_capacity", cap) or cap)
            base["mag_capacity"] = ecap
            base["ammo"] = min(ecap * 4, cur + cap)
            base["use_count"] = int(existing.get("use_count", 0) or 0)
            base["jammed"] = bool(existing.get("jammed", False))
            base["condition_tier"] = int(existing.get("condition_tier", tier) or tier)
        elif existing and src == "pickup":
            cur = int(existing.get("ammo", 0) or 0)
            ecap = int(existing.get("mag_capacity", cap) or cap)
            base["mag_capacity"] = ecap
            base["ammo"] = min(ecap * 4, cur + fill)
            base["use_count"] = int(existing.get("use_count", 0) or 0)
            base["jammed"] = bool(existing.get("jammed", False))
            base["condition_tier"] = int(existing.get("condition_tier", tier) or tier)
        elif existing:
            for k in ("ammo", "mag_capacity", "condition_tier", "use_count", "jammed"):
                if k in existing:
                    base[k] = existing[k]
        weapons[item_id] = base
    else:
        tier = int(wprof.get("condition_tier", 2) or 2) if wprof else 2
        tier = max(1, min(5, tier))
        base = {
            "name": str(name),
            "kind": "melee",
            "condition_tier": tier,
            "use_count": int(existing.get("use_count", 0) or 0),
        }
        if existing:
            for k in ("condition_tier", "use_count"):
                if k in existing:
                    base[k] = existing[k]
        weapons[item_id] = base

    return True
