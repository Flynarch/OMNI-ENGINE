from __future__ import annotations

import json
import os
from typing import Any, Dict, List, Optional, Set, Tuple

from ai.llm_http import chat_completion_json

# Contract version for intent JSON (bumped when required fields / shape changes).
INTENT_SCHEMA_VERSION = 2
# Minimum schema accepted by normalize_resolved_intent (roadmap: intent schema versioning).
INTENT_SCHEMA_MIN_SUPPORTED = INTENT_SCHEMA_VERSION

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
    }
)
ON_LINK_KEYS: Set[str] = frozenset({"next", "when"})
PRECONDITION_KEYS: Set[str] = frozenset({"kind", "op", "value"})


INTENT_SYSTEM_PROMPT = """OMNI-ENGINE v6.9 — INTENT RESOLVER (Schema v2, intent_schema_version=2).
You are a STRICT json-serializer for player intent in a simulation.

You do NOT narrate. You do NOT describe feelings. You ONLY return a single JSON object.

The human types a natural language command as PLAYER_INPUT plus a short ENGINE_SNAPSHOT.
Your job is to infer what the player character is TRYING TO DO in this world.
Support slang, abbreviations, mixed languages, and abstract phrasing; map them to structured fields.

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


def normalize_resolved_intent(obj: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Validate + whitelist a parsed LLM intent dict. Returns None if unusable."""
    if not isinstance(obj, dict):
        return None
    try:
        ver = int(obj.get("version", 1) or 1)
    except (TypeError, ValueError):
        ver = 1

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
        return base

    # v1 flat (legacy LLM or sleep fastpath)
    flat = _only_keys(obj, TOP_LEVEL_V1_KEYS)
    try:
        flat["version"] = int(flat.get("version", 1) or 1)
    except (TypeError, ValueError):
        flat["version"] = 1
    flat["intent_schema_version"] = INTENT_SCHEMA_VERSION
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
        if at == "sleep":
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
        from engine.core.intent_lru import intent_cache_get, intent_cache_set

        ck = _intent_lru_cache_key(state, player_input)
        hit = intent_cache_get(ck)
        if isinstance(hit, dict):
            return hit
    from engine.core.security_intent import check_llm_intent_budget, record_intent_budget_rollback

    ok_budget, _br = check_llm_intent_budget(state)
    if not ok_budget:
        return None
    user = f"[ENGINE_SNAPSHOT]\n{summary}\n[PLAYER_INPUT]\n{player_input}\n"
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
        from engine.core.intent_lru import intent_cache_set

        intent_cache_set(_intent_lru_cache_key(state, player_input), obj)
    return obj
