from __future__ import annotations

from typing import Any


def foreshadow_for_routed_event(state: dict[str, Any], ev: dict[str, Any]) -> dict[str, Any] | None:
    """Return a minimal foreshadow package for routed (scene-backed) events."""
    desc = event_to_scene_descriptor(state, ev)
    if not isinstance(desc, dict):
        return None
    et = str(ev.get("event_type", "") or "").strip()
    payload = ev.get("payload") if isinstance(ev.get("payload"), dict) else {}

    if et == "police_weapon_check":
        loc = str(payload.get("location", "") or str((state.get("player", {}) or {}).get("location", "") or "")).strip()
        wids = payload.get("weapon_ids", []) or []
        if not isinstance(wids, list):
            wids = []
        text = "Polisi menghentikanmu untuk pemeriksaan senjata. (Scene aktif: gunakan perintah SCENE)"
        if loc:
            text = f"Polisi menghentikanmu di {loc} untuk pemeriksaan senjata. (Scene aktif: gunakan perintah SCENE)"
        if wids:
            text += f" Mereka curiga kamu membawa: {', '.join([str(x) for x in wids[:3]])}" + (" ..." if len(wids) > 3 else "")
        return {"news_source": "police", "ripple_kind": "police_weapon_check", "origin_faction": "police", "origin_location": str(loc).strip().lower(), "text": text, "meta": {"weapon_ids": wids}}

    if et == "undercover_sting":
        loc = str(payload.get("location", "") or str((state.get("player", {}) or {}).get("location", "") or "")).strip().lower()
        iid = str(payload.get("bought_item_id", "") or "").strip()
        text = "Operasi sting: kamu merasa transaksi tadi dipantau. (Scene aktif: gunakan perintah SCENE)"
        if iid:
            text += f" (item={iid})"
        return {"news_source": "police", "ripple_kind": "undercover_sting", "origin_faction": "police", "origin_location": str(loc).strip().lower(), "text": text, "meta": {"bought_item_id": iid}}

    if et == "safehouse_raid":
        loc = str(payload.get("location", "") or str((state.get("player", {}) or {}).get("location", "") or "")).strip().lower()
        text = f"Police raid di safehouse {loc}. (Scene aktif: gunakan perintah SCENE)"
        return {"news_source": "police", "ripple_kind": "safehouse_raid", "origin_faction": "police", "origin_location": loc, "text": text, "meta": {"location": loc}}

    if et == "police_sweep":
        loc = str(payload.get("location", "") or str((state.get("player", {}) or {}).get("location", "") or "")).strip().lower()
        att = str(payload.get("attention", "investigated") or "investigated").strip().lower()
        text = f"Operasi polisi meningkat di {loc} (sweep). (Scene aktif: gunakan perintah SCENE)"
        return {
            "news_source": "broadcast",
            "ripple_kind": "police_sweep",
            "origin_faction": "police",
            "origin_location": loc,
            "text": text,
            "meta": {"location": loc, "attention": att},
        }

    if et == "traffic_stop":
        loc = str(payload.get("location", "") or str((state.get("player", {}) or {}).get("location", "") or "")).strip().lower()
        text = f"Traffic stop ahead in {loc}. (Scene aktif: gunakan perintah SCENE)"
        return {"news_source": "police", "ripple_kind": "traffic_stop", "origin_faction": "police", "origin_location": loc, "text": text, "meta": {"score": payload.get("score", 0)}}

    if et == "vehicle_search":
        loc = str(payload.get("location", "") or str((state.get("player", {}) or {}).get("location", "") or "")).strip().lower()
        text = f"Police vehicle search in {loc}. (Scene aktif: gunakan perintah SCENE)"
        return {"news_source": "police", "ripple_kind": "vehicle_search", "origin_faction": "police", "origin_location": loc, "text": text, "meta": {"score": payload.get("score", 0)}}

    if et == "border_control":
        loc = str(payload.get("location", "") or str((state.get("player", {}) or {}).get("location", "") or "")).strip().lower()
        dst = str(payload.get("travel_destination", "") or "").strip().lower()
        bc = int(payload.get("border_controls", 0) or 0)
        text = f"Border control check near {loc}. (Scene aktif: gunakan perintah SCENE)"
        if dst:
            text = f"Border control check en route to {dst}. (Scene aktif: gunakan perintah SCENE)"
        return {"news_source": "police", "ripple_kind": "border_control", "origin_faction": "border", "origin_location": loc, "text": text, "meta": {"border_controls": bc}}

    return None


def audit_casefile_for_event(state: dict[str, Any], ev: dict[str, Any]) -> dict[str, Any] | None:
    """Return a casefile entry for high-signal events (scene-backed or not)."""
    if not isinstance(ev, dict):
        return None
    et = str(ev.get("event_type", "") or "").strip()
    payload = ev.get("payload") if isinstance(ev.get("payload"), dict) else {}
    try:
        from engine.world.casefile import append_casefile
    except Exception:
        append_casefile = None  # type: ignore
    if not callable(append_casefile):
        return None

    # Basic context
    loc = str(payload.get("location", "") or str((state.get("player", {}) or {}).get("location", "") or "")).strip().lower()
    did = str((state.get("player", {}) or {}).get("district", "") or "").strip().lower()

    # Scene-backed encounters: rely on scene modules for detailed entries, but record trigger.
    if et in ("police_weapon_check", "undercover_sting", "safehouse_raid", "traffic_stop", "vehicle_search", "border_control"):
        st = event_to_scene_descriptor(state, ev) or {}
        scene_type = str((st or {}).get("scene_type", "") or "")
        summary = f"Triggered {et} (scene={scene_type or '-'})"
        row = {"kind": "event_trigger", "scene_type": scene_type, "event_type": et, "location": loc, "district": did, "summary": summary, "tags": [et, "scene_backed"], "meta": {"sig": (st or {}).get("sig", "")}}
        append_casefile(state, row)
        return row

    if et == "delivery_drop":
        iid = str(payload.get("item_id", "") or "").strip()
        dd = str(payload.get("drop_district", "") or "").strip().lower()
        delivery = str(payload.get("delivery", "dead_drop") or "dead_drop").strip().lower()
        summary = f"Delivery ready ({delivery}) item={iid or '-'} drop_district={dd or '-'}"
        row = {"kind": "event_trigger", "scene_type": "drop_pickup", "event_type": et, "location": loc, "district": did, "summary": summary, "tags": ["delivery", delivery], "meta": {"item_id": iid, "drop_district": dd}}
        append_casefile(state, row)
        return row

    if et == "delivery_expire":
        iid = str(payload.get("item_id", "") or "").strip()
        summary = f"Delivery expired item={iid or '-'}"
        row = {"kind": "event_trigger", "scene_type": "", "event_type": et, "location": loc, "district": did, "summary": summary, "tags": ["delivery", "expire"], "meta": {"item_id": iid}}
        append_casefile(state, row)
        return row

    if et == "paper_trail_ping":
        iid = str(payload.get("item_id", "") or "").strip()
        summary = f"Paper trail ping (item={iid or '-'})"
        row = {"kind": "event_trigger", "scene_type": "", "event_type": et, "location": loc, "district": did, "summary": summary, "tags": ["paper_trail"], "meta": {"item_id": iid}}
        append_casefile(state, row)
        return row

    if et == "npc_report":
        reporter = str(payload.get("reporter", "unknown") or "unknown")
        aff = str(payload.get("affiliation", "") or "").strip().lower()
        summary = f"NPC report filed by {reporter} (aff={aff or '-'})"
        row = {"kind": "event_trigger", "scene_type": "", "event_type": et, "location": loc, "district": did, "summary": summary, "tags": ["npc_report", aff or "unknown"], "meta": {"reporter": reporter, "affiliation": aff}}
        append_casefile(state, row)
        return row

    if et == "police_sweep":
        att = str(payload.get("attention", "investigated") or "investigated").strip().lower()
        summary = f"Police sweep started (attention={att})"
        row = {"kind": "event_trigger", "scene_type": "", "event_type": et, "location": loc, "district": did, "summary": summary, "tags": ["police_sweep", att], "meta": {"attention": att}}
        append_casefile(state, row)
        return row

    if et == "corporate_lockdown":
        summary = "Corporate lockdown restrictions applied"
        row = {"kind": "event_trigger", "scene_type": "", "event_type": et, "location": loc, "district": did, "summary": summary, "tags": ["lockdown", "corporate"], "meta": {}}
        append_casefile(state, row)
        return row

    if et == "informant_tip":
        reporter = str(payload.get("reporter", "unknown") or "unknown")
        aff = str(payload.get("affiliation", "") or "").strip().lower()
        try:
            sus = int(payload.get("suspicion", 55) or 55)
        except Exception:
            sus = 55
        summary = f"Informant tip received ({reporter}, aff={aff or '-'}, sus={sus})"
        row = {"kind": "event_trigger", "scene_type": "", "event_type": et, "location": loc, "district": did, "summary": summary, "tags": ["informant", aff or "unknown"], "meta": {"reporter": reporter, "affiliation": aff, "suspicion": int(sus)}}
        append_casefile(state, row)
        return row

    return None


def event_to_scene_descriptor(state: dict[str, Any], ev: dict[str, Any]) -> dict[str, Any] | None:
    """Convert a triggered event into a scene descriptor, or None if not scene-backed."""
    if not isinstance(ev, dict):
        return None
    et = str(ev.get("event_type", "") or "").strip()
    payload = ev.get("payload") if isinstance(ev.get("payload"), dict) else {}

    # Scene-backed encounters (v2).
    if et == "police_weapon_check":
        sig = "police_stop|" + str(payload.get("reason", "weapon_check") or "weapon_check") + "|" + ",".join(
            [str(x) for x in (payload.get("weapon_ids") or [])][:3]
        )
        return {"scene_type": "police_stop", "payload": payload, "sig": sig}
    if et == "undercover_sting":
        sig = "sting|" + str(payload.get("bought_item_id", "") or "")
        return {"scene_type": "sting_setup", "payload": payload, "sig": sig}
    if et == "safehouse_raid":
        sig = "raid|" + str(payload.get("location", "") or "")
        return {"scene_type": "raid_response", "payload": payload, "sig": sig}
    if et == "police_sweep":
        sig = "sweep|" + str(payload.get("location", "") or "")
        return {"scene_type": "checkpoint_sweep", "payload": payload, "sig": sig}
    if et == "traffic_stop":
        sig = "traffic|" + str(payload.get("location", "") or "") + "|" + str(payload.get("score", "") or "")
        return {"scene_type": "traffic_stop", "payload": payload, "sig": sig}
    if et == "vehicle_search":
        sig = "veh_search|" + str(payload.get("location", "") or "") + "|" + str(payload.get("score", "") or "")
        return {"scene_type": "vehicle_search", "payload": payload, "sig": sig}
    if et == "border_control":
        sig = "border|" + str(payload.get("location", "") or "") + "|" + str(payload.get("travel_destination", "") or "") + "|" + str(payload.get("border_controls", "") or "")
        return {"scene_type": "border_control", "payload": payload, "sig": sig}
    return None


def handle_triggered_event(state: dict[str, Any], ev: dict[str, Any]) -> dict[str, Any]:
    """Start or queue a scene for a triggered event. Returns {handled, started, queued, scene_type}."""
    desc = event_to_scene_descriptor(state, ev)
    if not isinstance(desc, dict):
        return {"handled": False}
    st = str(desc.get("scene_type", "") or "").strip().lower()
    payload = desc.get("payload") if isinstance(desc.get("payload"), dict) else {}
    sig = str(desc.get("sig", "") or "").strip()

    flags = state.get("flags", {}) or {}
    if not (isinstance(flags, dict) and bool(flags.get("scenes_enabled", True))):
        return {"handled": False, "reason": "scenes_disabled"}

    try:
        from engine.systems.scenes import enqueue_scene, has_active_scene
    except Exception:
        return {"handled": False, "reason": "scenes_import_failed"}

    if has_active_scene(state):
        enqueue_scene(state, {"scene_type": st, "payload": payload, "sig": sig})
        return {"handled": True, "queued": True, "started": False, "scene_type": st}

    # Start immediately.
    try:
        if st == "police_stop":
            from engine.systems.scenes import start_police_stop_scene

            start_police_stop_scene(state, payload=payload)
            return {"handled": True, "queued": False, "started": True, "scene_type": st}
        if st == "sting_setup":
            from engine.systems.scenes import start_sting_setup_scene

            start_sting_setup_scene(state, payload=payload)
            return {"handled": True, "queued": False, "started": True, "scene_type": st}
        if st == "raid_response":
            from engine.systems.scenes import start_raid_response_scene

            start_raid_response_scene(state, payload=payload)
            return {"handled": True, "queued": False, "started": True, "scene_type": st}
        if st == "checkpoint_sweep":
            from engine.systems.scenes import start_checkpoint_sweep_scene

            start_checkpoint_sweep_scene(state, payload=payload)
            return {"handled": True, "queued": False, "started": True, "scene_type": st}
        if st == "traffic_stop":
            from engine.systems.scenes import start_traffic_stop_scene

            start_traffic_stop_scene(state, payload=payload)
            return {"handled": True, "queued": False, "started": True, "scene_type": st}
        if st == "vehicle_search":
            from engine.systems.scenes import start_vehicle_search_scene

            start_vehicle_search_scene(state, payload=payload)
            return {"handled": True, "queued": False, "started": True, "scene_type": st}
        if st == "border_control":
            from engine.systems.scenes import start_border_control_scene

            start_border_control_scene(state, payload=payload)
            return {"handled": True, "queued": False, "started": True, "scene_type": st}
    except Exception:
        # Fallback: if start fails, queue it so it isn't lost.
        enqueue_scene(state, {"scene_type": st, "payload": payload, "sig": sig})
        return {"handled": True, "queued": True, "started": False, "scene_type": st, "reason": "start_failed"}

    return {"handled": False}

