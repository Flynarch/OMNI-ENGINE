from __future__ import annotations

from typing import Any


def handle_police_sweep(state: dict[str, Any], ev: dict[str, Any], *, day: int, time_min: int) -> bool:
    from engine.world.timers import _handle_event_legacy_by_type

    payload = ev.get("payload") if isinstance(ev.get("payload"), dict) else {}
    return _handle_event_legacy_by_type(state, et="police_sweep", payload=payload, day=day, time_min=time_min)


def handle_corporate_lockdown(state: dict[str, Any], ev: dict[str, Any], *, day: int, time_min: int) -> bool:
    from engine.world.timers import _handle_event_legacy_by_type

    payload = ev.get("payload") if isinstance(ev.get("payload"), dict) else {}
    return _handle_event_legacy_by_type(state, et="corporate_lockdown", payload=payload, day=day, time_min=time_min)


def handle_investigation_sweep(state: dict[str, Any], ev: dict[str, Any], *, day: int, time_min: int) -> bool:
    from engine.world.timers import _handle_event_legacy_by_type

    payload = ev.get("payload") if isinstance(ev.get("payload"), dict) else {}
    return _handle_event_legacy_by_type(state, et="investigation_sweep", payload=payload, day=day, time_min=time_min)


def handle_manhunt_lockdown(state: dict[str, Any], ev: dict[str, Any], *, day: int, time_min: int) -> bool:
    from engine.world.timers import _handle_event_legacy_by_type

    payload = ev.get("payload") if isinstance(ev.get("payload"), dict) else {}
    return _handle_event_legacy_by_type(state, et="manhunt_lockdown", payload=payload, day=day, time_min=time_min)


def handle_npc_sell_info(state: dict[str, Any], ev: dict[str, Any], *, day: int, time_min: int) -> bool:
    from engine.world.timers import _handle_event_legacy_by_type

    payload = ev.get("payload") if isinstance(ev.get("payload"), dict) else {}
    return _handle_event_legacy_by_type(state, et="npc_sell_info", payload=payload, day=day, time_min=time_min)

