"""Prompt-adversarial / spam guards for the intent resolver path (engine-owned heuristics)."""

from __future__ import annotations

import os
import re
from typing import Any, Dict, Tuple

from engine.core import error_taxonomy as EC

_INJECTION_PATTERNS = (
    re.compile(r"\[?\s*system\s*\]", re.I),
    re.compile(r"ignore\s+(all\s+)?(previous|prior)\s+instructions", re.I),
    re.compile(r"you\s+are\s+now\s+(a\s+)?d(an|eveloper)", re.I),
    re.compile(r"<\s*/?\s*script", re.I),
    re.compile(r"jailbreak", re.I),
)


def sanitize_player_command_text(cmd: str) -> str:
    t = str(cmd or "").replace("\x00", "")
    if len(t) > 8000:
        t = t[:8000]
    return t.strip()


def security_flags_for_intent_input(player_input: str) -> Dict[str, Any]:
    s = str(player_input or "")
    hits = sum(1 for p in _INJECTION_PATTERNS if p.search(s))
    return {
        "injection_pattern_hits": hits,
        "block_resolver": hits >= 2,
        "reason": EC.SECURITY_BLOCKED if hits >= 2 else "",
    }


def check_llm_intent_budget(state: dict[str, Any]) -> Tuple[bool, str]:
    """Cap LLM intent calls per simulated day (deterministic counter)."""
    meta = state.setdefault("meta", {})
    try:
        day = int(meta.get("day", 1) or 1)
    except (TypeError, ValueError):
        day = 1
    try:
        cap = int(os.getenv("OMNI_FFCI_LLM_INTENTS_PER_DAY", "400") or 400)
    except ValueError:
        cap = 400
    cap = max(32, min(5000, cap))
    hist = meta.get("ffci_llm_intent_day_counts")
    if not isinstance(hist, dict):
        hist = {}
    k = str(day)
    c = int(hist.get(k, 0) or 0)
    if c >= cap:
        return False, "ffci_llm_daily_budget"
    hist[k] = c + 1
    meta["ffci_llm_intent_day_counts"] = hist
    return True, ""


def record_intent_budget_rollback(state: dict[str, Any]) -> None:
    """If LLM call failed after incrementing budget, roll back last increment."""
    meta = state.get("meta", {}) or {}
    hist = meta.get("ffci_llm_intent_day_counts")
    if not isinstance(hist, dict):
        return
    try:
        day = int(meta.get("day", 1) or 1)
    except (TypeError, ValueError):
        day = 1
    k = str(day)
    c = int(hist.get(k, 0) or 0)
    if c > 0:
        hist[k] = c - 1
