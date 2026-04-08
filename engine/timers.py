from __future__ import annotations

from typing import Any


def _advance(meta: dict[str, Any], minutes: int) -> None:
    meta["time_min"] = int(meta.get("time_min", 0)) + minutes
    while meta["time_min"] >= 1440:
        meta["time_min"] -= 1440
        meta["day"] = int(meta.get("day", 1)) + 1


def _can_surface_ripple(state: dict[str, Any], rp: dict[str, Any]) -> bool:
    """Visibility/propagation gate: a ripple should only surface if player can logically know it."""
    propagation = str(rp.get("propagation", "local_witness") or "local_witness").lower()
    origin_loc = str(rp.get("origin_location", "") or "").strip().lower()
    cur_loc = str(state.get("player", {}).get("location", "") or "").strip().lower()
    origin_faction = str(rp.get("origin_faction", "") or "").strip().lower()

    # Default rule: local witness/rumor requires being in the same location.
    if propagation in ("local", "local_witness", "witness"):
        return bool(origin_loc and cur_loc and origin_loc == cur_loc)

    # Contacts can inform you across locations (phone/DM), if you have contacts at all.
    if propagation in ("contacts", "contact_network"):
        contacts = (state.get("world", {}) or {}).get("contacts", {}) or {}
        if not isinstance(contacts, dict) or len(contacts) == 0:
            return False
        # If ripple is tagged with origin_faction, require a logical link:
        # - a contact with matching affiliation, OR
        # - a very high-trust contact (relay), but relay will be delayed (handled in update_timers).
        if origin_faction:
            for _n, c in contacts.items():
                if not isinstance(c, dict):
                    continue
                aff = str(c.get("affiliation", "") or "").strip().lower()
                if aff == origin_faction:
                    return True
            # Relay path: allow surfacing only after a delay window.
            try:
                for _n, c in contacts.items():
                    if not isinstance(c, dict):
                        continue
                    if int(c.get("trust", 0) or 0) >= 85:
                        # Only allow after at least one reschedule attempt (≈ "it takes time to reach you").
                        return int(rp.get("surface_attempts", 0) or 0) >= 1
            except Exception:
                return False
            return False
        return True

    # Faction networks can propagate across locations.
    if propagation in ("faction_network", "global", "broadcast"):
        return True

    # Unknown propagation: be conservative.
    return False


def _push_news(state: dict[str, Any], *, text: str, source: str = "broadcast") -> None:
    """Append a bounded, structured headline to world.news_feed (quests-compatible)."""
    try:
        from engine.news import push_news

        push_news(state, text=text, source=source)
    except Exception:
        # Fallback to prior behavior if imports fail.
        meta = state.get("meta", {}) or {}
        day = int(meta.get("day", 1) or 1)
        world = state.setdefault("world", {})
        feed = world.setdefault("news_feed", [])
        if not isinstance(feed, list):
            feed = []
            world["news_feed"] = feed
        t = str(text)[:140]
        src = str(source or "broadcast")
        for it in feed[-12:]:
            if isinstance(it, dict) and int(it.get("day", -1)) == day and str(it.get("text", "")) == t:
                return
        feed.append({"day": day, "text": t, "source": src})
        world["news_feed"] = feed[-50:]


def _queue_ripple(state: dict[str, Any], rp: dict[str, Any]) -> None:
    from engine.ripple_queue import enqueue_ripple

    enqueue_ripple(state, rp)


def _apply_triggered_events(state: dict[str, Any], triggered: list[dict[str, Any]]) -> None:
    """Apply deterministic effects for known event types."""
    if not triggered:
        return
    meta = state.get("meta", {}) or {}
    day = int(meta.get("day", 1) or 1)
    time_min = int(meta.get("time_min", 0) or 0)

    for ev in triggered:
        if not isinstance(ev, dict):
            continue
        et = str(ev.get("event_type", "") or "")
        payload = ev.get("payload") or {}
        if not isinstance(payload, dict):
            payload = {}

        if et == "npc_report":
            reporter = str(payload.get("reporter", "unknown") or "unknown")
            aff = str(payload.get("affiliation", "") or "").strip().lower()
            try:
                sus = int(payload.get("suspicion", 50) or 50)
            except Exception:
                sus = 50
            sus = max(0, min(100, sus))

            # Trace pressure bump (bounded).
            tr = state.setdefault("trace", {})
            try:
                tp = int(tr.get("trace_pct", 0) or 0)
            except Exception:
                tp = 0
            before_tp = tp
            bump = 1 + int((sus - 50) / 20)
            if aff == "police":
                bump += 1
            tp = max(0, min(100, tp + max(1, min(5, bump))))
            tr["trace_pct"] = tp
            trace_delta = tp - before_tp

            # Sync attention from trace.
            try:
                from engine.factions import sync_faction_statuses_from_trace

                sync_faction_statuses_from_trace(state)
            except Exception:
                pass

            _push_news(state, text=f"Tip masuk: pihak berwenang menerima laporan anon tentang player ({reporter}).", source="broadcast")
            _queue_ripple(
                state,
                {
                    "kind": "npc_report",
                    "text": f"{reporter} mengontak otoritas (sus={sus}).",
                    "triggered_day": day,
                    "surface_day": day,
                    "surface_time": min(1439, time_min + 10),
                    "surfaced": False,
                    "propagation": "faction_network" if aff in ("police", "corporate") else "contacts",
                    "origin_location": str(payload.get("origin_location", "") or "").strip().lower(),
                    "origin_faction": aff,
                    "witnesses": [],
                    "surface_attempts": 0,
                    "meta": {"reporter": reporter, "suspicion": sus, "affiliation": aff},
                    "impact": {"trace_delta": trace_delta},
                },
            )

        if et == "npc_offer":
            npc = str(payload.get("npc", "unknown") or "unknown")
            role = str(payload.get("role", "civilian") or "civilian")
            service = str(payload.get("service", "offer") or "offer")
            world = state.setdefault("world", {})
            econ = world.setdefault("npc_economy", {"offers": {}, "last_refresh_day": 0})
            if not isinstance(econ, dict):
                econ = {"offers": {}, "last_refresh_day": 0}
                world["npc_economy"] = econ
            offers = econ.setdefault("offers", {})
            if not isinstance(offers, dict):
                offers = {}
                econ["offers"] = offers
            offers[npc] = {
                "npc": npc,
                "role": role,
                "service": service,
                "day": day,
                "expires_day": day + 2,
                "payload": dict(payload),
            }
            econ["offers"] = offers

            # Economy market hook: trade offers influence scarcity/price in that category.
            try:
                econ2 = state.setdefault("economy", {})
                market = econ2.get("market", {}) or {}
                if isinstance(market, dict) and isinstance(service, str) and service.startswith("trade:"):
                    cat = service.split(":", 1)[1].strip().lower()
                    if cat in market and isinstance(market.get(cat), dict):
                        row = market.get(cat) or {}
                        try:
                            sc = int(row.get("scarcity", 0) or 0)
                        except Exception:
                            sc = 0
                        try:
                            px = int(row.get("price_idx", 100) or 100)
                        except Exception:
                            px = 100
                        # Trade implies supply increases: scarcity down, price pressure down slightly.
                        row["scarcity"] = max(0, sc - 1)
                        row["price_idx"] = max(60, min(180, px - 1))
                        market[cat] = row
                        econ2["market"] = market
            except Exception:
                pass

            _queue_ripple(
                state,
                {
                    "kind": "npc_offer",
                    "text": f"{npc} ({role}) menawarkan: {service}.",
                    "triggered_day": day,
                    "surface_day": day,
                    "surface_time": min(1439, time_min + 5),
                    "surfaced": False,
                    "propagation": "contacts",
                    "origin_location": str(payload.get("origin_location", "") or "").strip().lower(),
                    "origin_faction": str(payload.get("origin_faction", "") or "").strip().lower(),
                    "witnesses": [],
                    "surface_attempts": 0,
                    "meta": {"npc": npc, "role": role, "service": service, "expires_day": day + 2},
                },
            )

        if et == "npc_sell_info":
            npc = str(payload.get("npc", "unknown") or "unknown")
            buyer = str(payload.get("buyer_faction", "black_market") or "black_market").strip().lower()
            try:
                sus = int(payload.get("suspicion", 50) or 50)
            except Exception:
                sus = 50
            sus = max(0, min(100, sus))
            # Small faction aftershock (no player cash change here).
            world = state.setdefault("world", {})
            factions = world.get("factions", {}) or {}
            if isinstance(factions, dict) and buyer in factions and isinstance(factions.get(buyer), dict):
                f = factions.get(buyer) or {}
                try:
                    pw = int(f.get("power", 50) or 50)
                except Exception:
                    pw = 50
                try:
                    st = int(f.get("stability", 50) or 50)
                except Exception:
                    st = 50
                bump = 1 + int((sus - 50) / 25)
                f["power"] = max(0, min(100, pw + max(1, min(3, bump))))
                f["stability"] = max(0, min(100, st + 1))
                factions[buyer] = f
                world["factions"] = factions

            # Economy market hook: intel trade moves markets (demand shocks).
            try:
                econ3 = state.setdefault("economy", {})
                market2 = econ3.get("market", {}) or {}
                if isinstance(market2, dict):
                    # black_market intel tends to loosen supply in illicit goods; corp/police intel tightens electronics.
                    if buyer == "black_market":
                        cat = "weapons"
                        if cat in market2 and isinstance(market2.get(cat), dict):
                            row = market2.get(cat) or {}
                            try:
                                sc2 = int(row.get("scarcity", 0) or 0)
                            except Exception:
                                sc2 = 0
                            try:
                                px2 = int(row.get("price_idx", 100) or 100)
                            except Exception:
                                px2 = 100
                            row["scarcity"] = max(0, sc2 - 1)
                            row["price_idx"] = max(60, min(200, px2 - 1))
                            market2[cat] = row
                    else:
                        cat = "electronics"
                        if cat in market2 and isinstance(market2.get(cat), dict):
                            row = market2.get(cat) or {}
                            try:
                                sc2 = int(row.get("scarcity", 0) or 0)
                            except Exception:
                                sc2 = 0
                            try:
                                px2 = int(row.get("price_idx", 100) or 100)
                            except Exception:
                                px2 = 100
                            row["scarcity"] = max(0, sc2 + 1)
                            row["price_idx"] = max(60, min(220, px2 + 2))
                            market2[cat] = row
                    econ3["market"] = market2
            except Exception:
                pass

            _push_news(state, text=f"Intel diperdagangkan di bawah tanah (sumber: {npc}).", source="faction_network")
            _queue_ripple(
                state,
                {
                    "kind": "npc_sell_info",
                    "text": f"{npc} menjual intel ke jaringan ({buyer}).",
                    "triggered_day": day,
                    "surface_day": day,
                    "surface_time": min(1439, time_min + 15),
                    "surfaced": False,
                    "propagation": "contacts" if buyer == "black_market" else "faction_network",
                    "origin_location": str(payload.get("origin_location", "") or "").strip().lower(),
                    "origin_faction": str(payload.get("origin_faction", "") or "").strip().lower(),
                    "witnesses": [],
                    "surface_attempts": 0,
                    "meta": {"npc": npc, "buyer_faction": buyer, "suspicion": sus},
                    "impact": {"factions": {buyer: {"power": +1}}},
                },
            )

        # Quest/event resolver: police sweep (location-specific restrictions).
        if et == "police_sweep":
            loc = str(payload.get("location", "") or str(state.get("player", {}).get("location", "") or "")).strip().lower()
            att = str(payload.get("attention", "investigated") or "investigated").strip().lower()
            world = state.setdefault("world", {})
            locs = world.setdefault("locations", {})
            if isinstance(locs, dict) and loc:
                locs.setdefault(loc, {})
                slot = locs.get(loc)
                if isinstance(slot, dict):
                    r = slot.setdefault("restrictions", {})
                    if isinstance(r, dict):
                        r["police_sweep_until_day"] = day + 1
                        r["police_sweep_attention"] = att
                    slot["restrictions"] = r
                    # Simple area model: downtown gets checkpoints.
                    slot.setdefault("areas", {})
                    if isinstance(slot.get("areas"), dict):
                        a = slot.get("areas") or {}
                        a["downtown"] = {"restricted": True, "until_day": day + 1, "reason": "police_sweep"}
                        slot["areas"] = a
                    locs[loc] = slot
            _push_news(state, text=f"Operasi polisi meningkat di {loc} (sweep).", source="broadcast")
            _queue_ripple(
                state,
                {
                    "kind": "police_sweep",
                    "text": f"Checkpoint & razia meningkat di {loc}.",
                    "triggered_day": day,
                    "surface_day": day,
                    "surface_time": min(1439, time_min + 5),
                    "surfaced": False,
                    "propagation": "broadcast",
                    "origin_location": loc,
                    "origin_faction": "police",
                    "witnesses": [],
                    "surface_attempts": 0,
                    "meta": {"location": loc, "attention": att},
                },
            )

        # Quest/event resolver: corporate lockdown (location-specific restriction + local economy shock).
        if et == "corporate_lockdown":
            loc = str(payload.get("location", "") or str(state.get("player", {}).get("location", "") or "")).strip().lower()
            world = state.setdefault("world", {})
            locs = world.setdefault("locations", {})
            if isinstance(locs, dict) and loc:
                locs.setdefault(loc, {})
                slot = locs.get(loc)
                if isinstance(slot, dict):
                    r = slot.setdefault("restrictions", {})
                    if isinstance(r, dict):
                        r["corporate_lockdown_until_day"] = day + 2
                    # Simple area model: corporate_district is restricted.
                    slot.setdefault("areas", {})
                    if isinstance(slot.get("areas"), dict):
                        a = slot.get("areas") or {}
                        a["corporate_district"] = {"restricted": True, "until_day": day + 2, "reason": "corporate_lockdown"}
                        slot["areas"] = a
                    # Local market shock: electronics scarcity/price up (only this city).
                    m = slot.get("market")
                    if not isinstance(m, dict) or not m:
                        # Lazy snapshot from global market.
                        base = (state.get("economy", {}) or {}).get("market", {}) or {}
                        m = {}
                        if isinstance(base, dict):
                            for k in ("electronics", "medical", "weapons", "food", "transport"):
                                row = base.get(k) if isinstance(base.get(k), dict) else {"price_idx": 100, "scarcity": 0}
                                m[k] = {"price_idx": int((row or {}).get("price_idx", 100) or 100), "scarcity": int((row or {}).get("scarcity", 0) or 0)}
                        slot["market"] = m
                    if isinstance(m, dict) and isinstance(m.get("electronics"), dict):
                        e = m.get("electronics") or {}
                        try:
                            e_sc = int(e.get("scarcity", 0) or 0)
                        except Exception:
                            e_sc = 0
                        try:
                            e_px = int(e.get("price_idx", 100) or 100)
                        except Exception:
                            e_px = 100
                        e["scarcity"] = max(0, min(100, e_sc + 3))
                        e["price_idx"] = max(60, min(300, e_px + 5))
                        m["electronics"] = e
                        slot["market"] = m
                    locs[loc] = slot
            _push_news(state, text=f"Korporasi lockdown di {loc}: akses & keamanan diperketat.", source="broadcast")
            _queue_ripple(
                state,
                {
                    "kind": "corporate_lockdown",
                    "text": f"Akses corporate di {loc} makin ketat (lockdown).",
                    "triggered_day": day,
                    "surface_day": day,
                    "surface_time": min(1439, time_min + 10),
                    "surfaced": False,
                    "propagation": "broadcast",
                    "origin_location": loc,
                    "origin_faction": "corporate",
                    "witnesses": [],
                    "surface_attempts": 0,
                    "meta": {"location": loc, "until_day": day + 2},
                },
            )

        # Quest/event resolver: black market offer -> quest chain instance.
        if et == "black_market_offer":
            loc = str(payload.get("location", "") or str(state.get("player", {}).get("location", "") or "")).strip().lower()
            try:
                bm_pw = int(payload.get("bm_power", 65) or 65)
            except Exception:
                bm_pw = 65
            try:
                bm_st = int(payload.get("bm_stability", 35) or 35)
            except Exception:
                bm_st = 35
            try:
                from engine.quests import create_black_market_delivery_quest

                q = create_black_market_delivery_quest(state, origin_location=loc, bm_power=bm_pw, bm_stability=bm_st)
                _push_news(state, text=f"Rumor: offer pasar gelap muncul di {loc} (quest {q.get('id','?')}).", source="faction_network")
                _queue_ripple(
                    state,
                    {
                        "kind": "quest_offer",
                        "text": f"Pasar gelap: job baru tersedia (lihat quest {q.get('id','?')}).",
                        "triggered_day": day,
                        "surface_day": day,
                        "surface_time": min(1439, time_min + 5),
                        "surfaced": False,
                        "propagation": "contacts",
                        "origin_location": loc,
                        "origin_faction": "black_market",
                        "witnesses": [],
                        "surface_attempts": 0,
                        "meta": {"quest_id": q.get("id", ""), "location": loc},
                    },
                )
            except Exception:
                pass

        # Legacy event resolver: map older world_tick events into the newer restriction system.
        if et == "investigation_sweep":
            loc = str(payload.get("location", "") or str(state.get("player", {}).get("location", "") or "")).strip().lower()
            try:
                trsnap = int(payload.get("trace_snapshot", 0) or 0)
            except Exception:
                trsnap = 0
            world = state.setdefault("world", {})
            locs = world.setdefault("locations", {})
            if isinstance(locs, dict) and loc:
                locs.setdefault(loc, {})
                slot = locs.get(loc)
                if isinstance(slot, dict):
                    r = slot.setdefault("restrictions", {})
                    if isinstance(r, dict):
                        r["police_sweep_until_day"] = max(int(r.get("police_sweep_until_day", 0) or 0), day + 1)
                        r["police_sweep_attention"] = "investigated"
                    slot.setdefault("areas", {})
                    if isinstance(slot.get("areas"), dict):
                        a = slot.get("areas") or {}
                        a["downtown"] = {"restricted": True, "until_day": day + 1, "reason": "investigation_sweep"}
                        slot["areas"] = a
                    locs[loc] = slot
            _push_news(state, text=f"Penyelidikan diperluas di {loc} (trace={trsnap}%).", source="broadcast")
            _queue_ripple(
                state,
                {
                    "kind": "police_sweep",
                    "text": f"Razia investigasi meningkat di {loc}.",
                    "triggered_day": day,
                    "surface_day": day,
                    "surface_time": min(1439, time_min + 10),
                    "surfaced": False,
                    "propagation": "broadcast",
                    "origin_location": loc,
                    "origin_faction": "police",
                    "witnesses": [],
                    "surface_attempts": 0,
                    "meta": {"location": loc, "source": "investigation_sweep"},
                },
            )

        if et == "manhunt_lockdown":
            loc = str(payload.get("location", "") or str(state.get("player", {}).get("location", "") or "")).strip().lower()
            try:
                trsnap = int(payload.get("trace_snapshot", 0) or 0)
            except Exception:
                trsnap = 0
            # Stronger sweep + trace pressure bump.
            try:
                tr = state.setdefault("trace", {})
                tp = int(tr.get("trace_pct", 0) or 0)
                tr["trace_pct"] = max(0, min(100, tp + 2))
            except Exception:
                pass
            world = state.setdefault("world", {})
            locs = world.setdefault("locations", {})
            if isinstance(locs, dict) and loc:
                locs.setdefault(loc, {})
                slot = locs.get(loc)
                if isinstance(slot, dict):
                    r = slot.setdefault("restrictions", {})
                    if isinstance(r, dict):
                        r["police_sweep_until_day"] = max(int(r.get("police_sweep_until_day", 0) or 0), day + 2)
                        r["police_sweep_attention"] = "manhunt"
                    slot.setdefault("areas", {})
                    if isinstance(slot.get("areas"), dict):
                        a = slot.get("areas") or {}
                        a["transit_hubs"] = {"restricted": True, "until_day": day + 2, "reason": "manhunt_lockdown"}
                        slot["areas"] = a
                    locs[loc] = slot
            _push_news(state, text=f"Manhunt checkpoint lockdown di {loc} (trace={trsnap}%).", source="broadcast")
            _queue_ripple(
                state,
                {
                    "kind": "police_sweep",
                    "text": f"Lockdown checkpoint (manhunt) aktif di {loc}.",
                    "triggered_day": day,
                    "surface_day": day,
                    "surface_time": min(1439, time_min + 5),
                    "surfaced": False,
                    "propagation": "broadcast",
                    "origin_location": loc,
                    "origin_faction": "police",
                    "witnesses": [],
                    "surface_attempts": 0,
                    "meta": {"location": loc, "source": "manhunt_lockdown"},
                    "impact": {"trace_delta": +2},
                },
            )

        if et == "debt_collection_ping":
            try:
                debt = int(payload.get("debt", 0) or 0)
            except Exception:
                debt = 0
            # Soft consequence: increase daily burn slightly + add a small risk to trace (pressure).
            try:
                econ = state.setdefault("economy", {})
                burn = int(econ.get("daily_burn", 0) or 0)
                if debt > 0:
                    econ["daily_burn"] = burn + 1
            except Exception:
                pass
            try:
                tr = state.setdefault("trace", {})
                tp = int(tr.get("trace_pct", 0) or 0)
                tr["trace_pct"] = max(0, min(100, tp + (1 if debt > 0 else 0)))
            except Exception:
                pass
            _push_news(state, text="Penagih utang mencari jejakmu (tekanan finansial naik).", source="contacts")
            _queue_ripple(
                state,
                {
                    "kind": "debt_pressure",
                    "text": "Penagih utang mulai menanyakan keberadaanmu.",
                    "triggered_day": day,
                    "surface_day": day,
                    "surface_time": min(1439, time_min + 20),
                    "surfaced": False,
                    "propagation": "contacts",
                    "origin_location": str(state.get("player", {}).get("location", "") or "").strip().lower(),
                    "origin_faction": "",
                    "witnesses": [],
                    "surface_attempts": 0,
                    "meta": {"debt": debt},
                },
            )


def update_timers(state: dict[str, Any], action_ctx: dict[str, Any]) -> None:
    meta = state.setdefault("meta", {"day": 1, "time_min": 480})
    kind = action_ctx.get("action_type", "instant")
    if kind == "combat":
        _advance(meta, 1)
    elif kind == "travel":
        # Location-specific movement friction (e.g., police sweep).
        try:
            cur_loc = str(state.get("player", {}).get("location", "") or "").strip().lower()
            dest_loc = str(action_ctx.get("travel_destination", "") or "").strip().lower()
            world = state.get("world", {}) or {}
            locs = world.get("locations", {}) or {}
            extra = 0
            day_now = int(meta.get("day", 1) or 1)
            if isinstance(locs, dict) and cur_loc:
                slot = locs.get(cur_loc)
                if isinstance(slot, dict):
                    r = slot.get("restrictions", {}) or {}
                    if isinstance(r, dict):
                        try:
                            until = int(r.get("police_sweep_until_day", 0) or 0)
                        except Exception:
                            until = 0
                        if until >= day_now:
                            extra += 12
            if isinstance(locs, dict) and dest_loc:
                slot2 = locs.get(dest_loc)
                if isinstance(slot2, dict):
                    r2 = slot2.get("restrictions", {}) or {}
                    if isinstance(r2, dict):
                        try:
                            until2 = int(r2.get("corporate_lockdown_until_day", 0) or 0)
                        except Exception:
                            until2 = 0
                        if until2 >= day_now:
                            extra += 15
            if extra > 0:
                try:
                    action_ctx["travel_minutes"] = int(action_ctx.get("travel_minutes", 30) or 30) + extra
                except Exception:
                    action_ctx["travel_minutes"] = 30 + extra
                state.setdefault("world_notes", []).append(f"[Restriction] Travel friction +{extra}min")
        except Exception:
            pass
        # Weather travel modifier.
        try:
            from engine.weather import ensure_weather, travel_minutes_modifier

            world = state.get("world", {}) or {}
            meta2 = state.get("meta", {}) or {}
            day2 = int(meta2.get("day", 1) or 1)
            cur_loc = str(state.get("player", {}).get("location", "") or "").strip().lower()
            dest_loc = str(action_ctx.get("travel_destination", "") or "").strip().lower()
            if cur_loc:
                w_cur = ensure_weather(state, cur_loc, day2)
                extra_w = travel_minutes_modifier(str((w_cur or {}).get("kind", "") or ""))
                if extra_w:
                    action_ctx["travel_minutes"] = int(action_ctx.get("travel_minutes", 30) or 30) + extra_w
            if dest_loc:
                w_dst = ensure_weather(state, dest_loc, day2)
                extra_w2 = travel_minutes_modifier(str((w_dst or {}).get("kind", "") or ""))
                if extra_w2:
                    action_ctx["travel_minutes"] = int(action_ctx.get("travel_minutes", 30) or 30) + max(0, extra_w2 - 3)
        except Exception:
            pass
        _advance(meta, int(action_ctx.get("travel_minutes", 30)))
    elif kind in ("rest", "sleep"):
        _advance(meta, int(action_ctx.get("rested_minutes", 60)))
    else:
        _advance(meta, int(action_ctx.get("instant_minutes", 2)))

    cur_day, cur_min = int(meta["day"]), int(meta["time_min"])

    # Limit how many scheduled items we process per turn to avoid narrative/UI spam.
    # IMPORTANT: we do NOT change scheduling logic or sim clock; we simply defer overflow to next turn.
    cap = 3

    due_events: list[dict[str, Any]] = []
    for ev in state.get("pending_events", []):
        if not isinstance(ev, dict) or ev.get("triggered"):
            continue
        if (int(ev.get("due_day", 99999)), int(ev.get("due_time", 99999))) <= (cur_day, cur_min):
            due_events.append(ev)

    due_ripples: list[dict[str, Any]] = []
    for rp in state.get("active_ripples", []):
        if not isinstance(rp, dict) or rp.get("surfaced"):
            continue
        if (int(rp.get("surface_day", 99999)), int(rp.get("surface_time", 99999))) <= (cur_day, cur_min):
            due_ripples.append(rp)

    # Merge by (day,time) so ordering is stable.
    items: list[tuple[tuple[int, int], str, dict[str, Any]]] = []
    for ev in due_events:
        items.append(((int(ev.get("due_day", 99999)), int(ev.get("due_time", 99999))), "event", ev))
    for rp in due_ripples:
        items.append(((int(rp.get("surface_day", 99999)), int(rp.get("surface_time", 99999))), "ripple", rp))
    items.sort(key=lambda x: (x[0][0], x[0][1], x[1]))

    triggered: list[dict[str, Any]] = []
    surfaced: list[dict[str, Any]] = []
    processed = 0
    for _when, kind2, obj in items:
        if processed >= cap:
            break
        if kind2 == "event":
            obj["triggered"] = True
            triggered.append(obj)
            processed += 1
        else:
            # Re-run propagation gate here; if not knowable, defer (do not count against cap).
            if not _can_surface_ripple(state, obj):
                obj["surface_attempts"] = int(obj.get("surface_attempts", 0) or 0) + 1
                if int(obj.get("surface_attempts", 0) or 0) >= 3:
                    obj["surfaced"] = True
                    obj["dropped_by_propagation"] = True
                    state.setdefault("world_notes", []).append(f"Ripple dropped (no propagation): {obj.get('text', 'unknown')}")
                    surfaced.append(obj)
                    processed += 1
                else:
                    prop = str(obj.get("propagation", "") or "").lower()
                    obj["surface_day"] = cur_day + 1
                    obj["surface_time"] = 8 * 60
                    if prop in ("contacts", "contact_network"):
                        obj["relay_pending"] = True
                continue
            obj["surfaced"] = True
            surfaced.append(obj)
            processed += 1

    state["triggered_events_this_turn"] = triggered
    if triggered:
        try:
            _apply_triggered_events(state, triggered)
        except Exception:
            pass
    if triggered:
        state.setdefault("world_notes", []).extend([f"Triggered event: {ev.get('title', ev.get('event_type', 'unknown'))}" for ev in triggered])
    state["surfacing_ripples_this_turn"] = surfaced
    if surfaced:
        state.setdefault("world_notes", []).extend([f"Surfaced ripple: {rp.get('text', 'unknown')}" for rp in surfaced])
        # Apply ripple effects only when they surface and are logically propagated.
        try:
            from engine.ripples import apply_ripple_effects

            for rp in surfaced:
                if isinstance(rp, dict) and not rp.get("dropped_by_propagation"):
                    apply_ripple_effects(state, rp)
        except Exception:
            pass
        # Update NPC beliefs from surfaced ripples (contacts/witness/local).
        try:
            from engine.npcs import apply_beliefs_from_ripple

            for rp in surfaced:
                if isinstance(rp, dict) and not rp.get("dropped_by_propagation"):
                    apply_beliefs_from_ripple(state, rp)
        except Exception:
            pass

    # Quest chains tick (multi-step objectives).
    try:
        from engine.quests import tick_quest_chains

        tick_quest_chains(state, action_ctx)
    except Exception:
        pass

    # Disguise expiry tick.
    try:
        from engine.disguise import tick_disguise_expiry

        tick_disguise_expiry(state)
    except Exception:
        pass

    # Safehouse lay-low bonus on rest/sleep.
    try:
        if str(action_ctx.get("action_type", "") or "") in ("rest", "sleep"):
            from engine.safehouse import apply_lay_low_bonus

            apply_lay_low_bonus(state)
    except Exception:
        pass

    # Archive completed items to keep active queues clean.
    if triggered:
        state.setdefault("resolved_events", []).extend(triggered)
    state["pending_events"] = [ev for ev in state.get("pending_events", []) if not ev.get("triggered")]

    if surfaced:
        state.setdefault("resolved_ripples", []).extend(surfaced)
    state["active_ripples"] = [rp for rp in state.get("active_ripples", []) if not rp.get("surfaced")]

