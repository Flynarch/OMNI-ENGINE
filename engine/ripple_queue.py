from __future__ import annotations

from typing import Any


def _sig(rp: dict[str, Any]) -> str:
    try:
        kind = str(rp.get("kind", "") or "")
        prop = str(rp.get("propagation", "") or "")
        ol = str(rp.get("origin_location", "") or "")
        of = str(rp.get("origin_faction", "") or "")
        meta = rp.get("meta") if isinstance(rp.get("meta"), dict) else {}
        return f"{kind}|{prop}|{ol}|{of}|{sorted(list(meta.items()))}|{str(rp.get('text','') or '')[:80]}"
    except Exception:
        return ""


def enqueue_ripple(state: dict[str, Any], rp: dict[str, Any]) -> None:
    """Enqueue ripple into state.active_ripples with shared dedup semantics.

    Dedup uses: kind + propagation + origin_location + origin_faction + meta + text prefix.
    Falls back to text-only if signature can't be computed.
    """
    if not isinstance(rp, dict):
        return
    ar = state.setdefault("active_ripples", [])
    if not isinstance(ar, list):
        ar = []
        state["active_ripples"] = ar

    sig = _sig(rp)
    if sig:
        for x in ar[-30:]:
            if not isinstance(x, dict):
                continue
            if x.get("surfaced"):
                continue
            if _sig(x) == sig:
                return
    else:
        # Conservative fallback: dedup by exact text.
        text = rp.get("text")
        for x in ar[-20:]:
            if isinstance(x, dict) and x.get("text") == text and not x.get("surfaced"):
                return

    ar.append(rp)

