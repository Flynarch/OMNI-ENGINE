from __future__ import annotations

from typing import Any, Callable


def dispatch_delivery_advance(
    scene_type: str,
    *,
    state: dict[str, Any],
    sc: dict[str, Any],
    action_ctx: dict[str, Any],
    advance_drop_pickup: Callable[..., dict[str, Any]],
) -> dict[str, Any] | None:
    st = str(scene_type or "").strip().lower()
    if st == "drop_pickup":
        return advance_drop_pickup(state, sc, action_ctx)
    return None

