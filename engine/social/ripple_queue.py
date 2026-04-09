from __future__ import annotations

from typing import Any


def _stable_meta(meta: dict[str, Any]) -> list[tuple[str, Any]]:
    """Reduce meta to stable keys for dedup signatures.

    Avoid volatile fields like expiry timestamps or counters which would defeat dedup.
    """
    allow = (
        "npc",
        "role",
        "service",
        "delivery_id",
        "quest_id",
        "target",
        "city",
        "country",
        "item_id",
        "faction",
        "tier",
    )
    out: list[tuple[str, Any]] = []
    for k in allow:
        if k in meta:
            v = meta.get(k)
            if isinstance(v, (str, int, float, bool)) or v is None:
                out.append((str(k), v))
            else:
                out.append((str(k), str(v)[:80]))
    return sorted(out)


def _sig(rp: dict[str, Any]) -> str:
    try:
        kind = str(rp.get("kind", "") or "")
        prop = str(rp.get("propagation", "") or "")
        ol = str(rp.get("origin_location", "") or "")
        of = str(rp.get("origin_faction", "") or "")
        meta = rp.get("meta") if isinstance(rp.get("meta"), dict) else {}
        sm = _stable_meta(meta) if isinstance(meta, dict) else []
        return f"{kind}|{prop}|{ol}|{of}|{sm}|{str(rp.get('text','') or '')[:80]}"
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

