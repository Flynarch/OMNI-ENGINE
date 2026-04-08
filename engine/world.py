from __future__ import annotations

from typing import Any
import hashlib


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
        from engine.ripple_queue import enqueue_ripple

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
    except Exception:
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
    notes = state.setdefault("world_notes", [])
    trace_pct = int(state.get("trace", {}).get("trace_pct", 0))
    # Weather refresh (deterministic per day+location).
    try:
        from engine.weather import ensure_weather

        cur_loc = str(state.get("player", {}).get("location", "") or "").strip().lower()
        if cur_loc:
            ensure_weather(state, cur_loc, day)
    except Exception:
        pass

    # Daily cooldowns / slow systems.
    try:
        from engine.hacking import decay_hacking_heat

        decay_hacking_heat(state)
    except Exception as e:
        try:
            from engine.errors import record_error

            record_error(state, "world.decay_hacking_heat", e)
        except Exception:
            pass

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
                    except Exception:
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
    except Exception:
        pass

    # Travel destination changes scene/world objects.
    if action_ctx.get("action_type") == "travel":
        dest = action_ctx.get("travel_destination")
        if dest:
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
                    except Exception:
                        pass
                    local_npcs: dict[str, Any] = {}
                    for name, npc in (state.get("npcs", {}) or {}).items():
                        if not isinstance(npc, dict):
                            continue
                        loc = str(npc.get("current_location", "") or "").strip().lower() or str(npc.get("home_location", "") or "").strip().lower()
                        if loc and loc == cur_loc:
                            local_npcs[str(name)] = dict(npc)
                    slot["npcs"] = local_npcs

            dest_s = str(dest).strip()
            state.setdefault("player", {})["location"] = dest_s
            # Ensure deterministic cultural/econ background exists for this location.
            try:
                from engine.atlas import ensure_location_profile

                ensure_location_profile(state, dest_s)
            except Exception:
                pass
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
            except Exception:
                prev_slot = None
                prev_factions = None
                prev_fk = None
            try:
                from engine.seeds import apply_seed_pack

                dest_l = dest_s.lower().strip()
                primary = dest_l.split()[0] if dest_l else ""
                candidates = []
                if dest_l:
                    candidates.append(dest_l)
                    candidates.append(dest_l.replace(" ", "_").replace("-", "_"))
                if primary and primary not in candidates:
                    candidates.insert(0, primary)

                ok = False
                for pack in candidates:
                    if not pack:
                        continue
                    if apply_seed_pack(state, pack):
                        ok = True
                        notes.append(f"Arrived: {dest_s} (seed='{pack}').")
                        break
                if not ok:
                    notes.append(f"Arrived: {dest_s} (no location seed file found; using fallback).")
                    # Deterministic fallback scene content so travel anywhere feels alive.
                    primary = dest_l.split()[0] if dest_l else dest_s.lower().strip()
                    world = state.setdefault("world", {})
                    world.setdefault("nearby_items", [])
                    world["nearby_items"] = [
                        {"id": f"{primary}_id_card", "name": f"{primary}_id_card"},
                        {"id": f"{primary}_sim_card", "name": f"{primary}_sim_card"},
                    ]
                    state.setdefault("world_notes", []).append(
                        f"[Fallback Scene] {dest_s}: ritme kota berbeda terasa di udara, namun aturan permainan tetap sama."
                    )
            except Exception:
                notes.append(f"Arrived: {dest_s} (seed merge error).")
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
            except Exception:
                pass

            # Snapshot NPCs AFTER seed merge so seeded locals are not lost on rebuild.
            seeded_npcs: dict[str, Any] = dict(state.get("npcs", {}) or {}) if isinstance(state.get("npcs", {}), dict) else {}

            # Restore persisted destination scene if it exists.
            dest_key = str(dest_s).strip().lower()
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
                        except Exception:
                            pass

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
                    v["home_location"] = dest_s
                    locals_from_seed[str(k)] = v
                elif home == dest_key:
                    locals_from_seed[str(k)] = dict(v)
            for k, v in locals_from_seed.items():
                vv = dict(v)
                if str(vv.get("current_location", "") or "").strip() == "":
                    vv["current_location"] = dest_s
                new_npcs[str(k)] = vv

            if isinstance(snap_npcs, dict):
                for k, v in snap_npcs.items():
                    if isinstance(v, dict):
                        vv = dict(v)
                        # Ensure locals loaded into a destination are marked as currently there.
                        if str(vv.get("current_location", "") or "").strip() == "":
                            vv["current_location"] = dest_s
                        new_npcs[str(k)] = vv
            state["npcs"] = new_npcs

            # After changing location, reseed faction baseline for that destination.
            try:
                from engine.hacking import ensure_location_factions

                ensure_location_factions(state)
            except Exception:
                pass
    else:
        # Non-travel beats: keep faction baseline consistent with current location.
        try:
            from engine.hacking import ensure_location_factions

            ensure_location_factions(state)
        except Exception:
            pass
        # Ensure profile exists for current location too (on older saves).
        try:
            cur = str(state.get("player", {}).get("location", "") or "").strip()
            if cur:
                from engine.atlas import ensure_location_profile

                ensure_location_profile(state, cur)
        except Exception:
            pass

    # Minimal autonomous world movement.
    if action_ctx.get("action_type") in {"sleep", "rest", "travel"}:
        notes.append(f"Day {day}: World advanced while player was occupied.")

    # Faction-driven event generation (once per day).
    try:
        from engine.quests import generate_faction_events

        generate_faction_events(state)
    except Exception as e:
        try:
            from engine.errors import record_error

            record_error(state, "world.generate_faction_events", e)
        except Exception:
            pass

    # Global geopolitics tick (once per day): sanctions/conflict pressure affects world economy indirectly.
    try:
        from engine.atlas import ensure_geopolitics, ensure_location_profile, ensure_country_profile

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
                    except Exception:
                        t0 = 0
                    gp["tension_idx"] = max(0, min(100, t0 + (8 if stance == "rival" else 4)))
                    state.setdefault("world_notes", []).append(f"[Geopol] Sanction {c1}↔{c2}")
                    # News surfaces via broadcast (player can know).
                    try:
                        from engine.timers import _push_news  # internal helper used elsewhere in timers

                        _push_news(state, text=f"Sanksi dagang meningkat: {c1} ↔ {c2}.", source="broadcast")
                    except Exception:
                        pass
                else:
                    # Slow decay when no new sanction.
                    try:
                        t0 = int(gp.get("tension_idx", 0) or 0)
                    except Exception:
                        t0 = 0
                    gp["tension_idx"] = max(0, t0 - 2)

            # Persist geopolitics state.
            atlas = (state.get("world", {}) or {}).get("atlas", {}) or {}
            if isinstance(atlas, dict):
                atlas["geopolitics"] = gp
                state.setdefault("world", {})["atlas"] = atlas
    except Exception as e:
        try:
            from engine.errors import record_error

            record_error(state, "world.geopolitics_tick", e)
        except Exception:
            pass

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
    except Exception:
        pass

    # NPC simulation tick (deterministic utility rules).
    try:
        from engine.npc_sim import tick_npc_sim

        tick_npc_sim(state, action_ctx)
    except Exception:
        pass

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
            from engine.quests import create_trace_cleanup_quest

            create_trace_cleanup_quest(state, origin_location=str(state.get("player", {}).get("location", "") or ""), trace_snapshot=trace_pct)
        except Exception:
            pass
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
            from engine.quests import create_debt_repayment_quest

            create_debt_repayment_quest(state)
        except Exception:
            pass

    # Auto quest offer: corporate infiltration when lockdown active in current city.
    try:
        cur_loc = str(state.get("player", {}).get("location", "") or "").strip().lower()
        world = state.get("world", {}) or {}
        slot = ((world.get("locations", {}) or {}).get(cur_loc) if isinstance((world.get("locations", {}) or {}), dict) else None)
        restr = (slot.get("restrictions", {}) if isinstance(slot, dict) else {}) or {}
        if isinstance(restr, dict):
            try:
                cl = int(restr.get("corporate_lockdown_until_day", 0) or 0)
            except Exception:
                cl = 0
            if cl >= day:
                from engine.quests import create_corp_infiltration_quest

                create_corp_infiltration_quest(state, origin_location=cur_loc)
    except Exception:
        pass

    # Disguise: chance to get caught under sweep if acting publicly.
    try:
        from engine.disguise import maybe_caught

        maybe_caught(state, action_ctx)
    except Exception:
        pass

