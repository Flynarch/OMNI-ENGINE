from __future__ import annotations

from typing import Any

from engine.social.news import push_news
from engine.social.ripple_queue import enqueue_ripple
from engine.core.rng import roll_for_action
from engine.core.balance import BALANCE, get_balance_snapshot


def ensure_disguise(state: dict[str, Any]) -> dict[str, Any]:
    p = state.setdefault("player", {})
    d = p.setdefault("disguise", {"active": False, "persona": "", "until_day": 0, "until_time": 0, "risk": 0})
    if not isinstance(d, dict):
        d = {"active": False, "persona": "", "until_day": 0, "until_time": 0, "risk": 0}
        p["disguise"] = d
    d.setdefault("active", False)
    d.setdefault("persona", "")
    d.setdefault("until_day", 0)
    d.setdefault("until_time", 0)
    d.setdefault("risk", 0)
    return d


def activate_disguise(
    state: dict[str, Any],
    persona: str,
    *,
    duration_minutes: int = BALANCE.disguise_default_duration_min,
    cost_cash: int = BALANCE.disguise_cost_cash,
) -> bool:
    snap = get_balance_snapshot(state)
    d = ensure_disguise(state)
    meta = state.get("meta", {}) or {}
    day = int(meta.get("day", 1) or 1)
    time_min = int(meta.get("time_min", 0) or 0)
    until_day = day
    until_time = time_min + int(duration_minutes)
    while until_time >= 1440:
        until_time -= 1440
        until_day += 1

    econ = state.setdefault("economy", {})
    cash = int(econ.get("cash", 0) or 0)
    # Allow per-save override via snapshot when caller uses defaults.
    if duration_minutes == BALANCE.disguise_default_duration_min:
        duration_minutes = int(snap.get("disguise_default_duration_min", duration_minutes) or duration_minutes)
    if cost_cash == BALANCE.disguise_cost_cash:
        cost_cash = int(snap.get("disguise_cost_cash", cost_cash) or cost_cash)

    if cash < cost_cash:
        return False
    econ["cash"] = cash - cost_cash

    d["active"] = True
    d["persona"] = str(persona)[:40]
    d["until_day"] = until_day
    d["until_time"] = until_time
    d["risk"] = 0

    # Small immediate trace relief (cover identity).
    tr = state.setdefault("trace", {})
    tp = int(tr.get("trace_pct", 0) or 0)
    tr["trace_pct"] = max(0, tp - int(snap.get("disguise_trace_relief", BALANCE.disguise_trace_relief) or BALANCE.disguise_trace_relief))

    push_news(state, text=f"Persona baru aktif: {d['persona']} (biaya {cost_cash}).", source="contacts")
    enqueue_ripple(
        state,
        {
            "kind": "disguise",
            "text": f"Player mengaktifkan disguise: {d['persona']}.",
            "triggered_day": day,
            "surface_day": day,
            "surface_time": min(1439, time_min + 5),
            "surfaced": False,
            "propagation": "contacts",
            "origin_location": str((state.get('player', {}) or {}).get("location", "") or "").strip().lower(),
            "origin_faction": "",
            "witnesses": [],
            "surface_attempts": 0,
            "meta": {"persona": d["persona"], "until_day": until_day},
        },
    )
    return True


def deactivate_disguise(state: dict[str, Any], *, reason: str = "off") -> None:
    d = ensure_disguise(state)
    if not bool(d.get("active", False)):
        return
    d["active"] = False
    d["persona"] = ""
    d["until_day"] = 0
    d["until_time"] = 0
    d["risk"] = 0
    push_news(state, text=f"Disguise nonaktif ({reason}).", source="contacts")


def tick_disguise_expiry(state: dict[str, Any]) -> None:
    d = ensure_disguise(state)
    if not bool(d.get("active", False)):
        return
    meta = state.get("meta", {}) or {}
    day = int(meta.get("day", 1) or 1)
    time_min = int(meta.get("time_min", 0) or 0)
    if (day, time_min) >= (int(d.get("until_day", 0) or 0), int(d.get("until_time", 0) or 0)):
        deactivate_disguise(state, reason="expired")


def maybe_caught(state: dict[str, Any], action_ctx: dict[str, Any]) -> bool:
    """Deterministic chance to get caught while disguised under police pressure."""
    snap = get_balance_snapshot(state)
    d = ensure_disguise(state)
    if not bool(d.get("active", False)):
        return False
    world = state.get("world", {}) or {}
    loc = str((state.get("player", {}) or {}).get("location", "") or "").strip().lower()
    slot = ((world.get("locations", {}) or {}).get(loc) if isinstance((world.get("locations", {}) or {}), dict) else None)
    restr = (slot.get("restrictions", {}) if isinstance(slot, dict) else {}) or {}
    meta = state.get("meta", {}) or {}
    day = int(meta.get("day", 1) or 1)
    ps = int((restr.get("police_sweep_until_day", 0) if isinstance(restr, dict) else 0) or 0)
    if ps < day:
        return False
    visibility = str(action_ctx.get("visibility", "public") or "public").lower()
    if visibility in ("low", "private", "stealth"):
        return False

    # Risk grows with repeated public actions under sweep.
    risk = int(d.get("risk", 0) or 0)
    risk_cap = int(snap.get("disguise_risk_cap", BALANCE.disguise_risk_cap) or BALANCE.disguise_risk_cap)
    risk_add = int(snap.get("disguise_public_risk_add", BALANCE.disguise_public_risk_add) or BALANCE.disguise_public_risk_add)
    risk = min(risk_cap, risk + risk_add)
    d["risk"] = risk

    roll = int(roll_for_action(state, action_ctx, salt="caught"))
    caught = roll <= max(5, risk // 2)
    if caught:
        # Heavy consequence: trace spike + broadcast ripple.
        tr = state.setdefault("trace", {})
        tp = int(tr.get("trace_pct", 0) or 0)
        spike = int(snap.get("disguise_caught_trace_spike", BALANCE.disguise_caught_trace_spike) or BALANCE.disguise_caught_trace_spike)
        tr["trace_pct"] = max(0, min(100, tp + spike))
        persona = str(d.get("persona", "") or "")
        deactivate_disguise(state, reason="caught")
        push_news(state, text=f"Identitas palsu terbongkar di {loc}.", source="broadcast")
        enqueue_ripple(
            state,
            {
                "kind": "disguise_caught",
                "text": f"Disguise terbongkar ({persona}) di {loc}.",
                "triggered_day": day,
                "surface_day": day,
                "surface_time": min(1439, int(meta.get("time_min", 0) or 0) + 5),
                "surfaced": False,
                "propagation": "broadcast",
                "origin_location": loc,
                "origin_faction": "police",
                "witnesses": [],
                "surface_attempts": 0,
                "meta": {"location": loc, "persona": persona},
                "impact": {"trace_delta": +spike},
            },
        )
        return True
    return False

