from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

from engine.player.boot_economy import apply_boot_economy
from engine.core.seeds import apply_seed_pack, list_seed_names

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data"
SAVE = ROOT / "save"
CURRENT = SAVE / "current.json"
PREVIOUS = SAVE / "previous.json"
TEMPLATE = DATA / "state_template.json"
SCHEMA_VERSION = 1


def _read(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _defaults() -> dict[str, Any]:
    return {
        "meta": {"turn": 0, "day": 1, "time_min": 8 * 60, "memory_hash_raw": "", "schema_version": SCHEMA_VERSION, "world_seed": ""},
        "player": {
            "social_stats": {
                "looks": 0,
                "outfit": 0,
                "hygiene": 0,
                "speaking": 0,
            }
        },
        "bio": {
            "blood_volume": 5.0,
            "blood_max": 5.0,
            "bp_state": "Stable",
            "sleep_debt": 0.0,
            "infection_pct": 0.0,
            "burnout": 0,
            "sanity_debt": 0,
            "hours_since_shower": 0.0,
            "blood_recovery_modifier_pct": 0,
            "blood_recovery_blocked": False,
            "hygiene_tax_active": False,
            "acute_stress": False,
            "hallucination_type": "none",
            "narrator_drift_state": "stable",
        },
        "economy": {
            "cash": 0,
            "bank": 0,
            "debt": 0,
            "daily_burn": 0,
            "fico": 600,
            "aml_status": "CLEAR",
            "last_economic_cycle_day": 0,
            "aml_threshold": 10000,
            "deposit_log": [],
            "market": {
                "electronics": {"price_idx": 100, "scarcity": 0},
                "medical": {"price_idx": 100, "scarcity": 0},
                "weapons": {"price_idx": 100, "scarcity": 0},
                "food": {"price_idx": 100, "scarcity": 0},
                "transport": {"price_idx": 100, "scarcity": 0},
            },
        },
        "trace": {"trace_pct": 0, "trace_status": "Ghost", "sources": []},
        "inventory": {
            "r_hand": "-",
            "l_hand": "-",
            "worn": "-",
            "pocket_capacity": 4,
            "pocket_contents": [],
            "bag_capacity": 12,
            "bag_contents": [],
            "item_sizes": {},
            "weapon_details": [],
            "weapons": {},
            "active_weapon_id": "",
            "item_quantities": {},
            "vehicles": {},
            "active_vehicle_id": "",
        },
        "skills": {},
        "npcs": {},
        "world": {
            "nearby_items": [],
            "locations": {},
            "contacts": {},
            "atlas": {"countries": {}, "version": 1},
            "safehouses": {},
            "heat_map": {},
            "suspicion": {},
            "tech_progress": 0.0,
            "news_feed": [],
            "last_news_day": 0,
            "hacking_heat": {},
            "last_hacking_heat_decay_day": 0,
            "social_graph": {"__player__": {}},
            "npc_economy": {"offers": {}, "last_refresh_day": 0},
            "conflict_model": "corporate_vs_police_with_black_market",
            "factions": {
                "corporate": {"stability": 50, "power": 50},
                "police": {"stability": 50, "power": 50},
                "black_market": {"stability": 50, "power": 50},
            },
            "faction_statuses": {
                "corporate": "idle",
                "police": "idle",
                "black_market": "idle",
            },
        },
        "reputation": {"police_label": "Neutral", "criminal_label": "Neutral", "civilian_label": "Neutral"},
        "active_ripples": [],
        "resolved_ripples": [],
        "resolved_events": [],
        "pending_events": [],
        "quests": {"active": [], "completed": [], "failed": [], "last_id": 0},
        "world_notes": [],
        "active_scene": None,
        "scene_queue": [],
        "flags": {
            "stop_sequence_active": False,
            "hand_slot_issue": False,
            "weapon_jammed": False,
            "equip_cost_active": False,
            "hallucination_active": False,
            "npc_sim_enabled": True,
            "npc_sim_verbose_notes": False,
            "scenes_enabled": True,
        },
        "memory_hash": {},
    }


def _ensure_required_state_fields(state: dict[str, Any]) -> dict[str, Any]:
    defaults = _defaults()
    for k, v in defaults.items():
        if k not in state:
            state[k] = v
        elif isinstance(v, dict) and isinstance(state.get(k), dict):
            for sk, sv in v.items():
                state[k].setdefault(sk, sv)
    state["meta"]["schema_version"] = SCHEMA_VERSION
    # Backfill player languages (0..100 proficiency).
    try:
        p = state.setdefault("player", {})
        if isinstance(p, dict):
            langs = p.setdefault("languages", {})
            if not isinstance(langs, dict):
                langs = {}
                p["languages"] = langs
            base = str(p.get("language", "en") or "en").strip().lower()
            if base and base not in langs:
                langs[base] = 70
    except Exception:
        pass
    # Backfill world tech progress (future hook).
    try:
        state.setdefault("world", {}).setdefault("tech_progress", 0.0)
    except Exception:
        pass
    return state


def _migrate_state(state: dict[str, Any]) -> dict[str, Any]:
    version = int(state.get("meta", {}).get("schema_version", 0))
    # Placeholder for future migrations.
    if version < 1:
        state = _ensure_required_state_fields(state)
    state = _ensure_required_state_fields(state)
    # Backfill: NPC current_location for older saves.
    try:
        npcs = state.get("npcs", {}) or {}
        if isinstance(npcs, dict):
            for _k, n in npcs.items():
                if not isinstance(n, dict):
                    continue
                if str(n.get("current_location", "") or "").strip() == "":
                    home = str(n.get("home_location", "") or "").strip()
                    if home:
                        n["current_location"] = home
                # Backfill: NPC memories (v2 memory bridge)
                if "memories" not in n or not isinstance(n.get("memories"), list):
                    n["memories"] = []
    except Exception:
        pass
    # Backfill: world.npc_economy, meta.market_index, player.narration_style, flags.ironman_mode
    try:
        state.setdefault("world", {}).setdefault("npc_economy", {"offers": {}, "last_refresh_day": 0})
    except Exception:
        pass
    try:
        state.setdefault("meta", {}).setdefault("market_index", {})
    except Exception:
        pass
    try:
        state.setdefault("player", {}).setdefault("narration_style", "cinematic")
    except Exception:
        pass
    try:
        state.setdefault("flags", {}).setdefault("ironman_mode", False)
    except Exception:
        pass
    # Backfill: active scene system (v6.9+)
    try:
        state.setdefault("active_scene", None)
    except Exception:
        pass
    try:
        state.setdefault("scene_queue", [])
    except Exception:
        pass
    try:
        state.setdefault("flags", {}).setdefault("scenes_enabled", True)
    except Exception:
        pass
    try:
        state.setdefault("quests", {"active": [], "completed": [], "failed": [], "last_id": 0})
    except Exception:
        pass
    try:
        state.setdefault("inventory", {}).setdefault("item_quantities", {})
    except Exception:
        pass
    try:
        state.setdefault("inventory", {}).setdefault("vehicles", {})
        state.setdefault("inventory", {}).setdefault("active_vehicle_id", "")
    except Exception:
        pass
    # Stable world seed for deterministic per-location baselines (not overwritten by travel seed packs).
    try:
        meta = state.setdefault("meta", {})
        if isinstance(meta, dict) and not str(meta.get("world_seed", "") or "").strip():
            meta["world_seed"] = str(meta.get("seed_pack", "") or "")
    except Exception:
        pass
    try:
        state.setdefault("world", {}).setdefault("atlas", {"countries": {}, "version": 1})
    except Exception:
        pass
    try:
        state.setdefault("world", {}).setdefault("safehouses", {})
    except Exception:
        pass
    try:
        state.setdefault("world", {}).setdefault("heat_map", {})
    except Exception:
        pass
    try:
        state.setdefault("world", {}).setdefault("suspicion", {})
    except Exception:
        pass
    try:
        state.setdefault("player", {}).setdefault("disguise", {"active": False, "persona": "", "until_day": 0, "until_time": 0, "risk": 0})
    except Exception:
        pass
    try:
        state.setdefault("world", {}).setdefault("accommodation", {})
    except Exception:
        pass
    try:
        bio = state.setdefault("bio", {})
        if isinstance(bio, dict):
            bio.setdefault("hours_since_shower", 0.0)
            bio.setdefault("blood_recovery_modifier_pct", 0)
            bio.setdefault("blood_recovery_blocked", False)
    except Exception:
        pass
    try:
        state.setdefault("meta", {}).setdefault("balance", {})
    except Exception:
        pass
    return state


def save_state(state: dict[str, Any], path: Path = CURRENT) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def backup_state() -> None:
    if CURRENT.exists():
        SAVE.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(CURRENT, PREVIOUS)


def load_state(path: Path = CURRENT) -> dict[str, Any]:
    try:
        if path.exists():
            st = _migrate_state(_read(path))
            try:
                from engine.core.balance import freeze_balance_into_state

                freeze_balance_into_state(st)
            except Exception:
                pass
            # Freeze content packs + apply their effects (sizes/index).
            try:
                from engine.core.content_packs import apply_pack_effects, freeze_packs_into_state

                freeze_packs_into_state(st)
                apply_pack_effects(st)
            except Exception:
                pass
            return st
    except Exception:
        if PREVIOUS.exists():
            st = _migrate_state(_read(PREVIOUS))
            try:
                from engine.core.balance import freeze_balance_into_state

                freeze_balance_into_state(st)
            except Exception:
                pass
            try:
                from engine.core.content_packs import apply_pack_effects, freeze_packs_into_state

                freeze_packs_into_state(st)
                apply_pack_effects(st)
            except Exception:
                pass
            return st
        raise
    return initialize_state({})


def initialize_state(character_data: dict[str, Any], seed_pack: str | None = None) -> dict[str, Any]:
    base: dict[str, Any]
    if TEMPLATE.exists():
        try:
            base = _read(TEMPLATE)
        except Exception:
            base = {}
    else:
        base = {}
    state = _defaults()
    # shallow merge
    for k, v in base.items():
        if isinstance(v, dict) and isinstance(state.get(k), dict):
            state[k].update(v)
        else:
            state[k] = v
    state["player"].update(character_data)
    state = _ensure_required_state_fields(state)
    apply_boot_economy(state)
    sp = (seed_pack or "").strip()
    if sp and sp.lower() not in ("none", "-", "no"):
        if not apply_seed_pack(state, sp):
            avail = ", ".join(list_seed_names()) or "(tidak ada file)"
            state.setdefault("world_notes", []).append(
                f"[Boot] Seed '{sp}' tidak dimuat — file tidak ada. Tersedia: {avail}."
            )
    # Set stable world seed once (do not overwrite later during travel).
    try:
        meta = state.setdefault("meta", {})
        if isinstance(meta, dict) and not str(meta.get("world_seed", "") or "").strip():
            meta["world_seed"] = str(sp or meta.get("seed_pack", "") or "")
    except Exception:
        pass
    # Freeze balance knobs (determinism for this save).
    try:
        from engine.core.balance import freeze_balance_into_state

        freeze_balance_into_state(state)
    except Exception:
        pass
    # Freeze content packs (determinism for this save) + apply their effects.
    try:
        from engine.core.content_packs import apply_pack_effects, freeze_packs_into_state

        freeze_packs_into_state(state)
        apply_pack_effects(state)
    except Exception:
        pass
    # Occupation template (deterministic, content-driven). Apply once at boot.
    try:
        from engine.systems.occupation import apply_occupation_template, pick_occupation_template_id

        p = state.get("player", {}) or {}
        if isinstance(p, dict) and not bool(p.get("occupation_template_applied", False)):
            # Prefer explicit template id if provided.
            tid = str(p.get("occupation_template_id", "") or "").strip().lower()
            if not tid:
                tid = pick_occupation_template_id(state, str(p.get("occupation", "") or ""), str(p.get("background", "") or "")) or ""
            if tid:
                apply_occupation_template(state, tid)
    except Exception:
        pass
    return state

