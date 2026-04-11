"""FFCI (free-form custom intent) — feature flags, feasibility, abuse guard, light consequences.

Engine-owned; no LLM authority. Used from main/modifiers/pipeline.
"""

from __future__ import annotations

import os
from typing import Any, Dict, Optional, Tuple


def _env_off(name: str, default: str = "1") -> bool:
    return os.getenv(name, default).strip().lower() in ("0", "false", "no", "off")


def ffci_enabled() -> bool:
    """Master switch for LLM-first intent + custom path (roadmap: FF_CUSTOM_INTENT_ENABLED).

    Aliases: OMNI_FFCI_ENABLED (primary), OMNI_FF_CUSTOM_INTENT_ENABLED (plan naming).
    """
    if _env_off("OMNI_FFCI_ENABLED", "1"):
        return False
    if _env_off("OMNI_FF_CUSTOM_INTENT_ENABLED", "1"):
        return False
    return True


def ffci_shadow_only() -> bool:
    """Shadow-only: resolver runs but mechanics stay parser path in main (OMNI_FFCI_SHADOW_ONLY).

    Alias: OMNI_FF_CUSTOM_INTENT_SHADOW_ONLY.
    """
    s = os.getenv("OMNI_FFCI_SHADOW_ONLY", "0").strip().lower()
    if s in ("1", "true", "yes", "on"):
        return True
    return os.getenv("OMNI_FF_CUSTOM_INTENT_SHADOW_ONLY", "0").strip().lower() in ("1", "true", "yes", "on")


def clamp_suggested_dc_ctx(action_ctx: dict[str, Any]) -> int:
    try:
        v = int(action_ctx.get("suggested_dc", 50) or 50)
    except (TypeError, ValueError):
        v = 50
    v = max(1, min(100, v))
    if str(action_ctx.get("action_type", "") or "").lower() == "custom":
        try:
            lo = int(os.getenv("OMNI_FFCI_CUSTOM_DC_MIN", "12") or 12)
            hi = int(os.getenv("OMNI_FFCI_CUSTOM_DC_MAX", "92") or 92)
        except ValueError:
            lo, hi = 12, 92
        lo = max(1, min(98, lo))
        hi = max(lo + 1, min(100, hi))
        v = max(lo, min(hi, v))
    action_ctx["suggested_dc"] = v
    return v


def update_ffci_custom_streak(meta: dict[str, Any], action_ctx: dict[str, Any]) -> None:
    """Count consecutive custom intents for anti-chain abuse (deterministic)."""
    if not isinstance(meta, dict):
        return
    if str(action_ctx.get("action_type", "") or "").lower() == "custom":
        meta["ffci_custom_streak"] = int(meta.get("ffci_custom_streak", 0) or 0) + 1
    else:
        meta["ffci_custom_streak"] = 0


def abuse_allow_custom_intent(state: dict[str, Any], action_ctx: dict[str, Any]) -> Tuple[bool, str]:
    """Rate-limit high-stakes custom intents per in-game day. Returns (allowed, reason_code)."""
    if str(action_ctx.get("action_type", "") or "").lower() != "custom":
        return True, ""
    meta0 = state.setdefault("meta", {})
    try:
        smax = int(os.getenv("OMNI_FFCI_CUSTOM_STREAK_MAX", "14") or 14)
    except ValueError:
        smax = 14
    smax = max(3, min(48, smax))
    if int(meta0.get("ffci_custom_streak", 0) or 0) > smax:
        return False, "ffci_custom_streak"
    stakes = str(action_ctx.get("stakes", "") or "").lower()
    risk = str(action_ctx.get("risk_level", "") or "").lower()
    high = stakes in ("high", "medium") or risk == "high"
    if not high:
        return True, ""
    meta = meta0
    try:
        day = int(meta.get("day", 1) or 1)
    except (TypeError, ValueError):
        day = 1
    try:
        cap = int(os.getenv("OMNI_FFCI_CUSTOM_HIGH_RISK_CAP_PER_DAY", "4") or 4)
    except ValueError:
        cap = 4
    cap = max(1, min(20, cap))
    hist = meta.get("ffci_custom_high_risk_days")
    if not isinstance(hist, dict):
        hist = {}
    cnt = int(hist.get(str(day), 0) or 0)
    if cnt >= cap:
        return False, "ffci_custom_daily_cap"
    return True, ""


def record_custom_high_risk(state: dict[str, Any], action_ctx: dict[str, Any]) -> None:
    if str(action_ctx.get("action_type", "") or "").lower() != "custom":
        return
    stakes = str(action_ctx.get("stakes", "") or "").lower()
    risk = str(action_ctx.get("risk_level", "") or "").lower()
    if stakes not in ("high", "medium") and risk != "high":
        return
    meta = state.setdefault("meta", {})
    try:
        day = int(meta.get("day", 1) or 1)
    except (TypeError, ValueError):
        day = 1
    hist = meta.setdefault("ffci_custom_high_risk_days", {})
    if not isinstance(hist, dict):
        hist = {}
        meta["ffci_custom_high_risk_days"] = hist
    k = str(day)
    hist[k] = int(hist.get(k, 0) or 0) + 1


def feasibility_custom_intent(state: dict[str, Any], action_ctx: dict[str, Any]) -> Optional[Dict[str, Any]]:
    """If custom intent is infeasible, return a no-roll / auto-fail roll package; else None."""
    if str(action_ctx.get("action_type", "") or "").lower() != "custom":
        return None
    if bool(action_ctx.get("scene_locked")):
        return None
    bio = state.get("bio", {}) or {}
    try:
        hunger = float(bio.get("hunger", 0.0) or 0.0)
    except (TypeError, ValueError):
        hunger = 0.0
    domain = str(action_ctx.get("roll_domain", action_ctx.get("domain", "")) or "").lower()
    if hunger >= 92 and domain in ("combat", "hacking", "stealth", "evasion"):
        action_ctx["ffci_gate_reason"] = "critical_hunger"
        return {
            "base": 0,
            "mods": [("FFCI feasibility (critical hunger)", -100)],
            "net_threshold": 0,
            "roll": None,
            "outcome": "No Roll (Too weak to attempt)",
            "net_threshold_locked": True,
            "ffci_feasibility_block": True,
        }
    if bool(bio.get("acute_stress", False)) and domain == "combat":
        if str(action_ctx.get("stakes", "") or "").lower() == "high":
            action_ctx["ffci_gate_reason"] = "acute_stress_combat"
            return {
                "base": 0,
                "mods": [("FFCI feasibility (acute stress)", -100)],
                "net_threshold": 0,
                "roll": None,
                "outcome": "No Roll (Nerves shot)",
                "net_threshold_locked": True,
                "ffci_feasibility_block": True,
            }
    sc = state.get("active_scene")
    if isinstance(sc, dict) and str(sc.get("kind", "") or "").lower() in ("arrest", "police_stop") and domain in (
        "hacking",
        "combat",
    ):
        action_ctx["ffci_gate_reason"] = "scene_arrest"
        return {
            "base": 0,
            "mods": [("FFCI feasibility (custody/scene)", -100)],
            "net_threshold": 0,
            "roll": None,
            "outcome": "No Roll (Situation prevents that)",
            "net_threshold_locked": True,
            "ffci_feasibility_block": True,
        }
    # Severe sleep debt: block high-exertion custom intents.
    try:
        sd = float(bio.get("sleep_debt", 0.0) or 0.0)
    except (TypeError, ValueError):
        sd = 0.0
    try:
        sd_gate = float(os.getenv("OMNI_FFCI_SLEEP_DEBT_GATE", "12") or 12)
    except ValueError:
        sd_gate = 12.0
    if sd >= sd_gate and domain in ("combat", "hacking", "stealth"):
        action_ctx["ffci_gate_reason"] = "severe_exhaustion"
        return {
            "base": 0,
            "mods": [("FFCI feasibility (exhaustion)", -100)],
            "net_threshold": 0,
            "roll": None,
            "outcome": "No Roll (Too exhausted)",
            "net_threshold_locked": True,
            "ffci_feasibility_block": True,
        }
    # Mental spiral + high-stakes social custom: infeasible until stabilized.
    if bool(bio.get("mental_spiral", False)) and domain == "social":
        st = str(action_ctx.get("stakes", "") or "").lower()
        if st in ("high", "medium"):
            action_ctx["ffci_gate_reason"] = "mental_spiral_social"
            return {
                "base": 0,
                "mods": [("FFCI feasibility (mental spiral)", -100)],
                "net_threshold": 0,
                "roll": None,
                "outcome": "No Roll (Head not in the game)",
                "net_threshold_locked": True,
                "ffci_feasibility_block": True,
            }
    return None


def apply_custom_intent_consequences(state: dict[str, Any], action_ctx: dict[str, Any], roll_pkg: dict[str, Any]) -> None:
    """Baseline heat/trace/time notes for custom intents (bounded, deterministic)."""
    if str(action_ctx.get("action_type", "") or "").lower() != "custom":
        return
    if bool(roll_pkg.get("ffci_feasibility_block")):
        return
    domain = str(action_ctx.get("domain", "") or "").lower()
    outcome = str(roll_pkg.get("outcome", "") or "")
    failed = "fail" in outcome.lower() or outcome.startswith("Auto Fail")
    notes = state.setdefault("world_notes", [])
    tr = state.setdefault("trace", {})
    try:
        cur = int(tr.get("trace_pct", 0) or 0)
    except (TypeError, ValueError):
        cur = 0
    if domain == "stealth" and failed:
        tr["trace_pct"] = min(100, cur + 2)
        notes.append("[FFCI] Custom stealth attempt left extra exposure.")
    elif domain == "hacking" and failed:
        tr["trace_pct"] = min(100, cur + 3)
        notes.append("[FFCI] Custom hack attempt increased digital footprint.")
    elif domain == "social" and not failed:
        notes.append("[FFCI] Custom social play shifted local attention slightly.")
    elif domain == "social" and failed:
        tr["trace_pct"] = min(100, cur + 1)
        notes.append("[FFCI] Custom social misfire drew a little scrutiny.")
    elif domain == "hacking" and not failed:
        tr["trace_pct"] = min(100, cur + 1)
        notes.append("[FFCI] Custom hack left a faint trail even on success.")
    elif domain == "other":
        meta = state.setdefault("meta", {})
        try:
            tm = int(meta.get("time_min", 0) or 0)
        except (TypeError, ValueError):
            tm = 0
        meta["time_min"] = min(24 * 60 - 1, tm + 5)
        notes.append("[FFCI] Abstract action cost a few minutes of friction.")
