"""
Smoke + compile check. Run from repo root: python scripts/verify.py
"""

from __future__ import annotations

import compileall
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _compile() -> bool:
    ok = compileall.compile_dir(ROOT / "engine", quiet=1)
    ok = compileall.compile_dir(ROOT / "ai", quiet=1) and ok
    ok = compileall.compile_dir(ROOT / "display", quiet=1) and ok
    ok = bool(compileall.compile_file(ROOT / "main.py", quiet=1)) and ok
    ok = bool(compileall.compile_file(ROOT / "scripts" / "verify.py", quiet=1)) and ok
    return ok


def _smoke() -> None:
    from ai.parser import (
        SECTION_TAGS,
        parse_memory_hash,
        validate_ai_sections,
        validate_memory_hash_delimiters,
        validate_tag_balance,
    )
    from engine.action_intent import parse_action_intent
    from engine.combat import apply_combat_gates, resolve_combat_after_roll
    from engine.economy import update_economy
    from engine.world import world_tick
    from engine.quests import generate_faction_events
    from engine.quests import generate_faction_strikes, generate_daily_news
    from engine.modifiers import compute_roll_package
    from engine.inventory_ops import apply_inventory_ops
    from engine.timers import update_timers
    from engine.state import initialize_state
    from engine.hacking import apply_hacking_after_roll, ensure_location_factions
    from engine.npc_emotions import apply_npc_emotion_after_roll
    from engine.npc_targeting import apply_npc_targeting
    from engine.npcs import update_npcs

    st = initialize_state(
        {
            "name": "Verify",
            "age": "30",
            "location": "Test",
            "year": "2025",
            "occupation": "engineer",
            "background": "smoke",
        },
        seed_pack="minimal",
    )
    assert st["meta"].get("seed_pack") == "minimal"
    assert st["economy"].get("daily_burn", 0) > 0

    # Seed pack should merge `world` content (nearby items).
    st_seed = initialize_state(
        {
            "name": "VerifySeed",
            "location": "Test",
            "year": "2025",
        },
        seed_pack="default",
    )
    assert isinstance(st_seed.get("world", {}).get("nearby_items"), list)

    # Travel should swap location seeds (culture-ish via nearby items).
    st_travel = initialize_state({"name": "TravelVerify", "location": "Start", "year": "2025"}, seed_pack="minimal")
    ctx_travel = parse_action_intent("aku pergi ke london")
    assert ctx_travel.get("action_type") == "travel"
    assert ctx_travel.get("travel_destination") in (None, "london", "london".strip())
    world_tick(st_travel, ctx_travel)
    assert st_travel.get("player", {}).get("location") in ("london", "London")
    assert any(
        isinstance(x, dict) and str(x.get("id", "")).lower() in ("umbrella", "tube_ticket")
        for x in (st_travel.get("world", {}).get("nearby_items") or [])
    )

    # World persistence: scene content should persist per location across travel.
    st_persist = initialize_state({"name": "PersistVerify", "location": "jakarta", "year": "2025"}, seed_pack="minimal")
    st_persist.setdefault("world", {})["nearby_items"] = [{"id": "bag1", "name": "bag1"}]
    # Travel to london and change scene.
    ctx_to_london = parse_action_intent("aku pergi ke london")
    world_tick(st_persist, ctx_to_london)
    st_persist.setdefault("world", {})["nearby_items"] = [{"id": "umbrella", "name": "umbrella"}]
    # Travel back to jakarta, expect bag1 restored.
    ctx_to_jakarta = parse_action_intent("aku pergi ke jakarta")
    world_tick(st_persist, ctx_to_jakarta)
    assert any(isinstance(x, dict) and x.get("id") == "bag1" for x in (st_persist.get("world", {}).get("nearby_items") or []))

    # Contacts persistence: global contacts survive travel; locals do not.
    st_contacts = initialize_state({"name": "ContactVerify", "location": "jakarta", "year": "2025"}, seed_pack="default")
    update_npcs(st_contacts, {"domain": "social", "intent_note": "social_dialogue"})
    assert "Operator_Link" in (st_contacts.get("world", {}).get("contacts") or {})
    st_contacts.setdefault("npcs", {})["LocalGuy"] = {"name": "LocalGuy", "home_location": "jakarta", "ambient": False}
    world_tick(st_contacts, parse_action_intent("aku pergi ke london"))
    assert "Operator_Link" in (st_contacts.get("npcs") or {})
    assert "LocalGuy" not in (st_contacts.get("npcs") or {})

    # Faction quest generation should schedule events when attention/power triggers.
    st_q = initialize_state({"name": "QuestVerify", "location": "london", "year": "2025"}, seed_pack="minimal")
    st_q.setdefault("world", {}).setdefault("faction_statuses", {})["police"] = "investigated"
    st_q.setdefault("world", {}).setdefault("factions", {}).setdefault("black_market", {}).update({"power": 80, "stability": 60})
    st_q.setdefault("world", {}).setdefault("factions", {}).setdefault("corporate", {}).update({"stability": 20, "power": 70})
    generate_faction_events(st_q)
    evts = st_q.get("pending_events", []) or []
    assert any(isinstance(e, dict) and e.get("event_type") == "police_sweep" for e in evts)
    assert any(isinstance(e, dict) and e.get("event_type") == "black_market_offer" for e in evts)
    assert any(isinstance(e, dict) and e.get("event_type") == "corporate_lockdown" for e in evts)

    # Faction strikes: if attacker strong and defender weak, should schedule a strike + add news.
    st_fs = initialize_state({"name": "StrikeVerify", "location": "london", "year": "2025"}, seed_pack="minimal")
    st_fs.setdefault("world", {}).setdefault("factions", {}).setdefault("corporate", {}).update({"power": 90, "stability": 70})
    st_fs.setdefault("world", {}).setdefault("factions", {}).setdefault("black_market", {}).update({"power": 30, "stability": 20})
    st_fs.setdefault("meta", {}).update({"day": 2, "time_min": 9 * 60})
    generate_faction_strikes(st_fs, force=True)
    assert any(isinstance(e, dict) and e.get("event_type") == "faction_strike" for e in (st_fs.get("pending_events") or []))
    assert isinstance(st_fs.get("world", {}).get("news_feed"), list)
    assert len(st_fs.get("world", {}).get("news_feed") or []) >= 1

    # Daily news should add at most 2 headlines/day.
    st_news = initialize_state({"name": "NewsVerify", "location": "london", "year": "2025"}, seed_pack="minimal")
    st_news.setdefault("meta", {}).update({"day": 3, "time_min": 8 * 60})
    st_news.setdefault("world", {}).setdefault("faction_statuses", {})["police"] = "manhunt"
    st_news.setdefault("world", {}).setdefault("factions", {}).setdefault("corporate", {})["stability"] = 20
    generate_daily_news(st_news)
    feed = st_news.get("world", {}).get("news_feed") or []
    todays = [x for x in feed if isinstance(x, dict) and int(x.get("day", -1)) == 3]
    assert len(todays) <= 2

    # Hacking should shift factions + economy in a deterministic way.
    st_hack = initialize_state(
        {"name": "HackVerify", "location": "london", "year": "2025"},
        seed_pack="minimal",
    )
    econ_before = dict(st_hack.get("economy", {}) or {})
    ensure_location_factions(st_hack)
    factions_before = (st_hack.get("world", {}) or {}).get("factions", {}) or {}
    corp_before = factions_before.get("corporate", {}).get("stability", 50)
    bm_power_before = factions_before.get("black_market", {}).get("power", 50)

    action_ctx_hack = {
        "domain": "hacking",
        "normalized_input": "aku hack perusahaan usa",
        "action_type": "instant",
    }
    roll_pkg_success = {"outcome": "Success", "roll": 40, "net_threshold": 50, "mods": [], "net_threshold_locked": True}
    apply_hacking_after_roll(st_hack, action_ctx_hack, roll_pkg_success)
    assert int(st_hack["economy"].get("cash", 0) or 0) >= int(econ_before.get("cash", 0) or 0) + 180
    assert st_hack.get("world", {}).get("factions", {}).get("corporate", {}).get("stability") <= corp_before
    assert st_hack.get("world", {}).get("factions", {}).get("black_market", {}).get("power") >= bm_power_before
    # Hacking should create a structured ripple (normal => contacts).
    ar = st_hack.get("active_ripples", []) or []
    assert any(isinstance(r, dict) and str(r.get("text", "")).startswith("[Hack]") and r.get("propagation") == "contacts" for r in ar)
    # Heat should be tracked per target (loc|target).
    hh = st_hack.get("world", {}).get("hacking_heat") or {}
    assert isinstance(hh, dict) and any("corporate" in str(k) for k in hh.keys())

    # Quiet stealth hack should mostly stay local (police attention <= aware).
    st_hack_quiet = initialize_state(
        {"name": "HackQuietVerify", "location": "london", "year": "2025"},
        seed_pack="minimal",
    )
    st_hack_quiet.setdefault("trace", {})["trace_pct"] = 0
    action_ctx_hack_quiet = {
        "domain": "hacking",
        "normalized_input": "aku hack perusahaan usa",
        "action_type": "instant",
        "visibility": "low",
    }
    roll_pkg_success2 = {"outcome": "Success", "roll": 40, "net_threshold": 50, "mods": [], "net_threshold_locked": True}
    apply_hacking_after_roll(st_hack_quiet, action_ctx_hack_quiet, roll_pkg_success2)
    assert st_hack_quiet.get("world", {}).get("faction_statuses", {}).get("police") in ("idle", "aware")
    arq = st_hack_quiet.get("active_ripples", []) or []
    assert any(isinstance(r, dict) and str(r.get("text", "")).startswith("[Hack]") and r.get("propagation") == "local_witness" for r in arq)

    # Critical hack should force investigated attention quickly.
    st_hack_critical = initialize_state(
        {"name": "HackCriticalVerify", "location": "london", "year": "2025"},
        seed_pack="minimal",
    )
    st_hack_critical.setdefault("trace", {})["trace_pct"] = 0
    action_ctx_hack_critical = {
        "domain": "hacking",
        "normalized_input": "aku hack server pusat data penting perusahaan",
        "action_type": "instant",
        "visibility": "public",
    }
    apply_hacking_after_roll(st_hack_critical, action_ctx_hack_critical, roll_pkg_success2)
    assert st_hack_critical.get("world", {}).get("faction_statuses", {}).get("police") in ("investigated", "manhunt")
    arc = st_hack_critical.get("active_ripples", []) or []
    assert any(isinstance(r, dict) and str(r.get("text", "")).startswith("[Hack]") and r.get("propagation") == "broadcast" for r in arc)

    # Partial success: near-miss should still grant reduced cash (vs full failure).
    st_p = initialize_state({"name": "PartialHack", "location": "london", "year": "2025"}, seed_pack="minimal")
    st_p.setdefault("economy", {})["cash"] = 0
    ctx_p = {"domain": "hacking", "normalized_input": "aku hack perusahaan", "action_type": "instant", "visibility": "public"}
    rp_partial = {"outcome": "Failure", "roll": 56, "net_threshold": 55, "mods": [], "net_threshold_locked": True}
    apply_hacking_after_roll(st_p, ctx_p, rp_partial)
    assert int(st_p.get("economy", {}).get("cash", 0) or 0) > 0

    # Cover tracks should reduce trace on success.
    st_ct = initialize_state({"name": "CoverTracks", "location": "london", "year": "2025"}, seed_pack="minimal")
    st_ct.setdefault("trace", {})["trace_pct"] = 60
    ctx_ct = {"domain": "hacking", "normalized_input": "hapus jejak dan hapus log", "action_type": "instant", "visibility": "low"}
    rp_ct = {"outcome": "Success", "roll": 20, "net_threshold": 55, "mods": [], "net_threshold_locked": True}
    apply_hacking_after_roll(st_ct, ctx_ct, rp_ct)
    assert int(st_ct.get("trace", {}).get("trace_pct", 0) or 0) < 60

    # Heat decay: should cool down daily via world_tick.
    st_heat = initialize_state({"name": "HeatVerify", "location": "london", "year": "2025"}, seed_pack="minimal")
    st_heat.setdefault("meta", {}).update({"day": 1, "time_min": 8 * 60})
    st_heat.setdefault("inventory", {}).setdefault("bag_contents", []).append("vpn_rig")
    ctx_h = {"domain": "hacking", "normalized_input": "aku hack perusahaan", "action_type": "instant", "visibility": "public"}
    rp_ok = {"outcome": "Success", "roll": 40, "net_threshold": 50, "mods": [], "net_threshold_locked": True}
    apply_hacking_after_roll(st_heat, ctx_h, rp_ok)
    hh2 = st_heat.get("world", {}).get("hacking_heat") or {}
    key = next(iter(hh2.keys()))
    heat1 = int(hh2[key].get("heat", 0) or 0)
    # Next day decay.
    st_heat["meta"]["day"] = 2
    from engine.world import world_tick as _wt
    _wt(st_heat, {"action_type": "instant"})
    heat2 = int((st_heat.get("world", {}).get("hacking_heat") or {}).get(key, {}).get("heat", 0) or 0)
    assert heat2 <= heat1

    ctx = parse_action_intent("tembak target")
    apply_combat_gates(st, ctx)
    assert ctx.get("combat_blocked") in (None, "no_weapon", "out_of_ammo", "broken")

    # Combat should raise trace and therefore police attention tier.
    st_combat = initialize_state({"name": "CombatVerify", "location": "london", "year": "2025"}, seed_pack="minimal")
    st_combat.setdefault("trace", {})["trace_pct"] = 45
    st_combat.setdefault("inventory", {})["r_hand"] = "-"
    st_combat.setdefault("inventory", {}).setdefault("weapons", {}).setdefault("gun1", {
        "name": "Gun-1",
        "kind": "firearm",
        "ammo": 3,
        "condition_tier": 2,
    })
    st_combat["inventory"]["active_weapon_id"] = "gun1"
    st_combat.setdefault("inventory", {})["pocket_contents"] = []
    st_combat.setdefault("inventory", {})["bag_contents"] = []

    action_ctx_combat = {
        "domain": "combat",
        "action_type": "combat",
        "combat_style": "ranged",
        "visibility": "public",
        "normalized_input": "aku menembak",
        "combat_blocked": None,
        "uncertain": True,
        "has_stakes": True,
        "intent_note": "attack",
    }
    roll_pkg_fake = {"outcome": "Success", "roll": 20, "net_threshold": 50, "mods": [], "net_threshold_locked": True}
    resolve_combat_after_roll(st_combat, action_ctx_combat, roll_pkg_fake)
    assert st_combat.get("trace", {}).get("trace_pct", 0) > 45
    # trace 45 + success delta (public) should push to investigated tier (>=51).
    assert st_combat.get("world", {}).get("faction_statuses", {}).get("police") in ("investigated", "manhunt")

    # Combat faction impact: attacking police-affiliated NPC should reduce police stability.
    st_cf = initialize_state({"name": "CombatFaction", "location": "london", "year": "2025"}, seed_pack="minimal")
    st_cf.setdefault("inventory", {}).setdefault("weapons", {})["gun1"] = {"name": "Gun-1", "kind": "firearm", "ammo": 3, "condition_tier": 2}
    st_cf["inventory"]["active_weapon_id"] = "gun1"
    st_cf.setdefault("npcs", {})["Officer_X"] = {"name": "Officer_X", "affiliation": "police", "ambient": False, "fear": 10}
    before_pol = int(st_cf.get("world", {}).get("factions", {}).get("police", {}).get("stability", 50) or 50)
    action_ctx_cf = {
        "domain": "combat",
        "action_type": "combat",
        "combat_style": "ranged",
        "visibility": "public",
        "normalized_input": "aku tembak polisi itu",
        "targets": ["Officer_X"],
        "uncertain": True,
        "has_stakes": True,
    }
    roll_pkg_cf = {"outcome": "Success", "roll": 20, "net_threshold": 50, "mods": [], "net_threshold_locked": True}
    resolve_combat_after_roll(st_cf, action_ctx_cf, roll_pkg_cf)
    after_pol = int(st_cf.get("world", {}).get("factions", {}).get("police", {}).get("stability", 50) or 50)
    assert after_pol < before_pol

    scan = parse_action_intent("coba mencari orang sekitar, cewe terutama")
    assert scan["domain"] == "social" and scan.get("intent_note") == "social_scan_crowd"

    q = parse_action_intent("tahun berapa ini?")
    assert q.get("intent_note") == "social_inquiry"
    assert q.get("social_mode") == "non_conflict"
    talk = parse_action_intent("aku mau bicara dengan orang sekitar")
    assert talk.get("intent_note") == "social_dialogue"
    assert talk.get("social_mode") == "non_conflict"
    rp = compute_roll_package(st, talk)
    assert rp.get("roll") is None and "No Roll" in str(rp.get("outcome", ""))

    # Heuristic combat detect: "menembak" should be combat+ranged (even if LLM is off).
    shoot = parse_action_intent("aku menembak orang bersenjata di depan")
    assert shoot.get("domain") == "combat"
    assert shoot.get("action_type") == "combat"
    assert shoot.get("combat_style") == "ranged"

    # Social conflict should roll and incorporate social_stats (non-zero)
    st2 = initialize_state(
        {"name": "Verify2", "occupation": "operator", "background": "smoke2", "location": "Test", "year": "2025"},
        seed_pack="minimal",
    )
    st2.setdefault("player", {}).setdefault("social_stats", {}).update({"looks": 10, "outfit": 10, "hygiene": 5, "speaking": 5})
    conflict = parse_action_intent("aku memaksa orang itu untuk ngomong sekarang")
    assert conflict.get("domain") == "social" and conflict.get("social_mode") == "conflict"
    rp2 = compute_roll_package(st2, conflict)
    assert rp2.get("roll") is not None
    assert any(k == "Social stats" for k, _ in (rp2.get("mods") or []))

    # NPC conflict should be able to betray to police and raise trace.
    st_npc = initialize_state({"name": "NpcVerify", "location": "london", "year": "2025"}, seed_pack="minimal")
    npc_name = "Orang di trotoar"
    st_npc.setdefault("npcs", {})[npc_name] = {
        "name": npc_name,
        "ambient": True,
        "affiliation": "civilian",
        "trust": 20,
        "fear": 80,
        "joy": 0,
        "anger": 90,
        "surprise": 0,
        "sadness": 0,
        "disgust": 0,
        "anticipation": 0,
        "opportunism": 90,
        "loyalty": 10,
        "mood": "calm",
        "disposition_score": 40,
        "disposition_label": "Cold",
    }
    st_npc.setdefault("world", {}).setdefault("faction_statuses", {})["police"] = "manhunt"
    st_npc.setdefault("trace", {})["trace_pct"] = 0
    action_ctx_npc = {
        "domain": "social",
        "social_mode": "conflict",
        "intent_note": "social_conflict",
        "action_type": "talk",
        "targets": [npc_name],
        "visibility": "public",
        "normalized_input": "aku memaksa orang itu untuk ngomong sekarang",
    }
    roll_pkg_npc = {"outcome": "Failure", "roll": 80, "net_threshold": 50, "mods": [], "net_threshold_locked": True}
    apply_npc_emotion_after_roll(st_npc, action_ctx_npc, roll_pkg_npc)
    assert int(st_npc.get("trace", {}).get("trace_pct", 0) or 0) > 0

    # Emotion decay: low severity fades faster than high severity.
    st_decay = initialize_state({"name": "DecayVerify", "location": "london", "year": "2025"}, seed_pack="minimal")
    st_decay.setdefault("meta", {})["turn"] = 1
    st_decay.setdefault("npcs", {})["LowSev"] = {
        "name": "LowSev",
        "fear": 60,
        "anger": 40,
        "trust": 50,
        "joy": 0,
        "surprise": 0,
        "sadness": 0,
        "disgust": 0,
        "anticipation": 0,
        "mood": "angry",
        "emotion_state": {
            "fear": {"severity": 10, "last_turn": 0, "last_kind": "test"},
            "anger": {"severity": 10, "last_turn": 0, "last_kind": "test"},
            "trust": {"severity": 0, "last_turn": 0, "last_kind": "none"},
            "joy": {"severity": 0, "last_turn": 0, "last_kind": "none"},
            "surprise": {"severity": 0, "last_turn": 0, "last_kind": "none"},
            "sadness": {"severity": 0, "last_turn": 0, "last_kind": "none"},
            "disgust": {"severity": 0, "last_turn": 0, "last_kind": "none"},
            "anticipation": {"severity": 0, "last_turn": 0, "last_kind": "none"},
        },
    }
    st_decay.setdefault("npcs", {})["HighSev"] = {
        "name": "HighSev",
        "fear": 60,
        "anger": 40,
        "trust": 50,
        "joy": 0,
        "surprise": 0,
        "sadness": 0,
        "disgust": 0,
        "anticipation": 0,
        "mood": "angry",
        "emotion_state": {
            "fear": {"severity": 95, "last_turn": 0, "last_kind": "test"},
            "anger": {"severity": 95, "last_turn": 0, "last_kind": "test"},
            "trust": {"severity": 0, "last_turn": 0, "last_kind": "none"},
            "joy": {"severity": 0, "last_turn": 0, "last_kind": "none"},
            "surprise": {"severity": 0, "last_turn": 0, "last_kind": "none"},
            "sadness": {"severity": 0, "last_turn": 0, "last_kind": "none"},
            "disgust": {"severity": 0, "last_turn": 0, "last_kind": "none"},
            "anticipation": {"severity": 0, "last_turn": 0, "last_kind": "none"},
        },
    }
    # Advance turns and decay via update_npcs.
    for t in range(2, 12):
        st_decay["meta"]["turn"] = t
        update_npcs(st_decay, {"domain": "social", "intent_note": "social_inquiry"})
    low_fear = int(st_decay["npcs"]["LowSev"].get("fear", 0) or 0)
    high_fear = int(st_decay["npcs"]["HighSev"].get("fear", 0) or 0)
    assert low_fear < high_fear

    # Emotion triggers (pemancing): bad hygiene should raise disgust and lower trust on social beats.
    st_trig = initialize_state({"name": "TriggerVerify", "location": "london", "year": "2025"}, seed_pack="minimal")
    st_trig.setdefault("meta", {})["turn"] = 1
    st_trig.setdefault("bio", {})["hygiene_tax_active"] = True
    st_trig.setdefault("player", {}).setdefault("social_stats", {}).update({"hygiene": -5, "outfit": 0, "speaking": 0, "looks": 0})
    st_trig.setdefault("npcs", {})["NPC_A"] = {"name": "NPC_A", "ambient": False, "trust": 50, "fear": 10}
    before_disgust = int(st_trig["npcs"]["NPC_A"].get("disgust", 0) or 0)
    before_trust = int(st_trig["npcs"]["NPC_A"].get("trust", 50) or 50)
    apply_npc_emotion_after_roll(
        st_trig,
        {"domain": "social", "social_mode": "non_conflict", "intent_note": "social_dialogue", "targets": ["NPC_A"], "normalized_input": "aku ngobrol biasa"},
        {"outcome": "No Roll (Social Non-Conflict)", "roll": None, "net_threshold": None, "mods": [], "net_threshold_locked": True},
    )
    after_disgust = int(st_trig["npcs"]["NPC_A"].get("disgust", 0) or 0)
    after_trust = int(st_trig["npcs"]["NPC_A"].get("trust", 50) or 50)
    assert after_disgust > before_disgust
    assert after_trust < before_trust
    assert st_npc.get("npcs", {}).get(npc_name, {}).get("mood") == "betrayed"
    assert any(
        "[NPC]" in str(n) and "mengkhianati rumor" in str(n)
        for n in (st_npc.get("world_notes", []) or [])
    )

    # NPC targeting: pronoun "orang itu" should map to meta.npc_focus.
    st_tgt = initialize_state({"name": "TgtVerify", "location": "Test", "year": "2025"}, seed_pack="minimal")
    st_tgt.setdefault("npcs", {})["A"] = {"name": "A", "affiliation": "civilian", "ambient": False, "fear": 10}
    st_tgt.setdefault("npcs", {})["B"] = {"name": "B", "affiliation": "police", "ambient": False, "fear": 20}
    st_tgt.setdefault("meta", {})["npc_focus"] = "B"
    ctx_tgt = {"domain": "social", "action_type": "talk", "social_mode": "conflict", "normalized_input": "aku memaksa orang itu"}
    apply_npc_targeting(st_tgt, ctx_tgt, "aku memaksa orang itu")
    assert ctx_tgt.get("targets") == ["B"]

    # Ripple propagation gate: local ripple should not surface after travel.
    st_rp = initialize_state({"name": "RippleVerify", "location": "jakarta", "year": "2025"}, seed_pack="minimal")
    st_rp.setdefault("meta", {}).update({"day": 1, "time_min": 8 * 60})
    st_rp.setdefault("active_ripples", []).append(
        {
            "text": "Local rumor in Jakarta",
            "triggered_day": 1,
            "surface_day": 1,
            "surface_time": 8 * 60,
            "surfaced": False,
            "propagation": "local_witness",
            "origin_location": "jakarta",
            "surface_attempts": 0,
        }
    )
    st_rp.setdefault("player", {})["location"] = "london"
    update_timers(st_rp, {"action_type": "instant", "instant_minutes": 0})
    assert not st_rp.get("surfacing_ripples_this_turn")
    # Global/broadcast ripple should surface anywhere.
    st_rp["active_ripples"].append(
        {
            "text": "Broadcast news",
            "triggered_day": 1,
            "surface_day": 1,
            "surface_time": 8 * 60,
            "surfaced": False,
            "propagation": "broadcast",
            "origin_location": "jakarta",
            "surface_attempts": 0,
        }
    )
    update_timers(st_rp, {"action_type": "instant", "instant_minutes": 0})
    assert any("Broadcast news" in str(rp.get("text", "")) for rp in (st_rp.get("surfacing_ripples_this_turn") or []))

    # Ripple effects targeting: local ripple with witnesses should affect only those NPCs.
    st_rpe = initialize_state({"name": "RippleEffects", "location": "jakarta", "year": "2025"}, seed_pack="minimal")
    st_rpe.setdefault("meta", {}).update({"day": 1, "time_min": 8 * 60, "turn": 10})
    st_rpe.setdefault("npcs", {})["W1"] = {"name": "W1", "home_location": "jakarta", "anger": 0, "trust": 50}
    st_rpe.setdefault("npcs", {})["N2"] = {"name": "N2", "home_location": "london", "anger": 0, "trust": 50}
    st_rpe.setdefault("active_ripples", []).append(
        {
            "text": "Witnessed incident",
            "triggered_day": 1,
            "surface_day": 1,
            "surface_time": 8 * 60,
            "surfaced": False,
            "propagation": "local_witness",
            "origin_location": "jakarta",
            "witnesses": ["W1"],
            "impact": {"npc_emotions": {"anger": 15}, "severity": 60},
            "surface_attempts": 0,
        }
    )
    update_timers(st_rpe, {"action_type": "instant", "instant_minutes": 0})
    assert int(st_rpe["npcs"]["W1"].get("anger", 0) or 0) >= 15
    assert int(st_rpe["npcs"]["N2"].get("anger", 0) or 0) == 0

    # Ripple targeting should use current_location (fallback home_location).
    st_loc = initialize_state({"name": "RippleLoc", "location": "london", "year": "2025"}, seed_pack="minimal")
    st_loc.setdefault("meta", {}).update({"day": 1, "time_min": 8 * 60, "turn": 1})
    st_loc.setdefault("npcs", {})["Mover"] = {"name": "Mover", "home_location": "jakarta", "current_location": "london", "anger": 0, "trust": 50}
    st_loc.setdefault("active_ripples", []).append(
        {
            "text": "Local incident London",
            "triggered_day": 1,
            "surface_day": 1,
            "surface_time": 8 * 60,
            "surfaced": False,
            "propagation": "local_witness",
            "origin_location": "london",
            "impact": {"npc_emotions": {"anger": 10}, "severity": 40},
            "surface_attempts": 0,
        }
    )
    update_timers(st_loc, {"action_type": "instant", "instant_minutes": 0})
    assert int(st_loc["npcs"]["Mover"].get("anger", 0) or 0) >= 10

    # Timer cap: process max 3 due items per turn (events+ripples), defer overflow.
    st_cap = initialize_state({"name": "CapVerify", "location": "london", "year": "2025"}, seed_pack="minimal")
    st_cap.setdefault("meta", {}).update({"day": 1, "time_min": 8 * 60})
    st_cap["pending_events"] = []
    for i in range(4):
        st_cap["pending_events"].append(
            {"event_type": f"e{i}", "title": f"E{i}", "due_day": 1, "due_time": 8 * 60, "triggered": False, "payload": {}}
        )
    st_cap["active_ripples"] = []
    for i in range(2):
        st_cap["active_ripples"].append(
            {
                "text": f"R{i}",
                "triggered_day": 1,
                "surface_day": 1,
                "surface_time": 8 * 60,
                "surfaced": False,
                "propagation": "broadcast",
                "origin_location": "london",
                "surface_attempts": 0,
            }
        )
    update_timers(st_cap, {"action_type": "instant", "instant_minutes": 0})
    assert (len(st_cap.get("triggered_events_this_turn") or []) + len(st_cap.get("surfacing_ripples_this_turn") or [])) <= 3
    update_timers(st_cap, {"action_type": "instant", "instant_minutes": 0})
    assert len(st_cap.get("resolved_events") or []) + len(st_cap.get("resolved_ripples") or []) >= 4

    # Event resolver: police_sweep/corporate_lockdown/black_market_offer should create real consequences.
    from engine.modifiers import compute_roll_package

    st_ev = initialize_state({"name": "EventResolve", "location": "london", "year": "2025"}, seed_pack="minimal")
    st_ev.setdefault("meta", {}).update({"day": 1, "time_min": 8 * 60})
    st_ev.setdefault("world", {}).setdefault("locations", {})["london"] = {"restrictions": {}, "market": {}}
    st_ev["pending_events"] = [
        {"event_type": "police_sweep", "title": "Sweep", "due_day": 1, "due_time": 8 * 60, "triggered": False, "payload": {"location": "london", "attention": "investigated", "police_power": 70}},
        {"event_type": "corporate_lockdown", "title": "Lockdown", "due_day": 1, "due_time": 8 * 60, "triggered": False, "payload": {"location": "london", "corp_power": 70, "corp_stability": 25}},
        {"event_type": "black_market_offer", "title": "Offer", "due_day": 1, "due_time": 8 * 60, "triggered": False, "payload": {"location": "london", "bm_power": 70, "bm_stability": 60}},
    ]
    update_timers(st_ev, {"action_type": "instant", "instant_minutes": 0})
    r = ((st_ev.get("world", {}) or {}).get("locations", {}) or {}).get("london", {}).get("restrictions", {}) or {}
    assert int(r.get("police_sweep_until_day", 0) or 0) >= 1
    assert int(r.get("corporate_lockdown_until_day", 0) or 0) >= 1
    qs = (st_ev.get("quests", {}) or {}).get("active") or []
    assert isinstance(qs, list) and len(qs) >= 1
    # Lockdown should make corporate hacking harder via modifiers.
    pkg = compute_roll_package(st_ev, {"domain": "hacking", "trained": True, "normalized_input": "hack corporate server"})
    assert any("lockdown" in str(k).lower() for k, _v in (pkg.get("mods") or []))

    # QUEST command state shape + branching: spotted requires cover tracks; overdue reduces reward.
    st_q = initialize_state({"name": "QuestVerify", "location": "london", "year": "2025"}, seed_pack="minimal")
    st_q.setdefault("meta", {}).update({"day": 1, "time_min": 8 * 60})
    st_q.setdefault("world", {}).setdefault("locations", {})["london"] = {"restrictions": {"police_sweep_until_day": 2}, "market": {"electronics": {"price_idx": 100, "scarcity": 0}, "medical": {"price_idx": 100, "scarcity": 0}, "weapons": {"price_idx": 100, "scarcity": 0}, "food": {"price_idx": 100, "scarcity": 0}, "transport": {"price_idx": 100, "scarcity": 0}}}
    st_q.setdefault("world", {}).setdefault("locations", {})["jakarta"] = {"restrictions": {}, "market": {"electronics": {"price_idx": 100, "scarcity": 0}, "medical": {"price_idx": 100, "scarcity": 0}, "weapons": {"price_idx": 100, "scarcity": 0}, "food": {"price_idx": 100, "scarcity": 0}, "transport": {"price_idx": 100, "scarcity": 0}}}
    # Trigger BM offer -> quest created.
    st_q["pending_events"] = [
        {"event_type": "black_market_offer", "title": "Offer", "due_day": 1, "due_time": 8 * 60, "triggered": False, "payload": {"location": "london", "bm_power": 70, "bm_stability": 60}},
    ]
    update_timers(st_q, {"action_type": "instant", "instant_minutes": 0})
    qa = (st_q.get("quests", {}) or {}).get("active") or []
    assert isinstance(qa, list) and qa
    q0 = qa[0]
    pkgid = (q0.get("data") or {}).get("package_id")
    droploc = str(((q0.get("data") or {}).get("drop_loc") or "")).strip().lower()
    assert pkgid
    # Fast-forward quest to delivery step + put package in bag.
    q0["step"] = 2
    st_q.setdefault("inventory", {}).setdefault("bag_contents", []).append(pkgid)
    # Travel during sweep should mark spotted.
    update_timers(st_q, {"action_type": "travel", "travel_minutes": 30, "travel_destination": droploc, "domain": "evasion", "normalized_input": "travel"})
    assert bool((q0.get("data") or {}).get("spotted", False)) is True
    # Attempt delivery while spotted should not complete.
    st_q.setdefault("player", {})["location"] = droploc
    update_timers(st_q, {"action_type": "instant", "instant_minutes": 0, "domain": "evasion", "normalized_input": "antar paket"})
    assert q0.get("status") in ("active", "overdue")
    # Cover tracks clears spotted.
    update_timers(st_q, {"action_type": "instant", "instant_minutes": 0, "domain": "hacking", "normalized_input": "hapus jejak cover tracks"})
    assert bool((q0.get("data") or {}).get("spotted", False)) is False

    # Local market should not leak: lockdown only affects city's local market, not global.
    st_m = initialize_state({"name": "MarketLocal", "location": "london", "year": "2025"}, seed_pack="minimal")
    st_m.setdefault("meta", {}).update({"day": 1, "time_min": 8 * 60})
    st_m.setdefault("world", {}).setdefault("locations", {})["london"] = {"restrictions": {"corporate_lockdown_until_day": 2}, "market": {"electronics": {"price_idx": 100, "scarcity": 0}, "medical": {"price_idx": 100, "scarcity": 0}, "weapons": {"price_idx": 100, "scarcity": 0}, "food": {"price_idx": 100, "scarcity": 0}, "transport": {"price_idx": 100, "scarcity": 0}}}
    st_m.setdefault("world", {}).setdefault("locations", {})["jakarta"] = {"restrictions": {}, "market": {"electronics": {"price_idx": 100, "scarcity": 0}, "medical": {"price_idx": 100, "scarcity": 0}, "weapons": {"price_idx": 100, "scarcity": 0}, "food": {"price_idx": 100, "scarcity": 0}, "transport": {"price_idx": 100, "scarcity": 0}}}
    from engine.market import update_market

    update_market(st_m)
    g_market = (st_m.get("economy", {}) or {}).get("market", {}) or {}
    g_e = int((g_market.get("electronics", {}) or {}).get("price_idx", 100) or 100) if isinstance(g_market, dict) else 100
    locs = ((st_m.get("world", {}) or {}).get("locations", {}) or {})
    lon = (locs.get("london", {}) or {}) if isinstance(locs, dict) else {}
    jak = (locs.get("jakarta", {}) or {}) if isinstance(locs, dict) else {}
    l_e = int((((lon.get("market", {}) or {}).get("electronics", {}) or {}).get("price_idx", 100) or 100))
    j_e = int((((jak.get("market", {}) or {}).get("electronics", {}) or {}).get("price_idx", 100) or 100))
    assert l_e >= j_e
    assert isinstance(g_e, int)

    # Remote location events: world_tick can schedule a remote event tagged with payload.location.
    from engine.world import world_tick

    st_rem = initialize_state({"name": "RemoteEvt", "location": "london", "year": "2025"}, seed_pack="minimal")
    st_rem.setdefault("meta", {}).update({"day": 1, "time_min": 8 * 60})
    st_rem.setdefault("world", {}).setdefault("locations", {})["london"] = {"restrictions": {}, "market": {}}
    st_rem.setdefault("world", {}).setdefault("locations", {})["jakarta"] = {"restrictions": {}, "market": {}}
    # Run world tick (non-travel) should schedule at most 1 remote event/day (if any).
    world_tick(st_rem, {"action_type": "instant"})
    pes = st_rem.get("pending_events", []) or []
    assert isinstance(pes, list)
    assert any(isinstance(ev, dict) and isinstance(ev.get("payload"), dict) and ev.get("payload", {}).get("location") in ("jakarta", "london") for ev in pes)

    # Atlas/location profile: should be deterministic + cached per location.
    from engine.atlas import ensure_location_profile

    st_at = initialize_state({"name": "Atlas", "location": "london", "year": "2025"}, seed_pack="minimal")
    st_at.setdefault("meta", {}).update({"day": 1, "time_min": 8 * 60})
    p1 = ensure_location_profile(st_at, "London")
    p2 = ensure_location_profile(st_at, "London")
    assert isinstance(p1, dict) and isinstance(p2, dict)
    assert p1.get("sig") == p2.get("sig")
    # New city should generate a profile too (even if seed missing).
    p3 = ensure_location_profile(st_at, "Gotham")
    assert isinstance(p3, dict) and p3.get("name") == "Gotham"
    # Country relations + geopolitics state exist.
    atlas = (st_at.get("world", {}) or {}).get("atlas", {}) or {}
    assert isinstance(atlas, dict)
    assert isinstance(atlas.get("countries", {}), dict)
    gp = atlas.get("geopolitics", {}) or {}
    assert isinstance(gp, dict)

    # Legacy events should map to restrictions/areas when triggered.
    st_leg = initialize_state({"name": "LegacyEvt", "location": "london", "year": "2025"}, seed_pack="minimal")
    st_leg.setdefault("meta", {}).update({"day": 2, "time_min": 8 * 60})
    st_leg.setdefault("world", {}).setdefault("locations", {})["london"] = {"restrictions": {}, "areas": {}, "market": {}}
    st_leg["pending_events"] = [
        {"event_type": "investigation_sweep", "title": "inv", "due_day": 2, "due_time": 8 * 60, "triggered": False, "payload": {"trace_snapshot": 55, "location": "london"}},
        {"event_type": "manhunt_lockdown", "title": "mh", "due_day": 2, "due_time": 8 * 60, "triggered": False, "payload": {"trace_snapshot": 80, "location": "london"}},
    ]
    update_timers(st_leg, {"action_type": "instant", "instant_minutes": 0})
    slot = (((st_leg.get("world", {}) or {}).get("locations", {}) or {}).get("london", {}) or {})
    restr = slot.get("restrictions", {}) or {}
    areas = slot.get("areas", {}) or {}
    assert int(restr.get("police_sweep_until_day", 0) or 0) >= 2
    assert isinstance(areas, dict) and ("downtown" in areas or "transit_hubs" in areas)

    # Intercity market flow: convergence should not explode values.
    st_flow = initialize_state({"name": "Flow", "location": "london", "year": "2025"}, seed_pack="minimal")
    st_flow.setdefault("meta", {}).update({"day": 1, "time_min": 8 * 60})
    st_flow.setdefault("world", {}).setdefault("locations", {})["london"] = {"restrictions": {}, "market": {"electronics": {"price_idx": 220, "scarcity": 10}, "medical": {"price_idx": 100, "scarcity": 0}, "weapons": {"price_idx": 100, "scarcity": 0}, "food": {"price_idx": 100, "scarcity": 0}, "transport": {"price_idx": 100, "scarcity": 0}}}
    st_flow.setdefault("world", {}).setdefault("locations", {})["jakarta"] = {"restrictions": {}, "market": {"electronics": {"price_idx": 80, "scarcity": 10}, "medical": {"price_idx": 100, "scarcity": 0}, "weapons": {"price_idx": 100, "scarcity": 0}, "food": {"price_idx": 100, "scarcity": 0}, "transport": {"price_idx": 100, "scarcity": 0}}}
    from engine.market import update_market

    update_market(st_flow)
    lpx = int((((st_flow["world"]["locations"]["london"]["market"]["electronics"]).get("price_idx", 100)) or 100))
    jpx = int((((st_flow["world"]["locations"]["jakarta"]["market"]["electronics"]).get("price_idx", 100)) or 100))
    assert 60 <= lpx <= 320
    assert 60 <= jpx <= 320

    # Geopolitics market hook: adding sanctions should push electronics/transport up (bounded).
    st_geo = initialize_state({"name": "Geo", "location": "london", "year": "2025"}, seed_pack="minimal")
    st_geo.setdefault("meta", {}).update({"day": 5, "time_min": 8 * 60})
    st_geo.setdefault("world", {}).setdefault("atlas", {}).setdefault("geopolitics", {"last_tick_day": 4, "tension_idx": 70, "active_sanctions": [{"day": 5, "a": "united states", "b": "japan", "kind": "sanction"}]})
    from engine.market import update_market

    before_e = int(((st_geo.get("economy", {}) or {}).get("market", {}) or {}).get("electronics", {}).get("price_idx", 100) or 100)
    update_market(st_geo)
    after_e = int(((st_geo.get("economy", {}) or {}).get("market", {}) or {}).get("electronics", {}).get("price_idx", 100) or 100)
    assert after_e >= before_e

    # Country market layer: iconic oil_gas countries should have cheaper transport baseline than manufacturing hubs.
    from engine.atlas import ensure_country_market

    st_cm = initialize_state({"name": "CountryMarket", "location": "london", "year": "2025"}, seed_pack="minimal")
    st_cm.setdefault("meta", {}).update({"day": 3, "time_min": 8 * 60})
    from engine.market import update_market

    update_market(st_cm)  # compute global market first
    gmk = (st_cm.get("economy", {}) or {}).get("market", {}) or {}
    iran = ensure_country_market(st_cm, "iran", global_market=gmk, day=3, sanctions_level=0, tension_idx=0)
    ger = ensure_country_market(st_cm, "germany", global_market=gmk, day=3, sanctions_level=0, tension_idx=0)
    iran_t = int(((iran.get("market", {}) or {}).get("transport", {}) or {}).get("price_idx", 100) or 100)
    ger_t = int(((ger.get("market", {}) or {}).get("transport", {}) or {}).get("price_idx", 100) or 100)
    assert iran_t <= ger_t

    # Auto quest offers: trace cleanup / debt repayment / corp infiltration.
    from engine.world import world_tick

    st_qo = initialize_state({"name": "AutoQuest", "location": "london", "year": "2025"}, seed_pack="minimal")
    st_qo.setdefault("meta", {}).update({"day": 2, "time_min": 8 * 60})
    st_qo.setdefault("world", {}).setdefault("locations", {})["london"] = {"restrictions": {"corporate_lockdown_until_day": 3}, "areas": {}, "market": {}}
    st_qo.setdefault("trace", {})["trace_pct"] = 60
    st_qo.setdefault("economy", {})["debt"] = 200
    world_tick(st_qo, {"action_type": "instant"})
    qa = (st_qo.get("quests", {}) or {}).get("active") or []
    assert isinstance(qa, list)
    kinds = {str(q.get("kind", "")) for q in qa if isinstance(q, dict)}
    assert "trace_cleanup" in kinds
    assert "debt_repayment" in kinds
    assert "corp_infiltration" in kinds

    # Progress one step: trace_cleanup cover tracks.
    from engine.quests import tick_quest_chains

    tick_quest_chains(st_qo, {"normalized_input": "hapus jejak cover tracks", "action_type": "instant", "domain": "hacking"})
    qa2 = (st_qo.get("quests", {}) or {}).get("active") or []
    tc = [q for q in qa2 if isinstance(q, dict) and q.get("kind") == "trace_cleanup"]
    assert tc and int(tc[0].get("step", 0) or 0) >= 1

    # Deterministic roll: same state + same action_ctx => same roll.
    from engine.modifiers import compute_roll_package

    st_rng = initialize_state({"name": "DetRoll", "location": "london", "year": "2025"}, seed_pack="minimal")
    st_rng.setdefault("meta", {}).update({"day": 1, "time_min": 8 * 60, "turn": 10})
    ctx_rng = {"domain": "stealth", "action_type": "instant", "normalized_input": "masuk diam-diam lewat jendela", "trained": True, "uncertain": True, "has_stakes": True}
    r1 = compute_roll_package(st_rng, dict(ctx_rng)).get("roll")
    r2 = compute_roll_package(st_rng, dict(ctx_rng)).get("roll")
    assert r1 == r2

    # Factions should persist per-location across travel (no reset).
    from engine.world import world_tick

    st_f = initialize_state({"name": "FactionPersist", "location": "london", "year": "2025"}, seed_pack="minimal")
    st_f.setdefault("meta", {}).update({"day": 1, "time_min": 8 * 60, "turn": 1})
    st_f.setdefault("world", {}).setdefault("locations", {})["london"] = {"restrictions": {}, "market": {}}
    st_f.setdefault("world", {}).setdefault("locations", {})["jakarta"] = {"restrictions": {}, "market": {}}
    # Initialize factions for london and mutate.
    from engine.hacking import ensure_location_factions

    ensure_location_factions(st_f)
    st_f["world"]["factions"]["corporate"]["power"] = 99
    # Travel away.
    world_tick(st_f, {"action_type": "travel", "travel_destination": "jakarta"})
    # Travel back.
    world_tick(st_f, {"action_type": "travel", "travel_destination": "london"})
    ensure_location_factions(st_f)
    assert int(st_f["world"]["factions"]["corporate"]["power"] or 0) == 99

    # Disguise: activate -> expires -> trace reduced; caught under sweep increases trace.
    from engine.disguise import activate_disguise, tick_disguise_expiry, ensure_disguise

    st_d = initialize_state({"name": "Disguise", "location": "london", "year": "2025"}, seed_pack="minimal")
    st_d.setdefault("meta", {}).update({"day": 1, "time_min": 8 * 60, "turn": 1})
    st_d.setdefault("economy", {})["cash"] = 200
    st_d.setdefault("trace", {})["trace_pct"] = 50
    ok = activate_disguise(st_d, "PersonaX", duration_minutes=5, cost_cash=40)
    assert ok is True
    assert int(st_d["trace"]["trace_pct"] or 0) <= 46
    # Advance time beyond expiry
    st_d["meta"]["time_min"] = 8 * 60 + 10
    tick_disguise_expiry(st_d)
    assert bool(ensure_disguise(st_d).get("active", True)) is False

    # Safehouse: rent + lay low reduces trace; rent delinquency emits ripple.
    from engine.safehouse import rent_here, apply_lay_low_bonus, process_daily_rent, ensure_safehouses

    st_sh = initialize_state({"name": "SH", "location": "london", "year": "2025"}, seed_pack="minimal")
    st_sh.setdefault("meta", {}).update({"day": 1, "time_min": 8 * 60})
    st_sh.setdefault("economy", {})["cash"] = 200
    st_sh.setdefault("trace", {})["trace_pct"] = 40
    assert rent_here(st_sh) is True
    apply_lay_low_bonus(st_sh)
    assert int(st_sh["trace"]["trace_pct"] or 0) < 40
    # Force cannot pay rent
    st_sh["economy"]["cash"] = 0
    st_sh["economy"]["bank"] = 0
    st_sh["meta"]["day"] = 2
    process_daily_rent(st_sh)
    st_sh["meta"]["day"] = 3
    process_daily_rent(st_sh)
    # After 2 delinquent days, should have a landlord_report ripple queued.
    ar = st_sh.get("active_ripples", []) or []
    assert any(isinstance(rp, dict) and rp.get("kind") == "landlord_report" for rp in ar)

    # Weather determinism: same day+loc yields same kind.
    from engine.weather import ensure_weather

    st_w = initialize_state({"name": "W", "location": "london", "year": "2025"}, seed_pack="minimal")
    st_w.setdefault("meta", {}).update({"day": 5, "time_min": 8 * 60})
    w1 = ensure_weather(st_w, "london", 5).get("kind")
    w2 = ensure_weather(st_w, "london", 5).get("kind")
    assert w1 == w2

    # Skills progression: XP increases after roll.
    from engine.skills import apply_skill_xp_after_roll, _ensure_skill

    st_skp = initialize_state({"name": "Skill", "location": "london", "year": "2025"}, seed_pack="minimal")
    st_skp.setdefault("meta", {}).update({"day": 1, "time_min": 8 * 60})
    _ensure_skill(st_skp, "hacking")
    before_xp = int((st_skp["skills"]["hacking"].get("xp", 0) or 0))
    apply_skill_xp_after_roll(st_skp, {"domain": "hacking", "stakes": "high"}, {"roll": 10, "outcome": "Success"})
    after_xp = int((st_skp["skills"]["hacking"].get("xp", 0) or 0))
    assert after_xp > before_xp

    # NPC sim: LOD cap respected (<=80 evaluated) and planner can schedule events/ripples.
    from engine.npc_sim import tick_npc_sim

    st_sim = initialize_state({"name": "NPCSimVerify", "location": "london", "year": "2025"}, seed_pack="minimal")
    st_sim.setdefault("meta", {}).update({"day": 1, "time_min": 8 * 60, "turn": 1})
    # Populate many NPCs; mark them as candidates via suspicion.
    st_sim["npcs"] = {}
    for i in range(200):
        st_sim["npcs"][f"N{i}"] = {
            "name": f"N{i}",
            "home_location": "jakarta" if i % 2 == 0 else "london",
            "affiliation": "civilian",
            "opportunism": 60,
            "loyalty": 40,
            "belief_summary": {"suspicion": 70, "respect": 40, "last_turn": 0},
        }
    tick_npc_sim(st_sim, {"action_type": "instant", "domain": "social"})
    last_counts = (st_sim.get("meta", {}) or {}).get("npc_sim_last_counts") or {}
    assert int(last_counts.get("evaluated", 999) or 999) <= 80

    # Force at least one scheduled action deterministically by trying a few turns.
    st_sim2 = initialize_state({"name": "NPCSimTrigger", "location": "london", "year": "2025"}, seed_pack="minimal")
    st_sim2.setdefault("meta", {}).update({"day": 1, "time_min": 8 * 60})
    st_sim2.setdefault("npcs", {})["Informer"] = {
        "name": "Informer",
        "home_location": "london",
        "affiliation": "police",
        "role": "informant",
        "opportunism": 95,
        "loyalty": 10,
        "belief_summary": {"suspicion": 95, "respect": 20, "last_turn": 0},
        "is_contact": True,
    }
    scheduled = False
    for t in range(1, 60):
        st_sim2.setdefault("meta", {})["turn"] = t
        tick_npc_sim(st_sim2, {"action_type": "instant", "domain": "social"})
        if (st_sim2.get("pending_events") or []) or (st_sim2.get("active_ripples") or []):
            scheduled = True
            break
    assert scheduled

    # NPC sim coarse tick: non-active NPC should get lod_bucket and last_coarse_turn on schedule (3/6/12).
    st_coarse = initialize_state({"name": "NPCCoarse", "location": "london", "year": "2025"}, seed_pack="minimal")
    st_coarse.setdefault("meta", {}).update({"day": 1, "time_min": 8 * 60, "turn": 12})
    st_coarse.setdefault("npcs", {})["FarNPC"] = {
        "name": "FarNPC",
        "home_location": "jakarta",
        "affiliation": "civilian",
        "role": "civilian",
        "belief_summary": {"suspicion": 5, "respect": 50, "last_turn": 0},
    }
    tick_npc_sim(st_coarse, {"action_type": "instant", "domain": "social"})
    pl = (st_coarse.get("npcs", {}).get("FarNPC", {}) or {}).get("planner", {}) or {}
    assert int(pl.get("lod_bucket", 0) or 0) in (3, 6, 12)
    assert int(pl.get("last_coarse_turn", 0) or 0) == 12

    # NPC move_location should change current_location, not home_location.
    st_mv = initialize_state({"name": "MoveLocVerify", "location": "london", "year": "2025"}, seed_pack="minimal")
    st_mv.setdefault("meta", {}).update({"day": 1, "time_min": 8 * 60, "turn": 10})
    st_mv.setdefault("npcs", {})["M"] = {"name": "M", "home_location": "london", "current_location": "london", "affiliation": "civilian", "belief_summary": {"suspicion": 0, "respect": 50}}
    st_mv["npcs"]["M"].setdefault("planner", {})["intent_queue"] = [{"kind": "move", "to": "jakarta", "created_turn": 10}]
    tick_npc_sim(st_mv, {"action_type": "instant", "domain": "social"})
    assert str(st_mv["npcs"]["M"].get("home_location", "") or "").strip().lower() == "london"
    assert str(st_mv["npcs"]["M"].get("current_location", "") or "").strip().lower() == "jakarta"

    # Social graph edge types should affect social conflict mods.
    st_rel = initialize_state({"name": "RelVerify", "location": "london", "year": "2025"}, seed_pack="minimal")
    st_rel.setdefault("npcs", {})["X"] = {"name": "X", "affiliation": "civilian", "belief_summary": {"suspicion": 0, "respect": 50}}
    st_rel.setdefault("world", {}).setdefault("social_graph", {}).setdefault("__player__", {})["X"] = {"type": "debt", "strength": 80, "since_day": 1, "last_interaction_day": 1}
    from engine.modifiers import compute_roll_package as _crp2
    rp_rel = _crp2(st_rel, {"domain": "social", "social_mode": "conflict", "targets": ["X"], "trained": True, "uncertain": True, "has_stakes": True})
    assert any(k == "Relationship" for k, _ in (rp_rel.get("mods") or []))

    # Social graph edge creation/update via NPCSim: seek_help should set handler/lover; last_interaction_day updates.
    st_edge = initialize_state({"name": "EdgeCreate", "location": "london", "year": "2025"}, seed_pack="minimal")
    st_edge.setdefault("meta", {}).update({"day": 3, "time_min": 8 * 60, "turn": 10})
    st_edge.setdefault("npcs", {})["C"] = {
        "name": "C",
        "home_location": "london",
        "affiliation": "corporate",
        "role": "civilian",
        "is_contact": True,
        "loyalty": 70,
        "opportunism": 30,
        "belief_summary": {"suspicion": 10, "respect": 60},
        # Strong love channel to force lover edge from seek_help intent execution.
        "joy": 95,
        "trust": 95,
        "fear": 80,
        "surprise": 0,
        "anger": 0,
        "disgust": 0,
    }
    # Inject an explicit queued intent to avoid probabilistic gating.
    st_edge["npcs"]["C"].setdefault("planner", {})["intent_queue"] = [{"kind": "seek_help"}]
    tick_npc_sim(st_edge, {"action_type": "instant", "domain": "social"})
    edge_c = (
        (st_edge.get("world", {}) or {}).get("social_graph", {}) or {}
    ).get("__player__", {}).get("C", {})
    assert isinstance(edge_c, dict)
    # seek_help may set lover/handler, but follow-up actions in the same tick can bump to ally.
    assert str(edge_c.get("type", "") or "") in ("lover", "handler", "ally", "neutral")
    assert int(edge_c.get("last_interaction_day", 0) or 0) == 3

    # Planner threshold gating: when utility is too low, NPCSim should not schedule actions/ripples.
    st_thr = initialize_state({"name": "ThresholdVerify", "location": "london", "year": "2025"}, seed_pack="minimal")
    st_thr.setdefault("meta", {}).update({"day": 1, "time_min": 8 * 60, "turn": 1})
    st_thr.setdefault("npcs", {})["Low"] = {
        "name": "Low",
        "home_location": "jakarta",
        "affiliation": "civilian",
        "role": "civilian",
        "opportunism": 10,
        "loyalty": 90,
        "belief_summary": {"suspicion": 5, "respect": 50},
        "fear": 0,
        "surprise": 0,
        "anger": 0,
        "disgust": 0,
        "joy": 0,
        "trust": 50,
    }
    tick_npc_sim(st_thr, {"action_type": "instant", "domain": "social"})
    assert not (st_thr.get("pending_events") or [])
    assert not (st_thr.get("active_ripples") or [])

    # Intent expiry: old intents should be pruned and not executed.
    st_exp = initialize_state({"name": "IntentExpiry", "location": "london", "year": "2025"}, seed_pack="minimal")
    st_exp.setdefault("meta", {}).update({"day": 1, "time_min": 8 * 60, "turn": 50})
    st_exp.setdefault("npcs", {})["E"] = {"name": "E", "home_location": "london", "affiliation": "civilian", "belief_summary": {"suspicion": 0, "respect": 50}}
    st_exp["npcs"]["E"].setdefault("planner", {})["intent_queue"] = [{"kind": "avoid", "created_turn": 1}]
    tick_npc_sim(st_exp, {"action_type": "instant", "domain": "social"})
    # Should not schedule anything from the stale intent.
    assert not (st_exp.get("active_ripples") or [])

    # Role event effects: npc_report should raise trace and push news/ripple when triggered.
    st_rep = initialize_state({"name": "NPCReportVerify", "location": "london", "year": "2025"}, seed_pack="minimal")
    st_rep.setdefault("meta", {}).update({"day": 1, "time_min": 8 * 60})
    st_rep.setdefault("trace", {})["trace_pct"] = 0
    st_rep["pending_events"] = [
        {
            "event_type": "npc_report",
            "title": "NPC report filed",
            "due_day": 1,
            "due_time": 8 * 60,
            "triggered": False,
            "payload": {"reporter": "Informer", "affiliation": "police", "suspicion": 90, "origin_location": "london", "origin_faction": "police"},
        }
    ]
    update_timers(st_rep, {"action_type": "instant", "instant_minutes": 0})
    assert int(st_rep.get("trace", {}).get("trace_pct", 0) or 0) > 0
    assert isinstance((st_rep.get("world", {}) or {}).get("news_feed", []), list)

    # npc_sell_info should trigger a ripple/news and bump buyer faction power slightly.
    st_sell = initialize_state({"name": "NPCSellVerify", "location": "london", "year": "2025"}, seed_pack="minimal")
    st_sell.setdefault("meta", {}).update({"day": 1, "time_min": 8 * 60})
    st_sell["pending_events"] = [
        {
            "event_type": "npc_sell_info",
            "title": "NPC sells intel",
            "due_day": 1,
            "due_time": 8 * 60,
            "triggered": False,
            "payload": {"npc": "Fixer", "buyer_faction": "black_market", "suspicion": 80, "origin_location": "london", "origin_faction": "black_market"},
        }
    ]
    before_pw = int((((st_sell.get("world", {}) or {}).get("factions", {}) or {}).get("black_market", {}) or {}).get("power", 50) or 50)
    update_timers(st_sell, {"action_type": "instant", "instant_minutes": 0})
    after_pw = int((((st_sell.get("world", {}) or {}).get("factions", {}) or {}).get("black_market", {}) or {}).get("power", 50) or 50)
    assert after_pw >= before_pw
    # Ripple is scheduled slightly in the future (time_min+15), so it may still be in active_ripples.
    assert any((rp.get("kind") == "npc_sell_info") for rp in (st_sell.get("active_ripples") or [])) or any(
        (rp.get("kind") == "npc_sell_info") for rp in (st_sell.get("surfacing_ripples_this_turn") or [])
    )

    # Contacts propagation: origin_faction should require matching contact affiliation (or delayed relay).
    st_c = initialize_state({"name": "ContactsProp", "location": "london", "year": "2025"}, seed_pack="minimal")
    st_c.setdefault("meta", {}).update({"day": 1, "time_min": 8 * 60, "turn": 1})
    st_c.setdefault("world", {}).setdefault("contacts", {})["CorpFriend"] = {"name": "CorpFriend", "affiliation": "corporate", "trust": 70, "is_contact": True}
    st_c.setdefault("world", {}).setdefault("contacts", {})["Random"] = {"name": "Random", "affiliation": "civilian", "trust": 90, "is_contact": True}
    st_c.setdefault("npcs", {})["CorpFriend"] = {"name": "CorpFriend", "affiliation": "corporate", "trust": 70, "anger": 0}
    st_c.setdefault("npcs", {})["Random"] = {"name": "Random", "affiliation": "civilian", "trust": 90, "anger": 0}
    st_c.setdefault("active_ripples", []).append(
        {
            "text": "Corp internal memo",
            "triggered_day": 1,
            "surface_day": 1,
            "surface_time": 8 * 60,
            "surfaced": False,
            "propagation": "contacts",
            "origin_location": "london",
            "origin_faction": "corporate",
            "impact": {"npc_emotions": {"anger": 10}, "severity": 40},
            "surface_attempts": 0,
        }
    )
    update_timers(st_c, {"action_type": "instant", "instant_minutes": 0})
    # Should surface immediately (matching corporate contact exists) and affect that contact.
    assert any("Corp internal memo" in str(rp.get("text", "")) for rp in (st_c.get("surfacing_ripples_this_turn") or []))
    assert int(st_c["npcs"]["CorpFriend"].get("anger", 0) or 0) >= 10

    # Relay case: no matching affiliation; only high-trust contact exists -> delayed surfacing.
    st_c2 = initialize_state({"name": "ContactsRelay", "location": "london", "year": "2025"}, seed_pack="minimal")
    st_c2.setdefault("meta", {}).update({"day": 1, "time_min": 8 * 60, "turn": 1})
    st_c2.setdefault("world", {}).setdefault("contacts", {})["Relay"] = {"name": "Relay", "affiliation": "civilian", "trust": 90, "is_contact": True}
    st_c2.setdefault("npcs", {})["Relay"] = {"name": "Relay", "affiliation": "civilian", "trust": 90, "anger": 0}
    st_c2.setdefault("active_ripples", []).append(
        {
            "text": "Police intel leak",
            "triggered_day": 1,
            "surface_day": 1,
            "surface_time": 8 * 60,
            "surfaced": False,
            "propagation": "contacts",
            "origin_location": "london",
            "origin_faction": "police",
            "impact": {"npc_emotions": {"anger": 10}, "severity": 40},
            "surface_attempts": 0,
        }
    )
    update_timers(st_c2, {"action_type": "instant", "instant_minutes": 0})
    assert not st_c2.get("surfacing_ripples_this_turn")
    # Next day retry should allow relay.
    st_c2.setdefault("meta", {})["day"] = 2
    st_c2.setdefault("meta", {})["time_min"] = 8 * 60
    update_timers(st_c2, {"action_type": "instant", "instant_minutes": 0})
    assert any("Police intel leak" in str(rp.get("text", "")) for rp in (st_c2.get("surfacing_ripples_this_turn") or []))

    # NPC belief snippets: surfaced ripple should create belief in relevant contact and affect social mods.
    st_b = initialize_state({"name": "BeliefVerify", "location": "london", "year": "2025"}, seed_pack="minimal")
    st_b.setdefault("meta", {}).update({"day": 1, "time_min": 8 * 60, "turn": 5})
    st_b.setdefault("world", {}).setdefault("contacts", {})["C1"] = {"name": "C1", "affiliation": "corporate", "trust": 70, "is_contact": True}
    st_b.setdefault("npcs", {})["C1"] = {"name": "C1", "affiliation": "corporate", "trust": 70, "disposition_score": 60, "ambient": False}
    st_b.setdefault("active_ripples", []).append(
        {
            "text": "[Hack] gagal: target=corporate (contacts).",
            "triggered_day": 1,
            "surface_day": 1,
            "surface_time": 8 * 60,
            "surfaced": False,
            "propagation": "contacts",
            "origin_location": "london",
            "origin_faction": "corporate",
            "surface_attempts": 0,
        }
    )
    update_timers(st_b, {"action_type": "instant", "instant_minutes": 0})
    bsn = (st_b.get("npcs", {}).get("C1", {}) or {}).get("belief_snippets") or []
    assert isinstance(bsn, list) and len(bsn) >= 1
    # Force high suspicion to validate modifier wiring (tuning of belief deltas is separate).
    st_b["npcs"]["C1"].setdefault("belief_summary", {})["suspicion"] = 80
    # Belief should influence social conflict roll via modifiers.
    from engine.modifiers import compute_roll_package as _crp
    ctx_sc = {"domain": "social", "social_mode": "conflict", "targets": ["C1"], "uncertain": True, "has_stakes": True}
    rp3 = _crp(st_b, ctx_sc)
    assert any(k in ("NPC suspicion", "NPC respect") for k, _ in (rp3.get("mods") or []))

    parts: list[str] = []
    for tag in SECTION_TAGS:
        if tag == "MEMORY_HASH":
            parts.append("<MEMORY_HASH>\n🎯 -\n</MEMORY_HASH>")
        else:
            parts.append(f"<{tag}>ok</{tag}>")
    valid = "\n".join(parts)
    assert not validate_ai_sections(valid)
    assert not validate_tag_balance(valid)
    assert not validate_memory_hash_delimiters(valid)
    mh = parse_memory_hash(valid)
    assert "raw" in mh

    # Daily burn once per sim day (not only when time_min==0); bank floor 0 after shortfall → debt.
    burn_st = {
        "meta": {"day": 2, "time_min": 1},
        "economy": {"cash": 100, "bank": 500, "debt": 0, "daily_burn": 40, "fico": 600, "last_economic_cycle_day": 1},
    }
    update_economy(burn_st, {})
    assert burn_st["economy"]["cash"] == 60
    assert burn_st["economy"]["last_economic_cycle_day"] == 2

    # Market should react to police attention + corp instability.
    mkt_st = {
        "meta": {"day": 2, "time_min": 1},
        "economy": {"cash": 100, "bank": 500, "debt": 0, "daily_burn": 0, "fico": 600, "last_economic_cycle_day": 1},
        "trace": {"trace_pct": 80, "trace_status": "Manhunt"},
        "world": {
            "faction_statuses": {"police": "manhunt", "corporate": "manhunt", "black_market": "manhunt"},
            "factions": {"corporate": {"stability": 15, "power": 70}, "black_market": {"stability": 60, "power": 70}, "police": {"stability": 50, "power": 80}},
        },
    }
    update_economy(mkt_st, {})
    mkt = mkt_st["economy"].get("market", {})
    assert isinstance(mkt, dict)
    assert int(mkt.get("weapons", {}).get("price_idx", 100) or 100) > 100
    assert int(mkt.get("electronics", {}).get("price_idx", 100) or 100) > 100

    debt_st = {
        "meta": {"day": 2, "time_min": 0},
        "economy": {"cash": 10, "bank": 5, "debt": 0, "daily_burn": 100, "fico": 600, "last_economic_cycle_day": 1},
    }
    update_economy(debt_st, {})
    assert debt_st["economy"]["cash"] == 0
    assert debt_st["economy"]["bank"] == 0
    assert debt_st["economy"]["debt"] == 85

    # Inventory micro-ops: stow from hand should not waste a turn, only adds time.
    inv_st = initialize_state({"name": "InvVerify", "location": "Test", "year": "2025"}, seed_pack="minimal")
    inv = inv_st.setdefault("inventory", {})
    inv["r_hand"] = "phone"
    inv["l_hand"] = "-"
    inv.setdefault("item_sizes", {})["phone"] = 1
    inv["pocket_capacity"] = 1
    ctx_ops = {"action_type": "instant", "domain": "other", "instant_minutes": 2, "inventory_ops": [{"op": "stow", "from": "r_hand", "to": "pocket", "time_cost_min": 1}]}
    apply_inventory_ops(inv_st, ctx_ops)
    assert inv_st["inventory"]["r_hand"] == "-"
    # pocket capacity=1 should still accept phone size=1
    assert "phone" in (inv_st["inventory"].get("pocket_contents") or [])
    assert int(ctx_ops.get("instant_minutes", 0)) >= 3
    # Timer should advance by that time
    before = int(inv_st.get("meta", {}).get("time_min", 0))
    update_timers(inv_st, ctx_ops)
    after = int(inv_st.get("meta", {}).get("time_min", 0))
    assert after >= before + 1

    # If pocket is full, stow should fall back to bag (if available)
    inv2 = initialize_state({"name": "InvVerify2", "location": "Test", "year": "2025"}, seed_pack="minimal")
    inv2i = inv2.setdefault("inventory", {})
    inv2i["r_hand"] = "laptop"
    inv2i["pocket_capacity"] = 1
    inv2i["pocket_contents"] = ["phone"]
    inv2i["bag_capacity"] = 12
    inv2i.setdefault("item_sizes", {}).update({"phone": 1, "laptop": 5})
    ctx2 = {"action_type": "instant", "domain": "other", "instant_minutes": 2, "inventory_ops": [{"op": "stow", "from": "r_hand", "to": "pocket", "time_cost_min": 2}]}
    apply_inventory_ops(inv2, ctx2)
    assert inv2i["r_hand"] == "-"
    assert "laptop" in (inv2i.get("bag_contents") or [])

    # Inventory micro-op: pickup from nearby scene objects into pocket/bag.
    inv3 = initialize_state({"name": "InvPickup", "location": "Test", "year": "2025"}, seed_pack="minimal")
    inv3.setdefault("world", {})["nearby_items"] = [{"id": "laptop1", "name": "Laptop Pro 15"}]
    inv3i = inv3.setdefault("inventory", {})
    inv3i["pocket_capacity"] = 1
    inv3i["bag_capacity"] = 10
    inv3i["pocket_contents"] = []
    inv3i["bag_contents"] = []
    inv3i.setdefault("item_sizes", {}).update({"laptop1": 5})
    ctx3 = {
        "action_type": "instant",
        "domain": "other",
        "instant_minutes": 2,
        "inventory_ops": [{"op": "pickup", "item_id": "laptop1", "to": "pocket", "time_cost_min": 2}],
    }
    apply_inventory_ops(inv3, ctx3)
    # Laptop doesn't fit pocket (size=5, cap=1), should fall back to bag.
    assert "laptop1" not in [x.get("id", x) if isinstance(x, dict) else x for x in inv3.get("world", {}).get("nearby_items", [])]
    assert "laptop1" in (inv3i.get("bag_contents") or [])

    # Inventory micro-op: drop from hand should reappear as nearby item.
    inv4 = initialize_state({"name": "InvDrop", "location": "Test", "year": "2025"}, seed_pack="minimal")
    inv4.setdefault("world", {})["nearby_items"] = []
    inv4i = inv4.setdefault("inventory", {})
    inv4i["r_hand"] = "phone"
    inv4i["pocket_capacity"] = 1
    inv4i.setdefault("item_sizes", {})["phone"] = 1
    ctx4 = {
        "action_type": "instant",
        "domain": "other",
        "instant_minutes": 2,
        "inventory_ops": [{"op": "drop", "from": "r_hand", "time_cost_min": 2}],
    }
    apply_inventory_ops(inv4, ctx4)
    assert inv4i["r_hand"] == "-"
    assert any((isinstance(x, dict) and x.get("id") == "phone") or (isinstance(x, str) and x == "phone") for x in inv4.get("world", {}).get("nearby_items", []))

    # Stress test: run multiple mixed turns and validate invariants.
    from engine.world import world_tick
    from engine.bio import update_bio
    from engine.skills import update_skills
    from engine.npcs import update_npcs
    from engine.inventory import update_inventory
    from engine.trace import update_trace
    from engine.hacking import apply_hacking_after_roll
    from engine.npc_emotions import apply_npc_emotion_after_roll
    from engine.combat import resolve_combat_after_roll
    from engine.timers import update_timers

    st_s = initialize_state({"name": "Stress", "location": "jakarta", "year": "2025"}, seed_pack="default")
    st_s.setdefault("inventory", {}).setdefault("weapons", {})["gun1"] = {"name": "Gun-1", "kind": "firearm", "ammo": 5, "condition_tier": 2}
    st_s["inventory"]["active_weapon_id"] = "gun1"
    cmds = [
        {"domain": "social", "action_type": "talk", "social_mode": "non_conflict", "intent_note": "social_dialogue", "normalized_input": "ngobrol"},
        {"domain": "social", "action_type": "talk", "social_mode": "conflict", "intent_note": "social_conflict", "normalized_input": "memaksa orang itu"},
        {"domain": "hacking", "action_type": "instant", "normalized_input": "hack server pusat data penting perusahaan", "visibility": "public"},
        {"domain": "hacking", "action_type": "instant", "normalized_input": "hack diam-diam", "visibility": "low"},
        {"domain": "combat", "action_type": "combat", "combat_style": "ranged", "normalized_input": "tembak", "visibility": "public"},
        {"action_type": "travel", "domain": "other", "travel_destination": "london", "normalized_input": "pergi ke london"},
        {"action_type": "travel", "domain": "other", "travel_destination": "jakarta", "normalized_input": "pergi ke jakarta"},
    ]

    for i in range(30):
        ctx = dict(cmds[i % len(cmds)])
        world_tick(st_s, ctx)
        update_timers(st_s, ctx)
        update_bio(st_s, ctx)
        update_skills(st_s, ctx)
        update_npcs(st_s, ctx)
        update_economy(st_s, ctx)
        update_trace(st_s, ctx)
        update_inventory(st_s, ctx)
        apply_combat_gates(st_s, ctx)
        rp = compute_roll_package(st_s, ctx)
        apply_hacking_after_roll(st_s, ctx, rp)
        apply_npc_emotion_after_roll(st_s, ctx, rp)
        resolve_combat_after_roll(st_s, ctx, rp)

        # Invariants
        trv = int(st_s.get("trace", {}).get("trace_pct", 0) or 0)
        assert 0 <= trv <= 100
        factions = st_s.get("world", {}).get("factions", {}) or {}
        if isinstance(factions, dict):
            for f in ("corporate", "police", "black_market"):
                row = factions.get(f, {}) or {}
                if isinstance(row, dict):
                    assert 0 <= int(row.get("stability", 50) or 50) <= 100
                    assert 0 <= int(row.get("power", 50) or 50) <= 100
        mkt = st_s.get("economy", {}).get("market", {}) or {}
        if isinstance(mkt, dict):
            for k in ("electronics", "medical", "weapons", "food", "transport"):
                row = mkt.get(k, {}) or {}
                if isinstance(row, dict):
                    assert 0 <= int(row.get("scarcity", 0) or 0) <= 100
                    assert 50 <= int(row.get("price_idx", 100) or 100) <= 300
        pe = st_s.get("pending_events", []) or []
        assert isinstance(pe, list)
        assert len(pe) < 80

    # Stress test: NPCSim heavy load (many NPCs + many contacts) should respect caps and avoid runaway queues.
    from engine.npc_sim import tick_npc_sim as _tns
    st_nsim = initialize_state({"name": "NPCSimLoad", "location": "london", "year": "2025"}, seed_pack="minimal")
    st_nsim.setdefault("meta", {}).update({"day": 1, "time_min": 8 * 60, "turn": 1})
    st_nsim.setdefault("world", {}).setdefault("contacts", {})
    for i in range(120):
        name = f"C{i}"
        st_nsim["world"]["contacts"][name] = {"name": name, "affiliation": "civilian", "trust": 70, "is_contact": True}
        st_nsim.setdefault("npcs", {})[name] = {"name": name, "home_location": "london", "is_contact": True, "affiliation": "civilian", "belief_summary": {"suspicion": 40, "respect": 55}}
    for i in range(220):
        name = f"N{i}"
        st_nsim.setdefault("npcs", {})[name] = {"name": name, "home_location": "jakarta", "affiliation": "civilian", "belief_summary": {"suspicion": 10, "respect": 50}}
    for t in range(1, 40):
        st_nsim.setdefault("meta", {})["turn"] = t
        _tns(st_nsim, {"action_type": "instant", "domain": "social"})
        # Queues should remain bounded.
        assert len(st_nsim.get("pending_events") or []) < 120
        assert len(st_nsim.get("active_ripples") or []) < 120
        # Caps should be respected in counters.
        c = (st_nsim.get("meta", {}) or {}).get("npc_sim_last_counts") or {}
        if isinstance(c, dict):
            assert int(c.get("evaluated", 0) or 0) <= 80
            assert int(c.get("coarse", 0) or 0) <= 80

    # Stress test: ironman vs normal + UNDO restore (state-level).
    from engine.state import CURRENT, PREVIOUS, save_state, backup_state, load_state
    st_mode = initialize_state({"name": "ModeTest", "location": "london", "year": "2025"}, seed_pack="minimal")
    st_mode.setdefault("flags", {})["ironman_mode"] = False
    st_mode.setdefault("economy", {})["cash"] = 10
    backup_state()
    save_state(st_mode, CURRENT)
    st_mode2 = load_state(CURRENT)
    assert bool((st_mode2.get("flags", {}) or {}).get("ironman_mode", False)) is False
    assert int((st_mode2.get("economy", {}) or {}).get("cash", 0) or 0) == 10
    # Simulate a new turn save + backup, then restore previous.
    st_mode2.setdefault("economy", {})["cash"] = 99
    backup_state()
    save_state(st_mode2, CURRENT)
    assert PREVIOUS.exists()
    restored = load_state(PREVIOUS)
    # previous should have the earlier cash value (10) or at least not equal to 99 in normal flow
    assert int((restored.get("economy", {}) or {}).get("cash", 0) or 0) != 99


def main() -> int:
    if not _compile():
        print("compileall FAILED", file=sys.stderr)
        return 1
    try:
        _smoke()
    except AssertionError as e:
        import traceback

        print("smoke FAILED:", e, file=sys.stderr)
        traceback.print_exc()
        return 1
    except Exception as e:
        import traceback

        print("smoke ERROR:", e, file=sys.stderr)
        traceback.print_exc()
        return 1
    print("OK: compileall + smoke")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
