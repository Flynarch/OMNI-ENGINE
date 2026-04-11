"""Post-turn integration fabric hooks: journal, bus, reconciler, policies, incident, memory."""

from __future__ import annotations

import os
from typing import Any, Dict, List

from engine.core import error_taxonomy as EC
from engine.core.mutation_gateway import append_world_note
from engine.core.tuning_pack import tuning_int


def append_state_change_journal(
    state: dict[str, Any],
    *,
    turn: int,
    summary: str,
    keys_touched: List[str] | None = None,
) -> None:
    meta = state.setdefault("meta", {})
    j = meta.setdefault("state_change_journal", [])
    if not isinstance(j, list):
        j = []
        meta["state_change_journal"] = j
    entry = {
        "turn": int(turn),
        "summary": str(summary or "")[:240],
        "keys": [str(k)[:48] for k in (keys_touched or [])[:24]],
    }
    j.append(entry)
    if len(j) > 200:
        del j[:-200]


def publish_integration_event(state: dict[str, Any], event_type: str, payload: dict[str, Any]) -> None:
    meta = state.setdefault("meta", {})
    bus = meta.setdefault("integration_event_bus_tail", [])
    if not isinstance(bus, list):
        bus = []
        meta["integration_event_bus_tail"] = bus
    evt = {
        "event_type": str(event_type)[:80],
        "source": "engine",
        "payload": dict(payload or {}),
        "turn": int(meta.get("turn", 0) or 0),
    }
    bus.append(evt)
    if len(bus) > 80:
        del bus[:-80]


def record_causal_edge(state: dict[str, Any], src: str, dst: str, label: str = "") -> None:
    meta = state.setdefault("meta", {})
    g = meta.setdefault("causal_link_graph_tail", [])
    if not isinstance(g, list):
        g = []
        meta["causal_link_graph_tail"] = g
    g.append(
        {
            "src": str(src)[:80],
            "dst": str(dst)[:80],
            "label": str(label)[:80],
            "turn": int(meta.get("turn", 0) or 0),
        }
    )
    if len(g) > 120:
        del g[:-120]


def reconcile_cross_system(state: dict[str, Any]) -> List[str]:
    """Lightweight invariant checks; returns warning codes."""
    warns: List[str] = []
    tr = state.get("trace", {}) or {}
    try:
        p = int(tr.get("trace_pct", 0) or 0)
    except (TypeError, ValueError):
        p = 0
    if p < 0 or p > 100:
        warns.append(EC.RECONCILER_WARN + ":trace_pct_range")
        tr["trace_pct"] = max(0, min(100, p))
    eco = state.get("economy", {}) or {}
    for k in ("cash", "bank"):
        try:
            v = int(eco.get(k, 0) or 0)
        except (TypeError, ValueError):
            v = 0
        if v < 0:
            warns.append(EC.RECONCILER_WARN + f":{k}_negative")
            eco[k] = 0
    return warns


def apply_cross_system_policies(state: dict[str, Any], action_ctx: dict[str, Any]) -> None:
    """Conservative cross-surface hints (no hard blocks)."""
    bio = state.get("bio", {}) or {}
    tr = state.get("trace", {}) or {}
    try:
        hunger = float(bio.get("hunger", 0) or 0)
    except (TypeError, ValueError):
        hunger = 0.0
    try:
        tp = int(tr.get("trace_pct", 0) or 0)
    except (TypeError, ValueError):
        tp = 0
    if hunger >= 88 and tp >= 70:
        action_ctx["cross_policy_note"] = "high_pressure_street"


def incident_playbook_check(state: dict[str, Any]) -> None:
    """Escalate soft operational signals when counters exceed env thresholds."""
    meta = state.setdefault("meta", {})
    try:
        thr = int(os.getenv("OMNI_INCIDENT_FALLBACK_STREAK", "12") or 12)
    except ValueError:
        thr = 12
    thr = max(4, min(200, thr))
    fb = int(meta.get("parser_fallback_streak", 0) or 0)
    src = str(meta.get("last_intent_source", "") or "")
    if src == "parser_fallback":
        fb += 1
    else:
        fb = 0
    meta["parser_fallback_streak"] = fb
    if fb >= thr:
        meta["incident_escalation"] = True
        append_world_note(state, "[Ops] Elevated parser fallback streak — consider shadow-only / review intent logs.")


def update_narrative_consistency_memory(state: dict[str, Any], action_ctx: dict[str, Any]) -> None:
    meta = state.setdefault("meta", {})
    note = str(action_ctx.get("intent_note", "") or "").strip()
    if not note:
        return
    decay = tuning_int("narrative_anchor_decay_turns", 8)
    decay = max(1, min(48, decay))
    cur = meta.get("narrative_consistency")
    if not isinstance(cur, dict):
        cur = {}
    cur["anchor"] = note[:120]
    cur["turns_left"] = decay
    meta["narrative_consistency"] = cur


def decay_narrative_memory(state: dict[str, Any]) -> None:
    meta = state.setdefault("meta", {})
    cur = meta.get("narrative_consistency")
    if not isinstance(cur, dict):
        return
    try:
        left = int(cur.get("turns_left", 0) or 0)
    except (TypeError, ValueError):
        left = 0
    left = max(0, left - 1)
    cur["turns_left"] = left
    if left <= 0:
        cur.pop("anchor", None)
    meta["narrative_consistency"] = cur


def update_intent_style_memory(state: dict[str, Any], cmd: str, action_ctx: dict[str, Any]) -> None:
    meta = state.setdefault("meta", {})
    hints = meta.setdefault("intent_style_hints", [])
    if not isinstance(hints, list):
        hints = []
        meta["intent_style_hints"] = hints
    frag = str(cmd or "").strip().lower()[:48]
    if len(frag) < 4:
        return
    dom = str(action_ctx.get("domain", "") or "").lower()
    for h in hints:
        if isinstance(h, dict) and str(h.get("frag", "")).lower() == frag:
            h["count"] = int(h.get("count", 0) or 0) + 1
            return
    hints.append({"frag": frag, "domain": dom, "count": 1})
    if len(hints) > 40:
        del hints[:-40]


def record_economy_ledger_line(state: dict[str, Any], kind: str, delta_cash: int, detail: str = "") -> None:
    meta = state.setdefault("meta", {})
    led = meta.setdefault("economy_ledger_tail", [])
    if not isinstance(led, list):
        led = []
        meta["economy_ledger_tail"] = led
    led.append(
        {
            "day": int(meta.get("day", 1) or 1),
            "turn": int(meta.get("turn", 0) or 0),
            "kind": str(kind)[:40],
            "delta_cash": int(delta_cash),
            "detail": str(detail)[:120],
        }
    )
    if len(led) > 60:
        del led[:-60]


def update_custom_balance_ema(state: dict[str, Any], action_ctx: dict[str, Any], roll_pkg: dict[str, Any]) -> None:
    if str(action_ctx.get("action_type", "") or "").lower() != "custom":
        return
    meta = state.setdefault("meta", {})
    dom = str(action_ctx.get("domain", "") or "").lower() or "other"
    ema = meta.setdefault("custom_domain_balance_ema", {})
    if not isinstance(ema, dict):
        ema = {}
        meta["custom_domain_balance_ema"] = ema
    tri = None
    oc = str(roll_pkg.get("outcome", "") or "").lower()
    if "success" in oc:
        tri = 1.0
    elif "fail" in oc:
        tri = 0.0
    if tri is None:
        return
    try:
        prev = float(ema.get(dom, 0.5) or 0.5)
    except (TypeError, ValueError):
        prev = 0.5
    ema[dom] = round(prev * 0.85 + tri * 0.15, 4)
    if len(ema) > 16:
        for k in list(ema.keys())[:-16]:
            ema.pop(k, None)


def post_turn_integration(
    state: dict[str, Any],
    action_ctx: dict[str, Any],
    roll_pkg: dict[str, Any],
    *,
    player_cmd: str,
    metrics_before: dict[str, Any],
    metrics_after: dict[str, Any],
) -> None:
    meta = state.setdefault("meta", {})
    turn = int(meta.get("turn", 0) or 0)
    decay_narrative_memory(state)
    update_narrative_consistency_memory(state, action_ctx)
    if str(meta.get("last_intent_source", "") or "") == "llm":
        update_intent_style_memory(state, player_cmd, action_ctx)

    keys: List[str] = []
    for k in ("trace_pct", "cash", "time_min"):
        if metrics_before.get(k) != metrics_after.get(k):
            keys.append(k)
    append_state_change_journal(
        state,
        turn=turn,
        summary=f"{action_ctx.get('action_type')}/{action_ctx.get('domain')}",
        keys_touched=keys,
    )
    publish_integration_event(
        state,
        "turn_closed",
        {
            "action_type": action_ctx.get("action_type"),
            "domain": action_ctx.get("domain"),
            "intent_source": meta.get("last_intent_source"),
        },
    )
    record_causal_edge(
        state,
        str(action_ctx.get("intent_note", "action") or "action")[:40],
        str(roll_pkg.get("outcome", "outcome") or "")[:40],
    )
    warns = reconcile_cross_system(state)
    for w in warns[:6]:
        append_world_note(state, f"[Reconciler] {w}")
    incident_playbook_check(state)
    update_custom_balance_ema(state, action_ctx, roll_pkg if isinstance(roll_pkg, dict) else {})

    cap_idx = meta.setdefault("system_capability_index", {})
    if not isinstance(cap_idx, dict):
        cap_idx = {}
        meta["system_capability_index"] = cap_idx
    cap_idx["last_action_type"] = str(action_ctx.get("action_type", "") or "")
    cap_idx["last_domain"] = str(action_ctx.get("domain", "") or "")

    try:
        from engine.core.intent_plan_runtime import advance_plan_runtime_after_roll

        advance_plan_runtime_after_roll(state, action_ctx, roll_pkg if isinstance(roll_pkg, dict) else {})
    except Exception:
        pass
