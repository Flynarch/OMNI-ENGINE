from __future__ import annotations

from typing import Any


def _here_key(state: dict[str, Any]) -> str:
    return str((state.get("player", {}) or {}).get("location", "") or "").strip().lower()


def _ensure_safehouse_row(state: dict[str, Any]) -> dict[str, Any]:
    from engine.systems.safehouse import ensure_safehouse_here

    return ensure_safehouse_here(state)


def _norm_stash(stash: Any) -> list[dict[str, Any]]:
    """Normalize stash list to list[dict] entries.

    Back-compat: existing stash may contain strings.
    """
    out: list[dict[str, Any]] = []
    if isinstance(stash, list):
        for x in stash[:200]:
            if isinstance(x, dict) and str(x.get("item_id", "") or "").strip():
                out.append(dict(x))
            elif isinstance(x, str) and x.strip():
                out.append({"item_id": x.strip(), "kind": "item"})
    return out


def list_stash_here(state: dict[str, Any]) -> list[dict[str, Any]]:
    row = _ensure_safehouse_row(state)
    stash = _norm_stash(row.get("stash"))
    row["stash"] = stash
    return stash


def get_stash_ammo_here(state: dict[str, Any]) -> dict[str, int]:
    row = _ensure_safehouse_row(state)
    m = row.get("stash_ammo")
    if not isinstance(m, dict):
        m = {}
        row["stash_ammo"] = m
    out: dict[str, int] = {}
    for k, v in list(m.items())[:200]:
        kid = str(k or "").strip()
        if not kid:
            continue
        try:
            out[kid] = max(0, int(v or 0))
        except Exception:
            out[kid] = 0
    row["stash_ammo"] = out
    return out


def stash_put_ammo(state: dict[str, Any], ammo_item_id: str, *, rounds: int) -> dict[str, Any]:
    aid = str(ammo_item_id or "").strip()
    if not aid:
        return {"ok": False, "reason": "missing_ammo_item_id"}
    n = max(1, min(99999, int(rounds or 0)))

    row = _ensure_safehouse_row(state)
    if str(row.get("status", "none") or "none") == "none":
        return {"ok": False, "reason": "no_safehouse_here"}

    inv = state.setdefault("inventory", {})
    iq = inv.setdefault("item_quantities", {})
    if not isinstance(iq, dict):
        iq = {}
        inv["item_quantities"] = iq
    have = int(iq.get(aid, 0) or 0)
    if have < n:
        return {"ok": False, "reason": "not_enough_ammo", "have": have, "need": n}

    # Only allow ammo-tagged items.
    try:
        from engine.systems.ammo import item_is_ammo

        if not item_is_ammo(state, aid):
            return {"ok": False, "reason": "not_ammo_item"}
    except Exception:
        pass

    iq[aid] = have - n
    sm = get_stash_ammo_here(state)
    sm[aid] = int(sm.get(aid, 0) or 0) + n
    row["stash_ammo"] = sm
    state.setdefault("world_notes", []).append(f"[Safehouse] STASH_PUT_AMMO ammo={aid} rounds=-{n} @ {_here_key(state)}")
    return {"ok": True, "ammo_item_id": aid, "rounds": n, "stash_rounds": int(sm[aid]), "carry_rounds": int(iq[aid])}


def stash_take_ammo(state: dict[str, Any], ammo_item_id: str, *, rounds: int) -> dict[str, Any]:
    aid = str(ammo_item_id or "").strip()
    if not aid:
        return {"ok": False, "reason": "missing_ammo_item_id"}
    n = max(1, min(99999, int(rounds or 0)))

    row = _ensure_safehouse_row(state)
    if str(row.get("status", "none") or "none") == "none":
        return {"ok": False, "reason": "no_safehouse_here"}

    sm = get_stash_ammo_here(state)
    have = int(sm.get(aid, 0) or 0)
    if have < n:
        return {"ok": False, "reason": "not_enough_stashed_ammo", "have": have, "need": n}

    inv = state.setdefault("inventory", {})
    iq = inv.setdefault("item_quantities", {})
    if not isinstance(iq, dict):
        iq = {}
        inv["item_quantities"] = iq

    sm[aid] = have - n
    iq[aid] = int(iq.get(aid, 0) or 0) + n
    row["stash_ammo"] = sm
    state.setdefault("world_notes", []).append(f"[Safehouse] STASH_TAKE_AMMO ammo={aid} rounds=+{n} @ {_here_key(state)}")
    return {"ok": True, "ammo_item_id": aid, "rounds": n, "stash_rounds": int(sm[aid]), "carry_rounds": int(iq[aid])}


def stash_put_from_bag(state: dict[str, Any], item_id: str) -> dict[str, Any]:
    """Move one item_id from bag -> safehouse stash, preserving weapon record if present."""
    iid = str(item_id or "").strip()
    if not iid:
        return {"ok": False, "reason": "missing_item_id"}

    row = _ensure_safehouse_row(state)
    if str(row.get("status", "none") or "none") == "none":
        return {"ok": False, "reason": "no_safehouse_here"}

    inv = state.get("inventory", {}) or {}
    bag = inv.get("bag_contents", [])
    if not isinstance(bag, list) or not any(str(x) == iid for x in bag):
        return {"ok": False, "reason": "not_in_bag"}

    # Remove from bag (one instance).
    removed = False
    kept: list[Any] = []
    for x in bag:
        if not removed and str(x) == iid:
            removed = True
            continue
        kept.append(x)
    inv["bag_contents"] = kept

    stash = _norm_stash(row.get("stash"))
    wmap = inv.get("weapons", {}) if isinstance(inv.get("weapons"), dict) else {}
    wentry = wmap.get(iid) if isinstance(wmap, dict) and isinstance(wmap.get(iid), dict) else None
    if wentry is not None:
        # Store full weapon record in stash, and remove from carry registry.
        stash.append({"item_id": iid, "kind": "weapon", "weapon": dict(wentry), "from": "bag"})
        try:
            del wmap[iid]
        except Exception:
            pass
        inv["weapons"] = wmap
        if str(inv.get("active_weapon_id", "") or "") == iid:
            inv["active_weapon_id"] = ""
    else:
        stash.append({"item_id": iid, "kind": "item", "from": "bag"})

    row["stash"] = stash
    state.setdefault("world_notes", []).append(f"[Safehouse] STASH_PUT item={iid} @ {_here_key(state)}")
    return {"ok": True, "item_id": iid, "stash_count": len(stash)}


def stash_take_to_bag(state: dict[str, Any], item_id: str) -> dict[str, Any]:
    """Move one item_id from safehouse stash -> bag, restoring weapon record if stored."""
    iid = str(item_id or "").strip()
    if not iid:
        return {"ok": False, "reason": "missing_item_id"}

    row = _ensure_safehouse_row(state)
    if str(row.get("status", "none") or "none") == "none":
        return {"ok": False, "reason": "no_safehouse_here"}

    stash = _norm_stash(row.get("stash"))
    idx = next((i for i, e in enumerate(stash) if isinstance(e, dict) and str(e.get("item_id", "") or "") == iid), None)
    if idx is None:
        return {"ok": False, "reason": "not_in_stash"}

    entry = stash.pop(int(idx))
    row["stash"] = stash

    inv = state.setdefault("inventory", {})
    inv.setdefault("bag_contents", [])
    if isinstance(inv.get("bag_contents"), list):
        inv["bag_contents"].append(iid)

    if isinstance(entry, dict) and entry.get("kind") == "weapon" and isinstance(entry.get("weapon"), dict):
        inv.setdefault("weapons", {})
        wmap = inv.get("weapons")
        if isinstance(wmap, dict):
            wmap[iid] = dict(entry.get("weapon") or {})
            inv["weapons"] = wmap

    state.setdefault("world_notes", []).append(f"[Safehouse] STASH_TAKE item={iid} @ {_here_key(state)}")
    return {"ok": True, "item_id": iid, "stash_count": len(stash)}

