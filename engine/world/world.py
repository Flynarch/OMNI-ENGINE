from __future__ import annotations

import hashlib
from typing import Any

from engine.core.error_taxonomy import log_swallowed_exception
from engine.core.errors import record_error
from engine.core.feed_prune import prune_world_notes_and_news_feed
from engine.npc.npc_sim import tick_npc_sim
from engine.social.police_check import maybe_schedule_weapon_check
from engine.social.ripple_queue import enqueue_ripple
from engine.systems.disguise import maybe_caught
from engine.systems.hacking import decay_hacking_heat, ensure_location_factions
from engine.systems.judicial import is_incarcerated
from engine.systems.quests import (
    create_corp_infiltration_quest,
    create_debt_repayment_quest,
    create_trace_cleanup_quest,
    generate_faction_events,
)
from engine.systems.safehouse_raid import maybe_schedule_safehouse_raid
from engine.world.atlas import (
    apply_w2_travel_gates,
    default_city_for_country,
    ensure_country_profile,
    ensure_geopolitics,
    ensure_location_profile,
    is_known_place,
    resolve_place,
    sync_daily_burn_from_city_stats,
)
from engine.world.districts import default_district_for_city, is_valid_district
from engine.world.faction_report import maybe_record_faction_daily_snapshot
from engine.world.heat import clear_local_pressure_for_city
from engine.world.location_presets import apply_location_preset_if_first_visit
from engine.world.timers_bus import push_news as _push_news
from engine.world.weather import ensure_weather


def _event_exists(events: list[dict[str, Any]], event_type: str, day: int) -> bool:
    for ev in events:
        if ev.get("event_type") == event_type and int(ev.get("due_day", -1)) >= day and not ev.get("triggered"):
            return True
    return False


def _add_event(state: dict[str, Any], *, event_type: str, title: str, due_day: int, due_time: int, payload: dict[str, Any] | None = None) -> None:
    events = state.setdefault("pending_events", [])
    if _event_exists(events, event_type, int(state.get("meta", {}).get("day", 1))):
        return
    events.append(
        {
            "event_type": event_type,
            "title": title,
            "due_day": due_day,
            "due_time": due_time,
            "triggered": False,
            "payload": payload or {},
        }
    )


def _add_ripple(
    state: dict[str, Any],
    *,
    text: str,
    surface_day: int,
    surface_time: int,
    propagation: str = "local_witness",
    visibility: str = "local",
    origin_faction: str | None = None,
    witnesses: list[str] | None = None,
) -> None:
    ripples = state.setdefault("active_ripples", [])
    if isinstance(ripples, list):
        for rp in ripples[-20:]:
            if isinstance(rp, dict) and rp.get("text") == text and not rp.get("surfaced"):
                return
    origin_loc = str(state.get("player", {}).get("location", "") or "").strip().lower()
    try:

        enqueue_ripple(
            state,
            {
                "text": text,
                "triggered_day": int(state.get("meta", {}).get("day", 1)),
                "surface_day": surface_day,
                "surface_time": surface_time,
                "surfaced": False,
                "propagation": propagation,
                "visibility": visibility,
                "origin_location": origin_loc,
                "origin_faction": origin_faction,
                "witnesses": witnesses or [],
                "surface_attempts": 0,
                "kind": "world_ripple",
                "meta": {},
            },
        )
    except Exception as _omni_sw_68:
        log_swallowed_exception('engine/world/world.py:68', _omni_sw_68)
        state.setdefault("active_ripples", []).append(
            {
                "text": text,
                "triggered_day": int(state.get("meta", {}).get("day", 1)),
                "surface_day": surface_day,
                "surface_time": surface_time,
                "surfaced": False,
                "propagation": propagation,
                "visibility": visibility,
                "origin_location": origin_loc,
                "origin_faction": origin_faction,
                "witnesses": witnesses or [],
                "surface_attempts": 0,
            }
        )


def world_tick(state: dict[str, Any], action_ctx: dict[str, Any]) -> None:
    meta = state.setdefault("meta", {})
    day = int(meta.get("day", 1))
    time_min = int(meta.get("time_min", 0))
    try:

        prune_world_notes_and_news_feed(state)
    except Exception as _omni_sw_95:
        log_swallowed_exception("engine/world/world.py:95", _omni_sw_95)
    notes = state.setdefault("world_notes", [])
    try:

        maybe_record_faction_daily_snapshot(state)
    except Exception as e:
        log_swallowed_exception('engine/world/world.py:95', e)
        try:

            record_error(state, "world.maybe_record_faction_daily_snapshot", e)
        except Exception as _omni_sw_100:
            log_swallowed_exception('engine/world/world.py:100', _omni_sw_100)
    trace_pct = int(state.get("trace", {}).get("trace_pct", 0))
    # Weather refresh (deterministic per day+location).
    try:

        cur_loc = str(state.get("player", {}).get("location", "") or "").strip().lower()
        if cur_loc:
            ensure_weather(state, cur_loc, day)
    except Exception as e:
        log_swallowed_exception('engine/world/world.py:110', e)
        try:

            record_error(state, "world.ensure_weather", e)
        except Exception as _omni_sw_115:
            log_swallowed_exception('engine/world/world.py:115', _omni_sw_115)
    # Daily cooldowns / slow systems.
    try:

        decay_hacking_heat(state)
    except Exception as e:
        log_swallowed_exception('engine/world/world.py:123', e)
        try:

            record_error(state, "world.decay_hacking_heat", e)
        except Exception as _omni_sw_128:
            log_swallowed_exception('engine/world/world.py:128', _omni_sw_128)
    # Daily housekeeping: prune expired NPC offers (role/econ).
    try:
        world = state.setdefault("world", {})
        econ = world.get("npc_economy", {}) or {}
        if isinstance(econ, dict):
            offers = econ.get("offers", {}) or {}
            if isinstance(offers, dict) and offers:
                keep: dict[str, Any] = {}
                for k, v in offers.items():
                    if not isinstance(v, dict):
                        continue
                    try:
                        exp = int(v.get("expires_day", day) or day)
                    except Exception as _omni_sw_144:
                        log_swallowed_exception('engine/world/world.py:144', _omni_sw_144)
                        exp = day
                    if exp >= day:
                        keep[str(k)] = v
                # Keep offers bounded.
                if len(keep) > 40:
                    # Deterministic prune by sorted key.
                    for kk in sorted(list(keep.keys()))[:-40]:
                        keep.pop(kk, None)
                econ["offers"] = keep
                world["npc_economy"] = econ
    except Exception as e:
        log_swallowed_exception('engine/world/world.py:155', e)
        try:

            record_error(state, "world.prune_npc_offers", e)
        except Exception as _omni_sw_160:
            log_swallowed_exception('engine/world/world.py:160', _omni_sw_160)
    # Police stop-check: if carrying illegal weapons in a high-attention context,
    # schedule a structured event for AI-driven dialog.
    try:

        maybe_schedule_weapon_check(state)
    except Exception as e:
        log_swallowed_exception('engine/world/world.py:169', e)
        try:

            record_error(state, "world.maybe_schedule_weapon_check", e)
        except Exception as _omni_sw_174:
            log_swallowed_exception('engine/world/world.py:174', _omni_sw_174)
    # Safehouse raid: contraband stashed can be raided under high attention.
    try:

        maybe_schedule_safehouse_raid(state)
    except Exception as e:
        log_swallowed_exception('engine/world/world.py:182', e)
        try:

            record_error(state, "world.maybe_schedule_safehouse_raid", e)
        except Exception as _omni_sw_187:
            log_swallowed_exception('engine/world/world.py:187', _omni_sw_187)
    # Travel destination changes scene/world objects.
    if action_ctx.get("action_type") == "travel":
        try:

            if is_incarcerated(state):
                notes.append("[Judicial] Travel blocked while serving sentence.")
                action_ctx["action_type"] = "instant"
                action_ctx.pop("travel_destination", None)
                action_ctx["instant_minutes"] = int(action_ctx.get("instant_minutes", 2) or 2)
                return
        except Exception as _omni_sw_201:
            log_swallowed_exception('engine/world/world.py:201', _omni_sw_201)
        dest = action_ctx.get("travel_destination")
        if dest:
            # Earth-only travel gate: block unknown/imaginary cities (DLC later).
            try:

                raw_dest = str(dest)
                if not is_known_place(raw_dest):
                    notes.append(f"[Travel] Unknown/unsupported location '{dest}'. (Earth-only mode)")
                    # Cancel travel so timers don't advance as travel.
                    action_ctx["action_type"] = "instant"
                    action_ctx.pop("travel_destination", None)
                    action_ctx["instant_minutes"] = int(action_ctx.get("instant_minutes", 2) or 2)
                    return
                # If user typed a COUNTRY, map it to a deterministic default CITY.
                meta2 = state.get("meta", {}) or {}
                seed2 = str(meta2.get("world_seed", "") or meta2.get("seed_pack", "") or "")
                c, kind = resolve_place(raw_dest)
                if kind == "country":
                    dc = default_city_for_country(c, seed=seed2)
                    if not dc:
                        notes.append(f"[Travel] Country '{c}' has no mapped city yet. (Earth-only mode)")
                        action_ctx["action_type"] = "instant"
                        action_ctx.pop("travel_destination", None)
                        action_ctx["instant_minutes"] = int(action_ctx.get("instant_minutes", 2) or 2)
                        return
                    notes.append(f"[Travel] '{raw_dest}' interpreted as country → default city '{dc}'.")
                    action_ctx["travel_destination"] = dc
            except Exception as _omni_sw_231:
                log_swallowed_exception('engine/world/world.py:231', _omni_sw_231)
            # W2-8: ticket / passport / wanted / city_stats pricing (skip TRAVELTO district mode).
            dest_gate = str(action_ctx.get("travel_destination", "") or "").strip().lower()
            cur_loc_gate = str((state.get("player", {}) or {}).get("location", "") or "").strip().lower()
            try:

                block_msg = apply_w2_travel_gates(state, action_ctx, cur_loc_gate, dest_gate)
                if block_msg:
                    notes.append(str(block_msg))
                    action_ctx["action_type"] = "instant"
                    action_ctx.pop("travel_destination", None)
                    action_ctx["instant_minutes"] = int(action_ctx.get("instant_minutes", 2) or 2)
                    action_ctx.pop("w2_travel_precalc", None)
                    return
            except Exception as e:
                log_swallowed_exception('engine/world/world.py:247', e)
                try:

                    record_error(state, "world.apply_w2_travel_gates", e)
                except Exception as _omni_sw_252:
                    log_swallowed_exception('engine/world/world.py:252', _omni_sw_252)
            # Persist current location scene before moving.
            cur_loc = str(state.get("player", {}).get("location", "") or "").strip().lower()
            world = state.setdefault("world", {})
            world.setdefault("locations", {})
            world.setdefault("contacts", {})
            loc_store = world.get("locations")
            if isinstance(loc_store, dict) and cur_loc:
                loc_store.setdefault(cur_loc, {})
                slot = loc_store.get(cur_loc)
                if isinstance(slot, dict):
                    slot["nearby_items"] = list(world.get("nearby_items", []) or [])
                    # Persist location-specific factions (so deltas survive travel).
                    try:
                        wf = world.get("factions", {}) or {}
                        if isinstance(wf, dict) and wf:
                            slot["factions"] = wf
                            # Keep any seed key if present.
                            if "factions_seed_key" in world and "factions_seed_key" not in slot:
                                slot["factions_seed_key"] = world.get("factions_seed_key")
                    except Exception as _omni_sw_273:
                        log_swallowed_exception('engine/world/world.py:273', _omni_sw_273)
                    local_npcs: dict[str, Any] = {}
                    for name, npc in (state.get("npcs", {}) or {}).items():
                        if not isinstance(npc, dict):
                            continue
                        # Contacts are global; do not persist them into per-location snapshots.
                        if npc.get("is_contact") is True:
                            continue
                        loc = str(npc.get("current_location", "") or "").strip().lower() or str(npc.get("home_location", "") or "").strip().lower()
                        if loc and loc == cur_loc:
                            local_npcs[str(name)] = dict(npc)
                    slot["npcs"] = local_npcs

            dest_s = str(dest).strip()
            dest_key_norm = dest_s.strip().lower()
            state.setdefault("player", {})["location"] = dest_key_norm
            # Normalize district on travel so district-scoped systems don't desync.
            try:

                p = state.setdefault("player", {})
                cur_d = str((p.get("district", "") if isinstance(p, dict) else "") or "").strip().lower()
                if not cur_d or not is_valid_district(state, dest_key_norm, cur_d):
                    p["district"] = default_district_for_city(state, dest_key_norm) or ""
            except Exception as _omni_sw_298:
                log_swallowed_exception('engine/world/world.py:298', _omni_sw_298)
            # Ensure deterministic cultural/econ background exists for this location.
            try:

                ensure_location_profile(state, dest_key_norm)
            except Exception as _omni_sw_305:
                log_swallowed_exception('engine/world/world.py:305', _omni_sw_305)
            # Preserve any previously persisted per-location factions across seed merges.
            try:
                dest_key0 = dest_s.strip().lower()
                w0 = state.get("world", {}) or {}
                ls0 = w0.get("locations", {}) or {}
                prev_slot = ls0.get(dest_key0) if isinstance(ls0, dict) else None
                prev_factions = None
                prev_fk = None
                if isinstance(prev_slot, dict):
                    pf = prev_slot.get("factions")
                    if isinstance(pf, dict) and pf:
                        prev_factions = pf
                    prev_fk = prev_slot.get("factions_seed_key")
            except Exception as _omni_sw_320:
                log_swallowed_exception('engine/world/world.py:320', _omni_sw_320)
                prev_slot = None
                prev_factions = None
                prev_fk = None
            # Location presets (applied once per location on first visit).
            try:

                applied = apply_location_preset_if_first_visit(state, dest_key_norm)
                notes.append(f"Arrived: {dest_key_norm}" + (" (preset applied)." if applied else "."))
            except Exception as _omni_sw_330:
                log_swallowed_exception('engine/world/world.py:330', _omni_sw_330)
                notes.append(f"Arrived: {dest_key_norm} (preset apply error).")
            # Re-apply persisted factions if seed merge overwrote the destination slot.
            try:
                if prev_factions is not None:
                    w1 = state.setdefault("world", {})
                    ls1 = w1.setdefault("locations", {})
                    dk = dest_s.strip().lower()
                    if isinstance(ls1, dict):
                        ls1.setdefault(dk, {})
                        if isinstance(ls1.get(dk), dict):
                            ls1[dk].setdefault("factions", prev_factions)
                            if prev_fk and "factions_seed_key" not in ls1[dk]:
                                ls1[dk]["factions_seed_key"] = prev_fk
                        w1["locations"] = ls1
            except Exception as _omni_sw_345:
                log_swallowed_exception('engine/world/world.py:345', _omni_sw_345)
            # Snapshot NPCs AFTER seed merge so seeded locals are not lost on rebuild.
            seeded_npcs: dict[str, Any] = dict(state.get("npcs", {}) or {}) if isinstance(state.get("npcs", {}), dict) else {}

            # Restore persisted destination scene if it exists.
            dest_key = dest_key_norm
            loc_store = (state.get("world", {}) or {}).get("locations", {})
            snap_npcs: dict[str, Any] = {}
            if isinstance(loc_store, dict):
                snap = loc_store.get(dest_key)
                if isinstance(snap, dict):
                    world = state.setdefault("world", {})
                    if "nearby_items" in snap:
                        world["nearby_items"] = list(snap.get("nearby_items") or [])
                    snap_npcs = snap.get("npcs") if isinstance(snap.get("npcs"), dict) else {}
                    # Restore cached profile if present (background persistence).
                    if "profile" in snap and isinstance(snap.get("profile"), dict):
                        snap_prof = snap.get("profile") or {}
                        # Keep slot.profile in sync (do not overwrite if already exists).
                        try:
                            wlocs = world.get("locations", {}) or {}
                            if isinstance(wlocs, dict):
                                wlocs.setdefault(dest_key, {})
                                if isinstance(wlocs.get(dest_key), dict):
                                    wlocs[dest_key].setdefault("profile", snap_prof)
                                    world["locations"] = wlocs
                        except Exception as _omni_sw_373:
                            log_swallowed_exception('engine/world/world.py:373', _omni_sw_373)
            # Two-layer NPC model (always rebuild on travel):
            # - local NPCs for this destination
            # - global contacts preserved across travel
            contacts = (state.get("world", {}) or {}).get("contacts", {})
            if not isinstance(contacts, dict):
                contacts = {}
                state.setdefault("world", {})["contacts"] = contacts

            new_npcs: dict[str, Any] = {}
            for k, v in contacts.items():
                if isinstance(v, dict):
                    vv = dict(v)
                    # Contacts are global; if they track a location, keep it.
                    if str(vv.get("current_location", "") or "").strip() == "":
                        # Default contacts to "remote" (empty) rather than forcibly pinning.
                        pass
                    new_npcs[str(k)] = vv

            # Include NPCs introduced by seed packs for this destination.
            locals_from_seed: dict[str, Any] = {}
            for k, v in (seeded_npcs or {}).items():
                if not isinstance(v, dict):
                    continue
                # Contacts are global; don't duplicate them in locals.
                if str(k) in new_npcs:
                    continue
                home = str(v.get("home_location", "") or "").strip().lower()
                if not home:
                    v = dict(v)
                    v["home_location"] = dest_key_norm
                    locals_from_seed[str(k)] = v
                elif home == dest_key:
                    locals_from_seed[str(k)] = dict(v)
            for k, v in locals_from_seed.items():
                vv = dict(v)
                if str(vv.get("current_location", "") or "").strip() == "":
                    vv["current_location"] = dest_key_norm
                new_npcs[str(k)] = vv

            if isinstance(snap_npcs, dict):
                for k, v in snap_npcs.items():
                    # Contacts win: never override global contact entries with local snapshots.
                    if str(k) in new_npcs:
                        continue
                    if isinstance(v, dict):
                        vv = dict(v)
                        # Ensure locals loaded into a destination are marked as currently there.
                        if str(vv.get("current_location", "") or "").strip() == "":
                            vv["current_location"] = dest_key_norm
                        new_npcs[str(k)] = vv
            state["npcs"] = new_npcs

            # W2-8: pay intercity/international ticket; fresh heat/suspicion bucket at destination; burn ~ city_stats.
            try:
                ch = int(action_ctx.pop("travel_ticket_charge", 0) or 0)
                if ch > 0:
                    econ = state.setdefault("economy", {})
                    cash0 = int(econ.get("cash", 0) or 0)
                    econ["cash"] = max(0, cash0 - ch)
                    notes.append(f"[Travel] Tiket dibeli: -${ch} (sisa cash ${int(econ.get('cash', 0) or 0)}).")
            except Exception as _omni_sw_436:
                log_swallowed_exception('engine/world/world.py:436', _omni_sw_436)
            try:
                rk = str(action_ctx.get("travel_route_kind", "") or "")
                if rk in ("intercity", "international"):

                    clear_local_pressure_for_city(state, dest_key_norm)
            except Exception as _omni_sw_444:
                log_swallowed_exception('engine/world/world.py:444', _omni_sw_444)
            try:

                sync_daily_burn_from_city_stats(state, dest_key_norm)
            except Exception as _omni_sw_450:
                log_swallowed_exception('engine/world/world.py:450', _omni_sw_450)
            action_ctx.pop("w2_travel_precalc", None)

            # After changing location, reseed faction baseline for that destination.
            try:

                ensure_location_factions(state)
            except Exception as _omni_sw_459:
                log_swallowed_exception('engine/world/world.py:459', _omni_sw_459)
    else:
        # Non-travel beats: keep faction baseline consistent with current location.
        try:

            ensure_location_factions(state)
        except Exception as _omni_sw_467:
            log_swallowed_exception('engine/world/world.py:467', _omni_sw_467)
        # Ensure profile exists for current location too (on older saves).
        try:
            cur = str(state.get("player", {}).get("location", "") or "").strip()
            if cur:

                ensure_location_profile(state, cur)
        except Exception as _omni_sw_476:
            log_swallowed_exception('engine/world/world.py:476', _omni_sw_476)
    # Minimal autonomous world movement.
    if action_ctx.get("action_type") in {"sleep", "rest", "travel"}:
        notes.append(f"Day {day}: World advanced while player was occupied.")

    # Faction-driven event generation (once per day).
    try:

        generate_faction_events(state)
    except Exception as e:
        log_swallowed_exception('engine/world/world.py:488', e)
        try:

            record_error(state, "world.generate_faction_events", e)
        except Exception as _omni_sw_493:
            log_swallowed_exception('engine/world/world.py:493', _omni_sw_493)
    # Global geopolitics tick (once per day): sanctions/conflict pressure affects world economy indirectly.
    try:

        gp = ensure_geopolitics(state)
        last = int(gp.get("last_tick_day", 0) or 0)
        if last < day:
            gp["last_tick_day"] = day
            # Ensure current location profile exists (so we have at least one country).
            cur_loc = str(state.get("player", {}).get("location", "") or "").strip()
            if cur_loc:
                prof = ensure_location_profile(state, cur_loc)
                cur_country = str((prof.get("country") if isinstance(prof, dict) else "") or "").strip().lower()
            else:
                cur_country = ""

            atlas = (state.get("world", {}) or {}).get("atlas", {}) or {}
            countries = atlas.get("countries", {}) if isinstance(atlas, dict) else {}
            keys = sorted([str(k) for k in countries.keys()]) if isinstance(countries, dict) else []
            # If atlas is small, seed a few baseline countries so relations exist.
            for base_c in ("united states", "united kingdom", "japan", "germany", "france", "india", "indonesia", "singapore"):
                ensure_country_profile(state, base_c)
            atlas = (state.get("world", {}) or {}).get("atlas", {}) or {}
            countries = atlas.get("countries", {}) if isinstance(atlas, dict) else {}
            keys = sorted([str(k) for k in countries.keys()]) if isinstance(countries, dict) else []

            if len(keys) >= 2:
                seed = str((state.get("meta", {}) or {}).get("seed_pack", "") or "")
                h = hashlib.md5(f"{seed}|{day}|geopol".encode("utf-8", errors="ignore")).hexdigest()
                a = int(h[:8], 16) % len(keys)
                b = int(h[8:16], 16) % len(keys)
                if b == a:
                    b = (b + 1) % len(keys)
                c1, c2 = keys[a], keys[b]
                if isinstance(countries.get(c1), dict) and isinstance((countries.get(c1) or {}).get("relations"), dict):
                    stance = str(((countries.get(c1) or {}).get("relations") or {}).get(c2, {}) .get("stance","neutral")).lower()
                else:
                    stance = "neutral"

                # Sanction event chance (more likely between rivals).
                roll = (int(h[16:24], 16) % 100) + 1
                do_sanction = (stance == "rival" and roll <= 35) or (stance != "ally" and roll <= 12)
                if do_sanction:
                    gp.setdefault("active_sanctions", [])
                    if isinstance(gp.get("active_sanctions"), list):
                        gp["active_sanctions"].append({"day": day, "a": c1, "b": c2, "kind": "sanction"})
                        gp["active_sanctions"] = (gp["active_sanctions"] or [])[-20:]
                    # Increase global tension index.
                    try:
                        t0 = int(gp.get("tension_idx", 0) or 0)
                    except Exception as _omni_sw_546:
                        log_swallowed_exception('engine/world/world.py:546', _omni_sw_546)
                        t0 = 0
                    gp["tension_idx"] = max(0, min(100, t0 + (8 if stance == "rival" else 4)))
                    state.setdefault("world_notes", []).append(f"[Geopol] Sanction {c1}↔{c2}")
                    # News surfaces via broadcast (player can know).
                    try:

                        _push_news(state, text=f"Sanksi dagang meningkat: {c1} ↔ {c2}.", source="broadcast")
                    except Exception as _omni_sw_555:
                        log_swallowed_exception('engine/world/world.py:555', _omni_sw_555)
                else:
                    # Slow decay when no new sanction.
                    try:
                        t0 = int(gp.get("tension_idx", 0) or 0)
                    except Exception as _omni_sw_561:
                        log_swallowed_exception('engine/world/world.py:561', _omni_sw_561)
                        t0 = 0
                    gp["tension_idx"] = max(0, t0 - 2)

            # Persist geopolitics state.
            atlas = (state.get("world", {}) or {}).get("atlas", {}) or {}
            if isinstance(atlas, dict):
                atlas["geopolitics"] = gp
                state.setdefault("world", {})["atlas"] = atlas
    except Exception as e:
        log_swallowed_exception('engine/world/world.py:570', e)
        try:

            record_error(state, "world.geopolitics_tick", e)
        except Exception as _omni_sw_575:
            log_swallowed_exception('engine/world/world.py:575', _omni_sw_575)
    # Location-specific remote events (once per day): other cities can have their own incidents.
    # This does not change sim clock; it only schedules events tagged with payload.location.
    try:
        world = state.setdefault("world", {})
        locs = world.get("locations", {}) or {}
        if isinstance(locs, dict):
            last = int(world.get("last_remote_event_day", 0) or 0)
            if last < day:
                world["last_remote_event_day"] = day
                cur_loc = str(state.get("player", {}).get("location", "") or "").strip().lower()
                keys = [str(k).strip().lower() for k in locs.keys() if str(k).strip()]
                remotes = [k for k in keys if k and k != cur_loc]
                if remotes:
                    seed = str((state.get("meta", {}) or {}).get("seed_pack", "") or "")
                    # Deterministic pick of 1 remote location/day.
                    sig = hashlib.md5(f"{seed}|{day}|remote_loc".encode("utf-8", errors="ignore")).hexdigest()
                    pick = int(sig[:8], 16) % len(remotes)
                    rloc = remotes[pick]
                    slot = locs.get(rloc) if isinstance(locs.get(rloc), dict) else {}
                    restr = (slot.get("restrictions", {}) if isinstance(slot, dict) else {}) or {}

                    # Deterministic event selection influenced by restrictions + global trace pressure.
                    sig2 = hashlib.md5(f"{seed}|{day}|{rloc}|remote_evt|{trace_pct}".encode("utf-8", errors="ignore")).hexdigest()
                    roll = (int(sig2[:8], 16) % 100) + 1

                    # If city already restricted, bias toward follow-up (lockdown/sweep persists).
                    has_ps = int(restr.get("police_sweep_until_day", 0) or 0) >= day if isinstance(restr, dict) else False
                    has_cl = int(restr.get("corporate_lockdown_until_day", 0) or 0) >= day if isinstance(restr, dict) else False

                    et: str | None = None
                    title = ""
                    payload: dict[str, Any] = {"location": rloc}
                    due = min(1439, time_min + 90)

                    if has_ps and roll <= 70:
                        et = "police_sweep"
                        title = f"Remote: police sweep escalates in {rloc}"
                        payload.update({"attention": "investigated", "police_power": 55})
                        due = min(1439, time_min + 60)
                    elif has_cl and roll <= 70:
                        et = "corporate_lockdown"
                        title = f"Remote: corporate lockdown tightens in {rloc}"
                        payload.update({"corp_power": 60, "corp_stability": 30})
                        due = min(1439, time_min + 120)
                    else:
                        # Otherwise: pick based on pressure.
                        if trace_pct >= 70 and roll <= 60:
                            et = "police_sweep"
                            title = f"Remote: checkpoint operation in {rloc}"
                            payload.update({"attention": "manhunt", "police_power": 70})
                            due = min(1439, time_min + 45)
                        elif roll <= 35:
                            et = "corporate_lockdown"
                            title = f"Remote: corporate hardening in {rloc}"
                            payload.update({"corp_power": 65, "corp_stability": 28})
                            due = min(1439, time_min + 180)
                        elif roll <= 55:
                            et = "black_market_offer"
                            title = f"Remote: black market offer emerges in {rloc}"
                            payload.update({"bm_power": 68, "bm_stability": 55})
                            due = min(1439, time_min + 220)

                    if et:
                        _add_event(state, event_type=et, title=title, due_day=day, due_time=due, payload=payload)
                        # Optional: remote-only ripple (contacts) so it can surface logically if player has contacts.
                        _add_ripple(
                            state,
                            text=f"[Remote:{rloc}] {title}",
                            surface_day=day,
                            surface_time=min(1439, time_min + 30),
                            propagation="contacts",
                            visibility="global",
                            origin_faction=("police" if et == "police_sweep" else "corporate" if et == "corporate_lockdown" else "black_market"),
                            witnesses=[],
                        )
    except Exception as _omni_sw_653:
        log_swallowed_exception('engine/world/world.py:653', _omni_sw_653)
    # NPC simulation tick (deterministic utility rules).
    try:

        tick_npc_sim(state, action_ctx)
    except Exception as e:
        log_swallowed_exception('engine/world/world.py:661', e)
        try:

            record_error(state, "world.tick_npc_sim", e)
        except Exception as _omni_sw_666:
            log_swallowed_exception('engine/world/world.py:666', _omni_sw_666)
    # Trace-pressure event generator (persistent world consequence).
    if trace_pct >= 51:
        notes.append(f"Day {day}: Investigative pressure increased (trace={trace_pct}%).")
        _add_event(
            state,
            event_type="investigation_sweep",
            title="Investigation sweep in player area",
            due_day=day,
            due_time=min(1439, time_min + 120),
            payload={"trace_snapshot": trace_pct},
        )
        # Auto quest offer: trace cleanup chain (optional).
        try:

            create_trace_cleanup_quest(state, origin_location=str(state.get("player", {}).get("location", "") or ""), trace_snapshot=trace_pct)
        except Exception as _omni_sw_685:
            log_swallowed_exception('engine/world/world.py:685', _omni_sw_685)
    if trace_pct >= 76:
        _add_event(
            state,
            event_type="manhunt_lockdown",
            title="High-priority manhunt checkpoint lockdown",
            due_day=day,
            due_time=min(1439, time_min + 30),
            payload={"trace_snapshot": trace_pct},
        )

    # NPC autonomous agenda can create ripples.
    for name, npc in (state.get("npcs", {}) or {}).items():
        if isinstance(npc, dict) and npc.get("agenda"):
            tick = int(npc.get("agenda_tick", 0)) + 1
            npc["agenda_tick"] = tick
            if tick % 3 == 0:
                _add_ripple(
                    state,
                    text=f"NPC agenda shift: {name} progressed '{npc.get('agenda')}'",
                    surface_day=day + 1,
                    surface_time=8 * 60,
                )

    # Economy pressure ripple for debt.
    debt = int(state.get("economy", {}).get("debt", 0))
    if debt > 0 and day % 2 == 0:
        _add_event(
            state,
            event_type="debt_collection_ping",
            title="Debt collector checks for player",
            due_day=day,
            due_time=min(1439, time_min + 180),
            payload={"debt": debt},
        )
        # Auto quest offer: debt repayment plan (optional).
        try:

            create_debt_repayment_quest(state)
        except Exception as _omni_sw_726:
            log_swallowed_exception('engine/world/world.py:726', _omni_sw_726)
    # Auto quest offer: corporate infiltration when lockdown active in current city.
    try:
        cur_loc = str(state.get("player", {}).get("location", "") or "").strip().lower()
        world = state.get("world", {}) or {}
        slot = ((world.get("locations", {}) or {}).get(cur_loc) if isinstance((world.get("locations", {}) or {}), dict) else None)
        restr = (slot.get("restrictions", {}) if isinstance(slot, dict) else {}) or {}
        if isinstance(restr, dict):
            try:
                cl = int(restr.get("corporate_lockdown_until_day", 0) or 0)
            except Exception as _omni_sw_738:
                log_swallowed_exception('engine/world/world.py:738', _omni_sw_738)
                cl = 0
            if cl >= day:

                create_corp_infiltration_quest(state, origin_location=cur_loc)
    except Exception as _omni_sw_744:
        log_swallowed_exception('engine/world/world.py:744', _omni_sw_744)
    # Disguise: chance to get caught under sweep if acting publicly.
    try:

        maybe_caught(state, action_ctx)
    except Exception as _omni_sw_752:
        log_swallowed_exception('engine/world/world.py:752', _omni_sw_752)