"""W2-6: seven core character stats — data-driven via data/skills_table.json `character_stats`.

Attribute modifiers apply after skill-level lines in `compute_roll_package` (small scale; training stays in skills).
"""

from __future__ import annotations

from engine.core.error_taxonomy import log_swallowed_exception
import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

ROOT = Path(__file__).resolve().parents[2]
SKILLS_TABLE_PATH = ROOT / "data" / "skills_table.json"

_STAT_KEYS: Tuple[str, ...] = (
    "charisma",
    "agility",
    "strength",
    "intelligence",
    "perception",
    "luck",
    "willpower",
)

_DEFAULT_CHARACTER_STATS: Dict[str, Any] = {
    "defaults": {k: 50 for k in _STAT_KEYS},
    "mod_per_point": 0.12,
    "mod_cap_per_stat": 7,
    "luck_mod_cap_high_dc_75": 2,
    "luck_mod_cap_high_dc_85": 0,
    "spiral_willpower_slope": 0.45,
    "spiral_willpower_max_penalty": 16,
    "domain_primary_stat": {
        "social": "charisma",
        "combat": "strength",
        "hacking": "intelligence",
        "medical": "intelligence",
        "driving": "agility",
        "stealth": "agility",
        "evasion": "agility",
        "economy": "intelligence",
        "other": "intelligence",
    },
    "domain_secondary_stat": {
        "stealth": "perception",
    },
    "other_domain_stat_hints": {
        "finance": "intelligence",
        "legal": "charisma",
        "negotiation": "charisma",
        "operations": "agility",
        "management": "charisma",
    },
}

_cached_cfg: Optional[Dict[str, Any]] = None


def reload_character_stats_config() -> None:
    global _cached_cfg
    _cached_cfg = None


def _deep_merge_cs(base: Dict[str, Any], overlay: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(base)
    for k, v in overlay.items():
        if k == "defaults" and isinstance(v, dict) and isinstance(out.get("defaults"), dict):
            d = dict(out["defaults"])
            d.update(v)
            out["defaults"] = d
        elif k in ("domain_primary_stat", "domain_secondary_stat", "other_domain_stat_hints") and isinstance(v, dict):
            inner = dict(out.get(k) or {})
            inner.update({str(a).lower(): str(b).lower() for a, b in v.items() if isinstance(a, str) and isinstance(b, str)})
            out[k] = inner
        else:
            out[k] = v
    return out


def _load_cfg() -> Dict[str, Any]:
    global _cached_cfg
    if _cached_cfg is not None:
        return _cached_cfg
    merged = dict(_DEFAULT_CHARACTER_STATS)
    if SKILLS_TABLE_PATH.exists():
        try:
            raw = json.loads(SKILLS_TABLE_PATH.read_text(encoding="utf-8"))
            cs = raw.get("character_stats") if isinstance(raw.get("character_stats"), dict) else {}
            if cs:
                merged = _deep_merge_cs(merged, cs)
        except Exception as _omni_sw_91:
            log_swallowed_exception('engine/core/character_stats.py:91', _omni_sw_91)
    _cached_cfg = merged
    return _cached_cfg


def stat_defaults() -> Dict[str, int]:
    d = _load_cfg().get("defaults") if isinstance(_load_cfg().get("defaults"), dict) else {}
    out: Dict[str, int] = {}
    for k in _STAT_KEYS:
        try:
            out[k] = max(1, min(100, int(d.get(k, 50) or 50)))
        except (TypeError, ValueError):
            out[k] = 50
    return out


def ensure_player_character_stats(state: dict[str, Any]) -> Dict[str, int]:
    player = state.setdefault("player", {})
    if not isinstance(player, dict):
        return dict(stat_defaults())
    cur = player.get("character_stats")
    defaults = stat_defaults()
    if not isinstance(cur, dict):
        cur = {}
        player["character_stats"] = cur
    for k, v in defaults.items():
        if k not in cur:
            cur[k] = v
        try:
            cur[k] = max(1, min(100, int(cur[k])))
        except (TypeError, ValueError):
            cur[k] = v
    return {k: int(cur.get(k, defaults[k]) or defaults[k]) for k in _STAT_KEYS}


def get_stat(state: dict[str, Any], key: str) -> int:
    st = ensure_player_character_stats(state)
    k = str(key or "").strip().lower()
    if k not in st:
        return 50
    return int(st.get(k, 50) or 50)


def _mod_from_stat(val: int, *, per: float, cap: int) -> int:
    try:
        delta = float(val) - 50.0
    except (TypeError, ValueError):
        delta = 0.0
    m = int(round(delta * float(per)))
    cap_i = max(0, int(cap))
    if m > cap_i:
        return cap_i
    if m < -cap_i:
        return -cap_i
    return m


def domain_primary_stat_map() -> Dict[str, str]:
    m = _load_cfg().get("domain_primary_stat")
    if not isinstance(m, dict):
        return {}
    return {str(k).lower(): str(v).lower() for k, v in m.items() if isinstance(k, str) and isinstance(v, str)}


def domain_secondary_stat_map() -> Dict[str, str]:
    m = _load_cfg().get("domain_secondary_stat")
    if not isinstance(m, dict):
        return {}
    return {str(k).lower(): str(v).lower() for k, v in m.items() if isinstance(k, str) and isinstance(v, str)}


def _investigation_social(note: str, norm: str) -> bool:
    return any(x in note for x in ("investigat", "intel", "case", "surveil", "scout", "observe")) or any(
        x in norm for x in ("investigasi", "intel", "case", "kasus", "mata-mata", "pantau", "intai", "interogasi")
    )


def resolve_roll_primary_stat(domain: str, action_ctx: dict[str, Any]) -> Optional[str]:
    dom = str(domain or "").strip().lower()
    pmap = domain_primary_stat_map()
    note = str(action_ctx.get("intent_note", "") or "").lower()
    norm = str(action_ctx.get("normalized_input", "") or "").lower()

    if dom == "social" and _investigation_social(note, norm):
        return "perception"
    if dom == "other":
        hints = _load_cfg().get("other_domain_stat_hints")
        if isinstance(hints, dict):
            if any(x in note or x in norm for x in ("finance", "bank", "invest", "launder", "cuci uang", "uang")):
                k = hints.get("finance")
                if isinstance(k, str):
                    return k.lower()
            if any(x in note or x in norm for x in ("legal", "law", "court", "hukum", "audit", "izin")):
                k = hints.get("legal")
                if isinstance(k, str):
                    return k.lower()
            if any(x in note or x in norm for x in ("negotiat", "deal", "lobby", "negosiasi")):
                k = hints.get("negotiation")
                if isinstance(k, str):
                    return k.lower()
            if any(x in note or x in norm for x in ("operat", "logistik", "supply", "rantai")):
                k = hints.get("operations")
                if isinstance(k, str):
                    return k.lower()
            if any(x in note or x in norm for x in ("manage", "manajemen", "tim", "team lead")):
                k = hints.get("management")
                if isinstance(k, str):
                    return k.lower()
        return pmap.get("other", "intelligence")

    st = pmap.get(dom)
    return st


def append_character_stat_modifiers(
    state: dict[str, Any],
    action_ctx: dict[str, Any],
    mods: List[Tuple[str, int]],
) -> None:
    cfg = _load_cfg()
    try:
        per = float(cfg.get("mod_per_point", 0.12) or 0.12)
    except (TypeError, ValueError):
        per = 0.12
    try:
        cap = int(cfg.get("mod_cap_per_stat", 7) or 7)
    except (TypeError, ValueError):
        cap = 7
    per = max(0.03, min(0.25, per))
    cap = max(2, min(12, cap))

    stats = ensure_player_character_stats(state)
    domain = str(action_ctx.get("roll_domain", action_ctx.get("domain", "")) or "").lower()
    act_type = str(action_ctx.get("action_type", "") or "").lower()

    primary = resolve_roll_primary_stat(domain, action_ctx)
    applied_secondaries: set[str] = set()

    if primary and primary in stats:
        m = _mod_from_stat(stats[primary], per=per, cap=cap)
        if m:
            mods.append((f"Stat ({primary})", m))

    sec_map = domain_secondary_stat_map()
    sec_stat = sec_map.get(domain)
    if sec_stat and sec_stat in stats and sec_stat != primary:
        half_cap = max(1, cap // 2)
        m2 = _mod_from_stat(stats[sec_stat], per=per * 0.55, cap=half_cap)
        if m2:
            mods.append((f"Stat ({sec_stat}·sec)", m2))
            applied_secondaries.add(sec_stat)

    if domain == "social" and primary == "perception" and "intelligence" in stats and "intelligence" not in applied_secondaries:
        half_cap = max(1, cap // 2)
        m3 = _mod_from_stat(stats["intelligence"], per=per * 0.55, cap=half_cap)
        if m3:
            mods.append(("Stat (intelligence·sec)", m3))

    stakes = str(action_ctx.get("stakes", "") or "").lower()
    luck_eligible = act_type == "custom" or (
        domain == "other" and bool(action_ctx.get("uncertain", False)) and stakes in ("medium", "high")
    )
    if luck_eligible and "luck" in stats:
        try:
            dc = int(action_ctx.get("suggested_dc", 50) or 50)
        except (TypeError, ValueError):
            dc = 50
        dc = max(1, min(100, dc))
        try:
            cap75 = int(cfg.get("luck_mod_cap_high_dc_75", 2) or 2)
        except (TypeError, ValueError):
            cap75 = 2
        raw_luck = _mod_from_stat(stats["luck"], per=per * 0.85, cap=cap)
        if dc >= 85:
            luck_use = 0
        elif dc >= 75:
            if raw_luck > 0:
                luck_use = min(raw_luck, cap75)
            else:
                luck_use = max(raw_luck, -cap75)
        else:
            luck_use = raw_luck
        if luck_use:
            mods.append(("Stat (luck·edge)", luck_use))

    bio = state.get("bio", {}) or {}
    action_ctx["willpower_spiral_check_active"] = False
    if isinstance(bio, dict) and bool(bio.get("mental_spiral", False)) and "willpower" in stats:
        will = int(stats.get("willpower", 50) or 50)
        try:
            slope = float(cfg.get("spiral_willpower_slope", 0.45) or 0.45)
        except (TypeError, ValueError):
            slope = 0.45
        try:
            mx = int(cfg.get("spiral_willpower_max_penalty", 16) or 16)
        except (TypeError, ValueError):
            mx = 16
        pen = int(min(mx, max(0, round((55 - will) * slope))))
        if pen > 0:
            mods.append(("Willpower vs spiral", -pen))
        action_ctx["willpower_spiral_check_active"] = True
