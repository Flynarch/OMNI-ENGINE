from __future__ import annotations

import json
import os
from typing import Any, Dict, Optional

from ai.llm_http import chat_completion_json


INTENT_SYSTEM_PROMPT = """OMNI-ENGINE v6.8 — INTENT RESOLVER.
You are a STRICT json-serializer for player intent in a simulation.

You do NOT narrate. You do NOT describe feelings. You ONLY return a single JSON object.

The human types a natural language command as PLAYER_INPUT plus a short ENGINE_SNAPSHOT.
Your job is to infer what the player character is TRYING TO DO in this world.

Return ONE JSON object with keys:
- action_type: one of ["instant","combat","travel","sleep","rest","talk","investigate","use_item","custom"]
- domain: one of ["evasion","combat","social","hacking","medical","driving","stealth","other"]
- combat_style: one of ["melee","ranged","none"] (only meaningful when domain="combat"; otherwise use "none")
- social_mode: one of ["non_conflict","conflict","none"]
- social_context: one of ["standard","formal","street","none"]
- intent_note: short snake_case label (e.g. "social_dialogue", "ask_time", "look_for_person")
- targets: array of short strings naming people/things/places if mentioned
- stakes: one of ["none","low","medium","high"]
- risk_level: one of ["low","medium","high"]
- time_cost_min: integer minutes 0-60 (how long this action realistically takes; 0 means use engine default)
- travel_destination: short place name if action_type="travel" (e.g. "jakarta", "london"), else "none"
- inventory_ops: array of operations (may be empty). Each operation is one of:
  - {"op":"stow","from":"r_hand|l_hand","to":"pocket|bag","time_cost_min":1}
  - {"op":"swap_hands","time_cost_min":1}
  - {"op":"drop","from":"r_hand|l_hand","time_cost_min":1}
  - {"op":"equip_weapon","weapon_id":"<id>","time_cost_min":1}
  - {"op":"pickup","item_id":"<id>","to":"pocket|bag","time_cost_min":1}
- confidence: float 0.0-1.0 of your confidence in this interpretation

Rules:
- If the player is simply talking / asking questions / looking around, that is usually social_mode=\"non_conflict\" and stakes=\"low\".
- ONLY use social_mode=\"conflict\" when there is explicit coercion, threat, deception, or tense negotiation.
- If you are confused, choose the simplest plausible intent and set confidence<=0.5.
- NEVER invent enemies or weapons if not clearly stated.
- For combat: if the player mentions shooting/aiming/ranged weapon/firearm OR Indonesian equivalents (tembak/menembak/shot/pistol/senjata/senapan/rifle), use combat_style=\"ranged\" and domain=\"combat\".
- For melee combat: if the player mentions stabbing/striking/melee weapon OR Indonesian equivalents (tusuk/pukul/memukul/hantam/tendang/pisau), use combat_style=\"melee\" and domain=\"combat\".
- If the player wants to fight but doesn't specify style, set combat_style=\"none\".
- If nothing matches, set domain=\"other\" and action_type=\"instant\".
- For time_cost_min: simple talk/look around = 1-3, searching a place = 5-15, breaking in = 10-30, combat = 1, travel handled by action_type travel.
- For inventory_ops: if the player wants to pick up / use a large object while holding something, add stow/swap/drop operations so the main action can proceed without \"wasting a turn\". Prefer stow to pocket/bag over drop.
- For inventory_ops pickup: if the player references an object being in the current scene (e.g. \"laptop di meja\", \"HP di saku\", \"barang di tas\") and the object id can be inferred from nearby_items in the ENGINE_SNAPSHOT, add:
  - {"op":"pickup","item_id":"<id>","to":"pocket|bag","time_cost_min":1}
- For inventory_ops weapon switching: if PLAYER_INPUT implies using a different weapon (\"senjata yang satunya\", \"other gun\") and weapon_ids has multiple entries, add:
  - equip_weapon for the other weapon_id (prefer this; do NOT stow unless hands are actually holding a non-weapon item)
  - If the input also includes shooting (tembak/menembak/shoot), then this is NOT a pure switch: set action_type=\"combat\" and stakes at least \"medium\".

Examples (you still must return ONLY JSON):
- \"aku menembak orang bersenjata di depan\" => action_type=\"combat\", domain=\"combat\", combat_style=\"ranged\", social_mode=\"none\", stakes=\"high\"
- \"aku pukul orang yang menghalangi jalan\" => action_type=\"combat\", domain=\"combat\", combat_style=\"melee\", stakes=\"medium\"
- \"aku mau bicara dengan orang sekitar\" => action_type=\"talk\", domain=\"social\", social_mode=\"non_conflict\", stakes=\"low\"
- \"aku memaksa orang itu untuk ngomong sekarang\" => domain=\"social\", social_mode=\"conflict\", stakes=\"medium\"
- \"memegang pistol aku mencoba menembakan senjata yang satunya\" => action_type=\"combat\", domain=\"combat\", combat_style=\"ranged\", intent_note=\"switch_then_shoot\", stakes=\"high\", inventory_ops=[{\"op\":\"equip_weapon\",\"weapon_id\":\"<other>\",\"time_cost_min\":1}]
- \"sedang di kafe dan laptop di meja, aku akan balik ke kos\" => action_type=\"travel\", domain=\"other\", social_mode=\"none\", stakes=\"low\", time_cost_min=10, inventory_ops=[{\"op\":\"pickup\",\"item_id\":\"<nearby_item_id>\",\"to\":\"bag\",\"time_cost_min\":2}]
- \"pergi ke jakarta\" => action_type=\"travel\", domain=\"other\", social_mode=\"none\", stakes=\"low\", time_cost_min=90, travel_destination=\"jakarta\", inventory_ops=[]

Return ONLY the JSON, no explanation, no markdown.
"""


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
    # Minimal sanity checks
    if "domain" not in obj or "action_type" not in obj:
        return None
    try:
        conf = float(obj.get("confidence", 0.0))
    except Exception:
        conf = 0.0
    if conf < 0.15:
        return None
    return obj

