from __future__ import annotations

from typing import Any, Callable


def apply_triggered_events(
    state: dict[str, Any],
    triggered: list[dict[str, Any]],
    *,
    push_news: Callable[..., None],
    queue_ripple: Callable[..., None],
    dispatch_registered_event_handler: Callable[..., bool],
    handle_event_legacy_by_type: Callable[..., bool],
    event_handlers: dict[str, Any],
) -> None:
    if not triggered:
        return
    meta = state.get("meta", {}) or {}
    day = int(meta.get("day", 1) or 1)
    time_min = int(meta.get("time_min", 0) or 0)
    for ev in triggered:
        if not isinstance(ev, dict):
            continue
        et = str(ev.get("event_type", "") or "")
        payload = ev.get("payload") if isinstance(ev.get("payload"), dict) else {}
        try:
            from engine.systems.encounter_router import audit_casefile_for_event

            audit_casefile_for_event(state, ev)
        except Exception:
            pass
        routed_fp: dict[str, Any] | None = None
        try:
            from engine.systems.encounter_router import foreshadow_for_routed_event

            fp = foreshadow_for_routed_event(state, ev)
            if isinstance(fp, dict):
                routed_fp = fp
        except Exception:
            pass
        if isinstance(routed_fp, dict):
            try:
                from engine.systems.encounter_router import handle_triggered_event

                handle_triggered_event(state, ev)
                text = str(routed_fp.get("text", "") or "").strip()
                if text:
                    push_news(state, text=text, source=str(routed_fp.get("news_source", "police") or "police"))
                queue_ripple(
                    state,
                    {
                        "kind": str(routed_fp.get("ripple_kind", et) or et),
                        "text": text or et,
                        "triggered_day": day,
                        "surface_day": day,
                        "surface_time": min(1439, time_min + 2),
                        "surfaced": False,
                        "propagation": "local_witness",
                        "origin_location": str(routed_fp.get("origin_location", "") or "").strip().lower(),
                        "origin_faction": str(routed_fp.get("origin_faction", "") or "").strip().lower() or "police",
                        "witnesses": [],
                        "surface_attempts": 0,
                        "meta": routed_fp.get("meta") if isinstance(routed_fp.get("meta"), dict) else {},
                    },
                )
            except Exception:
                state.setdefault("world_notes", []).append(f"[Timers] router-first handler failed for event_type={et}")
            continue
        handled_by_registry = dispatch_registered_event_handler(state, ev, day=day, time_min=time_min)
        if handled_by_registry:
            continue
        if et in event_handlers:
            state.setdefault("world_notes", []).append(f"[Timers] registered handler failed for event_type={et}")
            continue
        handle_event_legacy_by_type(state, et=et, payload=payload, day=day, time_min=time_min)
