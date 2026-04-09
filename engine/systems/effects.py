from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal


StackingRule = Literal["refresh", "stack", "replace"]


@dataclass(frozen=True)
class EffectSpec:
    id: str
    kind: str
    stacks: int
    until_day: int
    until_time: int
    source: str
    meta: dict[str, Any]


def _now(state: dict[str, Any]) -> tuple[int, int, int]:
    meta = state.get("meta", {}) or {}
    return int(meta.get("day", 1) or 1), int(meta.get("time_min", 0) or 0), int(meta.get("turn", 0) or 0)


def _is_expired(now_day: int, now_time: int, until_day: int, until_time: int) -> bool:
    return (int(until_day), int(until_time)) <= (int(now_day), int(now_time))


def _ensure_effects_list(container: dict[str, Any]) -> list[dict[str, Any]]:
    eff = container.setdefault("effects", [])
    if not isinstance(eff, list):
        eff = []
        container["effects"] = eff
    # normalize items
    out: list[dict[str, Any]] = []
    for e in eff[:80]:
        if isinstance(e, dict) and e.get("id"):
            out.append(e)
    container["effects"] = out
    return out


def add_effect(
    state: dict[str, Any],
    *,
    target: dict[str, Any],
    effect_id: str,
    kind: str,
    duration_min: int,
    stacks: int = 1,
    max_stacks: int = 5,
    stacking: StackingRule = "refresh",
    source: str = "system",
    meta: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Add/stack/refresh an effect on target (player or npc dict).

    Deterministic: uses current sim time only.
    """
    eid = str(effect_id or "").strip().lower()
    k = str(kind or "").strip().lower()
    if not eid or not k:
        return {"ok": False, "reason": "missing_id_or_kind"}
    try:
        dur = int(duration_min or 0)
    except Exception:
        dur = 0
    dur = max(1, min(24 * 60, dur))
    try:
        st = int(stacks or 1)
    except Exception:
        st = 1
    st = max(1, min(20, st))
    mx = max(1, min(20, int(max_stacks or 5)))
    st_rule: StackingRule = stacking if stacking in ("refresh", "stack", "replace") else "refresh"
    src = str(source or "system")[:40]
    md = dict(meta) if isinstance(meta, dict) else {}

    day, tmin, _turn = _now(state)
    until_time = int(tmin) + dur
    until_day = int(day)
    while until_time >= 1440:
        until_time -= 1440
        until_day += 1

    effs = _ensure_effects_list(target)
    existing = None
    for e in effs:
        if isinstance(e, dict) and str(e.get("id", "")).strip().lower() == eid:
            existing = e
            break

    if existing is None:
        effs.append(
            {
                "id": eid,
                "kind": k,
                "stacks": min(mx, st),
                "until_day": int(until_day),
                "until_time": int(until_time),
                "source": src,
                "meta": md,
            }
        )
        return {"ok": True, "action": "added", "id": eid, "stacks": min(mx, st)}

    # update existing
    cur_stacks = int(existing.get("stacks", 1) or 1)
    if st_rule == "stack":
        existing["stacks"] = min(mx, cur_stacks + st)
        # refresh expiry on stack
        existing["until_day"] = int(until_day)
        existing["until_time"] = int(until_time)
    elif st_rule == "replace":
        existing["stacks"] = min(mx, st)
        existing["until_day"] = int(until_day)
        existing["until_time"] = int(until_time)
    else:  # refresh
        existing["stacks"] = min(mx, max(cur_stacks, st))
        existing["until_day"] = int(until_day)
        existing["until_time"] = int(until_time)
    existing["kind"] = k
    existing["source"] = src
    existing["meta"] = md
    return {"ok": True, "action": "updated", "id": eid, "stacks": int(existing.get("stacks", 1) or 1)}


def tick_effects_expiry(state: dict[str, Any]) -> None:
    """Expire effects for player + NPCs."""
    day, tmin, _turn = _now(state)

    # Player
    player = state.get("player", {}) or {}
    if isinstance(player, dict):
        effs = _ensure_effects_list(player)
        kept: list[dict[str, Any]] = []
        for e in effs:
            try:
                ud = int(e.get("until_day", 0) or 0)
                ut = int(e.get("until_time", 0) or 0)
            except Exception:
                ud, ut = 0, 0
            if not _is_expired(day, tmin, ud, ut):
                kept.append(e)
        player["effects"] = kept

    # NPCs
    npcs = state.get("npcs", {}) or {}
    if isinstance(npcs, dict):
        for _name, npc in list(npcs.items())[:250]:
            if not isinstance(npc, dict):
                continue
            effs = _ensure_effects_list(npc)
            kept2: list[dict[str, Any]] = []
            for e in effs:
                try:
                    ud = int(e.get("until_day", 0) or 0)
                    ut = int(e.get("until_time", 0) or 0)
                except Exception:
                    ud, ut = 0, 0
                if not _is_expired(day, tmin, ud, ut):
                    kept2.append(e)
            npc["effects"] = kept2

