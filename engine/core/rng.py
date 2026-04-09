from __future__ import annotations

import hashlib
from typing import Any


def det_roll_1_100(*parts: Any) -> int:
    """Deterministic d100 roll from arbitrary parts (stable across runs)."""
    s = "|".join(str(p) for p in parts)
    h = hashlib.md5(s.encode("utf-8", errors="ignore")).hexdigest()
    return (int(h[:8], 16) % 100) + 1


def roll_for_action(state: dict[str, Any], action_ctx: dict[str, Any], *, salt: str = "") -> int:
    """Deterministic roll tied to the current turn + intent text."""
    meta = state.get("meta", {}) or {}
    seed = str(meta.get("seed_pack", "") or "")
    day = int(meta.get("day", 1) or 1)
    turn = int(meta.get("turn", 0) or 0)
    loc = str((state.get("player", {}) or {}).get("location", "") or "").strip().lower()
    domain = str(action_ctx.get("domain", "") or "")
    act = str(action_ctx.get("action_type", "") or "")
    norm = str(action_ctx.get("normalized_input", "") or "")
    # Include a stable actor label
    who = str((state.get("player", {}) or {}).get("name", "__player__") or "__player__")
    return det_roll_1_100(seed, day, turn, loc, who, domain, act, norm[:120], salt)

