from __future__ import annotations

from typing import Any


def handle_debt_collection_ping(state: dict[str, Any], ev: dict[str, Any], *, day: int, time_min: int) -> bool:
    from engine.world.timers import _push_news, _queue_ripple

    payload = ev.get("payload") if isinstance(ev.get("payload"), dict) else {}
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

