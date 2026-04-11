from __future__ import annotations

from typing import Any

from engine.core.ffci import apply_custom_intent_consequences
from engine.core.modifiers import compute_roll_package, stop_sequence_check
from engine.core.trace import update_trace
from engine.npc.npc_emotions import apply_npc_emotion_after_roll
from engine.npc.npcs import update_npcs
from engine.player.bio import update_bio
from engine.player.economy import update_economy
from engine.player.inventory import update_inventory
from engine.player.inventory_ops import apply_inventory_ops
from engine.player.skills import update_skills
from engine.systems.combat import apply_combat_gates, resolve_combat_after_roll
from engine.systems.hacking import apply_hacking_after_roll
from engine.systems.intimacy import apply_intimacy_aftermath
from engine.world.timers import update_timers
from engine.world.world import world_tick


def _is_travelto_ctx(action_ctx: dict[str, Any]) -> bool:
    if not isinstance(action_ctx, dict):
        return False
    return str(action_ctx.get("travel_mode", "") or "").strip().lower() == "district"


def _roll_travelto(state: dict[str, Any], action_ctx: dict[str, Any]) -> dict[str, Any]:
    from engine.world.districts import get_current_district, get_district

    player = state.get("player", {}) or {}
    city = str(player.get("location", "") or "").strip().lower()
    target = str(action_ctx.get("travel_target_district", "") or "").strip().lower()
    if not city:
        return {"ok": False, "reason": "no_city", "message": "You are not in any city."}
    if not target:
        return {"ok": False, "reason": "missing_target", "message": "Usage: TRAVELTO <district_id>"}

    current = get_current_district(state)
    if not isinstance(current, dict):
        return {"ok": False, "reason": "not_in_district", "message": "You are not in any district."}
    to = get_district(state, city, target)
    if not isinstance(to, dict):
        return {"ok": False, "reason": "invalid_district", "message": f"Unknown district: {target}"}
    cur_id = str(current.get("id", "") or "").strip().lower()
    if cur_id and cur_id == target:
        return {"ok": False, "reason": "same_district", "message": "You are already there."}

    try:
        dist_diff = abs(int(current.get("travel_time_from_center", 0) or 0) - int(to.get("travel_time_from_center", 0) or 0))
    except Exception:
        dist_diff = 0
    travel_minutes = max(5, dist_diff * 2)

    try:
        from engine.world.weather import travel_minutes_modifier

        meta = state.get("meta", {}) or {}
        day = int(meta.get("day", 1) or 1)
        weather_slot = (state.get("world", {}).get("locations", {}) or {}).get(city) or {}
        weather = weather_slot.get("weather", {}) or {}
        weather_kind = str(weather.get("kind", "clear") or "clear")
        travel_minutes += int(travel_minutes_modifier(weather_kind) or 0)
        _ = day
    except Exception:
        pass

    return {
        "ok": True,
        "from": cur_id,
        "to": target,
        "to_name": str(to.get("name", target) or target),
        "to_desc": str(to.get("desc", "") or ""),
        "travel_minutes": int(max(1, travel_minutes)),
        "crime_risk": int(to.get("crime_risk", 3) or 3),
        "police_presence": int(to.get("police_presence", 3) or 3),
        "tech_level": str(to.get("tech_level", "medium") or "medium").lower(),
    }


def _post_travelto(state: dict[str, Any], action_ctx: dict[str, Any], travel_pkg: dict[str, Any]) -> None:
    target = str(travel_pkg.get("to", "") or "").strip().lower()
    city = str((state.get("player", {}) or {}).get("location", "") or "").strip().lower()
    if not target:
        return

    state.setdefault("player", {})["district"] = target
    mins = int(travel_pkg.get("travel_minutes", 5) or 5)
    update_timers(
        state,
        {
            "action_type": "travel",
            "domain": "evasion",
            "normalized_input": str(action_ctx.get("normalized_input", "travelto") or "travelto"),
            "travel_minutes": max(1, mins),
            "stakes": "low",
        },
    )

    encounter = None
    try:
        from engine.world.districts import get_district, get_current_district, _h32

        current = get_current_district(state) or {}
        target_row = get_district(state, city, target) or {}
        crime_risk = int(travel_pkg.get("crime_risk", 3) or 3)
        police_presence = int(travel_pkg.get("police_presence", 3) or 3)
        tech_level = str(travel_pkg.get("tech_level", "medium") or "medium").lower()
        try:
            meta0 = state.get("meta", {}) or {}
            day0 = int(meta0.get("day", 1) or 1)
            slot = ((state.get("world", {}) or {}).get("locations", {}) or {}).get(city) or {}
            ca = slot.get("cyber_alert") if isinstance(slot, dict) else None
            if isinstance(ca, dict) and int(ca.get("until_day", 0) or 0) >= day0:
                lvl = int(ca.get("level", 0) or 0)
                if lvl >= 60 and tech_level in ("high", "cutting_edge"):
                    police_presence = min(5, police_presence + 1)
        except Exception:
            pass

        meta = state.get("meta", {}) or {}
        seed = str(meta.get("seed_pack", "") or "")
        turn = int(meta.get("turn", 0) or 0)
        roll = _h32(seed, city, str(travel_pkg.get("from", "") or ""), target, turn) % 100
        if roll < crime_risk * 5:
            encounter = {"type": "crime", "risk": crime_risk}
            if str(target_row.get("id", "") or "") in ("slums", "underside", "vice", "black_market"):
                tr = state.setdefault("trace", {})
                cur = int(tr.get("trace_pct", 0) or 0)
                tr["trace_pct"] = min(100, cur + crime_risk * 2)
        elif roll > 95 - police_presence * 3:
            encounter = {"type": "police", "presence": police_presence}
            try:
                from engine.social.police_check import maybe_schedule_weapon_check

                maybe_schedule_weapon_check(state)
            except Exception:
                pass
            try:
                slot = ((state.get("world", {}) or {}).get("locations", {}) or {}).get(city) or {}
                ca = slot.get("cyber_alert") if isinstance(slot, dict) else None
                if isinstance(ca, dict) and int(ca.get("level", 0) or 0) >= 60 and tech_level in ("high", "cutting_edge"):
                    state.setdefault("world_notes", []).append("[Cyber] checkpoint: device checks intensified in this district.")
            except Exception:
                pass
        _ = current
    except Exception:
        encounter = None

    # Unify subsystem updates through centralized flow (no manual command-level update_* calls).
    world_tick(state, action_ctx)
    update_bio(state, action_ctx)
    update_skills(state, action_ctx)
    update_npcs(state, action_ctx)
    update_economy(state, action_ctx)
    update_trace(state, action_ctx)
    update_inventory(state, action_ctx)
    apply_combat_gates(state, action_ctx)

    msg = f"Traveled to {travel_pkg.get('to_name', target)} ({travel_pkg.get('to_desc', '')}) in {mins} minutes."
    action_ctx["travel_result"] = {
        "ok": True,
        "from": travel_pkg.get("from"),
        "to": target,
        "to_name": travel_pkg.get("to_name"),
        "travel_time": mins,
        "encounter": encounter,
        "crime_risk": int(travel_pkg.get("crime_risk", 3) or 3),
        "police_presence": int(travel_pkg.get("police_presence", 3) or 3),
        "message": msg,
    }


def run_pipeline(state: dict[str, Any], action_ctx: dict[str, Any]) -> dict[str, Any]:
    if bool(action_ctx.get("scene_locked")):
        return compute_roll_package(state, action_ctx)
    if _is_travelto_ctx(action_ctx):
        travel_pkg = _roll_travelto(state, action_ctx)
        if not bool(travel_pkg.get("ok")):
            action_ctx["travel_result"] = {"ok": False, "message": str(travel_pkg.get("message", "Error") or "Error")}
            return {"outcome": "N/A", "travel": travel_pkg}
        _post_travelto(state, action_ctx, travel_pkg)
        return {"outcome": "N/A", "travel": action_ctx.get("travel_result", travel_pkg)}
    _pipeline_pre_roll(state, action_ctx)
    roll_pkg = _pipeline_roll(state, action_ctx)
    _pipeline_post_roll(state, action_ctx, roll_pkg)
    return roll_pkg


def _pipeline_pre_roll(state: dict[str, Any], action_ctx: dict[str, Any]) -> None:
    """Pre-roll mutation stages. Keep ordering stable for deterministic behavior."""
    try:
        from engine.core.domain_plugins import run_pre_roll_plugin

        run_pre_roll_plugin(state, action_ctx)
    except Exception:
        pass
    try:
        from engine.systems.smartphone import apply_smartphone_pipeline

        apply_smartphone_pipeline(state, action_ctx)
    except Exception:
        pass
    world_tick(state, action_ctx)
    apply_inventory_ops(state, action_ctx)
    update_timers(state, action_ctx)
    update_bio(state, action_ctx)
    update_skills(state, action_ctx)
    update_npcs(state, action_ctx)
    update_economy(state, action_ctx)
    update_trace(state, action_ctx)
    update_inventory(state, action_ctx)
    apply_combat_gates(state, action_ctx)


def _pipeline_roll(state: dict[str, Any], action_ctx: dict[str, Any]) -> dict[str, Any]:
    return compute_roll_package(state, action_ctx)


def _pipeline_post_roll(state: dict[str, Any], action_ctx: dict[str, Any], roll_pkg: dict[str, Any]) -> None:
    # Skill progression happens after roll resolution (deterministic).
    try:
        from engine.player.skills import apply_skill_xp_after_roll

        apply_skill_xp_after_roll(state, action_ctx, roll_pkg)
    except Exception as e:
        try:
            from engine.core.errors import record_error

            record_error(state, "pipeline.post_roll.skill_xp", e)
        except Exception:
            pass

    apply_hacking_after_roll(state, action_ctx, roll_pkg)
    apply_npc_emotion_after_roll(state, action_ctx, roll_pkg)
    apply_intimacy_aftermath(state, action_ctx, roll_pkg)
    # Social diffusion: gossip about player spreads through NPC network.
    try:
        from engine.npc.npc_rumor_system import trigger_rumor_from_action

        trigger_rumor_from_action(state, action_ctx, roll_pkg)
        from engine.social.social_diffusion import apply_social_decays

        apply_social_decays(state)
    except Exception as e:
        try:
            from engine.core.errors import record_error

            record_error(state, "pipeline.post_roll.social_diffusion", e)
        except Exception:
            pass

    resolve_combat_after_roll(state, action_ctx, roll_pkg)
    apply_custom_intent_consequences(state, action_ctx, roll_pkg)
    try:
        from engine.core.domain_plugins import run_post_roll_plugin

        run_post_roll_plugin(state, action_ctx, roll_pkg)
    except Exception:
        pass
    stop_sequence_check(state, action_ctx)
