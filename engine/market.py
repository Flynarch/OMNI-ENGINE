from __future__ import annotations

from typing import Any


def _clamp(v: int, lo: int, hi: int) -> int:
    return max(lo, min(hi, int(v)))


def _ensure_market(econ: dict[str, Any]) -> dict[str, dict[str, int]]:
    m = econ.setdefault("market", {})
    if not isinstance(m, dict):
        m = {}
        econ["market"] = m
    # Defaults
    for k in ("electronics", "medical", "weapons", "food", "transport"):
        m.setdefault(k, {"price_idx": 100, "scarcity": 0})
        if isinstance(m.get(k), dict):
            m[k].setdefault("price_idx", 100)
            m[k].setdefault("scarcity", 0)
    return m  # type: ignore[return-value]


def _apply_market_pressures(
    market: dict[str, dict[str, int]],
    *,
    police_att: str,
    corp_st: int,
    bm_pw: int,
    local_restrictions: dict[str, Any] | None = None,
    day: int | None = None,
) -> None:
    """Apply daily market pressures to a market dict in-place.

    Global pressures come from faction attention/stability/power.
    Local pressures come from location restrictions (sweep/lockdown).
    """
    police_att = str(police_att or "idle").lower()
    local_restrictions = local_restrictions or {}

    # Base pressures
    weapons_pressure = 0
    transport_pressure = 0
    if police_att == "aware":
        weapons_pressure += 5
        transport_pressure += 3
    elif police_att == "investigated":
        weapons_pressure += 12
        transport_pressure += 8
    elif police_att == "manhunt":
        weapons_pressure += 20
        transport_pressure += 15

    electronics_pressure = 0
    if int(corp_st) <= 35:
        electronics_pressure += 10
    if int(corp_st) <= 20:
        electronics_pressure += 10

    # Local restrictions: modest, bounded modifiers (location-specific only).
    try:
        if isinstance(local_restrictions, dict):
            until_ps = int(local_restrictions.get("police_sweep_until_day", 0) or 0)
            until_cl = int(local_restrictions.get("corporate_lockdown_until_day", 0) or 0)
            # Only apply if restriction is active (day <= until_day). If day missing, be conservative and apply only when until_day>0.
            active_ps = (day is None and until_ps > 0) or (day is not None and until_ps >= day)
            active_cl = (day is None and until_cl > 0) or (day is not None and until_cl >= day)
            if active_ps:
                transport_pressure += 4
                weapons_pressure += 3
            if active_cl:
                electronics_pressure += 6
    except Exception:
        pass

    # Black market mitigates scarcity but raises price when it has leverage.
    bm_mitigate = 0
    bm_markup = 0
    if int(bm_pw) >= 65:
        bm_mitigate = 6
        bm_markup = 8
    elif int(bm_pw) >= 50:
        bm_mitigate = 3
        bm_markup = 4

    # Apply adjustments (bounded).
    w = market["weapons"]
    w["scarcity"] = _clamp(int(w.get("scarcity", 0) or 0) + weapons_pressure - bm_mitigate, 0, 100)
    w["price_idx"] = _clamp(int(w.get("price_idx", 100) or 100) + weapons_pressure + bm_markup, 70, 220)

    t = market["transport"]
    t["scarcity"] = _clamp(int(t.get("scarcity", 0) or 0) + transport_pressure, 0, 100)
    t["price_idx"] = _clamp(int(t.get("price_idx", 100) or 100) + transport_pressure, 70, 200)

    e = market["electronics"]
    e["scarcity"] = _clamp(int(e.get("scarcity", 0) or 0) + electronics_pressure, 0, 100)
    e["price_idx"] = _clamp(int(e.get("price_idx", 100) or 100) + electronics_pressure, 70, 220)

    # Others drift slowly toward baseline (100, 0) to avoid runaway.
    for k in ("medical", "food"):
        row = market[k]
        row["price_idx"] = _clamp(
            int(row.get("price_idx", 100) or 100)
            + (1 if row.get("price_idx", 100) < 100 else -1 if row.get("price_idx", 100) > 100 else 0),
            70,
            200,
        )
        row["scarcity"] = _clamp(int(row.get("scarcity", 0) or 0) + (-1 if row.get("scarcity", 0) > 0 else 0), 0, 100)


def _apply_local_restrictions_only(market: dict[str, dict[str, int]], *, local_restrictions: dict[str, Any] | None, day: int) -> None:
    """Apply ONLY location restrictions pressure (no global faction pressures)."""
    local_restrictions = local_restrictions or {}
    if not isinstance(local_restrictions, dict):
        return
    try:
        until_ps = int(local_restrictions.get("police_sweep_until_day", 0) or 0)
    except Exception:
        until_ps = 0
    try:
        until_cl = int(local_restrictions.get("corporate_lockdown_until_day", 0) or 0)
    except Exception:
        until_cl = 0
    active_ps = until_ps >= day
    active_cl = until_cl >= day
    if active_ps:
        # More checkpoints -> transport + weapons tighter.
        if isinstance(market.get("transport"), dict):
            market["transport"]["scarcity"] = _clamp(int(market["transport"].get("scarcity", 0) or 0) + 4, 0, 100)
            market["transport"]["price_idx"] = _clamp(int(market["transport"].get("price_idx", 100) or 100) + 4, 60, 320)
        if isinstance(market.get("weapons"), dict):
            market["weapons"]["scarcity"] = _clamp(int(market["weapons"].get("scarcity", 0) or 0) + 3, 0, 100)
            market["weapons"]["price_idx"] = _clamp(int(market["weapons"].get("price_idx", 100) or 100) + 3, 60, 320)
    if active_cl:
        # Lockdown -> electronics tighter.
        if isinstance(market.get("electronics"), dict):
            market["electronics"]["scarcity"] = _clamp(int(market["electronics"].get("scarcity", 0) or 0) + 6, 0, 100)
            market["electronics"]["price_idx"] = _clamp(int(market["electronics"].get("price_idx", 100) or 100) + 6, 60, 320)


def update_market(state: dict[str, Any]) -> None:
    """Daily market pressure from factions + attention.

    - police attention raises weapons scarcity/price, transport friction.
    - corporate instability raises electronics price and scarcity.
    - black_market power reduces weapons scarcity but increases price volatility.
    """
    econ = state.setdefault("economy", {})
    market = _ensure_market(econ)
    meta = state.setdefault("meta", {})
    day = int(meta.get("day", 1) or 1)

    # Snapshot "before" for daily delta display.
    try:
        before_price = int(round(sum(int((market[k] or {}).get("price_idx", 100) or 100) for k in market.keys()) / max(1, len(market))))
        before_scar = int(round(sum(int((market[k] or {}).get("scarcity", 0) or 0) for k in market.keys()) / max(1, len(market))))
    except Exception:
        before_price = 100
        before_scar = 0
    world = state.get("world", {}) or {}

    statuses = world.get("faction_statuses", {}) or {}
    police_att = str(statuses.get("police", "idle") or "idle").lower()

    factions = world.get("factions", {}) or {}
    corp = factions.get("corporate", {}) if isinstance(factions.get("corporate"), dict) else {}
    bm = factions.get("black_market", {}) if isinstance(factions.get("black_market"), dict) else {}

    corp_st = int(corp.get("stability", 50) or 50)
    bm_pw = int(bm.get("power", 50) or 50)

    # Geopolitics pressure (world-scale background): sanctions/tension create global scarcity/price shocks.
    geo_tension = 0
    sanc_n = 0
    try:
        atlas = world.get("atlas", {}) or {}
        gp = atlas.get("geopolitics", {}) if isinstance(atlas, dict) else {}
        if isinstance(gp, dict):
            try:
                geo_tension = int(gp.get("tension_idx", 0) or 0)
            except Exception:
                geo_tension = 0
            s = gp.get("active_sanctions", []) or []
            if isinstance(s, list):
                # Only count sanctions in last 7 days.
                sanc_n = 0
                for it in s[-20:]:
                    if not isinstance(it, dict):
                        continue
                    try:
                        d0 = int(it.get("day", 0) or 0)
                    except Exception:
                        d0 = 0
                    if day - d0 <= 7:
                        sanc_n += 1
    except Exception:
        pass

    # Translate geopolitics into additional global pressures.
    # - electronics suffers most (sanctions/export controls)
    # - transport suffers (shipping/insurance)
    # - food mildly (if high tension persists)
    if geo_tension >= 25:
        corp_st = max(0, corp_st - min(10, geo_tension // 10))  # indirectly makes electronics pressure higher
    # Apply directly into global market for clarity (bounded).
    try:
        if sanc_n > 0:
            e_row = market.get("electronics", {}) if isinstance(market.get("electronics"), dict) else {}
            t_row = market.get("transport", {}) if isinstance(market.get("transport"), dict) else {}
            f_row = market.get("food", {}) if isinstance(market.get("food"), dict) else {}
            # sanctions -> electronics scarcity +2, price +3 per sanction (capped)
            e_row["scarcity"] = _clamp(int(e_row.get("scarcity", 0) or 0) + min(8, 2 * sanc_n), 0, 100)
            e_row["price_idx"] = _clamp(int(e_row.get("price_idx", 100) or 100) + min(12, 3 * sanc_n), 70, 260)
            # transport -> scarcity +1, price +2 per sanction (capped)
            t_row["scarcity"] = _clamp(int(t_row.get("scarcity", 0) or 0) + min(6, 1 * sanc_n), 0, 100)
            t_row["price_idx"] = _clamp(int(t_row.get("price_idx", 100) or 100) + min(10, 2 * sanc_n), 70, 240)
            # high tension (not just sanctions) nudges food volatility.
            if geo_tension >= 60:
                f_row["scarcity"] = _clamp(int(f_row.get("scarcity", 0) or 0) + 1, 0, 100)
                f_row["price_idx"] = _clamp(int(f_row.get("price_idx", 100) or 100) + 1, 70, 220)
            market["electronics"] = e_row
            market["transport"] = t_row
            market["food"] = f_row
    except Exception:
        pass
    _apply_market_pressures(market, police_att=police_att, corp_st=corp_st, bm_pw=bm_pw, local_restrictions=None, day=day)

    # Country market layer (global → country): cache baseline per country.
    try:
        atlas2 = world.get("atlas", {}) or {}
        gp2 = atlas2.get("geopolitics", {}) if isinstance(atlas2, dict) else {}
        t2 = int((gp2.get("tension_idx", 0) if isinstance(gp2, dict) else 0) or 0)
        sanc = gp2.get("active_sanctions", []) if isinstance(gp2, dict) else []
        sanc_level_by_country: dict[str, int] = {}
        if isinstance(sanc, list):
            for it in sanc[-30:]:
                if not isinstance(it, dict):
                    continue
                try:
                    d0 = int(it.get("day", 0) or 0)
                except Exception:
                    d0 = 0
                if day - d0 > 30:
                    continue
                a = str(it.get("a", "") or "").strip().lower()
                b = str(it.get("b", "") or "").strip().lower()
                if a:
                    sanc_level_by_country[a] = min(5, sanc_level_by_country.get(a, 0) + 1)
                if b:
                    sanc_level_by_country[b] = min(5, sanc_level_by_country.get(b, 0) + 1)
        from engine.atlas import ensure_country_market

        countries = (atlas2.get("countries", {}) if isinstance(atlas2, dict) else {}) or {}
        if isinstance(countries, dict):
            for c in list(countries.keys())[:80]:
                cc = str(c).strip().lower()
                ensure_country_market(
                    state,
                    cc,
                    global_market=market,
                    day=day,
                    sanctions_level=sanc_level_by_country.get(cc, 0),
                    tension_idx=t2,
                )
    except Exception:
        pass

    # City market (country → city): city market derives from country baseline + local restrictions.
    try:
        locs = world.get("locations", {}) or {}
        if isinstance(locs, dict):
            for _loc_key, slot in list(locs.items())[:120]:
                if not isinstance(slot, dict):
                    continue
                prof = slot.get("profile") if isinstance(slot.get("profile"), dict) else {}
                country = str((prof or {}).get("country", "") or "").strip().lower()
                # Country baseline (fallback to global).
                c_market = market
                try:
                    atlas3 = world.get("atlas", {}) or {}
                    c_row = (atlas3.get("countries", {}) or {}).get(country) if country else None
                    if isinstance(c_row, dict) and isinstance(c_row.get("market"), dict) and c_row.get("market"):
                        c_market = c_row.get("market")  # type: ignore[assignment]
                except Exception:
                    pass

                # Ensure city market exists (copy from country baseline on first use).
                lm = slot.get("market")
                if not isinstance(lm, dict) or not lm:
                    lm = {}
                    for k in ("electronics", "medical", "weapons", "food", "transport"):
                        row = c_market.get(k) if isinstance(c_market.get(k), dict) else {"price_idx": 100, "scarcity": 0}
                        lm[k] = {"price_idx": int((row or {}).get("price_idx", 100) or 100), "scarcity": int((row or {}).get("scarcity", 0) or 0)}
                else:
                    # Converge city market toward country baseline (30%/day).
                    for cat in ("electronics", "medical", "weapons", "food", "transport"):
                        if not isinstance(lm.get(cat), dict):
                            lm[cat] = {"price_idx": 100, "scarcity": 0}
                        row = lm.get(cat) or {}
                        base_row = c_market.get(cat) if isinstance(c_market.get(cat), dict) else {"price_idx": 100, "scarcity": 0}
                        try:
                            px = int(row.get("price_idx", 100) or 100)
                        except Exception:
                            px = 100
                        try:
                            sc = int(row.get("scarcity", 0) or 0)
                        except Exception:
                            sc = 0
                        try:
                            bpx = int((base_row or {}).get("price_idx", 100) or 100)
                        except Exception:
                            bpx = 100
                        try:
                            bsc = int((base_row or {}).get("scarcity", 0) or 0)
                        except Exception:
                            bsc = 0
                        px2 = px + int((bpx - px) * 0.3)
                        sc2 = sc + int((bsc - sc) * 0.3)
                        row["price_idx"] = _clamp(px2, 60, 320)
                        row["scarcity"] = _clamp(sc2, 0, 100)
                        lm[cat] = row

                # Apply only local restrictions (city-specific).
                restr = slot.get("restrictions", {}) if isinstance(slot.get("restrictions"), dict) else {}
                _apply_local_restrictions_only(lm, local_restrictions=restr, day=day)
                slot["market"] = lm
    except Exception:
        pass

    # Inter-city market flow (lightweight):
    # - converge local markets toward global market slowly (prevents runaway divergence)
    # - occasional shipment shock between two cities (deterministic) to create narrative/econ ripples
    try:
        locs2 = world.get("locations", {}) or {}
        if isinstance(locs2, dict) and len(locs2) >= 2:
            # Gather markets
            city_markets: list[tuple[str, dict[str, dict[str, int]]]] = []
            for k, slot in list(locs2.items())[:80]:
                if not isinstance(slot, dict):
                    continue
                lm = slot.get("market")
                if isinstance(lm, dict) and lm:
                    city_markets.append((str(k).strip().lower(), lm))  # type: ignore[arg-type]
            if city_markets:
                # Shipment shock: pick 2 cities deterministically once per day.
                import hashlib

                seed = str((state.get("meta", {}) or {}).get("seed_pack", "") or "")
                h = hashlib.md5(f"{seed}|{day}|ship".encode("utf-8", errors="ignore")).hexdigest()
                a = int(h[:8], 16)
                b = int(h[8:16], 16)
                i1 = a % len(city_markets)
                i2 = b % len(city_markets)
                if i2 == i1:
                    i2 = (i2 + 1) % len(city_markets)
                c1, m1 = city_markets[i1]
                c2, m2 = city_markets[i2]
                cat = ("electronics", "weapons", "medical", "food", "transport")[a % 5]
                # If there is a big price gap, simulate a shipment that reduces gap (supply flows).
                try:
                    p1 = int((m1.get(cat, {}) or {}).get("price_idx", 100) or 100)
                    p2 = int((m2.get(cat, {}) or {}).get("price_idx", 100) or 100)
                except Exception:
                    p1, p2 = 100, 100
                # Under high geopolitics tension, shipment shocks are more likely to be disrupted (bigger gaps persist),
                # so we require a smaller threshold to trigger "flow" events but reduce their effectiveness slightly.
                thresh = 18 if geo_tension < 60 else 14
                if abs(p1 - p2) >= thresh:
                    high_city, low_city = (c1, c2) if p1 > p2 else (c2, c1)
                    damp = 1 if geo_tension < 60 else 0  # when very tense, flows are less effective
                    # High price city gets scarcity -1, price -2; low price city gets scarcity +1, price +1 (export).
                    for city, delta_sc, delta_px in ((high_city, -1 + damp, -2 + damp), (low_city, +1, +1)):
                        slot = locs2.get(city)
                        if not isinstance(slot, dict) or not isinstance(slot.get("market"), dict):
                            continue
                        row = (slot["market"].get(cat) if isinstance(slot["market"].get(cat), dict) else {"price_idx": 100, "scarcity": 0}) or {}
                        try:
                            sc0 = int(row.get("scarcity", 0) or 0)
                        except Exception:
                            sc0 = 0
                        try:
                            px0 = int(row.get("price_idx", 100) or 100)
                        except Exception:
                            px0 = 100
                        row["scarcity"] = _clamp(sc0 + delta_sc, 0, 100)
                        row["price_idx"] = _clamp(px0 + delta_px, 60, 320)
                        slot["market"][cat] = row
                        locs2[city] = slot
                    # Store a lightweight note for UI/news systems to surface if appropriate.
                    state.setdefault("world_notes", []).append(f"[MarketFlow] Shipment: {cat} moved {low_city}→{high_city}")
                    world["locations"] = locs2
    except Exception:
        pass

    # Snapshot "after" + delta for UI.
    try:
        after_price = int(round(sum(int((market[k] or {}).get("price_idx", 100) or 100) for k in market.keys()) / max(1, len(market))))
        after_scar = int(round(sum(int((market[k] or {}).get("scarcity", 0) or 0) for k in market.keys()) / max(1, len(market))))
    except Exception:
        after_price = 100
        after_scar = 0

    meta["market_index"] = {
        "day": day,
        "price_avg": after_price,
        "scarcity_avg": after_scar,
        "d_price": int(after_price - before_price),
        "d_scarcity": int(after_scar - before_scar),
    }

