from __future__ import annotations

import json
import os
from typing import Any, Dict, Optional

from ai.llm_http import chat_completion_json


INTENT_SYSTEM_PROMPT = """OMNI-ENGINE v6.9 — INTENT RESOLVER (Schema v2).
You are a STRICT json-serializer for player intent in a simulation.

You do NOT narrate. You do NOT describe feelings. You ONLY return a single JSON object.

The human types a natural language command as PLAYER_INPUT plus a short ENGINE_SNAPSHOT.
Your job is to infer what the player character is TRYING TO DO in this world.

Return ONE JSON object using this schema (Intent v2):

Top-level keys:
- version: 2
- confidence: float 0.0-1.0
- player_goal: short string
- context_assumptions: array of short strings (may be empty)
- plan: object with:
  - plan_id: short string
  - steps: array (1..4) of step objects
- safety: object with:
  - refuse: boolean
  - refuse_reason: short string (empty if refuse=false)

Step object keys:
- step_id: short string
- label: short string
- action_type: one of ["instant","combat","travel","sleep","rest","talk","investigate","use_item","custom"]
- domain: one of ["evasion","combat","social","hacking","medical","driving","stealth","other"]
- combat_style: one of ["melee","ranged","none"] (only meaningful when domain="combat"; otherwise use "none")
- social_mode: one of ["non_conflict","conflict","none"]
- social_context: one of ["standard","formal","street","none"]
- intent_note: short snake_case label
- targets: array of short strings
- stakes: one of ["none","low","medium","high"]
- risk_level: one of ["low","medium","high"]
- time_cost_min: integer minutes 0-240 (0 means use engine default)
- travel_destination: short place name if action_type="travel", else "".
- inventory_ops: array of inventory micro-ops (same shapes as v1)
- preconditions: array of simple preconditions (may be empty). Each is:
  - {"kind":"hands_free|has_item|scene_phase|target_visible|npc_alive|location_is|district_is","op":"eq|neq|in","value":<json>}
- on_success: array of {"next":"<step_id>","when":"always|if_possible"} (may be empty)
- on_failure: array of {"next":"<step_id>","when":"always|if_blocked|if_failed_roll"} (may be empty)

Rules:
- Keep steps minimal. Prefer 1 step unless player explicitly asks for conditional/multi-step.
- For conditionals: represent as step2 with preconditions, and link via on_success/on_failure.
- NEVER invent enemies or weapons if not clearly stated.
- If confused: choose simplest plausible step plan and set confidence<=0.5.
- Consensual private adult intimacy (fade-to-black): action_type="talk", domain="social", social_mode="non_conflict", intent_note="intimacy_private", stakes="medium", time_cost_min 45-90.
- Refuse disallowed content by setting safety.refuse=true.

Return ONLY the JSON, no explanation, no markdown.
"""


def _flatten_intent_v2_for_compat(obj: Dict[str, Any]) -> Dict[str, Any]:
    """Derive v1-like top-level keys from v2 so existing callers can keep working."""
    out = dict(obj)
    plan = out.get("plan") if isinstance(out.get("plan"), dict) else {}
    steps = plan.get("steps") if isinstance(plan.get("steps"), list) else []
    step0 = steps[0] if steps and isinstance(steps[0], dict) else {}
    # v1-compat fields expected by main.py
    for k in (
        "action_type",
        "domain",
        "combat_style",
        "social_mode",
        "social_context",
        "intent_note",
        "targets",
        "stakes",
        "risk_level",
        "time_cost_min",
        "travel_destination",
        "inventory_ops",
    ):
        if k in step0 and step0.get(k) is not None:
            out[k] = step0.get(k)
    # A stable hint for future engine compilation
    if "step_now_id" not in out and isinstance(step0.get("step_id"), str):
        out["step_now_id"] = step0.get("step_id")
    return out


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
        timeout=60.0,
    )
    content = data["choices"][0]["message"]["content"]
    return str(content)


def _safe_parse_json_blob(text: str) -> Optional[Dict[str, Any]]:
    """Try to extract a single JSON object from raw LLM text (robust to ``` fences)."""
    text = text.strip()
    if not text:
        return None
    # Strip Markdown fences if present
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
        # Try substring between first { and last }
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
    user = f"[ENGINE_SNAPSHOT]\n{summary}\n[PLAYER_INPUT]\n{player_input}\n"
    try:
        raw = _invoke_llm_for_intent({"user": user})
    except Exception:
        return None
    obj = _safe_parse_json_blob(raw)
    if not obj:
        return None
    # Minimal sanity checks (v1 or v2)
    if int(obj.get("version", 1) or 1) == 2:
        if "plan" not in obj or not isinstance(obj.get("plan"), dict):
            return None
        steps = (obj.get("plan") or {}).get("steps")
        if not (isinstance(steps, list) and steps and isinstance(steps[0], dict)):
            return None
        obj = _flatten_intent_v2_for_compat(obj)
    else:
        if "domain" not in obj or "action_type" not in obj:
            return None
    try:
        conf = float(obj.get("confidence", 0.0))
    except Exception:
        conf = 0.0
    if conf < 0.15:
        return None
    return obj

