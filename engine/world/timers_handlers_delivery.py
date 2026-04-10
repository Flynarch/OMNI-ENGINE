from __future__ import annotations

from typing import Any


def handle_delivery_drop(state: dict[str, Any], ev: dict[str, Any], *, day: int, time_min: int) -> bool:
    from engine.world.timers import _handle_event_legacy_by_type

    payload = ev.get("payload") if isinstance(ev.get("payload"), dict) else {}
    return _handle_event_legacy_by_type(state, et="delivery_drop", payload=payload, day=day, time_min=time_min)


def handle_delivery_expire(state: dict[str, Any], ev: dict[str, Any], *, day: int, time_min: int) -> bool:
    from engine.world.timers import _handle_event_legacy_by_type

    payload = ev.get("payload") if isinstance(ev.get("payload"), dict) else {}
    return _handle_event_legacy_by_type(state, et="delivery_expire", payload=payload, day=day, time_min=time_min)


def handle_black_market_offer(state: dict[str, Any], ev: dict[str, Any], *, day: int, time_min: int) -> bool:
    from engine.world.timers import _handle_event_legacy_by_type

    payload = ev.get("payload") if isinstance(ev.get("payload"), dict) else {}
    return _handle_event_legacy_by_type(state, et="black_market_offer", payload=payload, day=day, time_min=time_min)

