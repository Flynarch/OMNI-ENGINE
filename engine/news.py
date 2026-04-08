from __future__ import annotations

from typing import Any


def push_news(state: dict[str, Any], *, text: str, source: str = "broadcast", day: int | None = None) -> None:
    """Append a bounded, structured headline to world.news_feed with dedup.

    Schema: {day, text, source}
    """
    meta = state.get("meta", {}) or {}
    d = int(meta.get("day", 1) or 1) if day is None else int(day or 1)
    world = state.setdefault("world", {})
    feed = world.setdefault("news_feed", [])
    if not isinstance(feed, list):
        feed = []
        world["news_feed"] = feed

    t = str(text)[:140]
    src = str(source or "broadcast")

    for it in feed[-12:]:
        if isinstance(it, dict) and int(it.get("day", -1)) == d and str(it.get("text", "")) == t:
            return
    feed.append({"day": d, "text": t, "source": src})
    world["news_feed"] = feed[-50:]

