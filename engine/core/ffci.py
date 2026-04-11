"""FFCI (free-form custom intent) — feature flags, feasibility, abuse guard, light consequences.

Engine-owned; no LLM authority. Used from main/modifiers/pipeline.
"""

from __future__ import annotations

import os
from typing import Any, Dict, Optional, Tuple


def ffci_enabled() -> bool:
    return os.getenv("OMNI_FFCI_ENABLED", "1").strip().lower() not in ("0", "false", "no", "off")


def ffci_shadow_only() -> bool:
    return os.getenv("OMNI_FFCI_SHADOW_ONLY", "0").strip().lower() in ("1", "true", "yes", "on")


def clamp_suggested_dc_ctx(action_ctx: dict[str, Any]) -> int:
    try:
        v = int(action_ctx.get("suggested_dc", 50) or 50)
    except (TypeError, ValueError):
        v = 50
    v = max(1, min(100, v))
    action_ctx["suggested_dc"] = v
    return v


def abuse_allow_custom_intent(state: dict[str, Any], action_ctx: dict[str, Any]) -> Tuple[bool, str]:
    """Rate-limit high-stakes custom intents per in-game day. Returns (allowed, reason_code)."""
    if str(action_ctx.get("action_type", "") or "").lower() != "custom":
        return True, ""
    stakes = str(action_ctx.get("stakes", "") or "").lower()
    risk = str(action_ctx.get("risk_level", "") or "").lower()
    high = stakes in ("high", "medium") or risk == "high"
    if not high:
        return True, ""
    meta = state.get("meta", {}) or {}
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
    elif domain == "other":
        meta = state.setdefault("meta", {})
        try:
            tm = int(meta.get("time_min", 0) or 0)
        except (TypeError, ValueError):
            tm = 0
        meta["time_min"] = min(24 * 60 - 1, tm + 5)
        notes.append("[FFCI] Abstract action cost a few minutes of friction.")
