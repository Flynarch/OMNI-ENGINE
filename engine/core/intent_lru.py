"""Tiny LRU for LLM intent results (same schema + coarse state bucket)."""

from __future__ import annotations

from collections import OrderedDict
from typing import Any, Dict, Optional, Tuple

_CACHE: OrderedDict[Tuple[Any, ...], Dict[str, Any]] = OrderedDict()
_MAX = 64


def intent_cache_get(key: Tuple[Any, ...]) -> Optional[Dict[str, Any]]:
    if key not in _CACHE:
        return None
    val = _CACHE.pop(key)
    _CACHE[key] = val
    return dict(val)


def intent_cache_set(key: Tuple[Any, ...], intent: Dict[str, Any]) -> None:
    if key in _CACHE:
        _CACHE.pop(key, None)
    _CACHE[key] = dict(intent)
    while len(_CACHE) > _MAX:
        _CACHE.popitem(last=False)


def clear_intent_cache() -> None:
    _CACHE.clear()
