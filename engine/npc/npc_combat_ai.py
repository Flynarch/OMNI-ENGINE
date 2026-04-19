from __future__ import annotations

from engine.core.error_taxonomy import log_swallowed_exception
from typing import Any

from engine.core.balance import get_balance_snapshot
from engine.npc.npcs import _label, add_belief_snippet
from engine.social.ripple_queue import enqueue_ripple


def apply_npc_combat_followup(state: dict[str, Any], action_ctx: dict[str, Any], roll_pkg: dict[str, Any]) -> None:
    """Post-combat: pursuit (player failed), surrender / backup (player succeeded vs NPC targets).

    Integrates with trace, beliefs, and world_notes; deterministic given state + roll outcome.
    """
    if str(action_ctx.get("domain", "") or "") != "combat":
        return
    if action_ctx.get("combat_blocked"):
        return
    if roll_pkg.get("roll") is None:
        return

    outcome = str(roll_pkg.get("outcome", "") or "")
    player_crit = "Critical Success" in outcome
    player_success = "Success" in outcome
    player_fail = ("Failure" in outcome or "Critical Failure" in outcome) and "Success" not in outcome

    targets = action_ctx.get("targets")
    if not isinstance(targets, list) or not targets:
        return
    npcs = state.get("npcs", {}) or {}
    if not isinstance(npcs, dict):
        return

    meta = state.get("meta", {}) or {}
    day = int(meta.get("day", 1) or 1)
    tmin = int(meta.get("time_min", 0) or 0)
    loc = str((state.get("player", {}) or {}).get("location", "") or "").strip().lower()
    snap = get_balance_snapshot(state)
    p_days = max(1, int(snap.get("npc_pursuit_days", 2) or 2))
    sur_thr = max(0, min(100, int(snap.get("npc_surrender_morale", 22) or 22)))
    backup_td = max(0, int(snap.get("npc_backup_trace_delta", 4) or 4))

    for t0 in targets[:4]:
        if not isinstance(t0, str) or t0 not in npcs:
            continue
        npc = npcs[t0]
        if not isinstance(npc, dict):
            continue
        npc.setdefault("combat_morale", 55)
        mor = int(npc.get("combat_morale", 55) or 55)

        if player_success:
            drop = 18 + (10 if player_crit else 0)
            mor = max(0, mor - drop)
            npc["combat_morale"] = mor
            if mor <= sur_thr:
                npc["combat_posture"] = "surrender"
                npc["mood"] = "subdued"
                npc["fear"] = min(100, int(npc.get("fear", 10) or 10) + 22)
                ds = int(npc.get("disposition_score", 50) or 50)
                npc["disposition_score"] = max(0, ds - 12)
                npc["disposition_label"] = _label(int(npc["disposition_score"]))
                state.setdefault("world_notes", []).append(f"[NPC] {t0} surrenders (combat).")
                try:
                    add_belief_snippet(
                        state,
                        npc,
                        topic="player_violence",
                        claim="Combat outcome: forced to surrender.",
                        source="witness",
                        origin="direct",
                        confidence=0.88,
                        bias=-0.1,
                    )
                except Exception as _omni_sw_75:
                    log_swallowed_exception('engine/npc/npc_combat_ai.py:75', _omni_sw_75)
            elif player_crit and mor < 48:
                enqueue_ripple(
                    state,
                    {
                        "kind": "npc_backup_call",
                        "text": f"{t0} calls for backup under fire.",
                        "triggered_day": day,
                        "surface_day": day,
                        "surface_time": min(1439, tmin + 12),
                        "surfaced": False,
                        "propagation": "contacts",
                        "origin_location": loc or "unknown",
                        "origin_faction": str(npc.get("affiliation", "civilian") or "civilian"),
                        "witnesses": [],
                        "surface_attempts": 0,
                    },
                )
                tr = state.setdefault("trace", {})
                tr["trace_pct"] = max(0, min(100, int(tr.get("trace_pct", 0) or 0) + backup_td))
                state.setdefault("world_notes", []).append(f"[NPC] {t0} calls backup (combat).")
        elif player_fail:
            npc["combat_posture"] = "pursuit"
            npc["pursuit_until_day"] = day + p_days
            npc["pursuit_location"] = loc
            tr = state.setdefault("trace", {})
            tr["trace_pct"] = max(0, min(100, int(tr.get("trace_pct", 0) or 0) + 2))
            state.setdefault("world_notes", []).append(f"[NPC] {t0} pursues (active until day {npc['pursuit_until_day']}).")
