from __future__ import annotations

from typing import Any


def handle_debt_collection_ping(state: dict[str, Any], ev: dict[str, Any], *, day: int, time_min: int) -> bool:
    from engine.world.timers import _handle_event_legacy_by_type

    payload = ev.get("payload") if isinstance(ev.get("payload"), dict) else {}
    return _handle_event_legacy_by_type(state, et="debt_collection_ping", payload=payload, day=day, time_min=time_min)

