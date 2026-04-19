"""Player language scores from ``state`` only (no atlas).

Split out so ``engine.world.atlas`` can use proficiency for travel gates without
importing ``engine.core.language`` (which imports atlas for location profiles).
"""

from __future__ import annotations

from engine.core.error_taxonomy import log_swallowed_exception
from typing import Any


def player_language_proficiency(state: dict[str, Any]) -> dict[str, int]:
    p = state.get("player", {}) or {}
    langs = p.get("languages", {}) if isinstance(p, dict) else {}
    out: dict[str, int] = {}
    if isinstance(langs, dict):
        for k, v in langs.items():
            try:
                out[str(k).lower()] = max(0, min(100, int(v or 0)))
            except Exception as _omni_sw_22:
                log_swallowed_exception('engine/core/player_language_levels.py:22', _omni_sw_22)
                continue
    base = str((p.get("language", "en") if isinstance(p, dict) else "en") or "en").strip().lower()
    if base and base not in out:
        out[base] = 70
    return out
