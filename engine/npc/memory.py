from __future__ import annotations

from engine.core.error_taxonomy import log_swallowed_exception
from typing import Any


def _clamp_int(v: Any, lo: int, hi: int, default: int) -> int:
    try:
        n = int(v)
    except Exception as _omni_sw_9:
        log_swallowed_exception('engine/npc/memory.py:9', _omni_sw_9)
        n = int(default)
    return max(int(lo), min(int(hi), int(n)))


def _norm_s(v: Any) -> str:
    return str(v or "").strip()


# Belief tag semantic mapping -> social coefficients (clamped later to -100..100).
BELIEF_TAG_SOCIAL_MODS: dict[str, dict[str, int]] = {
    # Core requested mappings
    "Deep_Grudge": {"respect": -50, "trust": -60, "suspicion": +40, "fear": 0},
    "Eternal_Gratitude": {"respect": +60, "trust": +70, "suspicion": -30, "fear": 0},
    "Core_Belief_Violence": {"respect": -20, "trust": 0, "suspicion": +10, "fear": +40},
    # Additional RPG tropes
    "Debtor": {"respect": -10, "trust": -25, "suspicion": +15, "fear": 0},
    "Informant_Loyalty": {"respect": +15, "trust": +35, "suspicion": -10, "fear": 0},
    "Blackmail_Leverage": {"respect": -25, "trust": -40, "suspicion": +30, "fear": +10},
}


# Belief anchors act as hard constraints on the final coefficients.
BELIEF_ANCHORS: dict[str, dict[str, int]] = {
    "Deep_Grudge": {"max_trust": 30, "min_suspicion": 50},
    "Eternal_Gratitude": {"min_trust": 50, "max_suspicion": 20},
    "Blackmail_Leverage": {"min_fear": 40},
    "Debtor": {"min_respect": -20, "max_trust": 70},
}


SOCIAL_THRESHOLDS: dict[str, dict[str, int]] = {
    "BETRAYAL_RISK": {"suspicion": 90, "trust": 10},
    "LOYA_REWARD": {"trust": 85, "respect": 60},
    "SUBMISSIVE_LEAK": {"fear": 70, "respect": -30},
    "REPORTING_RISK": {"suspicion": 85},
}


def _rumor_tag_line(state: dict[str, Any], npc_id: str) -> str:
    """Narrative hint when this NPC's suspicion was bumped by gossip this turn."""
    npcs = state.get("npcs", {}) or {}
    if not isinstance(npcs, dict):
        return ""
    npc = npcs.get(str(npc_id))
    if not isinstance(npc, dict):
        return ""
    meta = state.get("meta", {}) or {}
    turn = int(meta.get("turn", 0) or 0)
    try:
        rt = int(npc.get("rumor_influence_turn", -1_000_000) or -1_000_000)
    except Exception as _omni_sw_60:
        log_swallowed_exception('engine/npc/memory.py:60', _omni_sw_60)
        rt = -1_000_000
    if rt != turn:
        return ""
    return (
        "[RUMOR] Desas-desus tentang reputasi pemain baru menyebar ke NPC ini lewat gosip internal; "
        "tampilkan sikap lebih waspada halus — tanpa menyebut angka atau level."
    )


def _merge_narrative_bits(*bits: str) -> str:
    out = " ".join(b.strip() for b in bits if isinstance(b, str) and b.strip())
    return out


def _reporting_risk_narrative_line(state: dict[str, Any], npc_id: str) -> str:
    if not is_trigger_condition_met(state, str(npc_id), "REPORTING_RISK"):
        return ""
    return (
        "[REPORTING_RISK] NPC ini terlihat gelisah dan terus memperhatikan teleponnya "
        "atau petugas keamanan di sekitar."
    )


def _foreshadow_pending_line(state: dict[str, Any], npc_id: str) -> str:
    pe = state.get("pending_events", []) or []
    if not isinstance(pe, list) or not pe:
        return ""
    cand: list[tuple[int, str, str]] = []
    nid = str(npc_id).strip()
    for e in pe:
        if not isinstance(e, dict):
            continue
        if str(e.get("source_npc", "") or "").strip() != nid:
            continue
        if "turns_to_trigger" not in e:
            continue
        try:
            ttt = int(e.get("turns_to_trigger", 0) or 0)
        except Exception as _omni_sw_99:
            log_swallowed_exception('engine/npc/memory.py:99', _omni_sw_99)
            ttt = 0
        et = str(e.get("type", "") or "").strip() or "unknown"
        eid = str(e.get("id", "") or "")
        cand.append((max(0, min(50, ttt)), eid, et))
    if not cand:
        return ""
    cand.sort(key=lambda x: (x[0], x[1]))
    ttt, _, et = cand[0]
    return (
        f"[FORESHADOWING] NPC ini sedang merencanakan {et} dalam {ttt} turn. "
        "Perlihatkan gelagat gugup, mencurigakan, atau bersiap-siap dalam narasimu."
    )


def update_belief_summary(state: dict[str, Any], npc_id: str, raw_interaction_text: str) -> bool:
    """Formal entrypoint: synthesize an anchor-safe belief_summary.text from latest interaction.

    Deterministic: does not call the LLM. It produces a stable, bounded summary string while
    enforcing that anchors are reflected and never contradicted.
    """
    npcs = state.get("npcs", {}) or {}
    if not isinstance(npcs, dict):
        return False
    npc = npcs.get(str(npc_id))
    if not isinstance(npc, dict):
        return False

    anchor = get_narrative_anchor_context(state, str(npc_id))
    tags = npc.get("belief_tags", [])
    if not isinstance(tags, list):
        tags = []

    # Build an anchor-locked summary line.
    raw = str(raw_interaction_text or "").strip()
    raw = " ".join(raw.split())  # normalize whitespace
    if len(raw) > 240:
        raw = raw[:240]

    tag_line = ", ".join([str(x) for x in tags[:4] if str(x).strip()])
    if tag_line:
        tag_line = f"Beliefs={tag_line}."
    else:
        tag_line = "Beliefs=(none)."
    # Mandatory constraint: include anchor line when present.
    text = f"{tag_line} {anchor} LastInteraction: {raw}" if anchor else f"{tag_line} LastInteraction: {raw}"

    bs = npc.setdefault("belief_summary", {})
    if not isinstance(bs, dict):
        bs = {}
        npc["belief_summary"] = bs
    bs["text"] = text[:360]
    npc["belief_summary"] = bs
    return True

def get_behavioral_anchors(state: dict[str, Any], npc_id: str) -> dict[str, int]:
    """Return the most constraining anchor limits for the NPC based on belief_tags."""
    npcs = state.get("npcs", {}) or {}
    if not isinstance(npcs, dict):
        return {}
    npc = npcs.get(str(npc_id))
    if not isinstance(npc, dict):
        return {}
    tags = npc.get("belief_tags", [])
    if not isinstance(tags, list) or not tags:
        return {}

    out: dict[str, int] = {}
    for raw in tags[:16]:
        tag = str(raw or "").strip()
        if not tag:
            continue
        a = BELIEF_ANCHORS.get(tag)
        if not isinstance(a, dict):
            continue
        for k, v in a.items():
            try:
                n = int(v)
            except Exception as _omni_sw_177:
                log_swallowed_exception('engine/npc/memory.py:177', _omni_sw_177)
                continue
            if k.startswith("min_"):
                out[k] = max(int(out.get(k, -10_000)), n)
            elif k.startswith("max_"):
                out[k] = min(int(out.get(k, 10_000)), n)
            else:
                out[k] = n
    # Normalize: if min>max, keep the stricter bound (collapse to min).
    for dim in ("trust", "respect", "suspicion", "fear"):
        mn = out.get(f"min_{dim}")
        mx = out.get(f"max_{dim}")
        if isinstance(mn, int) and isinstance(mx, int) and mn > mx:
            out[f"max_{dim}"] = int(mn)
    return out


def get_narrative_anchor_context(state: dict[str, Any], npc_id: str) -> str:
    """Return a small deterministic prompt fragment for the narrator."""
    npcs = state.get("npcs", {}) or {}
    if not isinstance(npcs, dict):
        return _merge_narrative_bits(_foreshadow_pending_line(state, npc_id))
    npc = npcs.get(str(npc_id))
    if not isinstance(npc, dict):
        return _merge_narrative_bits(_foreshadow_pending_line(state, npc_id))
    rumor = _rumor_tag_line(state, npc_id)
    report = _reporting_risk_narrative_line(state, npc_id)
    tags = npc.get("belief_tags", [])
    if not isinstance(tags, list) or not tags:
        return _merge_narrative_bits(_foreshadow_pending_line(state, npc_id), rumor, report)
    # Pick the first tag as primary anchor (deterministic order already).
    primary = str(tags[0] or "").strip()
    if not primary:
        return _merge_narrative_bits(_foreshadow_pending_line(state, npc_id), rumor, report)
    tone = "neutral"
    if primary == "Deep_Grudge":
        tone = "cold_and_suspicious"
    elif primary == "Eternal_Gratitude":
        tone = "warm_and_helpful"
    elif primary == "Blackmail_Leverage":
        tone = "nervous_compliant"
    elif primary == "Debtor":
        tone = "defensive_uneasy"
    elif primary.startswith("Core_Belief_"):
        tone = "guarded"
    # Current emotional state: based on clamped coefficients (anchor layer).
    sm = get_npc_social_modifiers(state, npc_id)
    trust = int(sm.get("trust", 0) or 0)
    susp = int(sm.get("suspicion", 0) or 0)
    fear = int(sm.get("fear", 0) or 0)
    state_line = f"CurrentEmotionalState trust={trust} susp={susp} fear={fear}"
    anchor = f"[ANCHOR] NPC ini memiliki {primary}, bicara dengan nada {tone}. {state_line}"
    fore = _foreshadow_pending_line(state, npc_id)
    return _merge_narrative_bits(anchor, fore, rumor, report)


def verify_narrative_consistency(state: dict[str, Any], npc_id: str) -> str:
    """Cross-check deterministic contradictions between tags and current coefficients."""
    npcs = state.get("npcs", {}) or {}
    if not isinstance(npcs, dict):
        return "OK"
    npc = npcs.get(str(npc_id))
    if not isinstance(npc, dict):
        return "OK"
    tags = npc.get("belief_tags", [])
    if not isinstance(tags, list):
        tags = []
    sm = get_npc_social_modifiers(state, npc_id)
    trust = int(sm.get("trust", 0) or 0)
    susp = int(sm.get("suspicion", 0) or 0)

    if "Deep_Grudge" in tags and trust > 50:
        state.setdefault("world_notes", []).append(f"[Consistency] CRITICAL_CONTRADICTION npc={npc_id} trust={trust} tag=Deep_Grudge")
        return "CRITICAL_CONTRADICTION"
    if "Eternal_Gratitude" in tags and susp > 60:
        state.setdefault("world_notes", []).append(f"[Consistency] CRITICAL_CONTRADICTION npc={npc_id} susp={susp} tag=Eternal_Gratitude")
        return "CRITICAL_CONTRADICTION"
    return "OK"


def get_npc_social_modifiers(state: dict[str, Any], npc_id: str) -> dict[str, int]:
    """Aggregate social coefficients from npc belief_tags and memory_summary.

    Output keys: trust/respect/suspicion/fear, each clamped to [-100, 100].
    Deterministic: no randomness; pure aggregation.
    """
    out = {"trust": 0, "respect": 0, "suspicion": 0, "fear": 0}
    npcs = state.get("npcs", {}) or {}
    if not isinstance(npcs, dict):
        return out
    npc = npcs.get(str(npc_id))
    if not isinstance(npc, dict):
        return out
    npc_tags = npc.get("belief_tags", []) if isinstance(npc.get("belief_tags"), list) else []

    tags = npc.get("belief_tags", [])
    if isinstance(tags, list):
        for raw in tags[:12]:
            tag = str(raw or "").strip()
            if not tag:
                continue
            mods = BELIEF_TAG_SOCIAL_MODS.get(tag)
            if isinstance(mods, dict):
                for k in ("trust", "respect", "suspicion", "fear"):
                    try:
                        out[k] += int(mods.get(k, 0) or 0)
                    except Exception as _omni_sw_283:
                        log_swallowed_exception('engine/npc/memory.py:283', _omni_sw_283)
                        continue

    # Optionally bridge existing belief_summary into same space (lightweight).
    bs = npc.get("belief_summary")
    if isinstance(bs, dict):
        try:
            out["suspicion"] += int((int(bs.get("suspicion", 0) or 0) - 50) / 2)
        except Exception as _omni_sw_291:
            log_swallowed_exception('engine/npc/memory.py:291', _omni_sw_291)
        try:
            out["respect"] += int((int(bs.get("respect", 50) or 50) - 50) / 2)
        except Exception as _omni_sw_295:
            log_swallowed_exception('engine/npc/memory.py:295', _omni_sw_295)
    for k in ("trust", "respect", "suspicion", "fear"):
        out[k] = _clamp_int(out.get(k, 0), -100, 100, 0)

    # Apply behavioral anchors (hard constraints).
    anchors = get_behavioral_anchors(state, npc_id)
    if isinstance(anchors, dict) and anchors:
        for dim in ("trust", "respect", "suspicion", "fear"):
            before = int(out.get(dim, 0) or 0)
            lo = anchors.get(f"min_{dim}")
            hi = anchors.get(f"max_{dim}")
            after = before
            if isinstance(lo, int):
                after = max(after, int(lo))
            if isinstance(hi, int):
                after = min(after, int(hi))
            if after != before:
                out[dim] = int(after)
                state.setdefault("world_notes", []).append(
                    f"[Anchor] {npc_id} {dim} clamped to {after} due to {str((npc_tags or ['?'])[0])}"
                )
    return out


def is_trigger_condition_met(state: dict[str, Any], npc_id: str, trigger_type: str) -> bool:
    """True if SOCIAL_THRESHOLDS for trigger_type are satisfied (hybrid view, deterministic).

    Hybrid view matches ``check_social_triggers``:
    - trust, fear: NPC fields (0..100)
    - suspicion: belief_summary.suspicion (0..100)
    - respect (SUBMISSIVE_LEAK / fallback): coefficient from get_npc_social_modifiers
    - LOYA_REWARD respect: belief_summary.respect (0..100 cognitive), not the coefficient
    """
    req = SOCIAL_THRESHOLDS.get(str(trigger_type))
    if not isinstance(req, dict):
        return False
    npcs = state.get("npcs", {}) or {}
    if not isinstance(npcs, dict):
        return False
    npc = npcs.get(str(npc_id))
    if not isinstance(npc, dict):
        return False

    sm = get_npc_social_modifiers(state, str(npc_id))
    respect_coef = int(sm.get("respect", 0) or 0)
    try:
        trust = int(npc.get("trust", 50) or 50)
    except Exception as _omni_sw_344:
        log_swallowed_exception('engine/npc/memory.py:344', _omni_sw_344)
        trust = 50
    trust = max(0, min(100, trust))
    try:
        fear = int(npc.get("fear", 10) or 10)
    except Exception as _omni_sw_349:
        log_swallowed_exception('engine/npc/memory.py:349', _omni_sw_349)
        fear = 10
    fear = max(0, min(100, fear))
    bs = npc.get("belief_summary") if isinstance(npc.get("belief_summary"), dict) else {}
    if not isinstance(bs, dict):
        bs = {}
    try:
        suspicion = int(bs.get("suspicion", 0) or 0)
    except Exception as _omni_sw_357:
        log_swallowed_exception('engine/npc/memory.py:357', _omni_sw_357)
        suspicion = 0
    suspicion = max(0, min(100, suspicion))

    key = str(trigger_type)
    if key == "BETRAYAL_RISK":
        return (suspicion >= int(req.get("suspicion", 90) or 90)) and (trust <= int(req.get("trust", 10) or 10))
    if key == "LOYA_REWARD":
        try:
            rep0 = int(bs.get("respect", 50) or 50)
        except Exception as _omni_sw_367:
            log_swallowed_exception('engine/npc/memory.py:367', _omni_sw_367)
            rep0 = 50
        return (trust >= int(req.get("trust", 85) or 85)) and (rep0 >= int(req.get("respect", 60) or 60))
    if key == "SUBMISSIVE_LEAK":
        return (fear >= int(req.get("fear", 70) or 70)) and (respect_coef <= int(req.get("respect", -30) or -30))
    if key == "REPORTING_RISK":
        tags = npc.get("belief_tags", [])
        if isinstance(tags, list) and "Eternal_Gratitude" in tags:
            return False
        return suspicion >= int(req.get("suspicion", 85) or 85)
    # Conservative fallback for unknown keys still listed in SOCIAL_THRESHOLDS
    ok = True
    if "suspicion" in req and suspicion < int(req.get("suspicion", 0) or 0):
        ok = False
    if "fear" in req and fear < int(req.get("fear", 0) or 0):
        ok = False
    if "trust" in req:
        thr = int(req.get("trust", 0) or 0)
        if trust < thr:
            ok = False
    if "respect" in req and respect_coef < int(req.get("respect", -100) or -100):
        ok = False
    return ok


def process_memory_decay(
    state: dict[str, Any],
    *,
    base_importance_decay_per_day: int = 5,
    valence_cool_per_day: int = 8,
    consolidate_importance_threshold: int = 80,
    consolidate_min_age_days: int = 3,
) -> dict[str, int]:
    """Deterministic NPC memory decay + consolidation.

    - Decay: importance decreases each day; valence cools toward 0.
    - Consolidation: very high-importance memories (importance>threshold) older than N days become beliefs.
    - Hygiene: drop memories that reach importance==0; bound memory list size.

    Returns counters for debug/testing.
    """
    meta = state.get("meta", {}) or {}
    cur_day = _clamp_int(meta.get("day", 1), 1, 999999, 1)

    npcs = state.get("npcs", {}) or {}
    if not isinstance(npcs, dict):
        return {"decayed": 0, "removed": 0, "consolidated": 0}

    decayed = 0
    removed = 0
    consolidated = 0

    for npc_id, npc in list(npcs.items()):
        if not isinstance(npc, dict):
            continue
        mems = npc.get("memories", [])
        if not isinstance(mems, list) or not mems:
            continue

        belief_tags = npc.setdefault("belief_tags", [])
        if not isinstance(belief_tags, list):
            belief_tags = []
            npc["belief_tags"] = belief_tags
        ms = npc.setdefault("memory_summary", {})
        if not isinstance(ms, dict):
            ms = {}
            npc["memory_summary"] = ms
        belief_from_mem: dict[str, Any] = ms.setdefault("belief_from_memories", {})
        if not isinstance(belief_from_mem, dict):
            belief_from_mem = {}
            ms["belief_from_memories"] = belief_from_mem

        keep: list[dict[str, Any]] = []

        for m in mems[:120]:
            if not isinstance(m, dict):
                continue
            mid = _norm_s(m.get("memory_id", ""))[:40]
            if not mid:
                continue
            imp = _clamp_int(m.get("importance", 0), 0, 100, 0)
            val = _clamp_int(m.get("valence", 0), -100, 100, 0)
            kind = str(m.get("kind", "") or "").strip().lower()[:32]
            summ = str(m.get("summary", "") or "").strip()

            when = m.get("when") if isinstance(m.get("when"), dict) else {}
            md = _clamp_int((when or {}).get("day", cur_day), 1, 999999, cur_day)
            age = max(0, int(cur_day) - int(md))

            # Consolidate into beliefs if long-lived and very important.
            if imp > int(consolidate_importance_threshold) and age >= int(consolidate_min_age_days):
                if mid not in belief_from_mem:
                    tag = "Deep_Grudge" if val <= -40 else "Eternal_Gratitude" if val >= 40 else ("Core_Belief_" + (kind or "memory"))
                    if tag not in belief_tags:
                        belief_tags.append(tag)
                    belief_from_mem[mid] = {
                        "tag": tag,
                        "kind": kind,
                        "summary": summ[:140],
                        "since_day": int(md),
                        "consolidated_day": int(cur_day),
                    }
                    consolidated += 1
                    state.setdefault("world_notes", []).append(f"[Belief] {npc_id}: consolidated {tag} from memory {mid}")
                # Drop from transient memories (now permanent via belief).
                continue

            # Normal decay
            if age >= 1:
                new_imp = max(0, imp - int(base_importance_decay_per_day))
                new_val = val
                if new_val > 0:
                    new_val = max(0, new_val - int(valence_cool_per_day))
                elif new_val < 0:
                    new_val = min(0, new_val + int(valence_cool_per_day))
                if new_imp != imp or new_val != val:
                    decayed += 1
                imp = new_imp
                val = new_val

            if imp <= 0:
                removed += 1
                continue

            m2 = dict(m)
            m2["importance"] = int(imp)
            m2["valence"] = int(val)
            keep.append(m2)

        # Bound list size: keep most important then most recent.
        try:
            def _key(x: dict[str, Any]) -> tuple[int, int]:
                w = x.get("when") if isinstance(x.get("when"), dict) else {}
                d = _clamp_int((w or {}).get("day", 1), 1, 999999, 1)
                imp = _clamp_int(x.get("importance", 0), 0, 100, 0)
                return (imp, d)

            keep.sort(key=_key, reverse=True)
            npc["memories"] = keep[:50]
        except Exception as _omni_sw_506:
            log_swallowed_exception('engine/npc/memory.py:506', _omni_sw_506)
            npc["memories"] = keep[:50]

    return {"decayed": int(decayed), "removed": int(removed), "consolidated": int(consolidated)}

