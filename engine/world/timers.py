from __future__ import annotations

from typing import Any
import hashlib

from engine.world.timers_bus import can_surface_ripple as _bus_can_surface_ripple
from engine.world.timers_bus import enqueue_ripple as _bus_enqueue_ripple
from engine.world.timers_bus import push_news as _bus_push_news
from engine.world.timers_router import apply_triggered_events as _apply_triggered_events_v2
from engine.world.timers_scheduler import collect_due_items as _collect_due_items_v2


def _record_soft_error(state: dict[str, Any], scope: str, err: Exception) -> None:
    try:
        from engine.core.errors import record_error

        record_error(state, scope, err)
    except Exception:
        pass


def _advance(meta: dict[str, Any], minutes: int) -> None:
    meta["time_min"] = int(meta.get("time_min", 0)) + minutes
    while meta["time_min"] >= 1440:
        meta["time_min"] -= 1440
        meta["day"] = int(meta.get("day", 1)) + 1


def _reset_daily_attrition_counters(state: dict[str, Any]) -> None:
    meta = state.setdefault("meta", {})
    if not isinstance(meta, dict):
        meta = {}
        state["meta"] = meta
    meta["daily_gigs_done"] = 0
    meta["daily_hacks_attempted"] = 0


def _can_surface_ripple(state: dict[str, Any], rp: dict[str, Any]) -> bool:
    return _bus_can_surface_ripple(state, rp)


def _push_news(state: dict[str, Any], *, text: str, source: str = "broadcast") -> None:
    _bus_push_news(state, text=text, source=source)


def _queue_ripple(state: dict[str, Any], rp: dict[str, Any]) -> None:
    _bus_enqueue_ripple(state, rp)


EventHandler = Any
EVENT_HANDLERS: dict[str, EventHandler] = {}


def _dispatch_registered_event_handler(
    state: dict[str, Any],
    ev: dict[str, Any],
    *,
    day: int,
    time_min: int,
) -> bool:
    """Registry hook for incremental event-handler refactors."""
    et = str(ev.get("event_type", "") or "")
    h = EVENT_HANDLERS.get(et)
    if not callable(h):
        return False
    try:
        return bool(h(state, ev, day=day, time_min=time_min))
    except Exception as e:
        try:
            from engine.core.errors import record_error

            record_error(state, f"timers.event_handler.{et}", e)
        except Exception:
            pass
        return False


def _handle_event_legacy_by_type(
    state: dict[str, Any],
    *,
    et: str,
    payload: dict[str, Any],
    day: int,
    time_min: int,
) -> bool:
    if et == "social_diffusion_hop":
        try:
            from engine.social.social_diffusion import propagate_rumor
        except Exception:
            return True
        frm = str(payload.get("from_npc", "") or "").strip()
        to = str(payload.get("to_npc", "") or "").strip()
        rumor = str(payload.get("rumor", "") or "").strip()
        cat = str(payload.get("category", "") or "").strip()
        try:
            hop = int(payload.get("hop", 0) or 0)
        except Exception:
            hop = 0
        if not (frm and to and rumor and cat):
            return True
        try:
            meta2 = state.get("meta", {}) or {}
            turn2 = int(meta2.get("turn", 0) or 0)
        except Exception:
            turn2 = 0
        world2 = state.setdefault("world", {})
        sd = world2.setdefault("social_diffusion", {})
        if not isinstance(sd, dict):
            sd = {}
            world2["social_diffusion"] = sd
        try:
            sd_day = int(sd.get("day", 0) or 0)
        except Exception:
            sd_day = 0
        try:
            sd_turn = int(sd.get("turn", -1) or -1)
        except Exception:
            sd_turn = -1
        if sd_day != day:
            sd["day"] = int(day)
            sd["used_today"] = 0
        if sd_turn != turn2:
            sd["turn"] = int(turn2)
            sd["used_turn"] = 0
        max_today = int(sd.get("max_hops_per_day", 12) or 12)
        max_turn = int(sd.get("max_hops_per_turn", 3) or 3)
        used_today = int(sd.get("used_today", 0) or 0)
        used_turn = int(sd.get("used_turn", 0) or 0)
        if used_today >= max_today or used_turn >= max_turn:
            state.setdefault("world_notes", []).append("[SocialDiffusion] throttled (budget reached).")
            return True
        sd["used_today"] = used_today + 1
        sd["used_turn"] = used_turn + 1
        propagated = []
        try:
            propagated = propagate_rumor(state, frm, rumor, cat, hop=hop)
        except Exception:
            propagated = []
        if propagated:
            pending = state.setdefault("pending_events", [])
            if isinstance(pending, list):
                for p in propagated[:10]:
                    if not isinstance(p, dict):
                        continue
                    pending.append(
                        {
                            "event_type": "social_diffusion_hop",
                            "due_day": day,
                            "due_time": min(1439, time_min + 1),
                            "triggered": False,
                            "payload": {
                                "from_npc": p.get("from", frm),
                                "to_npc": p.get("to", ""),
                                "rumor": p.get("distorted", ""),
                                "category": cat,
                                "hop": int(p.get("hop", hop + 1) or (hop + 1)),
                            },
                        }
                    )
        try:
            from engine.social.informants import maybe_queue_informant_tip

            maybe_queue_informant_tip(
                state,
                from_npc=frm,
                to_npc=to,
                rumor=rumor,
                category=cat,
                hop=hop,
            )
        except Exception:
            pass
        state.setdefault("world_notes", []).append(f"[SocialDiffusion] {to} mendengar: {rumor[:90]}")
        return True

    if et == "informant_tip":
        try:
            from engine.social.investigation_chains import handle_informant_tip

            if isinstance(payload, dict):
                handle_informant_tip(state, payload)
        except Exception:
            pass
        return True

    if et == "npc_report":
        reporter = str(payload.get("reporter", "unknown") or "unknown")
        aff = str(payload.get("affiliation", "") or "").strip().lower()
        try:
            sus = int(payload.get("suspicion", 50) or 50)
        except Exception:
            sus = 50
        sus = max(0, min(100, sus))
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
        try:
            from engine.core.factions import sync_faction_statuses_from_trace

            sync_faction_statuses_from_trace(state)
        except Exception:
            pass
        _push_news(state, text=f"Tip masuk: pihak berwenang menerima laporan anon tentang player ({reporter}).", source="broadcast")
        try:
            from engine.world.heat import bump_heat, bump_suspicion

            loc0 = str(payload.get("origin_location", "") or str((state.get("player", {}) or {}).get("location", "") or "")).strip().lower()
            if loc0:
                bump_suspicion(state, loc=loc0, delta=2 + (1 if aff == "police" else 0), reason="npc_report", ttl_days=2)
                bump_heat(state, loc=loc0, delta=1, reason="npc_report", ttl_days=5)
        except Exception:
            pass
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
        return True

    if et == "paper_trail_ping":
        reporter = str(payload.get("reporter", "unknown") or "unknown")
        aff = str(payload.get("affiliation", "police") or "police").strip().lower()
        try:
            sus = int(payload.get("suspicion", 55) or 55)
        except Exception:
            sus = 55
        origin_location = str(payload.get("origin_location", "") or "").strip().lower()
        delivery_id = str(payload.get("delivery_id", "") or "").strip()
        item_id = str(payload.get("item_id", "") or "").strip()
        pend = state.setdefault("pending_events", [])
        if isinstance(pend, list):
            pend.append(
                {
                    "event_type": "npc_report",
                    "due_day": day,
                    "due_time": min(1439, time_min + 1),
                    "triggered": False,
                    "payload": {
                        "reporter": reporter,
                        "affiliation": aff,
                        "suspicion": max(0, min(100, sus)),
                        "origin_location": origin_location,
                        "meta": {"delivery_id": delivery_id, "item_id": item_id, "source": "paper_trail"},
                    },
                }
            )
        state.setdefault("world_notes", []).append(f"[PaperTrail] ping reporter={reporter} sus={sus} delivery_id={delivery_id} item={item_id}")
        try:
            from engine.world.heat import bump_heat, bump_suspicion

            loc0 = str(origin_location or str((state.get("player", {}) or {}).get("location", "") or "")).strip().lower()
            if loc0:
                bump_suspicion(state, loc=loc0, delta=2, reason="paper_trail", ttl_days=2)
                bump_heat(state, loc=loc0, delta=1, reason="paper_trail", ttl_days=6)
        except Exception:
            pass
        return True

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
        offers[npc] = {"npc": npc, "role": role, "service": service, "day": day, "expires_day": day + 2, "payload": dict(payload)}
        econ["offers"] = offers
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
        return True

    if et == "delivery_drop":
        loc = str(payload.get("location", "") or str((state.get("player", {}) or {}).get("location", "") or "")).strip().lower()
        drop_district = str(payload.get("drop_district", "") or "").strip().lower()
        iid = str(payload.get("item_id", "") or "").strip()
        nm = str(payload.get("item_name", iid) or iid)
        delivery = str(payload.get("delivery", "dead_drop") or "dead_drop").strip().lower()
        prefer = str(payload.get("prefer", "bag") or "bag").strip().lower()
        pp = int(payload.get("district_police_presence", 0) or 0)
        sting_bias = str(payload.get("sting_bias", "") or "").strip().lower()
        delivery_id = str(payload.get("delivery_id", "") or "").strip()
        world = state.setdefault("world", {})
        pd = world.setdefault("pending_deliveries", [])
        if not isinstance(pd, list):
            pd = []
            world["pending_deliveries"] = pd
        pd.append(
            {
                "delivery_id": delivery_id,
                "location": loc,
                "drop_district": drop_district,
                "item_id": iid,
                "item_name": nm,
                "delivery": delivery,
                "prefer": prefer,
                "ready_day": day,
                "ready_time": time_min,
                "expire_day": int(payload.get("expire_day", day) or day),
                "expire_time": int(payload.get("expire_time", min(1439, time_min + 60)) or min(1439, time_min + 60)),
                "sting_bias": sting_bias,
                "delivered": False,
                "expired": False,
            }
        )
        world["pending_deliveries"] = pd
        tr = state.setdefault("trace", {})
        try:
            tp = int(tr.get("trace_pct", 0) or 0)
        except Exception:
            tp = 0
        bump = 1 if delivery == "dead_drop" else 2
        if pp >= 4:
            bump += 1
        tr["trace_pct"] = max(0, min(100, tp + bump))
        try:
            from engine.core.factions import sync_faction_statuses_from_trace

            sync_faction_statuses_from_trace(state)
        except Exception:
            pass
        text = "Paketmu sudah siap diambil."
        if delivery == "dead_drop":
            text = "Dead drop aktif: paket sudah ditaruh di titik yang kamu sepakati."
        elif delivery == "courier":
            text = "Courier meet: paket sudah siap—handoff singkat sudah lewat."
        if iid:
            text += f" (item={iid})"
        if drop_district:
            text += f" drop_district={drop_district}"
        _push_news(state, text=text, source="contacts")
        _queue_ripple(
            state,
            {
                "kind": "delivery_drop",
                "text": text,
                "triggered_day": day,
                "surface_day": day,
                "surface_time": min(1439, time_min + 2),
                "surfaced": False,
                "propagation": "contacts",
                "origin_location": str(loc).strip().lower(),
                "origin_faction": "black_market",
                "witnesses": [],
                "surface_attempts": 0,
                "meta": {"item_id": iid, "delivery": delivery, "sting_bias": sting_bias},
            },
        )
        return True

    if et == "delivery_expire":
        loc = str(payload.get("location", "") or "").strip().lower()
        drop_district = str(payload.get("drop_district", "") or "").strip().lower()
        iid = str(payload.get("item_id", "") or "").strip()
        delivery = str(payload.get("delivery", "dead_drop") or "dead_drop").strip().lower()
        did0 = str(payload.get("delivery_id", "") or "").strip()
        world = state.setdefault("world", {})
        pd = world.get("pending_deliveries", []) or []
        if isinstance(pd, list) and pd:
            for row in pd:
                if not isinstance(row, dict):
                    continue
                if did0 and str(row.get("delivery_id", "") or "") != did0:
                    continue
                if not did0:
                    if str(row.get("item_id", "") or "") != iid:
                        continue
                    if str(row.get("location", "") or "").strip().lower() != loc:
                        continue
                    if drop_district and str(row.get("drop_district", "") or "").strip().lower() != drop_district:
                        continue
                if bool(row.get("delivered", False)):
                    continue
                row["expired"] = True
        nearby = (world.get("nearby_items", []) or []) if isinstance(world, dict) else []
        if isinstance(nearby, list) and nearby:
            kept = []
            for x in nearby:
                if isinstance(x, dict):
                    if did0 and str(x.get("delivery_id", "") or "") == did0:
                        continue
                    if (not did0) and str(x.get("id", "") or "") == iid and str(x.get("delivery", "") or "") == delivery:
                        continue
                kept.append(x)
            world["nearby_items"] = kept
        text = "Dead drop expired: paketmu keburu diambil orang."
        if iid:
            text += f" (item={iid})"
        _push_news(state, text=text, source="contacts")
        _queue_ripple(
            state,
            {
                "kind": "delivery_expire",
                "text": text,
                "triggered_day": day,
                "surface_day": day,
                "surface_time": min(1439, time_min + 2),
                "surfaced": False,
                "propagation": "contacts",
                "origin_location": str(loc).strip().lower(),
                "origin_faction": "black_market",
                "witnesses": [],
                "surface_attempts": 0,
                "meta": {"item_id": iid, "delivery": delivery, "delivery_id": did0},
            },
        )
        return True

    if et == "npc_sell_info":
        npc = str(payload.get("npc", "unknown") or "unknown")
        buyer = str(payload.get("buyer_faction", "black_market") or "black_market").strip().lower()
        try:
            sus = int(payload.get("suspicion", 50) or 50)
        except Exception:
            sus = 50
        sus = max(0, min(100, sus))
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
        try:
            econ3 = state.setdefault("economy", {})
            market2 = econ3.get("market", {}) or {}
            if isinstance(market2, dict):
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
        return True

    if et == "police_sweep":
        return True

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
                slot.setdefault("areas", {})
                if isinstance(slot.get("areas"), dict):
                    a = slot.get("areas") or {}
                    a["corporate_district"] = {"restricted": True, "until_day": day + 2, "reason": "corporate_lockdown"}
                    slot["areas"] = a
                m = slot.get("market")
                if not isinstance(m, dict) or not m:
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
        return True

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
            from engine.systems.quests import create_black_market_delivery_quest

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
        return True

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
        return True

    if et == "manhunt_lockdown":
        loc = str(payload.get("location", "") or str(state.get("player", {}).get("location", "") or "")).strip().lower()
        try:
            trsnap = int(payload.get("trace_snapshot", 0) or 0)
        except Exception:
            trsnap = 0
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
        return True

    if et == "debt_collection_ping":
        try:
            debt = int(payload.get("debt", 0) or 0)
        except Exception:
            debt = 0
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
        return True

    return False


def _register_event_handlers() -> None:
    from engine.world.timers_handlers_delivery import (
        handle_black_market_offer,
        handle_delivery_drop,
        handle_delivery_expire,
    )
    from engine.world.timers_handlers_economy import handle_debt_collection_ping
    from engine.world.timers_handlers_security import (
        handle_corporate_lockdown,
        handle_investigation_sweep,
        handle_manhunt_lockdown,
        handle_npc_sell_info,
        handle_police_sweep,
    )
    from engine.world.timers_handlers_social import (
        handle_informant_tip,
        handle_npc_offer,
        handle_npc_report,
        handle_paper_trail_ping,
        handle_social_diffusion_hop,
    )

    EVENT_HANDLERS.clear()
    EVENT_HANDLERS.update(
        {
            "social_diffusion_hop": handle_social_diffusion_hop,
            "informant_tip": handle_informant_tip,
            "npc_report": handle_npc_report,
            "paper_trail_ping": handle_paper_trail_ping,
            "npc_offer": handle_npc_offer,
            "delivery_drop": handle_delivery_drop,
            "delivery_expire": handle_delivery_expire,
            "npc_sell_info": handle_npc_sell_info,
            "police_sweep": handle_police_sweep,
            "corporate_lockdown": handle_corporate_lockdown,
            "black_market_offer": handle_black_market_offer,
            "investigation_sweep": handle_investigation_sweep,
            "manhunt_lockdown": handle_manhunt_lockdown,
            "debt_collection_ping": handle_debt_collection_ping,
        }
    )


_register_event_handlers()


def _apply_triggered_events(state: dict[str, Any], triggered: list[dict[str, Any]]) -> None:
    _apply_triggered_events_v2(
        state,
        triggered,
        push_news=_push_news,
        queue_ripple=_queue_ripple,
        dispatch_registered_event_handler=_dispatch_registered_event_handler,
        handle_event_legacy_by_type=_handle_event_legacy_by_type,
        event_handlers=EVENT_HANDLERS,
    )


def _collect_due_items(
    state: dict[str, Any],
    *,
    cur_day: int,
    cur_min: int,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[tuple[tuple[int, int], str, dict[str, Any]]]]:
    return _collect_due_items_v2(state, cur_day=cur_day, cur_min=cur_min)


def update_timers_v2(state: dict[str, Any], action_ctx: dict[str, Any]) -> None:
    """Composed-path alias used by dual-run equivalence harness."""
    update_timers(state, action_ctx)


def update_timers(state: dict[str, Any], action_ctx: dict[str, Any]) -> None:
    from engine.core.balance import BALANCE, get_balance_snapshot

    meta = state.setdefault("meta", {"day": 1, "time_min": 480})
    prev_day = int(meta.get("day", 1) or 1)
    # Queue hardening: keep only dict entries so malformed rows never crash tick cleanup.
    pe0 = state.get("pending_events", [])
    if not isinstance(pe0, list):
        pe0 = []
    state["pending_events"] = [ev for ev in pe0 if isinstance(ev, dict)]
    rp0 = state.get("active_ripples", [])
    if not isinstance(rp0, list):
        rp0 = []
    state["active_ripples"] = [rp for rp in rp0 if isinstance(rp, dict)]

    kind = action_ctx.get("action_type", "instant")
    if kind != "combat":
        try:
            from engine.systems.encounter_scheduler import evaluate_security_encounters

            evaluate_security_encounters(state, action_ctx)
        except Exception as e:
            try:
                from engine.core.errors import record_error

                record_error(state, "timers.evaluate_security_encounters", e)
            except Exception:
                pass
    if kind == "combat":
        action_ctx.setdefault("time_breakdown", []).append({"label": "combat", "minutes": 1})
        _advance(meta, 1)
    elif kind == "travel":
        snap = get_balance_snapshot(state)
        # Deterministic travel encounter scheduling (adds pending event; router will convert to scene when triggered).
        try:
            from engine.systems.encounter_scheduler import schedule_travel_encounters

            schedule_travel_encounters(state, action_ctx)
        except Exception as e:
            try:
                from engine.core.errors import record_error

                record_error(state, "timers.schedule_travel_encounters", e)
            except Exception:
                pass
        # Vehicle hook: adjust travel_minutes + fuel/condition/trace before other modifiers.
        try:
            from engine.systems.vehicles import apply_vehicle_to_travel

            apply_vehicle_to_travel(state, action_ctx)
        except Exception as e:
            try:
                from engine.core.errors import record_error

                record_error(state, "timers.apply_vehicle_to_travel", e)
            except Exception:
                pass
        # Trace tier: multiply travel time (and optional cash estimate) when Wanted/Lockdown.
        try:
            from engine.core.trace import apply_trace_travel_friction, get_trace_tier

            if bool(action_ctx.get("w2_travel_precalc")):
                pass
            else:
                cur_tm = int(action_ctx.get("travel_minutes", 30) or 30)
                new_tm, friction_applied = apply_trace_travel_friction(state, cur_tm)
                if friction_applied:
                    action_ctx["travel_minutes"] = new_tm
                    action_ctx.setdefault("time_breakdown", []).append(
                        {"label": "trace_friction", "minutes": int(new_tm - cur_tm)}
                    )
                    state.setdefault("world_notes", []).append(
                        "[Security] Travel friction increased due to high Trace."
                    )
                tier = get_trace_tier(state)
                mult = float(tier.get("friction_multiplier", 1.0) or 1.0)
                if mult > 1.0:
                    tcc = action_ctx.get("travel_cash_cost")
                    if isinstance(tcc, (int, float)):
                        try:
                            old_c = float(tcc)
                            action_ctx["travel_cash_cost"] = max(0, int(round(old_c * mult)))
                        except Exception:
                            pass
        except Exception:
            pass
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
                            extra += int(snap.get("travel_friction_police_sweep_min", BALANCE.travel_friction_police_sweep_min) or BALANCE.travel_friction_police_sweep_min)
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
                            extra += int(snap.get("travel_friction_lockdown_min", BALANCE.travel_friction_lockdown_min) or BALANCE.travel_friction_lockdown_min)
            if extra > 0:
                try:
                    action_ctx["travel_minutes"] = int(action_ctx.get("travel_minutes", 30) or 30) + extra
                except Exception:
                    action_ctx["travel_minutes"] = 30 + extra
                state.setdefault("world_notes", []).append(f"[Restriction] Travel friction +{extra}min")
                action_ctx.setdefault("time_breakdown", []).append({"label": "restrictions", "minutes": int(extra)})
        except Exception:
            pass
        # Weather travel modifier.
        try:
            from engine.world.weather import ensure_weather, travel_minutes_modifier
            from engine.core.balance import BALANCE

            world = state.get("world", {}) or {}
            meta2 = state.get("meta", {}) or {}
            day2 = int(meta2.get("day", 1) or 1)
            cur_loc = str(state.get("player", {}).get("location", "") or "").strip().lower()
            dest_loc = str(action_ctx.get("travel_destination", "") or "").strip().lower()
            if cur_loc:
                w_cur = ensure_weather(state, cur_loc, day2)
                kcur = str((w_cur or {}).get("kind", "") or "").lower()
                extra_w = travel_minutes_modifier(kcur)
                if kcur == "storm":
                    extra_w = int(snap.get("weather_travel_storm_min", BALANCE.weather_travel_storm_min) or BALANCE.weather_travel_storm_min)
                elif kcur == "rain":
                    extra_w = int(snap.get("weather_travel_rain_min", BALANCE.weather_travel_rain_min) or BALANCE.weather_travel_rain_min)
                elif kcur == "fog":
                    extra_w = int(snap.get("weather_travel_fog_min", BALANCE.weather_travel_fog_min) or BALANCE.weather_travel_fog_min)
                elif kcur == "windy":
                    extra_w = int(snap.get("weather_travel_windy_min", BALANCE.weather_travel_windy_min) or BALANCE.weather_travel_windy_min)
                if extra_w:
                    action_ctx["travel_minutes"] = int(action_ctx.get("travel_minutes", 30) or 30) + extra_w
                    action_ctx.setdefault("time_breakdown", []).append({"label": "weather", "minutes": int(extra_w)})
            if dest_loc:
                w_dst = ensure_weather(state, dest_loc, day2)
                kdst = str((w_dst or {}).get("kind", "") or "").lower()
                extra_w2 = travel_minutes_modifier(kdst)
                if kdst == "storm":
                    extra_w2 = int(snap.get("weather_travel_storm_min", BALANCE.weather_travel_storm_min) or BALANCE.weather_travel_storm_min)
                elif kdst == "rain":
                    extra_w2 = int(snap.get("weather_travel_rain_min", BALANCE.weather_travel_rain_min) or BALANCE.weather_travel_rain_min)
                elif kdst == "fog":
                    extra_w2 = int(snap.get("weather_travel_fog_min", BALANCE.weather_travel_fog_min) or BALANCE.weather_travel_fog_min)
                elif kdst == "windy":
                    extra_w2 = int(snap.get("weather_travel_windy_min", BALANCE.weather_travel_windy_min) or BALANCE.weather_travel_windy_min)
                if extra_w2:
                    add2 = max(0, extra_w2 - 3)
                    action_ctx["travel_minutes"] = int(action_ctx.get("travel_minutes", 30) or 30) + add2
                    if add2:
                        action_ctx.setdefault("time_breakdown", []).append({"label": "weather(dest)", "minutes": int(add2)})
        except Exception:
            pass
        # History border controls (year-aware): crossing into strict borders costs time.
        try:
            from engine.world.atlas import ensure_country_history_idx, ensure_location_profile

            meta2 = state.get("meta", {}) or {}
            sy = int(meta2.get("sim_year", 0) or 0)
            dest_loc = str(action_ctx.get("travel_destination", "") or "").strip().lower()
            if dest_loc:
                prof = ensure_location_profile(state, dest_loc)
                c = str((prof.get("country") if isinstance(prof, dict) else "") or "").strip().lower()
                if c:
                    hi = ensure_country_history_idx(state, c, sim_year=sy)
                    bc = int((hi.get("border_controls", 0) if isinstance(hi, dict) else 0) or 0)
                    extra_b = 0
                    if bc >= 80:
                        extra_b = 25
                    elif bc >= 60:
                        extra_b = 12
                    elif bc >= 45:
                        extra_b = 6
                    if extra_b:
                        action_ctx["travel_minutes"] = int(action_ctx.get("travel_minutes", 30) or 30) + extra_b
                        action_ctx.setdefault("time_breakdown", []).append({"label": "border_controls", "minutes": int(extra_b)})
        except Exception:
            pass
        # Base travel (whatever minutes currently set after modifiers).
        try:
            tm = int(action_ctx.get("travel_minutes", 30) or 30)
        except Exception:
            tm = 30
        base_guess = max(0, tm)
        # If breakdown exists, subtract known extras to approximate base.
        extras = 0
        for it in (action_ctx.get("time_breakdown") or []):
            if not isinstance(it, dict):
                continue
            label = str(it.get("label", "") or "")
            if label in ("restrictions", "weather", "weather(dest)", "border_controls", "trace_friction"):
                try:
                    extras += int(it.get("minutes", 0) or 0)
                except Exception:
                    pass
        base = max(0, base_guess - extras)
        action_ctx.setdefault("time_breakdown", []).insert(0, {"label": "travel_base", "minutes": int(base)})
        _advance(meta, int(action_ctx.get("travel_minutes", 30)))
    elif kind in ("rest", "sleep"):
        if str(kind).lower() == "sleep":
            try:
                rm = int(action_ctx.get("rested_minutes", 8 * 60) or 8 * 60)
            except Exception:
                rm = 8 * 60
            rm = max(60, min(12 * 60, rm))
            action_ctx["rested_minutes"] = rm
            action_ctx["sleep_duration_h"] = round(rm / 60.0, 2)
        action_ctx.setdefault("time_breakdown", []).append({"label": str(kind), "minutes": int(action_ctx.get("rested_minutes", 60) or 60)})
        _advance(meta, int(action_ctx.get("rested_minutes", 60)))
    else:
        action_ctx.setdefault("time_breakdown", []).append({"label": "instant", "minutes": int(action_ctx.get("instant_minutes", 2) or 2)})
        _advance(meta, int(action_ctx.get("instant_minutes", 2)))

    cur_day, cur_min = int(meta["day"]), int(meta["time_min"])
    if int(cur_day) > int(prev_day):
        _reset_daily_attrition_counters(state)
    # Daily decay for investigation heat/suspicion (once per day).
    try:
        world = state.setdefault("world", {})
        if isinstance(world, dict):
            last = int(world.get("last_heat_decay_day", 0) or 0)
            if last != int(cur_day):
                from engine.world.heat import decay_heat_and_suspicion

                decay_heat_and_suspicion(state, cur_day=int(cur_day))
                # NPC memory decay + consolidation (once per day).
                try:
                    from engine.npc.memory import process_memory_decay

                    counts = process_memory_decay(state)
                    if isinstance(counts, dict) and (counts.get("decayed") or counts.get("removed") or counts.get("consolidated")):
                        state.setdefault("world_notes", []).append(
                            f"[Memory] decayed={int(counts.get('decayed',0) or 0)} removed={int(counts.get('removed',0) or 0)} consolidated={int(counts.get('consolidated',0) or 0)}"
                        )
                except Exception:
                    pass
                world["last_heat_decay_day"] = int(cur_day)
    except Exception as e:
        try:
            from engine.core.errors import record_error

            record_error(state, "timers.decay_heat_and_suspicion", e)
        except Exception:
            pass
    _materialize_deliveries_if_arrived(state, cur_day=cur_day, cur_min=cur_min)
    # Cache sim year / tech epoch for this turn (UI + language barriers).
    try:
        from engine.world.time_model import cache_sim_time

        cache_sim_time(state)
    except Exception as e:
        try:
            from engine.core.errors import record_error

            record_error(state, "timers.cache_sim_time", e)
        except Exception:
            pass

    # Limit how many scheduled items we process per turn to avoid narrative/UI spam.
    # IMPORTANT: we do NOT change scheduling logic or sim clock; we simply defer overflow to next turn.
    cap = 3

    due_events, due_ripples, items = _collect_due_items(state, cur_day=cur_day, cur_min=cur_min)

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

    # Scheduler fairness: advance bookkeeping for due ripples that were not visited due to cap saturation.
    # This prevents immortal due ripples under sustained event pressure.
    try:
        visited = set([id(x) for x in triggered] + [id(x) for x in surfaced])
        for rp in due_ripples[:120]:
            if not isinstance(rp, dict) or rp.get("surfaced"):
                continue
            if id(rp) in visited:
                continue
            # Only act on still-due ripples.
            if (int(rp.get("surface_day", 99999)), int(rp.get("surface_time", 99999))) > (cur_day, cur_min):
                continue
            if _can_surface_ripple(state, rp):
                # Leave it due; it will be processed on a later turn when cap allows.
                continue
            rp["surface_attempts"] = int(rp.get("surface_attempts", 0) or 0) + 1
            if int(rp.get("surface_attempts", 0) or 0) >= 3:
                rp["surfaced"] = True
                rp["dropped_by_propagation"] = True
                state.setdefault("world_notes", []).append(f"Ripple dropped (no propagation): {rp.get('text', 'unknown')}")
            else:
                prop = str(rp.get("propagation", "") or "").lower()
                rp["surface_day"] = cur_day + 1
                rp["surface_time"] = 8 * 60
                if prop in ("contacts", "contact_network"):
                    rp["relay_pending"] = True
    except Exception as e:
        _record_soft_error(state, "timers.tick_disguise_expiry", e)

    state["triggered_events_this_turn"] = triggered
    if triggered:
        try:
            _apply_triggered_events(state, triggered)
        except Exception as e:
            try:
                from engine.core.errors import record_error

                record_error(state, "timers.apply_triggered_events", e)
            except Exception:
                pass
    if triggered:
        state.setdefault("world_notes", []).extend([f"Triggered event: {ev.get('title', ev.get('event_type', 'unknown'))}" for ev in triggered])
    state["surfacing_ripples_this_turn"] = surfaced
    if surfaced:
        state.setdefault("world_notes", []).extend([f"Surfaced ripple: {rp.get('text', 'unknown')}" for rp in surfaced])
        # Apply ripple effects only when they surface and are logically propagated.
        try:
            from engine.social.ripples import apply_ripple_effects

            for rp in surfaced:
                if isinstance(rp, dict) and not rp.get("dropped_by_propagation"):
                    apply_ripple_effects(state, rp)
        except Exception as e:
            try:
                from engine.core.errors import record_error

                record_error(state, "timers.apply_ripple_effects", e)
            except Exception:
                pass
        # Update NPC beliefs from surfaced ripples (contacts/witness/local).
        try:
            from engine.npc.npcs import apply_beliefs_from_ripple

            for rp in surfaced:
                if isinstance(rp, dict) and not rp.get("dropped_by_propagation"):
                    apply_beliefs_from_ripple(state, rp)
        except Exception as e:
            try:
                from engine.core.errors import record_error

                record_error(state, "timers.apply_beliefs_from_ripple", e)
            except Exception:
                pass
        # Dead NPC cleanup / non-interactable guardrail.
        try:
            from engine.npc.dead_npc import cleanup_dead_npcs

            cleanup_dead_npcs(state)
        except Exception:
            pass

    # Scene queue pump: if no active scene, start the next queued one.
    try:
        flags = state.get("flags", {}) or {}
        if isinstance(flags, dict) and bool(flags.get("scenes_enabled", True)) and state.get("active_scene") is None:
            from engine.systems.scenes import pump_scene_queue

            pump_scene_queue(state)
    except Exception as e:
        try:
            from engine.core.errors import record_error

            record_error(state, "timers.pump_scene_queue", e)
        except Exception:
            pass

    # Quest chains tick (multi-step objectives).
    try:
        from engine.systems.quests import tick_quest_chains

        tick_quest_chains(state, action_ctx)
    except Exception as e:
        try:
            from engine.core.errors import record_error

            record_error(state, "timers.tick_quest_chains", e)
        except Exception:
            pass

    # Disguise expiry tick.
    try:
        from engine.systems.disguise import tick_disguise_expiry

        tick_disguise_expiry(state)
    except Exception as e:
        _record_soft_error(state, "timers.tick_effects_expiry", e)

    # Status effects expiry tick (player + NPCs).
    try:
        from engine.systems.effects import tick_effects_expiry

        tick_effects_expiry(state)
    except Exception as e:
        _record_soft_error(state, "timers.apply_lay_low_bonus", e)

    # Safehouse lay-low bonus on rest/sleep.
    try:
        if str(action_ctx.get("action_type", "") or "") in ("rest", "sleep"):
            from engine.systems.safehouse import apply_lay_low_bonus

            apply_lay_low_bonus(state)
            from engine.systems.accommodation import apply_accommodation_rest_bonus

            apply_accommodation_rest_bonus(state)
    except Exception as e:
        _record_soft_error(state, "timers.cleanup_dead_npcs", e)

    # Archive completed items to keep active queues clean.
    if triggered:
        state.setdefault("resolved_events", []).extend(triggered)
    state["pending_events"] = [ev for ev in state.get("pending_events", []) if isinstance(ev, dict) and not bool(ev.get("triggered", False))]

    if surfaced:
        state.setdefault("resolved_ripples", []).extend(surfaced)
    state["active_ripples"] = [rp for rp in state.get("active_ripples", []) if isinstance(rp, dict) and not bool(rp.get("surfaced", False))]

    # Unified cleanup (lightweight, deterministic).
    try:
        # Keep dead NPC invariants stable even if no ripple surfaced this turn.
        from engine.npc.dead_npc import cleanup_dead_npcs

        cleanup_dead_npcs(state)
    except Exception as e:
        _record_soft_error(state, "timers.pending_deliveries_bound", e)
    try:
        # Bound pending_deliveries list to avoid unbounded save growth.
        world3 = state.get("world", {}) or {}
        pd = world3.get("pending_deliveries", []) or []
        if isinstance(pd, list) and len(pd) > 120:
            # Keep newest-ish rows; prioritize unresolved.
            unresolved = [r for r in pd if isinstance(r, dict) and not bool(r.get("delivered", False)) and not bool(r.get("expired", False))]
            resolved = [r for r in pd if isinstance(r, dict) and (bool(r.get("delivered", False)) or bool(r.get("expired", False)))]
            world3["pending_deliveries"] = (unresolved[:80] + resolved[:40])[:120]
    except Exception:
        pass


def _materialize_deliveries_if_arrived(state: dict[str, Any], *, cur_day: int, cur_min: int) -> None:
    """If a delivery is ready and player is at the drop district, spawn it into nearby_items."""
    try:
        p = state.get("player", {}) or {}
        loc = str(p.get("location", "") or "").strip().lower()
        did = str(p.get("district", "") or "").strip().lower()
    except Exception:
        return

    world = state.setdefault("world", {})
    pending = world.setdefault("pending_deliveries", [])
    if not isinstance(pending, list):
        pending = []
        world["pending_deliveries"] = pending

    changed = False
    # Fair, bounded selection: scan a larger window but spawn only a few per tick.
    MAX_SCAN = 200
    MAX_SPAWN = 3
    candidates: list[tuple[tuple[int, int], str, dict[str, Any]]] = []
    for row in pending[:MAX_SCAN]:
        if not isinstance(row, dict):
            continue
        if bool(row.get("delivered", False)) or bool(row.get("expired", False)):
            continue
        if str(row.get("location", "") or "").strip().lower() != loc:
            continue
        if str(row.get("drop_district", "") or "").strip().lower() != did:
            continue
        try:
            rd = int(row.get("ready_day", 99999) or 99999)
            rt = int(row.get("ready_time", 99999) or 99999)
        except Exception:
            rd, rt = 99999, 99999
        when = (rd, rt)
        if when > (int(cur_day), int(cur_min)):
            continue
        delivery_id = str(row.get("delivery_id", "") or "").strip()
        candidates.append((when, delivery_id, row))
    candidates.sort(key=lambda x: (x[0][0], x[0][1], x[1]))
    spawned = 0
    for _when, _did2, row in candidates:
        if spawned >= MAX_SPAWN:
            break
        _spawn_delivery_into_nearby(state, row)
        row["delivered"] = True
        changed = True
        spawned += 1
        # Scene hook: start a drop_pickup encounter when delivery materializes here.
        try:
            flags = state.get("flags", {}) or {}
            if isinstance(flags, dict) and bool(flags.get("scenes_enabled", True)) and state.get("active_scene") is None:
                from engine.systems.scenes import start_drop_pickup_scene

                start_drop_pickup_scene(state, delivery_row=row)
        except Exception:
            pass

    if changed:
        world["pending_deliveries"] = pending


def _spawn_delivery_into_nearby(state: dict[str, Any], row: dict[str, Any]) -> None:
    world = state.setdefault("world", {})
    nearby = world.setdefault("nearby_items", [])
    if not isinstance(nearby, list):
        nearby = []
        world["nearby_items"] = nearby
    iid = str(row.get("item_id", "") or "").strip()
    nm = str(row.get("item_name", iid) or iid)
    delivery = str(row.get("delivery", "dead_drop") or "dead_drop").strip().lower()
    prefer = str(row.get("prefer", "bag") or "bag").strip().lower()
    did = str(row.get("delivery_id", "") or "").strip()
    sting_bias = str(row.get("sting_bias", "") or "").strip().lower()

    # Avoid duplicates by delivery_id.
    for x in nearby:
        if isinstance(x, dict) and str(x.get("delivery_id", "") or "") == did and did:
            return

    # Decide pickup risk (decoy / sting on pickup) deterministically.
    pr = row.get("pickup_risk") if isinstance(row.get("pickup_risk"), dict) else {}
    if not isinstance(pr, dict):
        pr = {}
    if not pr:
        try:
            meta = state.get("meta", {}) or {}
            seed = str(meta.get("world_seed", "") or meta.get("seed_pack", "") or "").strip()
        except Exception:
            seed = "seed"
        try:
            tp = int((state.get("trace", {}) or {}).get("trace_pct", 0) or 0)
        except Exception:
            tp = 0
        try:
            # Use district police presence if available.
            from engine.systems.shop import _district_police_presence  # type: ignore

            pp = int(_district_police_presence(state) or 0)
        except Exception:
            pp = 0

        base = 6 if sting_bias == "higher" else 3
        base += (tp // 25) * 4
        if pp >= 4:
            base += 6
        sting_rate = max(0, min(55, int(base)))
        decoy_rate = max(0, min(35, int(sting_rate * 0.45)))
        h = hashlib.md5(f"{seed}|{did}|{iid}|pickup_risk".encode("utf-8", errors="ignore")).hexdigest()
        r = int(h[:8], 16) % 100
        pr = {
            "sting_rate": int(sting_rate),
            "decoy_rate": int(decoy_rate),
            "roll": int(r),
            "decoy": bool(r < decoy_rate),
            "sting_on_pickup": bool((r >= decoy_rate) and (r < sting_rate)),
        }
        row["pickup_risk"] = pr

    try:
        from engine.systems.ammo import item_is_ammo, rounds_per_purchase

        if callable(item_is_ammo) and item_is_ammo(state, iid):
            r = rounds_per_purchase(state, iid)
            nearby.append(
                {
                    "id": iid,
                    "name": nm,
                    "rounds": int(r),
                    "delivery": delivery,
                    "delivery_id": did,
                    "decoy": bool(pr.get("decoy", False)),
                    "sting_on_pickup": bool(pr.get("sting_on_pickup", False)),
                }
            )
        else:
            nearby.append(
                {
                    "id": iid,
                    "name": nm,
                    "delivery": delivery,
                    "prefer": prefer,
                    "delivery_id": did,
                    "decoy": bool(pr.get("decoy", False)),
                    "sting_on_pickup": bool(pr.get("sting_on_pickup", False)),
                }
            )
    except Exception:
        nearby.append(
            {
                "id": iid,
                "name": nm,
                "delivery": delivery,
                "prefer": prefer,
                "delivery_id": did,
                "decoy": bool(pr.get("decoy", False)),
                "sting_on_pickup": bool(pr.get("sting_on_pickup", False)),
            }
        )

