"""
Smoke + compile check. Run from repo root: python scripts/verify.py
"""

from __future__ import annotations

import compileall
import hashlib
import json
import sys
import tempfile
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
    ok = bool(compileall.compile_file(ROOT / "scripts" / "migrate_save.py", quiet=1)) and ok
    ok = bool(compileall.compile_file(ROOT / "scripts" / "validate_all.py", quiet=1)) and ok
    return ok


def test_master_e2e_pipeline() -> None:
    """Master E2E: use top-level handlers to validate cross-system stability."""
    from engine.core.state import initialize_state
    from main import handle_special
    from engine.systems.black_market import generate_black_market_inventory
    from engine.systems.jobs import generate_gigs

    st = initialize_state({"name": "MasterE2E", "location": "london", "year": "2025", "occupation": "hacker"}, seed_pack="minimal")
    st.setdefault("meta", {}).update({"day": 3, "time_min": 8 * 60, "turn": 0})
    st.setdefault("economy", {})["cash"] = 100_000
    st.setdefault("trace", {})["trace_pct"] = 0
    st.setdefault("inventory", {}).setdefault("bag_contents", []).append("laptop_basic")
    abs_min = lambda s: int((s.get("meta", {}) or {}).get("day", 1) or 1) * 1440 + int((s.get("meta", {}) or {}).get("time_min", 0) or 0)

    # 1) GIGS -> WORK <id>
    assert handle_special(st, "GIGS") is True
    gigs = generate_gigs(st)
    assert isinstance(gigs, list) and gigs
    gid = str((gigs[0] or {}).get("id", "") or "")
    assert gid
    t0 = abs_min(st)
    assert handle_special(st, f"WORK {gid}") is True
    t1 = abs_min(st)
    assert t1 > t0

    # 2) WORK until fatigue limit reached (max 2/day).
    assert handle_special(st, f"WORK {gid}") is True
    t2 = abs_min(st)
    assert t2 >= t1
    assert int((st.get("meta", {}) or {}).get("daily_gigs_done", 0) or 0) == 2
    assert handle_special(st, f"WORK {gid}") is True
    t3 = abs_min(st)
    assert t3 == t2  # no time spent when exhausted
    assert any("physically and mentally exhausted" in str(x) for x in (st.get("world_notes") or []))

    # 3) HACK atm increments daily_hacks_attempted.
    h0 = int((st.get("meta", {}) or {}).get("daily_hacks_attempted", 0) or 0)
    assert handle_special(st, "HACK atm") is True
    h1 = int((st.get("meta", {}) or {}).get("daily_hacks_attempted", 0) or 0)
    assert h1 == h0 + 1

    # 4) STAY 1 crossing midnight resets daily counters.
    meta = st.setdefault("meta", {})
    meta["time_min"] = 23 * 60 + 55
    d0 = int((st.get("meta", {}) or {}).get("day", 0) or 0)
    assert handle_special(st, "STAY hotel 1") is True
    d1 = int((st.get("meta", {}) or {}).get("day", 0) or 0)
    assert d1 == d0 + 1
    assert int((st.get("meta", {}) or {}).get("daily_gigs_done", -1) or 0) == 0
    assert int((st.get("meta", {}) or {}).get("daily_hacks_attempted", -1) or 0) == 0

    # 5) Reach night, access BLACKMARKET, then BUY_DARK.
    (st.get("meta", {}) or {})["time_min"] = 20 * 60
    assert handle_special(st, "BLACKMARKET") is True
    inv = generate_black_market_inventory(st)
    items = inv.get("items", []) or []
    assert isinstance(items, list) and items
    seed = str((st.get("meta", {}) or {}).get("world_seed", "") or (st.get("meta", {}) or {}).get("seed_pack", "") or "seed")
    day = int((st.get("meta", {}) or {}).get("day", 1) or 1)
    chosen = None
    for it in items:
        if not isinstance(it, dict):
            continue
        iid = str(it.get("id", "") or "")
        if not iid:
            continue
        h = hashlib.md5(f"{seed}|{day}|{iid}|sting".encode("utf-8", errors="ignore")).hexdigest()
        if int(h[:8], 16) % 100 >= 5:  # avoid sting for this e2e flow
            chosen = iid
            break
    if not chosen:
        chosen = str((items[0] or {}).get("id", "") or "")
    assert chosen
    assert handle_special(st, f"BUY_DARK {chosen}") is True
    bag = (st.get("inventory", {}) or {}).get("bag_contents", []) or []
    assert chosen in [str(x) for x in bag]


def _smoke() -> None:
    from ai.parser import (
        SECTION_TAGS,
        parse_memory_hash,
        validate_ai_sections,
        validate_memory_hash_delimiters,
        validate_tag_balance,
    )
    from engine.core.action_intent import parse_action_intent
    from engine.systems.combat import apply_combat_gates, resolve_combat_after_roll
    from engine.player.economy import update_economy
    from engine.world.world import world_tick
    from engine.systems.quests import generate_faction_events
    from engine.systems.quests import generate_faction_strikes, generate_daily_news
    from engine.core.modifiers import compute_roll_package
    from engine.player.inventory_ops import apply_inventory_ops
    from engine.world.timers import update_timers
    from engine.core.state import initialize_state
    from engine.systems.hacking import apply_hacking_after_roll, ensure_location_factions
    from engine.npc.npc_emotions import apply_npc_emotion_after_roll
    from engine.npc.npc_targeting import apply_npc_targeting

    def _stable_json(obj: object) -> str:
        return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"))

    def _determinism_fingerprint(state: dict[str, object]) -> str:
        # Focus on simulation-relevant state; excludes UI-only/transient fields.
        core = {
            "meta": state.get("meta", {}),
            "player": state.get("player", {}),
            "trace": state.get("trace", {}),
            "economy": state.get("economy", {}),
            "skills": state.get("skills", {}),
            "inventory": state.get("inventory", {}),
            "world": state.get("world", {}),
            "npcs": state.get("npcs", {}),
            "pending_events": state.get("pending_events", []),
            "active_ripples": state.get("active_ripples", []),
        }
        return hashlib.sha256(_stable_json(core).encode("utf-8", errors="ignore")).hexdigest()
    from engine.npc.npcs import update_npcs

    test_master_e2e_pipeline()

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
    assert str(st_travel.get("player", {}).get("location") or "").strip().lower() == "london"
    # Location preset should seed a few recognizable items (Earth-only travel uses presets, not seed packs).
    assert any(
        isinstance(x, dict) and str(x.get("id", "")).lower() in ("burner_phone", "laptop_basic", "keys")
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

    # Cross-domain ripple chain: one public cybercrime should impact trace -> faction attention -> market -> NPC beliefs/disposition.
    st_chain = initialize_state({"name": "ChainVerify", "location": "london", "year": "2025"}, seed_pack="minimal")
    st_chain.setdefault("meta", {}).update({"day": 1, "time_min": 8 * 60})
    st_chain.setdefault("trace", {})["trace_pct"] = 55
    # Keep one deterministic contact as recipient of surfaced rumor/broadcast.
    st_chain.setdefault("npcs", {})["Analyst_Z"] = {
        "name": "Analyst_Z",
        "affiliation": "civilian",
        "home_location": "london",
        "current_location": "london",
        "is_contact": True,
        "trust": 55,
        "disposition_score": 60,
        "disposition_label": "Warm",
        "belief_summary": {"suspicion": 0, "respect": 55},
    }
    st_chain.setdefault("world", {}).setdefault("contacts", {})["Analyst_Z"] = dict(st_chain["npcs"]["Analyst_Z"])
    # Day-1 baseline market snapshot.
    st_chain.setdefault("economy", {})["last_economic_cycle_day"] = 0
    update_economy(st_chain, {})
    pre_weap_px = int((((st_chain.get("economy", {}) or {}).get("market", {}) or {}).get("weapons", {}) or {}).get("price_idx", 100) or 100)
    pre_el_px = int((((st_chain.get("economy", {}) or {}).get("market", {}) or {}).get("electronics", {}) or {}).get("price_idx", 100) or 100)

    ctx_chain = {
        "domain": "hacking",
        "normalized_input": "hack server pusat data penting perusahaan",
        "action_type": "instant",
        "visibility": "public",
    }
    rp_chain = {"outcome": "Success", "roll": 20, "net_threshold": 50, "mods": [], "net_threshold_locked": True}
    apply_hacking_after_roll(st_chain, ctx_chain, rp_chain)
    assert int((st_chain.get("trace", {}) or {}).get("trace_pct", 0) or 0) >= 55
    assert st_chain.get("world", {}).get("faction_statuses", {}).get("police") in ("investigated", "manhunt")
    assert any(
        isinstance(rp, dict) and str(rp.get("text", "")).startswith("[Hack]")
        for rp in (st_chain.get("active_ripples", []) or [])
    )

    # Next day economy update should reflect heightened attention.
    st_chain["meta"]["day"] = 2
    st_chain["meta"]["time_min"] = 8 * 60
    st_chain.setdefault("economy", {})["last_economic_cycle_day"] = 1
    update_economy(st_chain, {})
    post_weap_px = int((((st_chain.get("economy", {}) or {}).get("market", {}) or {}).get("weapons", {}) or {}).get("price_idx", 100) or 100)
    post_el_px = int((((st_chain.get("economy", {}) or {}).get("market", {}) or {}).get("electronics", {}) or {}).get("price_idx", 100) or 100)
    assert post_weap_px >= pre_weap_px
    assert post_el_px >= pre_el_px

    # Surface ripple and ensure NPC receives belief update (suspicion/disposition consequence).
    disp_before = int((st_chain.get("npcs", {}).get("Analyst_Z", {}) or {}).get("disposition_score", 50) or 50)
    update_timers(st_chain, {"action_type": "instant", "instant_minutes": 0})
    az = (st_chain.get("npcs", {}) or {}).get("Analyst_Z", {}) or {}
    bsum = az.get("belief_summary", {}) if isinstance(az, dict) else {}
    assert isinstance(az.get("belief_snippets", []), list) and len(az.get("belief_snippets", [])) >= 1
    assert int((bsum.get("suspicion", 0) if isinstance(bsum, dict) else 0) or 0) > 0
    # Disposition should be updated as belief/suspicion effects are applied.
    assert int(az.get("disposition_score", 50) or 50) != disp_before

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

    # Gig economy: listing gigs and working one should advance time and log [Economy].
    from main import handle_special as _hs_gigs
    from engine.systems.jobs import generate_gigs as _gen_gigs

    st_g = initialize_state({"name": "GigVerify", "location": "london", "year": "2025"}, seed_pack="minimal")
    st_g.setdefault("meta", {}).update({"day": 2, "time_min": 8 * 60})
    st_g.setdefault("economy", {})["cash"] = 0
    assert _hs_gigs(st_g, "GIGS") is True
    gigs = _gen_gigs(st_g)
    assert isinstance(gigs, list) and gigs
    gid0 = str((gigs[0] or {}).get("id", "") or "")
    assert gid0
    t0 = int(st_g.get("meta", {}).get("time_min", 0) or 0)
    assert _hs_gigs(st_g, f"WORK {gid0}") is True
    t1 = int(st_g.get("meta", {}).get("time_min", 0) or 0)
    assert t1 != t0  # time advanced (instant_minutes applied)
    assert any(str(x).startswith("[Economy]") for x in (st_g.get("world_notes") or []))

    # Gig risk: failing a hacking/stealth/security gig increases trace by +10.
    st_gr = initialize_state({"name": "GigRisk", "location": "london", "year": "2025", "occupation": "hacker"}, seed_pack="minimal")
    st_gr.setdefault("meta", {}).update({"day": 2, "time_min": 8 * 60})
    st_gr.setdefault("trace", {})["trace_pct"] = 0
    st_gr.setdefault("skills", {})["hacking"] = {"level": 1, "xp": 0, "base": 10, "current": 10, "last_used_day": 1}
    gigs_r = _gen_gigs(st_gr)
    assert gigs_r and str((gigs_r[0] or {}).get("req_skill", "")) == "hacking"
    gid_r = str((gigs_r[0] or {}).get("id", "") or "")
    assert gid_r
    # Find a turn that forces failure for this gig (chance: lvl1 => 45 - diff*5).
    from engine.systems.jobs import execute_gig as _exec_g
    fail_turn = None
    for tn in range(512):
        st_gr["meta"]["turn"] = int(tn)
        rr = _exec_g(st_gr, gid_r)
        if bool(rr.get("ok")) and not bool(rr.get("success")):
            fail_turn = int(tn)
            break
    assert fail_turn is not None
    st_gr["meta"]["turn"] = fail_turn
    tr0 = int((st_gr.get("trace") or {}).get("trace_pct", 0) or 0)
    assert _hs_gigs(st_gr, f"WORK {gid_r}") is True
    tr1 = int((st_gr.get("trace") or {}).get("trace_pct", 0) or 0)
    assert tr1 >= tr0 + 10
    assert any("left a digital trail" in str(x) for x in (st_gr.get("world_notes") or []))

    # Targeted hacking system: success gives cash, failure raises trace, missing tools blocks.
    from engine.systems.targeted_hacking import deterministic_hack_roll_1_100
    from main import handle_special as _hs_hack

    st_hs = initialize_state({"name": "HackSys", "location": "london", "year": "2025"}, seed_pack="minimal")
    st_hs.setdefault("meta", {}).update({"day": 2, "time_min": 8 * 60})
    st_hs.setdefault("economy", {})["cash"] = 0
    st_hs.setdefault("trace", {})["trace_pct"] = 0
    st_hs.setdefault("skills", {})["hacking"] = {"level": 6, "xp": 0, "base": 10, "current": 40, "last_used_day": 1}
    st_hs.setdefault("inventory", {}).setdefault("bag_contents", []).append("laptop_basic")

    # Find a turn that succeeds at HACK atm.
    hit_s = None
    hit_f = None
    for tn in range(512):
        st_hs["meta"]["turn"] = int(tn)
        # chance formula in execute_hack: lvl6 -> chance=35+35-12=58
        r = deterministic_hack_roll_1_100(st_hs, target_type="atm")
        if hit_s is None and int(r) <= 58:
            hit_s = int(tn)
        if hit_f is None and int(r) > 58:
            hit_f = int(tn)
        if hit_s is not None and hit_f is not None:
            break
    assert hit_s is not None and hit_f is not None

    st_hs["meta"]["turn"] = hit_s
    cash0 = int((st_hs.get("economy") or {}).get("cash", 0) or 0)
    assert _hs_hack(st_hs, "HACK atm") is True
    cash1 = int((st_hs.get("economy") or {}).get("cash", 0) or 0)
    assert cash1 > cash0
    assert any(str(x).startswith("[Cyber] Successfully breached atm.") for x in (st_hs.get("world_notes") or []))

    st_hs["meta"]["turn"] = hit_f
    tr0 = int((st_hs.get("trace") or {}).get("trace_pct", 0) or 0)
    assert _hs_hack(st_hs, "HACK atm") is True
    tr1 = int((st_hs.get("trace") or {}).get("trace_pct", 0) or 0)
    assert tr1 >= tr0 + 15
    assert any(str(x).startswith("[Cyber] Intrusion detected at atm.") for x in (st_hs.get("world_notes") or []))

    # Hacking heat escalation: corporate faction heat increases on corp_server success.
    st_fh = initialize_state({"name": "HackHeat", "location": "london", "year": "2025"}, seed_pack="minimal")
    st_fh.setdefault("meta", {}).update({"day": 2, "time_min": 8 * 60})
    st_fh.setdefault("economy", {})["cash"] = 0
    st_fh.setdefault("trace", {})["trace_pct"] = 0
    st_fh.setdefault("skills", {})["hacking"] = {"level": 6, "xp": 0, "base": 10, "current": 40, "last_used_day": 1}
    st_fh.setdefault("inventory", {}).setdefault("bag_contents", []).append("laptop_basic")
    hit_corp = None
    for tn in range(512):
        st_fh["meta"]["turn"] = int(tn)
        r = deterministic_hack_roll_1_100(st_fh, target_type="corp_server")
        # chance formula in execute_hack: lvl6 -> chance=35+35-24=46
        if int(r) <= 46:
            hit_corp = int(tn)
            break
    assert hit_corp is not None
    st_fh["meta"]["turn"] = hit_corp
    assert _hs_hack(st_fh, "HACK corp_server") is True
    fh = (st_fh.get("world", {}) or {}).get("faction_heat", {}) or {}
    assert int(fh.get("corporate", 0) or 0) >= 20
    assert any("Corporate heat increased" in str(x) for x in (st_fh.get("world_notes") or []))

    st_no = initialize_state({"name": "HackNoTool", "location": "london", "year": "2025"}, seed_pack="minimal")
    st_no.setdefault("meta", {}).update({"day": 2, "time_min": 8 * 60})
    st_no.setdefault("inventory", {})["bag_contents"] = []
    st_no.setdefault("inventory", {})["pocket_contents"] = []
    assert _hs_hack(st_no, "HACK atm") is True
    assert any("Missing equipment" in str(x) for x in (st_no.get("world_notes") or []))

    # Underworld economy: black market stock is accessible at night; blocked at noon unless a Fixer/Smuggler is nearby.
    from engine.systems.black_market import buy_black_market_item, generate_black_market_inventory
    from main import handle_special as _hs_bm

    st_bm = initialize_state({"name": "BMVerify", "location": "london", "year": "2025"}, seed_pack="minimal")
    st_bm.setdefault("meta", {}).update({"day": 2, "time_min": 22 * 60})
    st_bm.setdefault("economy", {})["cash"] = 50_000
    assert _hs_bm(st_bm, "BLACKMARKET") is True
    inv = generate_black_market_inventory(st_bm)
    inv2 = generate_black_market_inventory(st_bm)
    assert inv == inv2
    items = inv.get("items", [])
    assert isinstance(items, list) and items
    iid0 = str((items[0] or {}).get("id", "") or "")
    assert iid0
    assert _hs_bm(st_bm, f"BUY_DARK {iid0}") is True
    bag = (st_bm.get("inventory", {}) or {}).get("bag_contents", []) or []
    assert isinstance(bag, list) and iid0 in [str(x) for x in bag]
    inv3 = generate_black_market_inventory(st_bm)
    assert iid0 not in [str((x or {}).get("id", "")) for x in (inv3.get("items") or []) if isinstance(x, dict)]

    from engine.systems.black_market import black_market_accessible, buy_black_market_item

    st_bm2 = initialize_state({"name": "BMNoon", "location": "london", "year": "2025"}, seed_pack="minimal")
    st_bm2.setdefault("meta", {}).update({"day": 2, "time_min": 12 * 60})
    assert black_market_accessible(st_bm2) is False
    r_den = buy_black_market_item(st_bm2, "burner_phone")
    assert bool(r_den.get("ok")) is False and r_den.get("reason") == "connection_refused"

    # Fixer nearby bypass at noon.
    st_bm2.setdefault("npcs", {})["Fixer_A"] = {"name": "Fixer_A", "role": "fixer", "tags": ["Fixer"], "current_location": "london", "ambient": False}
    assert black_market_accessible(st_bm2) is True

    # Sting operation: deterministic ambush during Black Market purchase.
    import hashlib

    from engine.systems.scenes import advance_scene as _advance_scene_sting

    st_sting = initialize_state({"name": "StingVerify", "location": "london", "year": "2025"}, seed_pack="minimal")
    st_sting.setdefault("meta", {}).update({"day": 1, "time_min": 22 * 60})
    st_sting.setdefault("economy", {})["cash"] = 50_000
    st_sting.setdefault("trace", {})["trace_pct"] = 80  # enables 20% sting chance

    # Find a day + item that deterministically triggers sting.
    seed = str((st_sting.get("meta", {}) or {}).get("seed_pack", "") or (st_sting.get("meta", {}) or {}).get("world_seed", "") or "seed")
    chosen = None
    for day in range(1, 60):
        st_sting["meta"]["day"] = int(day)
        inv_s = generate_black_market_inventory(st_sting)
        items_s = inv_s.get("items", []) or []
        for it in items_s:
            if not isinstance(it, dict):
                continue
            iid = str(it.get("id", "") or "")
            if not iid:
                continue
            h = hashlib.md5(f"{seed}|{day}|{iid}|sting".encode("utf-8", errors="ignore")).hexdigest()
            r = int(h[:8], 16) % 100
            if int(r) < 20:
                chosen = (iid, int(it.get("price", 0) or 0), int(day))
                break
        if chosen:
            break
    assert chosen is not None
    iid_s, price_s, day_s = chosen
    st_sting["meta"]["day"] = int(day_s)
    cash0 = int((st_sting.get("economy") or {}).get("cash", 0) or 0)
    rr = buy_black_market_item(st_sting, iid_s)
    assert bool(rr.get("ok")) is False and rr.get("reason") == "sting_operation"
    cash1 = int((st_sting.get("economy") or {}).get("cash", 0) or 0)
    assert cash1 == cash0 - int(price_s)
    asc = st_sting.get("active_scene") or {}
    assert str(asc.get("scene_type", "")) == "sting_operation"
    assert any("sting operation has been triggered" in str(x) for x in (st_sting.get("world_notes") or []))
    bag_s = (st_sting.get("inventory", {}) or {}).get("bag_contents", []) or []
    assert iid_s not in [str(x) for x in bag_s]

    day0 = int((st_sting.get("meta", {}) or {}).get("day", 0) or 0)
    _advance_scene_sting(st_sting, {"scene_action": "surrender"})
    assert (st_sting.get("active_scene") is None) or (st_sting.get("active_scene") == {})
    assert int((st_sting.get("trace") or {}).get("trace_pct", 0) or 0) == 0
    assert int((st_sting.get("meta", {}) or {}).get("day", 0) or 0) == day0 + 2


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
    from engine.world.world import world_tick as _wt
    _wt(st_heat, {"action_type": "instant"})
    heat2 = int((st_heat.get("world", {}).get("hacking_heat") or {}).get(key, {}).get("heat", 0) or 0)
    assert heat2 <= heat1

    # Security heat check (Lockdown tier): deterministic 30% trigger + scene intent lock.
    from engine.core.action_intent import apply_active_scene_intent_lock
    from engine.systems.encounter_scheduler import deterministic_security_roll_percent, evaluate_security_encounters

    st_sec = initialize_state({"name": "SecHeat", "location": "london", "year": "2025"}, seed_pack="minimal")
    st_sec.setdefault("trace", {})["trace_pct"] = 80
    st_sec.setdefault("meta", {}).setdefault("day", 1)
    hit_turn = None
    for tn in range(512):
        st_sec["meta"]["turn"] = int(tn)
        if deterministic_security_roll_percent(st_sec) < 30:
            hit_turn = int(tn)
            break
    assert hit_turn is not None
    st_sec["meta"]["turn"] = hit_turn
    st_sec.setdefault("world", {})["encounter_sched"] = {}
    r0 = evaluate_security_encounters(st_sec, {"action_type": "instant"})
    assert bool(r0.get("triggered")) is True
    asc = st_sec.get("active_scene") or {}
    assert str(asc.get("scene_type", "")) == "police_stop"
    assert str(asc.get("phase", "")) == "approach"
    assert "[Security]" in " ".join(st_sec.get("world_notes") or [])

    ctx_blk = parse_action_intent("aku pergi ke jakarta")
    apply_active_scene_intent_lock(st_sec, ctx_blk, "aku pergi ke jakarta")
    assert bool(ctx_blk.get("scene_locked")) is True
    assert ctx_blk.get("combat_blocked") == "scene_locked"

    ctx_ok = parse_action_intent("SCENE COMPLY")
    apply_active_scene_intent_lock(st_sec, ctx_ok, "SCENE COMPLY")
    assert ctx_ok.get("scene_locked") is None
    assert ctx_ok.get("combat_blocked") is None

    # Arrest protocol: patrol scene + high trace + COMPLY -> execute_arrest (time/money/trace/inventory).
    from engine.systems.scenes import advance_scene as _advance_scene_arrest

    st_ar = initialize_state({"name": "ArrestProt", "location": "london", "year": "2025"}, seed_pack="minimal")
    st_ar.setdefault("trace", {})["trace_pct"] = 90
    st_ar.setdefault("economy", {})["cash"] = 1000
    st_ar.setdefault("economy", {})["bank"] = 10000
    st_ar.setdefault("meta", {}).update({"day": 5, "time_min": 600})
    st_ar.setdefault("inventory", {}).setdefault("weapons", {})["gun1"] = {"name": "Gun-1", "kind": "firearm", "ammo": 3}
    st_ar["inventory"]["active_weapon_id"] = "gun1"
    st_ar["inventory"]["r_hand"] = "-"
    st_ar["inventory"]["l_hand"] = "-"
    st_ar["active_scene"] = {
        "scene_id": "testscene01",
        "scene_type": "police_stop",
        "phase": "approach",
        "context": {
            "location": "london",
            "district": "",
            "weapon_ids": [],
            "reason": "heat_check",
            "permit_doc": {},
            "dialog": {},
        },
        "vars": {"wait_count": 0},
        "expires_at": {"day": 5, "time_min": 1200},
        "next_options": ["SCENE COMPLY", "SCENE BRIBE 500", "SCENE RUN"],
    }
    r_ar = _advance_scene_arrest(st_ar, {"scene_action": "comply", "action_type": "instant"})
    assert bool(r_ar.get("ok")) and bool(r_ar.get("ended"))
    assert int((st_ar.get("trace") or {}).get("trace_pct", 0) or 0) == 0
    assert str(st_ar.get("trace", {}).get("trace_status", "")) == "Ghost"
    assert int(st_ar.get("meta", {}).get("day", 0) or 0) == 7
    assert int(st_ar.get("meta", {}).get("time_min", 0) or 0) == 480
    assert int((st_ar.get("economy") or {}).get("cash", 0) or 0) == 0
    assert int((st_ar.get("economy") or {}).get("bank", 0) or 0) == 8500
    assert str(st_ar.get("inventory", {}).get("active_weapon_id", "x") or "") == ""
    assert st_ar.get("active_scene") is None
    assert any("[Arrest]" in str(x) for x in (st_ar.get("world_notes") or []))

    ctx = parse_action_intent("tembak target")
    apply_combat_gates(st, ctx)
    assert ctx.get("combat_blocked") in (None, "no_weapon", "out_of_ammo", "broken", "scene_locked")

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
        {"name": "Verify2", "occupation": "operator", "background": "smoke2", "location": "london", "year": "2025", "language": "en"},
        seed_pack="minimal",
    )
    st2.setdefault("player", {}).setdefault("languages", {}).update({"en": 90})
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
    from engine.core.modifiers import compute_roll_package

    st_ev = initialize_state({"name": "EventResolve", "location": "london", "year": "2025"}, seed_pack="minimal")
    st_ev.setdefault("meta", {}).update({"day": 1, "time_min": 8 * 60})
    st_ev.setdefault("world", {}).setdefault("locations", {})["london"] = {"restrictions": {}, "market": {}}
    st_ev["pending_events"] = [
        {"event_type": "police_sweep", "title": "Sweep", "due_day": 1, "due_time": 8 * 60, "triggered": False, "payload": {"location": "london", "attention": "investigated", "police_power": 70}},
        {"event_type": "corporate_lockdown", "title": "Lockdown", "due_day": 1, "due_time": 8 * 60, "triggered": False, "payload": {"location": "london", "corp_power": 70, "corp_stability": 25}},
        {"event_type": "black_market_offer", "title": "Offer", "due_day": 1, "due_time": 8 * 60, "triggered": False, "payload": {"location": "london", "bm_power": 70, "bm_stability": 60}},
    ]
    update_timers(st_ev, {"action_type": "instant", "instant_minutes": 0})
    # police_sweep is now scene-backed (checkpoint_sweep); resolve it to apply restrictions deterministically.
    if isinstance(st_ev.get("active_scene"), dict) and (st_ev.get("active_scene") or {}).get("scene_type") == "checkpoint_sweep":
        from engine.systems.scenes import advance_scene

        advance_scene(st_ev, {"scene_action": "comply"})
    r = ((st_ev.get("world", {}) or {}).get("locations", {}) or {}).get("london", {}).get("restrictions", {}) or {}
    assert int(r.get("police_sweep_until_day", 0) or 0) >= 1
    assert int(r.get("corporate_lockdown_until_day", 0) or 0) >= 1
    qs = (st_ev.get("quests", {}) or {}).get("active") or []
    assert isinstance(qs, list) and len(qs) >= 1
    # Lockdown should make corporate hacking harder via modifiers.
    st_ev.setdefault("inventory", {}).setdefault("bag_contents", []).extend(["laptop_basic", "exploit_kit"])
    pkg = compute_roll_package(st_ev, {"domain": "hacking", "trained": True, "normalized_input": "hack corporate server intrusion"})
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
    from engine.player.market import update_market

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
    from engine.world.world import world_tick

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
    from engine.world.atlas import ensure_location_profile

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
    from engine.player.market import update_market

    update_market(st_flow)
    lpx = int((((st_flow["world"]["locations"]["london"]["market"]["electronics"]).get("price_idx", 100)) or 100))
    jpx = int((((st_flow["world"]["locations"]["jakarta"]["market"]["electronics"]).get("price_idx", 100)) or 100))
    assert 60 <= lpx <= 320
    assert 60 <= jpx <= 320

    # Geopolitics market hook: adding sanctions should push electronics/transport up (bounded).
    st_geo = initialize_state({"name": "Geo", "location": "london", "year": "2025"}, seed_pack="minimal")
    st_geo.setdefault("meta", {}).update({"day": 5, "time_min": 8 * 60})
    st_geo.setdefault("world", {}).setdefault("atlas", {}).setdefault("geopolitics", {"last_tick_day": 4, "tension_idx": 70, "active_sanctions": [{"day": 5, "a": "united states", "b": "japan", "kind": "sanction"}]})
    from engine.player.market import update_market

    before_e = int(((st_geo.get("economy", {}) or {}).get("market", {}) or {}).get("electronics", {}).get("price_idx", 100) or 100)
    update_market(st_geo)
    after_e = int(((st_geo.get("economy", {}) or {}).get("market", {}) or {}).get("electronics", {}).get("price_idx", 100) or 100)
    assert after_e >= before_e

    # Country market layer: iconic oil_gas countries should have cheaper transport baseline than manufacturing hubs.
    from engine.world.atlas import ensure_country_market

    st_cm = initialize_state({"name": "CountryMarket", "location": "london", "year": "2025"}, seed_pack="minimal")
    st_cm.setdefault("meta", {}).update({"day": 3, "time_min": 8 * 60})
    from engine.player.market import update_market

    update_market(st_cm)  # compute global market first
    gmk = (st_cm.get("economy", {}) or {}).get("market", {}) or {}
    iran = ensure_country_market(st_cm, "iran", global_market=gmk, day=3, sanctions_level=0, tension_idx=0)
    ger = ensure_country_market(st_cm, "germany", global_market=gmk, day=3, sanctions_level=0, tension_idx=0)
    iran_t = int(((iran.get("market", {}) or {}).get("transport", {}) or {}).get("price_idx", 100) or 100)
    ger_t = int(((ger.get("market", {}) or {}).get("transport", {}) or {}).get("price_idx", 100) or 100)
    assert iran_t <= ger_t

    # Auto quest offers: trace cleanup / debt repayment / corp infiltration.
    from engine.world.world import world_tick

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
    from engine.systems.quests import tick_quest_chains

    tick_quest_chains(st_qo, {"normalized_input": "hapus jejak cover tracks", "action_type": "instant", "domain": "hacking"})
    qa2 = (st_qo.get("quests", {}) or {}).get("active") or []
    tc = [q for q in qa2 if isinstance(q, dict) and q.get("kind") == "trace_cleanup"]
    assert tc and int(tc[0].get("step", 0) or 0) >= 1

    # Deterministic roll: same state + same action_ctx => same roll.
    from engine.core.modifiers import compute_roll_package

    st_rng = initialize_state({"name": "DetRoll", "location": "london", "year": "2025"}, seed_pack="minimal")
    st_rng.setdefault("meta", {}).update({"day": 1, "time_min": 8 * 60, "turn": 10})
    ctx_rng = {"domain": "stealth", "action_type": "instant", "normalized_input": "masuk diam-diam lewat jendela", "trained": True, "uncertain": True, "has_stakes": True}
    r1 = compute_roll_package(st_rng, dict(ctx_rng)).get("roll")
    r2 = compute_roll_package(st_rng, dict(ctx_rng)).get("roll")
    assert r1 == r2

    # Factions should persist per-location across travel (no reset).
    from engine.world.world import world_tick

    st_f = initialize_state({"name": "FactionPersist", "location": "london", "year": "2025"}, seed_pack="minimal")
    st_f.setdefault("meta", {}).update({"day": 1, "time_min": 8 * 60, "turn": 1})
    st_f.setdefault("world", {}).setdefault("locations", {})["london"] = {"restrictions": {}, "market": {}}
    st_f.setdefault("world", {}).setdefault("locations", {})["jakarta"] = {"restrictions": {}, "market": {}}
    # Initialize factions for london and mutate.
    from engine.systems.hacking import ensure_location_factions

    ensure_location_factions(st_f)
    st_f["world"]["factions"]["corporate"]["power"] = 99
    # Travel away.
    world_tick(st_f, {"action_type": "travel", "travel_destination": "jakarta"})
    # Travel back.
    world_tick(st_f, {"action_type": "travel", "travel_destination": "london"})
    ensure_location_factions(st_f)
    assert int(st_f["world"]["factions"]["corporate"]["power"] or 0) == 99

    # Disguise: activate -> expires -> trace reduced; caught under sweep increases trace.
    from engine.systems.disguise import activate_disguise, tick_disguise_expiry, ensure_disguise

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
    from engine.systems.safehouse import rent_here, apply_lay_low_bonus, process_daily_rent, ensure_safehouses

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
    from engine.world.weather import ensure_weather

    st_w = initialize_state({"name": "W", "location": "london", "year": "2025"}, seed_pack="minimal")
    st_w.setdefault("meta", {}).update({"day": 5, "time_min": 8 * 60})
    w1 = ensure_weather(st_w, "london", 5).get("kind")
    w2 = ensure_weather(st_w, "london", 5).get("kind")
    assert w1 == w2

    # Earth-only travel gate: unknown city should be rejected (no travel tick).
    st_tr = initialize_state({"name": "TravelGate", "location": "london", "year": "2025"}, seed_pack="minimal")
    ctx_bad = {"action_type": "travel", "travel_destination": "gotham"}
    world_tick(st_tr, ctx_bad)
    assert str((st_tr.get("player", {}) or {}).get("location", "") or "").strip().lower() == "london"
    assert ctx_bad.get("action_type") == "instant"

    # Skills progression: XP increases after roll.
    from engine.player.skills import apply_skill_xp_after_roll, _ensure_skill

    st_skp = initialize_state({"name": "Skill", "location": "london", "year": "2025"}, seed_pack="minimal")
    st_skp.setdefault("meta", {}).update({"day": 1, "time_min": 8 * 60})
    _ensure_skill(st_skp, "hacking")
    before_xp = int((st_skp["skills"]["hacking"].get("xp", 0) or 0))
    apply_skill_xp_after_roll(st_skp, {"domain": "hacking", "stakes": "high"}, {"roll": 10, "outcome": "Success"})
    after_xp = int((st_skp["skills"]["hacking"].get("xp", 0) or 0))
    assert after_xp > before_xp

    # Content packs: core pack loads and applies item_sizes.
    from engine.core.content_packs import freeze_packs_into_state, apply_pack_effects

    st_p = initialize_state({"name": "Pack", "location": "london", "year": "2025"}, seed_pack="minimal")
    freeze_packs_into_state(st_p, pack_ids=["core"])
    apply_pack_effects(st_p)
    sizes = (st_p.get("inventory", {}) or {}).get("item_sizes", {}) or {}
    assert isinstance(sizes, dict)
    assert int(sizes.get("laptop_basic", 0) or 0) == 3
    # Strict extras mode should still pass for valid packs.
    st_ps = initialize_state({"name": "PackStrict", "location": "london", "year": "2025"}, seed_pack="minimal")
    freeze_packs_into_state(st_ps, pack_ids=["core"], strict_extras=True)
    assert isinstance(((st_ps.get("meta", {}) or {}).get("content_packs", {}) or {}).get("extras", {}), dict)

    # Occupation templates: content-driven starter kits (items/skills/languages).
    st_occ = initialize_state(
        {"name": "OccVerify", "location": "london", "year": "2025", "occupation": "hacker", "background": "ops", "language": "en"},
        seed_pack="minimal",
    )
    assert str((st_occ.get("player", {}) or {}).get("occupation_template_id", "") or "").strip().lower() in ("hacker", "")
    bag_occ = (st_occ.get("inventory", {}) or {}).get("bag_contents", []) or []
    assert isinstance(bag_occ, list) and any(str(x).lower() == "laptop_basic" for x in bag_occ)
    sk_occ = (st_occ.get("skills", {}) or {}).get("hacking") or {}
    assert isinstance(sk_occ, dict) and int(sk_occ.get("level", 1) or 1) >= 3
    langs_occ = (st_occ.get("player", {}) or {}).get("languages", {}) or {}
    assert isinstance(langs_occ, dict) and int(langs_occ.get("en", 0) or 0) >= 60

    # Language learning MVP: class/book/immersion updates player.languages with time/cost.
    from engine.player.language_learning import learn_language

    st_ll = initialize_state({"name": "LearnLang", "location": "tokyo", "year": "2025", "language": "en"}, seed_pack="minimal")
    st_ll.setdefault("economy", {})["cash"] = 1000
    st_ll.setdefault("player", {})["languages"] = {"en": 80}
    st_ll.setdefault("inventory", {}).setdefault("bag_contents", []).append("phrasebook")
    res_book = learn_language(st_ll, "ja", method="book")
    assert bool(res_book.get("ok")) and int(res_book.get("minutes", 0) or 0) > 0
    assert int(((st_ll.get("player", {}) or {}).get("languages", {}) or {}).get("ja", 0) or 0) > 0
    res_imm = learn_language(st_ll, "ja", method="immersion")
    assert bool(res_imm.get("ok")) and int(res_imm.get("delta", 0) or 0) > 0

    # History indices determinism (seed/year/country): cached and stable.
    from engine.world.atlas import ensure_country_history_idx

    st_hist = initialize_state({"name": "Hist", "location": "london", "year": "2025"}, seed_pack="minimal")
    st_hist.setdefault("meta", {})["sim_year"] = 1942
    h1 = dict(ensure_country_history_idx(st_hist, "united kingdom", sim_year=1942))
    h2 = dict(ensure_country_history_idx(st_hist, "united kingdom", sim_year=1942))
    assert h1 == h2 and int(h1.get("border_controls", 0) or 0) >= 0
    h3 = dict(ensure_country_history_idx(st_hist, "united kingdom", sim_year=2025))
    assert h3.get("last_year") != h1.get("last_year") or h3 != h1

    # Border controls travel friction: should add time when strict.
    from engine.world.timers import update_timers

    st_bt = initialize_state({"name": "BorderTravel", "location": "nyc", "year": "1942"}, seed_pack="minimal")
    st_bt.setdefault("meta", {})["sim_year"] = 1942
    # Force strict border controls for deterministic test.
    uk = st_bt.setdefault("world", {}).setdefault("atlas", {}).setdefault("countries", {}).setdefault("united kingdom", {})
    uk.setdefault("history_idx", {})["last_year"] = 1942
    uk["history_idx"]["border_controls"] = 90
    act_bt = {"action_type": "travel", "travel_destination": "london", "travel_minutes": 30}
    update_timers(st_bt, act_bt)
    tb = act_bt.get("time_breakdown", []) or []
    assert any(isinstance(x, dict) and x.get("label") == "border_controls" for x in tb)

    # Hacking tier gate: intrusion without exploit should return No Roll (Missing Tools).
    from engine.core.modifiers import compute_roll_package

    st_hg = initialize_state({"name": "HackGate", "location": "london", "year": "2025"}, seed_pack="minimal")
    st_hg.setdefault("inventory", {}).setdefault("bag_contents", []).append("laptop_basic")
    ctx_hg = {"domain": "hacking", "action_type": "instant", "normalized_input": "hack corporate server intrusion", "trained": True}
    rp = compute_roll_package(st_hg, ctx_hg)
    assert str(rp.get("outcome", "")).startswith("No Roll (Missing Tools)")

    # Language barrier (year-aware): early year + no translator blocks high-stakes social in foreign language.
    from engine.core.language import communication_quality

    st_lb = initialize_state({"name": "Lang", "location": "tokyo", "year": 1995, "language": "en"}, seed_pack="minimal")
    # Force local language to be non-English for test determinism.
    st_lb.setdefault("world", {}).setdefault("locations", {}).setdefault("tokyo", {}).setdefault("profile", {})["language"] = "ja"
    st_lb.setdefault("player", {})["languages"] = {"en": 80}
    # No translator items.
    pkg = compute_roll_package(st_lb, {"domain": "social", "social_mode": "conflict", "trained": True, "normalized_input": "negosiasi kontrak"})
    assert str(pkg.get("outcome", "")).startswith("No Roll (Language Barrier)")

    # Modern year + translator item allows with penalty (not blocked).
    st_lb2 = initialize_state({"name": "Lang2", "location": "tokyo", "year": 2025, "language": "en"}, seed_pack="minimal")
    st_lb2.setdefault("world", {}).setdefault("locations", {}).setdefault("tokyo", {}).setdefault("profile", {})["language"] = "ja"
    st_lb2.setdefault("player", {})["languages"] = {"en": 80}
    st_lb2.setdefault("inventory", {}).setdefault("bag_contents", []).append("smartphone")
    pkg2 = compute_roll_package(st_lb2, {"domain": "social", "social_mode": "conflict", "trained": True, "normalized_input": "negosiasi kontrak"})
    assert str(pkg2.get("outcome", "")).startswith("No Roll") is False
    # Still should include a language modifier when not shared.
    assert any("language" in str(k).lower() for k, _v in (pkg2.get("mods") or []))

    # NPC sim: LOD cap respected (<=80 evaluated) and planner can schedule events/ripples.
    from engine.npc.npc_sim import tick_npc_sim

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
    st_rel = initialize_state({"name": "RelVerify", "location": "london", "year": "2025", "language": "en"}, seed_pack="minimal")
    st_rel.setdefault("player", {}).setdefault("languages", {}).update({"en": 90})
    st_rel.setdefault("npcs", {})["X"] = {"name": "X", "affiliation": "civilian", "belief_summary": {"suspicion": 0, "respect": 50}}
    st_rel.setdefault("world", {}).setdefault("social_graph", {}).setdefault("__player__", {})["X"] = {"type": "debt", "strength": 80, "since_day": 1, "last_interaction_day": 1}
    from engine.core.modifiers import compute_roll_package as _crp2
    rp_rel = _crp2(st_rel, {"domain": "social", "social_mode": "conflict", "targets": ["X"], "trained": True, "uncertain": True, "has_stakes": True})
    assert any(k == "Relationship" for k, _ in (rp_rel.get("mods") or []))

    # Social graph edge creation/update via NPCSim: seek_help should set handler/lover; last_interaction_day updates.
    st_edge = initialize_state({"name": "EdgeCreate", "location": "london", "year": "2025", "language": "en"}, seed_pack="minimal")
    st_edge.setdefault("player", {}).setdefault("languages", {}).update({"en": 90})
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
    st_b = initialize_state({"name": "BeliefVerify", "location": "london", "year": "2025", "language": "en"}, seed_pack="minimal")
    st_b.setdefault("player", {}).setdefault("languages", {}).update({"en": 90})
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
    from engine.core.modifiers import compute_roll_package as _crp
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

    # SHOP MVP: deterministic pricing + buy/sell affects cash & inventory.
    from engine.systems.shop import buy_item, list_shop_quotes, quote_item, sell_item, sell_item_all, sell_item_n, get_capacity_status

    st_shop = initialize_state({"name": "ShopVerify", "location": "london", "year": "2025"}, seed_pack="minimal")
    st_shop.setdefault("economy", {})["cash"] = 5000
    # ensure packs frozen/applied in init; quote should exist for core item
    q1 = quote_item(st_shop, "burner_phone")
    assert q1 is not None and int(q1.buy_price) > 0 and int(q1.sell_price) > 0
    q2 = quote_item(st_shop, "burner_phone")
    assert q2 is not None and q1.buy_price == q2.buy_price and q1.sell_price == q2.sell_price
    cash0 = int((st_shop.get("economy", {}) or {}).get("cash", 0) or 0)
    rbuy = buy_item(st_shop, "burner_phone", prefer="bag")
    assert bool(rbuy.get("ok"))
    inv_bag = (st_shop.get("inventory", {}) or {}).get("bag_contents", []) or []
    assert any(str(x).lower() == "burner_phone" for x in inv_bag)
    cash1 = int((st_shop.get("economy", {}) or {}).get("cash", 0) or 0)
    assert cash1 < cash0
    rsell = sell_item(st_shop, "burner_phone")
    assert bool(rsell.get("ok"))
    inv_bag2 = (st_shop.get("inventory", {}) or {}).get("bag_contents", []) or []
    assert not any(str(x).lower() == "burner_phone" for x in inv_bag2)
    cash2 = int((st_shop.get("economy", {}) or {}).get("cash", 0) or 0)
    assert cash2 > cash1
    cap0 = get_capacity_status(st_shop)
    assert cap0.bag_cap >= 1 and cap0.pocket_cap >= 1

    # SELL ALL should sell multiple occurrences deterministically.
    st_shop["economy"]["cash"] = 0
    st_shop.setdefault("inventory", {}).setdefault("bag_contents", []).extend(["burner_phone", "burner_phone"])
    r_all = sell_item_all(st_shop, "burner_phone")
    assert bool(r_all.get("ok")) and int(r_all.get("count", 0) or 0) >= 2
    assert int((st_shop.get("economy", {}) or {}).get("cash", 0) or 0) == int(r_all.get("gain", 0) or 0)
    # SELL xN
    st_shop["economy"]["cash"] = 0
    st_shop.setdefault("inventory", {})["bag_contents"] = ["burner_phone", "burner_phone", "burner_phone"]
    r_n = sell_item_n(st_shop, "burner_phone", n=2)
    assert bool(r_n.get("ok")) and int(r_n.get("count", 0) or 0) == 2
    assert len((st_shop.get("inventory", {}) or {}).get("bag_contents", []) or []) == 1

    # SHOP paging/offset: should return deterministic, non-empty page 1.
    q_p1 = list_shop_quotes(st_shop, limit=5, role="fixer", offset=0)
    assert isinstance(q_p1, list) and len(q_p1) >= 1
    # Tag filtering should produce a deterministic subset.
    q_tag = list_shop_quotes(st_shop, limit=10, tag="translator")
    assert isinstance(q_tag, list) and len(q_tag) >= 1

    # Shop skill modifiers: streetwise should slightly improve buy/sell prices (bounded).
    st_shop_mod = initialize_state({"name": "ShopMods", "location": "london", "year": "2025", "language": "en"}, seed_pack="minimal")
    st_shop_mod.setdefault("economy", {})["cash"] = 5000
    st_shop_mod.setdefault("skills", {})["streetwise"] = {"level": 1, "xp": 0, "base": 10, "last_used_day": 0, "mastery_streak": 0}
    qb1 = quote_item(st_shop_mod, "burner_phone")
    assert qb1 is not None
    st_shop_mod.setdefault("skills", {})["streetwise"]["level"] = 10
    qb2 = quote_item(st_shop_mod, "burner_phone")
    assert qb2 is not None
    assert int(qb2.buy_price) <= int(qb1.buy_price)

    # Shop language premium: if local language isn't shared, buy price should be higher (all else equal).
    st_shop_lang = initialize_state({"name": "ShopLang", "location": "tokyo", "year": "2025", "language": "en"}, seed_pack="minimal")
    st_shop_lang.setdefault("economy", {})["cash"] = 5000
    # Force deterministic local language context.
    st_shop_lang.setdefault("world", {}).setdefault("locations", {}).setdefault("tokyo", {}).setdefault("profile", {})["language"] = "ja"
    st_shop_lang.setdefault("player", {})["languages"] = {"en": 80}
    ql1 = quote_item(st_shop_lang, "burner_phone")
    assert ql1 is not None
    st_shop_lang.setdefault("player", {})["languages"]["ja"] = 80
    ql2 = quote_item(st_shop_lang, "burner_phone")
    assert ql2 is not None
    assert int(ql2.buy_price) <= int(ql1.buy_price)

    # Delivery: contraband can be purchased via dead drop (delayed, pickup required).
    st_del = initialize_state({"name": "Delivery", "location": "new york", "year": "2025"}, seed_pack="minimal")
    st_del.setdefault("economy", {})["cash"] = 10000
    st_del.setdefault("player", {})["district"] = "harbor"  # metropolis: has black_market
    rdel = buy_item(st_del, "compact_pistol", prefer="bag", delivery="dead_drop")
    assert bool(rdel.get("ok")) and rdel.get("placed_to") == "delivery_pending"
    assert any(isinstance(ev, dict) and ev.get("event_type") == "delivery_drop" for ev in (st_del.get("pending_events") or []))
    assert isinstance(rdel.get("drop_district", ""), str)
    # Delivery spawn objects can carry trap flags (decoy/sting_on_pickup) deterministically.
    from engine.world.timers import update_timers
    # Jump time forward. We need two timer ticks:
    # - first tick triggers delivery_drop -> pending_deliveries
    # - second tick materializes pending_deliveries -> nearby_items (+ scene start)
    st_del.setdefault("meta", {}).update({"day": 1, "time_min": 9 * 60})
    st_del.setdefault("player", {})["district"] = str(rdel.get("drop_district") or st_del.get("player", {}).get("district", "harbor"))
    update_timers(st_del, {"action_type": "instant", "domain": "other", "instant_minutes": 60})
    update_timers(st_del, {"action_type": "instant", "domain": "other", "instant_minutes": 1})
    nb = (st_del.get("world", {}) or {}).get("nearby_items", []) or []
    # If spawned, it should include the flags.
    if nb and isinstance(nb[0], dict):
        assert "decoy" in nb[0] and "sting_on_pickup" in nb[0]
    # Scene should start when delivery materializes in current drop district.
    sc = st_del.get("active_scene")
    assert isinstance(sc, dict) and sc.get("scene_type") == "drop_pickup" and sc.get("phase") == "spot_package"

    # Dead NPC guard: targeting should not select dead NPCs.
    from engine.npc.npc_targeting import apply_npc_targeting

    st_dead = initialize_state({"name": "DeadNPC", "location": "london", "year": "2025"}, seed_pack="minimal")
    st_dead.setdefault("npcs", {})["Bob"] = {"name": "Bob", "alive": False, "hp": 0, "current_location": "london", "home_location": "london"}
    ctx_dead = {"domain": "social", "normalized_input": "talk bob", "targets": ["Bob"]}
    apply_npc_targeting(st_dead, ctx_dead, "talk bob")
    assert ctx_dead.get("targets") == []

    # Effects stacking + expiry: should expire after timers tick.
    from engine.systems.effects import add_effect
    from engine.world.timers import update_timers

    st_eff = initialize_state({"name": "Effects", "location": "london", "year": "2025"}, seed_pack="minimal")
    st_eff.setdefault("meta", {}).update({"day": 1, "time_min": 8 * 60, "turn": 1})
    player = st_eff.setdefault("player", {})
    add_effect(st_eff, target=player, effect_id="bleeding", kind="bleed", duration_min=1, stacks=1, stacking="stack", source="test")
    add_effect(st_eff, target=player, effect_id="bleeding", kind="bleed", duration_min=1, stacks=1, stacking="stack", source="test")
    effs0 = (st_eff.get("player", {}) or {}).get("effects", []) or []
    assert isinstance(effs0, list) and any(isinstance(e, dict) and e.get("id") == "bleeding" and int(e.get("stacks", 0) or 0) >= 2 for e in effs0)
    update_timers(st_eff, {"action_type": "instant", "instant_minutes": 2})
    effs1 = (st_eff.get("player", {}) or {}).get("effects", []) or []
    assert not any(isinstance(e, dict) and e.get("id") == "bleeding" for e in effs1)

    # Social diffusion budget: if budget is zero, hops should be throttled.
    st_sd = initialize_state({"name": "SocDiff", "location": "london", "year": "2025"}, seed_pack="minimal")
    st_sd.setdefault("meta", {}).update({"day": 1, "time_min": 8 * 60, "turn": 1})
    st_sd.setdefault("world", {})["social_diffusion"] = {"max_hops_per_day": 0, "max_hops_per_turn": 0, "used_today": 0, "used_turn": 0, "day": 1, "turn": 1}
    st_sd.setdefault("npcs", {})["A"] = {"name": "A", "alive": True, "hp": 100, "current_location": "london", "home_location": "london"}
    st_sd.setdefault("npcs", {})["B"] = {"name": "B", "alive": True, "hp": 100, "current_location": "london", "home_location": "london"}
    st_sd.setdefault("pending_events", []).append(
        {
            "event_type": "social_diffusion_hop",
            "due_day": 1,
            "due_time": 8 * 60,
            "triggered": False,
            "payload": {"from_npc": "A", "to_npc": "B", "rumor": "player hack rumor", "category": "hack", "hop": 0},
        }
    )
    update_timers(st_sd, {"action_type": "instant", "instant_minutes": 1})
    # No new hops should have been queued.
    assert not any(isinstance(e, dict) and e.get("event_type") == "social_diffusion_hop" and not bool(e.get("triggered")) for e in (st_sd.get("pending_events") or []))

    # Ripple contacts gate: contacts + origin_faction should eventually surface (indirect leak) rather than drop.
    st_rp = initialize_state({"name": "RippleGate", "location": "london", "year": "2025"}, seed_pack="minimal")
    st_rp.setdefault("meta", {}).update({"day": 1, "time_min": 8 * 60, "turn": 1})
    st_rp.setdefault("world", {}).setdefault("contacts", {})["CorpContact"] = {"name": "CorpContact", "affiliation": "corporate", "trust": 40}
    st_rp.setdefault("active_ripples", []).append(
        {
            "kind": "test",
            "text": "[Test] contact police ripple",
            "triggered_day": 1,
            "surface_day": 1,
            "surface_time": 8 * 60,
            "surfaced": False,
            "propagation": "contacts",
            "origin_location": "london",
            "origin_faction": "police",
            "witnesses": [],
            "surface_attempts": 0,
        }
    )
    from engine.world.timers import update_timers as _ut

    # Attempt 1: reschedule
    _ut(st_rp, {"action_type": "instant", "instant_minutes": 1})
    # Jump to next day 08:00 twice to allow surface_attempts to accumulate.
    st_rp["meta"]["day"] = 2
    st_rp["meta"]["time_min"] = 8 * 60
    st_rp["meta"]["turn"] = 2
    _ut(st_rp, {"action_type": "instant", "instant_minutes": 1})
    st_rp["meta"]["day"] = 3
    st_rp["meta"]["time_min"] = 8 * 60
    st_rp["meta"]["turn"] = 3
    _ut(st_rp, {"action_type": "instant", "instant_minutes": 1})
    surfaced = st_rp.get("surfacing_ripples_this_turn", []) or []
    assert any(isinstance(r, dict) and "[Test]" in str(r.get("text", "")) and not bool(r.get("dropped_by_propagation")) for r in surfaced)

    # Scheduler cap drain: cap=3 should defer overflow and drain across subsequent turns (no loss).
    st_cap = initialize_state({"name": "CapDrain", "location": "london", "year": "2025"}, seed_pack="minimal")
    st_cap.setdefault("meta", {}).update({"day": 1, "time_min": 8 * 60, "turn": 1})
    pe = st_cap.setdefault("pending_events", [])
    for i in range(10):
        pe.append(
            {
                "event_type": "informant_tip",  # safe no-op if payload empty
                "due_day": 1,
                "due_time": 8 * 60,
                "triggered": False,
                "payload": {"kind": "test", "i": i},
            }
        )
    from engine.world.timers import update_timers as _ut2

    _ut2(st_cap, {"action_type": "instant", "instant_minutes": 1})
    tr1 = st_cap.get("triggered_events_this_turn", []) or []
    assert len(tr1) <= 3
    # Advance turn; keep time due.
    st_cap["meta"]["turn"] = 2
    _ut2(st_cap, {"action_type": "instant", "instant_minutes": 1})
    tr2 = st_cap.get("triggered_events_this_turn", []) or []
    assert len(tr2) <= 3
    st_cap["meta"]["turn"] = 3
    _ut2(st_cap, {"action_type": "instant", "instant_minutes": 1})
    tr3 = st_cap.get("triggered_events_this_turn", []) or []
    assert len(tr3) <= 3
    # Eventually, all should be marked triggered after enough turns.
    for t in range(4, 8):
        st_cap["meta"]["turn"] = t
        _ut2(st_cap, {"action_type": "instant", "instant_minutes": 1})
    assert all(bool(ev.get("triggered")) for ev in (st_cap.get("pending_events") or []) if isinstance(ev, dict) and ev.get("event_type") == "informant_tip")

    # Ripple dedup: volatile meta keys should not defeat dedup.
    from engine.social.ripple_queue import enqueue_ripple

    st_dedup = initialize_state({"name": "RippleDedup", "location": "london", "year": "2025"}, seed_pack="minimal")
    st_dedup["active_ripples"] = []
    enqueue_ripple(
        st_dedup,
        {
            "kind": "npc_offer",
            "propagation": "contacts",
            "origin_location": "london",
            "origin_faction": "black_market",
            "text": "[Offer] Fixer offers service",
            "meta": {"npc": "FixerA", "service": "sell_info", "expires_day": 2},
            "surfaced": False,
        },
    )
    enqueue_ripple(
        st_dedup,
        {
            "kind": "npc_offer",
            "propagation": "contacts",
            "origin_location": "london",
            "origin_faction": "black_market",
            "text": "[Offer] Fixer offers service",
            "meta": {"npc": "FixerA", "service": "sell_info", "expires_day": 3},
            "surfaced": False,
        },
    )
    ar = st_dedup.get("active_ripples", []) or []
    assert isinstance(ar, list) and len(ar) == 1

    # Different stable meta should not dedup.
    enqueue_ripple(
        st_dedup,
        {
            "kind": "npc_offer",
            "propagation": "contacts",
            "origin_location": "london",
            "origin_faction": "black_market",
            "text": "[Offer] Fixer offers service",
            "meta": {"npc": "FixerB", "service": "sell_info"},
            "surfaced": False,
        },
    )
    ar2 = st_dedup.get("active_ripples", []) or []
    assert isinstance(ar2, list) and len(ar2) == 2

    # Observability: swallowed exceptions should be recorded in meta.errors.
    # Force a deterministic failure by temporarily patching cache_sim_time to raise.
    st_err = initialize_state({"name": "ErrVerify", "location": "london", "year": "2025"}, seed_pack="minimal")
    st_err.setdefault("meta", {}).update({"day": 1, "time_min": 8 * 60, "turn": 1})
    from engine.world.timers import update_timers as _ut_err
    import engine.world.time_model as _tm

    _orig_cache = _tm.cache_sim_time
    try:
        def _boom(_state):
            raise RuntimeError("test boom")

        _tm.cache_sim_time = _boom
        _ut_err(st_err, {"action_type": "instant", "instant_minutes": 1})
    finally:
        _tm.cache_sim_time = _orig_cache

    errs = (st_err.get("meta", {}) or {}).get("errors", {}) or {}
    assert isinstance(errs, dict) and int(errs.get("timers.cache_sim_time", 0) or 0) >= 1

    # Travel district normalization: after travel, player.district must be valid for the destination.
    from engine.world.districts import is_valid_district
    from engine.world.world import world_tick

    st_dist = initialize_state({"name": "DistVerify", "location": "london", "year": "2025"}, seed_pack="minimal")
    st_dist.setdefault("player", {})["district"] = "nonexistent_district"
    ctx_tr = {"action_type": "travel", "travel_destination": "tokyo", "travel_minutes": 30, "time_breakdown": []}
    world_tick(st_dist, ctx_tr)
    did = str((st_dist.get("player", {}) or {}).get("district", "") or "").strip().lower()
    loc2 = str((st_dist.get("player", {}) or {}).get("location", "") or "").strip().lower()
    assert bool(did) and is_valid_district(st_dist, loc2, did)

    # Delivery fairness: ready matching delivery beyond index 40 must spawn.
    st_df = initialize_state({"name": "DelFair", "location": "new york", "year": "2025"}, seed_pack="minimal")
    st_df.setdefault("meta", {}).update({"day": 1, "time_min": 9 * 60, "turn": 1})
    st_df.setdefault("player", {})["district"] = "harbor"
    pd = st_df.setdefault("world", {}).setdefault("pending_deliveries", [])
    for i in range(55):
        pd.append(
            {
                "delivery_id": f"X{i}",
                "location": "new york",
                "drop_district": "downtown",
                "ready_day": 1,
                "ready_time": 9 * 60,
                "item_id": "burner_phone",
                "item_name": "burner_phone",
                "delivered": False,
                "expired": False,
            }
        )
    pd.append(
        {
            "delivery_id": "MATCH55",
            "location": "new york",
            "drop_district": "harbor",
            "ready_day": 1,
            "ready_time": 9 * 60,
            "item_id": "burner_phone",
            "item_name": "burner_phone",
            "delivered": False,
            "expired": False,
        }
    )
    from engine.world.timers import update_timers as _ut_df

    _ut_df(st_df, {"action_type": "instant", "instant_minutes": 1})
    nb2 = (st_df.get("world", {}) or {}).get("nearby_items", []) or []
    assert any(isinstance(x, dict) and str(x.get("delivery_id", "")) == "MATCH55" for x in nb2)

    # Contacts authority: local snapshot must not override global contact entry on travel.
    st_ca = initialize_state({"name": "ContactAuth", "location": "london", "year": "2025"}, seed_pack="minimal")
    st_ca.setdefault("world", {}).setdefault("contacts", {})["AgentX"] = {"name": "AgentX", "is_contact": True, "marker": "KEEP", "home_location": "london"}
    st_ca.setdefault("world", {}).setdefault("locations", {}).setdefault("tokyo", {})["npcs"] = {"AgentX": {"name": "AgentX", "is_contact": True}}
    world_tick(st_ca, {"action_type": "travel", "travel_destination": "tokyo", "travel_minutes": 30, "time_breakdown": []})
    assert str((st_ca.get("npcs", {}) or {}).get("AgentX", {}).get("marker", "")) == "KEEP"

    # Inventory clamp: negative/non-int quantities should normalize to non-negative ints.
    st_iq = initialize_state({"name": "InvClamp", "location": "london", "year": "2025"}, seed_pack="minimal")
    st_iq.setdefault("inventory", {})["item_quantities"] = {"ammo_9mm": -5, "weird": "3", "huge": 999999999}
    from engine.player.inventory import update_inventory

    update_inventory(st_iq, {})
    iq2 = (st_iq.get("inventory", {}) or {}).get("item_quantities", {}) or {}
    assert isinstance(iq2, dict)
    assert int(iq2.get("ammo_9mm", 0) or 0) >= 0
    assert int(iq2.get("weird", 0) or 0) == 3
    assert int(iq2.get("huge", 0) or 0) <= 99999

    # Scheduler starvation: due ripple bookkeeping should advance even when cap is saturated by events.
    st_starve = initialize_state({"name": "Starve", "location": "london", "year": "2025"}, seed_pack="minimal")
    st_starve.setdefault("meta", {}).update({"day": 1, "time_min": 8 * 60, "turn": 1})
    st_starve.setdefault("player", {})["location"] = "london"
    for i in range(6):
        st_starve.setdefault("pending_events", []).append(
            {"event_type": "informant_tip", "due_day": 1, "due_time": 8 * 60, "triggered": False, "payload": {"i": i}}
        )
    st_starve.setdefault("active_ripples", []).append(
        {
            "kind": "test",
            "text": "[Starve] unreachable ripple",
            "surface_day": 1,
            "surface_time": 8 * 60,
            "surfaced": False,
            "propagation": "local_witness",
            "origin_location": "tokyo",
            "surface_attempts": 0,
        }
    )
    from engine.world.timers import update_timers as _ut_s

    for t in range(1, 6):
        st_starve["meta"]["turn"] = t
        _ut_s(st_starve, {"action_type": "instant", "instant_minutes": 1})
    rp0 = (st_starve.get("active_ripples", []) or [None])[0]
    assert isinstance(rp0, dict) and int(rp0.get("surface_attempts", 0) or 0) >= 1

    # Intent v2 plan execution: select_best_step should skip failing step0 and choose step1.
    from engine.core.action_intent import merge_intent_into_action_ctx, select_best_step

    st_plan = initialize_state({"name": "IntentPlan", "location": "london", "year": "2025"}, seed_pack="minimal")
    st_plan.setdefault("economy", {})["cash"] = 0
    action_ctx_plan = parse_action_intent("test plan")
    intent_v2 = {
        "version": 2,
        "confidence": 0.9,
        "player_goal": "test",
        "context_assumptions": [],
        "plan": {
            "plan_id": "p_test",
            "steps": [
                {
                    "step_id": "s0",
                    "label": "expensive",
                    "action_type": "instant",
                    "domain": "other",
                    "preconditions": [{"kind": "money_gte", "op": "gte", "value": 10}],
                },
                {
                    "step_id": "s1",
                    "label": "cheap",
                    "action_type": "instant",
                    "domain": "other",
                    "preconditions": [{"kind": "money_gte", "op": "gte", "value": 0}],
                },
            ],
        },
        "safety": {"refuse": False, "refuse_reason": ""},
    }
    merge_intent_into_action_ctx(action_ctx_plan, intent_v2)
    sid = select_best_step(action_ctx_plan, st_plan)
    assert sid == "s1"

    # Intent v2 plan execution: skill_gte should gate steps based on state.skills[*].level.
    st_skill = initialize_state({"name": "IntentPlanSkill", "location": "london", "year": "2025"}, seed_pack="minimal")
    st_skill.setdefault("skills", {}).setdefault("hacking", {})["level"] = 1
    action_ctx_skill = parse_action_intent("test plan skill")
    intent_v2_skill = {
        "version": 2,
        "confidence": 0.9,
        "player_goal": "test",
        "context_assumptions": [],
        "plan": {
            "plan_id": "p_skill",
            "steps": [
                {
                    "step_id": "s0",
                    "label": "needs_hacking3",
                    "action_type": "instant",
                    "domain": "hacking",
                    "preconditions": [{"kind": "skill_gte", "op": "gte", "value": {"skill": "hacking", "level": 3}}],
                },
                {
                    "step_id": "s1",
                    "label": "fallback",
                    "action_type": "instant",
                    "domain": "other",
                    "preconditions": [{"kind": "skill_gte", "op": "gte", "value": {"skill": "hacking", "level": 1}}],
                },
            ],
        },
        "safety": {"refuse": False, "refuse_reason": ""},
    }
    merge_intent_into_action_ctx(action_ctx_skill, intent_v2_skill)
    sid2 = select_best_step(action_ctx_skill, st_skill)
    assert sid2 == "s1"

    # MEMORY_HASH v2: JSON inside <MEMORY_HASH> should apply npc memories (bounded + clamped).
    from ai.parser import apply_memory_hash_to_state, parse_memory_hash

    st_mh = initialize_state({"name": "MemHashV2", "location": "london", "year": "2025"}, seed_pack="minimal")
    st_mh.setdefault("npcs", {})["AgentX"] = {"name": "AgentX", "alive": True, "memories": []}
    mh_text = (
        "<MEMORY_HASH>{"
        "\"version\":2,"
        "\"npc_memory_deltas\":[{"
        "\"npc_id\":\"AgentX\","
        "\"memories_add\":[{\"memory_id\":\"m1\",\"kind\":\"favor\",\"summary\":\"Player paid the debt.\",\"importance\":150,\"valence\":200,\"confidence\":2.0}],"
        "\"memories_update\":[]"
        "}]"
        "}</MEMORY_HASH>"
    )
    mh = parse_memory_hash(mh_text)
    apply_memory_hash_to_state(st_mh, mh)
    mems = (st_mh.get("npcs", {}) or {}).get("AgentX", {}).get("memories", [])
    assert isinstance(mems, list) and mems
    m0 = mems[0]
    assert isinstance(m0, dict) and m0.get("memory_id") == "m1"
    assert 0 <= int(m0.get("importance", 0) or 0) <= 100
    assert -100 <= int(m0.get("valence", 0) or 0) <= 100
    assert 0.0 <= float(m0.get("confidence", 0.0) or 0.0) <= 1.0

    # NPC memory decay + consolidation: high-importance memories older than 3 days become beliefs.
    from engine.npc.memory import process_memory_decay

    st_md = initialize_state({"name": "MemDecay", "location": "london", "year": "2025"}, seed_pack="minimal")
    st_md.setdefault("meta", {}).update({"day": 10, "time_min": 8 * 60})
    st_md.setdefault("npcs", {})["AgentY"] = {
        "name": "AgentY",
        "alive": True,
        "memories": [
            {"memory_id": "hi1", "kind": "betrayal", "summary": "Player sold them out.", "when": {"day": 6, "time_min": 0}, "importance": 95, "valence": -90, "confidence": 1.0, "tags": []},
            {"memory_id": "lo1", "kind": "conversation", "summary": "Small talk.", "when": {"day": 9, "time_min": 0}, "importance": 5, "valence": 20, "confidence": 1.0, "tags": []},
        ],
    }
    counts = process_memory_decay(st_md)
    assert isinstance(counts, dict) and int(counts.get("consolidated", 0) or 0) >= 1
    npc_y = (st_md.get("npcs", {}) or {}).get("AgentY", {})
    assert isinstance(npc_y, dict)
    assert isinstance(npc_y.get("belief_tags", []), list) and len(npc_y.get("belief_tags", [])) >= 1
    # low-importance memory should drop after decay
    assert all(isinstance(m, dict) and str(m.get("memory_id", "")) != "lo1" for m in (npc_y.get("memories", []) or []))

    # Belief tags -> social modifiers should affect roll package for social conflict.
    st_sm = initialize_state({"name": "SocialMods", "location": "london", "year": "2025"}, seed_pack="minimal")
    # Ensure shared language so social roll isn't hard-gated by language barrier.
    st_sm.setdefault("player", {})["language"] = "en"
    st_sm.setdefault("player", {}).setdefault("languages", {})["en"] = 90
    st_sm.setdefault("npcs", {})["GrudgeNPC"] = {"name": "GrudgeNPC", "alive": True, "belief_tags": ["Deep_Grudge"], "belief_summary": {"suspicion": 90, "respect": 10}}
    from engine.core.modifiers import compute_roll_package

    pkg = compute_roll_package(st_sm, {"domain": "social", "action_type": "talk", "social_mode": "conflict", "targets": ["GrudgeNPC"], "trained": True})
    mods = pkg.get("mods", []) or []
    assert any(isinstance(m, (list, tuple)) and "NPC beliefs" in str(m[0]) for m in mods)

    # Anchor layer: Deep_Grudge clamps max_trust=30 and min_suspicion=50.
    from engine.npc.memory import get_npc_social_modifiers

    st_anchor = initialize_state({"name": "AnchorClamp", "location": "london", "year": "2025"}, seed_pack="minimal")
    st_anchor.setdefault("npcs", {})["A"] = {"name": "A", "alive": True, "belief_tags": ["Deep_Grudge"], "belief_summary": {"suspicion": 0, "respect": 90}}
    sm2 = get_npc_social_modifiers(st_anchor, "A")
    assert int(sm2.get("trust", 0) or 0) <= 30
    assert int(sm2.get("suspicion", 0) or 0) >= 50

    # Social Decay to Anchor: apply_social_decay should drag fields toward anchor bounds.
    from engine.core.modifiers import apply_social_decay
    st_sd = initialize_state({"name": "SocialDecay", "location": "london", "year": "2025"}, seed_pack="minimal")
    st_sd.setdefault("npcs", {})["D"] = {
        "name": "D",
        "alive": True,
        "belief_tags": ["Deep_Grudge"],
        "trust": 100,
        "fear": 0,
        "belief_summary": {"suspicion": 0, "respect": 90},
    }
    d1 = apply_social_decay(st_sd, "D")
    assert isinstance(d1, dict)
    npc_d = (st_sd.get("npcs", {}) or {}).get("D", {})
    assert isinstance(npc_d, dict)
    assert int(npc_d.get("trust", 0) or 0) <= 80  # moved toward max_trust=30
    assert int((npc_d.get("belief_summary", {}) or {}).get("suspicion", 0) or 0) >= 18  # moved toward min_suspicion=50

    # Social triggers schedule pending ripple events (countdown); one-shot while armed.
    from engine.npc.memory import get_narrative_anchor_context, is_trigger_condition_met
    from engine.npc.npcs import check_social_triggers, process_pending_events

    st_tr = initialize_state({"name": "TriggerTest", "location": "london", "year": "2025"}, seed_pack="minimal")
    st_tr.setdefault("npcs", {})["T"] = {
        "name": "T",
        "alive": True,
        "belief_tags": ["Blackmail_Leverage"],
        "trust": 0,
        "fear": 80,
        "belief_summary": {"suspicion": 60, "respect": -40},
    }
    fired1 = check_social_triggers(st_tr, "T")
    assert isinstance(fired1, list) and fired1
    pe_tr = st_tr.get("pending_events", []) or []
    assert isinstance(pe_tr, list) and any(
        isinstance(x, dict) and str(x.get("source_npc", "")) == "T" and "turns_to_trigger" in x for x in pe_tr
    )
    ctx_t = get_narrative_anchor_context(st_tr, "T")
    assert isinstance(ctx_t, str) and "[FORESHADOWING]" in ctx_t
    fired2 = check_social_triggers(st_tr, "T")
    assert fired2 == []

    # BETRAYAL_RISK: pending event defuses if social state improves before countdown completes.
    st_def = initialize_state({"name": "DefuseRipple", "location": "london", "year": "2025"}, seed_pack="minimal")
    st_def.setdefault("npcs", {})["Brutus"] = {
        "name": "Brutus",
        "alive": True,
        "trust": 5,
        "fear": 20,
        "belief_summary": {"suspicion": 95, "respect": 50},
    }
    assert is_trigger_condition_met(st_def, "Brutus", "BETRAYAL_RISK") is True
    fired_b = check_social_triggers(st_def, "Brutus")
    assert "BETRAYAL_RISK" in fired_b
    assert any(
        isinstance(x, dict)
        and x.get("source_npc") == "Brutus"
        and x.get("type") == "BETRAYAL_RISK"
        and "turns_to_trigger" in x
        for x in (st_def.get("pending_events") or [])
    )
    # Cheat: rebuild trust / lower suspicion so threshold no longer holds.
    st_def["npcs"]["Brutus"]["trust"] = 95
    st_def["npcs"]["Brutus"]["belief_summary"]["suspicion"] = 20
    assert is_trigger_condition_met(st_def, "Brutus", "BETRAYAL_RISK") is False
    process_pending_events(st_def)
    pe_brutus = [
        x
        for x in (st_def.get("pending_events") or [])
        if isinstance(x, dict) and x.get("source_npc") == "Brutus" and "turns_to_trigger" in x
    ]
    assert pe_brutus == []
    we_def = st_def.get("world_events", []) or []
    assert any(isinstance(x, dict) and x.get("kind") == "ABORTED_EVENT" and x.get("type") == "BETRAYAL_RISK" for x in we_def)
    notes_def = st_def.get("world_notes", []) or []
    assert any(isinstance(n, str) and "[Ripple Defused]" in n for n in notes_def)
    at_b = (st_def.get("npcs", {}) or {}).get("Brutus", {}).get("active_triggers", {}) or {}
    assert at_b.get("BETRAYAL_RISK") is False

    # Gossip protocol: deterministic spread from grudge/suspicion source to same-faction peer.
    from engine.npc.memory import get_narrative_anchor_context
    from engine.npc.npc_rumor_system import propagate_reputation

    st_go = initialize_state({"name": "GossipProto", "location": "london", "year": "2025"}, seed_pack="minimal")
    st_go.setdefault("npcs", {})["G_A"] = {
        "name": "G_A",
        "alive": True,
        "hp": 100,
        "affiliation": "corporate",
        "current_location": "london",
        "belief_tags": ["Deep_Grudge"],
        "belief_summary": {"suspicion": 50, "respect": 50},
    }
    st_go.setdefault("npcs", {})["G_B"] = {
        "name": "G_B",
        "alive": True,
        "hp": 100,
        "affiliation": "corporate",
        "current_location": "london",
        "belief_summary": {"suspicion": 40, "respect": 50},
    }
    sus0 = int((st_go["npcs"]["G_B"].get("belief_summary") or {}).get("suspicion", 0) or 0)
    gossip_hit_turn: int | None = None
    for t in range(48):
        st_go.setdefault("meta", {})["turn"] = t
        n_sp = propagate_reputation(st_go)
        if n_sp > 0:
            gossip_hit_turn = t
            break
    assert gossip_hit_turn is not None
    sus1 = int((st_go["npcs"]["G_B"].get("belief_summary") or {}).get("suspicion", 0) or 0)
    assert sus1 > sus0
    notes_g = st_go.get("world_notes", []) or []
    assert any(isinstance(x, str) and x.startswith("[Gossip] Reputation spread from G_A to G_B") for x in notes_g)
    ctx_gb = get_narrative_anchor_context(st_go, "G_B")
    assert isinstance(ctx_gb, str) and "[RUMOR]" in ctx_gb

    # REPORTING_RISK / snitch: trace delta +20 without disguise, +5 with active disguise.
    from engine.npc.npcs import process_pending_events
    from engine.systems.disguise import ensure_disguise

    st_sn = initialize_state({"name": "SnitchTrace", "location": "london", "year": "2025"}, seed_pack="minimal")
    st_sn["trace"] = {"trace_pct": 10, "trace_status": "Ghost"}
    st_sn.setdefault("npcs", {})["Sn"] = {
        "name": "Sn",
        "alive": True,
        "hp": 100,
        "belief_summary": {"suspicion": 90, "respect": 50},
        "active_triggers": {"REPORTING_RISK": True},
    }
    st_sn.setdefault("pending_events", []).append(
        {
            "id": "se:Sn:REPORTING_RISK:0",
            "type": "REPORTING_RISK",
            "source_npc": "Sn",
            "turns_to_trigger": 0,
            "payload": {"effect": "file_report", "trigger": "REPORTING_RISK"},
        }
    )
    process_pending_events(st_sn)
    assert int((st_sn.get("trace", {}) or {}).get("trace_pct", 0) or 0) == 30
    assert any(isinstance(x, dict) and x.get("kind") == "REPORT_FILED" for x in (st_sn.get("world_events", []) or []))
    notes_sn = st_sn.get("world_notes", []) or []
    assert any(isinstance(x, str) and x.startswith("[Snitch]") for x in notes_sn)
    ctx_rep = get_narrative_anchor_context(st_sn, "Sn")
    assert isinstance(ctx_rep, str) and "[REPORTING_RISK]" in ctx_rep

    st_sd = initialize_state({"name": "SnitchDisguise", "location": "london", "year": "2025"}, seed_pack="minimal")
    st_sd["trace"] = {"trace_pct": 10, "trace_status": "Ghost"}
    ensure_disguise(st_sd)["active"] = True
    st_sd.setdefault("npcs", {})["Sn2"] = {
        "name": "Sn2",
        "alive": True,
        "hp": 100,
        "belief_summary": {"suspicion": 90, "respect": 50},
        "active_triggers": {"REPORTING_RISK": True},
    }
    st_sd.setdefault("pending_events", []).append(
        {
            "id": "se:Sn2:REPORTING_RISK:0",
            "type": "REPORTING_RISK",
            "source_npc": "Sn2",
            "turns_to_trigger": 0,
            "payload": {"effect": "file_report", "trigger": "REPORTING_RISK"},
        }
    )
    process_pending_events(st_sd)
    assert int((st_sd.get("trace", {}) or {}).get("trace_pct", 0) or 0) == 15

    # Reporting plan defuses when belief_summary.suspicion drops below 80.
    st_rd = initialize_state({"name": "ReportDefuse", "location": "london", "year": "2025"}, seed_pack="minimal")
    st_rd.setdefault("npcs", {})["Sn3"] = {
        "name": "Sn3",
        "alive": True,
        "hp": 100,
        "belief_summary": {"suspicion": 75, "respect": 50},
        "active_triggers": {"REPORTING_RISK": True},
    }
    st_rd.setdefault("pending_events", []).append(
        {
            "id": "se:Sn3:REPORTING_RISK:1",
            "type": "REPORTING_RISK",
            "source_npc": "Sn3",
            "turns_to_trigger": 2,
            "payload": {"effect": "file_report", "trigger": "REPORTING_RISK"},
        }
    )
    process_pending_events(st_rd)
    pe3 = st_rd.get("pending_events", []) or []
    assert not any(
        isinstance(x, dict) and x.get("type") == "REPORTING_RISK" and x.get("source_npc") == "Sn3" for x in pe3
    )
    assert any(
        isinstance(x, str) and "below 80" in x and "Sn3" in x for x in (st_rd.get("world_notes", []) or [])
    )

    # Trace tier friction: Lockdown scales travel minutes; HUD label uses security tier names.
    from engine.core.trace import apply_trace_travel_friction, fmt_trace_monitor_ui, get_trace_tier
    from engine.world.timers import update_timers

    st_tf0 = initialize_state({"name": "TraceTier0", "location": "london", "year": "2025"}, seed_pack="minimal")
    st_tf0["trace"] = {"trace_pct": 0, "trace_status": "Ghost"}
    assert get_trace_tier(st_tf0)["tier_id"] == "Ghost"
    assert apply_trace_travel_friction(st_tf0, 50) == (50, False)

    st_tf80 = initialize_state({"name": "TraceTier80", "location": "london", "year": "2025"}, seed_pack="minimal")
    st_tf80["trace"] = {"trace_pct": 80, "trace_status": "Manhunt"}
    assert get_trace_tier(st_tf80)["tier_id"] == "Lockdown"
    m80, ap80 = apply_trace_travel_friction(st_tf80, 50)
    assert m80 == 100 and ap80 is True
    ui80 = fmt_trace_monitor_ui(st_tf80)
    assert "[Lockdown]" in ui80 and "80%" in ui80

    st_trv0 = initialize_state({"name": "TravelFriction0", "location": "london", "year": "2025"}, seed_pack="minimal")
    st_trv0.setdefault("meta", {}).update({"day": 1, "time_min": 480, "turn": 0})
    st_trv0["trace"] = {"trace_pct": 0, "trace_status": "Ghost"}
    t0 = int(st_trv0["meta"]["time_min"])
    update_timers(st_trv0, {"action_type": "travel", "travel_minutes": 100})
    adv0 = int(st_trv0["meta"]["time_min"]) - t0

    st_trv1 = initialize_state({"name": "TravelFriction80", "location": "london", "year": "2025"}, seed_pack="minimal")
    st_trv1.setdefault("meta", {}).update({"day": 1, "time_min": 480, "turn": 0})
    st_trv1["trace"] = {"trace_pct": 80, "trace_status": "Manhunt"}
    t1 = int(st_trv1["meta"]["time_min"])
    update_timers(st_trv1, {"action_type": "travel", "travel_minutes": 100})
    adv1 = int(st_trv1["meta"]["time_min"]) - t1
    assert adv1 > adv0
    # Lockdown doubles the pre-modifier travel_minutes bucket (100 → 200) before other shared modifiers.
    assert (adv1 - adv0) >= 95
    assert any("[Security] Travel friction increased due to high Trace." in str(x) for x in (st_trv1.get("world_notes", []) or []))

    from engine.systems.scenes import advance_scene

    r1 = advance_scene(st_del, {"scene_action": "approach"})
    assert bool(r1.get("ok")) and r1.get("phase_before") == "spot_package" and r1.get("phase_after") == "approach"
    # WAIT twice OK, third should fail and not consume input.
    w1 = advance_scene(st_del, {"scene_action": "wait"})
    assert bool(w1.get("ok")) and w1.get("phase_after") == "approach"
    w2 = advance_scene(st_del, {"scene_action": "wait"})
    assert bool(w2.get("ok")) and w2.get("phase_after") == "approach"
    w3 = advance_scene(st_del, {"scene_action": "wait"})
    assert bool(w3.get("ok")) is False and w3.get("reason") == "wait_limit_reached"
    # TAKE resolves (decoy or normal); must end the scene.
    t1 = advance_scene(st_del, {"scene_action": "take"})
    assert bool(t1.get("ok")) and bool(t1.get("ended")) is True
    assert st_del.get("active_scene") is None

    # Courier deliveries create a delayed paper trail ping.
    st_pt = initialize_state({"name": "PaperTrail", "location": "new york", "year": "2025"}, seed_pack="minimal")
    st_pt.setdefault("economy", {})["cash"] = 20000
    st_pt.setdefault("player", {})["district"] = "harbor"  # has black_market
    r_pt = buy_item(st_pt, "compact_pistol", prefer="bag", delivery="courier")
    assert bool(r_pt.get("ok"))
    assert any(isinstance(ev, dict) and ev.get("event_type") == "paper_trail_ping" for ev in (st_pt.get("pending_events") or []))

    # SHOP polish: sold out is deterministic under high scarcity.
    st_so = initialize_state({"name": "SoldOutVerify", "location": "tokyo", "year": "2025"}, seed_pack="minimal")
    st_so.setdefault("meta", {}).update({"day": 7, "time_min": 8 * 60})
    # Ensure location slot exists with tags/npcs (simulate first visit preset applied).
    st_so.setdefault("world", {}).setdefault("locations", {}).setdefault("tokyo", {}).setdefault("tags", ["surveillance_high"])
    st_so["world"]["locations"]["tokyo"].setdefault("npcs", {"Fixer_Suzume": {"role": "fixer"}})
    st_so.setdefault("world", {}).setdefault("nearby_items", [])
    # Force local market scarcity high to trigger sold-out behavior for electronics.
    st_so["economy"].setdefault("market", {}).setdefault("electronics", {})["scarcity"] = 95
    st_so["economy"]["market"]["electronics"]["price_idx"] = 120
    qs = list_shop_quotes(st_so, limit=12, role="fixer")
    assert isinstance(qs, list) and len(qs) >= 1
    assert any(q.available is False for q in qs)
    sold = next((q for q in qs if q.available is False), None)
    if sold is not None:
        st_so["economy"]["cash"] = 5000
        r = buy_item(st_so, sold.item_id, prefer="bag")
        assert bool(r.get("ok")) is False and r.get("reason") == "sold_out"

    # District police presence: can refuse contraband outright and increases weapons sold-out.
    st_dc = initialize_state({"name": "DistrictContraband", "location": "tokyo", "year": "2025"}, seed_pack="minimal")
    st_dc.setdefault("economy", {})["cash"] = 9000
    st_dc.setdefault("player", {})["district"] = "finance"  # police_presence=5 in east_asian templates
    rd = buy_item(st_dc, "compact_pistol")
    assert bool(rd.get("ok")) is False
    assert rd.get("reason") in ("sold_out", "district_refuses_contraband")

    # Permit as real document: if carried, police check payload should include permit_doc.
    st_p = initialize_state({"name": "PermitDoc", "location": "new york", "year": "2025"}, seed_pack="minimal")
    st_p.setdefault("player", {})["district"] = "port"  # has black_market in western templates
    st_p.setdefault("inventory", {}).setdefault("bag_contents", []).append("compact_pistol")
    st_p.setdefault("inventory", {}).setdefault("pocket_contents", []).append("weapon_permit_usa")
    from engine.social.police_check import schedule_weapon_check

    schedule_weapon_check(st_p, weapon_ids=["compact_pistol"], reason="test")
    pe = st_p.get("pending_events", []) or []
    assert any(isinstance(ev, dict) and ev.get("event_type") == "police_weapon_check" for ev in pe)
    ev0 = [ev for ev in pe if isinstance(ev, dict) and ev.get("event_type") == "police_weapon_check"][0]
    pd = (ev0.get("payload", {}) or {}).get("permit_doc", {})
    assert isinstance(pd, dict) and bool(pd.get("permit_present", False)) is True

    # Police stop is now a playable scene (police_weapon_check -> police_stop).
    from engine.world.timers import update_timers
    from engine.systems.scenes import advance_scene

    st_p.setdefault("meta", {}).update({"day": 1, "time_min": 8 * 60})
    update_timers(st_p, {"action_type": "instant", "domain": "other", "instant_minutes": 2})
    sc2 = st_p.get("active_scene")
    assert isinstance(sc2, dict) and sc2.get("scene_type") == "police_stop" and sc2.get("phase") == "stop"
    r0 = advance_scene(st_p, {"scene_action": "comply"})
    assert bool(r0.get("ok")) and r0.get("phase_after") == "dialog"
    # Conceal then admit (should still be deterministic; may reduce found).
    advance_scene(st_p, {"scene_action": "conceal", "scene_arg": "compact_pistol"})
    r1 = advance_scene(st_p, {"scene_action": "say_yes"})
    assert bool(r1.get("ok")) and bool(r1.get("ended")) is True
    assert st_p.get("active_scene") is None

    # Undercover sting is now a playable scene (undercover_sting -> sting_setup).
    st_sting = initialize_state({"name": "StingScene", "location": "new york", "year": "2025"}, seed_pack="minimal")
    st_sting.setdefault("meta", {}).update({"day": 1, "time_min": 8 * 60})
    st_sting.setdefault("player", {})["district"] = "harbor"
    # Ensure player carries an illegal weapon so follow-up scheduling path is exercised.
    st_sting.setdefault("inventory", {}).setdefault("bag_contents", []).append("compact_pistol")
    st_sting.setdefault("pending_events", []).append(
        {
            "event_type": "undercover_sting",
            "title": "Undercover Sting",
            "due_day": 1,
            "due_time": 8 * 60,
            "triggered": False,
            "payload": {"location": "new york", "bought_item_id": "compact_pistol", "district_police_presence": 4, "sting_bias": "high"},
        }
    )
    update_timers(st_sting, {"action_type": "instant", "domain": "other", "instant_minutes": 1})
    scs = st_sting.get("active_scene")
    assert isinstance(scs, dict) and scs.get("scene_type") == "sting_setup" and scs.get("phase") == "realization"
    s0 = advance_scene(st_sting, {"scene_action": "walk_away"})
    assert bool(s0.get("ok")) and bool(s0.get("ended")) is True
    assert st_sting.get("active_scene") is None
    # Either a follow-up police stop is scheduled or not, but if scheduled it must be deterministic and valid.
    pe2 = st_sting.get("pending_events", []) or []
    if any(isinstance(ev, dict) and ev.get("event_type") == "police_weapon_check" for ev in pe2):
        evp = [ev for ev in pe2 if isinstance(ev, dict) and ev.get("event_type") == "police_weapon_check"][0]
        assert isinstance(evp.get("payload"), dict)

    # Safehouse raid is now a playable scene (safehouse_raid -> raid_response) and applies confiscation in-scene.
    st_raid = initialize_state({"name": "RaidScene", "location": "london", "year": "2025"}, seed_pack="minimal")
    st_raid.setdefault("meta", {}).update({"day": 1, "time_min": 8 * 60})
    st_raid.setdefault("player", {})["district"] = "downtown"
    # Prepare a safehouse with contraband in stash.
    w = st_raid.setdefault("world", {})
    sh = w.setdefault("safehouses", {})
    sh.setdefault("london", {"status": "active", "security_level": 2, "delinquent_days": 0, "stash": [], "stash_ammo": {}})
    sh["london"]["stash"] = [{"item_id": "compact_pistol"}]
    w["safehouses"] = sh
    st_raid.setdefault("economy", {})["cash"] = 2000
    st_raid.setdefault("pending_events", []).append(
        {
            "event_type": "safehouse_raid",
            "title": "Safehouse Raid",
            "due_day": 1,
            "due_time": 8 * 60,
            "triggered": False,
            "payload": {
                "location": "london",
                "country": "united kingdom",
                "law_level": "strict",
                "corruption": "low",
                "firearm_policy": "civilian_ban",
                "has_weapon_permit": False,
                "disguise_active": False,
                "security_level": 2,
                "trace_snapshot": 0,
                "hot_item_ids": ["compact_pistol"],
            },
        }
    )
    update_timers(st_raid, {"action_type": "instant", "domain": "other", "instant_minutes": 1})
    scr = st_raid.get("active_scene")
    assert isinstance(scr, dict) and scr.get("scene_type") == "raid_response"
    rr = advance_scene(st_raid, {"scene_action": "comply"})
    assert bool(rr.get("ok")) and bool(rr.get("ended")) is True
    # Stash should be modified (confiscation may remove the item).
    stash2 = (((st_raid.get("world", {}) or {}).get("safehouses", {}) or {}).get("london", {}) or {}).get("stash") or []
    assert isinstance(stash2, list)
    # Casefile should record high-signal triggers.
    cf = ((st_raid.get("world", {}) or {}).get("casefile", []) or [])
    assert isinstance(cf, list)
    assert any(isinstance(x, dict) and x.get("event_type") in ("safehouse_raid", "police_weapon_check", "undercover_sting") for x in cf) or len(cf) >= 1

    # Police sweep is now a playable scene (police_sweep -> checkpoint_sweep).
    st_sw = initialize_state({"name": "SweepScene", "location": "london", "year": "2025"}, seed_pack="minimal")
    st_sw.setdefault("meta", {}).update({"day": 1, "time_min": 8 * 60})
    st_sw.setdefault("player", {})["district"] = "downtown"
    st_sw.setdefault("pending_events", []).append(
        {
            "event_type": "police_sweep",
            "title": "Police Sweep",
            "due_day": 1,
            "due_time": 8 * 60,
            "triggered": False,
            "payload": {"location": "london", "attention": "investigated"},
        }
    )
    update_timers(st_sw, {"action_type": "instant", "domain": "other", "instant_minutes": 1})
    sc_sw = st_sw.get("active_scene")
    assert isinstance(sc_sw, dict) and sc_sw.get("scene_type") == "checkpoint_sweep"
    # Carry illegal weapon so checkpoint can schedule follow-up stop deterministically.
    st_sw.setdefault("inventory", {}).setdefault("bag_contents", []).append("compact_pistol")
    # Also mark contraband so checkpoint can escalate toward raid deterministically (if safehouse exists here).
    w_sw = st_sw.setdefault("world", {})
    sh_sw = w_sw.setdefault("safehouses", {})
    sh_sw.setdefault("london", {"status": "active", "security_level": 2, "delinquent_days": 0, "stash": [], "stash_ammo": {}})
    w_sw["safehouses"] = sh_sw
    rr_sw = advance_scene(st_sw, {"scene_action": "detour"})
    assert bool(rr_sw.get("ok")) and bool(rr_sw.get("ended")) is True
    rmap = (((st_sw.get("world", {}) or {}).get("locations", {}) or {}).get("london", {}) or {}).get("restrictions", {}) or {}
    assert isinstance(rmap, dict) and int(rmap.get("police_sweep_until_day", 0) or 0) >= 1
    # Follow-up stop may be scheduled; if scheduled it must be well-formed.
    pe_sw = st_sw.get("pending_events", []) or []
    if any(isinstance(ev, dict) and ev.get("event_type") == "police_weapon_check" for ev in pe_sw):
        evp = [ev for ev in pe_sw if isinstance(ev, dict) and ev.get("event_type") == "police_weapon_check"][0]
        assert isinstance(evp.get("payload"), dict)
    if any(isinstance(ev, dict) and ev.get("event_type") == "safehouse_raid" for ev in pe_sw):
        evr = [ev for ev in pe_sw if isinstance(ev, dict) and ev.get("event_type") == "safehouse_raid"][0]
        assert isinstance(evr.get("payload"), dict)

    # Travel encounters: scheduler gates into scene-backed traffic_stop / vehicle_search deterministically.
    st_tr1 = initialize_state({"name": "TravelTraffic", "location": "london", "year": "2025"}, seed_pack="minimal")
    st_tr1.setdefault("meta", {}).update({"day": 1, "time_min": 8 * 60, "turn": 1})
    st_tr1.setdefault("player", {})["district"] = "downtown"
    # Set medium score -> traffic_stop.
    st_tr1.setdefault("world", {}).setdefault("heat_map", {}).setdefault("london", {})["__all__"] = {"level": 60, "until_day": 9, "reasons": ["test"]}
    st_tr1.setdefault("world", {}).setdefault("suspicion", {}).setdefault("london", {})["__all__"] = {"level": 50, "until_day": 9, "reasons": ["test"]}
    update_timers(st_tr1, {"action_type": "travel", "domain": "move", "travel_destination": "tokyo", "travel_minutes": 5})
    sc_tr1 = st_tr1.get("active_scene")
    assert isinstance(sc_tr1, dict) and sc_tr1.get("scene_type") == "traffic_stop"
    # Use conceal and then comply.
    st_tr1.setdefault("inventory", {}).setdefault("bag_contents", []).append("compact_pistol")
    advance_scene(st_tr1, {"scene_action": "conceal", "scene_arg": "compact_pistol"})
    rtr1 = advance_scene(st_tr1, {"scene_action": "comply"})
    assert bool(rtr1.get("ok")) and bool(rtr1.get("ended")) is True
    assert st_tr1.get("active_scene") is None

    st_tr2 = initialize_state({"name": "TravelSearch", "location": "london", "year": "2025"}, seed_pack="minimal")
    st_tr2.setdefault("meta", {}).update({"day": 1, "time_min": 8 * 60, "turn": 2})
    st_tr2.setdefault("player", {})["district"] = "downtown"
    # High score -> vehicle_search.
    st_tr2.setdefault("world", {}).setdefault("heat_map", {}).setdefault("london", {})["__all__"] = {"level": 100, "until_day": 9, "reasons": ["test"]}
    st_tr2.setdefault("world", {}).setdefault("suspicion", {}).setdefault("london", {})["__all__"] = {"level": 100, "until_day": 9, "reasons": ["test"]}
    st_tr2.setdefault("trace", {})["trace_pct"] = 50
    st_tr2.setdefault("economy", {})["cash"] = 5000
    update_timers(st_tr2, {"action_type": "travel", "domain": "move", "travel_destination": "tokyo", "travel_minutes": 5})
    sc_tr2 = st_tr2.get("active_scene")
    assert isinstance(sc_tr2, dict) and sc_tr2.get("scene_type") == "vehicle_search"
    # Bribe out deterministically (amount defaulted in scene if omitted).
    rtr2 = advance_scene(st_tr2, {"scene_action": "bribe", "bribe_amount": 600})
    assert bool(rtr2.get("ok")) and bool(rtr2.get("ended")) is True
    assert st_tr2.get("active_scene") is None

    # Border control travel scene: strict border_controls should prefer border_control over traffic_stop.
    st_bc = initialize_state({"name": "BorderControl", "location": "london", "year": "1942"}, seed_pack="minimal")
    st_bc.setdefault("meta", {}).update({"day": 1, "time_min": 8 * 60, "turn": 3, "sim_year": 1942})
    st_bc.setdefault("player", {})["district"] = "downtown"
    st_bc.setdefault("world", {}).setdefault("heat_map", {}).setdefault("london", {})["__all__"] = {"level": 90, "until_day": 9, "reasons": ["test"]}
    st_bc.setdefault("world", {}).setdefault("suspicion", {}).setdefault("london", {})["__all__"] = {"level": 80, "until_day": 9, "reasons": ["test"]}
    update_timers(st_bc, {"action_type": "travel", "domain": "move", "travel_destination": "tokyo", "travel_minutes": 5})
    sc_bc = st_bc.get("active_scene")
    assert isinstance(sc_bc, dict) and sc_bc.get("scene_type") == "border_control"
    rr_bc = advance_scene(st_bc, {"scene_action": "comply"})
    assert bool(rr_bc.get("ok")) and bool(rr_bc.get("ended")) is True
    assert st_bc.get("active_scene") is None

    # Heat/Suspicion core: deterministic bump + decay.
    from engine.world.heat import bump_heat, bump_suspicion, decay_heat_and_suspicion

    st_hs = initialize_state({"name": "HeatSusp", "location": "london", "year": "2025"}, seed_pack="minimal")
    st_hs.setdefault("meta", {}).update({"day": 1, "time_min": 8 * 60})
    bump_heat(st_hs, loc="london", delta=10, reason="test", ttl_days=3)
    bump_suspicion(st_hs, loc="london", delta=20, reason="test", ttl_days=1)
    hb0 = ((st_hs.get("world", {}) or {}).get("heat_map", {}) or {}).get("london", {}).get("__all__", {}) or {}
    sb0 = ((st_hs.get("world", {}) or {}).get("suspicion", {}) or {}).get("london", {}).get("__all__", {}) or {}
    assert int(hb0.get("level", 0) or 0) == 10
    assert int(sb0.get("level", 0) or 0) == 20
    decay_heat_and_suspicion(st_hs, cur_day=1)
    # same day decay still applies (deterministic) but bounded
    hb1 = ((st_hs.get("world", {}) or {}).get("heat_map", {}) or {}).get("london", {}).get("__all__", {}) or {}
    sb1 = ((st_hs.get("world", {}) or {}).get("suspicion", {}) or {}).get("london", {}).get("__all__", {}) or {}
    assert int(hb1.get("level", 0) or 0) <= 10
    assert int(sb1.get("level", 0) or 0) <= 20

    # Informant network: a rumor hop can generate informant_tip -> npc_report -> follow-up sweep/stop.
    st_inf = initialize_state({"name": "Informants", "location": "london", "year": "2025"}, seed_pack="minimal")
    st_inf.setdefault("meta", {}).update({"day": 1, "time_min": 8 * 60, "turn": 3})
    st_inf.setdefault("player", {})["district"] = "downtown"
    # Prepare NPCs + a forced informant profile.
    st_inf.setdefault("npcs", {}).update(
        {
            "Fixer_Ivy": {"role": "fixer", "home_location": "london"},
            "Cop_Rook": {"role": "police_officer", "home_location": "london"},
        }
    )
    st_inf.setdefault("world", {}).setdefault("informants", {})["Cop_Rook"] = {"affiliation": "police", "reliability": 100, "last_tip_turn": -999}
    # Simulate a rumor hop arriving at Cop_Rook.
    st_inf.setdefault("pending_events", []).append(
        {
            "event_type": "social_diffusion_hop",
            "due_day": 1,
            "due_time": 8 * 60,
            "triggered": False,
            "payload": {"from_npc": "Fixer_Ivy", "to_npc": "Cop_Rook", "rumor": "Orang bilang kamu bawa pistol.", "category": "combat", "hop": 1},
        }
    )
    update_timers(st_inf, {"action_type": "instant", "domain": "other", "instant_minutes": 1})
    pe_inf = st_inf.get("pending_events", []) or []
    assert any(isinstance(ev, dict) and ev.get("event_type") == "informant_tip" for ev in pe_inf)
    # Trigger tip processing.
    update_timers(st_inf, {"action_type": "instant", "domain": "other", "instant_minutes": 3})
    pe2_inf = st_inf.get("pending_events", []) or []
    # Tip should have produced at least an npc_report, and possibly follow-up police_sweep/stop.
    assert any(isinstance(ev, dict) and ev.get("event_type") == "npc_report" for ev in pe2_inf) or isinstance(st_inf.get("active_scene"), dict)

    # Informant roster + ops: seed roster, pay increases reliability, burn can schedule backlash.
    from engine.social.informants import seed_informant_roster
    from engine.social.informant_ops import pay_informant, burn_informant

    st_ops = initialize_state({"name": "InformantOps", "location": "london", "year": "2025"}, seed_pack="minimal")
    st_ops.setdefault("meta", {}).update({"day": 1, "time_min": 8 * 60, "turn": 10})
    st_ops.setdefault("player", {})["district"] = "downtown"
    st_ops.setdefault("economy", {})["cash"] = 5000
    st_ops.setdefault("npcs", {}).update({"Cop_A": {"role": "police_officer", "home_location": "london"}, "Civ_B": {"role": "civilian", "home_location": "london"}})
    rseed = seed_informant_roster(st_ops, loc="london", district="downtown")
    assert bool(rseed.get("ok")) is True
    names = list((rseed.get("names") or []) if isinstance(rseed.get("names"), list) else [])
    assert names
    pick = names[0]
    # Ensure profile exists and pay works.
    before_rel = int(((st_ops.get("world", {}) or {}).get("informants", {}) or {}).get(pick, {}).get("reliability", 50) or 50)
    rpay = pay_informant(st_ops, pick, 1000)
    assert bool(rpay.get("ok")) is True
    after_rel = int(((st_ops.get("world", {}) or {}).get("informants", {}) or {}).get(pick, {}).get("reliability", 50) or 50)
    assert after_rel >= before_rel
    rburn = burn_informant(st_ops, pick)
    assert bool(rburn.get("ok")) is True
    # burned informant removed
    assert pick not in (((st_ops.get("world", {}) or {}).get("informants", {}) or {}))

    # SHOP per-role: ordering should differ between roles for same context.
    st_role = initialize_state({"name": "RoleShop", "location": "tokyo", "year": "2025"}, seed_pack="minimal")
    st_role.setdefault("meta", {}).update({"day": 3, "time_min": 8 * 60})
    st_role.setdefault("world", {}).setdefault("locations", {}).setdefault("tokyo", {}).setdefault("tags", ["surveillance_high", "corporate_dense"])
    st_role["world"]["locations"]["tokyo"].setdefault("npcs", {"Fixer_Suzume": {"role": "fixer"}, "Doc_Yuna": {"role": "doc"}})
    q_fix = list_shop_quotes(st_role, limit=6, role="fixer")
    q_doc = list_shop_quotes(st_role, limit=6, role="doc")
    assert q_fix and q_doc
    assert q_fix[0].item_id != q_doc[0].item_id or q_fix[0].buy_price != q_doc[0].buy_price

    # BANK: deposit feeds AML via update_economy(cash_deposit).
    from engine.player.banking import bank_deposit

    st_bank = initialize_state({"name": "BankVerify", "location": "london", "year": "2025"}, seed_pack="minimal")
    st_bank.setdefault("economy", {}).update({"cash": 20000, "bank": 0, "aml_threshold": 10000})
    st_bank.setdefault("meta", {}).update({"day": 1, "time_min": 600})
    d_small = bank_deposit(st_bank, 3000)
    assert d_small["ok"]
    update_economy(st_bank, {"cash_deposit": d_small["cash_deposit"]})
    assert str((st_bank.get("economy", {}) or {}).get("aml_status", "")) == "CLEAR"
    st_aml = initialize_state({"name": "BankAML", "location": "london", "year": "2025"}, seed_pack="minimal")
    st_aml.setdefault("economy", {}).update({"cash": 20000, "bank": 0, "aml_threshold": 10000})
    st_aml.setdefault("meta", {}).update({"day": 1, "time_min": 600})
    d_big = bank_deposit(st_aml, 15000)
    assert d_big["ok"]
    update_economy(st_aml, {"cash_deposit": d_big["cash_deposit"]})
    assert str((st_aml.get("economy", {}) or {}).get("aml_status", "")).startswith("ACTIVE")

    # ACCOMMODATION: prepaid hotel nights tick down per game day (not on check-in day).
    from engine.systems.accommodation import deterministic_stay_raid_roll_percent, normalize_stay_kind, process_accommodation_daily, stay_checkin

    # NL accommodation intent: narrator hint only; engine charges via STAY command.
    ctx_stay_nl = parse_action_intent("kamu stay satu malam di hotel")
    assert ctx_stay_nl.get("intent_note") == "accommodation_stay"
    assert int((ctx_stay_nl.get("accommodation_intent") or {}).get("nights", 0) or 0) == 1
    assert (ctx_stay_nl.get("accommodation_intent") or {}).get("kind") == "hotel"
    ctx_br = parse_action_intent("menginap semalam di hostel murah")
    assert ctx_br.get("intent_note") == "accommodation_stay"
    assert (ctx_br.get("accommodation_intent") or {}).get("kind") == "kos"

    import os

    from engine.systems.accommodation import try_auto_stay_from_intent

    assert try_auto_stay_from_intent(st, {"intent_note": "accommodation_stay", "accommodation_intent": {"nights": 1}}).get("reason") == "disabled"
    _prev_auto = os.environ.get("OMNI_AUTO_STAY_INTENT")
    os.environ["OMNI_AUTO_STAY_INTENT"] = "1"
    try:
        st_auto = initialize_state({"name": "AutoStay", "location": "paris", "year": "2025"}, seed_pack="minimal")
        st_auto.setdefault("economy", {})["cash"] = 100000
        st_auto.setdefault("meta", {}).update({"day": 2, "time_min": 480})
        ctx_auto = parse_action_intent("stay satu malam di hotel")
        r_auto = try_auto_stay_from_intent(st_auto, ctx_auto)
        assert r_auto.get("applied") is True
        assert int(((st_auto.get("world", {}) or {}).get("accommodation", {}) or {}).get("paris", {}).get("nights_remaining", 0) or 0) >= 1
    finally:
        if _prev_auto is None:
            os.environ.pop("OMNI_AUTO_STAY_INTENT", None)
        else:
            os.environ["OMNI_AUTO_STAY_INTENT"] = _prev_auto

    assert normalize_stay_kind("boarding") == "kos"
    assert normalize_stay_kind("dorm") == "kos"
    assert normalize_stay_kind("kos") == "kos"

    st_board = initialize_state({"name": "StayBoard", "location": "berlin", "year": "2025"}, seed_pack="minimal")
    st_board.setdefault("economy", {})["cash"] = 50000
    st_board.setdefault("meta", {}).update({"day": 1, "time_min": 480})
    r_board = stay_checkin(st_board, "boarding", 1)
    assert r_board["ok"] and r_board.get("kind") == "kos"

    st_acc = initialize_state({"name": "StayVerify", "location": "paris", "year": "2025"}, seed_pack="minimal")
    st_acc.setdefault("economy", {})["cash"] = 50000
    st_acc.setdefault("meta", {}).update({"day": 5, "time_min": 480})
    r_stay = stay_checkin(st_acc, "hotel", 2)
    assert r_stay["ok"]
    paris = (st_acc.get("world", {}).get("accommodation", {}) or {}).get("paris") or {}
    assert int(paris.get("nights_remaining", 0) or 0) == 2
    process_accommodation_daily(st_acc)
    assert int(((st_acc.get("world", {}) or {}).get("accommodation", {}) or {}).get("paris", {}).get("nights_remaining", 0) or 0) == 2
    st_acc.setdefault("meta", {})["day"] = 6
    process_accommodation_daily(st_acc)
    assert int(((st_acc.get("world", {}) or {}).get("accommodation", {}) or {}).get("paris", {}).get("nights_remaining", 0) or 0) == 1

    # STAY anti-turtle: Lockdown can trigger immediate safehouse raid before time advances.
    from main import handle_special as _handle_special

    st_stay_raid = initialize_state({"name": "StayRaid", "location": "london", "year": "2025"}, seed_pack="minimal")
    st_stay_raid.setdefault("trace", {})["trace_pct"] = 90
    st_stay_raid.setdefault("economy", {})["cash"] = 1000
    st_stay_raid.setdefault("economy", {})["bank"] = 10000
    st_stay_raid.setdefault("meta", {}).update({"day": 3, "time_min": 480})
    st_stay_raid.setdefault("world", {}).setdefault("safehouses", {})["london"] = {
        "status": "rent",
        "security_level": 1,
        "stash": [{"item_id": "compact_pistol"}],
        "stash_ammo": {},
        "delinquent_days": 0,
    }
    hit_turn = None
    for tn in range(512):
        st_stay_raid["meta"]["turn"] = int(tn)
        if deterministic_stay_raid_roll_percent(st_stay_raid) < 40:
            hit_turn = int(tn)
            break
    assert hit_turn is not None
    st_stay_raid["meta"]["turn"] = hit_turn
    day0 = int(st_stay_raid.get("meta", {}).get("day", 0) or 0)
    time0 = int(st_stay_raid.get("meta", {}).get("time_min", 0) or 0)
    assert _handle_special(st_stay_raid, "STAY hotel 1") is True
    sc_sr = st_stay_raid.get("active_scene")
    assert isinstance(sc_sr, dict) and sc_sr.get("scene_type") == "safehouse_raid"
    assert int(st_stay_raid.get("meta", {}).get("day", 0) or 0) == day0
    assert int(st_stay_raid.get("meta", {}).get("time_min", 0) or 0) == time0
    rr_sr = advance_scene(st_stay_raid, {"scene_action": "comply"})
    assert bool(rr_sr.get("ok")) and bool(rr_sr.get("ended")) is True
    assert int((st_stay_raid.get("trace") or {}).get("trace_pct", 0) or 0) == 0
    assert int(st_stay_raid.get("meta", {}).get("day", 0) or 0) == day0 + 2
    assert st_stay_raid.get("active_scene") is None
    sh_after = (((st_stay_raid.get("world", {}) or {}).get("safehouses", {}) or {}).get("london", {}) or {})
    assert str(sh_after.get("status", "")) == "none"

    # Skill level → meaningful roll modifier (BAL_SKILL_MOD_PER_LEVEL).
    from engine.core.modifiers import compute_roll_package

    st_skill = initialize_state({"name": "SkillMod", "location": "london", "year": "2025"}, seed_pack="minimal")
    st_skill.setdefault("skills", {})["evasion"] = {
        "level": 6,
        "xp": 0,
        "base": 10,
        "current": 40,
        "last_used_day": 1,
        "mastery_streak": 0,
    }
    pkg_sk = compute_roll_package(
        st_skill,
        {
            "domain": "evasion",
            "trained": True,
            "stakes": "high",
            "normalized_input": "evade pursuit",
            "has_stakes": True,
            "uncertain": True,
        },
    )
    mod_labels = [str(m[0]) for m in (pkg_sk.get("mods") or []) if isinstance(m, (list, tuple)) and len(m) >= 2]
    assert any("Skill level" in x for x in mod_labels)

    # STRICT_PACK_VALIDATION: fail-fast on invalid extras (same path as OMNI_STRICT_PACK_EXTRAS).
    from engine.core.content_packs import freeze_packs_into_state

    _prev_sp = os.environ.get("STRICT_PACK_VALIDATION")
    os.environ["STRICT_PACK_VALIDATION"] = "1"
    try:
        st_pk = initialize_state({"name": "PackStrict", "location": "london", "year": "2025"}, seed_pack="minimal")
        freeze_packs_into_state(st_pk, pack_ids=["core"])
        assert isinstance((st_pk.get("meta", {}) or {}).get("content_packs"), dict)
    finally:
        if _prev_sp is None:
            os.environ.pop("STRICT_PACK_VALIDATION", None)
        else:
            os.environ["STRICT_PACK_VALIDATION"] = _prev_sp

    # NPC combat AI: pursuit (player fails) vs surrender (opponent breaks).
    from engine.npc.npc_combat_ai import apply_npc_combat_followup

    st_nc = initialize_state({"name": "NpcCombat", "location": "london", "year": "2025"}, seed_pack="minimal")
    st_nc.setdefault("npcs", {})["Guard_A"] = {"name": "Guard_A", "affiliation": "police", "combat_morale": 60}
    apply_npc_combat_followup(
        st_nc,
        {"domain": "combat", "targets": ["Guard_A"], "combat_style": "melee"},
        {"outcome": "Failure", "roll": 12, "mods": [], "net_threshold": 50},
    )
    assert (st_nc.get("npcs", {}).get("Guard_A") or {}).get("pursuit_until_day")
    st_nc2 = initialize_state({"name": "NpcCombat2", "location": "london", "year": "2025"}, seed_pack="minimal")
    st_nc2.setdefault("npcs", {})["Thug_B"] = {
        "name": "Thug_B",
        "affiliation": "black_market",
        "combat_morale": 20,
        "disposition_score": 40,
    }
    apply_npc_combat_followup(
        st_nc2,
        {"domain": "combat", "targets": ["Thug_B"], "combat_style": "melee"},
        {"outcome": "Critical Success", "roll": 3, "mods": [], "net_threshold": 50},
    )
    assert (st_nc2.get("npcs", {}).get("Thug_B") or {}).get("combat_posture") == "surrender"

    # turn_prompt: package builds with extended ENGINE lines (import smoke).
    from ai.turn_prompt import build_turn_package

    _tp = build_turn_package(st_nc2, "test", {"outcome": "Success", "roll": 10, "mods": [], "net_threshold": 50}, {})
    assert "Skills (engine):" in _tp or "Skill (engine):" in _tp
    assert "Weather (engine)" in _tp or "Cuaca (engine)" in _tp

    # Bio: worst infection controls recovery block; shower intent resets hygiene clock; BAL-driven thresholds.
    from engine.player.bio import update_bio

    st_bio = initialize_state({"name": "BioVerify", "location": "london", "year": "2025"}, seed_pack="minimal")
    st_bio.setdefault("bio", {})["hours_since_shower"] = 10.0
    st_bio["injuries"] = [{"id": "leg", "infection_pct": 55}]
    update_bio(
        st_bio,
        {
            "action_type": "instant",
            "instant_minutes": 120,
            "time_breakdown": [{"label": "instant", "minutes": 120}],
            "normalized_input": "walk",
        },
    )
    assert (st_bio.get("bio", {}) or {}).get("blood_recovery_blocked") is True
    st_bio["injuries"] = [{"id": "leg", "infection_pct": 15}]
    update_bio(
        st_bio,
        {
            "action_type": "instant",
            "instant_minutes": 1,
            "time_breakdown": [{"label": "instant", "minutes": 1}],
            "normalized_input": "walk",
        },
    )
    assert (st_bio.get("bio", {}) or {}).get("blood_recovery_blocked") is False
    st_bio.setdefault("bio", {})["hours_since_shower"] = 5.0
    update_bio(
        st_bio,
        {
            "action_type": "instant",
            "instant_minutes": 60,
            "normalized_input": "aku mandi shower sekarang",
            "time_breakdown": [{"label": "instant", "minutes": 60}],
        },
    )
    assert float((st_bio.get("bio", {}) or {}).get("hours_since_shower", 99)) == 0.0

    # Intimacy: consensual path parses; aftermath sets satisfaction + partner mood (fade-to-black is LLM prompt).
    from engine.core.action_intent import parse_action_intent
    from engine.systems.intimacy import apply_intimacy_aftermath
    from engine.npc.npcs import ensure_ambient_npcs

    ctx_ix = parse_action_intent("make love with Rio")
    assert ctx_ix.get("intent_note") == "intimacy_private"
    assert ctx_ix.get("visibility") == "private"
    assert "Rio" in (ctx_ix.get("targets") or [])
    st_ix = initialize_state({"name": "Ix", "location": "Test", "year": "2025"}, seed_pack="minimal")
    st_ix.setdefault("npcs", {})["Rio"] = {"joy": 10, "trust": 40, "ambient": True, "affiliation": "civilian"}
    ensure_ambient_npcs(st_ix, ctx_ix)
    ctx_ix["domain"] = "social"
    ctx_ix["social_mode"] = "non_conflict"
    ctx_ix["normalized_input"] = "make love with Rio"
    apply_intimacy_aftermath(st_ix, ctx_ix, {"outcome": "Success", "roll": 50, "mods": [], "net_threshold": 50})
    il = (st_ix.get("meta", {}) or {}).get("intimacy_last")
    assert isinstance(il, dict) and il.get("partner") == "Rio"
    assert 1 <= int(il.get("satisfaction", 0)) <= 100
    assert int(((st_ix.get("npcs", {}) or {}).get("Rio") or {}).get("joy", 0)) > 10
    assert parse_action_intent("paksa dia bercinta").get("intent_note") != "intimacy_private"

    # Weapon kit: buying a firearm seeds inventory.weapons with ammo/capacity for combat gates.
    from engine.systems.shop import buy_item

    st_wpn = initialize_state({"name": "WpnBuy", "location": "Test", "year": "2025"}, seed_pack="minimal")
    st_wpn.setdefault("economy", {})["cash"] = 9000
    br = buy_item(st_wpn, "compact_pistol")
    assert bool(br.get("ok")), br
    wrow = (st_wpn.get("inventory", {}).get("weapons") or {}).get("compact_pistol")
    assert isinstance(wrow, dict)
    assert str(wrow.get("kind")) == "firearm"
    assert int(wrow.get("ammo", 0) or 0) >= 1
    assert int(wrow.get("mag_capacity", 0) or 0) >= 1
    assert str(wrow.get("ammo_item_id", "")) == "ammo_9mm"
    tr0 = int((st_wpn.get("trace", {}) or {}).get("trace_pct", 0) or 0)
    assert tr0 > 0

    # Vehicles: active vehicle modifies travel minutes and consumes fuel.
    from engine.systems.vehicles import buy_vehicle, set_active_vehicle

    st_v = initialize_state({"name": "Veh", "location": "jakarta", "year": "2025"}, seed_pack="minimal")
    st_v.setdefault("economy", {})["cash"] = 10000
    assert buy_vehicle(st_v, "car_standard").get("ok") is True
    assert set_active_vehicle(st_v, "car_standard").get("ok") is True
    invv = st_v.setdefault("inventory", {})
    fuel0 = int(((invv.get("vehicles", {}) or {}).get("car_standard") or {}).get("fuel", 0) or 0)
    ctx_tr = {"action_type": "travel", "travel_destination": "tokyo", "travel_minutes": 60, "domain": "evasion"}
    update_timers(st_v, ctx_tr)
    fuel1 = int((((st_v.get("inventory", {}) or {}).get("vehicles", {}) or {}).get("car_standard") or {}).get("fuel", 0) or 0)
    assert str(ctx_tr.get("vehicle_used", "")) == "car_standard"
    assert fuel1 < fuel0

    # District travel should use travel_minutes (not instant_minutes).
    from engine.world.districts import ensure_city_districts, travel_within_city

    st_d = initialize_state({"name": "Districts", "location": "tokyo", "year": "2025"}, seed_pack="minimal")
    ensure_city_districts(st_d, "tokyo")
    # Pick a deterministic district id
    st_d.setdefault("player", {})["district"] = "finance"
    before_tm = int((st_d.get("meta", {}) or {}).get("time_min", 0) or 0)
    rdt = travel_within_city(st_d, "old_town")
    assert bool(rdt.get("ok"))
    after_tm = int((st_d.get("meta", {}) or {}).get("time_min", 0) or 0)
    assert after_tm > before_tm

    # Hacking should set cyber_alert context when noise rises.
    from engine.systems.hacking import apply_hacking_after_roll

    st_cy = initialize_state({"name": "Cyber", "location": "tokyo", "year": "2025"}, seed_pack="minimal")
    st_cy.setdefault("player", {})["district"] = "finance"
    ctx_h = {"domain": "hacking", "action_type": "instant", "normalized_input": "hack corporate main server", "visibility": "public"}
    apply_hacking_after_roll(st_cy, ctx_h, {"outcome": "Success", "roll": 80, "net_threshold": 50})
    slot = ((st_cy.get("world", {}) or {}).get("locations", {}) or {}).get("tokyo") or {}
    ca = slot.get("cyber_alert") if isinstance(slot, dict) else None
    assert isinstance(ca, dict)
    assert int(ca.get("level", 0) or 0) >= 0

    st_am = initialize_state({"name": "AmmoBuy", "location": "Test", "year": "2025"}, seed_pack="minimal")
    st_am.setdefault("economy", {})["cash"] = 9000
    nbag = len((st_am.get("inventory", {}) or {}).get("bag_contents", []) or [])
    ra = buy_item(st_am, "ammo_9mm")
    assert bool(ra.get("ok")), ra
    assert len((st_am.get("inventory", {}) or {}).get("bag_contents", []) or []) == nbag
    assert int(((st_am.get("inventory", {}) or {}).get("item_quantities") or {}).get("ammo_9mm", 0) or 0) >= 50

    from engine.core.reload import try_reload

    st_rl = initialize_state({"name": "Reload", "location": "Test", "year": "2025"}, seed_pack="minimal")
    st_rl.setdefault("inventory", {}).update(
        {
            "active_weapon_id": "compact_pistol",
            "weapons": {
                "compact_pistol": {
                    "kind": "firearm",
                    "ammo": 0,
                    "mag_capacity": 12,
                    "ammo_item_id": "ammo_9mm",
                    "condition_tier": 2,
                    "jammed": False,
                    "use_count": 0,
                    "name": "Compact Pistol",
                }
            },
            "item_quantities": {"ammo_9mm": 30},
        }
    )
    rr = try_reload(st_rl)
    assert rr.get("ok") is True
    assert int(((st_rl.get("inventory", {}) or {}).get("weapons") or {}).get("compact_pistol", {}).get("ammo", -1) or -1) == 12
    assert int(((st_rl.get("inventory", {}) or {}).get("item_quantities") or {}).get("ammo_9mm", -1) or -1) == 18

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

    # Pickup: ammo goes to item_quantities (no bag slot).
    inv_am = initialize_state({"name": "InvAmmoPickup", "location": "Test", "year": "2025"}, seed_pack="minimal")
    inv_am.setdefault("world", {})["nearby_items"] = [{"id": "ammo_9mm", "name": "Box", "rounds": 25}]
    inv_ami = inv_am.setdefault("inventory", {})
    inv_ami["pocket_contents"] = []
    inv_ami["bag_contents"] = []
    ctx_am = {
        "action_type": "instant",
        "domain": "other",
        "instant_minutes": 1,
        "inventory_ops": [{"op": "pickup", "item_id": "ammo_9mm", "to": "bag", "time_cost_min": 1}],
    }
    apply_inventory_ops(inv_am, ctx_am)
    assert int((inv_ami.get("item_quantities") or {}).get("ammo_9mm", 0) or 0) == 25
    assert "ammo_9mm" not in (inv_ami.get("bag_contents") or [])

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
    from engine.world.world import world_tick
    from engine.player.bio import update_bio
    from engine.player.skills import update_skills
    from engine.npc.npcs import update_npcs
    from engine.player.inventory import update_inventory
    from engine.core.trace import update_trace
    from engine.systems.hacking import apply_hacking_after_roll
    from engine.npc.npc_emotions import apply_npc_emotion_after_roll
    from engine.systems.combat import resolve_combat_after_roll
    from engine.world.timers import update_timers

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
    from engine.npc.npc_sim import tick_npc_sim as _tns
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

    # Determinism regression harness:
    # replay the exact same turn sequence twice and compare per-turn fingerprints.
    def _run_replay(seed_name: str) -> tuple[list[str], str]:
        st_r = initialize_state(
            {"name": "Determinism", "location": "jakarta", "year": "2025", "occupation": "operator", "background": "replay"},
            seed_pack=seed_name,
        )
        st_r.setdefault("player", {}).setdefault("languages", {"en": 80})
        st_r.setdefault("inventory", {}).setdefault("bag_contents", []).append("smartphone")
        seq = [
            {"domain": "social", "action_type": "talk", "social_mode": "non_conflict", "intent_note": "social_dialogue", "normalized_input": "ngobrol sebentar"},
            {"domain": "social", "action_type": "talk", "social_mode": "conflict", "intent_note": "social_conflict", "normalized_input": "negosiasi kontrak keras"},
            {"domain": "hacking", "action_type": "instant", "normalized_input": "hack server pusat data penting perusahaan", "visibility": "public"},
            {"domain": "hacking", "action_type": "instant", "normalized_input": "hapus jejak dan hapus log", "visibility": "low"},
            {"action_type": "travel", "domain": "other", "travel_destination": "london", "normalized_input": "pergi ke london"},
            {"domain": "social", "action_type": "talk", "social_mode": "non_conflict", "intent_note": "social_inquiry", "normalized_input": "tanya kondisi pasar"},
            {"action_type": "travel", "domain": "other", "travel_destination": "jakarta", "normalized_input": "kembali ke jakarta"},
            {"domain": "combat", "action_type": "combat", "combat_style": "ranged", "normalized_input": "tembak", "visibility": "public"},
        ]
        trail: list[str] = []
        for i in range(24):
            ctx = dict(seq[i % len(seq)])
            world_tick(st_r, ctx)
            apply_inventory_ops(st_r, ctx)
            update_timers(st_r, ctx)
            update_bio(st_r, ctx)
            update_skills(st_r, ctx)
            update_npcs(st_r, ctx)
            update_economy(st_r, ctx)
            update_trace(st_r, ctx)
            update_inventory(st_r, ctx)
            apply_combat_gates(st_r, ctx)
            rp = compute_roll_package(st_r, ctx)
            apply_hacking_after_roll(st_r, ctx, rp)
            apply_npc_emotion_after_roll(st_r, ctx, rp)
            apply_npc_targeting(st_r, ctx, rp)
            resolve_combat_after_roll(st_r, ctx, rp)
            trail.append(_determinism_fingerprint(st_r))
        return (trail, _determinism_fingerprint(st_r))

    t1, f1 = _run_replay("minimal")
    t2, f2 = _run_replay("minimal")
    assert t1 == t2
    assert f1 == f2

    # Long-run autonomy sim (no explicit player goals):
    # world should progress for many days without runaway queues/ranges.
    def _run_autonomy(seed_name: str) -> tuple[dict[str, object], str]:
        st_a = initialize_state(
            {"name": "Autonomy", "location": "london", "year": "2025", "occupation": "operator", "background": "autonomy"},
            seed_pack=seed_name,
        )
        st_a.setdefault("meta", {}).update({"day": 1, "time_min": 8 * 60})
        # 30 days * 12 turns/day * 120 minutes/turn = 360 turns.
        for _ in range(360):
            ctx = {
                "action_type": "instant",
                "domain": "other",
                "normalized_input": "wait",
                "instant_minutes": 120,
            }
            world_tick(st_a, ctx)
            update_timers(st_a, ctx)
            update_bio(st_a, ctx)
            update_skills(st_a, ctx)
            update_npcs(st_a, ctx)
            update_economy(st_a, ctx)
            update_trace(st_a, ctx)
            update_inventory(st_a, ctx)
            apply_combat_gates(st_a, ctx)
            rp = compute_roll_package(st_a, ctx)
            apply_hacking_after_roll(st_a, ctx, rp)
            apply_npc_emotion_after_roll(st_a, ctx, rp)
            apply_npc_targeting(st_a, ctx, rp)
            resolve_combat_after_roll(st_a, ctx, rp)

            # Stability invariants during autonomous progression.
            trv = int((st_a.get("trace", {}) or {}).get("trace_pct", 0) or 0)
            assert 0 <= trv <= 100
            pe = st_a.get("pending_events", []) or []
            ar = st_a.get("active_ripples", []) or []
            assert isinstance(pe, list) and len(pe) < 180
            assert isinstance(ar, list) and len(ar) < 180
            mkt = (st_a.get("economy", {}) or {}).get("market", {}) or {}
            if isinstance(mkt, dict):
                for k in ("electronics", "medical", "weapons", "food", "transport"):
                    row = mkt.get(k, {}) or {}
                    if isinstance(row, dict):
                        assert 0 <= int(row.get("scarcity", 0) or 0) <= 100
                        assert 50 <= int(row.get("price_idx", 100) or 100) <= 300

        meta_a = st_a.get("meta", {}) or {}
        day_a = int(meta_a.get("day", 1) or 1)
        assert day_a >= 30

        summary: dict[str, object] = {
            "day": day_a,
            "news_count": len(((st_a.get("world", {}) or {}).get("news_feed", []) or [])),
            "pending_events": len((st_a.get("pending_events", []) or [])),
            "active_ripples": len((st_a.get("active_ripples", []) or [])),
            "trace_pct": int((st_a.get("trace", {}) or {}).get("trace_pct", 0) or 0),
        }
        return (summary, _determinism_fingerprint(st_a))

    a1, af1 = _run_autonomy("minimal")
    a2, af2 = _run_autonomy("minimal")
    assert a1 == a2
    assert af1 == af2

    # Stress test: ironman vs normal + UNDO restore (state-level).
    from engine.core.state import CURRENT, PREVIOUS, save_state, backup_state, load_state
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

    # Save round-trip: deterministic fingerprint after save/load (same migration path as runtime).
    from ai.turn_prompt import build_turn_package

    with tempfile.TemporaryDirectory() as tdir:
        p_rt = Path(tdir) / "roundtrip.json"
        st_rt = initialize_state({"name": "RoundTrip", "location": "test", "year": "2025"}, seed_pack="minimal")
        save_state(st_rt, p_rt)
        st_ld = load_state(p_rt)
        save_state(st_ld, p_rt)
        st_ld2 = load_state(p_rt)
        # Second pass must match first: load/migrate/save is idempotent for the fingerprint slice.
        assert _determinism_fingerprint(st_ld) == _determinism_fingerprint(st_ld2)

    st_facts = initialize_state({"name": "FactsLine", "location": "test", "year": "2025"}, seed_pack="minimal")
    st_facts.setdefault("meta", {})["last_turn_diff"] = {
        "cash": -10,
        "bank": 0,
        "debt": 0,
        "trace": 0,
        "time_elapsed_min": 5,
        "xp_delta": {"hacking": 2, "social": 0, "combat": 0, "stealth": 0, "evasion": 0},
        "notes_added_count": 1,
    }
    st_facts.setdefault("meta", {})["last_turn_audit"] = {"commerce_notes": ["[Shop] BUY knife price=10"]}
    pkg = build_turn_package(
        st_facts,
        "beli sesuatu",
        {"mods": [], "net_threshold": 50, "roll": 50, "outcome": "No Roll"},
        {"action_type": "instant", "domain": "evasion"},
    )
    assert "commerce:" in pkg and "[Shop]" in pkg
    assert "cash-10" in pkg


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
