from __future__ import annotations

from typing import Any


def collect_due_items(
    state: dict[str, Any],
    *,
    cur_day: int,
    cur_min: int,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[tuple[tuple[int, int], str, dict[str, Any]]]]:
    due_events: list[dict[str, Any]] = []
    for ev in state.get("pending_events", []):
        if not isinstance(ev, dict) or ev.get("triggered"):
            continue
        if (int(ev.get("due_day", 99999)), int(ev.get("due_time", 99999))) <= (cur_day, cur_min):
            due_events.append(ev)

    due_ripples: list[dict[str, Any]] = []
    for rp in state.get("active_ripples", []):
        if not isinstance(rp, dict) or rp.get("surfaced"):
            continue
        if (int(rp.get("surface_day", 99999)), int(rp.get("surface_time", 99999))) <= (cur_day, cur_min):
            due_ripples.append(rp)

    items: list[tuple[tuple[int, int], str, dict[str, Any]]] = []
    for ev in due_events:
        items.append(((int(ev.get("due_day", 99999)), int(ev.get("due_time", 99999))), "event", ev))
    for rp in due_ripples:
        items.append(((int(rp.get("surface_day", 99999)), int(rp.get("surface_time", 99999))), "ripple", rp))
    items.sort(key=lambda x: (x[0][0], x[0][1], x[1]))
    return due_events, due_ripples, items
