from __future__ import annotations

import hashlib
from typing import Any


_POOL: list[dict[str, Any]] = [
    {"id": "cyberdeck_mk1", "name": "Cyberdeck MK1", "base_price": 4200},
    {"id": "police_scanner", "name": "Police Scanner", "base_price": 1800},
    {"id": "burner_phone", "name": "Burner Phone", "base_price": 350},
    {"id": "fake_id", "name": "Fake ID", "base_price": 900},
    {"id": "lockpick", "name": "Lockpick Set", "base_price": 250},
    {"id": "disguise_kit", "name": "Disguise Kit", "base_price": 1200},
]


def _seed_key(state: dict[str, Any]) -> str:
    meta = state.get("meta", {}) or {}
    seed = str(meta.get("world_seed", "") or meta.get("seed_pack", "") or "").strip()
    return seed or "seed"


def _day(state: dict[str, Any]) -> int:
    meta = state.get("meta", {}) or {}
    try:
        return int(meta.get("day", 1) or 1)
    except Exception:
        return 1


def _time_min(state: dict[str, Any]) -> int:
    meta = state.get("meta", {}) or {}
    try:
        return int(meta.get("time_min", 0) or 0)
    except Exception:
        return 0


def _loc(state: dict[str, Any]) -> str:
    return str((state.get("player", {}) or {}).get("location", "") or "").strip().lower()


def _night_access(time_min: int) -> bool:
    # 20:00..04:00
    return int(time_min) >= 20 * 60 or int(time_min) < 4 * 60


def has_underworld_contact_here(state: dict[str, Any]) -> bool:
    loc = _loc(state)
    if not loc:
        return False
    # Check global NPC map (simplest + used in tests).
    npcs = state.get("npcs", {}) or {}
    if isinstance(npcs, dict):
        for _nid, row in list(npcs.items())[:200]:
            if not isinstance(row, dict):
                continue
            here = str(row.get("current_location", row.get("home_location", "")) or "").strip().lower()
            if here and here != loc:
                continue
            role = str(row.get("role", "") or "").strip().lower()
            tags = row.get("tags", []) or row.get("belief_tags", []) or []
            if not isinstance(tags, list):
                tags = []
            tags_l = [str(x).strip().lower() for x in tags if isinstance(x, str)]
            if "fixer" in tags_l or "smuggler" in tags_l:
                return True
            if role in ("fixer", "smuggler"):
                return True
    # Check location slot NPCs if present.
    try:
        slot = ((state.get("world", {}) or {}).get("locations", {}) or {}).get(loc)
        if isinstance(slot, dict):
            lnpcs = slot.get("npcs") or {}
            if isinstance(lnpcs, dict):
                for _nm, row in list(lnpcs.items())[:120]:
                    if not isinstance(row, dict):
                        continue
                    role = str(row.get("role", "") or "").strip().lower()
                    tags = row.get("tags", []) or []
                    if not isinstance(tags, list):
                        tags = []
                    tags_l = [str(x).strip().lower() for x in tags if isinstance(x, str)]
                    if "fixer" in tags_l or "smuggler" in tags_l or role in ("fixer", "smuggler"):
                        return True
    except Exception:
        pass
    return False


def black_market_accessible(state: dict[str, Any]) -> bool:
    return _night_access(_time_min(state)) or has_underworld_contact_here(state)


def generate_black_market_inventory(state: dict[str, Any]) -> dict[str, Any]:
    """Daily rotating underground stock (deterministic per seed+day)."""
    seed = _seed_key(state)
    day = _day(state)
    h = hashlib.md5(f"{seed}|{day}|black_market_v1".encode("utf-8", errors="ignore")).hexdigest()
    n = 3 + (int(h[:2], 16) % 3)  # 3..5
    picked: list[dict[str, Any]] = []
    used: set[str] = set()
    for i in range(12):
        if len(picked) >= n:
            break
        hi = hashlib.md5(f"{h}|pick|{i}".encode("utf-8", errors="ignore")).hexdigest()
        idx = int(hi[:2], 16) % len(_POOL)
        row = dict(_POOL[idx])
        iid = str(row.get("id", "") or "")
        if not iid or iid in used:
            continue
        used.add(iid)
        # Price fluctuation: -15% .. +25% (full-integer math).
        base = int(row.get("base_price", 0) or 0)
        f_raw = (int(hi[2:4], 16) % 41) - 15  # -15..25
        price = max(1, (base * (100 + int(f_raw))) // 100)
        row["price"] = int(price)
        row["day"] = int(day)
        row["stock"] = 1
        picked.append(row)

    world = state.setdefault("world", {})
    bm = world.setdefault("black_market", {})
    if not isinstance(bm, dict):
        bm = {}
        world["black_market"] = bm
    bm["day"] = int(day)
    bm.setdefault("purchases_by_day", {})
    if not isinstance(bm.get("purchases_by_day"), dict):
        bm["purchases_by_day"] = {}
    bought = bm["purchases_by_day"].get(str(day), [])
    if not isinstance(bought, list):
        bought = []
    bought_ids = {str(x) for x in bought if isinstance(x, str)}
    items = [x for x in picked if str(x.get("id", "") or "") not in bought_ids]
    bm["items"] = items
    world["black_market"] = bm
    return {"day": int(day), "items": list(items)}


def buy_black_market_item(state: dict[str, Any], item_id: str) -> dict[str, Any]:
    iid = str(item_id or "").strip()
    if not iid:
        return {"ok": False, "reason": "missing_item_id"}
    if not black_market_accessible(state):
        return {"ok": False, "reason": "connection_refused"}
    inv = generate_black_market_inventory(state)
    items = inv.get("items", [])
    if not isinstance(items, list):
        items = []
    row = None
    for it in items:
        if isinstance(it, dict) and str(it.get("id", "") or "") == iid:
            row = it
            break
    if not isinstance(row, dict):
        return {"ok": False, "reason": "not_in_stock"}
    price = int(row.get("price", 0) or 0)
    eco = state.setdefault("economy", {})
    try:
        cash = int(eco.get("cash", 0) or 0)
    except Exception:
        cash = 0
    if cash < price:
        return {"ok": False, "reason": "not_enough_cash", "need": int(price), "cash": int(cash)}
    # Sting operation check (deterministic): 5% base + 15% if trace_pct > 50.
    try:
        tr = state.get("trace", {}) or {}
        tp = int(tr.get("trace_pct", 0) or 0) if isinstance(tr, dict) else 0
    except Exception:
        tp = 0
    base_chance = 5 + (15 if int(tp) > 50 else 0)
    seed = _seed_key(state)
    day = _day(state)
    h = hashlib.md5(f"{seed}|{day}|{iid}|sting".encode("utf-8", errors="ignore")).hexdigest()
    r = int(h[:8], 16) % 100
    if int(r) < int(base_chance):
        # Money is burned as evidence/deposit; item is not delivered.
        eco["cash"] = int(cash - price)
        state["economy"] = eco
        state.setdefault("world_notes", []).append("[Security] It's a setup! A sting operation has been triggered during the Black Market deal.")
        scene_id = hashlib.md5(f"{seed}|{day}|{iid}|sting_operation".encode("utf-8", errors="ignore")).hexdigest()[:10]
        state["active_scene"] = {
            "scene_id": scene_id,
            "scene_type": "sting_operation",
            "phase": "ambush",
            "next_options": ["SCENE SURRENDER", "SCENE FLEE", "SCENE FIGHT"],
        }
        return {"ok": False, "reason": "sting_operation", "roll": int(r), "chance": int(base_chance)}

    eco["cash"] = int(cash - price)
    state["economy"] = eco
    inv2 = state.setdefault("inventory", {})
    if not isinstance(inv2, dict):
        inv2 = {}
        state["inventory"] = inv2
    bag = inv2.setdefault("bag_contents", [])
    if not isinstance(bag, list):
        bag = []
    bag.append(iid)
    inv2["bag_contents"] = bag
    state["inventory"] = inv2

    world = state.setdefault("world", {})
    bm = world.setdefault("black_market", {})
    if not isinstance(bm, dict):
        bm = {}
    bm.setdefault("purchases_by_day", {})
    if not isinstance(bm.get("purchases_by_day"), dict):
        bm["purchases_by_day"] = {}
    day = _day(state)
    key = str(day)
    arr = bm["purchases_by_day"].get(key, [])
    if not isinstance(arr, list):
        arr = []
    if iid not in arr:
        arr.append(iid)
    bm["purchases_by_day"][key] = arr
    world["black_market"] = bm

    nm = str(row.get("name", iid) or iid)
    state.setdefault("world_notes", []).append(f"[Economy] Purchased {nm} from the underground network.")
    return {"ok": True, "item_id": iid, "name": nm, "price": int(price), "cash_after": int(eco.get("cash", 0) or 0)}

