from __future__ import annotations

from dataclasses import dataclass
from typing import Any
import hashlib


@dataclass(frozen=True)
class ShopQuote:
    item_id: str
    name: str
    category: str
    base_price: int
    price_idx: int
    scarcity: int
    buy_price: int
    sell_price: int
    available: bool
    sold_out_reason: str


@dataclass(frozen=True)
class CapacityStatus:
    pocket_used: int
    pocket_cap: int
    bag_used: int
    bag_cap: int


def _clamp_int(v: Any, lo: int, hi: int, default: int) -> int:
    try:
        x = int(v)
    except Exception:
        return int(default)
    return max(lo, min(hi, x))


def _get_local_market(state: dict[str, Any]) -> dict[str, dict[str, int]]:
    eco = state.get("economy", {}) or {}
    mkt = eco.get("market", {}) or {}
    try:
        loc = str((state.get("player", {}) or {}).get("location", "") or "").strip().lower()
        slot = ((state.get("world", {}) or {}).get("locations", {}) or {}).get(loc)
        if isinstance(slot, dict) and isinstance(slot.get("market"), dict) and slot.get("market"):
            mkt = slot.get("market") or mkt
    except Exception:
        pass
    return mkt if isinstance(mkt, dict) else {}


def _get_loc_key(state: dict[str, Any]) -> str:
    try:
        return str((state.get("player", {}) or {}).get("location", "") or "").strip().lower()
    except Exception:
        return ""


def _get_seed_key(state: dict[str, Any]) -> str:
    meta = state.get("meta", {}) or {}
    if isinstance(meta, dict):
        ws = str(meta.get("world_seed", "") or "").strip()
        if ws:
            return ws
        sp = str(meta.get("seed_pack", "") or "").strip()
        if sp:
            return sp
    return "seed"


def _get_day(state: dict[str, Any]) -> int:
    meta = state.get("meta", {}) or {}
    try:
        return int((meta.get("day", 1) if isinstance(meta, dict) else 1) or 1)
    except Exception:
        return 1


def _get_location_tags(state: dict[str, Any]) -> list[str]:
    loc = _get_loc_key(state)
    slot = (((state.get("world", {}) or {}).get("locations", {}) or {}).get(loc) if loc else None)
    if isinstance(slot, dict):
        tags = slot.get("tags") or []
        if isinstance(tags, list):
            out: list[str] = []
            for t in tags[:20]:
                if isinstance(t, str) and t.strip():
                    s = t.strip().lower()
                    if s not in out:
                        out.append(s)
            return out
    return []


def _get_location_npc_roles(state: dict[str, Any]) -> list[str]:
    loc = _get_loc_key(state)
    slot = (((state.get("world", {}) or {}).get("locations", {}) or {}).get(loc) if loc else None)
    roles: list[str] = []
    if isinstance(slot, dict):
        npcs = slot.get("npcs") or {}
        if isinstance(npcs, dict):
            for _nm, row in list(npcs.items())[:80]:
                if not isinstance(row, dict):
                    continue
                r = str(row.get("role", "") or "").strip().lower()
                if r and r not in roles:
                    roles.append(r)
    return roles


def _category_for_item(item: dict[str, Any]) -> str:
    tags = item.get("tags", [])
    tags_l = [str(x).lower() for x in tags] if isinstance(tags, list) else []
    if "weapons" in tags_l or "weapon" in tags_l:
        return "weapons"
    if "medical" in tags_l:
        return "medical"
    if "food" in tags_l:
        return "food"
    if "transport" in tags_l:
        return "transport"
    # electronics/comms/tools default to electronics market bucket
    if "electronics" in tags_l or "comms" in tags_l or "tool" in tags_l or "translator_basic" in tags_l or "translator_good" in tags_l:
        return "electronics"
    return "electronics"


def _compute_price(base_price: int, *, price_idx: int, scarcity: int) -> int:
    # Deterministic, bounded simple pricing.
    # scarcity increases price up to +50% at scarcity=100.
    mult = (max(60, min(320, int(price_idx))) / 100.0) * (1.0 + max(0, min(100, int(scarcity))) / 200.0)
    return max(1, int(round(int(base_price) * mult)))


def _sold_out_rate_from_scarcity(scarcity: int) -> int:
    """Deterministic sold-out probability (0..95) as function of scarcity."""
    sc = max(0, min(100, int(scarcity)))
    if sc < 70:
        return 0
    # 70 -> 40%, 80 -> 80%, 84+ -> 95% cap
    return max(0, min(95, (sc - 60) * 4))


def _is_sold_out(state: dict[str, Any], *, item_id: str, category: str, scarcity: int) -> tuple[bool, str]:
    rate = _sold_out_rate_from_scarcity(scarcity)
    if rate <= 0:
        return (False, "")
    seed = _get_seed_key(state)
    day = _get_day(state)
    loc = _get_loc_key(state)
    h = hashlib.md5(f"{seed}|{day}|{loc}|{category}|{item_id}|stock".encode("utf-8", errors="ignore")).hexdigest()
    r = int(h[:8], 16) % 100
    if r < rate:
        return (True, f"sold_out(sc={scarcity},rate={rate}%)")
    return (False, "")


def _item_tags(item: dict[str, Any]) -> list[str]:
    tags = item.get("tags", [])
    if not isinstance(tags, list):
        return []
    out: list[str] = []
    for t in tags[:40]:
        if isinstance(t, str) and t.strip():
            s = t.strip().lower()
            if s not in out:
                out.append(s)
    return out


def _matches_tag_filter(item_tags: list[str], tag_filter: str) -> bool:
    tf = str(tag_filter or "").strip().lower()
    if not tf:
        return True
    # allow alias queries
    aliases = {
        "trans": "translator",
        "translate": "translator",
        "phone": "comms",
        "comm": "comms",
        "electronics": "electronics",
        "weapon": "weapons",
    }
    tf = aliases.get(tf, tf)

    # direct tag hit
    if tf in item_tags:
        return True
    # group queries
    if tf == "translator":
        return any(t.startswith("translator_") for t in item_tags)
    if tf == "comms":
        return "comms" in item_tags or "burner_phone" in item_tags or "smartphone" in item_tags
    if tf == "tool":
        return "tool" in item_tags
    if tf == "stealth":
        return "stealth" in item_tags or "lockpick" in " ".join(item_tags)
    if tf == "medical":
        return "medical" in item_tags
    return False


def _score_item_for_role(item_tags: list[str], *, role: str, loc_tags: list[str]) -> int:
    r = str(role or "").strip().lower()
    score = 0
    # Global signals from location tags.
    if "surveillance_high" in loc_tags:
        if "stealth" in item_tags or "burner" in " ".join(item_tags):
            score += 6
        if "translator_good" in item_tags or "translator_basic" in item_tags:
            score += 2
    if "nightlife_hot" in loc_tags or "rumor_fast" in loc_tags:
        if "comms" in item_tags or "burner" in " ".join(item_tags):
            score += 3
    if "traffic_friction" in loc_tags and "transport" in item_tags:
        score += 2

    # Role preference.
    if r in ("fixer", "broker"):
        if "tool" in item_tags:
            score += 7
        if "stealth" in item_tags:
            score += 6
        if "comms" in item_tags:
            score += 5
        if "electronics" in item_tags:
            score += 4
        if "translator_advanced" in item_tags:
            score += 2
    elif r in ("doc", "medic", "doctor"):
        if "medical" in item_tags:
            score += 9
        if "translator_lowtech" in item_tags:
            score += 5
        if "translator_basic" in item_tags:
            score += 6
        if "translator_good" in item_tags:
            score += 7
        if "translator_advanced" in item_tags:
            score += 8
    elif r in ("merchant", "vendor", "shopkeeper"):
        # Generalist: likes common, low-complexity items.
        if "comms" in item_tags or "tool" in item_tags:
            score += 3
        if "translator_lowtech" in item_tags:
            score += 2
    elif r in ("security", "cop", "detective", "police"):
        if "stealth" in item_tags:
            score += 2
        if "tool" in item_tags:
            score += 1
    else:
        # Unknown role: small bump for useful basics.
        if "comms" in item_tags:
            score += 2
        if "tool" in item_tags:
            score += 2
    return score


def list_shop_quotes(
    state: dict[str, Any],
    *,
    limit: int = 12,
    role: str | None = None,
    offset: int = 0,
    tag: str | None = None,
) -> list[ShopQuote]:
    """Return deterministic shop quotes from content packs + current market."""
    world = state.get("world", {}) or {}
    idx = (world.get("content_index", {}) or {}) if isinstance(world, dict) else {}
    items = idx.get("items", {}) if isinstance(idx, dict) else {}
    if not isinstance(items, dict) or not items:
        return []

    mkt = _get_local_market(state)
    loc_tags = _get_location_tags(state)
    npc_roles = _get_location_npc_roles(state)
    want_role = str(role or "").strip().lower()
    tag_filter = str(tag or "").strip().lower()

    scored: list[tuple[int, str]] = []
    for iid in sorted([str(k) for k in items.keys()])[:200]:
        row = items.get(iid)
        if not isinstance(row, dict):
            continue
        base_price = _clamp_int(row.get("base_price", 0), 0, 10_000_000, 0)
        if base_price <= 0:
            continue
        itags = _item_tags(row)
        if tag_filter and not _matches_tag_filter(itags, tag_filter):
            continue
        sc = 0
        if want_role:
            # If that role exists locally, boost relevance; otherwise still allow but slightly lower confidence.
            if want_role in npc_roles:
                sc += 4
            else:
                sc -= 2
            sc += _score_item_for_role(itags, role=want_role, loc_tags=loc_tags)
        else:
            # No specific role: blend top relevance across any local roles.
            if npc_roles:
                for r in npc_roles[:4]:
                    sc = max(sc, _score_item_for_role(itags, role=r, loc_tags=loc_tags))
            else:
                sc = _score_item_for_role(itags, role="", loc_tags=loc_tags)
        # Prefer cheaper items for display (merchant-like UX), but keep deterministic.
        sc += max(0, 8 - int(base_price / 250))
        scored.append((sc, iid))

    scored.sort(key=lambda t: (-t[0], t[1]))

    off = max(0, int(offset))
    window = max(12, min(240, int(limit) * 10))
    out: list[ShopQuote] = []
    for _sc, iid in scored[off : off + window]:
        row = items.get(iid)
        if not isinstance(row, dict):
            continue
        base_price = _clamp_int(row.get("base_price", 0), 0, 10_000_000, 0)
        if base_price <= 0:
            continue
        cat = _category_for_item(row)
        mrow = mkt.get(cat, {}) if isinstance(mkt.get(cat), dict) else {}
        price_idx = _clamp_int(mrow.get("price_idx", 100), 50, 320, 100)
        scarcity = _clamp_int(mrow.get("scarcity", 0), 0, 100, 0)
        buy = _compute_price(base_price, price_idx=price_idx, scarcity=scarcity)
        sell = max(1, int(round(buy * 0.6)))
        sold, reason = _is_sold_out(state, item_id=iid, category=cat, scarcity=scarcity)
        out.append(
            ShopQuote(
                item_id=iid,
                name=str(row.get("name", iid) or iid),
                category=str(cat),
                base_price=int(base_price),
                price_idx=int(price_idx),
                scarcity=int(scarcity),
                buy_price=int(buy),
                sell_price=int(sell),
                available=not sold,
                sold_out_reason=str(reason),
            )
        )
        if len(out) >= max(1, min(30, int(limit))):
            break
    return out


def quote_item(state: dict[str, Any], item_id: str) -> ShopQuote | None:
    iid = str(item_id or "").strip()
    if not iid:
        return None
    for q in list_shop_quotes(state, limit=60):
        if q.item_id == iid:
            return q
    # If not in limited list, still allow quoting if exists in content index.
    world = state.get("world", {}) or {}
    idx = (world.get("content_index", {}) or {}) if isinstance(world, dict) else {}
    items = idx.get("items", {}) if isinstance(idx, dict) else {}
    row = items.get(iid) if isinstance(items, dict) else None
    if not isinstance(row, dict):
        return None
    base_price = _clamp_int(row.get("base_price", 0), 0, 10_000_000, 0)
    if base_price <= 0:
        return None
    cat = _category_for_item(row)
    mkt = _get_local_market(state)
    mrow = mkt.get(cat, {}) if isinstance(mkt.get(cat), dict) else {}
    price_idx = _clamp_int(mrow.get("price_idx", 100), 50, 320, 100)
    scarcity = _clamp_int(mrow.get("scarcity", 0), 0, 100, 0)
    buy = _compute_price(base_price, price_idx=price_idx, scarcity=scarcity)
    sell = max(1, int(round(buy * 0.6)))
    sold, reason = _is_sold_out(state, item_id=iid, category=cat, scarcity=scarcity)
    return ShopQuote(
        item_id=iid,
        name=str(row.get("name", iid) or iid),
        category=str(cat),
        base_price=int(base_price),
        price_idx=int(price_idx),
        scarcity=int(scarcity),
        buy_price=int(buy),
        sell_price=int(sell),
        available=not sold,
        sold_out_reason=str(reason),
    )


def _item_size(state: dict[str, Any], item_id: str) -> int:
    inv = state.get("inventory", {}) or {}
    sizes = inv.get("item_sizes", {}) if isinstance(inv, dict) else {}
    if isinstance(sizes, dict):
        return _clamp_int(sizes.get(item_id, 1), 1, 6, 1)
    return 1


def _used_capacity(state: dict[str, Any], which: str) -> int:
    inv = state.get("inventory", {}) or {}
    items = inv.get(which, []) if isinstance(inv, dict) else []
    if not isinstance(items, list):
        return 0
    total = 0
    for it in items:
        total += _item_size(state, str(it))
    return total


def get_capacity_status(state: dict[str, Any]) -> CapacityStatus:
    inv = state.get("inventory", {}) or {}
    pocket_cap = _clamp_int((inv.get("pocket_capacity", 4) if isinstance(inv, dict) else 4), 1, 99, 4)
    bag_cap = _clamp_int((inv.get("bag_capacity", 12) if isinstance(inv, dict) else 12), 1, 99, 12)
    return CapacityStatus(
        pocket_used=_used_capacity(state, "pocket_contents"),
        pocket_cap=pocket_cap,
        bag_used=_used_capacity(state, "bag_contents"),
        bag_cap=bag_cap,
    )


def buy_item(state: dict[str, Any], item_id: str, *, prefer: str = "bag") -> dict[str, Any]:
    q = quote_item(state, item_id)
    if q is None:
        return {"ok": False, "reason": "unknown_item"}
    if not bool(q.available):
        return {"ok": False, "reason": "sold_out", "detail": q.sold_out_reason}
    eco = state.setdefault("economy", {})
    cash = _clamp_int(eco.get("cash", 0), 0, 10_000_000_000, 0)
    if cash < q.buy_price:
        return {"ok": False, "reason": "not_enough_cash", "need": q.buy_price, "cash": cash}

    inv = state.setdefault("inventory", {})
    inv.setdefault("bag_contents", [])
    inv.setdefault("pocket_contents", [])
    inv.setdefault("bag_capacity", 12)
    inv.setdefault("pocket_capacity", 4)

    size = _item_size(state, q.item_id)
    cap = get_capacity_status(state)
    prefer_n = str(prefer or "bag").strip().lower()
    if prefer_n not in ("bag", "pocket"):
        prefer_n = "bag"

    placed = None
    if prefer_n == "pocket" and cap.pocket_used + size <= cap.pocket_cap:
        if isinstance(inv.get("pocket_contents"), list):
            inv["pocket_contents"].append(q.item_id)
            placed = "pocket"
    if placed is None and cap.bag_used + size <= cap.bag_cap:
        if isinstance(inv.get("bag_contents"), list):
            inv["bag_contents"].append(q.item_id)
            placed = "bag"
    if placed is None:
        return {
            "ok": False,
            "reason": "no_capacity",
            "size": size,
            "pocket_used": cap.pocket_used,
            "pocket_cap": cap.pocket_cap,
            "bag_used": cap.bag_used,
            "bag_cap": cap.bag_cap,
        }

    eco["cash"] = cash - q.buy_price

    state.setdefault("world_notes", []).append(f"[Shop] BUY {q.item_id} price={q.buy_price} cat={q.category} to={placed}")
    return {"ok": True, "quote": q, "cash_after": int(eco["cash"]), "placed_to": placed}


def sell_item(state: dict[str, Any], item_id: str) -> dict[str, Any]:
    q = quote_item(state, item_id)
    if q is None:
        return {"ok": False, "reason": "unknown_item"}

    inv = state.get("inventory", {}) or {}
    removed = False
    for key in ("pocket_contents", "bag_contents"):
        arr = inv.get(key, [])
        if isinstance(arr, list) and any(str(x) == q.item_id for x in arr):
            inv[key] = [x for x in arr if str(x) != q.item_id]
            removed = True
            break
    if not removed:
        return {"ok": False, "reason": "not_in_inventory"}

    eco = state.setdefault("economy", {})
    cash = _clamp_int(eco.get("cash", 0), 0, 10_000_000_000, 0)
    eco["cash"] = cash + q.sell_price
    state.setdefault("world_notes", []).append(f"[Shop] SELL {q.item_id} price={q.sell_price} cat={q.category}")
    return {"ok": True, "quote": q, "cash_after": int(eco["cash"])}


def sell_item_all(state: dict[str, Any], item_id: str) -> dict[str, Any]:
    """Sell all occurrences of item_id from pocket+bag."""
    q = quote_item(state, item_id)
    if q is None:
        return {"ok": False, "reason": "unknown_item"}

    inv = state.get("inventory", {}) or {}
    total = 0
    for key in ("pocket_contents", "bag_contents"):
        arr = inv.get(key, [])
        if not isinstance(arr, list) or not arr:
            continue
        kept: list[Any] = []
        for x in arr:
            if str(x) == q.item_id:
                total += 1
            else:
                kept.append(x)
        inv[key] = kept

    if total <= 0:
        return {"ok": False, "reason": "not_in_inventory"}

    eco = state.setdefault("economy", {})
    cash = _clamp_int(eco.get("cash", 0), 0, 10_000_000_000, 0)
    gain = int(q.sell_price) * int(total)
    eco["cash"] = cash + gain
    state.setdefault("world_notes", []).append(f"[Shop] SELL_ALL {q.item_id} n={total} price={q.sell_price} total={gain} cat={q.category}")
    return {"ok": True, "quote": q, "count": int(total), "gain": int(gain), "cash_after": int(eco["cash"])}


def sell_item_n(state: dict[str, Any], item_id: str, *, n: int) -> dict[str, Any]:
    """Sell up to n occurrences of item_id from pocket+bag."""
    q = quote_item(state, item_id)
    if q is None:
        return {"ok": False, "reason": "unknown_item"}
    want = max(1, min(999, int(n or 1)))

    inv = state.get("inventory", {}) or {}
    sold = 0
    for key in ("pocket_contents", "bag_contents"):
        arr = inv.get(key, [])
        if not isinstance(arr, list) or not arr:
            continue
        kept: list[Any] = []
        for x in arr:
            if sold < want and str(x) == q.item_id:
                sold += 1
            else:
                kept.append(x)
        inv[key] = kept
        if sold >= want:
            break

    if sold <= 0:
        return {"ok": False, "reason": "not_in_inventory"}

    eco = state.setdefault("economy", {})
    cash = _clamp_int(eco.get("cash", 0), 0, 10_000_000_000, 0)
    gain = int(q.sell_price) * int(sold)
    eco["cash"] = cash + gain
    state.setdefault("world_notes", []).append(f"[Shop] SELL_N {q.item_id} n={sold}/{want} price={q.sell_price} total={gain} cat={q.category}")
    return {"ok": True, "quote": q, "count": int(sold), "gain": int(gain), "cash_after": int(eco["cash"])}

