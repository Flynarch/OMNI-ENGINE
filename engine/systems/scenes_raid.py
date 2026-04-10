from __future__ import annotations

from typing import Any, Callable


def dispatch_raid_auto(
    scene_type: str,
    *,
    state: dict[str, Any],
    sc: dict[str, Any],
    phase_before: str,
    auto_safehouse_raid: Callable[..., dict[str, Any]],
    auto_raid_response: Callable[..., dict[str, Any]],
) -> dict[str, Any] | None:
    st = str(scene_type or "").strip().lower()
    if st == "safehouse_raid":
        return auto_safehouse_raid(state, sc, phase_before=phase_before)
    if st == "raid_response":
        return auto_raid_response(state, sc, phase_before=phase_before)
    return None


def dispatch_raid_advance(
    scene_type: str,
    *,
    state: dict[str, Any],
    sc: dict[str, Any],
    action_ctx: dict[str, Any],
    advance_safehouse_raid: Callable[..., dict[str, Any]],
    advance_raid_response: Callable[..., dict[str, Any]],
) -> dict[str, Any] | None:
    st = str(scene_type or "").strip().lower()
    if st == "safehouse_raid":
        return advance_safehouse_raid(state, sc, action_ctx)
    if st == "raid_response":
        return advance_raid_response(state, sc, action_ctx)
    return None

