from __future__ import annotations

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
    except Exception:
        n = 1
    if n <= 3:
        state.setdefault("world_notes", []).append(f"[ERR:{where}] {type(err).__name__}: {str(err)[:120]}")

