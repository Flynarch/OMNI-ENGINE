from __future__ import annotations

from typing import Any, Callable


def dispatch_sting_auto(
    scene_type: str,
    *,
    state: dict[str, Any],
    sc: dict[str, Any],
    phase_before: str,
    auto_sting_setup: Callable[..., dict[str, Any]],
) -> dict[str, Any] | None:
    st = str(scene_type or "").strip().lower()
    if st == "sting_setup":
        return auto_sting_setup(state, sc, phase_before=phase_before)
    return None


def dispatch_sting_advance(
    scene_type: str,
    *,
    state: dict[str, Any],
    sc: dict[str, Any],
    action_ctx: dict[str, Any],
    advance_sting_setup: Callable[..., dict[str, Any]],
    advance_sting_operation: Callable[..., dict[str, Any]],
) -> dict[str, Any] | None:
    st = str(scene_type or "").strip().lower()
    if st == "sting_setup":
        return advance_sting_setup(state, sc, action_ctx)
    if st == "sting_operation":
        return advance_sting_operation(state, sc, action_ctx)
    return None

