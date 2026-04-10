from __future__ import annotations

from typing import Any, Callable


def dispatch_police_auto(
    scene_type: str,
    *,
    state: dict[str, Any],
    sc: dict[str, Any],
    phase_before: str,
    auto_police_stop: Callable[..., dict[str, Any]],
    auto_checkpoint_sweep: Callable[..., dict[str, Any]],
    auto_traffic_stop: Callable[..., dict[str, Any]],
    auto_vehicle_search: Callable[..., dict[str, Any]],
    auto_border_control: Callable[..., dict[str, Any]],
) -> dict[str, Any] | None:
    st = str(scene_type or "").strip().lower()
    if st == "police_stop":
        return auto_police_stop(state, sc, phase_before=phase_before)
    if st == "checkpoint_sweep":
        return auto_checkpoint_sweep(state, sc, phase_before=phase_before)
    if st == "traffic_stop":
        return auto_traffic_stop(state, sc, phase_before=phase_before)
    if st == "vehicle_search":
        return auto_vehicle_search(state, sc, phase_before=phase_before)
    if st == "border_control":
        return auto_border_control(state, sc, phase_before=phase_before)
    return None


def dispatch_police_advance(
    scene_type: str,
    *,
    state: dict[str, Any],
    sc: dict[str, Any],
    action_ctx: dict[str, Any],
    advance_police_stop: Callable[..., dict[str, Any]],
    advance_checkpoint_sweep: Callable[..., dict[str, Any]],
    advance_traffic_stop: Callable[..., dict[str, Any]],
    advance_vehicle_search: Callable[..., dict[str, Any]],
    advance_border_control: Callable[..., dict[str, Any]],
) -> dict[str, Any] | None:
    st = str(scene_type or "").strip().lower()
    if st == "police_stop":
        return advance_police_stop(state, sc, action_ctx)
    if st == "checkpoint_sweep":
        return advance_checkpoint_sweep(state, sc, action_ctx)
    if st == "traffic_stop":
        return advance_traffic_stop(state, sc, action_ctx)
    if st == "vehicle_search":
        return advance_vehicle_search(state, sc, action_ctx)
    if st == "border_control":
        return advance_border_control(state, sc, action_ctx)
    return None

