from __future__ import annotations

from typing import Any

from engine.news import push_news
from engine.ripple_queue import enqueue_ripple
from engine.rng import roll_for_action


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


def activate_disguise(state: dict[str, Any], persona: str, *, duration_minutes: int = 8 * 60, cost_cash: int = 40) -> bool:
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
    tr["trace_pct"] = max(0, tp - 4)

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
    risk = min(90, risk + 12)
    d["risk"] = risk

    roll = int(roll_for_action(state, action_ctx, salt="caught"))
    caught = roll <= max(5, risk // 2)
    if caught:
        # Heavy consequence: trace spike + broadcast ripple.
        tr = state.setdefault("trace", {})
        tp = int(tr.get("trace_pct", 0) or 0)
        tr["trace_pct"] = max(0, min(100, tp + 18))
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
                "impact": {"trace_delta": +18},
            },
        )
        return True
    return False

