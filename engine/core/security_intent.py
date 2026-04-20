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

_INJECTION_NEUTRALIZE_RULES = (
    # Prompt-role tags and obvious instruction override phrases.
    (re.compile(r"(?i)\[\s*(system|developer|assistant|user)\s*\]"), "[role_redacted]"),
    (re.compile(r"(?i)<\s*/?\s*(system|assistant|developer|user|instruction|prompt)\s*>"), " "),
    (re.compile(r"(?i)\bignore\s+(all\s+)?(previous|prior)\s+instructions?\b"), "[instruction_override_redacted]"),
    (re.compile(r"(?i)\babaikan\s+instruksi\s+sebelumnya\b"), "[instruction_override_redacted]"),
    # Direct state manipulation requests commonly used in prompt injection.
    (re.compile(r"(?i)\b(set|grant|give|add|inject)\s+(me\s+)?(\$|rp|idr|usd|money|cash|bank|credits?)\b"), "[economy_mutation_redacted]"),
    (re.compile(r"(?i)\b(set|max|boost|increase)\s+(my\s+)?(stat|stats|hp|health|trace|heat|reputation|xp|level)\b"), "[stat_mutation_redacted]"),
)


def sanitize_player_command_text(cmd: str) -> str:
    return sanitize_player_input(cmd)


def sanitize_player_input(text: str) -> str:
    """Best-effort prompt-injection neutralizer for player text before LLM intent resolution."""
    t = str(text or "").replace("\x00", "")
    if len(t) > 8000:
        t = t[:8000]
    t = t.strip()
    for pat, repl in _INJECTION_NEUTRALIZE_RULES:
        try:
            t = pat.sub(repl, t)
        except Exception:
            continue
    # Collapse repeated whitespace after replacements so parser paths remain stable.
    t = re.sub(r"\s{2,}", " ", t).strip()
    return t


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
