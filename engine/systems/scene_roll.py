"""Deterministic scene RNG and small state readers (no ``scenes`` / ``search_conceal`` imports).

Split from ``scenes`` so ``search_conceal.resolve_search`` can roll without importing
``engine.systems.scenes`` (which imports ``search_conceal``).
"""

from __future__ import annotations

import hashlib
from typing import Any


def _now(state: dict[str, Any]) -> tuple[int, int]:
    meta = state.get("meta", {}) or {}
    try:
        day = int(meta.get("day", 1) or 1)
    except Exception:
        day = 1
    try:
        tmin = int(meta.get("time_min", 0) or 0)
    except Exception:
        tmin = 0
    return (day, tmin)


def _seed_key(state: dict[str, Any]) -> str:
    meta = state.get("meta", {}) or {}
    if isinstance(meta, dict):
        ws = str(meta.get("world_seed", "") or "").strip()
        if ws:
            return ws
        sp = str(meta.get("seed_pack", "") or "").strip()
        if sp:
            return sp
    return "seed"


def _player_loc(state: dict[str, Any]) -> tuple[str, str]:
    p = state.get("player", {}) or {}
    loc = str(p.get("location", "") or "").strip().lower()
    did = str(p.get("district", "") or "").strip().lower()
    return (loc, did)


def _h100(*parts: Any) -> int:
    s = "|".join([str(p) for p in parts])
    h = hashlib.md5(s.encode("utf-8", errors="ignore")).hexdigest()
    return int(h[:8], 16) % 100


def scene_rng(state: dict[str, Any], *, scene_id: str, scene_type: str, salt: str) -> int:
    """Deterministic 0..99 RNG for scenes (never use random())."""
    seed = _seed_key(state)
    day, tmin = _now(state)
    meta = state.get("meta", {}) or {}
    try:
        turn = int(meta.get("turn", 0) or 0)
    except Exception:
        turn = 0
    loc, did = _player_loc(state)
    return _h100(seed, day, tmin, turn, loc, did, str(scene_id), str(scene_type), str(salt))
