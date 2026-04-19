"""W2-10 Property & assets: apartments, houses, small businesses, city-priced vehicles.

All monetary effects for maintenance and business passive income run from Python daily
economy hooks — never trust action_ctx for income (anti custom-intent exploit).
"""

from __future__ import annotations

from engine.core.error_taxonomy import log_swallowed_exception
from engine.npc.relationship import get_top_relationships
from engine.systems.occupation import ensure_career
from engine.systems.vehicles import VEHICLE_TYPES, buy_vehicle
import hashlib
from typing import Any

from engine.world.atlas import get_city_stats_for_travel

_ASSET_KINDS_RESIDENTIAL = frozenset({"apartment", "house"})
_ASSET_KINDS = frozenset({"apartment", "house", "small_business"})


def _norm_city(s: str) -> str:
    return str(s or "").strip().lower()


def get_city_property_stats(state: dict[str, Any], city: str) -> dict[str, float]:
    return get_city_stats_for_travel(state, _norm_city(city))


def quote_apartment_buy_usd(state: dict[str, Any], city: str) -> int:
    st = get_city_property_stats(state, city)
    try:
        return max(1000, int(float(st.get("avg_apartment_price_usd", 45000) or 45000)))
    except Exception as _omni_sw_30:
        log_swallowed_exception('engine/systems/property.py:30', _omni_sw_30)
        return 45000


def quote_house_buy_usd(state: dict[str, Any], city: str) -> int:
    st = get_city_property_stats(state, city)
    try:
        return max(2000, int(float(st.get("avg_house_price_usd", 120000) or 120000)))
    except Exception as _omni_sw_38:
        log_swallowed_exception('engine/systems/property.py:38', _omni_sw_38)
        return 120000


def quote_rent_daily_usd(state: dict[str, Any], city: str) -> int:
    st = get_city_property_stats(state, city)
    try:
        rm = float(st.get("avg_rent_monthly_usd", 800) or 800)
    except Exception as _omni_sw_46:
        log_swallowed_exception('engine/systems/property.py:46', _omni_sw_46)
        rm = 800.0
    return max(3, int(rm / 30.0))


def quote_vehicle_price_usd(state: dict[str, Any], city: str, vehicle_id: str) -> int:
    """Scale catalog vehicle price by city's avg_car_price_usd vs global baseline (car_standard=2000)."""
    vid = str(vehicle_id or "").strip().lower()
    if vid not in VEHICLE_TYPES or vid == "taxi":
        return 0
    st = get_city_property_stats(state, city)
    try:
        avg_car = float(st.get("avg_car_price_usd", 12000) or 12000)
    except Exception as _omni_sw_61:
        log_swallowed_exception('engine/systems/property.py:61', _omni_sw_61)
        avg_car = 12000.0
    base_ref = 2000.0
    base_prices: dict[str, float] = {
        "bicycle": 50.0,
        "motorcycle": 500.0,
        "car_standard": 2000.0,
        "car_sports": 10000.0,
        "car_van": 3000.0,
        "boat_small": 5000.0,
        "boat_speed": 15000.0,
        "helicopter": 100000.0,
    }
    cat = float(base_prices.get(vid, 1000.0))
    if vid == "bicycle":
        return max(25, int(avg_car * 0.028))
    return max(50, int(avg_car * (cat / base_ref)))


def ensure_player_assets(state: dict[str, Any]) -> dict[str, Any]:
    p = state.setdefault("player", {})
    if not isinstance(p, dict):
        p = {}
        state["player"] = p
    a = p.get("assets")
    if not isinstance(a, dict):
        a = {"version": 1, "entries": []}
        p["assets"] = a
    a.setdefault("version", 1)
    ent = a.setdefault("entries", [])
    if not isinstance(ent, list):
        ent = []
        a["entries"] = ent
    return a


def _entries(state: dict[str, Any]) -> list[dict[str, Any]]:
    a = ensure_player_assets(state)
    e = a.get("entries", [])
    return e if isinstance(e, list) else []


def list_asset_entries(state: dict[str, Any]) -> list[dict[str, Any]]:
    """Public read-only view of owned/rented property rows."""
    return [x for x in _entries(state) if isinstance(x, dict)]


def has_residential_in_city(state: dict[str, Any], city: str) -> bool:
    c = _norm_city(city)
    for raw in _entries(state):
        if not isinstance(raw, dict):
            continue
        if str(raw.get("kind", "") or "") in _ASSET_KINDS_RESIDENTIAL and _norm_city(str(raw.get("city", "") or "")) == c:
            return True
    return False


def has_business_in_city(state: dict[str, Any], city: str) -> bool:
    c = _norm_city(city)
    for raw in _entries(state):
        if not isinstance(raw, dict):
            continue
        if str(raw.get("kind", "") or "") == "small_business" and _norm_city(str(raw.get("city", "") or "")) == c:
            return True
    return False


def _new_asset_id(kind: str, city: str, state: dict[str, Any]) -> str:
    meta = state.get("meta", {}) or {}
    d = int(meta.get("day", 1) or 1)
    t = int(meta.get("turn", 0) or 0)
    h = hashlib.md5(f"{kind}|{city}|{d}|{t}|w210".encode("utf-8", errors="ignore")).hexdigest()[:10]
    return f"{kind[:3]}_{_norm_city(city)[:16]}_{h}"


def _daily_maintenance_owned(purchase_price: int, col: float) -> int:
    try:
        pp = int(purchase_price)
    except Exception as _omni_sw_139:
        log_swallowed_exception('engine/systems/property.py:139', _omni_sw_139)
        pp = 0
    try:
        c = float(col or 50.0)
    except Exception as _omni_sw_143:
        log_swallowed_exception('engine/systems/property.py:143', _omni_sw_143)
        c = 50.0
    return max(5, min(900, int(pp * 0.0001 + c * 0.32)))


def buy_apartment(state: dict[str, Any], city: str, *, rental: bool = False) -> dict[str, Any]:
    c = _norm_city(city)
    if not c:
        return {"ok": False, "reason": "bad_city"}
    if str((state.get("player", {}) or {}).get("location", "") or "").strip().lower() != c:
        return {"ok": False, "reason": "must_be_in_city", "city": c}
    if has_residential_in_city(state, c):
        return {"ok": False, "reason": "duplicate_residential", "city": c}
    eco = state.setdefault("economy", {})
    stats = get_city_property_stats(state, c)
    try:
        col = float(stats.get("cost_of_living_index", 50) or 50)
    except Exception as _omni_sw_160:
        log_swallowed_exception('engine/systems/property.py:160', _omni_sw_160)
        col = 50.0
    if rental:
        # First month + small deposit (simplified as upfront + daily rent tracked).
        rent_d = quote_rent_daily_usd(state, c)
        upfront = int(rent_d * 10)
        cash = int(eco.get("cash", 0) or 0)
        if cash < upfront:
            return {"ok": False, "reason": "cash", "need": upfront, "have": cash}
        eco["cash"] = cash - upfront
        aid = _new_asset_id("apartment", c, state)
        meta = state.get("meta", {}) or {}
        day = int(meta.get("day", 1) or 1)
        _entries(state).append(
            {
                "asset_id": aid,
                "kind": "apartment",
                "city": c,
                "rental": True,
                "rent_daily_usd": int(rent_d),
                "deposit_paid_usd": int(upfront),
                "acquired_day": day,
                "sabotage_until_day": 0,
                "sabotage_income_factor": 1.0,
            }
        )
        state.setdefault("world_notes", []).append(f"[Property] Sewa apartemen di {c} (deposit+awal).")
        return {"ok": True, "asset_id": aid, "upfront": upfront, "rent_daily_usd": rent_d}
    price = quote_apartment_buy_usd(state, c)
    cash = int(eco.get("cash", 0) or 0)
    if cash < price:
        return {"ok": False, "reason": "cash", "need": price, "have": cash}
    eco["cash"] = cash - price
    aid = _new_asset_id("apartment", c, state)
    meta = state.get("meta", {}) or {}
    day = int(meta.get("day", 1) or 1)
    maint = _daily_maintenance_owned(price, col)
    _entries(state).append(
        {
            "asset_id": aid,
            "kind": "apartment",
            "city": c,
            "rental": False,
            "purchase_price_usd": int(price),
            "maintenance_daily_usd": int(maint),
            "acquired_day": day,
            "sabotage_until_day": 0,
            "sabotage_income_factor": 1.0,
        }
    )
    state.setdefault("world_notes", []).append(f"[Property] Beli apartemen di {c} (${price}).")
    return {"ok": True, "asset_id": aid, "price": price, "maintenance_daily_usd": maint}


def buy_house(state: dict[str, Any], city: str) -> dict[str, Any]:
    c = _norm_city(city)
    if not c:
        return {"ok": False, "reason": "bad_city"}
    if str((state.get("player", {}) or {}).get("location", "") or "").strip().lower() != c:
        return {"ok": False, "reason": "must_be_in_city", "city": c}
    if has_residential_in_city(state, c):
        return {"ok": False, "reason": "duplicate_residential", "city": c}
    price = quote_house_buy_usd(state, c)
    eco = state.setdefault("economy", {})
    cash = int(eco.get("cash", 0) or 0)
    if cash < price:
        return {"ok": False, "reason": "cash", "need": price, "have": cash}
    eco["cash"] = cash - price
    stats = get_city_property_stats(state, c)
    try:
        col = float(stats.get("cost_of_living_index", 50) or 50)
    except Exception as _omni_sw_231:
        log_swallowed_exception('engine/systems/property.py:231', _omni_sw_231)
        col = 50.0
    maint = _daily_maintenance_owned(price, col)
    aid = _new_asset_id("house", c, state)
    meta = state.get("meta", {}) or {}
    day = int(meta.get("day", 1) or 1)
    _entries(state).append(
        {
            "asset_id": aid,
            "kind": "house",
            "city": c,
            "rental": False,
            "purchase_price_usd": int(price),
            "maintenance_daily_usd": int(maint),
            "acquired_day": day,
            "sabotage_until_day": 0,
            "sabotage_income_factor": 1.0,
        }
    )
    state.setdefault("world_notes", []).append(f"[Property] Beli rumah di {c} (${price}).")
    return {"ok": True, "asset_id": aid, "price": price, "maintenance_daily_usd": maint}


def buy_small_business(state: dict[str, Any], city: str) -> dict[str, Any]:
    c = _norm_city(city)
    if not c:
        return {"ok": False, "reason": "bad_city"}
    if str((state.get("player", {}) or {}).get("location", "") or "").strip().lower() != c:
        return {"ok": False, "reason": "must_be_in_city", "city": c}
    if has_business_in_city(state, c):
        return {"ok": False, "reason": "duplicate_business", "city": c}
    st = get_city_property_stats(state, c)
    try:
        monthly_rev = float(st.get("avg_small_business_revenue_monthly_usd", 8000) or 8000)
    except Exception as _omni_sw_265:
        log_swallowed_exception('engine/systems/property.py:265', _omni_sw_265)
        monthly_rev = 8000.0
    try:
        col = float(st.get("cost_of_living_index", 50) or 50)
    except Exception as _omni_sw_269:
        log_swallowed_exception('engine/systems/property.py:269', _omni_sw_269)
        col = 50.0
    # Stake ~ 2 months gross benchmark (deterministic).
    price = max(3000, int(monthly_rev * 2.0 + col * 120.0))
    eco = state.setdefault("economy", {})
    cash = int(eco.get("cash", 0) or 0)
    if cash < price:
        return {"ok": False, "reason": "cash", "need": price, "have": cash}
    eco["cash"] = cash - price
    maint = max(8, min(700, int(price * 0.00008 + col * 0.28)))
    aid = _new_asset_id("biz", c, state)
    meta = state.get("meta", {}) or {}
    day = int(meta.get("day", 1) or 1)
    _entries(state).append(
        {
            "asset_id": aid,
            "kind": "small_business",
            "city": c,
            "rental": False,
            "purchase_price_usd": int(price),
            "maintenance_daily_usd": int(maint),
            "acquired_day": day,
            "sabotage_until_day": 0,
            "sabotage_income_factor": 1.0,
        }
    )
    state.setdefault("world_notes", []).append(f"[Property] Akuisisi bisnis kecil di {c} (${price}).")
    return {"ok": True, "asset_id": aid, "price": price, "maintenance_daily_usd": maint}


def sell_asset(state: dict[str, Any], asset_id: str) -> dict[str, Any]:
    aid = str(asset_id or "").strip()
    if not aid:
        return {"ok": False, "reason": "bad_id"}
    lst = _entries(state)
    idx = None
    for i, raw in enumerate(lst):
        if isinstance(raw, dict) and str(raw.get("asset_id", "") or "") == aid:
            idx = i
            break
    if idx is None:
        return {"ok": False, "reason": "not_found"}
    a = lst[idx]
    if bool(a.get("rental")):
        lst.pop(idx)
        state.setdefault("world_notes", []).append(f"[Property] Sewa dihentikan ({aid}).")
        return {"ok": True, "asset_id": aid, "refund": 0}
    try:
        pp = int(a.get("purchase_price_usd", 0) or 0)
    except Exception as _omni_sw_318:
        log_swallowed_exception('engine/systems/property.py:318', _omni_sw_318)
        pp = 0
    refund = max(0, int(pp * 0.62))
    eco = state.setdefault("economy", {})
    eco["cash"] = int(eco.get("cash", 0) or 0) + refund
    lst.pop(idx)
    state.setdefault("world_notes", []).append(f"[Property] Jual aset {aid} (+${refund}).")
    return {"ok": True, "asset_id": aid, "refund": refund}


def _bisnis_career_multiplier(state: dict[str, Any]) -> float:
    try:
        ensure_career(state)
        c = (state.get("player", {}) or {}).get("career", {}) or {}
        if not isinstance(c, dict):
            return 1.0
        row = (c.get("tracks", {}) or {}).get("bisnis", {}) or {}
        if not isinstance(row, dict):
            return 1.0
        lvl = int(row.get("level", 0) or 0)
        return 1.0 + 0.045 * max(0, min(lvl, 6))
    except Exception as _omni_sw_341:
        log_swallowed_exception('engine/systems/property.py:341', _omni_sw_341)
        return 1.0


def _business_partner_multiplier(state: dict[str, Any]) -> float:
    try:
        n = sum(
            1
            for _nm, rel in get_top_relationships(state, limit=24)
            if str((rel or {}).get("type", "") or "").lower() == "business_partner"
        )
        return 1.0 + 0.028 * max(0, min(n, 8))
    except Exception as _omni_sw_355:
        log_swallowed_exception('engine/systems/property.py:355', _omni_sw_355)
        return 1.0


def _business_daily_gross_for_asset(state: dict[str, Any], asset: dict[str, Any], day: int) -> int:
    c = _norm_city(str(asset.get("city", "") or ""))
    st = get_city_property_stats(state, c)
    try:
        monthly = float(st.get("avg_small_business_revenue_monthly_usd", 5000) or 5000)
    except Exception as _omni_sw_364:
        log_swallowed_exception('engine/systems/property.py:364', _omni_sw_364)
        monthly = 5000.0
    daily = monthly / 22.0
    daily *= _bisnis_career_multiplier(state)
    daily *= _business_partner_multiplier(state)
    try:
        sud = int(asset.get("sabotage_until_day", 0) or 0)
    except Exception as _omni_sw_371:
        log_swallowed_exception('engine/systems/property.py:371', _omni_sw_371)
        sud = 0
    if sud >= day:
        try:
            fac = float(asset.get("sabotage_income_factor", 0.5) or 0.5)
        except Exception as _omni_sw_376:
            log_swallowed_exception('engine/systems/property.py:376', _omni_sw_376)
            fac = 0.5
        daily *= max(0.08, min(1.0, fac))
    return int(max(0, daily))


def clear_expired_sabotage(state: dict[str, Any], day: int) -> None:
    for raw in _entries(state):
        if not isinstance(raw, dict):
            continue
        try:
            sud = int(raw.get("sabotage_until_day", 0) or 0)
        except Exception as _omni_sw_388:
            log_swallowed_exception('engine/systems/property.py:388', _omni_sw_388)
            sud = 0
        if day > sud:
            raw["sabotage_until_day"] = 0
            raw["sabotage_income_factor"] = 1.0
            raw["sabotage_maintenance_mult"] = 1.0


def sabotage_assets_in_city(
    state: dict[str, Any],
    city: str,
    *,
    extra_days: int = 4,
    income_factor: float = 0.48,
    maintenance_bump: float = 1.35,
) -> dict[str, Any]:
    """Nemesis / enemy sabotage: hurts business income and raises upkeep for assets in a city."""
    c = _norm_city(city)
    meta = state.get("meta", {}) or {}
    try:
        day = int(meta.get("day", 1) or 1)
    except Exception as _omni_sw_409:
        log_swallowed_exception('engine/systems/property.py:409', _omni_sw_409)
        day = 1
    until = day + max(1, int(extra_days))
    n = 0
    for raw in _entries(state):
        if not isinstance(raw, dict):
            continue
        if _norm_city(str(raw.get("city", "") or "")) != c:
            continue
        raw["sabotage_until_day"] = max(int(raw.get("sabotage_until_day", 0) or 0), until)
        raw["sabotage_income_factor"] = min(float(raw.get("sabotage_income_factor", 1.0) or 1.0), float(income_factor))
        raw["sabotage_maintenance_mult"] = max(float(raw.get("sabotage_maintenance_mult", 1.0) or 1.0), float(maintenance_bump))
        n += 1
    if n:
        state.setdefault("world_notes", []).append(f"[Property] Sabotase aset di {c} ({n} entri) — pendapatan bisnis tertekan.")
    return {"ok": True, "affected": n, "until_day": until}


def process_property_daily_economy(state: dict[str, Any]) -> None:
    """Daily: maintenance/rent out; business passive income in (ignores action_ctx entirely)."""
    meta = state.get("meta", {}) or {}
    try:
        day = int(meta.get("day", 1) or 1)
    except Exception as _omni_sw_432:
        log_swallowed_exception('engine/systems/property.py:432', _omni_sw_432)
        day = 1
    clear_expired_sabotage(state, day)
    eco = state.setdefault("economy", {})
    cash = int(eco.get("cash", 0) or 0)
    total_cost = 0
    total_inc = 0
    for raw in _entries(state):
        if not isinstance(raw, dict):
            continue
        kind = str(raw.get("kind", "") or "")
        if bool(raw.get("rental")) and kind == "apartment":
            try:
                rd = int(raw.get("rent_daily_usd", 0) or 0)
            except Exception as _omni_sw_446:
                log_swallowed_exception('engine/systems/property.py:446', _omni_sw_446)
                rd = 0
            rd = max(0, rd)
            mult = float(raw.get("sabotage_maintenance_mult", 1.0) or 1.0)
            cost = int(rd * max(1.0, mult))
        elif kind in _ASSET_KINDS and not bool(raw.get("rental")):
            try:
                base_m = int(raw.get("maintenance_daily_usd", 0) or 0)
            except Exception as _omni_sw_454:
                log_swallowed_exception('engine/systems/property.py:454', _omni_sw_454)
                base_m = 0
            mult = float(raw.get("sabotage_maintenance_mult", 1.0) or 1.0)
            cost = int(max(0, base_m) * max(1.0, mult))
        else:
            cost = 0
        if cost > 0:
            pay = min(cash, cost)
            cash -= pay
            total_cost += pay
            if pay < cost:
                state.setdefault("world_notes", []).append(
                    f"[Property] Biaya aset {raw.get('asset_id')} terpotong sebagian (${pay}/{cost}); tunggakan menumpuk."
                )
        if kind == "small_business":
            total_inc += _business_daily_gross_for_asset(state, raw, day)
    eco["cash"] = cash + total_inc
    if total_cost > 0:
        state.setdefault("world_notes", []).append(f"[Property] Pemeliharaan/sewa harian total -${total_cost}.")
    if total_inc > 0:
        state.setdefault("world_notes", []).append(f"[Property] Pendapatan bisnis pasif +${total_inc}.")


def seize_owned_vehicles_on_arrest(state: dict[str, Any]) -> None:
    """Police custody: remove registered vehicles (W2-10)."""
    inv = state.setdefault("inventory", {})
    if not isinstance(inv, dict):
        return
    vs = inv.get("vehicles")
    if isinstance(vs, dict) and vs:
        inv["vehicles"] = {}
        inv["active_vehicle_id"] = ""
        state.setdefault("world_notes", []).append("[Property] Kendaraan disita oleh otoritas.")


def fmt_property_engine_brief(state: dict[str, Any]) -> str:
    ensure_player_assets(state)
    n = len(_entries(state))
    loc = str((state.get("player", {}) or {}).get("location", "") or "").strip().lower()
    if not loc:
        return f"assets={n}"
    apt = quote_apartment_buy_usd(state, loc)
    hs = quote_house_buy_usd(state, loc)
    return f"assets={n} loc={loc} quote_apt_usd={apt} quote_house_usd={hs}"


def buy_vehicle_city_priced(state: dict[str, Any], vehicle_id: str) -> dict[str, Any]:
    loc = str((state.get("player", {}) or {}).get("location", "") or "").strip().lower()
    if not loc:
        return {"ok": False, "reason": "no_location"}
    price = quote_vehicle_price_usd(state, loc, vehicle_id)
    if price <= 0:
        return {"ok": False, "reason": "bad_vehicle"}
    return buy_vehicle(state, vehicle_id, price_override=price)
