from __future__ import annotations

from typing import Any
import hashlib

from engine.systems.scenes_delivery import dispatch_delivery_advance
from engine.systems.scenes_police import dispatch_police_advance, dispatch_police_auto
from engine.systems.scenes_raid import dispatch_raid_advance, dispatch_raid_auto
from engine.systems.scene_roll import _now, _player_loc, _seed_key, scene_rng
from engine.systems.scenes_sting import dispatch_sting_advance, dispatch_sting_auto

from engine.core.errors import record_error
from engine.core.factions import sync_faction_statuses_from_trace
from engine.player.inventory_ops import apply_inventory_ops
from engine.social.police_check import (
    _firearm_policy_for_country,
    _has_illegal_weapon,
    _has_weapon_permit,
    schedule_weapon_check,
)
from engine.systems.arrest import execute_arrest
from engine.systems.search_conceal import apply_conceal, apply_dump, resolve_search
from engine.world.atlas import ensure_location_profile
from engine.world.casefile import append_casefile
from engine.world.heat import bump_heat, bump_suspicion


def _record_soft_error(state: dict[str, Any], scope: str, err: Exception) -> None:
    try:
        record_error(state, scope, err)
    except Exception:
        pass


def has_active_scene(state: dict[str, Any]) -> bool:
    return isinstance(state.get("active_scene"), dict) and bool((state.get("active_scene") or {}).get("scene_type"))


def active_scene(state: dict[str, Any]) -> dict[str, Any] | None:
    s = state.get("active_scene")
    return s if isinstance(s, dict) else None


def clear_active_scene(state: dict[str, Any]) -> None:
    state["active_scene"] = None


def enqueue_scene(state: dict[str, Any], row: dict[str, Any]) -> bool:
    """Queue a scene descriptor for later (when no scene is active)."""
    if not isinstance(row, dict) or not row:
        return False
    q = state.setdefault("scene_queue", [])
    if not isinstance(q, list):
        q = []
        state["scene_queue"] = q
    # Avoid obvious duplicates.
    try:
        sig = str(row.get("sig", "") or "").strip()
        if sig:
            for it in q[-12:]:
                if isinstance(it, dict) and str(it.get("sig", "") or "").strip() == sig:
                    return False
    except Exception as e:
        _record_soft_error(state, "scenes.enqueue_scene.dedupe", e)
    q.append(row)
    state["scene_queue"] = q[-24:]
    return True


def pump_scene_queue(state: dict[str, Any]) -> dict[str, Any] | None:
    """If no active scene, start the next queued scene (if any)."""
    if has_active_scene(state):
        return None
    flags = state.get("flags", {}) or {}
    if isinstance(flags, dict) and not bool(flags.get("scenes_enabled", True)):
        return None
    q = state.get("scene_queue", [])
    if not isinstance(q, list) or not q:
        return None
    row = q.pop(0)
    state["scene_queue"] = q
    if not isinstance(row, dict):
        return None
    st = str(row.get("scene_type", "") or "").strip().lower()
    if st == "police_stop":
        payload = row.get("payload") if isinstance(row.get("payload"), dict) else {}
        return start_police_stop_scene(state, payload=payload)
    if st == "sting_setup":
        payload = row.get("payload") if isinstance(row.get("payload"), dict) else {}
        return start_sting_setup_scene(state, payload=payload)
    if st == "safehouse_raid":
        payload = row.get("payload") if isinstance(row.get("payload"), dict) else {}
        return start_safehouse_raid_scene(state, payload=payload)
    if st == "raid_response":
        payload = row.get("payload") if isinstance(row.get("payload"), dict) else {}
        return start_raid_response_scene(state, payload=payload)
    if st == "checkpoint_sweep":
        payload = row.get("payload") if isinstance(row.get("payload"), dict) else {}
        return start_checkpoint_sweep_scene(state, payload=payload)
    if st == "traffic_stop":
        payload = row.get("payload") if isinstance(row.get("payload"), dict) else {}
        return start_traffic_stop_scene(state, payload=payload)
    if st == "vehicle_search":
        payload = row.get("payload") if isinstance(row.get("payload"), dict) else {}
        return start_vehicle_search_scene(state, payload=payload)
    if st == "border_control":
        payload = row.get("payload") if isinstance(row.get("payload"), dict) else {}
        return start_border_control_scene(state, payload=payload)
    if st == "drop_pickup":
        delivery_row = row.get("delivery_row") if isinstance(row.get("delivery_row"), dict) else {}
        return start_drop_pickup_scene(state, delivery_row=delivery_row)
    return None


def _scene_return(
    *,
    ok: bool,
    reason: str,
    phase_before: str,
    phase_after: str,
    ended: bool,
    next_options: list[str],
    effects: list[dict[str, Any]],
    messages: list[str],
) -> dict[str, Any]:
    return {
        "ok": bool(ok),
        "reason": str(reason or ""),
        "phase_before": str(phase_before or ""),
        "phase_after": str(phase_after or ""),
        "ended": bool(ended),
        "next_options": list(next_options or []),
        "effects": list(effects or []),
        "messages": list(messages or []),
    }


def start_drop_pickup_scene(state: dict[str, Any], *, delivery_row: dict[str, Any]) -> dict[str, Any]:
    """Start drop_pickup scene from a materialized delivery row (pending_deliveries entry)."""
    if has_active_scene(state):
        return {"ok": False, "reason": "scene_already_active"}
    flags = state.get("flags", {}) or {}
    if isinstance(flags, dict) and not bool(flags.get("scenes_enabled", True)):
        return {"ok": False, "reason": "scenes_disabled"}

    loc, did = _player_loc(state)
    drop_district = str(delivery_row.get("drop_district", "") or "").strip().lower()
    if not (loc and did and drop_district and did == drop_district):
        return {"ok": False, "reason": "not_at_drop_point"}

    delivery_id = str(delivery_row.get("delivery_id", "") or "").strip()
    iid = str(delivery_row.get("item_id", "") or "").strip()
    if not (delivery_id and iid):
        return {"ok": False, "reason": "missing_delivery_fields"}

    day, tmin = _now(state)
    # Default scene expiry: align to delivery expiry if present, else 60 minutes.
    try:
        exp_day = int(delivery_row.get("expire_day", day) or day)
    except Exception:
        exp_day = day
    try:
        exp_time = int(delivery_row.get("expire_time", min(1439, tmin + 60)) or min(1439, tmin + 60))
    except Exception:
        exp_time = min(1439, tmin + 60)

    scene_id = hashlib.md5(f"{_seed_key(state)}|{delivery_id}|drop_pickup".encode("utf-8", errors="ignore")).hexdigest()[:10]
    sc = {
        "scene_id": scene_id,
        "scene_type": "drop_pickup",
        "phase": "spot_package",
        "context": {
            "location": loc,
            "district": did,
            "delivery_id": delivery_id,
            "item_id": iid,
            "item_name": str(delivery_row.get("item_name", iid) or iid),
            "delivery": str(delivery_row.get("delivery", "dead_drop") or "dead_drop"),
            "drop_district": drop_district,
            "delivery_expire_at": {"day": int(exp_day), "time_min": int(exp_time)},
        },
        "vars": {"wait_count": 0},
        "expires_at": {"day": int(exp_day), "time_min": int(exp_time)},
        "next_options": ["SCENE APPROACH", "SCENE ABORT", "SCENE WAIT"],
    }
    state["active_scene"] = sc
    state.setdefault("world_notes", []).append(f"[Scene] start drop_pickup delivery_id={delivery_id} item={iid}")
    return {"ok": True, "scene_id": scene_id, "scene_type": "drop_pickup"}


def auto_resolve_scene_if_needed(state: dict[str, Any], *, cur_day: int, cur_time: int) -> dict[str, Any] | None:
    sc = active_scene(state)
    if not sc:
        return None
    exp = sc.get("expires_at") if isinstance(sc.get("expires_at"), dict) else {}
    try:
        ed = int((exp or {}).get("day", 99999) or 99999)
    except Exception:
        ed = 99999
    try:
        et = int((exp or {}).get("time_min", 99999) or 99999)
    except Exception:
        et = 99999
    if (ed, et) > (int(cur_day), int(cur_time)):
        return None

    # Scene-specific timeout behavior (matang: never silently drop consequences).
    st = str(sc.get("scene_type", "") or "").strip().lower()
    phase_before = str(sc.get("phase", "") or "")
    r_sting = dispatch_sting_auto(st, state=state, sc=sc, phase_before=phase_before, auto_sting_setup=_auto_resolve_sting_setup)
    if isinstance(r_sting, dict):
        return r_sting
    r_raid = dispatch_raid_auto(
        st,
        state=state,
        sc=sc,
        phase_before=phase_before,
        auto_safehouse_raid=_auto_resolve_safehouse_raid,
        auto_raid_response=_auto_resolve_raid_response,
    )
    if isinstance(r_raid, dict):
        return r_raid
    r_pol = dispatch_police_auto(
        st,
        state=state,
        sc=sc,
        phase_before=phase_before,
        auto_police_stop=_auto_resolve_police_stop,
        auto_checkpoint_sweep=_auto_resolve_checkpoint_sweep,
        auto_traffic_stop=_auto_resolve_traffic_stop,
        auto_vehicle_search=_auto_resolve_vehicle_search,
        auto_border_control=_auto_resolve_border_control,
    )
    if isinstance(r_pol, dict):
        return r_pol

    clear_active_scene(state)
    msg = "Scene expired and auto-resolved."
    state.setdefault("world_notes", []).append(f"[Scene] auto_resolve expired (phase={phase_before})")
    return _scene_return(
        ok=True,
        reason="auto_resolved_expired",
        phase_before=phase_before,
        phase_after="",
        ended=True,
        next_options=[],
        effects=[{"kind": "scene_end", "reason": "expired"}],
        messages=[msg],
    )


def advance_scene(state: dict[str, Any], action_ctx: dict[str, Any]) -> dict[str, Any]:
    """Advance the active scene based on `action_ctx['scene_action']`."""
    sc = active_scene(state)
    if not sc:
        return _scene_return(
            ok=False,
            reason="no_active_scene",
            phase_before="",
            phase_after="",
            ended=False,
            next_options=[],
            effects=[],
            messages=["No active scene."],
        )
    st = str(sc.get("scene_type", "") or "").strip().lower()
    r_delivery = dispatch_delivery_advance(st, state=state, sc=sc, action_ctx=action_ctx, advance_drop_pickup=_advance_drop_pickup)
    if isinstance(r_delivery, dict):
        return r_delivery
    r_sting = dispatch_sting_advance(
        st,
        state=state,
        sc=sc,
        action_ctx=action_ctx,
        advance_sting_setup=_advance_sting_setup,
        advance_sting_operation=_advance_sting_operation,
    )
    if isinstance(r_sting, dict):
        return r_sting
    r_raid = dispatch_raid_advance(
        st,
        state=state,
        sc=sc,
        action_ctx=action_ctx,
        advance_safehouse_raid=_advance_safehouse_raid,
        advance_raid_response=_advance_raid_response,
    )
    if isinstance(r_raid, dict):
        return r_raid
    r_pol = dispatch_police_advance(
        st,
        state=state,
        sc=sc,
        action_ctx=action_ctx,
        advance_police_stop=_advance_police_stop,
        advance_checkpoint_sweep=_advance_checkpoint_sweep,
        advance_traffic_stop=_advance_traffic_stop,
        advance_vehicle_search=_advance_vehicle_search,
        advance_border_control=_advance_border_control,
    )
    if isinstance(r_pol, dict):
        return r_pol
    return _scene_return(
        ok=False,
        reason="unsupported_scene_type",
        phase_before=str(sc.get("phase", "") or ""),
        phase_after=str(sc.get("phase", "") or ""),
        ended=False,
        next_options=list(sc.get("next_options") or []),
        effects=[],
        messages=["Scene type not supported yet."],
    )


def start_border_control_scene(state: dict[str, Any], *, payload: dict[str, Any]) -> dict[str, Any]:
    if has_active_scene(state):
        return {"ok": False, "reason": "scene_already_active"}
    flags = state.get("flags", {}) or {}
    if isinstance(flags, dict) and not bool(flags.get("scenes_enabled", True)):
        return {"ok": False, "reason": "scenes_disabled"}
    loc, did = _player_loc(state)
    loc0 = str((payload or {}).get("location", loc) or loc).strip().lower()
    dst = str((payload or {}).get("travel_destination", "") or "").strip().lower()
    bc = int((payload or {}).get("border_controls", 0) or 0)
    scene_id = hashlib.md5(f"{_seed_key(state)}|border_control|{loc0}|{dst}|{bc}".encode("utf-8", errors="ignore")).hexdigest()[:10]
    day, tmin = _now(state)
    sc = {
        "scene_id": scene_id,
        "scene_type": "border_control",
        "phase": "control",
        "context": {"location": loc0, "district": did, "payload": dict(payload or {})},
        "vars": {"wait_count": 0},
        "expires_at": {"day": int(day), "time_min": min(1439, int(tmin) + 16)},
        "next_options": ["SCENE COMPLY", "SCENE BRIBE 500", "SCENE CONCEAL <item_id>", "SCENE DUMP <item_id>", "SCENE RUN"],
    }
    state["active_scene"] = sc
    state.setdefault("world_notes", []).append(f"[Scene] start border_control loc={loc0} dst={dst} bc={bc}")
    return {"ok": True, "scene_id": scene_id, "scene_type": "border_control"}


def _auto_resolve_border_control(state: dict[str, Any], sc: dict[str, Any], *, phase_before: str) -> dict[str, Any]:
    return _advance_border_control(state, sc, {"scene_action": "comply", "scene_timeout": True})


def _advance_border_control(state: dict[str, Any], sc: dict[str, Any], action_ctx: dict[str, Any]) -> dict[str, Any]:
    phase_before = str(sc.get("phase", "") or "")
    act = str(action_ctx.get("scene_action", "") or "").strip().lower().replace("-", "_")
    if phase_before != "control":
        return _scene_return(ok=False, reason="invalid_phase", phase_before=phase_before, phase_after=phase_before, ended=False, next_options=list(sc.get("next_options") or []), effects=[], messages=["Scene is in an unknown phase."])
    effects: list[dict[str, Any]] = []
    if act in ("conceal",):
        arg = str(action_ctx.get("scene_arg", "") or "").strip()
        if not arg:
            return _scene_return(ok=False, reason="missing_arg", phase_before=phase_before, phase_after=phase_before, ended=False, next_options=list(sc.get("next_options") or []), effects=[], messages=["Usage: SCENE CONCEAL <item_id>"])

        r0 = apply_conceal(state, item_id=arg, method="vehicle")
        if not bool(r0.get("ok")):
            return _scene_return(ok=False, reason=str(r0.get("reason", "conceal_failed") or "conceal_failed"), phase_before=phase_before, phase_after=phase_before, ended=False, next_options=list(sc.get("next_options") or []), effects=[], messages=["Conceal failed."])
        return _scene_return(ok=True, reason="", phase_before=phase_before, phase_after=phase_before, ended=False, next_options=list(sc.get("next_options") or []), effects=[{"kind": "conceal", "item_id": arg}], messages=[f"You conceal {arg}."])
    if act in ("dump", "ditch"):
        arg = str(action_ctx.get("scene_arg", "") or "").strip()
        if not arg:
            return _scene_return(ok=False, reason="missing_arg", phase_before=phase_before, phase_after=phase_before, ended=False, next_options=list(sc.get("next_options") or []), effects=[], messages=["Usage: SCENE DUMP <item_id>"])

        r0 = apply_dump(state, item_id=arg)
        if not bool(r0.get("ok")):
            return _scene_return(ok=False, reason=str(r0.get("reason", "dump_failed") or "dump_failed"), phase_before=phase_before, phase_after=phase_before, ended=False, next_options=list(sc.get("next_options") or []), effects=[], messages=["Dump failed."])
        return _scene_return(ok=True, reason="", phase_before=phase_before, phase_after=phase_before, ended=False, next_options=list(sc.get("next_options") or []), effects=[{"kind": "inventory_remove", "item_id": arg, "count": 1, "reason": "dump"}], messages=[f"You ditch {arg}."])
    if act in ("run", "flee"):
        td = _bump_trace(state, 10)
        effects.append({"kind": "trace_delta", "delta": int(td), "reason": "border_control_run"})
        effects.append({"kind": "scene_end", "reason": "run"})
        clear_active_scene(state)
        return _scene_return(ok=True, reason="", phase_before=phase_before, phase_after="", ended=True, next_options=[], effects=effects, messages=["You run from border control. This escalates hard."])
    if act in ("bribe",):
        try:
            br = int(action_ctx.get("bribe_amount", 0) or 0)
        except Exception:
            br = 0
        if br <= 0:
            br = 500
        eco = state.get("economy", {}) if isinstance(state.get("economy"), dict) else {}
        try:
            cash = int(eco.get("cash", 0) or 0)
        except Exception:
            cash = 0
        if cash < br:
            return _scene_return(ok=False, reason="insufficient_cash", phase_before=phase_before, phase_after=phase_before, ended=False, next_options=list(sc.get("next_options") or []), effects=[], messages=[f"Not enough cash to bribe (need {br})."])
        eco["cash"] = int(cash - br)
        state["economy"] = eco
        td = _bump_trace(state, 3)
        effects.append({"kind": "cash_delta", "delta": int(-br), "reason": "border_control_bribe"})
        effects.append({"kind": "trace_delta", "delta": int(td), "reason": "border_control_bribe"})
        effects.append({"kind": "scene_end", "reason": "bribe"})
        clear_active_scene(state)
        return _scene_return(ok=True, reason="", phase_before=phase_before, phase_after="", ended=True, next_options=[], effects=effects, messages=["You bribe your way through border control."])
    if act in ("comply", "cooperate"):
        # Higher intensity when border controls are strict.
        bc = int((((sc.get("context") or {}) if isinstance(sc.get("context"), dict) else {}).get("payload") or {}).get("border_controls", 0) or 0)
        intensity = 70 if bc >= 80 else 60
        try:

            sr = resolve_search(state, scene_id=str(sc.get("scene_id", "")), scene_type="border_control", intensity=int(intensity), salt="border_search")
            if sr.get("found"):
                effects.append({"kind": "search_found", "items": list(sr.get("found") or [])[:8]})
        except Exception:
            pass
        effects.append({"kind": "scene_end", "reason": "comply" if not bool(action_ctx.get("scene_timeout")) else "timeout"})
        clear_active_scene(state)
        return _scene_return(ok=True, reason="", phase_before=phase_before, phase_after="", ended=True, next_options=[], effects=effects, messages=["You comply with border control and proceed."])
    return _scene_return(ok=False, reason="invalid_action", phase_before=phase_before, phase_after=phase_before, ended=False, next_options=list(sc.get("next_options") or []), effects=[], messages=["Invalid scene action."])


def start_traffic_stop_scene(state: dict[str, Any], *, payload: dict[str, Any]) -> dict[str, Any]:
    if has_active_scene(state):
        return {"ok": False, "reason": "scene_already_active"}
    flags = state.get("flags", {}) or {}
    if isinstance(flags, dict) and not bool(flags.get("scenes_enabled", True)):
        return {"ok": False, "reason": "scenes_disabled"}
    loc, did = _player_loc(state)
    loc0 = str((payload or {}).get("location", loc) or loc).strip().lower()
    scene_id = hashlib.md5(f"{_seed_key(state)}|traffic_stop|{loc0}".encode("utf-8", errors="ignore")).hexdigest()[:10]
    day, tmin = _now(state)
    sc = {
        "scene_id": scene_id,
        "scene_type": "traffic_stop",
        "phase": "stop",
        "context": {"location": loc0, "district": did, "payload": dict(payload or {})},
        "vars": {"wait_count": 0},
        "expires_at": {"day": int(day), "time_min": min(1439, int(tmin) + 12)},
        "next_options": ["SCENE COMPLY", "SCENE BRIBE", "SCENE CONCEAL <item_id>", "SCENE DUMP <item_id>", "SCENE RUN"],
    }
    state["active_scene"] = sc
    state.setdefault("world_notes", []).append(f"[Scene] start traffic_stop loc={loc0}")
    return {"ok": True, "scene_id": scene_id, "scene_type": "traffic_stop"}


def _auto_resolve_traffic_stop(state: dict[str, Any], sc: dict[str, Any], *, phase_before: str) -> dict[str, Any]:
    return _advance_traffic_stop(state, sc, {"scene_action": "comply", "scene_timeout": True})


def _advance_traffic_stop(state: dict[str, Any], sc: dict[str, Any], action_ctx: dict[str, Any]) -> dict[str, Any]:
    phase_before = str(sc.get("phase", "") or "")
    act = str(action_ctx.get("scene_action", "") or "").strip().lower().replace("-", "_")
    if phase_before != "stop":
        return _scene_return(ok=False, reason="invalid_phase", phase_before=phase_before, phase_after=phase_before, ended=False, next_options=list(sc.get("next_options") or []), effects=[], messages=["Scene is in an unknown phase."])
    effects: list[dict[str, Any]] = []
    messages: list[str] = []
    if act in ("conceal",):
        arg = str(action_ctx.get("scene_arg", "") or "").strip()
        if not arg:
            return _scene_return(ok=False, reason="missing_arg", phase_before=phase_before, phase_after=phase_before, ended=False, next_options=list(sc.get("next_options") or []), effects=[], messages=["Usage: SCENE CONCEAL <item_id>"])

        r0 = apply_conceal(state, item_id=arg, method="body")
        if not bool(r0.get("ok")):
            return _scene_return(ok=False, reason=str(r0.get("reason", "conceal_failed") or "conceal_failed"), phase_before=phase_before, phase_after=phase_before, ended=False, next_options=list(sc.get("next_options") or []), effects=[], messages=["Conceal failed."])
        return _scene_return(ok=True, reason="", phase_before=phase_before, phase_after=phase_before, ended=False, next_options=list(sc.get("next_options") or []), effects=[{"kind": "conceal", "item_id": arg}], messages=[f"You conceal {arg}."])
    if act in ("dump", "ditch"):
        arg = str(action_ctx.get("scene_arg", "") or "").strip()
        if not arg:
            return _scene_return(ok=False, reason="missing_arg", phase_before=phase_before, phase_after=phase_before, ended=False, next_options=list(sc.get("next_options") or []), effects=[], messages=["Usage: SCENE DUMP <item_id>"])

        r0 = apply_dump(state, item_id=arg)
        if not bool(r0.get("ok")):
            return _scene_return(ok=False, reason=str(r0.get("reason", "dump_failed") or "dump_failed"), phase_before=phase_before, phase_after=phase_before, ended=False, next_options=list(sc.get("next_options") or []), effects=[], messages=["Dump failed."])
        return _scene_return(ok=True, reason="", phase_before=phase_before, phase_after=phase_before, ended=False, next_options=list(sc.get("next_options") or []), effects=[{"kind": "inventory_remove", "item_id": arg, "count": 1, "reason": "dump"}], messages=[f"You ditch {arg}."])
    if act in ("run", "flee"):
        td = _bump_trace(state, 6)
        effects.append({"kind": "trace_delta", "delta": int(td), "reason": "traffic_stop_run"})
        effects.append({"kind": "scene_end", "reason": "run"})
        clear_active_scene(state)
        return _scene_return(ok=True, reason="", phase_before=phase_before, phase_after="", ended=True, next_options=[], effects=effects, messages=["You run from a traffic stop. Attention spikes."])
    if act in ("bribe",):
        try:
            br = int(action_ctx.get("bribe_amount", 0) or 0)
        except Exception:
            br = 0
        if br <= 0:
            br = 200
        eco = state.get("economy", {}) if isinstance(state.get("economy"), dict) else {}
        try:
            cash = int(eco.get("cash", 0) or 0)
        except Exception:
            cash = 0
        if cash < br:
            return _scene_return(ok=False, reason="insufficient_cash", phase_before=phase_before, phase_after=phase_before, ended=False, next_options=list(sc.get("next_options") or []), effects=[], messages=[f"Not enough cash to bribe (need {br})."])
        eco["cash"] = int(cash - br)
        state["economy"] = eco
        td = _bump_trace(state, 1)
        effects.append({"kind": "cash_delta", "delta": int(-br), "reason": "traffic_stop_bribe"})
        effects.append({"kind": "trace_delta", "delta": int(td), "reason": "traffic_stop_bribe"})
        effects.append({"kind": "scene_end", "reason": "bribe"})
        clear_active_scene(state)
        return _scene_return(ok=True, reason="", phase_before=phase_before, phase_after="", ended=True, next_options=[], effects=effects, messages=["You bribe your way out of the traffic stop."])
    if act in ("comply", "cooperate"):
        # Deterministic search outcome using conceal marks.
        try:

            sr = resolve_search(state, scene_id=str(sc.get("scene_id", "")), scene_type="traffic_stop", intensity=55, salt="traffic_search")
            if sr.get("found"):
                effects.append({"kind": "search_found", "items": list(sr.get("found") or [])[:6]})
        except Exception:
            pass
        effects.append({"kind": "scene_end", "reason": "comply" if not bool(action_ctx.get("scene_timeout")) else "timeout"})
        clear_active_scene(state)
        return _scene_return(ok=True, reason="", phase_before=phase_before, phase_after="", ended=True, next_options=[], effects=effects, messages=["You comply and the stop ends."])
    return _scene_return(ok=False, reason="invalid_action", phase_before=phase_before, phase_after=phase_before, ended=False, next_options=list(sc.get("next_options") or []), effects=[], messages=["Invalid scene action."])


def start_vehicle_search_scene(state: dict[str, Any], *, payload: dict[str, Any]) -> dict[str, Any]:
    if has_active_scene(state):
        return {"ok": False, "reason": "scene_already_active"}
    flags = state.get("flags", {}) or {}
    if isinstance(flags, dict) and not bool(flags.get("scenes_enabled", True)):
        return {"ok": False, "reason": "scenes_disabled"}
    loc, did = _player_loc(state)
    loc0 = str((payload or {}).get("location", loc) or loc).strip().lower()
    scene_id = hashlib.md5(f"{_seed_key(state)}|vehicle_search|{loc0}".encode("utf-8", errors="ignore")).hexdigest()[:10]
    day, tmin = _now(state)
    sc = {
        "scene_id": scene_id,
        "scene_type": "vehicle_search",
        "phase": "search",
        "context": {"location": loc0, "district": did, "payload": dict(payload or {})},
        "vars": {"wait_count": 0},
        "expires_at": {"day": int(day), "time_min": min(1439, int(tmin) + 14)},
        "next_options": ["SCENE COMPLY", "SCENE BRIBE", "SCENE CONCEAL <item_id>", "SCENE DUMP <item_id>", "SCENE RUN"],
    }
    state["active_scene"] = sc
    state.setdefault("world_notes", []).append(f"[Scene] start vehicle_search loc={loc0}")
    return {"ok": True, "scene_id": scene_id, "scene_type": "vehicle_search"}


def _auto_resolve_vehicle_search(state: dict[str, Any], sc: dict[str, Any], *, phase_before: str) -> dict[str, Any]:
    return _advance_vehicle_search(state, sc, {"scene_action": "comply", "scene_timeout": True})


def _advance_vehicle_search(state: dict[str, Any], sc: dict[str, Any], action_ctx: dict[str, Any]) -> dict[str, Any]:
    phase_before = str(sc.get("phase", "") or "")
    act = str(action_ctx.get("scene_action", "") or "").strip().lower().replace("-", "_")
    if phase_before != "search":
        return _scene_return(ok=False, reason="invalid_phase", phase_before=phase_before, phase_after=phase_before, ended=False, next_options=list(sc.get("next_options") or []), effects=[], messages=["Scene is in an unknown phase."])
    # Higher intensity than traffic stop.
    effects: list[dict[str, Any]] = []
    if act in ("conceal",):
        arg = str(action_ctx.get("scene_arg", "") or "").strip()
        if not arg:
            return _scene_return(ok=False, reason="missing_arg", phase_before=phase_before, phase_after=phase_before, ended=False, next_options=list(sc.get("next_options") or []), effects=[], messages=["Usage: SCENE CONCEAL <item_id>"])

        r0 = apply_conceal(state, item_id=arg, method="bag")
        if not bool(r0.get("ok")):
            return _scene_return(ok=False, reason=str(r0.get("reason", "conceal_failed") or "conceal_failed"), phase_before=phase_before, phase_after=phase_before, ended=False, next_options=list(sc.get("next_options") or []), effects=[], messages=["Conceal failed."])
        return _scene_return(ok=True, reason="", phase_before=phase_before, phase_after=phase_before, ended=False, next_options=list(sc.get("next_options") or []), effects=[{"kind": "conceal", "item_id": arg}], messages=[f"You conceal {arg}."])
    if act in ("dump", "ditch"):
        arg = str(action_ctx.get("scene_arg", "") or "").strip()
        if not arg:
            return _scene_return(ok=False, reason="missing_arg", phase_before=phase_before, phase_after=phase_before, ended=False, next_options=list(sc.get("next_options") or []), effects=[], messages=["Usage: SCENE DUMP <item_id>"])

        r0 = apply_dump(state, item_id=arg)
        if not bool(r0.get("ok")):
            return _scene_return(ok=False, reason=str(r0.get("reason", "dump_failed") or "dump_failed"), phase_before=phase_before, phase_after=phase_before, ended=False, next_options=list(sc.get("next_options") or []), effects=[], messages=["Dump failed."])
        return _scene_return(ok=True, reason="", phase_before=phase_before, phase_after=phase_before, ended=False, next_options=list(sc.get("next_options") or []), effects=[{"kind": "inventory_remove", "item_id": arg, "count": 1, "reason": "dump"}], messages=[f"You ditch {arg}."])
    if act in ("run", "flee"):
        td = _bump_trace(state, 8)
        effects.append({"kind": "trace_delta", "delta": int(td), "reason": "vehicle_search_run"})
        effects.append({"kind": "scene_end", "reason": "run"})
        clear_active_scene(state)
        return _scene_return(ok=True, reason="", phase_before=phase_before, phase_after="", ended=True, next_options=[], effects=effects, messages=["You run from a vehicle search. This escalates hard."])
    if act in ("bribe",):
        try:
            br = int(action_ctx.get("bribe_amount", 0) or 0)
        except Exception:
            br = 0
        if br <= 0:
            br = 600
        eco = state.get("economy", {}) if isinstance(state.get("economy"), dict) else {}
        try:
            cash = int(eco.get("cash", 0) or 0)
        except Exception:
            cash = 0
        if cash < br:
            return _scene_return(ok=False, reason="insufficient_cash", phase_before=phase_before, phase_after=phase_before, ended=False, next_options=list(sc.get("next_options") or []), effects=[], messages=[f"Not enough cash to bribe (need {br})."])
        eco["cash"] = int(cash - br)
        state["economy"] = eco
        td = _bump_trace(state, 2)
        effects.append({"kind": "cash_delta", "delta": int(-br), "reason": "vehicle_search_bribe"})
        effects.append({"kind": "trace_delta", "delta": int(td), "reason": "vehicle_search_bribe"})
        effects.append({"kind": "scene_end", "reason": "bribe"})
        clear_active_scene(state)
        return _scene_return(ok=True, reason="", phase_before=phase_before, phase_after="", ended=True, next_options=[], effects=effects, messages=["You bribe your way out of a vehicle search."])
    if act in ("comply", "cooperate"):
        try:

            sr = resolve_search(state, scene_id=str(sc.get("scene_id", "")), scene_type="vehicle_search", intensity=75, salt="vehicle_search")
            if sr.get("found"):
                effects.append({"kind": "search_found", "items": list(sr.get("found") or [])[:8]})
        except Exception:
            pass
        effects.append({"kind": "scene_end", "reason": "comply" if not bool(action_ctx.get("scene_timeout")) else "timeout"})
        clear_active_scene(state)
        return _scene_return(ok=True, reason="", phase_before=phase_before, phase_after="", ended=True, next_options=[], effects=effects, messages=["You comply with the vehicle search."])
    return _scene_return(ok=False, reason="invalid_action", phase_before=phase_before, phase_after=phase_before, ended=False, next_options=list(sc.get("next_options") or []), effects=[], messages=["Invalid scene action."])


def start_checkpoint_sweep_scene(state: dict[str, Any], *, payload: dict[str, Any]) -> dict[str, Any]:
    if has_active_scene(state):
        return {"ok": False, "reason": "scene_already_active"}
    flags = state.get("flags", {}) or {}
    if isinstance(flags, dict) and not bool(flags.get("scenes_enabled", True)):
        return {"ok": False, "reason": "scenes_disabled"}
    loc, did = _player_loc(state)
    loc0 = str((payload or {}).get("location", loc) or loc).strip().lower()
    att = str((payload or {}).get("attention", "investigated") or "investigated").strip().lower()
    scene_id = hashlib.md5(f"{_seed_key(state)}|checkpoint_sweep|{loc0}|{att}".encode("utf-8", errors="ignore")).hexdigest()[:10]
    day, tmin = _now(state)
    sc = {
        "scene_id": scene_id,
        "scene_type": "checkpoint_sweep",
        "phase": "checkpoint",
        "context": {"location": loc0, "district": did, "attention": att},
        "vars": {"wait_count": 0},
        "expires_at": {"day": int(day), "time_min": min(1439, int(tmin) + 18)},
        "next_options": ["SCENE COMPLY", "SCENE DETOUR", "SCENE BRIBE", "SCENE CONCEAL <item_id>", "SCENE DUMP <item_id>", "SCENE RUN", "SCENE WAIT"],
    }
    state["active_scene"] = sc
    state.setdefault("world_notes", []).append(f"[Scene] start checkpoint_sweep loc={loc0} att={att}")
    try:

        append_casefile(
            state,
            {
                "kind": "scene_start",
                "scene_type": "checkpoint_sweep",
                "event_type": "police_sweep",
                "location": loc0,
                "district": did,
                "summary": f"Checkpoint sweep active (attention={att})",
                "tags": ["police_sweep", "checkpoint"],
                "meta": {"attention": att},
            },
        )
    except Exception as e:
        _record_soft_error(state, "scenes.checkpoint_sweep_casefile", e)
    return {"ok": True, "scene_id": scene_id, "scene_type": "checkpoint_sweep"}


def _apply_police_sweep_restrictions(state: dict[str, Any], *, loc: str, attention: str, until_day: int) -> None:
    world = state.setdefault("world", {})
    locs = world.setdefault("locations", {})
    if not (isinstance(locs, dict) and loc):
        return
    locs.setdefault(loc, {})
    slot = locs.get(loc)
    if not isinstance(slot, dict):
        slot = {}
        locs[loc] = slot
    r = slot.setdefault("restrictions", {})
    if isinstance(r, dict):
        r["police_sweep_until_day"] = int(until_day)
        r["police_sweep_attention"] = str(attention or "investigated")
    slot["restrictions"] = r
    slot.setdefault("areas", {})
    if isinstance(slot.get("areas"), dict):
        a = slot.get("areas") or {}
        a["downtown"] = {"restricted": True, "until_day": int(until_day), "reason": "police_sweep"}
        slot["areas"] = a
    slot.setdefault("tags", [])
    tags = slot.get("tags")
    if isinstance(tags, list) and "police_sweep" not in [str(x).lower() for x in tags]:
        tags.append("police_sweep")
        slot["tags"] = tags
    locs[loc] = slot
    world["locations"] = locs


def _auto_resolve_checkpoint_sweep(state: dict[str, Any], sc: dict[str, Any], *, phase_before: str) -> dict[str, Any]:
    # Timeout policy: comply but with a small trace cost (delay looks suspicious).
    return _advance_checkpoint_sweep(state, sc, {"scene_action": "comply", "scene_timeout": True})


def _advance_checkpoint_sweep(state: dict[str, Any], sc: dict[str, Any], action_ctx: dict[str, Any]) -> dict[str, Any]:
    phase_before = str(sc.get("phase", "") or "")
    act = str(action_ctx.get("scene_action", "") or "").strip().lower().replace("-", "_")
    ctx = sc.get("context") if isinstance(sc.get("context"), dict) else {}
    loc = str((ctx or {}).get("location", "") or "").strip().lower() or _player_loc(state)[0]
    att = str((ctx or {}).get("attention", "investigated") or "investigated").strip().lower()
    law_tight = att in ("manhunt", "hunt", "hot")

    # Base until day: 1 day by default, 2 if attention high.
    today = _now(state)[0]
    until_day = int(today + (2 if law_tight else 1))

    def _maybe_schedule_stop(reason: str) -> dict[str, Any] | None:
        # Deterministically schedule a follow-up stop if illegal weapons are carried.
        try:

            has_illegal, wids = _has_illegal_weapon(state)
            if not has_illegal or not wids:
                return None
            # Roll chance depends on attention + action outcome.
            base = 25 if not law_tight else 45
            if reason in ("checkpoint_run",):
                base += 20
            if reason in ("checkpoint_bribe_backfire",):
                base += 15
            base = max(10, min(85, base))
            r0 = scene_rng(state, scene_id=str(sc.get("scene_id", "")), scene_type="checkpoint_sweep", salt=f"follow_stop|{reason}|{loc}|{att}")
            if r0 >= base:
                return None
            schedule_weapon_check(state, weapon_ids=list(wids)[:8], reason="checkpoint", extra_payload={"checkpoint": True, "checkpoint_attention": att})
            return {"event_type": "police_weapon_check", "weapon_ids": list(wids)[:8]}
        except Exception:
            return None

    def _carried_contraband_count() -> int:
        inv = state.get("inventory", {}) if isinstance(state.get("inventory"), dict) else {}
        if not isinstance(inv, dict):
            return 0
        held: list[str] = []
        for k in ("bag_contents", "pocket_contents"):
            arr = inv.get(k, [])
            if isinstance(arr, list):
                for x in arr[:160]:
                    s = str(x or "").strip()
                    if s:
                        held.append(s)
        for k in ("r_hand", "l_hand", "worn"):
            v = str(inv.get(k, "") or "").strip()
            if v and v != "-":
                held.append(v)
        if not held:
            return 0
        world = state.get("world", {}) or {}
        idx = (world.get("content_index", {}) or {}) if isinstance(world, dict) else {}
        items = idx.get("items", {}) if isinstance(idx, dict) else {}
        cnt = 0
        seen: set[str] = set()
        for iid in held[:200]:
            if iid in seen:
                continue
            seen.add(iid)
            meta = items.get(iid) if isinstance(items, dict) else None
            tags = meta.get("tags", []) if isinstance(meta, dict) else []
            if not isinstance(tags, list):
                tags = []
            tl = [str(t).lower() for t in tags if isinstance(t, str)]
            if ("contraband" in tl) or ("illegal_in_many_regions" in tl) or ("forged" in tl):
                cnt += 1
        return int(cnt)

    def _maybe_schedule_raid(reason: str) -> dict[str, Any] | None:
        # Deterministically schedule a safehouse_raid if player has a safehouse here and is carrying contraband.
        ccount = _carried_contraband_count()
        if ccount <= 0:
            return None
        loc_here = str((state.get("player", {}) or {}).get("location", "") or "").strip().lower()
        if not loc_here:
            return None
        world = state.get("world", {}) or {}
        sh = (world.get("safehouses", {}) or {}) if isinstance(world, dict) else {}
        row = sh.get(loc_here) if isinstance(sh, dict) else None
        if not isinstance(row, dict) or str(row.get("status", "none") or "none") == "none":
            return None
        # Deduplicate.
        pe = state.get("pending_events", []) or []
        if isinstance(pe, list):
            for ev0 in pe:
                if isinstance(ev0, dict) and str(ev0.get("event_type", "") or "") == "safehouse_raid" and not bool(ev0.get("triggered")):
                    return None

        base = 12 if not law_tight else 28
        base += min(20, ccount * 6)
        if reason in ("checkpoint_run", "checkpoint_bribe_backfire"):
            base += 12
        base = max(5, min(85, base))
        r0 = scene_rng(state, scene_id=str(sc.get("scene_id", "")), scene_type="checkpoint_sweep", salt=f"raid|{reason}|{loc_here}|{att}|{ccount}")
        if r0 >= base:
            return None

        # Build raid payload (same shape as safehouse_raid scheduler) but deterministic and immediate-ish.
        country = ""
        law_level = "standard"
        corruption = "medium"
        firearm_policy = "standard_permit"
        try:

            prof = ensure_location_profile(state, loc_here)
            if isinstance(prof, dict):
                country = str(prof.get("country", "") or "").strip().lower()
                law_level = str(prof.get("law_level", law_level) or law_level).lower()
                corruption = str(prof.get("corruption", corruption) or corruption).lower()
        except Exception:
            pass
        try:

            fp = _firearm_policy_for_country(state, country=country or "unknown")
            firearm_policy = str(fp.get("firearm_policy", firearm_policy) or firearm_policy)
            has_permit = bool(_has_weapon_permit(state, country=country or ""))
        except Exception:
            has_permit = False

        meta = state.get("meta", {}) or {}
        day0 = int(meta.get("day", 1) or 1) if isinstance(meta, dict) else 1
        t0 = int(meta.get("time_min", 0) or 0) if isinstance(meta, dict) else 0
        tr = state.get("trace", {}) or {}
        try:
            tp = int(tr.get("trace_pct", 0) or 0)
        except Exception:
            tp = 0
        sec = int(row.get("security_level", 1) or 1)
        delin = int(row.get("delinquent_days", 0) or 0)
        payload = {
            "location": loc_here,
            "country": country,
            "law_level": law_level,
            "corruption": corruption,
            "firearm_policy": str(firearm_policy or ""),
            "has_weapon_permit": bool(has_permit),
            "disguise_active": bool(((state.get("player", {}) or {}).get("disguise", {}) or {}).get("active", False)),
            "security_level": sec,
            "delinquent_days": delin,
            "trace_snapshot": tp,
            "hot_item_ids": [],  # stash-based confiscation handled by raid_response; this escalation is from checkpoint.
            "response": "none",
            "bribe_amount": 0,
            "reason": "checkpoint_escalation",
        }
        state.setdefault("pending_events", []).append(
            {
                "event_type": "safehouse_raid",
                "title": "Police Raid — Safehouse",
                "due_day": day0,
                "due_time": min(1439, t0 + 6),
                "triggered": False,
                "payload": payload,
            }
        )
        return {"event_type": "safehouse_raid", "location": loc_here}

    effects: list[dict[str, Any]] = []
    messages: list[str] = []

    if phase_before != "checkpoint":
        return _scene_return(ok=False, reason="invalid_phase", phase_before=phase_before, phase_after=phase_before, ended=False, next_options=list(sc.get("next_options") or []), effects=[], messages=["Scene is in an unknown phase."])

    # Allow quick conceal/dump during checkpoint.
    if act in ("conceal",):
        arg = str(action_ctx.get("scene_arg", "") or "").strip()
        if not arg:
            return _scene_return(ok=False, reason="missing_arg", phase_before=phase_before, phase_after=phase_before, ended=False, next_options=list(sc.get("next_options") or []), effects=[], messages=["Usage: SCENE CONCEAL <item_id>"])
        try:

            r0 = apply_conceal(state, item_id=arg, method="bag")
        except Exception:
            r0 = {"ok": False}
        if not bool(r0.get("ok")):
            return _scene_return(ok=False, reason="conceal_failed", phase_before=phase_before, phase_after=phase_before, ended=False, next_options=list(sc.get("next_options") or []), effects=[], messages=["Conceal failed."])
        return _scene_return(ok=True, reason="", phase_before=phase_before, phase_after=phase_before, ended=False, next_options=list(sc.get("next_options") or []), effects=[{"kind": "conceal", "item_id": arg}], messages=[f"You conceal {arg}."])

    if act in ("dump", "ditch"):
        arg = str(action_ctx.get("scene_arg", "") or "").strip()
        if not arg:
            return _scene_return(ok=False, reason="missing_arg", phase_before=phase_before, phase_after=phase_before, ended=False, next_options=list(sc.get("next_options") or []), effects=[], messages=["Usage: SCENE DUMP <item_id>"])
        try:

            r0 = apply_dump(state, item_id=arg)
        except Exception:
            r0 = {"ok": False}
        if not bool(r0.get("ok")):
            return _scene_return(ok=False, reason="dump_failed", phase_before=phase_before, phase_after=phase_before, ended=False, next_options=list(sc.get("next_options") or []), effects=[], messages=["Dump failed."])
        return _scene_return(ok=True, reason="", phase_before=phase_before, phase_after=phase_before, ended=False, next_options=list(sc.get("next_options") or []), effects=[{"kind": "inventory_remove", "item_id": arg, "count": 1, "reason": "dump"}], messages=[f"You ditch {arg}."])

    if act in ("wait",):
        # Reuse generic wait: consumes 5m, but here just adds small suspicion (trace) when attention is high.
        td = _bump_trace(state, 1 if law_tight else 0)
        effects.append({"kind": "time_advance", "minutes": 5})
        if td:
            effects.append({"kind": "trace_delta", "delta": int(td), "reason": "checkpoint_wait"})
        follow = _maybe_schedule_stop("checkpoint_wait")
        if isinstance(follow, dict):
            effects.append({"kind": "event_schedule", "event_type": "police_weapon_check", "due_day": _now(state)[0], "due_time": min(1439, _now(state)[1] + 1), "reason": "checkpoint_wait"})
            messages.append("A patrol car starts shadowing you after the wait.")
        raid = _maybe_schedule_raid("checkpoint_wait")
        if isinstance(raid, dict):
            effects.append({"kind": "event_schedule", "event_type": "safehouse_raid", "due_day": _now(state)[0], "due_time": min(1439, _now(state)[1] + 6), "reason": "checkpoint_wait"})
            messages.append("You get the sense they’re building a case—your safehouse might get attention.")
        messages.append("You wait and watch the checkpoint pattern.")
        return _scene_return(ok=True, reason="", phase_before=phase_before, phase_after=phase_before, ended=False, next_options=list(sc.get("next_options") or []), effects=effects, messages=messages)

    if act in ("detour", "reroute"):
        _apply_police_sweep_restrictions(state, loc=loc, attention=att, until_day=until_day)
        td = _bump_trace(state, 1 if law_tight else 0)
        effects.append({"kind": "restriction_add", "restriction_id": "police_sweep", "until_day": int(until_day), "reason": "checkpoint_detour"})
        if td:
            effects.append({"kind": "trace_delta", "delta": int(td), "reason": "checkpoint_detour"})
        follow = _maybe_schedule_stop("checkpoint_detour")
        if isinstance(follow, dict):
            effects.append({"kind": "event_schedule", "event_type": "police_weapon_check", "due_day": _now(state)[0], "due_time": min(1439, _now(state)[1] + 1), "reason": "checkpoint_detour"})
        raid = _maybe_schedule_raid("checkpoint_detour")
        if isinstance(raid, dict):
            effects.append({"kind": "event_schedule", "event_type": "safehouse_raid", "due_day": _now(state)[0], "due_time": min(1439, _now(state)[1] + 6), "reason": "checkpoint_detour"})
        effects.append({"kind": "scene_end", "reason": "detour"})
        clear_active_scene(state)
        messages.append("You take a longer route to avoid the checkpoint.")
        return _scene_return(ok=True, reason="", phase_before=phase_before, phase_after="", ended=True, next_options=[], effects=effects, messages=messages)

    if act in ("bribe",):
        # Use bribe amount if provided.
        try:
            bribe_amt = int(action_ctx.get("bribe_amount", 0) or 0)
        except Exception:
            bribe_amt = 0
        if bribe_amt <= 0:
            bribe_amt = 250 if not law_tight else 600
        eco = state.get("economy", {}) if isinstance(state.get("economy"), dict) else {}
        try:
            cash = int(eco.get("cash", 0) or 0)
        except Exception:
            cash = 0
        if cash < bribe_amt:
            return _scene_return(ok=False, reason="insufficient_cash", phase_before=phase_before, phase_after=phase_before, ended=False, next_options=list(sc.get("next_options") or []), effects=[], messages=[f"Not enough cash to bribe (need {bribe_amt})."])
        eco["cash"] = int(cash - bribe_amt)
        state["economy"] = eco
        # Deterministic bribe: higher attention = higher backfire chance.
        r = scene_rng(state, scene_id=str(sc.get("scene_id", "")), scene_type="checkpoint_sweep", salt=f"bribe|{bribe_amt}|{att}")
        backfire = r < (20 if law_tight else 10)
        td = _bump_trace(state, 6 if backfire else (2 if law_tight else 1))
        effects.append({"kind": "cash_delta", "delta": int(-bribe_amt), "reason": "checkpoint_bribe"})
        tr_reason = "checkpoint_bribe_backfire" if backfire else "checkpoint_bribe"
        effects.append({"kind": "trace_delta", "delta": int(td), "reason": tr_reason})
        _apply_police_sweep_restrictions(state, loc=loc, attention=att, until_day=until_day)
        effects.append({"kind": "restriction_add", "restriction_id": "police_sweep", "until_day": int(until_day), "reason": "checkpoint_bribe"})
        follow = _maybe_schedule_stop(tr_reason)
        if isinstance(follow, dict):
            effects.append({"kind": "event_schedule", "event_type": "police_weapon_check", "due_day": _now(state)[0], "due_time": min(1439, _now(state)[1] + 1), "reason": tr_reason})
        raid = _maybe_schedule_raid(tr_reason)
        if isinstance(raid, dict):
            effects.append({"kind": "event_schedule", "event_type": "safehouse_raid", "due_day": _now(state)[0], "due_time": min(1439, _now(state)[1] + 6), "reason": tr_reason})
        effects.append({"kind": "scene_end", "reason": "bribe_backfire" if backfire else "bribe"})
        clear_active_scene(state)
        messages.append("You offer cash. They let you through." + (" It feels noted." if backfire else ""))
        return _scene_return(ok=True, reason="", phase_before=phase_before, phase_after="", ended=True, next_options=[], effects=effects, messages=messages)

    if act in ("run", "flee"):
        td = _bump_trace(state, 8 if law_tight else 6)
        effects.append({"kind": "trace_delta", "delta": int(td), "reason": "checkpoint_run"})
        follow = _maybe_schedule_stop("checkpoint_run")
        if isinstance(follow, dict):
            effects.append({"kind": "event_schedule", "event_type": "police_weapon_check", "due_day": _now(state)[0], "due_time": min(1439, _now(state)[1] + 1), "reason": "checkpoint_run"})
        raid = _maybe_schedule_raid("checkpoint_run")
        if isinstance(raid, dict):
            effects.append({"kind": "event_schedule", "event_type": "safehouse_raid", "due_day": _now(state)[0], "due_time": min(1439, _now(state)[1] + 6), "reason": "checkpoint_run"})
        effects.append({"kind": "scene_end", "reason": "run"})
        clear_active_scene(state)
        messages.append("You bolt from the checkpoint. That escalates attention immediately.")
        return _scene_return(ok=True, reason="", phase_before=phase_before, phase_after="", ended=True, next_options=[], effects=effects, messages=messages)

    if act in ("comply", "cooperate"):
        _apply_police_sweep_restrictions(state, loc=loc, attention=att, until_day=until_day)
        td = _bump_trace(state, 2 if law_tight else (1 if bool(action_ctx.get("scene_timeout")) else 0))
        effects.append({"kind": "restriction_add", "restriction_id": "police_sweep", "until_day": int(until_day), "reason": "checkpoint_comply"})
        if td:
            effects.append({"kind": "trace_delta", "delta": int(td), "reason": "checkpoint_comply"})
        follow = _maybe_schedule_stop("checkpoint_comply")
        if isinstance(follow, dict):
            effects.append({"kind": "event_schedule", "event_type": "police_weapon_check", "due_day": _now(state)[0], "due_time": min(1439, _now(state)[1] + 1), "reason": "checkpoint_comply"})
        raid = _maybe_schedule_raid("checkpoint_comply")
        if isinstance(raid, dict):
            effects.append({"kind": "event_schedule", "event_type": "safehouse_raid", "due_day": _now(state)[0], "due_time": min(1439, _now(state)[1] + 6), "reason": "checkpoint_comply"})
        effects.append({"kind": "scene_end", "reason": "comply" if not bool(action_ctx.get("scene_timeout")) else "timeout"})
        clear_active_scene(state)
        messages.append("You comply and pass through the checkpoint.")
        return _scene_return(ok=True, reason="", phase_before=phase_before, phase_after="", ended=True, next_options=[], effects=effects, messages=messages)

    return _scene_return(ok=False, reason="invalid_action", phase_before=phase_before, phase_after=phase_before, ended=False, next_options=list(sc.get("next_options") or []), effects=[], messages=["Invalid scene action."])


def _bump_trace(state: dict[str, Any], delta: int) -> int:
    tr = state.setdefault("trace", {})
    try:
        tp = int((tr or {}).get("trace_pct", 0) or 0)
    except Exception:
        tp = 0
    before = tp
    tp = max(0, min(100, tp + int(delta)))
    tr["trace_pct"] = tp
    try:

        sync_faction_statuses_from_trace(state)
    except Exception:
        pass
    return int(tp - before)


def _confiscate_items(state: dict[str, Any], item_ids: list[str]) -> dict[str, Any]:
    """Remove specific carried items from hands/worn/bag/pocket. Returns counts removed."""
    inv = state.get("inventory", {}) if isinstance(state.get("inventory"), dict) else {}
    if not isinstance(inv, dict):
        return {"removed": {}, "total": 0}
    targets = [str(x or "").strip() for x in (item_ids or []) if str(x or "").strip()]
    if not targets:
        return {"removed": {}, "total": 0}
    removed: dict[str, int] = {}

    for k in ("r_hand", "l_hand", "worn"):
        v = str(inv.get(k, "") or "").strip()
        if v in targets and v:
            inv[k] = "-"
            removed[v] = int(removed.get(v, 0) or 0) + 1

    for k in ("bag_contents", "pocket_contents"):
        arr = inv.get(k, [])
        if not isinstance(arr, list) or not arr:
            continue
        new_arr: list[str] = []
        for x in arr[:200]:
            s = str(x or "").strip()
            if s in targets:
                removed[s] = int(removed.get(s, 0) or 0) + 1
            else:
                new_arr.append(s if s else "")
        inv[k] = [x for x in new_arr if x]

    state["inventory"] = inv
    total = sum([int(v or 0) for v in removed.values()]) if removed else 0
    return {"removed": removed, "total": int(total)}


def start_police_stop_scene(state: dict[str, Any], *, payload: dict[str, Any]) -> dict[str, Any]:
    if has_active_scene(state):
        return {"ok": False, "reason": "scene_already_active"}
    flags = state.get("flags", {}) or {}
    if isinstance(flags, dict) and not bool(flags.get("scenes_enabled", True)):
        return {"ok": False, "reason": "scenes_disabled"}

    loc, did = _player_loc(state)
    wids = payload.get("weapon_ids", []) or []
    if not isinstance(wids, list):
        wids = []
    wids = [str(x or "").strip() for x in wids[:12] if str(x or "").strip()]
    permit_doc = payload.get("permit_doc") or {}
    if not isinstance(permit_doc, dict):
        permit_doc = {}
    scene_id = hashlib.md5(f"{_seed_key(state)}|police_stop|{loc}|{did}|{','.join(wids)}".encode("utf-8", errors="ignore")).hexdigest()[:10]

    sc = {
        "scene_id": scene_id,
        "scene_type": "police_stop",
        "phase": "stop",
        "context": {
            "location": str(payload.get("location", loc) or loc).strip().lower(),
            "district": did,
            "weapon_ids": wids,
            "reason": str(payload.get("reason", "weapon_check") or "weapon_check"),
            "country": str(payload.get("country", "") or "").strip().lower(),
            "law_level": str(payload.get("law_level", "") or "").strip().lower(),
            "firearm_policy": str(payload.get("firearm_policy", "") or "").strip().lower(),
            "firearm_policy_narrative": str(payload.get("firearm_policy_narrative", "") or "").strip(),
            "permit_doc": permit_doc,
            "dialog": payload.get("dialog") if isinstance(payload.get("dialog"), dict) else {},
        },
        "vars": {"wait_count": 0},
        "expires_at": {"day": _now(state)[0], "time_min": min(1439, _now(state)[1] + 20)},
        "next_options": ["SCENE COMPLY", "SCENE RUN"],
    }
    state["active_scene"] = sc
    state.setdefault("world_notes", []).append(f"[Scene] start police_stop weapons={','.join(wids) if wids else '-'}")
    return {"ok": True, "scene_id": scene_id, "scene_type": "police_stop"}


def _advance_police_stop(state: dict[str, Any], sc: dict[str, Any], action_ctx: dict[str, Any]) -> dict[str, Any]:
    phase_before = str(sc.get("phase", "") or "")
    act = str(action_ctx.get("scene_action", "") or "").strip().lower().replace("-", "_")
    ctx = sc.get("context") if isinstance(sc.get("context"), dict) else {}
    wids = (ctx or {}).get("weapon_ids", []) or []
    if not isinstance(wids, list):
        wids = []
    wids = [str(x or "").strip() for x in wids if str(x or "").strip()]
    permit_doc = (ctx or {}).get("permit_doc") if isinstance((ctx or {}).get("permit_doc"), dict) else {}
    law = str((ctx or {}).get("law_level", "") or "").strip().lower()
    reason = str((ctx or {}).get("reason", "") or "weapon_check")

    effects: list[dict[str, Any]] = []
    messages: list[str] = []

    if phase_before in ("stop", "approach"):
        # Patrol / heat-check path: arrest protocol, minor fine, escape roll, or bribe threshold.
        _patrol = phase_before == "approach" or str(reason or "").strip().lower() == "heat_check"
        if _patrol:

            def _patrol_escape_chance_pct() -> int:
                base = 40
                try:
                    row = (state.get("skills", {}) or {}).get("evasion")
                    lvl = int((row or {}).get("level", 1) or 1)
                except Exception:
                    lvl = 1
                bonus = max(0, min(35, (lvl - 1) * 3))
                return min(90, base + bonus)

            if act in ("comply", "cooperate"):
                try:
                    tp = int((state.get("trace", {}) or {}).get("trace_pct", 0) or 0)
                except Exception:
                    tp = 0
                if tp >= 50:
                    execute_arrest(state)
                    messages.append("You comply. They run your record—and the cuffs come out.")
                    return _scene_return(
                        ok=True,
                        reason="arrest",
                        phase_before=phase_before,
                        phase_after="",
                        ended=True,
                        next_options=[],
                        effects=[{"kind": "arrest", "reason": "comply_trace_high"}],
                        messages=messages,
                    )
                eco = state.setdefault("economy", {})
                try:
                    cash0 = int(eco.get("cash", 0) or 0)
                except Exception:
                    cash0 = 0
                fine = min(100, cash0)
                eco["cash"] = int(cash0 - fine)
                effects.append({"kind": "cash_delta", "delta": int(-fine), "reason": "patrol_minor_fine"})
                effects.append({"kind": "scene_end", "reason": "minor_fine"})
                messages.append("You pay a minor fine and they let you go.")
                state.setdefault("world_notes", []).append("[Security] Paid a minor fine.")
                clear_active_scene(state)
                return _scene_return(
                    ok=True,
                    reason="",
                    phase_before=phase_before,
                    phase_after="",
                    ended=True,
                    next_options=[],
                    effects=effects,
                    messages=messages,
                )

            if act in ("run", "flee"):
                ch = _patrol_escape_chance_pct()
                r = scene_rng(state, scene_id=str(sc.get("scene_id", "")), scene_type="police_stop", salt="patrol_escape_v1")
                if int(r) < int(ch):
                    clear_active_scene(state)
                    td = _bump_trace(state, 15)
                    effects.append({"kind": "trace_delta", "delta": int(td), "reason": "patrol_escape"})
                    effects.append({"kind": "scene_end", "reason": "escape"})
                    messages.append("You slip away—but the city will remember.")
                    state.setdefault("world_notes", []).append("[Security] Escaped the patrol, but heat increased.")
                    return _scene_return(
                        ok=True,
                        reason="",
                        phase_before=phase_before,
                        phase_after="",
                        ended=True,
                        next_options=[],
                        effects=effects,
                        messages=messages,
                    )
                execute_arrest(state)
                messages.append("They cut you off. There is no clean exit.")
                return _scene_return(
                    ok=True,
                    reason="arrest",
                    phase_before=phase_before,
                    phase_after="",
                    ended=True,
                    next_options=[],
                    effects=[{"kind": "arrest", "reason": "flee_failed"}],
                    messages=messages,
                )

            if act in ("bribe",):
                br = int(action_ctx.get("bribe_amount", 0) or 0)
                if br <= 0:
                    br = 500
                eco = state.setdefault("economy", {})
                try:
                    cash0 = int(eco.get("cash", 0) or 0)
                except Exception:
                    cash0 = 0
                if br >= 500 and cash0 >= br:
                    eco["cash"] = int(cash0 - br)
                    effects.append({"kind": "cash_delta", "delta": int(-br), "reason": "patrol_bribe_success"})
                    effects.append({"kind": "scene_end", "reason": "bribe"})
                    messages.append("The patrol looks away. You walk before they change their minds.")
                    state.setdefault("world_notes", []).append("[Security] Bribed the patrol successfully.")
                    clear_active_scene(state)
                    return _scene_return(
                        ok=True,
                        reason="",
                        phase_before=phase_before,
                        phase_after="",
                        ended=True,
                        next_options=[],
                        effects=effects,
                        messages=messages,
                    )
                execute_arrest(state, bribery_attempt=True)
                messages.append("The bribe backfires—or you couldn't pay. You are in custody.")
                return _scene_return(
                    ok=True,
                    reason="arrest",
                    phase_before=phase_before,
                    phase_after="",
                    ended=True,
                    next_options=[],
                    effects=[{"kind": "arrest", "reason": "bribe_failed"}],
                    messages=messages,
                )

            return _scene_return(
                ok=False,
                reason="invalid_action",
                phase_before=phase_before,
                phase_after=phase_before,
                ended=False,
                next_options=list(sc.get("next_options") or []),
                effects=[],
                messages=["Invalid scene action for this phase."],
            )

        # Legacy weapon-check stop: COMPLY opens dialog; RUN flees with heat/trace.
        if act in ("comply", "cooperate"):
            sc["phase"] = "dialog"
            sc["next_options"] = [
                "SCENE SAY_NO",
                "SCENE SAY_YES",
                "SCENE SHOW_PERMIT",
                "SCENE BRIBE",
                "SCENE CONCEAL <item_id>",
                "SCENE DUMP <item_id>",
                "SCENE RUN",
            ]
            messages.append("You stop and comply. The officer asks if you are carrying any weapons.")
            return _scene_return(
                ok=True,
                reason="",
                phase_before=phase_before,
                phase_after="dialog",
                ended=False,
                next_options=list(sc.get("next_options") or []),
                effects=effects,
                messages=messages,
            )
        if act in ("run", "flee"):
            td = _bump_trace(state, 8 if law in ("strict", "militarized") else 6)
            try:

                loc, _did = _player_loc(state)
                bump_suspicion(state, loc=loc, delta=6, reason="police_stop_flee", ttl_days=2)
                bump_heat(state, loc=loc, delta=2, reason="police_stop_flee", ttl_days=7)
            except Exception:
                pass
            effects.append({"kind": "trace_delta", "delta": int(td), "reason": "flee_police_stop"})
            effects.append({"kind": "scene_end", "reason": "flee"})
            messages.append("You bolt. Sirens follow—this will escalate.")
            clear_active_scene(state)
            return _scene_return(
                ok=True,
                reason="",
                phase_before=phase_before,
                phase_after="",
                ended=True,
                next_options=[],
                effects=effects,
                messages=messages,
            )
        return _scene_return(
            ok=False,
            reason="invalid_action",
            phase_before=phase_before,
            phase_after=phase_before,
            ended=False,
            next_options=list(sc.get("next_options") or []),
            effects=[],
            messages=["Invalid scene action for this phase."],
        )

    if phase_before == "dialog":
        # Helper: determine if the lie is detected (deterministic).
        def _lie_detected() -> bool:
            base = 55
            if law in ("strict", "militarized"):
                base += 12
            if reason in ("sting", "raid", "undercover"):
                base += 10
            if bool(permit_doc.get("permit_forged", False)):
                base += 6
            base = max(15, min(85, base))
            r = scene_rng(state, scene_id=str(sc.get("scene_id", "")), scene_type="police_stop", salt="lie_detect")
            return r < base

        if act in ("show_permit", "permit"):
            if bool(permit_doc.get("permit_valid", False)):
                td = _bump_trace(state, 1)
                effects.append({"kind": "trace_delta", "delta": int(td), "reason": "permit_presented"})
                effects.append({"kind": "scene_end", "reason": "cleared_with_permit"})
                messages.append("You present your permit. After a quick check, they wave you through.")
                clear_active_scene(state)
                return _scene_return(
                    ok=True,
                    reason="",
                    phase_before=phase_before,
                    phase_after="",
                    ended=True,
                    next_options=[],
                    effects=effects,
                    messages=messages,
                )
            # Invalid/forged suspected -> escalate.
            confisc = _confiscate_items(state, wids)
            td = _bump_trace(state, 10 if law in ("strict", "militarized") else 7)
            effects.append({"kind": "trace_delta", "delta": int(td), "reason": "permit_failed"})
            effects.append({"kind": "confiscate", "items": confisc.get("removed", {}), "total": int(confisc.get("total", 0) or 0)})
            effects.append({"kind": "scene_end", "reason": "permit_failed"})
            messages.append("They scrutinize the document. Something doesn’t add up. Your weapons are confiscated.")
            clear_active_scene(state)
            return _scene_return(
                ok=True,
                reason="",
                phase_before=phase_before,
                phase_after="",
                ended=True,
                next_options=[],
                effects=effects,
                messages=messages,
            )

        if act in ("say_yes", "yes", "admit"):
            if bool(permit_doc.get("permit_valid", False)):
                td = _bump_trace(state, 2)
                effects.append({"kind": "trace_delta", "delta": int(td), "reason": "admitted_with_permit"})
                effects.append({"kind": "scene_end", "reason": "admit_ok"})
                messages.append("You admit it and present valid paperwork. They log it and let you go.")
                clear_active_scene(state)
                return _scene_return(ok=True, reason="", phase_before=phase_before, phase_after="", ended=True, next_options=[], effects=effects, messages=messages)
            confisc = _confiscate_items(state, wids)
            td = _bump_trace(state, 8 if law in ("strict", "militarized") else 6)
            effects.append({"kind": "trace_delta", "delta": int(td), "reason": "admitted_no_permit"})
            effects.append({"kind": "confiscate", "items": confisc.get("removed", {}), "total": int(confisc.get("total", 0) or 0)})
            effects.append({"kind": "scene_end", "reason": "confiscated"})
            messages.append("You admit carrying. Without valid permit, they confiscate the weapon(s).")
            clear_active_scene(state)
            return _scene_return(ok=True, reason="", phase_before=phase_before, phase_after="", ended=True, next_options=[], effects=effects, messages=messages)

        if act in ("say_no", "no", "deny"):
            if wids and _lie_detected():
                # Search resolution: concealed items can reduce what is found (v1).
                try:

                    _sr = resolve_search(state, scene_id=str(sc.get("scene_id", "")), scene_type="police_stop", intensity=80, salt="stop_search")
                    wids = [x for x in wids if x in (_sr.get("found") or wids)]
                except Exception:
                    pass
                confisc = _confiscate_items(state, wids)
                td = _bump_trace(state, 12 if law in ("strict", "militarized") else 9)
                effects.append({"kind": "trace_delta", "delta": int(td), "reason": "lie_detected"})
                effects.append({"kind": "confiscate", "items": confisc.get("removed", {}), "total": int(confisc.get("total", 0) or 0)})
                effects.append({"kind": "scene_end", "reason": "lie_detected"})
                messages.append("They search anyway—and find it. The lie makes it worse. Weapons confiscated.")
                clear_active_scene(state)
                return _scene_return(ok=True, reason="", phase_before=phase_before, phase_after="", ended=True, next_options=[], effects=effects, messages=messages)
            td = _bump_trace(state, 3)
            effects.append({"kind": "trace_delta", "delta": int(td), "reason": "denied"})
            effects.append({"kind": "scene_end", "reason": "released"})
            messages.append("You deny it. After a tense moment, they let you go.")
            clear_active_scene(state)
            return _scene_return(ok=True, reason="", phase_before=phase_before, phase_after="", ended=True, next_options=[], effects=effects, messages=messages)

        if act in ("bribe",):
            eco = state.get("economy", {}) if isinstance(state.get("economy"), dict) else {}
            try:
                cash = int(eco.get("cash", 0) or 0)
            except Exception:
                cash = 0
            base = 300 if law in ("strict", "militarized") else 200
            if bool(permit_doc.get("permit_forged", False)):
                base += 200
            if wids and not bool(permit_doc.get("permit_valid", False)):
                base += 250
            bribe_cost = int(max(150, min(2500, base)))
            if cash < bribe_cost:
                return _scene_return(
                    ok=False,
                    reason="insufficient_cash",
                    phase_before=phase_before,
                    phase_after=phase_before,
                    ended=False,
                    next_options=list(sc.get("next_options") or []),
                    effects=[],
                    messages=[f"Not enough cash to bribe (need {bribe_cost})."],
                )
            eco["cash"] = int(cash - bribe_cost)
            state["economy"] = eco
            td = _bump_trace(state, 4)
            effects.append({"kind": "cash_delta", "delta": int(-bribe_cost), "reason": "bribe"})
            effects.append({"kind": "trace_delta", "delta": int(td), "reason": "bribe_paid"})
            effects.append({"kind": "scene_end", "reason": "bribe"})
            messages.append("You slip them cash. They decide it isn’t worth the paperwork and let you go.")
            clear_active_scene(state)
            return _scene_return(ok=True, reason="", phase_before=phase_before, phase_after="", ended=True, next_options=[], effects=effects, messages=messages)

        if act in ("run", "flee"):
            td = _bump_trace(state, 10 if law in ("strict", "militarized") else 8)
            try:

                loc, _did = _player_loc(state)
                bump_suspicion(state, loc=loc, delta=6, reason="police_stop_flee", ttl_days=2)
                bump_heat(state, loc=loc, delta=2, reason="police_stop_flee", ttl_days=7)
            except Exception:
                pass
            effects.append({"kind": "trace_delta", "delta": int(td), "reason": "flee_after_question"})
            effects.append({"kind": "scene_end", "reason": "flee"})
            messages.append("You run mid-stop. That’s an admission all by itself.")
            clear_active_scene(state)
            return _scene_return(ok=True, reason="", phase_before=phase_before, phase_after="", ended=True, next_options=[], effects=effects, messages=messages)

        if act in ("conceal",):
            arg = str(action_ctx.get("scene_arg", "") or "").strip()
            if not arg:
                return _scene_return(ok=False, reason="missing_arg", phase_before=phase_before, phase_after=phase_before, ended=False, next_options=list(sc.get("next_options") or []), effects=[], messages=["Usage: SCENE CONCEAL <item_id>"])
            try:

                r0 = apply_conceal(state, item_id=arg, method="body")
            except Exception:
                r0 = {"ok": False, "reason": "conceal_failed"}
            if not bool(r0.get("ok")):
                return _scene_return(ok=False, reason=str(r0.get("reason", "conceal_failed") or "conceal_failed"), phase_before=phase_before, phase_after=phase_before, ended=False, next_options=list(sc.get("next_options") or []), effects=[], messages=["Conceal failed."])
            return _scene_return(ok=True, reason="", phase_before=phase_before, phase_after=phase_before, ended=False, next_options=list(sc.get("next_options") or []), effects=[{"kind": "conceal", "item_id": arg}], messages=[f"You conceal {arg}."])

        if act in ("dump", "ditch"):
            arg = str(action_ctx.get("scene_arg", "") or "").strip()
            if not arg:
                return _scene_return(ok=False, reason="missing_arg", phase_before=phase_before, phase_after=phase_before, ended=False, next_options=list(sc.get("next_options") or []), effects=[], messages=["Usage: SCENE DUMP <item_id>"])
            try:

                r0 = apply_dump(state, item_id=arg)
            except Exception:
                r0 = {"ok": False, "reason": "dump_failed"}
            if not bool(r0.get("ok")):
                return _scene_return(ok=False, reason=str(r0.get("reason", "dump_failed") or "dump_failed"), phase_before=phase_before, phase_after=phase_before, ended=False, next_options=list(sc.get("next_options") or []), effects=[], messages=["Dump failed."])
            return _scene_return(ok=True, reason="", phase_before=phase_before, phase_after=phase_before, ended=False, next_options=list(sc.get("next_options") or []), effects=[{"kind": "inventory_remove", "item_id": arg, "count": 1, "reason": "dump"}], messages=[f"You ditch {arg}."])

        return _scene_return(
            ok=False,
            reason="invalid_action",
            phase_before=phase_before,
            phase_after=phase_before,
            ended=False,
            next_options=list(sc.get("next_options") or []),
            effects=[],
            messages=["Invalid scene action for this phase."],
        )

    return _scene_return(
        ok=False,
        reason="invalid_phase",
        phase_before=phase_before,
        phase_after=phase_before,
        ended=False,
        next_options=list(sc.get("next_options") or []),
        effects=[],
        messages=["Scene is in an unknown phase."],
    )


def _auto_resolve_police_stop(state: dict[str, Any], sc: dict[str, Any], *, phase_before: str) -> dict[str, Any]:
    """Timeout policy: treat as non-cooperation escalation (worse than RUN)."""
    ctx = sc.get("context") if isinstance(sc.get("context"), dict) else {}
    law = str((ctx or {}).get("law_level", "") or "").strip().lower()
    td = _bump_trace(state, 12 if law in ("strict", "militarized") else 10)
    clear_active_scene(state)
    try:

        loc, did = _player_loc(state)
        append_casefile(
            state,
            {
                "kind": "scene_timeout",
                "scene_type": "police_stop",
                "event_type": "police_weapon_check",
                "location": loc,
                "district": did,
                "summary": "Police stop timed out; escalation applied.",
                "tags": ["timeout", "police"],
                "meta": {"trace_delta": int(td)},
            },
        )
    except Exception:
        pass
    return _scene_return(
        ok=True,
        reason="timeout",
        phase_before=phase_before,
        phase_after="",
        ended=True,
        next_options=[],
        effects=[
            {"kind": "trace_delta", "delta": int(td), "reason": "police_stop_timeout"},
            {"kind": "scene_end", "reason": "timeout"},
        ],
        messages=["You hesitate too long. The stop escalates and your trace spikes."],
    )


def start_sting_setup_scene(state: dict[str, Any], *, payload: dict[str, Any]) -> dict[str, Any]:
    if has_active_scene(state):
        return {"ok": False, "reason": "scene_already_active"}
    flags = state.get("flags", {}) or {}
    if isinstance(flags, dict) and not bool(flags.get("scenes_enabled", True)):
        return {"ok": False, "reason": "scenes_disabled"}
    loc, did = _player_loc(state)
    iid = str((payload or {}).get("bought_item_id", "") or "").strip()
    scene_id = hashlib.md5(f"{_seed_key(state)}|sting_setup|{loc}|{did}|{iid}".encode("utf-8", errors="ignore")).hexdigest()[:10]
    day, tmin = _now(state)
    sc = {
        "scene_id": scene_id,
        "scene_type": "sting_setup",
        "phase": "realization",
        "context": {
            "location": loc,
            "district": did,
            "bought_item_id": iid,
            "district_police_presence": int((payload or {}).get("district_police_presence", 0) or 0),
            "sting_bias": str((payload or {}).get("sting_bias", "") or "").strip().lower(),
        },
        "vars": {"wait_count": 0},
        "expires_at": {"day": int(day), "time_min": min(1439, int(tmin) + 15)},
        "next_options": ["SCENE LAY_LOW", "SCENE DITCH_ITEMS", "SCENE WALK_AWAY", "SCENE RUN"],
    }
    state["active_scene"] = sc
    state.setdefault("world_notes", []).append("[Scene] start sting_setup")
    try:

        append_casefile(
            state,
            {
                "kind": "scene_start",
                "scene_type": "sting_setup",
                "event_type": "undercover_sting",
                "location": loc,
                "district": did,
                "summary": f"Sting suspicion triggered (item={iid or '-'})",
                "tags": ["sting", "police"],
                "meta": {"bought_item_id": iid},
            },
        )
    except Exception:
        pass
    return {"ok": True, "scene_id": scene_id, "scene_type": "sting_setup"}


def _schedule_police_stop_from_sting(state: dict[str, Any], *, reason: str, sting_item_id: str) -> dict[str, Any]:
    """Schedule a police weapon check follow-up (scene-first system will convert it)."""
    try:

        has_illegal, wids = _has_illegal_weapon(state)
        if has_illegal and wids:
            schedule_weapon_check(state, weapon_ids=wids, reason=reason, extra_payload={"sting_item_id": sting_item_id, "sting": True})
            return {"ok": True, "weapon_ids": list(wids)}
    except Exception:
        pass
    return {"ok": False}


def _auto_resolve_sting_setup(state: dict[str, Any], sc: dict[str, Any], *, phase_before: str) -> dict[str, Any]:
    """Timeout policy: pressure escalates into a follow-up stop if weapons present."""
    ctx = sc.get("context") if isinstance(sc.get("context"), dict) else {}
    iid = str((ctx or {}).get("bought_item_id", "") or "").strip()
    td = _bump_trace(state, 4)
    follow = _schedule_police_stop_from_sting(state, reason="sting_timeout", sting_item_id=iid)
    clear_active_scene(state)
    try:

        loc, did = _player_loc(state)
        append_casefile(
            state,
            {
                "kind": "scene_timeout",
                "scene_type": "sting_setup",
                "event_type": "undercover_sting",
                "location": loc,
                "district": did,
                "summary": "Sting scene timed out; escalation scheduled.",
                "tags": ["timeout", "sting"],
                "meta": {"trace_delta": int(td), "followup": follow},
            },
        )
    except Exception:
        pass
    return _scene_return(
        ok=True,
        reason="timeout",
        phase_before=phase_before,
        phase_after="",
        ended=True,
        next_options=[],
        effects=[
            {"kind": "trace_delta", "delta": int(td), "reason": "sting_timeout"},
            {"kind": "event_schedule", "event_type": "police_weapon_check", "due_day": _now(state)[0], "due_time": min(1439, _now(state)[1] + 1), "reason": "sting_timeout"},
            {"kind": "scene_end", "reason": "timeout"},
        ],
        messages=["You wait too long. The tail tightens and a stop is imminent."],
    )


def _advance_sting_setup(state: dict[str, Any], sc: dict[str, Any], action_ctx: dict[str, Any]) -> dict[str, Any]:
    phase_before = str(sc.get("phase", "") or "")
    act = str(action_ctx.get("scene_action", "") or "").strip().lower().replace("-", "_")
    ctx = sc.get("context") if isinstance(sc.get("context"), dict) else {}
    iid = str((ctx or {}).get("bought_item_id", "") or "").strip()
    pp = int((ctx or {}).get("district_police_presence", 0) or 0)
    effects: list[dict[str, Any]] = []
    messages: list[str] = []

    if phase_before == "realization":
        # One-step resolution actions.
        if act in ("lay_low", "laylow"):
            td = _bump_trace(state, 1 + (1 if pp >= 4 else 0))
            effects.append({"kind": "trace_delta", "delta": int(td), "reason": "sting_lay_low"})
            effects.append({"kind": "time_advance", "minutes": 10})
            effects.append({"kind": "scene_end", "reason": "lay_low"})
            clear_active_scene(state)
            return _scene_return(ok=True, reason="", phase_before=phase_before, phase_after="", ended=True, next_options=[], effects=effects, messages=["You slow down, blend in, and let the moment pass."])
        if act in ("ditch_items", "ditch", "drop"):
            removed = {}
            if iid:
                c = _confiscate_items(state, [iid])
                removed = c.get("removed", {}) if isinstance(c, dict) else {}
            td = _bump_trace(state, 2 + (1 if pp >= 4 else 0))
            effects.append({"kind": "trace_delta", "delta": int(td), "reason": "sting_ditch"})
            if removed:
                effects.append({"kind": "inventory_remove", "item_id": iid, "count": int(removed.get(iid, 0) or 0), "reason": "ditched"})
            effects.append({"kind": "scene_end", "reason": "ditch_items"})
            clear_active_scene(state)
            return _scene_return(ok=True, reason="", phase_before=phase_before, phase_after="", ended=True, next_options=[], effects=effects, messages=["You quietly get rid of anything that links you to the transaction."])
        if act in ("walk_away", "walkaway", "leave"):
            td = _bump_trace(state, 3 + (1 if pp >= 4 else 0))
            follow = _schedule_police_stop_from_sting(state, reason="sting_walk_away", sting_item_id=iid)
            effects.append({"kind": "trace_delta", "delta": int(td), "reason": "sting_walk_away"})
            if bool(follow.get("ok")):
                effects.append({"kind": "event_schedule", "event_type": "police_weapon_check", "due_day": _now(state)[0], "due_time": min(1439, _now(state)[1] + 1), "reason": "sting_walk_away"})
            effects.append({"kind": "scene_end", "reason": "walk_away"})
            clear_active_scene(state)
            return _scene_return(ok=True, reason="", phase_before=phase_before, phase_after="", ended=True, next_options=[], effects=effects, messages=["You walk away calmly, but you can feel eyes tracking you."])
        if act in ("run", "flee"):
            td = _bump_trace(state, 7 + (2 if pp >= 4 else 0))
            follow = _schedule_police_stop_from_sting(state, reason="sting_run", sting_item_id=iid)
            effects.append({"kind": "trace_delta", "delta": int(td), "reason": "sting_run"})
            if bool(follow.get("ok")):
                effects.append({"kind": "event_schedule", "event_type": "police_weapon_check", "due_day": _now(state)[0], "due_time": min(1439, _now(state)[1] + 1), "reason": "sting_run"})
            effects.append({"kind": "scene_end", "reason": "run"})
            clear_active_scene(state)
            return _scene_return(ok=True, reason="", phase_before=phase_before, phase_after="", ended=True, next_options=[], effects=effects, messages=["You run. That confirms their suspicion."])

        return _scene_return(ok=False, reason="invalid_action", phase_before=phase_before, phase_after=phase_before, ended=False, next_options=list(sc.get("next_options") or []), effects=[], messages=["Invalid scene action."])

    return _scene_return(ok=False, reason="invalid_phase", phase_before=phase_before, phase_after=phase_before, ended=False, next_options=list(sc.get("next_options") or []), effects=[], messages=["Scene is in an unknown phase."])


def _advance_sting_operation(state: dict[str, Any], sc: dict[str, Any], action_ctx: dict[str, Any]) -> dict[str, Any]:
    """Hard consequence scene: surrender, flee (30%), or fight (auto-fail)."""

    phase_before = str(sc.get("phase", "") or "")
    act = str(action_ctx.get("scene_action", "") or "").strip().lower().replace("-", "_")
    if act in ("surrender", "comply"):
        execute_arrest(state)
        state.setdefault("world_notes", []).append("[Security] You surrendered to the sting team. Arrest processed.")
        return _scene_return(ok=True, reason="arrest", phase_before=phase_before, phase_after="", ended=True, next_options=[], effects=[{"kind": "arrest", "reason": "sting_surrender"}], messages=["You put your hands up. The net closes immediately."])

    if act in ("flee", "run"):
        chance = 30
        roll = scene_rng(state, scene_id=str(sc.get("scene_id", "sting")), scene_type="sting_operation", salt="flee|v1")
        if int(roll) < int(chance):
            clear_active_scene(state)
            td = _bump_trace(state, 20)
            state.setdefault("world_notes", []).append("[Security] You slipped the sting, but the escape left a heavy trail.")
            return _scene_return(ok=True, reason="", phase_before=phase_before, phase_after="", ended=True, next_options=[], effects=[{"kind": "trace_delta", "delta": int(td), "reason": "sting_escape"}, {"kind": "scene_end", "reason": "flee"}], messages=["You vanish into the noise—barely."])
        execute_arrest(state)
        return _scene_return(ok=True, reason="arrest", phase_before=phase_before, phase_after="", ended=True, next_options=[], effects=[{"kind": "arrest", "reason": "sting_flee_failed"}], messages=["The ambush was layered. You run straight into cuffs."])

    if act in ("fight", "attack"):
        execute_arrest(state)
        # Max penalty: wipe bank balance after arrest processing.
        try:
            eco = state.get("economy", {}) or {}
            if isinstance(eco, dict):
                eco["bank"] = 0
                state["economy"] = eco
        except Exception:
            pass
        state.setdefault("world_notes", []).append("[Security] Fighting a sting squad ended in a maximum fine and arrest.")
        return _scene_return(ok=True, reason="arrest", phase_before=phase_before, phase_after="", ended=True, next_options=[], effects=[{"kind": "arrest", "reason": "sting_fight_auto_fail"}, {"kind": "fine_max", "reason": "sting_fight"}], messages=["You swing once. The response is overwhelming and final."])

    return _scene_return(ok=False, reason="invalid_action", phase_before=phase_before, phase_after=phase_before, ended=False, next_options=list(sc.get("next_options") or []), effects=[], messages=["Invalid scene action."])


def _burn_safehouse_after_raid(state: dict[str, Any], *, loc: str) -> None:
    world = state.setdefault("world", {})
    sh = world.setdefault("safehouses", {})
    row = sh.get(loc) if isinstance(sh, dict) else None
    if not isinstance(row, dict):
        return
    row["status"] = "none"
    row["stash"] = []
    row["stash_ammo"] = {}
    sh[loc] = row
    world["safehouses"] = sh


def start_safehouse_raid_scene(state: dict[str, Any], *, payload: dict[str, Any]) -> dict[str, Any]:
    if has_active_scene(state):
        return {"ok": False, "reason": "scene_already_active"}
    loc, did = _player_loc(state)
    loc0 = str((payload or {}).get("location", loc) or loc).strip().lower()
    day, tmin = _now(state)
    scene_id = hashlib.md5(f"{_seed_key(state)}|safehouse_raid|{loc0}|{day}|{tmin}".encode("utf-8", errors="ignore")).hexdigest()[:10]
    state["active_scene"] = {
        "scene_id": scene_id,
        "scene_type": "safehouse_raid",
        "phase": "breach",
        "context": {
            "location": loc0,
            "district": did,
            "payload": dict(payload or {}),
        },
        "vars": {"wait_count": 0},
        "expires_at": {"day": int(day), "time_min": min(1439, int(tmin) + 20)},
        "next_options": ["SCENE COMPLY", "SCENE FLEE", "SCENE HIDE", "SCENE FIGHT"],
    }
    return {"ok": True, "scene_id": scene_id, "scene_type": "safehouse_raid"}


def _auto_resolve_safehouse_raid(state: dict[str, Any], sc: dict[str, Any], *, phase_before: str) -> dict[str, Any]:
    return _advance_safehouse_raid(state, sc, {"scene_action": "comply", "scene_timeout": True})


def _advance_safehouse_raid(state: dict[str, Any], sc: dict[str, Any], action_ctx: dict[str, Any]) -> dict[str, Any]:

    phase_before = str(sc.get("phase", "") or "")
    act = str(action_ctx.get("scene_action", "") or "").strip().lower().replace("-", "_")
    ctx = sc.get("context") if isinstance(sc.get("context"), dict) else {}
    payload = (ctx or {}).get("payload") if isinstance((ctx or {}).get("payload"), dict) else {}
    loc = str((payload or {}).get("location", "") or (ctx or {}).get("location", "") or _player_loc(state)[0]).strip().lower()
    law = str((payload or {}).get("law_level", "") or (ctx or {}).get("law_level", "") or "").strip().lower()

    def _escape_chance(stat_key: str) -> int:
        base = 30
        try:
            row = (state.get("skills", {}) or {}).get(stat_key)
            lvl = int((row or {}).get("level", 1) or 1)
        except Exception:
            lvl = 1
        return min(85, base + max(0, (lvl - 1) * 4))

    if act in ("comply", "cooperate"):
        _burn_safehouse_after_raid(state, loc=loc)
        execute_arrest(state)
        state.setdefault("world_notes", []).append("[Arrest] You surrendered during the raid. The location is burned.")
        return _scene_return(ok=True, reason="arrest", phase_before=phase_before, phase_after="", ended=True, next_options=[], effects=[{"kind": "arrest", "reason": "raid_comply"}], messages=["You raise your hands. The breach team owns the room in seconds."])

    if act in ("flee", "run", "hide"):
        stat_key = "evasion" if act in ("flee", "run") else "stealth"
        chance = _escape_chance(stat_key)
        roll = scene_rng(state, scene_id=str(sc.get("scene_id", "")), scene_type="safehouse_raid", salt=f"{act}|escape_v1")
        _burn_safehouse_after_raid(state, loc=loc)
        if int(roll) < int(chance):
            clear_active_scene(state)
            td = _bump_trace(state, 20)
            state.setdefault("world_notes", []).append("[Security] You barely escaped the raid, but this location is burned.")
            return _scene_return(ok=True, reason="", phase_before=phase_before, phase_after="", ended=True, next_options=[], effects=[{"kind": "trace_delta", "delta": int(td), "reason": "raid_escape"}, {"kind": "scene_end", "reason": act}], messages=["You get out by inches. The place behind you is finished."])
        execute_arrest(state)
        return _scene_return(ok=True, reason="arrest", phase_before=phase_before, phase_after="", ended=True, next_options=[], effects=[{"kind": "arrest", "reason": f"raid_{act}_failed"}], messages=["The tactical cordon closes before you can vanish."])

    if act in ("fight",):
        _burn_safehouse_after_raid(state, loc=loc)
        execute_arrest(state)
        return _scene_return(ok=True, reason="arrest", phase_before=phase_before, phase_after="", ended=True, next_options=[], effects=[{"kind": "arrest", "reason": "raid_fight_auto_fail"}], messages=["Trying to fight a tactical entry team lasts exactly one bad decision."])

    return _scene_return(ok=False, reason="invalid_action", phase_before=phase_before, phase_after=phase_before, ended=False, next_options=list(sc.get("next_options") or []), effects=[], messages=["Invalid scene action."])


def start_raid_response_scene(state: dict[str, Any], *, payload: dict[str, Any]) -> dict[str, Any]:
    if has_active_scene(state):
        return {"ok": False, "reason": "scene_already_active"}
    flags = state.get("flags", {}) or {}
    if isinstance(flags, dict) and not bool(flags.get("scenes_enabled", True)):
        return {"ok": False, "reason": "scenes_disabled"}
    loc, did = _player_loc(state)
    sh_loc = str((payload or {}).get("location", loc) or loc).strip().lower()
    scene_id = hashlib.md5(f"{_seed_key(state)}|raid_response|{sh_loc}".encode("utf-8", errors="ignore")).hexdigest()[:10]
    day, tmin = _now(state)
    sc = {
        "scene_id": scene_id,
        "scene_type": "raid_response",
        "phase": "knock",
        "context": {
            "location": sh_loc,
            "district": did,
            "payload": dict(payload or {}),
        },
        "vars": {"wait_count": 0},
        "expires_at": {"day": int(day), "time_min": min(1439, int(tmin) + 25)},
        "next_options": ["SCENE COMPLY", "SCENE HIDE", "SCENE BRIBE", "SCENE FLEE", "SCENE SHOW_PERMIT"],
    }
    state["active_scene"] = sc
    state.setdefault("world_notes", []).append(f"[Scene] start raid_response loc={sh_loc}")
    try:

        append_casefile(
            state,
            {
                "kind": "scene_start",
                "scene_type": "raid_response",
                "event_type": "safehouse_raid",
                "location": sh_loc,
                "district": did,
                "summary": "Safehouse raid triggered; awaiting response.",
                "tags": ["raid", "police"],
                "meta": {"location": sh_loc},
            },
        )
    except Exception:
        pass
    return {"ok": True, "scene_id": scene_id, "scene_type": "raid_response"}


def _auto_resolve_raid_response(state: dict[str, Any], sc: dict[str, Any], *, phase_before: str) -> dict[str, Any]:
    """Timeout policy: comply (bad) by default."""
    return _advance_raid_response(state, sc, {"scene_action": "comply", "scene_timeout": True})


def _advance_raid_response(state: dict[str, Any], sc: dict[str, Any], action_ctx: dict[str, Any]) -> dict[str, Any]:
    phase_before = str(sc.get("phase", "") or "")
    act = str(action_ctx.get("scene_action", "") or "").strip().lower().replace("-", "_")
    ctx = sc.get("context") if isinstance(sc.get("context"), dict) else {}
    payload = (ctx or {}).get("payload") if isinstance((ctx or {}).get("payload"), dict) else {}
    if not isinstance(payload, dict):
        payload = {}
    loc = str(payload.get("location", "") or (ctx or {}).get("location", "") or "").strip().lower()
    if not loc:
        loc = _player_loc(state)[0]

    # Extract from payload (same fields as old timers handler).
    law_level = str(payload.get("law_level", "") or "").strip()
    corruption = str(payload.get("corruption", "") or "").strip().lower()
    firearm_policy = str(payload.get("firearm_policy", "") or "").strip().lower()
    has_permit = bool(payload.get("has_weapon_permit", False))
    disguise_active = bool(payload.get("disguise_active", False))
    sec = int(payload.get("security_level", 1) or 1)
    hot = payload.get("hot_item_ids", []) or []
    if not isinstance(hot, list):
        hot = []

    # Optional bribe amount passed via action_ctx.
    bribe_amt = 0
    try:
        bribe_amt = int(action_ctx.get("bribe_amount", 0) or 0)
    except Exception:
        bribe_amt = 0

    response = act
    if response in ("open", "ok", "cooperate"):
        response = "comply"
    if response not in ("comply", "hide", "bribe", "flee", "show_permit"):
        return _scene_return(ok=False, reason="invalid_action", phase_before=phase_before, phase_after=phase_before, ended=False, next_options=list(sc.get("next_options") or []), effects=[], messages=["Invalid scene action."])

    # Apply the old deterministic raid resolution here (scene owns consequences).
    eff_sec = sec
    miss_bonus = 0
    trace_bonus = 0
    bribe_success = False
    bribe_backfire = False
    if response == "hide":
        eff_sec = min(10, sec + 2)
        miss_bonus += 12
        trace_bonus += 1
    elif response == "flee":
        trace_bonus += 6
    elif response == "show_permit":
        if has_permit and firearm_policy in ("permit_friendly", "standard_permit", "lenient"):
            miss_bonus += 10
            trace_bonus -= 1
        else:
            trace_bonus += 2
    elif response == "bribe":
        # Charge bribe (realism).
        eco = state.get("economy", {}) if isinstance(state.get("economy"), dict) else {}
        try:
            cash = int(eco.get("cash", 0) or 0)
        except Exception:
            cash = 0
        if bribe_amt <= 0:
            # default bribe amount if player uses SCENE BRIBE without number
            bribe_amt = 400
        if cash < bribe_amt:
            return _scene_return(ok=False, reason="insufficient_cash", phase_before=phase_before, phase_after=phase_before, ended=False, next_options=list(sc.get("next_options") or []), effects=[], messages=[f"Not enough cash to bribe (need {bribe_amt})."])
        eco["cash"] = int(cash - bribe_amt)
        state["economy"] = eco

        base = 30
        if corruption == "high":
            base += 20
        elif corruption == "low":
            base -= 15
        amt_score = min(35, int(bribe_amt / 40))
        success_rate = max(0, min(85, base + amt_score))
        backfire_rate = max(0, min(40, 18 - (8 if corruption == "high" else 0) + (5 if corruption == "low" else 0)))
        rb = scene_rng(state, scene_id=str(sc.get("scene_id", "")), scene_type="raid_response", salt=f"bribe|{bribe_amt}")
        if rb < backfire_rate:
            bribe_backfire = True
            trace_bonus += 10
        elif rb < backfire_rate + success_rate:
            bribe_success = True
            miss_bonus += 25
            trace_bonus -= 2
        else:
            trace_bonus += 4

    if disguise_active:
        miss_bonus += 6
        trace_bonus = max(-3, trace_bonus - 1)

    # Confiscate contraband from safehouse stash/ammo.
    world = state.setdefault("world", {})
    sh = world.setdefault("safehouses", {})
    row = sh.get(loc) if isinstance(sh, dict) else None
    confiscated: list[str] = []
    ammo_confiscated: dict[str, int] = {}
    if isinstance(row, dict):
        row["last_raid_day"] = int(_now(state)[0])
        row["raid_count"] = int(row.get("raid_count", 0) or 0) + 1
        stash_ammo = row.get("stash_ammo") or {}
        if not isinstance(stash_ammo, dict):
            stash_ammo = {}
        hot_s = [str(x) for x in hot]
        for aid, n in list(stash_ammo.items())[:200]:
            try:
                nn = int(n or 0)
            except Exception:
                nn = 0
            if nn <= 0:
                continue
            if str(aid) not in hot_s:
                continue
            r0 = scene_rng(state, scene_id=str(sc.get("scene_id", "")), scene_type="raid_response", salt=f"raid_ammo|{loc}|{aid}")
            miss0 = r0 < max(0, min(85, eff_sec * 10 + miss_bonus))
            if miss0:
                continue
            take = max(1, min(nn, 10 + int(nn * (0.35 if law_level.lower() in ("strict", "militarized") else 0.25))))
            stash_ammo[str(aid)] = max(0, nn - take)
            ammo_confiscated[str(aid)] = int(take)
            if str(aid) not in confiscated:
                confiscated.append(str(aid))
        row["stash_ammo"] = stash_ammo

        stash = row.get("stash") or []
        if isinstance(stash, list) and stash:
            kept: list[Any] = []
            for ent in stash:
                iid = ""
                if isinstance(ent, dict):
                    iid = str(ent.get("item_id", "") or "").strip()
                elif isinstance(ent, str):
                    iid = ent.strip()
                if iid and iid in hot_s:
                    r = scene_rng(state, scene_id=str(sc.get("scene_id", "")), scene_type="raid_response", salt=f"raid_item|{loc}|{iid}")
                    miss = r < max(0, min(85, eff_sec * 10 + miss_bonus))
                    if miss:
                        kept.append(ent)
                    else:
                        confiscated.append(iid)
                    continue
                kept.append(ent)
            row["stash"] = kept
        cd = 2 + (1 if law_level.lower() in ("strict", "militarized") else 0) + (1 if bribe_backfire or response == "flee" else 0)
        row["raid_cooldown_until_day"] = max(int(row.get("raid_cooldown_until_day", 0) or 0), int(_now(state)[0]) + cd)
        sh[loc] = row
        world["safehouses"] = sh

    # Restrictions aftermath (scene-owned).
    try:
        wlocs = world.setdefault("locations", {})
        if isinstance(wlocs, dict) and loc:
            wlocs.setdefault(loc, {})
            slot = wlocs.get(loc)
            if isinstance(slot, dict):
                slot.setdefault("restrictions", {})
                rmap = slot.get("restrictions")
                if isinstance(rmap, dict):
                    until = int(rmap.get("police_sweep_until_day", 0) or 0)
                    extra = 2 if law_level.lower() in ("strict", "militarized") else 1
                    rmap["police_sweep_until_day"] = max(until, int(_now(state)[0]) + extra)
                    rmap["police_sweep_attention"] = "investigated"
                slot.setdefault("tags", [])
                tags = slot.get("tags")
                if isinstance(tags, list) and "police_sweep" not in [str(x).lower() for x in tags]:
                    tags.append("police_sweep")
                    slot["tags"] = tags
                wlocs[loc] = slot
                world["locations"] = wlocs
    except Exception:
        pass

    bump = 4 + (3 if law_level.lower() in ("strict", "militarized") else 0) + min(8, len(confiscated) * 2) + trace_bonus
    td = _bump_trace(state, bump)

    effects: list[dict[str, Any]] = []
    if response == "bribe":
        effects.append({"kind": "cash_delta", "delta": int(-bribe_amt), "reason": "raid_bribe"})
    effects.append({"kind": "trace_delta", "delta": int(td), "reason": "safehouse_raid"})
    effects.append({"kind": "confiscate", "items": {x: 1 for x in confiscated}, "total": int(len(confiscated)), "from": "safehouse_stash"})
    for aid, n in list(ammo_confiscated.items())[:12]:
        effects.append({"kind": "ammo_remove", "item_id": str(aid), "count": int(n), "reason": "raid_confiscation"})
    effects.append({"kind": "restriction_add", "restriction_id": "police_sweep", "until_day": int(_now(state)[0]) + (2 if law_level.lower() in ("strict", "militarized") else 1), "reason": "raid_aftermath"})
    effects.append({"kind": "scene_end", "reason": response if not bool(action_ctx.get("scene_timeout")) else "timeout"})

    clear_active_scene(state)
    try:

        loc2, did2 = _player_loc(state)
        append_casefile(
            state,
            {
                "kind": "scene_end",
                "scene_type": "raid_response",
                "event_type": "safehouse_raid",
                "location": loc,
                "district": did2,
                "summary": f"Raid resolved via {response}; confiscated={len(confiscated)} trace+={td}",
                "tags": ["raid", response],
                "meta": {"confiscated": confiscated[:12], "ammo_confiscated": ammo_confiscated, "trace_delta": int(td), "bribe_success": bribe_success, "bribe_backfire": bribe_backfire},
            },
        )
    except Exception:
        pass

    msg = f"Raid resolved ({response})."
    if confiscated:
        msg += " Confiscated: " + ", ".join(confiscated[:5]) + (" ..." if len(confiscated) > 5 else "")
    else:
        msg += " No hot items found."
    return _scene_return(ok=True, reason="", phase_before=phase_before, phase_after="", ended=True, next_options=[], effects=effects, messages=[msg])


def _advance_drop_pickup(state: dict[str, Any], sc: dict[str, Any], action_ctx: dict[str, Any]) -> dict[str, Any]:
    phase_before = str(sc.get("phase", "") or "")
    act = str(action_ctx.get("scene_action", "") or "").strip().lower().replace("-", "_")
    effects: list[dict[str, Any]] = []
    messages: list[str] = []

    if phase_before == "spot_package":
        if act in ("approach",):
            sc["phase"] = "approach"
            sc["next_options"] = ["SCENE TAKE", "SCENE ABORT", "SCENE WAIT"]
            messages.append("You move closer to the drop.")
            return _scene_return(
                ok=True,
                reason="",
                phase_before=phase_before,
                phase_after="approach",
                ended=False,
                next_options=list(sc.get("next_options") or []),
                effects=effects,
                messages=messages,
            )
        if act in ("abort",):
            clear_active_scene(state)
            effects.append({"kind": "scene_end", "reason": "abort"})
            messages.append("You back off and leave the package untouched.")
            return _scene_return(
                ok=True,
                reason="",
                phase_before=phase_before,
                phase_after="",
                ended=True,
                next_options=[],
                effects=effects,
                messages=messages,
            )
        if act in ("wait",):
            return _scene_wait(state, sc, phase_before=phase_before)
        return _scene_return(
            ok=False,
            reason="invalid_action",
            phase_before=phase_before,
            phase_after=phase_before,
            ended=False,
            next_options=list(sc.get("next_options") or []),
            effects=[],
            messages=["Invalid scene action for this phase."],
        )

    if phase_before == "approach":
        if act in ("take",):
            return _scene_take_delivery(state, sc, phase_before=phase_before)
        if act in ("abort",):
            clear_active_scene(state)
            effects.append({"kind": "scene_end", "reason": "abort"})
            messages.append("You abort and walk away.")
            return _scene_return(
                ok=True,
                reason="",
                phase_before=phase_before,
                phase_after="",
                ended=True,
                next_options=[],
                effects=effects,
                messages=messages,
            )
        if act in ("wait",):
            return _scene_wait(state, sc, phase_before=phase_before)
        return _scene_return(
            ok=False,
            reason="invalid_action",
            phase_before=phase_before,
            phase_after=phase_before,
            ended=False,
            next_options=list(sc.get("next_options") or []),
            effects=[],
            messages=["Invalid scene action for this phase."],
        )

    return _scene_return(
        ok=False,
        reason="invalid_phase",
        phase_before=phase_before,
        phase_after=phase_before,
        ended=False,
        next_options=list(sc.get("next_options") or []),
        effects=[],
        messages=["Scene is in an unknown phase."],
    )


def _scene_wait(state: dict[str, Any], sc: dict[str, Any], *, phase_before: str) -> dict[str, Any]:
    vars0 = sc.get("vars") if isinstance(sc.get("vars"), dict) else {}
    if not isinstance(vars0, dict):
        vars0 = {}
        sc["vars"] = vars0
    try:
        wc = int(vars0.get("wait_count", 0) or 0)
    except Exception:
        wc = 0
    if wc >= 2:
        return _scene_return(
            ok=False,
            reason="wait_limit_reached",
            phase_before=phase_before,
            phase_after=phase_before,
            ended=False,
            next_options=list(sc.get("next_options") or []),
            effects=[],
            messages=["Wait limit reached."],
        )
    wc += 1
    vars0["wait_count"] = wc
    sc["vars"] = vars0

    # Extend scene deadline by +60 minutes.
    exp = sc.get("expires_at") if isinstance(sc.get("expires_at"), dict) else {}
    if not isinstance(exp, dict):
        exp = {}
    try:
        ed = int(exp.get("day", 1) or 1)
    except Exception:
        ed = 1
    try:
        et = int(exp.get("time_min", 0) or 0)
    except Exception:
        et = 0
    # Extend the scene deadline by +60 minutes, but never beyond the delivery's own expiry (R2 clamp).
    et2 = et + 60
    while et2 >= 1440:
        et2 -= 1440
        ed += 1
    # Clamp to delivery expiry if present.
    ext_minutes = 60
    ctx = sc.get("context") if isinstance(sc.get("context"), dict) else {}
    dex = (ctx or {}).get("delivery_expire_at") if isinstance((ctx or {}).get("delivery_expire_at"), dict) else None
    if isinstance(dex, dict):
        try:
            dd = int(dex.get("day", 0) or 0)
        except Exception:
            dd = 0
        try:
            dt = int(dex.get("time_min", 0) or 0)
        except Exception:
            dt = 0
        if dd > 0 and (dd, dt) < (ed, et2):
            # compute how many minutes we actually extended to reach clamp
            before_total = int(exp.get("day", 0) or 0) * 1440 + int(exp.get("time_min", 0) or 0)
            clamp_total = int(dd) * 1440 + int(dt)
            ext_minutes = max(0, min(60, clamp_total - before_total))
            ed, et2 = int(dd), int(dt)

    exp["day"] = int(ed)
    exp["time_min"] = int(et2)
    sc["expires_at"] = exp

    # The dispatcher should pass a turn by running update_timers with instant_minutes=5.
    effects = [
        {"kind": "time_advance", "minutes": 5},
        {"kind": "scene_extend_deadline", "minutes": int(ext_minutes), "wait_count": int(wc)},
    ]
    messages = ["You wait and watch the area."]
    return _scene_return(
        ok=True,
        reason="",
        phase_before=phase_before,
        phase_after=phase_before,
        ended=False,
        next_options=list(sc.get("next_options") or []),
        effects=effects,
        messages=messages,
    )


def _scene_take_delivery(state: dict[str, Any], sc: dict[str, Any], *, phase_before: str) -> dict[str, Any]:
    ctx = sc.get("context") if isinstance(sc.get("context"), dict) else {}
    delivery_id = str((ctx or {}).get("delivery_id", "") or "").strip()
    if not delivery_id:
        clear_active_scene(state)
        return _scene_return(
            ok=False,
            reason="missing_delivery_id",
            phase_before=phase_before,
            phase_after="",
            ended=True,
            next_options=[],
            effects=[{"kind": "scene_end", "reason": "error"}],
            messages=["Delivery context missing; ending scene."],
        )

    # Ensure the target delivery object is the first match in nearby_items (pickup uses item_id).
    world = state.get("world", {}) or {}
    nearby = world.get("nearby_items", []) if isinstance(world, dict) else []
    if not isinstance(nearby, list):
        nearby = []
    target_idx = None
    target_item_id = ""
    for i, x in enumerate(nearby[:60]):
        if isinstance(x, dict) and str(x.get("delivery_id", "") or "").strip() == delivery_id:
            target_idx = i
            target_item_id = str(x.get("id", "") or "").strip()
            break
    if target_idx is None or not target_item_id:
        clear_active_scene(state)
        return _scene_return(
            ok=False,
            reason="delivery_object_missing",
            phase_before=phase_before,
            phase_after="",
            ended=True,
            next_options=[],
            effects=[{"kind": "scene_end", "reason": "missing_object"}],
            messages=["The package is no longer here."],
        )

    if target_idx != 0:
        try:
            obj = nearby.pop(target_idx)
            nearby.insert(0, obj)
            state.setdefault("world", {})["nearby_items"] = nearby
        except Exception:
            pass

    # Snapshots for deterministic effects (before pickup applies).
    inv0 = state.get("inventory", {}) if isinstance(state.get("inventory"), dict) else {}
    bag0 = list((inv0 or {}).get("bag_contents") or []) if isinstance((inv0 or {}).get("bag_contents"), list) else []
    pocket0 = list((inv0 or {}).get("pocket_contents") or []) if isinstance((inv0 or {}).get("pocket_contents"), list) else []
    qty0 = dict((inv0 or {}).get("item_quantities") or {}) if isinstance((inv0 or {}).get("item_quantities"), dict) else {}
    pe0 = list(state.get("pending_events") or []) if isinstance(state.get("pending_events"), list) else []

    actx = {"inventory_ops": [{"op": "pickup", "item_id": target_item_id, "to": "bag", "time_cost_min": 0}]}
    apply_inventory_ops(state, actx)

    clear_active_scene(state)
    inv1 = state.get("inventory", {}) if isinstance(state.get("inventory"), dict) else {}
    bag1 = list((inv1 or {}).get("bag_contents") or []) if isinstance((inv1 or {}).get("bag_contents"), list) else []
    pocket1 = list((inv1 or {}).get("pocket_contents") or []) if isinstance((inv1 or {}).get("pocket_contents"), list) else []
    qty1 = dict((inv1 or {}).get("item_quantities") or {}) if isinstance((inv1 or {}).get("item_quantities"), dict) else {}
    pe1 = list(state.get("pending_events") or []) if isinstance(state.get("pending_events"), list) else []

    # Compute deltas.
    try:
        item_delta = int(bag1.count(target_item_id) + pocket1.count(target_item_id)) - int(bag0.count(target_item_id) + pocket0.count(target_item_id))
    except Exception:
        item_delta = 0
    try:
        ammo_delta = int(qty1.get(target_item_id, 0) or 0) - int(qty0.get(target_item_id, 0) or 0)
    except Exception:
        ammo_delta = 0

    new_events: list[dict[str, Any]] = []
    try:
        before_s = set([repr(x) for x in pe0[:120]])
        for ev in pe1[:200]:
            if isinstance(ev, dict) and repr(ev) not in before_s:
                new_events.append(ev)
    except Exception:
        new_events = []

    effects: list[dict[str, Any]] = [
        {"kind": "nearby_remove", "delivery_id": delivery_id},
        {"kind": "scene_end", "reason": "take"},
    ]
    if item_delta > 0:
        effects.append({"kind": "inventory_add", "item_id": target_item_id, "count": int(item_delta)})
    if ammo_delta > 0:
        effects.append({"kind": "ammo_add", "item_id": target_item_id, "count": int(ammo_delta)})
    for ev in new_events[:6]:
        et = str(ev.get("event_type", "") or "")
        effects.append({"kind": "event_schedule", "event_type": et})

    if (item_delta > 0) or (ammo_delta > 0):
        messages = ["You take the package."]
    else:
        messages = ["You secure the package—something feels off."]
    return _scene_return(
        ok=True,
        reason="",
        phase_before=phase_before,
        phase_after="",
        ended=True,
        next_options=[],
        effects=effects,
        messages=messages,
    )

