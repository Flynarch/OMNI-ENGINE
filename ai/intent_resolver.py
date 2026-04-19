from __future__ import annotations

import json
import math
import os
from typing import Any, Dict, List, Optional, Set, Tuple

from ai.llm_http import chat_completion_json

from engine.core.action_registry import (
    allowed_registry_action_ids,
    get_registry_action_by_id,
    sanitize_registry_action_id_hint,
)
from engine.core.intent_lru import intent_cache_get, intent_cache_set
from engine.core.security_intent import check_llm_intent_budget, record_intent_budget_rollback

# Contract version for intent JSON (bumped when required fields / shape changes).
INTENT_SCHEMA_VERSION = 2
# Minimum schema accepted by normalize_resolved_intent (roadmap: intent schema versioning).
INTENT_SCHEMA_MIN_SUPPORTED = INTENT_SCHEMA_VERSION
# ``version`` / ``intent_schema_version`` 3: registry-first stub → normalized v1-shaped output.
REGISTRY_STUB_INTENT_SCHEMA_VERSION = 3

ALLOWED_ACTION_TYPES: Set[str] = frozenset(
    {"instant", "combat", "travel", "sleep", "rest", "talk", "investigate", "use_item", "custom"}
)
ALLOWED_DOMAINS: Set[str] = frozenset(
    {"evasion", "combat", "social", "hacking", "medical", "driving", "stealth", "other"}
)
ALLOWED_COMBAT_STYLES: Set[str] = frozenset({"melee", "ranged", "none"})
ALLOWED_SOCIAL_MODES: Set[str] = frozenset({"non_conflict", "conflict", "none"})
ALLOWED_SOCIAL_CONTEXTS: Set[str] = frozenset({"standard", "formal", "street", "none"})
ALLOWED_STAKES: Set[str] = frozenset({"none", "low", "medium", "high"})
ALLOWED_RISK: Set[str] = frozenset({"low", "medium", "high"})
ALLOWED_PRECONDITION_KINDS: Set[str] = frozenset(
    {
        "hands_free",
        "has_item",
        "scene_phase",
        "target_visible",
        "npc_alive",
        "location_is",
        "district_is",
        "money_gte",
        "has_cash",
        "has_funds",
        "time_is",
        "day_phase",
        "has_ammo",
        "weapon_drawn",
        "skill_gte",
    }
)
TOP_LEVEL_V2_KEYS: Set[str] = frozenset(
    {
        "version",
        "intent_schema_version",
        "confidence",
        "player_goal",
        "context_assumptions",
        "plan",
        "safety",
        "registry_action_id_hint",
    }
)
PLAN_KEYS: Set[str] = frozenset({"plan_id", "steps"})
STEP_KEYS: Set[str] = frozenset(
    {
        "step_id",
        "label",
        "action_type",
        "domain",
        "combat_style",
        "social_mode",
        "social_context",
        "intent_note",
        "suggested_dc",
        "targets",
        "stakes",
        "risk_level",
        "time_cost_min",
        "travel_destination",
        "inventory_ops",
        "preconditions",
        "on_success",
        "on_failure",
        "accommodation_intent",
        "smartphone_op",
        "params",
    }
)
SAFETY_KEYS: Set[str] = frozenset({"refuse", "refuse_reason"})
TOP_LEVEL_V1_KEYS: Set[str] = frozenset(
    {
        "version",
        "intent_schema_version",
        "confidence",
        "action_type",
        "domain",
        "combat_style",
        "social_mode",
        "social_context",
        "intent_note",
        "suggested_dc",
        "targets",
        "stakes",
        "risk_level",
        "time_cost_min",
        "travel_destination",
        "inventory_ops",
        "smartphone_op",
        "player_goal",
        "context_assumptions",
        "registry_action_id_hint",
    }
)
TOP_LEVEL_V3_STUB_KEYS: Set[str] = frozenset(
    {
        "version",
        "intent_schema_version",
        "confidence",
        "registry_action_id_hint",
        "player_goal",
        "context_assumptions",
        "params",
    }
)
ON_LINK_KEYS: Set[str] = frozenset({"next", "when"})
PRECONDITION_KEYS: Set[str] = frozenset({"kind", "op", "value"})

# Mechanical keys merged from registry ``ctx_patch`` when ``registry_action_id_hint`` is valid (Fase 3).
_REGISTRY_PATCH_OVERLAY_KEYS_V1: Set[str] = frozenset(
    {
        "action_type",
        "domain",
        "combat_style",
        "social_mode",
        "social_context",
        "intent_note",
        "stakes",
        "risk_level",
        "time_cost_min",
        "rested_minutes",
        "sleep_duration_h",
        "has_stakes",
        "uncertain",
        "visibility",
        "trivial",
        "trivial_action",
        "impossible",
        "physically_impossible",
        "attempt_clear_jam",
        "instant_minutes",
    }
)
_REGISTRY_PATCH_OVERLAY_KEYS_STEP: Set[str] = _REGISTRY_PATCH_OVERLAY_KEYS_V1 | frozenset({"suggested_dc"})
_REGISTRY_OVERLAY_VISIBILITY: Set[str] = frozenset(
    {"private", "public", "low", "stealth", "standard", "local", "global", "network"}
)


INTENT_SYSTEM_PROMPT = """OMNI-ENGINE v6.9 — INTENT RESOLVER (Schema v2, intent_schema_version=2).
You are a STRICT json-serializer for player intent in a simulation.

You do NOT narrate. You do NOT describe feelings. You ONLY return a single JSON object.

The human types a natural language command as PLAYER_INPUT plus a short ENGINE_SNAPSHOT.
Your job is to infer what the player character is TRYING TO DO in this world.
Support slang, abbreviations, mixed languages, and abstract phrasing; map them to structured fields.

The snapshot may include a block [REGISTRY_ACTION_IDS] with comma-separated stable parser ids from the game's data-driven action registry.
Use it only as a cross-check for which engine paths already exist; still map PLAYER_INPUT to the JSON schema fields as usual. Do not invent ids that are not listed there.

Return ONE JSON object:

Top-level keys:
- intent_schema_version: integer, MUST be 2
- version: 2
- confidence: float 0.0-1.0
- player_goal: short string (what they want in plain words)
- context_assumptions: array of short strings (may be empty)
- plan: object with:
  - plan_id: short string
  - steps: array (1..4) of step objects
- safety: object with:
  - refuse: boolean
  - refuse_reason: short string (empty if refuse=false)

Each step object MUST include these keys (required for the engine):
- step_id: short string
- label: short string (human-readable micro-label)
- action_type: one of ["instant","combat","travel","sleep","rest","talk","investigate","use_item","custom"]
- domain: one of ["evasion","combat","social","hacking","medical","driving","stealth","other"]
- intent_note: short snake_case label describing this step
- suggested_dc: integer 1-100 (target difficulty for mechanical resolution; use ~50 for normal, higher for harder)

Legacy mapping (CRITICAL): if the player's intent clearly matches a built-in engine path, use the normal action_type/domain
for that path instead of defaulting to custom. Examples:
- shoot / tembak / attack -> action_type "combat", domain "combat", appropriate combat_style
- go to / pergi ke / travel -> action_type "travel", domain often "driving" or "other"
- talk / ngobrol / greet -> action_type "talk", domain "social"
- sleep / tidur -> action_type "sleep", domain "other"
- hack / breach -> action_type "investigate" or "instant" with domain "hacking" if recon; use "custom" only if nothing fits
Use action_type "custom" ONLY when the action does not fit the standard set above.

Optional top-level (v1 and v2): registry_action_id_hint: string — if present, MUST exactly equal one id from the REGISTRY_ACTION_IDS line in the snapshot; omit when unsure. Invalid or unknown ids are dropped by the engine.
When the hint is valid, the engine overlays that registry entry's ctx_patch onto your structured fields so mechanical domain/action_type cannot contradict the registry definition for overlapping keys.

Registry-first stub (optional): version=3 AND intent_schema_version=3 with registry_action_id_hint (+ optional confidence, player_goal, context_assumptions, params object). ``params`` may override or add mechanical fields after the registry ctx_patch (same key families as overlay: action_type, domain, suggested_dc, targets, rested_minutes, …). The engine expands this to the same normalized v1-shaped dict as after a valid hint overlay (for tooling / tests).

Tool-only JSON (no version): ``{"registry_action_id":"<id>","params":{...}}`` or the same with ``registry_action_id_hint`` / ``action_id`` as the id key (only one distinct id if multiple aliases are present). Optional confidence / player_goal / context_assumptions. Omit ``action_type``, ``domain``, ``plan``, and ``version`` so it is not mistaken for v1/v2.

Optional step keys:
- combat_style: one of ["melee","ranged","none"] (only meaningful when domain="combat"; otherwise "none")
- social_mode: one of ["non_conflict","conflict","none"]
- social_context: one of ["standard","formal","street","none"]
- targets: array of short strings
- stakes: one of ["none","low","medium","high"]
- risk_level: one of ["low","medium","high"]
- time_cost_min: integer minutes 0-720 for sleep, 0-240 for other action types (0 means use engine default)
- travel_destination: short place name if action_type="travel", else "".
- inventory_ops: array of inventory micro-ops (same shapes as v1)
- smartphone_op: optional object for phone UI (action_type usually "instant", domain "other", intent_note "smartphone"):
  {"op":"power","value":"on|off|status"} OR {"op":"call","target":"<name>"} OR {"op":"message","target":"<name>","body":"<text>"} OR {"op":"dark_web"}
- preconditions: array (may be empty). Each item is ONLY {"kind","op","value"} with kind one of:
  ["hands_free","has_item","scene_phase","target_visible","npc_alive","location_is","district_is","money_gte","has_cash","has_funds","time_is","day_phase","has_ammo","weapon_drawn","skill_gte"]
  and op one of ["eq","neq","in","gte"] (use gte for money_gte/skill_gte).
  - has_cash / has_funds: value is integer threshold (cash only vs cash+bank).
  - time_is / day_phase: value is one of night|day|morning|evening (or Indonesian aliases malam|siang|pagi|sore).
  - has_ammo: value is minimum rounds (default 1).
  - weapon_drawn: value boolean or true/false string.
- on_success: array of {"next":"<step_id>","when":"always|if_possible"} (may be empty)
- on_failure: array of {"next":"<step_id>","when":"always|if_blocked|if_failed_roll"} (may be empty)

Rules:
- Keep steps minimal. Prefer 1 step unless the player explicitly asks for conditional/multi-step.
- For conditionals: represent as step2 with preconditions, and link via on_success/on_failure.
- NEVER invent enemies or weapons if not clearly stated.
- If confused: simplest plausible step, confidence<=0.5, suggested_dc around 55-65.
- Consensual private adult intimacy (fade-to-black): action_type="talk", domain="social", social_mode="non_conflict", intent_note="intimacy_private", stakes="medium", time_cost_min 45-90.
- Refuse disallowed content by setting safety.refuse=true.

Return ONLY the JSON, no explanation, no markdown.
"""


def clamp_suggested_dc(val: Any) -> int:
    """Clamp LLM-provided DC to 1..100; default 50 if missing/invalid."""
    if val is None:
        return 50
    try:
        n = int(round(float(val)))
    except (TypeError, ValueError):
        return 50
    return max(1, min(100, n))


def _only_keys(d: Dict[str, Any], allowed: Set[str]) -> Dict[str, Any]:
    return {k: d[k] for k in d if k in allowed}


def _sanitize_context_assumptions(raw: Any) -> List[str]:
    if not isinstance(raw, list):
        return []
    out: List[str] = []
    for x in raw[:24]:
        s = str(x).strip()
        if s:
            out.append(s[:200])
    return out


def _sanitize_safety(raw: Any) -> Dict[str, Any]:
    if not isinstance(raw, dict):
        return {"refuse": False, "refuse_reason": ""}
    s = _only_keys(raw, SAFETY_KEYS)
    refuse = bool(s.get("refuse", False))
    rr = str(s.get("refuse_reason", "") or "").strip()
    return {"refuse": refuse, "refuse_reason": rr[:500]}


def _sanitize_precondition(cond: Any) -> Optional[Dict[str, Any]]:
    if not isinstance(cond, dict):
        return None
    c = _only_keys(cond, PRECONDITION_KEYS)
    kind = str(c.get("kind", "") or "").strip().lower()
    if not kind or kind not in ALLOWED_PRECONDITION_KINDS:
        return None
    op = str(c.get("op", "eq") or "eq").strip().lower()
    if op not in ("eq", "neq", "in", "gte"):
        op = "eq"
    return {"kind": kind, "op": op, "value": c.get("value")}


def _sanitize_on_links(raw: Any, *, failure: bool) -> List[Dict[str, str]]:
    if not isinstance(raw, list):
        return []
    if failure:
        allowed_when: Set[str] = frozenset({"always", "if_blocked", "if_failed_roll"})
    else:
        allowed_when = frozenset({"always", "if_possible"})
    out: List[Dict[str, str]] = []
    for item in raw[:12]:
        if not isinstance(item, dict):
            continue
        nxt = str(item.get("next", "") or "").strip()
        when = str(item.get("when", "always") or "always").strip().lower()
        if not nxt or when not in allowed_when:
            continue
        out.append({"next": nxt[:80], "when": when})
    return out


def _sanitize_smartphone_op(raw: Any) -> Optional[Dict[str, Any]]:
    if not isinstance(raw, dict):
        return None
    op = str(raw.get("op", "") or "").strip().lower()
    if op == "power":
        v = str(raw.get("value", "") or "").strip().lower()
        if v not in ("on", "off", "status"):
            return None
        return {"op": "power", "value": v}
    if op == "call":
        tgt = str(raw.get("target", "") or "").strip()[:80]
        if not tgt:
            return None
        return {"op": "call", "target": tgt}
    if op == "message":
        tgt = str(raw.get("target", "") or "").strip()[:80]
        body = str(raw.get("body", "") or "").strip()[:500]
        if not tgt:
            return None
        return {"op": "message", "target": tgt, "body": body}
    if op in ("dark_web", "darkweb"):
        return {"op": "dark_web"}
    return None


def _sanitize_step(step: Any) -> Optional[Dict[str, Any]]:
    if not isinstance(step, dict):
        return None
    s = _only_keys(step, STEP_KEYS)
    sid = str(s.get("step_id", "") or "").strip()
    if not sid:
        return None
    at = str(s.get("action_type", "") or "").strip().lower()
    dom = str(s.get("domain", "") or "").strip().lower()
    if at not in ALLOWED_ACTION_TYPES or dom not in ALLOWED_DOMAINS:
        return None
    note = str(s.get("intent_note", "") or "").strip().lower().replace(" ", "_")
    if not note:
        note = "abstract_intent"
    note = note[:80]
    dc = clamp_suggested_dc(s.get("suggested_dc"))
    label = str(s.get("label", "") or "").strip()[:120] or note
    out: Dict[str, Any] = {
        "step_id": sid[:80],
        "label": label,
        "action_type": at,
        "domain": dom,
        "intent_note": note,
        "suggested_dc": dc,
    }
    cs = str(s.get("combat_style", "none") or "none").strip().lower()
    out["combat_style"] = cs if cs in ALLOWED_COMBAT_STYLES else "none"
    sm = str(s.get("social_mode", "none") or "none").strip().lower()
    out["social_mode"] = sm if sm in ALLOWED_SOCIAL_MODES else "none"
    sc = str(s.get("social_context", "none") or "none").strip().lower()
    out["social_context"] = sc if sc in ALLOWED_SOCIAL_CONTEXTS else "none"
    if "targets" in s:
        tg = s.get("targets")
        if isinstance(tg, list):
            out["targets"] = [str(x).strip()[:80] for x in tg[:16] if str(x).strip()]
    st = str(s.get("stakes", "none") or "none").strip().lower()
    if st in ALLOWED_STAKES:
        out["stakes"] = st
    rk = str(s.get("risk_level", "low") or "low").strip().lower()
    if rk in ALLOWED_RISK:
        out["risk_level"] = rk
    try:
        tcm = int(s.get("time_cost_min", 0) or 0)
        cap_m = 12 * 60 if at == "sleep" else 240
        out["time_cost_min"] = max(0, min(cap_m, tcm))
    except (TypeError, ValueError):
        out["time_cost_min"] = 0
    if at == "travel":
        out["travel_destination"] = str(s.get("travel_destination", "") or "").strip()[:120]
    else:
        out["travel_destination"] = str(s.get("travel_destination", "") or "").strip()[:120]
    if isinstance(s.get("inventory_ops"), list):
        out["inventory_ops"] = s["inventory_ops"][:24]
    pre: List[Dict[str, Any]] = []
    if isinstance(s.get("preconditions"), list):
        for p in s["preconditions"][:16]:
            sp = _sanitize_precondition(p)
            if sp:
                pre.append(sp)
    if pre:
        out["preconditions"] = pre
    osucc = _sanitize_on_links(s.get("on_success"), failure=False)
    ofail = _sanitize_on_links(s.get("on_failure"), failure=True)
    if osucc:
        out["on_success"] = osucc
    if ofail:
        out["on_failure"] = ofail
    if isinstance(s.get("accommodation_intent"), dict):
        out["accommodation_intent"] = dict(s["accommodation_intent"])
    if isinstance(s.get("smartphone_op"), dict):
        spo = _sanitize_smartphone_op(s["smartphone_op"])
        if spo:
            out["smartphone_op"] = spo
    if isinstance(s.get("params"), dict):
        out["params"] = dict(s["params"])
    return out


def _sanitize_registry_action_id_hint_field(blob: Dict[str, Any]) -> None:
    """Drop or clamp ``registry_action_id_hint`` to known registry ids (in-place)."""
    try:
        h = sanitize_registry_action_id_hint(blob.get("registry_action_id_hint"))
        if h:
            blob["registry_action_id_hint"] = h
        else:
            blob.pop("registry_action_id_hint", None)
    except Exception:
        blob.pop("registry_action_id_hint", None)


def _registry_overlay_merge_key(blob: Dict[str, Any], k: str, v: Any) -> None:
    """Apply one registry ``ctx_patch`` entry onto a v1 dict or a v2 step dict."""
    if k == "action_type":
        at = str(v).strip().lower()
        if at in ALLOWED_ACTION_TYPES:
            blob["action_type"] = at
    elif k == "domain":
        dom = str(v).strip().lower()
        if dom in ALLOWED_DOMAINS:
            blob["domain"] = dom
    elif k == "combat_style":
        cs = str(v).strip().lower()
        blob["combat_style"] = cs if cs in ALLOWED_COMBAT_STYLES else "none"
    elif k == "social_mode":
        sm = str(v).strip().lower()
        blob["social_mode"] = sm if sm in ALLOWED_SOCIAL_MODES else "none"
    elif k == "social_context":
        sc = str(v).strip().lower()
        blob["social_context"] = sc if sc in ALLOWED_SOCIAL_CONTEXTS else "none"
    elif k == "intent_note":
        note = str(v).strip().lower().replace(" ", "_")
        blob["intent_note"] = note[:80] if note else "abstract_intent"
    elif k == "stakes":
        st = str(v).strip().lower()
        if st in ALLOWED_STAKES:
            blob["stakes"] = st
    elif k == "risk_level":
        rk = str(v).strip().lower()
        if rk in ALLOWED_RISK:
            blob["risk_level"] = rk
    elif k == "time_cost_min":
        try:
            blob["time_cost_min"] = int(v)
        except (TypeError, ValueError):
            pass
    elif k == "suggested_dc":
        blob["suggested_dc"] = clamp_suggested_dc(v)
    elif k == "rested_minutes":
        try:
            rm = int(v)
            blob["rested_minutes"] = max(0, min(12 * 60, rm))
        except (TypeError, ValueError):
            pass
    elif k == "sleep_duration_h":
        try:
            sh = int(v)
            blob["sleep_duration_h"] = max(0, min(24, sh))
        except (TypeError, ValueError):
            pass
    elif k == "instant_minutes":
        try:
            im = int(v)
            blob["instant_minutes"] = max(0, min(24 * 60, im))
        except (TypeError, ValueError):
            pass
    elif k in ("has_stakes", "uncertain", "trivial", "trivial_action", "impossible", "physically_impossible", "attempt_clear_jam"):
        if isinstance(v, bool):
            blob[k] = v
        elif isinstance(v, str):
            s = v.strip().lower()
            if s in ("true", "1", "yes"):
                blob[k] = True
            elif s in ("false", "0", "no"):
                blob[k] = False
    elif k == "visibility":
        vis = str(v).strip().lower()[:32]
        if vis in _REGISTRY_OVERLAY_VISIBILITY:
            blob["visibility"] = vis


def _reclamp_v1_time_cost_min(flat: Dict[str, Any]) -> None:
    try:
        tcm = int(flat.get("time_cost_min", 0) or 0)
    except (TypeError, ValueError):
        tcm = 0
    at = str(flat.get("action_type", "") or "").strip().lower()
    if at == "sleep":
        flat["time_cost_min"] = max(0, min(12 * 60, tcm))
    else:
        flat["time_cost_min"] = max(0, min(240, tcm))


def _apply_registry_ctx_patch_to_normalized_v1(flat: Dict[str, Any]) -> None:
    """When ``registry_action_id_hint`` is a known id, overlay ctx_patch fields onto v1 output (registry wins)."""
    h = flat.get("registry_action_id_hint")
    if not h:
        return
    try:
        m = get_registry_action_by_id(str(h))
    except Exception:
        return
    if not m:
        return
    patch = m.get("ctx_patch") if isinstance(m.get("ctx_patch"), dict) else {}
    for k, v in patch.items():
        if k not in _REGISTRY_PATCH_OVERLAY_KEYS_V1 or v is None:
            continue
        _registry_overlay_merge_key(flat, k, v)
    _reclamp_v1_time_cost_min(flat)


def _apply_registry_ctx_patch_to_normalized_v2(base: Dict[str, Any]) -> None:
    """Overlay registry ctx_patch onto the first plan step when hint is valid (v2)."""
    h = base.get("registry_action_id_hint")
    if not h:
        return
    try:
        m = get_registry_action_by_id(str(h))
    except Exception:
        return
    if not m:
        return
    patch = m.get("ctx_patch") if isinstance(m.get("ctx_patch"), dict) else {}
    plan = base.get("plan")
    if not isinstance(plan, dict):
        return
    steps = plan.get("steps")
    if not isinstance(steps, list) or not steps:
        return
    s0 = steps[0]
    if not isinstance(s0, dict):
        return
    for k, v in patch.items():
        if k not in _REGISTRY_PATCH_OVERLAY_KEYS_STEP or v is None:
            continue
        _registry_overlay_merge_key(s0, k, v)
    try:
        tcm = int(s0.get("time_cost_min", 0) or 0)
    except (TypeError, ValueError):
        tcm = 0
    at = str(s0.get("action_type", "") or "").strip().lower()
    if at == "sleep":
        s0["time_cost_min"] = max(0, min(12 * 60, tcm))
    else:
        s0["time_cost_min"] = max(0, min(240, tcm))


def _finalize_v1_flat_fields(flat: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Clamp v1 mechanical fields after ``ctx_patch`` overlay (returns None if action_type/domain invalid)."""
    at = str(flat.get("action_type", "") or "").strip().lower()
    dom = str(flat.get("domain", "") or "").strip().lower()
    if at not in ALLOWED_ACTION_TYPES or dom not in ALLOWED_DOMAINS:
        return None
    note = str(flat.get("intent_note", "") or "").strip().lower().replace(" ", "_")
    if not note:
        note = "abstract_intent"
    flat["intent_note"] = note[:80]
    flat["suggested_dc"] = clamp_suggested_dc(flat.get("suggested_dc"))
    cs = str(flat.get("combat_style", "none") or "none").strip().lower()
    flat["combat_style"] = cs if cs in ALLOWED_COMBAT_STYLES else "none"
    sm = str(flat.get("social_mode", "none") or "none").strip().lower()
    flat["social_mode"] = sm if sm in ALLOWED_SOCIAL_MODES else "none"
    sc = str(flat.get("social_context", "none") or "none").strip().lower()
    flat["social_context"] = sc if sc in ALLOWED_SOCIAL_CONTEXTS else "none"
    if "targets" in flat and isinstance(flat["targets"], list):
        flat["targets"] = [str(x).strip()[:80] for x in flat["targets"][:16] if str(x).strip()]
    st = str(flat.get("stakes", "none") or "none").strip().lower()
    if st in ALLOWED_STAKES:
        flat["stakes"] = st
    rk = str(flat.get("risk_level", "low") or "low").strip().lower()
    if rk in ALLOWED_RISK:
        flat["risk_level"] = rk
    try:
        tcm = int(flat.get("time_cost_min", 0) or 0)
        at2 = str(flat.get("action_type", "") or "").strip().lower()
        if at2 == "sleep":
            flat["time_cost_min"] = max(0, min(12 * 60, tcm))
        else:
            flat["time_cost_min"] = max(0, min(240, tcm))
    except (TypeError, ValueError):
        flat["time_cost_min"] = 0
    flat["travel_destination"] = str(flat.get("travel_destination", "") or "").strip()[:120]
    if isinstance(flat.get("inventory_ops"), list):
        flat["inventory_ops"] = flat["inventory_ops"][:24]
    if isinstance(flat.get("smartphone_op"), dict):
        spo = _sanitize_smartphone_op(flat["smartphone_op"])
        if spo:
            flat["smartphone_op"] = spo
        else:
            flat.pop("smartphone_op", None)
    try:
        conf = float(flat.get("confidence", 0.0))
    except (TypeError, ValueError):
        conf = 0.0
    flat["confidence"] = max(0.0, min(1.0, conf))
    return flat


def _shallow_sanitize_stub_accommodation_intent(raw: Any) -> Optional[Dict[str, Any]]:
    """Bounded primitive-only dict for ``params.accommodation_intent`` (stub v3 / tooling)."""
    if not isinstance(raw, dict):
        return None
    out: Dict[str, Any] = {}
    for i, (k, v) in enumerate(raw.items()):
        if i >= 24:
            break
        ks = str(k).strip()[:64]
        if not ks:
            continue
        if isinstance(v, bool):
            out[ks] = v
        elif isinstance(v, int) and not isinstance(v, bool):
            out[ks] = v
        elif isinstance(v, float):
            if math.isfinite(v):
                out[ks] = v
        elif isinstance(v, str):
            ts = v.strip()
            out[ks] = ts[:400] if len(ts) > 400 else ts
    return out or None


def _apply_registry_stub_v3_params(flat: Dict[str, Any], raw_params: Any) -> None:
    """Merge optional ``params`` onto stub ``flat`` after registry ``ctx_patch`` (deterministic overrides)."""
    if not isinstance(raw_params, dict):
        return
    for idx, (k, v) in enumerate(raw_params.items()):
        if idx >= 48:
            break
        ks = str(k).strip()
        if not ks:
            continue
        if ks == "suggested_dc":
            flat["suggested_dc"] = clamp_suggested_dc(v)
        elif ks == "targets" and isinstance(v, list):
            flat["targets"] = [str(x).strip()[:80] for x in v[:16] if str(x).strip()]
        elif ks == "travel_destination":
            flat["travel_destination"] = str(v).strip()[:120]
        elif ks == "inventory_ops" and isinstance(v, list):
            flat["inventory_ops"] = v[:24]
        elif ks == "smartphone_op" and isinstance(v, dict):
            spo = _sanitize_smartphone_op(v)
            if spo:
                flat["smartphone_op"] = spo
        elif ks == "accommodation_intent":
            acc = _shallow_sanitize_stub_accommodation_intent(v)
            if acc:
                flat["accommodation_intent"] = acc
        elif ks in _REGISTRY_PATCH_OVERLAY_KEYS_V1 and v is not None:
            _registry_overlay_merge_key(flat, ks, v)
    _reclamp_v1_time_cost_min(flat)


def _normalize_registry_stub_v3(obj: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Minimal registry-first payload (``version``/``intent_schema_version`` 3) → v1-shaped normalized intent."""
    stub = _only_keys(obj, TOP_LEVEL_V3_STUB_KEYS)
    try:
        isv = int(stub.get("intent_schema_version", 0) or 0)
    except (TypeError, ValueError):
        return None
    if isv != REGISTRY_STUB_INTENT_SCHEMA_VERSION:
        return None
    flat: Dict[str, Any] = {
        "version": 1,
        "intent_schema_version": INTENT_SCHEMA_VERSION,
        "confidence": 0.0,
        "action_type": "instant",
        "domain": "evasion",
        "intent_note": "registry_stub",
        "combat_style": "none",
        "social_mode": "none",
        "social_context": "none",
        "stakes": "none",
        "risk_level": "medium",
        "time_cost_min": 0,
        "travel_destination": "",
    }
    try:
        conf = float(stub.get("confidence", 0.0) or 0.0)
    except (TypeError, ValueError):
        conf = 0.0
    flat["confidence"] = max(0.0, min(1.0, conf))
    flat["registry_action_id_hint"] = str(stub.get("registry_action_id_hint", "") or "").strip()
    pg = str(stub.get("player_goal", "") or "").strip()
    if pg:
        flat["player_goal"] = pg[:300]
    flat["context_assumptions"] = _sanitize_context_assumptions(stub.get("context_assumptions"))
    _sanitize_registry_action_id_hint_field(flat)
    if not flat.get("registry_action_id_hint"):
        return None
    _apply_registry_ctx_patch_to_normalized_v1(flat)
    _apply_registry_stub_v3_params(flat, stub.get("params"))
    return _finalize_v1_flat_fields(flat)


_MINIMAL_REGISTRY_ID_KEYS: tuple[str, ...] = (
    "registry_action_id",
    "registry_action_id_hint",
    "action_id",
)


def _minimal_registry_payload_raw_id(obj: Dict[str, Any]) -> str | None:
    """Return unified id if alias keys agree; ``""`` if none set; ``None`` if values conflict."""
    seen: set[str] = set()
    for key in _MINIMAL_REGISTRY_ID_KEYS:
        v = str(obj.get(key, "") or "").strip()
        if v:
            seen.add(v)
    if not seen:
        return ""
    if len(seen) > 1:
        return None
    return next(iter(seen))


def _minimal_registry_id_alias_keys_present(obj: Dict[str, Any]) -> bool:
    return any(str(obj.get(k, "") or "").strip() for k in _MINIMAL_REGISTRY_ID_KEYS)


def _is_minimal_registry_intent_payload(obj: Dict[str, Any]) -> bool:
    """True for tool-only shape: one registry id (+ optional ``params``) without ``version`` / v1 / v2 shells."""
    rid = _minimal_registry_payload_raw_id(obj)
    if rid is None or rid == "":
        return False
    if "version" in obj:
        return False
    if "intent_schema_version" in obj:
        return False
    if "plan" in obj:
        return False
    if "action_type" in obj or "domain" in obj:
        return False
    return True


def _normalize_minimal_registry_intent_payload(obj: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """``{registry_action_id | registry_action_id_hint | action_id, params?, ...}`` → stub v3 path."""
    raw = _minimal_registry_payload_raw_id(obj)
    if raw is None or raw == "":
        return None
    try:
        rid = sanitize_registry_action_id_hint(raw)
    except Exception:
        rid = None
    if not rid:
        return None
    inner: Dict[str, Any] = {
        "version": 3,
        "intent_schema_version": REGISTRY_STUB_INTENT_SCHEMA_VERSION,
        "registry_action_id_hint": rid,
    }
    try:
        c = float(obj.get("confidence", 0.0) or 0.0)
        inner["confidence"] = max(0.0, min(1.0, c))
    except (TypeError, ValueError):
        pass
    pg = str(obj.get("player_goal", "") or "").strip()
    if pg:
        inner["player_goal"] = pg[:300]
    if isinstance(obj.get("context_assumptions"), list):
        inner["context_assumptions"] = obj["context_assumptions"]
    if isinstance(obj.get("params"), dict):
        inner["params"] = obj["params"]
    return _normalize_registry_stub_v3(inner)


def normalize_resolved_intent(obj: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Validate + whitelist a parsed LLM intent dict. Returns None if unusable.

    ``version`` 1 / 2: FFCI LLM shapes. ``version`` 3 + ``intent_schema_version`` 3: registry-first stub
    (``REGISTRY_STUB_INTENT_SCHEMA_VERSION``) expanded to v1-shaped output: registry ``ctx_patch`` then optional ``params``.

    Tool-only: one of ``registry_action_id`` / ``registry_action_id_hint`` / ``action_id`` (+ optional ``params``)
    with no ``version`` / ``plan`` / ``action_type`` / ``domain`` is normalized like stub v3
    (see ``_normalize_minimal_registry_intent_payload``).
    """
    if not isinstance(obj, dict):
        return None
    rid0 = _minimal_registry_payload_raw_id(obj)
    if rid0 is None and _minimal_registry_id_alias_keys_present(obj):
        return None
    if _is_minimal_registry_intent_payload(obj):
        return _normalize_minimal_registry_intent_payload(obj)
    try:
        ver = int(obj.get("version", 1) or 1)
    except (TypeError, ValueError):
        ver = 1

    if ver == 3:
        return _normalize_registry_stub_v3(obj)

    if ver == 2:
        base = _only_keys(obj, TOP_LEVEL_V2_KEYS)
        base["version"] = 2
        try:
            isv = int(base.get("intent_schema_version", INTENT_SCHEMA_VERSION) or INTENT_SCHEMA_VERSION)
        except (TypeError, ValueError):
            isv = INTENT_SCHEMA_VERSION
        if isv != INTENT_SCHEMA_MIN_SUPPORTED:
            return None
        base["intent_schema_version"] = INTENT_SCHEMA_VERSION
        safety = _sanitize_safety(base.get("safety"))
        base["safety"] = safety
        if safety.get("refuse"):
            return None
        pl = base.get("plan")
        if not isinstance(pl, dict):
            return None
        plan = _only_keys(pl, PLAN_KEYS)
        pid = str(plan.get("plan_id", "") or "").strip()[:80]
        if not pid:
            pid = "plan"
        plan["plan_id"] = pid
        steps_raw = plan.get("steps")
        if not isinstance(steps_raw, list) or not steps_raw:
            return None
        if len(steps_raw) > 4:
            return None
        steps: List[Dict[str, Any]] = []
        for st in steps_raw:
            ss = _sanitize_step(st)
            if not ss:
                return None
            steps.append(ss)
        plan["steps"] = steps
        base["plan"] = plan
        base["player_goal"] = str(base.get("player_goal", "") or "").strip()[:300]
        base["context_assumptions"] = _sanitize_context_assumptions(base.get("context_assumptions"))
        try:
            conf = float(base.get("confidence", 0.0))
        except (TypeError, ValueError):
            conf = 0.0
        conf = max(0.0, min(1.0, conf))
        base["confidence"] = conf
        _sanitize_registry_action_id_hint_field(base)
        _apply_registry_ctx_patch_to_normalized_v2(base)
        return base

    # v1 flat (legacy LLM or sleep fastpath)
    flat = _only_keys(obj, TOP_LEVEL_V1_KEYS)
    try:
        flat["version"] = int(flat.get("version", 1) or 1)
    except (TypeError, ValueError):
        flat["version"] = 1
    flat["intent_schema_version"] = INTENT_SCHEMA_VERSION
    _sanitize_registry_action_id_hint_field(flat)
    _apply_registry_ctx_patch_to_normalized_v1(flat)
    return _finalize_v1_flat_fields(flat)


def parse_and_normalize_intent_json(text: str) -> Optional[Dict[str, Any]]:
    """Parse JSON text (single object) then run :func:`normalize_resolved_intent` (FFCI + stub v3 + minimal registry)."""
    blob = _safe_parse_json_blob(text)
    if not isinstance(blob, dict):
        return None
    return normalize_resolved_intent(blob)


def _flatten_intent_v2_for_compat(obj: Dict[str, Any]) -> Dict[str, Any]:
    """Derive v1-like top-level keys from v2 so existing callers can keep working."""
    out = dict(obj)
    plan = out.get("plan") if isinstance(out.get("plan"), dict) else {}
    steps = plan.get("steps") if isinstance(plan.get("steps"), list) else []
    step0 = steps[0] if steps and isinstance(steps[0], dict) else {}
    for k in (
        "action_type",
        "domain",
        "combat_style",
        "social_mode",
        "social_context",
        "intent_note",
        "suggested_dc",
        "targets",
        "stakes",
        "risk_level",
        "time_cost_min",
        "travel_destination",
        "inventory_ops",
        "smartphone_op",
        "rested_minutes",
        "sleep_duration_h",
        "has_stakes",
        "uncertain",
        "visibility",
        "trivial",
        "trivial_action",
        "impossible",
        "physically_impossible",
        "attempt_clear_jam",
        "instant_minutes",
    ):
        if k in step0 and step0.get(k) is not None:
            out[k] = step0.get(k)
    if "step_now_id" not in out and isinstance(step0.get("step_id"), str):
        out["step_now_id"] = step0.get("step_id")
    return out


def _intent_llm_timeout_sec() -> float:
    raw = os.getenv("OMNI_LLM_INTENT_TIMEOUT_SEC", "").strip()
    if raw.replace(".", "", 1).isdigit():
        return max(5.0, min(180.0, float(raw)))
    return 60.0


def _invoke_llm_for_intent(payload: Dict[str, Any]) -> str:
    _mt = os.getenv("LLM_INTENT_MAX_TOKENS", "").strip()
    if _mt.isdigit():
        max_tokens = int(_mt)
    else:
        max_tokens = 512

    data = chat_completion_json(
        messages=[
            {"role": "system", "content": INTENT_SYSTEM_PROMPT},
            {"role": "user", "content": payload["user"]},
        ],
        max_tokens=max_tokens,
        timeout=_intent_llm_timeout_sec(),
    )
    content = data["choices"][0]["message"]["content"]
    return str(content)


def _safe_parse_json_blob(text: str) -> Optional[Dict[str, Any]]:
    """Try to extract a single JSON object from raw LLM text (robust to ``` fences)."""
    text = text.strip()
    if not text:
        return None
    if text.startswith("```"):
        parts = text.split("```")
        if len(parts) >= 2:
            text = parts[1]
    text = text.strip()
    try:
        obj = json.loads(text)
        if isinstance(obj, dict):
            return obj
    except Exception:
        try:
            a = text.find("{")
            b = text.rfind("}")
            if a != -1 and b != -1 and b > a:
                obj = json.loads(text[a : b + 1])
                if isinstance(obj, dict):
                    return obj
        except Exception:
            pass
    return None


def _sleep_fastpath(player_input: str) -> Optional[Dict[str, Any]]:
    t = str(player_input or "").strip().lower()
    if not t:
        return None
    hrs: int | None = None
    import re

    m = re.search(r"\b(?:aku|saya)\s+mau\s+tidur\s+(\d{1,2})(?:\s*(?:jam|hours?|h))?\b", t)
    if m:
        try:
            hrs = int(m.group(1))
        except Exception:
            hrs = 8
    elif t in ("sleep", "tidur", "aku mau tidur", "saya mau tidur"):
        hrs = 8
    else:
        m = re.search(r"\b(?:sleep|tidur)\s+(\d{1,2})(?:\s*(?:jam|hours?|h))?\b", t)
        if not m:
            m = re.search(r"\b(\d{1,2})\s*(?:jam|hours?|h)\b", t)
            if not m or ("sleep" not in t and "tidur" not in t):
                return None
        try:
            hrs = int(m.group(1))
        except Exception:
            hrs = 8
    hrs = max(1, min(12, int(hrs)))
    raw = {
        "version": 1,
        "intent_schema_version": INTENT_SCHEMA_VERSION,
        "confidence": 0.95,
        "action_type": "sleep",
        "domain": "other",
        "intent_note": "sleep",
        "suggested_dc": 40,
        "stakes": "none",
        "risk_level": "low",
        "time_cost_min": int(hrs) * 60,
    }
    return normalize_resolved_intent(raw)


def _intent_lru_cache_key(state: Dict[str, Any], player_input: str) -> Tuple[Any, ...]:
    meta = state.get("meta", {}) or {}
    player = state.get("player", {}) or {}
    return (
        INTENT_SCHEMA_VERSION,
        int(meta.get("day", 1) or 1),
        int(meta.get("time_min", 0) or 0) // 45,
        str(player.get("location", "") or "")[:48].lower(),
        str(player_input or "").strip().lower()[:520],
    )


def resolve_intent(state: Dict[str, Any], player_input: str) -> Optional[Dict[str, Any]]:
    """Best-effort LLM intent resolution. Returns dict or None if unusable."""
    meta = state.get("meta", {}) or {}
    player = state.get("player", {}) or {}
    inv = state.get("inventory", {}) or {}
    weapons = inv.get("weapons") if isinstance(inv, dict) else {}
    weapon_ids = list(weapons.keys())[:8] if isinstance(weapons, dict) else []
    world = state.get("world", {}) or {}
    nearby = world.get("nearby_items", []) or []
    nearby_preview = nearby[:12] if isinstance(nearby, list) else []
    summary = (
        f"day={meta.get('day', 1)} time_min={meta.get('time_min', 0)} "
        f"loc={player.get('location', '-')} year={player.get('year', '-')}\n"
        f"trace={state.get('trace', {}).get('trace_pct', 0)} "
        f"cash={state.get('economy', {}).get('cash', 0)} "
        f"bank={state.get('economy', {}).get('bank', 0)}\n"
        f"hands: r_hand={inv.get('r_hand','-')} l_hand={inv.get('l_hand','-')}\n"
        f"pocket: {inv.get('pocket_contents', [])} cap={inv.get('pocket_capacity', 4)}\n"
        f"bag: {inv.get('bag_contents', [])} cap={inv.get('bag_capacity', 12)}\n"
        f"active_weapon_id={inv.get('active_weapon_id','')} weapon_ids={weapon_ids}\n"
        f"nearby_items={nearby_preview}"
    )
    fast = _sleep_fastpath(player_input)
    if isinstance(fast, dict):
        return fast
    if os.getenv("OMNI_INTENT_LRU", "1").strip().lower() not in ("0", "false", "no", "off"):
        ck = _intent_lru_cache_key(state, player_input)
        hit = intent_cache_get(ck)
        if isinstance(hit, dict):
            return hit
    ok_budget, _br = check_llm_intent_budget(state)
    if not ok_budget:
        return None
    reg_block = ""
    try:
        rids = allowed_registry_action_ids()
        if rids:
            reg_block = "\n[REGISTRY_ACTION_IDS]\n" + ",".join(rids) + "\n"
    except Exception:
        reg_block = ""
    user = f"[ENGINE_SNAPSHOT]\n{summary}{reg_block}\n[PLAYER_INPUT]\n{player_input}\n"
    try:
        raw = _invoke_llm_for_intent({"user": user})
    except Exception:
        record_intent_budget_rollback(state)
        return None
    blob = _safe_parse_json_blob(raw)
    if not blob:
        return None
    obj = normalize_resolved_intent(blob)
    if not obj:
        return None
    if int(obj.get("version", 1) or 1) == 2:
        obj = _flatten_intent_v2_for_compat(obj)
    try:
        conf = float(obj.get("confidence", 0.0))
    except (TypeError, ValueError):
        conf = 0.0
    if conf < 0.15:
        return None
    if os.getenv("OMNI_INTENT_LRU", "1").strip().lower() not in ("0", "false", "no", "off"):
        intent_cache_set(_intent_lru_cache_key(state, player_input), obj)
    return obj
