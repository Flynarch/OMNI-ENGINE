"""Consensual private intimacy aftermath (engine truth): satisfaction roll + player/NPC hooks.

Narration stays fade-to-black via turn prompt; this module only updates state + notes."""

from __future__ import annotations

from typing import Any

from engine.npcs import ensure_ambient_npcs
from engine.npc_emotions import (
    _clamp_int,
    _ensure_primary_fields,
    _secondary_emotions,
    ensure_emotion_state,
    touch_emotion,
)
from engine.rng import roll_for_action


def _tier_from_score(s: int) -> str:
    if s >= 85:
        return "blissful"
    if s >= 65:
        return "warm"
    if s >= 45:
        return "mixed"
    if s >= 25:
        return "awkward"
    return "cold"


def _pick_partner(state: dict[str, Any], action_ctx: dict[str, Any]) -> str | None:
    npcs = state.get("npcs", {}) or {}
    if not isinstance(npcs, dict) or not npcs:
        return None
    targets = action_ctx.get("targets")
    if isinstance(targets, list):
        for t in targets[:4]:
            if isinstance(t, str) and t.strip() in npcs:
                return t.strip()
    ambient = [n for n, v in npcs.items() if isinstance(v, dict) and v.get("ambient") is True]
    if ambient:
        return ambient[0]
    return next(iter(npcs.keys()), None)


def apply_intimacy_aftermath(state: dict[str, Any], action_ctx: dict[str, Any], roll_pkg: dict[str, Any]) -> None:
    if str(action_ctx.get("intent_note", "") or "") != "intimacy_private":
        return
    if str(action_ctx.get("domain", "") or "").lower() != "social":
        return
    if str(action_ctx.get("social_mode", "") or "").lower() == "conflict":
        return

    ensure_ambient_npcs(state, action_ctx)
    partner = _pick_partner(state, action_ctx)
    outcome = str(roll_pkg.get("outcome", "") or "")
    social_ok = any(x in outcome for x in ("Success", "Critical Success"))
    partial = "Failure" in outcome and "Critical" not in outcome

    sat = int(roll_for_action(state, action_ctx, salt="intimacy_satisfaction"))
    if social_ok and "Critical Success" in outcome:
        sat = min(100, sat + 10)
    elif not social_ok and partial:
        sat = max(8, int(sat * 0.45))
    elif not social_ok:
        sat = max(5, int(sat * 0.28))

    tier = _tier_from_score(sat)
    turn = int(state.get("meta", {}).get("turn", 0) or 0)
    meta = state.setdefault("meta", {})
    meta["intimacy_last"] = {
        "turn": turn,
        "partner": partner or "-",
        "satisfaction": sat,
        "tier": tier,
        "social_outcome": outcome,
    }

    # Player: stress relief + light social presence (no explicit vitals).
    bio = state.setdefault("bio", {})
    if isinstance(bio, dict):
        bio["acute_stress"] = False
        try:
            sd = float(bio.get("sleep_debt", 0.0) or 0.0)
            cut = round(min(4.0, (sat / 100.0) * 2.8), 2)
            bio["sleep_debt"] = max(0.0, sd - cut)
        except Exception:
            pass
    p = state.setdefault("player", {})
    stats = p.setdefault("social_stats", {})
    if isinstance(stats, dict):
        spk = int(stats.get("speaking", 0) or 0)
        bonus = 1
        if tier in ("blissful", "warm"):
            bonus = 3
        elif tier == "mixed":
            bonus = 2
        elif tier == "awkward":
            bonus = 0
        elif tier == "cold":
            bonus = -1
        stats["speaking"] = _clamp_int(spk + bonus, -50, 50)

    if partner:
        npcs = state.get("npcs", {}) or {}
        npc = npcs.get(partner) if isinstance(npcs, dict) else None
        if isinstance(npc, dict):
            _ensure_primary_fields(npc)
            ensure_emotion_state(npc)
            j0 = _clamp_int(npc.get("joy", 0), 0, 100)
            t0 = _clamp_int(npc.get("trust", 50), 0, 100)
            mult = sat / 100.0
            dj = int(8 + 18 * mult)
            dt = int(6 + 14 * mult)
            if tier in ("cold", "awkward"):
                dj = max(0, dj // 3)
                dt = max(0, dt // 3)
            npc["joy"] = _clamp_int(j0 + dj, 0, 100)
            npc["trust"] = _clamp_int(t0 + dt, 0, 100)
            npc["fear"] = _clamp_int(int(npc.get("fear", 10) or 10) - int(3 + 5 * mult), 0, 100)
            if tier in ("blissful", "warm"):
                npc["mood"] = "smitten"
                touch_emotion(npc, "joy", severity=min(95, 55 + sat // 4), turn=turn, kind="intimacy_aftermath")
                touch_emotion(npc, "trust", severity=min(90, 50 + sat // 5), turn=turn, kind="intimacy_aftermath")
            elif tier == "mixed":
                npc["mood"] = "thoughtful"
                touch_emotion(npc, "anticipation", severity=40, turn=turn, kind="intimacy_aftermath")
            else:
                npc["mood"] = "awkward"
                touch_emotion(npc, "surprise", severity=35, turn=turn, kind="intimacy_aftermath")

            love = _secondary_emotions(npc).get("love", 0)
            if love >= 72 or _clamp_int(npc.get("trust", 50), 0, 100) >= 70:
                npc["is_contact"] = True
                world = state.setdefault("world", {})
                c = world.setdefault("contacts", {})
                if isinstance(c, dict):
                    c[partner] = dict(npc)

    state.setdefault("world_notes", []).append(
        f"[Intimacy] fade-to-black partner={partner or 'unknown'} satisfaction={sat} tier={tier} engine_note=non-graphic"
    )
