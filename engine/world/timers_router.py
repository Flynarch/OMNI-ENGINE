from __future__ import annotations

from engine.core.error_taxonomy import log_swallowed_exception
from engine.systems.storyteller_director import StorytellerDirector
from typing import Any, Callable, Literal

import engine.systems.encounter_router as _encounter_router


def apply_triggered_events(
    state: dict[str, Any],
    triggered: list[dict[str, Any]],
    *,
    push_news: Callable[..., None],
    queue_ripple: Callable[..., None],
    dispatch_registered_event_handler: Callable[..., Literal["handled", "miss", "failed"]],
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
        st_sig = StorytellerDirector().router_signal(state, event_type=et)
        try:
            surf_shift = int(st_sig.get("surface_time_shift_min", 0) or 0)
        except Exception:
            surf_shift = 0
        payload = ev.get("payload") if isinstance(ev.get("payload"), dict) else {}
        try:
            _encounter_router.audit_casefile_for_event(state, ev)
        except Exception as _omni_sw_30:
            log_swallowed_exception('engine/world/timers_router.py:30', _omni_sw_30)
        routed_fp: dict[str, Any] | None = None
        try:
            fp = _encounter_router.foreshadow_for_routed_event(state, ev)
            if isinstance(fp, dict):
                routed_fp = fp
        except Exception as _omni_sw_39:
            log_swallowed_exception('engine/world/timers_router.py:39', _omni_sw_39)
        if isinstance(routed_fp, dict):
            try:
                _encounter_router.handle_triggered_event(state, ev)
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
                        "surface_time": min(1439, max(0, time_min + 2 + surf_shift)),
                        "surfaced": False,
                        "propagation": "local_witness",
                        "origin_location": str(routed_fp.get("origin_location", "") or "").strip().lower(),
                        "origin_faction": str(routed_fp.get("origin_faction", "") or "").strip().lower() or "police",
                        "witnesses": [],
                        "surface_attempts": 0,
                        "meta": routed_fp.get("meta") if isinstance(routed_fp.get("meta"), dict) else {},
                    },
                )
                if str(st_sig.get("mode", "neutral")) in ("build", "release"):
                    state.setdefault("world_notes", []).append(
                        f"[Storyteller] pacing={st_sig.get('mode')} event={et}"
                    )
            except Exception as _omni_sw_66:
                log_swallowed_exception('engine/world/timers_router.py:66', _omni_sw_66)
                state.setdefault("world_notes", []).append(f"[Timers] router-first handler failed for event_type={et}")
            continue
        reg_disp = dispatch_registered_event_handler(state, ev, day=day, time_min=time_min)
        if reg_disp == "handled":
            continue
        if reg_disp == "failed":
            state.setdefault("world_notes", []).append(
                f"[Timers] event handler fault for {et}; deterministic legacy fallback engaged."
            )
        handle_event_legacy_by_type(state, et=et, payload=payload, day=day, time_min=time_min)
