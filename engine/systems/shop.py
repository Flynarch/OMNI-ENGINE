from __future__ import annotations

from dataclasses import dataclass
from typing import Any
import hashlib

from engine.systems.ammo import item_is_ammo, rounds_per_purchase


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


def _cleanup_weapon_registry(state: dict[str, Any], item_id: str) -> None:
    """Drop weapons[id] if the player no longer holds that item anywhere."""
    inv = state.get("inventory", {}) or {}
    if not isinstance(inv, dict):
        return
    iid = str(item_id or "").strip()
    if not iid:
        return
    held = False
    for key in ("pocket_contents", "bag_contents", "r_hand", "l_hand", "worn"):
        v = inv.get(key)
        if isinstance(v, list):
            if any(str(x) == iid for x in v):
                held = True
                break
        elif isinstance(v, str) and v.strip() == iid:
            held = True
            break
    if held:
        return
    wmap = inv.setdefault("weapons", {})
    if isinstance(wmap, dict) and iid in wmap:
        del wmap[iid]
    if str(inv.get("active_weapon_id", "") or "") == iid:
        inv["active_weapon_id"] = ""
        state.setdefault("flags", {})["weapon_jammed"] = False


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


def _district_police_presence(state: dict[str, Any]) -> int:
    try:
        p = state.get("player", {}) or {}
        loc = str(p.get("location", "") or "").strip().lower()
        did = str(p.get("district", "") or "").strip().lower()
        if not (loc and did):
            return 0
        from engine.world.districts import get_district

        d = get_district(state, loc, did)
        if isinstance(d, dict):
            return max(0, min(5, int(d.get("police_presence", 0) or 0)))
    except Exception:
        pass
    return 0


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
    if "ammo" in tags_l:
        return "weapons"
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


def _skill_level(state: dict[str, Any], key: str) -> int:
    skills = state.get("skills", {}) or {}
    if not isinstance(skills, dict):
        return 1
    row = skills.get(str(key)) if isinstance(key, str) else None
    if not isinstance(row, dict):
        return 1
    try:
        return max(1, min(20, int(row.get("level", 1) or 1)))
    except Exception:
        return 1


def _apply_player_price_mods(state: dict[str, Any], *, buy: int, sell: int) -> tuple[int, int]:
    """Apply small, bounded player-driven price modifiers (streetwise/languages)."""
    b = int(buy)
    s = int(sell)

    # Streetwise: better deals.
    lvl_sw = _skill_level(state, "streetwise")
    sw_bonus = min(0.10, max(0.0, (lvl_sw - 1) * 0.01))  # up to 10%

    # Languages: reduce outsider premium when local language isn't shared.
    outsider_premium = 0.0
    try:
        # Use explicit language facts (avoid dummy action_ctx coupling).
        from engine.core.language import _split_lang, player_language_proficiency
        from engine.world.atlas import ensure_location_profile

        loc = _get_loc_key(state)
        prof = ensure_location_profile(state, loc) if loc else {}
        local_lang = str((prof.get("language") if isinstance(prof, dict) else "") or "").strip().lower()
        local_codes = _split_lang(local_lang) if local_lang else []
        pl = player_language_proficiency(state)
        shared = False
        for code in local_codes[:3]:
            try:
                if int(pl.get(str(code).lower(), 0) or 0) >= 60:
                    shared = True
                    break
            except Exception:
                continue
        if not shared and local_codes:
            outsider_premium = 0.04  # 4% premium when you can't communicate well
            lvl_lang = _skill_level(state, "languages")
            lang_bonus = min(0.03, max(0.0, (lvl_lang - 1) * 0.01))  # up to 3%
            outsider_premium = max(0.0, outsider_premium - lang_bonus)
    except Exception:
        pass

    buy_mult = max(0.70, min(1.20, (1.0 + outsider_premium) * (1.0 - sw_bonus)))
    sell_mult = max(0.40, min(0.95, (1.0 - outsider_premium * 0.5) * (1.0 + sw_bonus * 0.5)))
    b2 = max(1, int(round(b * buy_mult)))
    s2 = max(1, int(round(s * sell_mult)))
    return (b2, s2)


def _sold_out_rate_from_scarcity(scarcity: int) -> int:
    """Deterministic sold-out probability (0..95) as function of scarcity."""
    sc = max(0, min(100, int(scarcity)))
    if sc < 70:
        return 0
    # 70 -> 40%, 80 -> 80%, 84+ -> 95% cap
    return max(0, min(95, (sc - 60) * 4))


def _is_sold_out(state: dict[str, Any], *, item_id: str, category: str, scarcity: int) -> tuple[bool, str]:
    rate = _sold_out_rate_from_scarcity(scarcity)
    # If the district doesn't have a black market, contraband weapons/ammo effectively don't exist on shelves.
    try:
        if str(category or "") == "weapons":
            if _has_district_context(state):
                sv = _district_services(state)
                if "black_market" not in sv:
                    from engine.systems.illegal_trade import _is_contraband_for_heat, _item_tags  # type: ignore

                    tags = _item_tags(state, str(item_id or ""))
                    if _is_contraband_for_heat(tags):
                        return (True, "no_black_market_access")
    except Exception:
        pass
    # In high-police districts, weapons/ammo effectively "sell out" more often (or vanish from shelves).
    try:
        if str(category or "") == "weapons":
            pp = _district_police_presence(state)
            if pp >= 4:
                rate = min(95, rate + (10 if pp == 4 else 18))
    except Exception:
        pass
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
    if tf == "ammo":
        return "ammo" in item_tags
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
        if "ammo" in item_tags:
            score += 6
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
        buy, sell = _apply_player_price_mods(state, buy=buy, sell=sell)
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
    buy, sell = _apply_player_price_mods(state, buy=buy, sell=sell)
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


def buy_item(
    state: dict[str, Any],
    item_id: str,
    *,
    prefer: str = "bag",
    delivery: str = "counter",
) -> dict[str, Any]:
    q = quote_item(state, item_id)
    if q is None:
        return {"ok": False, "reason": "unknown_item"}
    if not bool(q.available):
        return {"ok": False, "reason": "sold_out", "detail": q.sold_out_reason}

    # District-aware restrictions: high police districts may refuse contraband sales outright.
    try:
        from engine.systems.illegal_trade import _is_contraband_for_heat, _item_tags  # type: ignore

        tags = _item_tags(state, q.item_id)
        if _is_contraband_for_heat(tags):
            p = state.get("player", {}) or {}
            loc = str(p.get("location", "") or "").strip().lower()
            did = str(p.get("district", "") or "").strip().lower()
            if loc and did:
                from engine.world.districts import get_district

                d = get_district(state, loc, did)
                if isinstance(d, dict):
                    pp = int(d.get("police_presence", 0) or 0)
                    if pp >= 5:
                        return {"ok": False, "reason": "district_refuses_contraband", "detail": f"police_presence={pp}"}
    except Exception:
        pass
    eco = state.setdefault("economy", {})
    cash = _clamp_int(eco.get("cash", 0), 0, 10_000_000_000, 0)
    if cash < q.buy_price:
        return {"ok": False, "reason": "not_enough_cash", "need": q.buy_price, "cash": cash}

    delivery_n = str(delivery or "counter").strip().lower().replace("-", "_")
    if delivery_n in ("drop", "dead", "dead_drop", "deaddrop"):
        delivery_n = "dead_drop"
    elif delivery_n in ("courier", "meet", "courier_meet", "handoff"):
        delivery_n = "courier"
    else:
        delivery_n = "counter"

    # For contraband, allow safer delivery methods that delay the actual handoff.
    try:
        from engine.systems.illegal_trade import _is_contraband_for_heat, _item_tags  # type: ignore

        tags = _item_tags(state, q.item_id)
        if _is_contraband_for_heat(tags) and delivery_n in ("dead_drop", "courier"):
            return _schedule_delivery(state, q, prefer=prefer, delivery=delivery_n)
    except Exception:
        pass

    if item_is_ammo(state, q.item_id):
        inv = state.setdefault("inventory", {})
        iq = inv.setdefault("item_quantities", {})
        if not isinstance(iq, dict):
            iq = {}
            inv["item_quantities"] = iq
        rpb = rounds_per_purchase(state, q.item_id)
        iq[q.item_id] = int(iq.get(q.item_id, 0) or 0) + int(rpb)
        eco["cash"] = cash - q.buy_price
        try:
            from engine.systems.illegal_trade import apply_contraband_acquire_pressure

            apply_contraband_acquire_pressure(state, q.item_id, via="shop")
        except Exception:
            pass
        state.setdefault("world_notes", []).append(
            f"[Shop] BUY_AMMO {q.item_id} price={q.buy_price} rounds=+{rpb} reserve={iq.get(q.item_id)}"
        )
        _maybe_schedule_undercover_sting(state, bought_item_id=q.item_id)
        return {"ok": True, "quote": q, "cash_after": int(eco["cash"]), "placed_to": "reserve", "rounds_added": int(rpb)}

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

    try:
        from engine.systems.weapon_kit import ensure_weapon_for_item

        ensure_weapon_for_item(state, q.item_id, source="buy")
    except Exception:
        pass

    try:
        from engine.systems.illegal_trade import apply_contraband_acquire_pressure

        apply_contraband_acquire_pressure(state, q.item_id, via="shop")
    except Exception:
        pass

    state.setdefault("world_notes", []).append(f"[Shop] BUY {q.item_id} price={q.buy_price} cat={q.category} to={placed}")
    _maybe_schedule_undercover_sting(state, bought_item_id=q.item_id)
    return {"ok": True, "quote": q, "cash_after": int(eco["cash"]), "placed_to": placed}


def _schedule_delivery(state: dict[str, Any], q: ShopQuote, *, prefer: str, delivery: str) -> dict[str, Any]:
    """Take payment now, then spawn item into world.nearby_items later (pickup required)."""
    delivery = str(delivery or "dead_drop").strip().lower()
    if delivery not in ("dead_drop", "courier"):
        delivery = "dead_drop"

    eco = state.setdefault("economy", {})
    cash = _clamp_int(eco.get("cash", 0), 0, 10_000_000_000, 0)

    pp = _district_police_presence(state)
    loc_tags = _get_location_tags(state)
    fee = 0
    delay = 25
    sting_bias = "lower"
    if delivery == "dead_drop":
        fee = 25 + (15 if pp >= 4 else 0)
        delay = 35 + (10 if "surveillance_high" in loc_tags else 0)
        sting_bias = "lower"
    else:
        # courier meet is faster but riskier (eyes-on you)
        fee = 60 + (20 if pp >= 4 else 0)
        delay = 15 + (5 if pp >= 4 else 0)
        sting_bias = "higher"

    total = int(q.buy_price) + int(fee)
    if cash < total:
        return {"ok": False, "reason": "not_enough_cash", "need": total, "cash": cash, "detail": f"delivery_fee={fee}"}
    eco["cash"] = cash - total

    meta = state.get("meta", {}) or {}
    day = int(meta.get("day", 1) or 1)
    tmin = int(meta.get("time_min", 0) or 0)
    loc = _get_loc_key(state)
    did = ""
    try:
        did = str((state.get("player", {}) or {}).get("district", "") or "").strip().lower()
    except Exception:
        did = ""

    # Choose a target drop district (sometimes different from current).
    drop_district = did
    try:
        if _has_district_context(state):
            from engine.world.districts import list_districts

            all_d = list_districts(state, loc)
            bm = []
            for d in all_d:
                if not isinstance(d, dict):
                    continue
                sv = d.get("services", []) or []
                if isinstance(sv, list) and any(str(x).strip().lower() == "black_market" for x in sv):
                    bm.append(str(d.get("id", "") or "").strip().lower())
            bm = [x for x in bm if x]
            if bm:
                seed = str(meta.get("world_seed", "") or meta.get("seed_pack", "") or "").strip()
                h2 = hashlib.md5(f"{seed}|{day}|{tmin}|{loc}|{q.item_id}|drop_pick".encode("utf-8", errors="ignore")).hexdigest()
                r2 = int(h2[:8], 16) % 100
                # 40%: move the drop to another black-market district.
                if r2 < 40 and len(bm) >= 2:
                    alt = [x for x in bm if x != did] or bm
                    drop_district = alt[r2 % len(alt)]
                else:
                    drop_district = did if did else bm[r2 % len(bm)]
    except Exception:
        drop_district = did

    # Expiry: if you don't pick it up in time, it's gone.
    expires_in = 90 if delivery == "dead_drop" else 45
    expire_day = day
    expire_time = min(1439, tmin + int(delay) + int(expires_in))

    delivery_id = hashlib.md5(f"{loc}|{day}|{tmin}|{q.item_id}|{delivery}".encode("utf-8", errors="ignore")).hexdigest()[:10]

    state.setdefault("pending_events", []).append(
        {
            "event_type": "delivery_drop",
            "title": "Pengiriman — Paket Tiba",
            "due_day": day,
            "due_time": min(1439, tmin + int(delay)),
            "triggered": False,
            "payload": {
                "delivery_id": delivery_id,
                "item_id": q.item_id,
                "item_name": q.name,
                "category": q.category,
                "delivery": delivery,
                "delivery_fee": int(fee),
                "prefer": str(prefer or "bag"),
                "location": loc,
                "drop_district": drop_district,
                "district_police_presence": int(pp),
                "sting_bias": sting_bias,
                "paid_total": int(total),
                "expire_day": int(expire_day),
                "expire_time": int(expire_time),
            },
        }
    )
    state.setdefault("pending_events", []).append(
        {
            "event_type": "delivery_expire",
            "title": "Pengiriman — Paket Hilang",
            "due_day": int(expire_day),
            "due_time": int(expire_time),
            "triggered": False,
            "payload": {
                "delivery_id": delivery_id,
                "item_id": q.item_id,
                "item_name": q.name,
                "delivery": delivery,
                "location": loc,
                "drop_district": drop_district,
            },
        }
    )

    # Paper trail / marked bills: courier handoffs create a delayed investigative ping.
    # This is not a difficulty slider — it reflects real-world leakage (cameras, marked cash, informants).
    if delivery == "courier":
        try:
            seed = str(meta.get("world_seed", "") or meta.get("seed_pack", "") or "").strip()
        except Exception:
            seed = "seed"
        # Delay 2–6 hours deterministically.
        h3 = hashlib.md5(f"{seed}|{delivery_id}|paper_trail".encode("utf-8", errors="ignore")).hexdigest()
        mins = 120 + (int(h3[:8], 16) % 241)  # 120..360
        due_day2 = day
        due_time2 = int(tmin) + int(mins)
        if due_time2 >= 1440:
            due_day2 += due_time2 // 1440
            due_time2 = due_time2 % 1440
        # Suspicion: depends on trace + police presence.
        try:
            tp = int((state.get("trace", {}) or {}).get("trace_pct", 0) or 0)
        except Exception:
            tp = 0
        sus = 45 + (tp // 20) * 8 + (8 if pp >= 4 else 0)
        sus = max(30, min(95, int(sus)))
        state.setdefault("pending_events", []).append(
            {
                "event_type": "paper_trail_ping",
                "title": "Jejak Transaksi — Investigasi",
                "due_day": int(due_day2),
                "due_time": int(due_time2),
                "triggered": False,
                "payload": {
                    "origin_location": str(loc).strip().lower(),
                    "delivery_id": delivery_id,
                    "delivery": delivery,
                    "item_id": q.item_id,
                    "suspicion": int(sus),
                    "affiliation": "police",
                    "reporter": "CCTV / serial cash trail",
                },
            }
        )

    state.setdefault("world_notes", []).append(
        f"[Delivery] scheduled item={q.item_id} via={delivery} fee={fee} due+{delay}m drop_district={drop_district} exp+{delay+expires_in}m"
    )
    return {
        "ok": True,
        "quote": q,
        "cash_after": int(eco["cash"]),
        "placed_to": "delivery_pending",
        "delivery": delivery,
        "delivery_fee": int(fee),
        "delivery_due_in_min": int(delay),
        "pickup_required": True,
        "drop_district": str(drop_district or ""),
        "expires_in_min": int(expires_in),
    }


def _district_services(state: dict[str, Any]) -> list[str]:
    try:
        p = state.get("player", {}) or {}
        loc = str(p.get("location", "") or "").strip().lower()
        did = str(p.get("district", "") or "").strip().lower()
        if not (loc and did):
            return []
        from engine.world.districts import get_district

        d = get_district(state, loc, did)
        if isinstance(d, dict):
            sv = d.get("services", []) or []
            if isinstance(sv, list):
                return [str(x).strip().lower() for x in sv if isinstance(x, str) and str(x).strip()]
    except Exception:
        pass
    return []


def _has_district_context(state: dict[str, Any]) -> bool:
    try:
        p = state.get("player", {}) or {}
        loc = str(p.get("location", "") or "").strip().lower()
        did = str(p.get("district", "") or "").strip().lower()
        return bool(loc and did)
    except Exception:
        return False


def _maybe_schedule_undercover_sting(state: dict[str, Any], *, bought_item_id: str) -> None:
    """After some contraband buys, schedule an undercover sting that escalates to a fast police stop."""
    iid = str(bought_item_id or "").strip()
    if not iid:
        return

    # Only meaningful where black markets exist.
    services = _district_services(state)
    if "black_market" not in services:
        return

    try:
        from engine.systems.illegal_trade import _is_contraband_for_heat, _item_tags  # type: ignore

        tags = _item_tags(state, iid)
        if not _is_contraband_for_heat(tags):
            return
    except Exception:
        return

    # Avoid duplicates.
    pending = state.get("pending_events", []) or []
    if isinstance(pending, list):
        for ev in pending:
            if isinstance(ev, dict) and str(ev.get("event_type", "") or "") == "undercover_sting" and not bool(ev.get("triggered")):
                return

    pp = _district_police_presence(state)
    loc_tags = _get_location_tags(state)
    ca_lvl = 0
    try:
        loc = _get_loc_key(state)
        slot = ((state.get("world", {}) or {}).get("locations", {}) or {}).get(loc)
        ca = slot.get("cyber_alert") if isinstance(slot, dict) else None
        if isinstance(ca, dict):
            ca_lvl = int(ca.get("level", 0) or 0)
    except Exception:
        ca_lvl = 0

    base = 4
    if pp >= 4:
        base += 10
    elif pp == 3:
        base += 6
    if "surveillance_high" in loc_tags:
        base += 8
    if ca_lvl >= 60:
        base += 6

    # Weapon/ammo buys are more likely to be stung.
    try:
        from engine.systems.illegal_trade import _item_tags as _itags  # type: ignore

        t = _itags(state, iid)
        if "firearm" in t or "ammo" in t:
            base += 10
    except Exception:
        pass

    chance = max(0, min(45, int(base)))
    if chance <= 0:
        return

    meta = state.get("meta", {}) or {}
    seed = str(meta.get("world_seed", "") or meta.get("seed_pack", "") or "").strip()
    day = int(meta.get("day", 1) or 1) if isinstance(meta, dict) else 1
    tmin = int(meta.get("time_min", 0) or 0) if isinstance(meta, dict) else 0
    loc = _get_loc_key(state)
    h = hashlib.md5(f"{seed}|{day}|{tmin}|{loc}|{iid}|sting".encode("utf-8", errors="ignore")).hexdigest()
    r = int(h[:8], 16) % 100
    if r >= chance:
        return

    state.setdefault("pending_events", []).append(
        {
            "event_type": "undercover_sting",
            "title": "Lapak Palsu — Sting Operasi",
            "due_day": day,
            "due_time": min(1439, tmin + 1),
            "triggered": False,
            "payload": {
                "bought_item_id": iid,
                "location": loc,
                "district_police_presence": pp,
                "chance": chance,
            },
        }
    )
    state.setdefault("world_notes", []).append(f"[Sting] undercover_sting scheduled item={iid} chance={chance}%")


def sell_item(state: dict[str, Any], item_id: str) -> dict[str, Any]:
    q = quote_item(state, item_id)
    if q is None:
        return {"ok": False, "reason": "unknown_item"}

    inv = state.get("inventory", {}) or {}
    iq = inv.get("item_quantities") if isinstance(inv.get("item_quantities"), dict) else None
    if item_is_ammo(state, q.item_id) and isinstance(iq, dict):
        rpb = rounds_per_purchase(state, q.item_id)
        have = int(iq.get(q.item_id, 0) or 0)
        if have >= rpb:
            iq[q.item_id] = have - rpb
            eco = state.setdefault("economy", {})
            cash = _clamp_int(eco.get("cash", 0), 0, 10_000_000_000, 0)
            eco["cash"] = cash + int(q.sell_price)
            state.setdefault("world_notes", []).append(f"[Shop] SELL_AMMO {q.item_id} rounds=-{rpb} price={q.sell_price} cat={q.category}")
            return {"ok": True, "quote": q, "cash_after": int(eco["cash"])}

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
    _cleanup_weapon_registry(state, q.item_id)
    return {"ok": True, "quote": q, "cash_after": int(eco["cash"])}


def sell_item_all(state: dict[str, Any], item_id: str) -> dict[str, Any]:
    """Sell all occurrences of item_id from pocket+bag."""
    q = quote_item(state, item_id)
    if q is None:
        return {"ok": False, "reason": "unknown_item"}

    inv = state.get("inventory", {}) or {}
    iq = inv.get("item_quantities") if isinstance(inv.get("item_quantities"), dict) else None
    if item_is_ammo(state, q.item_id) and isinstance(iq, dict):
        rpb = rounds_per_purchase(state, q.item_id)
        have = int(iq.get(q.item_id, 0) or 0)
        boxes = have // rpb
        if boxes > 0:
            iq[q.item_id] = have - boxes * rpb
            eco = state.setdefault("economy", {})
            cash = _clamp_int(eco.get("cash", 0), 0, 10_000_000_000, 0)
            gain = int(q.sell_price) * int(boxes)
            eco["cash"] = cash + gain
            state.setdefault("world_notes", []).append(
                f"[Shop] SELL_ALL_AMMO {q.item_id} n={boxes} price={q.sell_price} total={gain} cat={q.category}"
            )
            return {"ok": True, "quote": q, "count": int(boxes), "gain": int(gain), "cash_after": int(eco["cash"])}

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
    _cleanup_weapon_registry(state, q.item_id)
    return {"ok": True, "quote": q, "count": int(total), "gain": int(gain), "cash_after": int(eco["cash"])}


def sell_item_n(state: dict[str, Any], item_id: str, *, n: int) -> dict[str, Any]:
    """Sell up to n occurrences of item_id from pocket+bag."""
    q = quote_item(state, item_id)
    if q is None:
        return {"ok": False, "reason": "unknown_item"}
    want = max(1, min(999, int(n or 1)))

    inv = state.get("inventory", {}) or {}
    iq = inv.get("item_quantities") if isinstance(inv.get("item_quantities"), dict) else None
    if item_is_ammo(state, q.item_id) and isinstance(iq, dict):
        rpb = rounds_per_purchase(state, q.item_id)
        have = int(iq.get(q.item_id, 0) or 0)
        max_boxes = have // rpb
        boxes = min(want, max_boxes)
        if boxes > 0:
            iq[q.item_id] = have - boxes * rpb
            eco = state.setdefault("economy", {})
            cash = _clamp_int(eco.get("cash", 0), 0, 10_000_000_000, 0)
            gain = int(q.sell_price) * int(boxes)
            eco["cash"] = cash + gain
            state.setdefault("world_notes", []).append(
                f"[Shop] SELL_N_AMMO {q.item_id} n={boxes}/{want} price={q.sell_price} total={gain} cat={q.category}"
            )
            return {"ok": True, "quote": q, "count": int(boxes), "gain": int(gain), "cash_after": int(eco["cash"])}

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
    _cleanup_weapon_registry(state, q.item_id)
    return {"ok": True, "quote": q, "count": int(sold), "gain": int(gain), "cash_after": int(eco["cash"])}

