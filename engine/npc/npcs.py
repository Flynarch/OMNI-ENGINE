from __future__ import annotations

from engine.core.error_taxonomy import log_swallowed_exception
from engine.core.modifiers import apply_social_decay
from engine.core.trace import apply_npc_snitch_report_trace
import hashlib
from typing import Any

from engine.npc.memory import (
    SOCIAL_THRESHOLDS,
    get_npc_social_modifiers,
    is_trigger_condition_met,
    update_belief_summary,
    verify_narrative_consistency,
)
from engine.npc.npc_emotions import decay_npc_emotions
from engine.npc.npc_rumor_system import propagate_reputation
from engine.npc.relationship import get_relationship
from engine.social.social_diffusion import record_player_info
from engine.world.heat import bump_heat, bump_suspicion


def _label(score: int) -> str:
    return "Devoted" if score >= 90 else "Friendly" if score >= 70 else "Neutral" if score >= 50 else "Cold" if score >= 30 else "Hostile" if score >= 10 else "Enemy"


def _clamp_int(v: int, lo: int, hi: int) -> int:
    return max(lo, min(hi, int(v)))


def _now(state: dict[str, Any]) -> tuple[int, int, int]:
    meta = state.get("meta", {}) or {}
    return int(meta.get("day", 1) or 1), int(meta.get("time_min", 0) or 0), int(meta.get("turn", 0) or 0)


def _ensure_belief_fields(n: dict[str, Any]) -> None:
    """Ensure belief memory is present for contacts (and safe for others)."""
    bs = n.setdefault("belief_snippets", [])
    if not isinstance(bs, list):
        n["belief_snippets"] = []
    summ = n.setdefault("belief_summary", {})
    if not isinstance(summ, dict):
        summ = {}
        n["belief_summary"] = summ
    summ.setdefault("suspicion", 0)  # 0..100
    summ.setdefault("respect", 50)  # 0..100 (kognitif; beda dari trust Plutchik)
    summ.setdefault("last_turn", 0)


def _ensure_life_fields(n: dict[str, Any], *, default_hp: int = 100) -> None:
    """Ensure NPC life/death fields exist (for cleanup + interaction guards)."""
    n.setdefault("alive", True)
    try:
        alive = bool(n.get("alive", True))
    except Exception as _omni_sw_41:
        log_swallowed_exception('engine/npc/npcs.py:41', _omni_sw_41)
        alive = True
        n["alive"] = True
    if alive:
        try:
            mhp = int(n.get("max_hp", default_hp) or default_hp)
        except Exception as _omni_sw_47:
            log_swallowed_exception('engine/npc/npcs.py:47', _omni_sw_47)
            mhp = default_hp
        mhp = max(1, min(500, mhp))
        n["max_hp"] = mhp
        try:
            hp = int(n.get("hp", mhp) or mhp)
        except Exception as _omni_sw_53:
            log_swallowed_exception('engine/npc/npcs.py:53', _omni_sw_53)
            hp = mhp
        n["hp"] = max(0, min(mhp, hp))
    else:
        # Dead NPCs are non-interactable; keep hp at 0 as canonical.
        n["hp"] = 0
        n.setdefault("max_hp", max(1, int(n.get("max_hp", default_hp) or default_hp)))
        n.setdefault("dead_turn", 0)
        n.setdefault("dead_reason", "unknown")


def _snippet_id(*parts: Any) -> str:
    s = "|".join([str(p) for p in parts])
    h = hashlib.md5(s.encode("utf-8", errors="ignore")).hexdigest()
    return h[:12]


def _h32(*parts: Any) -> int:
    s = "|".join([str(p) for p in parts])
    h = hashlib.md5(s.encode("utf-8", errors="ignore")).hexdigest()
    return int(h[:8], 16)


def _belief_summary_suspicion(npc: dict[str, Any] | None) -> int:
    if not isinstance(npc, dict):
        return 0
    bs = npc.get("belief_summary")
    if not isinstance(bs, dict):
        return 0
    try:
        return max(0, min(100, int(bs.get("suspicion", 0) or 0)))
    except Exception as _omni_sw_84:
        log_swallowed_exception('engine/npc/npcs.py:84', _omni_sw_84)
        return 0


def _remove_social_pending(state: dict[str, Any], npc_id: str, trigger_type: str) -> None:
    pe = state.get("pending_events")
    if not isinstance(pe, list):
        return
    nid = str(npc_id).strip()
    tt = str(trigger_type).strip()
    keep: list[Any] = []
    for ev in pe:
        if (
            isinstance(ev, dict)
            and "turns_to_trigger" in ev
            and str(ev.get("source_npc", "") or "").strip() == nid
            and str(ev.get("type", "") or "").strip() == tt
        ):
            continue
        keep.append(ev)
    state["pending_events"] = keep


def execute_npc_snitch_report(state: dict[str, Any], npc_id: str) -> int:
    """Apply trace spike, log snitch, emit REPORT_FILED, clear reporting pending + active flag."""
    delta = apply_npc_snitch_report_trace(state, str(npc_id))
    state.setdefault("world_notes", []).append(f"[Snitch] NPC {npc_id} has reported your activities to authorities.")
    state.setdefault("world_events", []).append(
        {
            "kind": "REPORT_FILED",
            "npc_id": str(npc_id),
            "source_npc": str(npc_id),
            "text": f"[Report] {npc_id} filed a report with authorities.",
            "day": int((state.get("meta", {}) or {}).get("day", 1) or 1),
        }
    )
    _remove_social_pending(state, str(npc_id), "REPORTING_RISK")
    npc = (state.get("npcs", {}) or {}).get(str(npc_id))
    if isinstance(npc, dict):
        at = npc.setdefault("active_triggers", {})
        if isinstance(at, dict):
            at["REPORTING_RISK"] = False
    return int(delta)


def check_npc_reporting(state: dict[str, Any], npc_id: str) -> bool:
    """15% / turn (deterministic) snitch while REPORTING_RISK is armed and conditions hold."""
    npcs = state.get("npcs", {}) or {}
    if not isinstance(npcs, dict):
        return False
    npc = npcs.get(str(npc_id))
    if not isinstance(npc, dict):
        return False
    tags = npc.get("belief_tags", [])
    if isinstance(tags, list) and "Eternal_Gratitude" in tags:
        return False
    if not is_trigger_condition_met(state, str(npc_id), "REPORTING_RISK"):
        return False
    active = npc.get("active_triggers")
    if not isinstance(active, dict) or active.get("REPORTING_RISK") is not True:
        return False
    meta = state.get("meta", {}) or {}
    seed = str(meta.get("world_seed", "") or "")
    turn = int(meta.get("turn", 0) or 0)
    if _h32(seed, turn, npc_id, "snitch_report") % 100 >= 15:
        return False
    execute_npc_snitch_report(state, str(npc_id))
    return True


def add_belief_snippet(
    state: dict[str, Any],
    npc: dict[str, Any],
    *,
    topic: str,
    claim: str,
    source: str,
    origin: str,
    confidence: float,
    bias: float,
    truthiness: float | None = None,
) -> None:
    """Append a bounded belief snippet and update belief_summary + disposition/trust drift."""
    _ensure_belief_fields(npc)
    day, time_min, turn = _now(state)

    conf = float(max(0.0, min(1.0, confidence)))
    b = float(max(-1.0, min(1.0, bias)))
    tid = _snippet_id(topic, claim, source, origin, day)
    entry = {
        "id": tid,
        "topic": str(topic),
        "claim": str(claim)[:180],
        "source": str(source),
        "origin": str(origin),
        "day": day,
        "time_min": time_min,
        "confidence": round(conf, 3),
        "bias": round(b, 3),
    }
    if truthiness is not None:
        entry["truthiness"] = float(max(0.0, min(1.0, truthiness)))

    # Dedup by id.
    bs = npc.get("belief_snippets") or []
    if isinstance(bs, list):
        for it in bs[-30:]:
            if isinstance(it, dict) and it.get("id") == tid:
                return
    npc["belief_snippets"].append(entry)
    npc["belief_snippets"] = npc["belief_snippets"][-20:]

    # Update belief summary.
    summ = npc.get("belief_summary") or {}
    if not isinstance(summ, dict):
        summ = {}
        npc["belief_summary"] = summ
    sus = _clamp_int(summ.get("suspicion", 0), 0, 100)
    rep = _clamp_int(summ.get("respect", 50), 0, 100)

    # Topic weight: negative topics raise suspicion; positive lower it.
    t = str(topic).lower()
    neg = t in ("player_hacking", "player_trace", "player_violence", "player_crime", "player_lie")
    pos = t in ("player_help", "player_honesty", "player_generosity")
    w = 8
    if t in ("player_trace", "player_violence"):
        w = 12
    if pos:
        w = 10

    # Bias pushes interpretation: negative bias increases suspicion, positive decreases.
    bias_factor = 1.0 + (-b * 0.6)  # b=-1 => +0.6 suspicion; b=+1 => -0.6 suspicion
    delta = int(round(w * conf * bias_factor))
    if neg:
        sus = _clamp_int(sus + delta, 0, 100)
        rep = _clamp_int(rep - int(delta / 2), 0, 100)
    elif pos:
        sus = _clamp_int(sus - int(delta / 2), 0, 100)
        rep = _clamp_int(rep + delta, 0, 100)
    else:
        # neutral info slightly shifts towards confidence: small respect bump
        rep = _clamp_int(rep + int(delta / 4), 0, 100)

    summ["suspicion"] = sus
    summ["respect"] = rep
    summ["last_turn"] = turn

    # Apply small deterministic drift to disposition_score and Plutchik trust.
    try:
        ds = int(npc.get("disposition_score", 50) or 50)
    except Exception as _omni_sw_236:
        log_swallowed_exception('engine/npc/npcs.py:236', _omni_sw_236)
        ds = 50
    try:
        tr = int(npc.get("trust", 50) or 50)
    except Exception as _omni_sw_240:
        log_swallowed_exception('engine/npc/npcs.py:240', _omni_sw_240)
        tr = 50
    # Suspicion high hurts disposition/trust; respect helps.
    ds += int((rep - 50) / 25) - int((sus - 30) / 20)
    tr += int((rep - 50) / 30) - int((sus - 35) / 25)
    npc["disposition_score"] = _clamp_int(ds, 0, 100)
    npc["trust"] = _clamp_int(tr, 0, 100)


def check_social_triggers(state: dict[str, Any], npc_id: str) -> list[str]:
    """Check SOCIAL_THRESHOLDS and schedule one-shot pending ripple events (no spam)."""
    npcs = state.get("npcs", {}) or {}
    if not isinstance(npcs, dict):
        return []
    npc = npcs.get(str(npc_id))
    if not isinstance(npc, dict):
        return []

    active = npc.setdefault("active_triggers", {})
    if not isinstance(active, dict):
        active = {}
        npc["active_triggers"] = active

    sm = get_npc_social_modifiers(state, str(npc_id))
    respect = int(sm.get("respect", 0) or 0)
    try:
        trust = int(npc.get("trust", 50) or 50)
    except Exception as _omni_sw_267:
        log_swallowed_exception('engine/npc/npcs.py:267', _omni_sw_267)
        trust = 50
    trust = max(0, min(100, trust))
    try:
        fear = int(npc.get("fear", 10) or 10)
    except Exception as _omni_sw_272:
        log_swallowed_exception('engine/npc/npcs.py:272', _omni_sw_272)
        fear = 10
    fear = max(0, min(100, fear))
    bs = npc.get("belief_summary") if isinstance(npc.get("belief_summary"), dict) else {}
    if not isinstance(bs, dict):
        bs = {}
    try:
        suspicion = int(bs.get("suspicion", 0) or 0)
    except Exception as _omni_sw_280:
        log_swallowed_exception('engine/npc/npcs.py:280', _omni_sw_280)
        suspicion = 0
    suspicion = max(0, min(100, suspicion))

    fired: list[str] = []
    # Relationship-specific trigger: nemesis applies recurring pressure.
    try:
        rel = get_relationship(state, str(npc_id))
        if str(rel.get("type", "") or "").lower() == "nemesis" and active.get("NEMESIS_PRESSURE") is not True:
            active["NEMESIS_PRESSURE"] = True
            fired.append("NEMESIS_PRESSURE")
            meta = state.get("meta", {}) or {}
            turn = int(meta.get("turn", 0) or 0)
            delay = 1 + (_h32(meta.get("world_seed", ""), npc_id, "NEMESIS_PRESSURE", turn, "delay") % 3)  # 1..3
            ev_id = f"se:{npc_id}:NEMESIS_PRESSURE:{turn}"
            state.setdefault("pending_events", []).append(
                {
                    "id": ev_id,
                    "type": "NEMESIS_PRESSURE",
                    "source_npc": str(npc_id),
                    "turns_to_trigger": int(delay),
                    "payload": {
                        "trigger": "NEMESIS_PRESSURE",
                        "effect": "nemesis_pressure",
                        "strength": int(rel.get("strength", 50) or 50),
                    },
                }
            )
            state.setdefault("world_notes", []).append(f"[Trigger] {npc_id}: NEMESIS_PRESSURE scheduled in {delay}t")
    except Exception as _omni_sw_311:
        log_swallowed_exception('engine/npc/npcs.py:311', _omni_sw_311)
    for key, req in SOCIAL_THRESHOLDS.items():
        if not isinstance(req, dict):
            continue
        if active.get(key) is True:
            continue
        if not is_trigger_condition_met(state, str(npc_id), key):
            continue

        active[key] = True
        fired.append(key)
        meta = state.get("meta", {}) or {}
        turn = int(meta.get("turn", 0) or 0)
        delay = 2 + (_h32(meta.get("world_seed", ""), npc_id, key, turn, "delay") % 4)  # 2..5

        payload: dict[str, Any] = {
            "trigger": key,
            "trust": trust,
            "respect": respect,
            "suspicion": suspicion,
            "fear": fear,
        }
        if key == "BETRAYAL_RISK":
            payload.update({"effect": "spawn_ambush"})
        elif key == "LOYA_REWARD":
            payload.update({"effect": "close_shop"})
        elif key == "SUBMISSIVE_LEAK":
            payload.update({"effect": "submissive_leak"})
        elif key == "REPORTING_RISK":
            payload.update({"effect": "file_report"})
        else:
            payload.update({"effect": "social_event"})

        ev_id = f"se:{npc_id}:{key}:{turn}"
        state.setdefault("pending_events", []).append(
            {"id": ev_id, "type": str(key), "source_npc": str(npc_id), "turns_to_trigger": int(delay), "payload": payload}
        )
        state.setdefault("world_notes", []).append(f"[Trigger] {npc_id}: {key} scheduled in {delay}t")

    npc["active_triggers"] = active
    return fired


def process_pending_events(state: dict[str, Any]) -> dict[str, int]:
    """Countdown social ripple events; defuse if thresholds no longer met; execute at 0.

    Entries with ``turns_to_trigger`` / ``type`` / ``source_npc`` are social-scheduled.
    Other ``pending_events`` shapes are preserved for ``engine.world.timers``.
    """
    pe = state.get("pending_events", []) or []
    if not isinstance(pe, list) or not pe:
        return {"ticked": 0, "executed": 0, "archived": 0, "defused": 0}
    npcs = state.get("npcs", {}) or {}
    if not isinstance(npcs, dict):
        npcs = {}

    ticked = 0
    executed = 0
    archived = 0
    defused = 0
    keep: list[Any] = []

    meta = state.get("meta", {}) or {}
    day = int(meta.get("day", 1) or 1)

    for ev in pe:
        if not isinstance(ev, dict):
            keep.append(ev)
            continue
        if "turns_to_trigger" not in ev or "type" not in ev or "source_npc" not in ev:
            keep.append(ev)
            continue

        src = str(ev.get("source_npc", "") or "").strip()
        et = str(ev.get("type", "") or "").strip()
        if not src or not et:
            keep.append(ev)
            continue

        try:
            ttt = int(ev.get("turns_to_trigger", 0) or 0)
        except Exception as _omni_sw_393:
            log_swallowed_exception('engine/npc/npcs.py:393', _omni_sw_393)
            ttt = 0
        ttt = max(0, min(50, ttt))

        npc_here = npcs.get(src)

        if et == "NEMESIS_PRESSURE":
            if ttt > 0:
                ev2 = dict(ev)
                ev2["turns_to_trigger"] = ttt - 1
                keep.append(ev2)
                ticked += 1
                continue
            executed += 1
            try:
                pl = state.get("player", {}) or {}
                loc0 = str(pl.get("location", "") or "").strip().lower()
                did0 = str(pl.get("district", "") or "").strip().lower()
                pld = ev.get("payload") if isinstance(ev.get("payload"), dict) else {}
                st = int(pld.get("strength", 50) or 50)
                dh = max(2, min(8, st // 15))
                ds = max(3, min(10, st // 12))
                bump_heat(state, loc=loc0, district=did0, delta=int(dh), reason=f"nemesis:{src}", ttl_days=4)
                bump_suspicion(state, loc=loc0, district=did0, delta=int(ds), reason=f"nemesis:{src}", ttl_days=2)
            except Exception as _omni_sw_419:
                log_swallowed_exception('engine/npc/npcs.py:419', _omni_sw_419)
            state.setdefault("world_notes", []).append(f"[Nemesis] {src} escalates pressure around you.")
            state.setdefault("world_events", []).append(
                {
                    "kind": "NEMESIS_EVENT",
                    "type": "NEMESIS_PRESSURE",
                    "source_npc": src,
                    "text": f"[Nemesis] {src} triggered pressure event.",
                    "day": day,
                    "payload": ev.get("payload") if isinstance(ev.get("payload"), dict) else {},
                }
            )
            archived += 1
            npc2 = npcs.get(src)
            if isinstance(npc2, dict):
                at2 = npc2.setdefault("active_triggers", {})
                if isinstance(at2, dict):
                    at2["NEMESIS_PRESSURE"] = False
            continue

        # REPORTING_RISK: defuse if suspicion < 80; hysteresis 80–84 ticks but cannot file until >=85.
        if et == "REPORTING_RISK":
            sus = _belief_summary_suspicion(npc_here if isinstance(npc_here, dict) else None)
            if sus < 80:
                defused += 1
                if isinstance(npc_here, dict):
                    at = npc_here.setdefault("active_triggers", {})
                    if isinstance(at, dict):
                        at[et] = False
                state.setdefault("world_notes", []).append(
                    f"[Ripple Defused] Event {et} for NPC {src} was aborted (suspicion eased below 80; reporting plan cancelled)."
                )
                state.setdefault("world_events", []).append(
                    {
                        "kind": "ABORTED_EVENT",
                        "type": et,
                        "source_npc": src,
                        "text": f"[Aborted] {et} for NPC {src} — suspicion dropped below 80.",
                        "day": day,
                        "payload": ev.get("payload") if isinstance(ev.get("payload"), dict) else {},
                    }
                )
                continue
            if sus < 85:
                if ttt == 0:
                    defused += 1
                    if isinstance(npc_here, dict):
                        at = npc_here.setdefault("active_triggers", {})
                        if isinstance(at, dict):
                            at[et] = False
                    state.setdefault("world_notes", []).append(
                        f"[Ripple Defused] Event {et} for NPC {src} was aborted (deadline reached without filing threshold)."
                    )
                    state.setdefault("world_events", []).append(
                        {
                            "kind": "ABORTED_EVENT",
                            "type": et,
                            "source_npc": src,
                            "text": f"[Aborted] {et} for NPC {src} — suspicion below 85 at deadline.",
                            "day": day,
                            "payload": ev.get("payload") if isinstance(ev.get("payload"), dict) else {},
                        }
                    )
                    continue
                ev2 = dict(ev)
                ev2["turns_to_trigger"] = ttt - 1
                keep.append(ev2)
                ticked += 1
                continue
            if ttt > 0:
                ev2 = dict(ev)
                ev2["turns_to_trigger"] = ttt - 1
                keep.append(ev2)
                ticked += 1
                continue
            executed += 1
            execute_npc_snitch_report(state, src)
            archived += 1
            continue

        if not is_trigger_condition_met(state, src, et):
            defused += 1
            npc = npcs.get(src)
            if isinstance(npc, dict):
                at = npc.setdefault("active_triggers", {})
                if not isinstance(at, dict):
                    at = {}
                    npc["active_triggers"] = at
                at[et] = False
            state.setdefault("world_notes", []).append(
                f"[Ripple Defused] Event {et} for NPC {src} was aborted due to changing social conditions."
            )
            state.setdefault("world_events", []).append(
                {
                    "kind": "ABORTED_EVENT",
                    "type": et,
                    "source_npc": src,
                    "text": f"[Aborted] {et} for NPC {src} — social conditions changed.",
                    "day": day,
                    "payload": ev.get("payload") if isinstance(ev.get("payload"), dict) else {},
                }
            )
            continue

        if ttt > 0:
            ev2 = dict(ev)
            ev2["turns_to_trigger"] = ttt - 1
            keep.append(ev2)
            ticked += 1
            continue

        # Execute at 0
        executed += 1
        payload = ev.get("payload") if isinstance(ev.get("payload"), dict) else {}
        eff = str((payload or {}).get("effect", "") or "").strip().lower()

        npc = npcs.get(src)
        if isinstance(npc, dict):
            if eff == "spawn_ambush":
                try:
                    tr = state.setdefault("trace", {})
                    if isinstance(tr, dict):
                        tr["trace_pct"] = max(0, min(100, int(tr.get("trace_pct", 0) or 0) + 6))
                except Exception as _omni_sw_543:
                    log_swallowed_exception('engine/npc/npcs.py:543', _omni_sw_543)
                state.setdefault("active_ripples", []).append(
                    {
                        "kind": "threat",
                        "text": f"[Threat] {src} set something in motion. An ambush risk is rising.",
                        "triggered_day": day,
                        "surface_day": day,
                        "surface_time": min(1439, int(meta.get("time_min", 0) or 0) + 5),
                        "surfaced": False,
                        "propagation": "local_witness",
                        "origin_location": str((state.get("player", {}) or {}).get("location", "") or "").strip().lower(),
                        "origin_faction": "",
                        "witnesses": [],
                        "surface_attempts": 0,
                        "meta": {"source_npc": src, "event": et},
                    }
                )
                npc["is_active"] = False
            elif eff == "close_shop":
                npc["is_active"] = False
            elif eff == "submissive_leak":
                bs = npc.get("belief_summary") if isinstance(npc.get("belief_summary"), dict) else {}
                if not isinstance(bs, dict):
                    bs = {}
                try:
                    bs["suspicion"] = max(0, min(100, int(bs.get("suspicion", 0) or 0) + 10))
                except Exception as _omni_sw_570:
                    log_swallowed_exception('engine/npc/npcs.py:570', _omni_sw_570)
                    bs["suspicion"] = 50
                npc["belief_summary"] = bs
                state.setdefault("active_ripples", []).append(
                    {
                        "kind": "leak",
                        "text": f"[Leak] {src} quietly shared something damaging about you.",
                        "triggered_day": day,
                        "surface_day": day,
                        "surface_time": min(1439, int(meta.get("time_min", 0) or 0) + 5),
                        "surfaced": False,
                        "propagation": "contacts",
                        "origin_location": str((state.get("player", {}) or {}).get("location", "") or "").strip().lower(),
                        "origin_faction": "",
                        "witnesses": [],
                        "surface_attempts": 0,
                        "meta": {"source_npc": src, "event": et},
                    }
                )

        archived += 1
        state.setdefault("world_events", []).append(
            {
                "kind": "ARCHIVED_EVENT",
                "type": et,
                "source_npc": src,
                "text": f"[Archived] {et} executed for NPC {src}.",
                "day": day,
                "payload": payload,
            }
        )
        state.setdefault("world_notes", []).append(f"[Ripple] Event {et} executed for NPC {src}")

    state["pending_events"] = keep
    return {"ticked": int(ticked), "executed": int(executed), "archived": int(archived), "defused": int(defused)}


def apply_beliefs_from_ripple(state: dict[str, Any], rp: dict[str, Any]) -> None:
    """Update NPC beliefs from a surfaced ripple (only for NPCs who can logically know it)."""
    if not isinstance(rp, dict) or rp.get("dropped_by_propagation"):
        return
    npcs = state.get("npcs", {}) or {}
    if not isinstance(npcs, dict) or not npcs:
        return

    text = str(rp.get("text", "") or "")
    prop = str(rp.get("propagation", "local_witness") or "local_witness").lower()
    origin_loc = str(rp.get("origin_location", "") or "").strip().lower()
    origin_faction = str(rp.get("origin_faction", "") or "").strip().lower()
    witnesses = rp.get("witnesses") if isinstance(rp.get("witnesses"), list) else []
    witnesses = [w for w in witnesses if isinstance(w, str)]

    # Topic inference (v1).
    t_low = text.lower()
    if t_low.startswith("[hack]") or "hack" in t_low:
        topic = "player_hacking"
    elif "manhunt" in t_low or "investigation" in t_low or "checkpoint" in t_low or "trace" in t_low:
        topic = "player_trace"
    elif "strike" in t_low or "raid" in t_low:
        topic = "world_conflict"
    else:
        topic = "world_rumor"

    # Confidence by channel.
    conf_map = {"local_witness": 0.85, "witness": 0.85, "contacts": 0.65, "contact_network": 0.65, "broadcast": 0.75, "faction_network": 0.7}
    confidence = conf_map.get(prop, 0.55)

    # Determine targets who can know it (bounded).
    targets: list[tuple[str, dict[str, Any]]] = []
    if witnesses:
        for w in witnesses[:8]:
            d = npcs.get(w)
            if isinstance(d, dict):
                targets.append((w, d))
    else:
        if prop in ("local", "local_witness", "witness"):
            for name, d in list(npcs.items())[:80]:
                if not isinstance(d, dict):
                    continue
                loc = str(d.get("current_location", "") or "").strip().lower() or str(d.get("home_location", "") or "").strip().lower()
                if origin_loc and loc and loc == origin_loc:
                    targets.append((str(name), d))
            targets = targets[:6]
        elif prop in ("contacts", "contact_network", "broadcast", "faction_network"):
            contacts = (state.get("world", {}) or {}).get("contacts", {}) or {}
            if isinstance(contacts, dict):
                relay_allowed = bool(rp.get("relay_pending") is True)
                for name in list(contacts.keys())[:24]:
                    d = npcs.get(str(name))
                    if not isinstance(d, dict):
                        continue
                    if prop == "faction_network" and origin_faction:
                        aff = str(d.get("affiliation", "") or "").strip().lower()
                        if aff != origin_faction:
                            continue
                    if prop in ("contacts", "contact_network") and origin_faction:
                        aff = str(d.get("affiliation", "") or "").strip().lower()
                        if aff == origin_faction:
                            targets.append((str(name), d))
                            continue
                        if relay_allowed and int(d.get("trust", 0) or 0) >= 85:
                            targets.append((str(name), d))
                    else:
                        targets.append((str(name), d))
            targets = targets[:6]

    if not targets:
        return

    for name, npc in targets:
        # Dead NPCs don't update beliefs.
        try:
            if npc.get("alive") is False or int(npc.get("hp", 1) or 1) <= 0:
                npc["alive"] = False
                npc["hp"] = 0
                continue
        except Exception as _omni_sw_686:
            log_swallowed_exception('engine/npc/npcs.py:686', _omni_sw_686)
        # Bias: faction-aligned NPCs interpret info differently.
        bias = 0.0
        aff = str(npc.get("affiliation", "") or "").strip().lower()
        if origin_faction and aff:
            if aff == origin_faction:
                bias = +0.2  # more charitable to own side
            elif aff in ("police", "corporate", "black_market") and origin_faction in ("police", "corporate", "black_market"):
                bias = -0.15  # rival framing
        add_belief_snippet(
            state,
            npc,
            topic=topic,
            claim=text.replace("\n", " ").strip(),
            source=prop,
            origin=origin_faction or "world",
            confidence=confidence,
            bias=bias,
        )

        # Sync into social_memory (NPC-to-NPC diffusion seeds) without double-applying trust deltas.
        topic_to_cat = {
            "player_hacking": "hack",
            "player_trace": "stealth",
            "world_conflict": "combat",
            "world_rumor": "social",
        }
        icat = topic_to_cat.get(topic, "social")
        try:
            mix = float(confidence) + float(bias) * 0.12
        except Exception as _omni_sw_724b:
            log_swallowed_exception("engine/npc/npcs.py:724b", _omni_sw_724b)
            mix = float(confidence)
        mix = max(0.06, min(0.97, mix))
        try:
            record_player_info(
                state,
                name,
                icat,
                text.replace("\n", " ").strip()[:400],
                confidence=mix,
                apply_trust_delta=False,
            )
        except Exception as _omni_sw_724c:
            log_swallowed_exception("engine/npc/npcs.py:724c", _omni_sw_724c)

        # Optional: rumor spreading (rate-limited, contact-only).
        if npc.get("is_contact") is True and topic in ("player_hacking", "player_trace") and confidence >= 0.65:
            try:
                meta = state.setdefault("meta", {})
                turn = int(meta.get("turn", 0) or 0)
                last = int(meta.get("last_rumor_turn", -999) or -999)
                if turn - last >= 1 and int(npc.get("opportunism", 30) or 0) >= 70:
                    meta["last_rumor_turn"] = turn
                    state.setdefault("active_ripples", []).append(
                        {
                            "text": f"[Rumor] {name}: {text.replace('[', '').replace(']', '')[:90]}",
                            "triggered_day": int(meta.get("day", 1) or 1),
                            "surface_day": int(meta.get("day", 1) or 1) + 1,
                            "surface_time": 8 * 60,
                            "surfaced": False,
                            "propagation": "contacts",
                            "origin_location": origin_loc or str(state.get("player", {}).get("location", "") or "").strip().lower(),
                            "origin_faction": aff or origin_faction or "",
                            "witnesses": [],
                            "surface_attempts": 0,
                        }
                    )
            except Exception as _omni_sw_729:
                log_swallowed_exception('engine/npc/npcs.py:729', _omni_sw_729)
def _ensure_psych_fields(n: dict) -> None:
    """Add NPC psychology fields (safe defaults if missing)."""
    _ensure_life_fields(n)
    n.setdefault("affiliation", "civilian")
    # Plutchik primaries
    n.setdefault("joy", n.get("affection", 0))
    n.setdefault("trust", n.get("trust", n.get("respect", 50)))
    n.setdefault("fear", 10)
    n.setdefault("surprise", 0)
    n.setdefault("sadness", 0)
    n.setdefault("disgust", 0)
    n.setdefault("anger", n.get("resentment", 0))
    n.setdefault("anticipation", n.get("jealousy", 0))
    n.setdefault("opportunism", 30)
    n.setdefault("loyalty", 50)
    n.setdefault("mood", "calm")
    _ensure_belief_fields(n)


def ensure_ambient_npcs(state: dict, action_ctx: dict) -> None:
    """Kalau pemain berinteraksi sosial tapi state kosong, isi NPC keramaian supaya dialog punya anchor."""
    if action_ctx.get("domain") != "social":
        return
    note = action_ctx.get("intent_note", "")
    if note not in ("social_dialogue", "social_scan_crowd", "social_inquiry", "intimacy_private"):
        return
    npcs = state.setdefault("npcs", {})
    if len(npcs) >= 2:
        return
    day = int(state.get("meta", {}).get("day", 1))
    loc = str(state.get("player", {}).get("location", "") or "").strip()
    for name, score in (("Orang di trotoar", 52), ("Pengunjung warung", 48)):
        if name not in npcs:
            npcs[name] = {
                "name": name,
                "alive": True,
                "hp": 100,
                "max_hp": 100,
                "disposition_score": score,
                "disposition_label": _label(score),
                "last_contact_day": day,
                "ambient": True,
                "role": "crowd",
                "home_location": loc,
                "current_location": loc,
                "affiliation": "civilian",
                "joy": 0,
                "trust": 50,
                "fear": 10,
                "surprise": 0,
                "sadness": 0,
                "disgust": 0,
                "anger": 0,
                "anticipation": 0,
                "opportunism": 30,
                "loyalty": 50,
                "mood": "calm",
            }


def update_npcs(state: dict, action_ctx: dict) -> None:
    # Organic news propagation during social talk (rate-limited).
    try:
        if str(action_ctx.get("domain", "") or "").lower() == "social":
            meta = state.get("meta", {}) or {}
            turn = int(meta.get("turn", 0) or 0)
            last = int(meta.get("last_gossip_turn", -999) or -999)
            if turn - last >= 3:
                world = state.get("world", {}) or {}
                news = world.get("news_feed", []) or []
                if isinstance(news, list) and news:
                    pick = None
                    for it in reversed(news[-10:]):
                        if isinstance(it, dict) and it.get("text"):
                            pick = it
                            break
                    if isinstance(pick, dict):
                        txt = str(pick.get("text", "-"))
                        src = str(pick.get("source", "broadcast"))
                        targs = action_ctx.get("targets")
                        if isinstance(targs, list) and targs and isinstance(targs[0], str):
                            npc = (state.get("npcs", {}) or {}).get(targs[0])
                            if isinstance(npc, dict):
                                add_belief_snippet(
                                    state,
                                    npc,
                                    topic="world_news",
                                    claim=txt,
                                    source=f"gossip:{src}",
                                    origin="conversation",
                                    confidence=0.7,
                                    bias=0.0,
                                )
                                try:
                                    update_belief_summary(state, str(targs[0]), raw_interaction_text=str(action_ctx.get("normalized_input", "") or "social talk"))
                                except Exception as _omni_sw_828:
                                    log_swallowed_exception('engine/npc/npcs.py:828', _omni_sw_828)
                                state.setdefault("world_notes", []).append(f"[Gossip] {targs[0]} shares: {txt[:90]}")
                                action_ctx["npc_gossip"] = txt[:140]
                                meta["last_gossip_turn"] = turn
    except Exception as _omni_sw_833:
        log_swallowed_exception('engine/npc/npcs.py:833', _omni_sw_833)
    ensure_ambient_npcs(state, action_ctx)
    try:
        decay_npc_emotions(state)
    except Exception as _omni_sw_840:
        log_swallowed_exception('engine/npc/npcs.py:840', _omni_sw_840)
    day = int(state.get("meta", {}).get("day", 1))
    time_min = int(state.get("meta", {}).get("time_min", 0))
    world_notes = state.setdefault("world_notes", [])
    contacts = state.setdefault("world", {}).setdefault("contacts", {})
    for name, n in state.setdefault("npcs", {}).items():
        if not isinstance(n, dict):
            continue
        n.setdefault("name", name)
        _ensure_psych_fields(n)
        # Dead NPCs don't update disposition/agenda/contacts.
        if n.get("alive") is False or int(n.get("hp", 1) or 1) <= 0:
            n["alive"] = False
            n["hp"] = 0
            continue
        lc = int(n.get("last_contact_day", day))
        if day - lc > 20:
            n["disposition_score"] = max(0, int(n.get("disposition_score", 50)) - 10)
            n["last_contact_day"] = day
            world_notes.append(f"NPC neglect decay: {n['name']} disposition worsened.")
        s = int(n.get("disposition_score", 50))
        n["disposition_label"] = _label(s)

        # Anchor-driven persistence: decay social state toward belief anchors each turn.
        try:
            apply_social_decay(state, str(name))
            verify_narrative_consistency(state, str(name))
        except Exception as _omni_sw_871:
            log_swallowed_exception('engine/npc/npcs.py:871', _omni_sw_871)
        # Social triggers (one-shot): convert social coefficients into world_events.
        try:
            check_social_triggers(state, str(name))
        except Exception as _omni_sw_877:
            log_swallowed_exception('engine/npc/npcs.py:877', _omni_sw_877)
        try:
            check_npc_reporting(state, str(name))
        except Exception as _omni_sw_882:
            log_swallowed_exception('engine/npc/npcs.py:882', _omni_sw_882)
        # Autonomous agenda tick: NPCs act while player does other things.
        agenda = n.get("agenda")
        if agenda and time_min % 120 == 0:
            n["agenda_tick"] = int(n.get("agenda_tick", 0)) + 1
            world_notes.append(f"NPC:{n['name']} advanced agenda: {agenda}")
            # Consistent low-impact disposition drift from autonomous pressure.
            if "hunt" in str(agenda).lower() or "revenge" in str(agenda).lower():
                n["disposition_score"] = max(0, int(n.get("disposition_score", 50)) - 1)
                n["disposition_label"] = _label(int(n["disposition_score"]))

        # Keep global contacts in sync if flagged.
        if isinstance(contacts, dict) and n.get("is_contact") is True:
            contacts[str(name)] = dict(n)

    try:
        process_pending_events(state)
    except Exception as _omni_sw_901:
        log_swallowed_exception('engine/npc/npcs.py:901', _omni_sw_901)
    try:
        propagate_reputation(state)
    except Exception as _omni_sw_908:
        log_swallowed_exception('engine/npc/npcs.py:908', _omni_sw_908)