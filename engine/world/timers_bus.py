from __future__ import annotations

from typing import Any


def can_surface_ripple(state: dict[str, Any], rp: dict[str, Any]) -> bool:
    """Visibility/propagation gate shared by timers and handlers."""
    propagation = str(rp.get("propagation", "local_witness") or "local_witness").lower()
    origin_loc = str(rp.get("origin_location", "") or "").strip().lower()
    cur_loc = str(state.get("player", {}).get("location", "") or "").strip().lower()
    origin_faction = str(rp.get("origin_faction", "") or "").strip().lower()

    if propagation in ("local", "local_witness", "witness"):
        return bool(origin_loc and cur_loc and origin_loc == cur_loc)

    if propagation in ("contacts", "contact_network"):
        contacts = (state.get("world", {}) or {}).get("contacts", {}) or {}
        if not isinstance(contacts, dict) or len(contacts) == 0:
            return False
        if origin_faction:
            for _n, c in contacts.items():
                if not isinstance(c, dict):
                    continue
                aff = str(c.get("affiliation", "") or "").strip().lower()
                if aff == origin_faction:
                    return True
            try:
                for _n, c in contacts.items():
                    if not isinstance(c, dict):
                        continue
                    if int(c.get("trust", 0) or 0) >= 85:
                        return int(rp.get("surface_attempts", 0) or 0) >= 1
            except Exception:
                return False
            try:
                return int(rp.get("surface_attempts", 0) or 0) >= 2
            except Exception:
                return False
        return True

    if propagation in ("faction_network", "global", "broadcast"):
        return True

    return False


def push_news(state: dict[str, Any], *, text: str, source: str = "broadcast") -> None:
    """Append a bounded, structured headline to world.news_feed."""
    try:
        from engine.social.news import push_news as _push

        _push(state, text=text, source=source)
    except Exception:
        meta = state.get("meta", {}) or {}
        day = int(meta.get("day", 1) or 1)
        world = state.setdefault("world", {})
        feed = world.setdefault("news_feed", [])
        if not isinstance(feed, list):
            feed = []
            world["news_feed"] = feed
        t = str(text)[:140]
        feed.append({"day": day, "text": t, "source": str(source or "broadcast")[:24]})
        world["news_feed"] = feed[-100:]


def enqueue_ripple(state: dict[str, Any], rp: dict[str, Any]) -> None:
    """Queue ripple with dedupe/fallback semantics."""
    try:
        from engine.social.ripple_queue import enqueue_ripple as _enqueue

        _enqueue(state, rp)
    except Exception:
        arr = state.setdefault("active_ripples", [])
        if not isinstance(arr, list):
            arr = []
        arr.append(rp)
        state["active_ripples"] = arr[-200:]
