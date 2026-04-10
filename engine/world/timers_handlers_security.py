from __future__ import annotations

from typing import Any


def handle_police_sweep(state: dict[str, Any], ev: dict[str, Any], *, day: int, time_min: int) -> bool:
    return True


def handle_corporate_lockdown(state: dict[str, Any], ev: dict[str, Any], *, day: int, time_min: int) -> bool:
    from engine.world.timers_bus import enqueue_ripple as _queue_ripple
    from engine.world.timers_bus import push_news as _push_news

    payload = ev.get("payload") if isinstance(ev.get("payload"), dict) else {}
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


def handle_investigation_sweep(state: dict[str, Any], ev: dict[str, Any], *, day: int, time_min: int) -> bool:
    from engine.world.timers_bus import enqueue_ripple as _queue_ripple
    from engine.world.timers_bus import push_news as _push_news

    payload = ev.get("payload") if isinstance(ev.get("payload"), dict) else {}
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


def handle_manhunt_lockdown(state: dict[str, Any], ev: dict[str, Any], *, day: int, time_min: int) -> bool:
    from engine.world.timers_bus import enqueue_ripple as _queue_ripple
    from engine.world.timers_bus import push_news as _push_news

    payload = ev.get("payload") if isinstance(ev.get("payload"), dict) else {}
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


def handle_npc_sell_info(state: dict[str, Any], ev: dict[str, Any], *, day: int, time_min: int) -> bool:
    from engine.world.timers_bus import enqueue_ripple as _queue_ripple
    from engine.world.timers_bus import push_news as _push_news

    payload = ev.get("payload") if isinstance(ev.get("payload"), dict) else {}
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

