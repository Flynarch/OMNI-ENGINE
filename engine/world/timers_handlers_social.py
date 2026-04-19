from __future__ import annotations

from engine.core.error_taxonomy import log_swallowed_exception
from typing import Any

from engine.core.factions import sync_faction_statuses_from_trace
from engine.social.informants import maybe_queue_informant_tip
from engine.social.investigation_chains import handle_informant_tip as informant_tip_investigation_chain
from engine.social.social_diffusion import propagate_rumor
from engine.world.heat import bump_heat, bump_suspicion
from engine.world.timers_bus import enqueue_ripple as _queue_ripple
from engine.world.timers_bus import push_news as _push_news


def handle_social_diffusion_hop(state: dict[str, Any], ev: dict[str, Any], *, day: int, time_min: int) -> bool:
    payload = ev.get("payload") if isinstance(ev.get("payload"), dict) else {}

    frm = str(payload.get("from_npc", "") or "").strip()
    to = str(payload.get("to_npc", "") or "").strip()
    rumor = str(payload.get("rumor", "") or "").strip()
    cat = str(payload.get("category", "") or "").strip()
    try:
        hop = int(payload.get("hop", 0) or 0)
    except Exception as _omni_sw_19:
        log_swallowed_exception('engine/world/timers_handlers_social.py:19', _omni_sw_19)
        hop = 0
    if not (frm and to and rumor and cat):
        return True

    try:
        meta2 = state.get("meta", {}) or {}
        turn2 = int(meta2.get("turn", 0) or 0)
    except Exception as _omni_sw_27:
        log_swallowed_exception('engine/world/timers_handlers_social.py:27', _omni_sw_27)
        turn2 = 0

    world2 = state.setdefault("world", {})
    sd = world2.setdefault("social_diffusion", {})
    if not isinstance(sd, dict):
        sd = {}
        world2["social_diffusion"] = sd
    try:
        sd_day = int(sd.get("day", 0) or 0)
    except Exception as _omni_sw_37:
        log_swallowed_exception('engine/world/timers_handlers_social.py:37', _omni_sw_37)
        sd_day = 0
    try:
        sd_turn = int(sd.get("turn", -1) or -1)
    except Exception as _omni_sw_41:
        log_swallowed_exception('engine/world/timers_handlers_social.py:41', _omni_sw_41)
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
    except Exception as _omni_sw_62:
        log_swallowed_exception('engine/world/timers_handlers_social.py:62', _omni_sw_62)
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
        maybe_queue_informant_tip(
            state,
            from_npc=frm,
            to_npc=to,
            rumor=rumor,
            category=cat,
            hop=hop,
        )
    except Exception as _omni_sw_96:
        log_swallowed_exception('engine/world/timers_handlers_social.py:96', _omni_sw_96)
    state.setdefault("world_notes", []).append(f"[SocialDiffusion] {to} mendengar: {rumor[:90]}")
    return True


def handle_informant_tip(state: dict[str, Any], ev: dict[str, Any], *, day: int, time_min: int) -> bool:
    payload = ev.get("payload") if isinstance(ev.get("payload"), dict) else {}
    try:
        if isinstance(payload, dict):
            informant_tip_investigation_chain(state, payload)
    except Exception as _omni_sw_109:
        log_swallowed_exception('engine/world/timers_handlers_social.py:109', _omni_sw_109)
    return True


def handle_npc_report(state: dict[str, Any], ev: dict[str, Any], *, day: int, time_min: int) -> bool:
    payload = ev.get("payload") if isinstance(ev.get("payload"), dict) else {}

    reporter = str(payload.get("reporter", "unknown") or "unknown")
    aff = str(payload.get("affiliation", "") or "").strip().lower()
    try:
        sus = int(payload.get("suspicion", 50) or 50)
    except Exception as _omni_sw_123:
        log_swallowed_exception('engine/world/timers_handlers_social.py:123', _omni_sw_123)
        sus = 50
    sus = max(0, min(100, sus))
    tr = state.setdefault("trace", {})
    try:
        tp = int(tr.get("trace_pct", 0) or 0)
    except Exception as _omni_sw_129:
        log_swallowed_exception('engine/world/timers_handlers_social.py:129', _omni_sw_129)
        tp = 0
    before_tp = tp
    bump = 1 + int((sus - 50) / 20)
    if aff == "police":
        bump += 1
    tp = max(0, min(100, tp + max(1, min(5, bump))))
    tr["trace_pct"] = tp
    trace_delta = tp - before_tp

    try:
        sync_faction_statuses_from_trace(state)
    except Exception as _omni_sw_143:
        log_swallowed_exception('engine/world/timers_handlers_social.py:143', _omni_sw_143)
    _push_news(state, text=f"Tip masuk: pihak berwenang menerima laporan anon tentang player ({reporter}).", source="broadcast")
    try:
        loc0 = str(payload.get("origin_location", "") or str((state.get("player", {}) or {}).get("location", "") or "")).strip().lower()
        if loc0:
            bump_suspicion(state, loc=loc0, delta=2 + (1 if aff == "police" else 0), reason="npc_report", ttl_days=2)
            bump_heat(state, loc=loc0, delta=1, reason="npc_report", ttl_days=5)
    except Exception as _omni_sw_153:
        log_swallowed_exception('engine/world/timers_handlers_social.py:153', _omni_sw_153)
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


def handle_paper_trail_ping(state: dict[str, Any], ev: dict[str, Any], *, day: int, time_min: int) -> bool:
    payload = ev.get("payload") if isinstance(ev.get("payload"), dict) else {}
    reporter = str(payload.get("reporter", "unknown") or "unknown")
    aff = str(payload.get("affiliation", "police") or "police").strip().lower()
    try:
        sus = int(payload.get("suspicion", 55) or 55)
    except Exception as _omni_sw_182:
        log_swallowed_exception('engine/world/timers_handlers_social.py:182', _omni_sw_182)
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
        loc0 = str(origin_location or str((state.get("player", {}) or {}).get("location", "") or "")).strip().lower()
        if loc0:
            bump_suspicion(state, loc=loc0, delta=2, reason="paper_trail", ttl_days=2)
            bump_heat(state, loc=loc0, delta=1, reason="paper_trail", ttl_days=6)
    except Exception as _omni_sw_212:
        log_swallowed_exception('engine/world/timers_handlers_social.py:212', _omni_sw_212)
    return True


def handle_npc_offer(state: dict[str, Any], ev: dict[str, Any], *, day: int, time_min: int) -> bool:
    payload = ev.get("payload") if isinstance(ev.get("payload"), dict) else {}

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
                except Exception as _omni_sw_244:
                    log_swallowed_exception('engine/world/timers_handlers_social.py:244', _omni_sw_244)
                    sc = 0
                try:
                    px = int(row.get("price_idx", 100) or 100)
                except Exception as _omni_sw_248:
                    log_swallowed_exception('engine/world/timers_handlers_social.py:248', _omni_sw_248)
                    px = 100
                row["scarcity"] = max(0, sc - 1)
                row["price_idx"] = max(60, min(180, px - 1))
                market[cat] = row
                econ2["market"] = market
    except Exception as _omni_sw_254:
        log_swallowed_exception('engine/world/timers_handlers_social.py:254', _omni_sw_254)
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

