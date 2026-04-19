from __future__ import annotations

from engine.core.error_taxonomy import log_swallowed_exception
from typing import Any


def record_error(state: dict[str, Any], where: str, err: Exception) -> None:
    """Record a lightweight error marker without crashing the game."""
    meta = state.setdefault("meta", {})
    if isinstance(meta, dict):
        errs = meta.setdefault("errors", {})
        if not isinstance(errs, dict):
            errs = {}
            meta["errors"] = errs
        key = str(where or "unknown")
        errs[key] = int(errs.get(key, 0) or 0) + 1
        meta["errors"] = errs
    # Avoid spamming: only append first few occurrences per location.
    try:
        n = int(((state.get("meta", {}) or {}).get("errors", {}) or {}).get(where, 0) or 0)
    except Exception as _omni_sw_20:
        log_swallowed_exception('engine/core/errors.py:20', _omni_sw_20)
        n = 1
    if n <= 3:
        state.setdefault("world_notes", []).append(f"[ERR:{where}] {type(err).__name__}: {str(err)[:120]}")

