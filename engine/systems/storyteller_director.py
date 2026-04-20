from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class StorytellerConfig:
    poor_net_worth_lte: int = 1200
    wealth_build_gte: int = 25000
    safe_heat_lte: int = 28
    release_hp_pct_lte: int = 35
    safe_turns_for_build: int = 6
    release_hostile_mult_pct: int = 55
    build_hostile_mult_pct: int = 135
    build_router_time_shift_min: int = -1
    release_router_time_shift_min: int = 4
    build_investigation_due_min: int = 2


def _pack_path() -> Path:
    return Path(__file__).resolve().parents[2] / "data" / "packs" / "core" / "storyteller_director.json"


def _int_env(name: str, default: int) -> int:
    raw = str(os.getenv(name, "") or "").strip()
    if raw.lstrip("-").isdigit():
        try:
            return int(raw)
        except Exception:
            return int(default)
    return int(default)


def _load_pack_config() -> dict[str, Any]:
    p = _pack_path()
    if not p.exists():
        return {}
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return raw if isinstance(raw, dict) else {}


def _cfg_int(pack: dict[str, Any], key: str, fallback: int) -> int:
    v = pack.get(key, fallback)
    try:
        return int(v)
    except Exception:
        return int(fallback)


class StorytellerDirector:
    """Meta-AI pacing observer for encounter pressure.

    Important: this class is read-only against game state. It only returns
    deterministic signals/weights that callers may apply.
    """

    HOSTILE_EVENT_TYPES = frozenset(
        {
            "traffic_stop",
            "vehicle_search",
            "border_control",
            "police_weapon_check",
            "police_sweep",
            "investigation_sweep",
            "manhunt_lockdown",
            "safehouse_raid",
        }
    )

    def __init__(self, config: StorytellerConfig | None = None) -> None:
        self.config = config or self._load_config()

    @classmethod
    def _load_config(cls) -> StorytellerConfig:
        pack = _load_pack_config()
        cfg = StorytellerConfig(
            poor_net_worth_lte=_cfg_int(pack, "poor_net_worth_lte", 1200),
            wealth_build_gte=_cfg_int(pack, "wealth_build_gte", 25000),
            safe_heat_lte=_cfg_int(pack, "safe_heat_lte", 28),
            release_hp_pct_lte=_cfg_int(pack, "release_hp_pct_lte", 35),
            safe_turns_for_build=_cfg_int(pack, "safe_turns_for_build", 6),
            release_hostile_mult_pct=_cfg_int(pack, "release_hostile_mult_pct", 55),
            build_hostile_mult_pct=_cfg_int(pack, "build_hostile_mult_pct", 135),
            build_router_time_shift_min=_cfg_int(pack, "build_router_time_shift_min", -1),
            release_router_time_shift_min=_cfg_int(pack, "release_router_time_shift_min", 4),
            build_investigation_due_min=_cfg_int(pack, "build_investigation_due_min", 2),
        )
        return StorytellerConfig(
            poor_net_worth_lte=_int_env("STORYTELLER_POOR_NET_WORTH_LTE", cfg.poor_net_worth_lte),
            wealth_build_gte=_int_env("STORYTELLER_WEALTH_BUILD_GTE", cfg.wealth_build_gte),
            safe_heat_lte=_int_env("STORYTELLER_SAFE_HEAT_LTE", cfg.safe_heat_lte),
            release_hp_pct_lte=_int_env("STORYTELLER_RELEASE_HP_PCT_LTE", cfg.release_hp_pct_lte),
            safe_turns_for_build=_int_env("STORYTELLER_SAFE_TURNS_FOR_BUILD", cfg.safe_turns_for_build),
            release_hostile_mult_pct=_int_env("STORYTELLER_RELEASE_HOSTILE_MULT_PCT", cfg.release_hostile_mult_pct),
            build_hostile_mult_pct=_int_env("STORYTELLER_BUILD_HOSTILE_MULT_PCT", cfg.build_hostile_mult_pct),
            build_router_time_shift_min=_int_env("STORYTELLER_BUILD_ROUTER_SHIFT_MIN", cfg.build_router_time_shift_min),
            release_router_time_shift_min=_int_env("STORYTELLER_RELEASE_ROUTER_SHIFT_MIN", cfg.release_router_time_shift_min),
            build_investigation_due_min=_int_env("STORYTELLER_BUILD_INVESTIGATION_DUE_MIN", cfg.build_investigation_due_min),
        )

    def _observer(self, state: dict[str, Any]) -> dict[str, Any]:
        world = state.get("world", {}) or {}
        ob = world.get("storyteller_observer", {}) if isinstance(world, dict) else {}
        return ob if isinstance(ob, dict) else {}

    def _net_worth(self, state: dict[str, Any]) -> int:
        eco = state.get("economy", {}) or {}
        try:
            nw = int(eco.get("net_worth", 0) or 0)
            if nw:
                return nw
        except Exception:
            pass
        try:
            cash = int(eco.get("cash", 0) or 0)
        except Exception:
            cash = 0
        try:
            bank = int(eco.get("bank", 0) or 0)
        except Exception:
            bank = 0
        return int(cash + bank)

    def _current_heat(self, state: dict[str, Any]) -> int:
        try:
            trace = int(((state.get("trace", {}) or {}).get("trace_pct", 0) or 0))
        except Exception:
            trace = 0
        world = state.get("world", {}) or {}
        loc = str(((state.get("player", {}) or {}).get("location", "") or "")).strip().lower()
        heat = 0
        susp = 0
        try:
            hm = ((world.get("heat_map", {}) or {}).get(loc, {}) or {}).get("__all__", {}) or {}
            heat = int(hm.get("level", 0) or 0)
        except Exception:
            heat = 0
        try:
            sm = ((world.get("suspicion", {}) or {}).get(loc, {}) or {}).get("__all__", {}) or {}
            susp = int(sm.get("level", 0) or 0)
        except Exception:
            susp = 0
        return int(max(0, min(100, max(trace, heat, susp))))

    def _hp_pct(self, state: dict[str, Any]) -> int:
        p = state.get("player", {}) or {}
        try:
            hp = int(p.get("hp", 100) or 100)
        except Exception:
            hp = 100
        try:
            hp_max = int(p.get("hp_max", 100) or 100)
        except Exception:
            hp_max = 100
        hp_max = max(1, hp_max)
        return int(max(0, min(100, round((hp / hp_max) * 100))))

    def _recent_raid_signal(self, state: dict[str, Any]) -> bool:
        notes = state.get("world_notes", []) or []
        for n in notes[-24:]:
            s = str(n or "").lower()
            if "raid" in s and ("safehouse" in s or "authorities tracked" in s):
                return True
        pending = state.get("pending_events", []) or []
        for ev in pending[-60:]:
            if isinstance(ev, dict) and str(ev.get("event_type", "") or "") == "safehouse_raid" and not bool(ev.get("triggered", False)):
                return True
        return False

    def encounter_signal(self, state: dict[str, Any]) -> dict[str, Any]:
        cfg = self.config
        ob = self._observer(state)
        safe_turns = int(ob.get("safe_turns", 0) or 0)
        current_heat = self._current_heat(state)
        net_worth = self._net_worth(state)
        hp_pct = self._hp_pct(state)
        raid = self._recent_raid_signal(state)

        release = bool(raid or hp_pct <= cfg.release_hp_pct_lte)
        safe_now = bool(current_heat <= cfg.safe_heat_lte and not raid)
        build = bool((not release) and safe_now and safe_turns >= cfg.safe_turns_for_build and net_worth >= cfg.wealth_build_gte)

        hostile_mult = 1.0
        if release:
            hostile_mult = max(0.25, float(cfg.release_hostile_mult_pct) / 100.0)
        elif build:
            hostile_mult = max(1.0, float(cfg.build_hostile_mult_pct) / 100.0)

        return {
            "release_mode": bool(release),
            "build_mode": bool(build),
            "hostile_weight_mult": float(hostile_mult),
            "current_heat": int(current_heat),
            "net_worth": int(net_worth),
            "safe_turns": int(safe_turns),
            "build_investigation_due_min": int(max(1, cfg.build_investigation_due_min)),
        }

    def router_signal(self, state: dict[str, Any], *, event_type: str) -> dict[str, Any]:
        sig = self.encounter_signal(state)
        et = str(event_type or "")
        if et not in self.HOSTILE_EVENT_TYPES:
            return {"surface_time_shift_min": 0, "mode": "neutral"}
        if bool(sig.get("release_mode")):
            return {"surface_time_shift_min": int(self.config.release_router_time_shift_min), "mode": "release"}
        if bool(sig.get("build_mode")):
            return {"surface_time_shift_min": int(self.config.build_router_time_shift_min), "mode": "build"}
        return {"surface_time_shift_min": 0, "mode": "neutral"}

    def observer_update(self, state: dict[str, Any], *, hostile_happened: bool) -> dict[str, Any]:
        ob = self._observer(state)
        safe_turns = int(ob.get("safe_turns", 0) or 0)
        if hostile_happened:
            safe_turns = 0
        else:
            safe_turns = max(0, min(200, safe_turns + 1))
        return {"safe_turns": int(safe_turns)}
