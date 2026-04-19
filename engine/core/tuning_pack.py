"""Versioned JSON tuning knobs (live tuning pack — data-only where possible)."""

from __future__ import annotations

from engine.core.error_taxonomy import log_swallowed_exception
import json
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict

_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_PATH = _ROOT / "data" / "ffci_tuning.json"


@lru_cache(maxsize=1)
def load_ffci_tuning(path: str | None = None) -> dict[str, Any]:
    p = Path(path) if path else _DEFAULT_PATH
    if not p.exists():
        return {"pack_version": 0}
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
        return raw if isinstance(raw, dict) else {"pack_version": 0}
    except Exception as _omni_sw_22:
        log_swallowed_exception('engine/core/tuning_pack.py:22', _omni_sw_22)
        return {"pack_version": 0}


def tuning_int(key: str, default: int, *, path: str | None = None) -> int:
    pack = load_ffci_tuning(path)
    try:
        return int(pack.get(key, default))
    except (TypeError, ValueError):
        return default
