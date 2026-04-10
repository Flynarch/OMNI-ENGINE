from __future__ import annotations

from typing import Any


def handle_social_diffusion_hop(state: dict[str, Any], ev: dict[str, Any], *, day: int, time_min: int) -> bool:
    from engine.world.timers import _handle_event_legacy_by_type

    payload = ev.get("payload") if isinstance(ev.get("payload"), dict) else {}
    return _handle_event_legacy_by_type(state, et="social_diffusion_hop", payload=payload, day=day, time_min=time_min)


def handle_informant_tip(state: dict[str, Any], ev: dict[str, Any], *, day: int, time_min: int) -> bool:
    from engine.world.timers import _handle_event_legacy_by_type

    payload = ev.get("payload") if isinstance(ev.get("payload"), dict) else {}
    return _handle_event_legacy_by_type(state, et="informant_tip", payload=payload, day=day, time_min=time_min)


def handle_npc_report(state: dict[str, Any], ev: dict[str, Any], *, day: int, time_min: int) -> bool:
    from engine.world.timers import _handle_event_legacy_by_type

    payload = ev.get("payload") if isinstance(ev.get("payload"), dict) else {}
    return _handle_event_legacy_by_type(state, et="npc_report", payload=payload, day=day, time_min=time_min)


def handle_paper_trail_ping(state: dict[str, Any], ev: dict[str, Any], *, day: int, time_min: int) -> bool:
    from engine.world.timers import _handle_event_legacy_by_type

    payload = ev.get("payload") if isinstance(ev.get("payload"), dict) else {}
    return _handle_event_legacy_by_type(state, et="paper_trail_ping", payload=payload, day=day, time_min=time_min)


def handle_npc_offer(state: dict[str, Any], ev: dict[str, Any], *, day: int, time_min: int) -> bool:
    from engine.world.timers import _handle_event_legacy_by_type

    payload = ev.get("payload") if isinstance(ev.get("payload"), dict) else {}
    return _handle_event_legacy_by_type(state, et="npc_offer", payload=payload, day=day, time_min=time_min)

