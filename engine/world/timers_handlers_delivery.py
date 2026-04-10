from __future__ import annotations

from typing import Any


def handle_delivery_drop(state: dict[str, Any], ev: dict[str, Any], *, day: int, time_min: int) -> bool:
    payload = ev.get("payload") if isinstance(ev.get("payload"), dict) else {}
    from engine.world.timers import _push_news, _queue_ripple

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


def handle_delivery_expire(state: dict[str, Any], ev: dict[str, Any], *, day: int, time_min: int) -> bool:
    payload = ev.get("payload") if isinstance(ev.get("payload"), dict) else {}
    from engine.world.timers import _push_news, _queue_ripple

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


def handle_black_market_offer(state: dict[str, Any], ev: dict[str, Any], *, day: int, time_min: int) -> bool:
    payload = ev.get("payload") if isinstance(ev.get("payload"), dict) else {}
    from engine.world.timers import _push_news, _queue_ripple

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

