"""Unified turn telemetry snapshot (roadmap: observability / integration fabric hook).

Engine-owned dict shape; safe defaults. Narrator must not invent these fields.
"""

from __future__ import annotations

from typing import Any

# Canonical keys for cross-module analytics (subset; extend additively).
TURN_TELEMETRY_KEYS: frozenset[str] = frozenset(
    {
        "intent_source",
        "domain_raw",
        "domain_norm",
        "action_type",
        "fallback_reason",
        "custom_path_used",
        "risk_tag",
        "roll_outcome_preview",
        "effect_keys",
    }
)


def _risk_tag(action_ctx: dict[str, Any]) -> str:
    st = str(action_ctx.get("stakes", "") or "").lower()
    rk = str(action_ctx.get("risk_level", "") or "").lower()
    if st == "high" or rk == "high":
        return "high"
    if st in ("medium", "high") or rk == "medium":
        return "medium"
    return "low"


def snapshot_turn_telemetry(
    state: dict[str, Any],
    action_ctx: dict[str, Any],
    roll_pkg: dict[str, Any] | None,
) -> dict[str, Any]:
    meta = state.get("meta", {}) or {}
    out: dict[str, Any] = {
        "intent_source": str(meta.get("last_intent_source", "") or ""),
        "domain_raw": str(meta.get("llm_domain_raw", "") or ""),
        "domain_norm": str(meta.get("normalized_domain", "") or str(action_ctx.get("domain", "") or "")).lower(),
        "action_type": str(action_ctx.get("action_type", "") or "").lower(),
        "fallback_reason": str(meta.get("fallback_reason", "") or "") if meta.get("fallback_reason") else "",
        "custom_path_used": bool(meta.get("custom_path_used", False)),
        "risk_tag": _risk_tag(action_ctx),
        "roll_outcome_preview": "",
        "effect_keys": [],
    }
    if isinstance(roll_pkg, dict):
        oc = str(roll_pkg.get("outcome", "") or "")
        out["roll_outcome_preview"] = oc[:120]
        ek: list[str] = []
        if bool(roll_pkg.get("ffci_feasibility_block")):
            ek.append("ffci_feasibility_block")
        if bool(roll_pkg.get("net_threshold_locked")):
            ek.append("net_threshold_locked")
        if bool(action_ctx.get("intent_plan_blocked")):
            ek.append("intent_plan_blocked")
        out["effect_keys"] = ek
    return out


def merge_telemetry_turn_last(state: dict[str, Any], snap: dict[str, Any]) -> None:
    """Store last turn snapshot on meta (bounded, JSON-serializable)."""
    if not isinstance(snap, dict):
        return
    meta = state.setdefault("meta", {})
    clean = {k: snap[k] for k in TURN_TELEMETRY_KEYS if k in snap}
    meta["telemetry_turn_last"] = clean
