"""Prune unbounded ``world_notes`` and ``world.news_feed`` into bounded active state + archive.

Rules (in-game days from ``meta.day``):
- Entries older than ``MAX_FEED_AGE_DAYS`` are removed from active state and appended to
  ``save/archive.json`` (merged under keys ``world_notes`` / ``news_feed``).
- Active lists are capped at ``MAX_FEED_ENTRIES``, keeping the most recent items (list tail).

Plain-string ``world_notes`` entries are normalized to ``{"day": meta.day, "text": ...}`` on prune.

Optional env (integers, clamped): ``OMNI_FEED_MAX_AGE_DAYS`` (1–365, default 7),
``OMNI_FEED_MAX_ENTRIES`` (10–500, default 100), ``OMNI_FEED_ARCHIVE_LIST_CAP`` (100–50000, default 5000).
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from engine.core.error_taxonomy import log_swallowed_exception

ROOT = Path(__file__).resolve().parents[2]
SAVE_DIR = ROOT / "save"
DEFAULT_ARCHIVE_PATH = SAVE_DIR / "archive.json"

MAX_FEED_AGE_DAYS = 7
MAX_FEED_ENTRIES = 100
ARCHIVE_LIST_CAP = 5000


def effective_prune_limits() -> tuple[int, int, int]:
    """Return ``(max_age_days, max_active_entries, archive_list_cap)`` after env overrides."""
    try:
        age = int(os.getenv("OMNI_FEED_MAX_AGE_DAYS", str(MAX_FEED_AGE_DAYS)) or MAX_FEED_AGE_DAYS)
    except Exception as _omni_sw_43:
        log_swallowed_exception("engine/core/feed_prune.py:limits_age", _omni_sw_43)
        age = MAX_FEED_AGE_DAYS
    try:
        ent = int(os.getenv("OMNI_FEED_MAX_ENTRIES", str(MAX_FEED_ENTRIES)) or MAX_FEED_ENTRIES)
    except Exception as _omni_sw_49:
        log_swallowed_exception("engine/core/feed_prune.py:limits_ent", _omni_sw_49)
        ent = MAX_FEED_ENTRIES
    try:
        cap = int(os.getenv("OMNI_FEED_ARCHIVE_LIST_CAP", str(ARCHIVE_LIST_CAP)) or ARCHIVE_LIST_CAP)
    except Exception as _omni_sw_55:
        log_swallowed_exception("engine/core/feed_prune.py:limits_cap", _omni_sw_55)
        cap = ARCHIVE_LIST_CAP
    return max(1, min(365, age)), max(10, min(500, ent)), max(100, min(50000, cap))


def world_note_plain(entry: Any) -> str:
    """Return display/search text for a world_notes element (legacy str or structured dict)."""
    if isinstance(entry, str):
        return entry
    if isinstance(entry, dict):
        t = entry.get("text", "")
        return str(t) if t is not None else ""
    return str(entry) if entry is not None else ""


def _current_day(state: dict[str, Any]) -> int:
    meta = state.get("meta", {}) or {}
    try:
        return int(meta.get("day", 1) or 1)
    except Exception as _omni_sw_40:
        log_swallowed_exception("engine/core/feed_prune.py:40", _omni_sw_40)
        return 1


def _note_day(entry: Any, fallback: int) -> int:
    if isinstance(entry, dict):
        try:
            return int(entry.get("day", fallback) or fallback)
        except Exception as _omni_sw_50:
            log_swallowed_exception("engine/core/feed_prune.py:50", _omni_sw_50)
            return int(fallback)
    return int(fallback)


def _normalize_world_notes(notes: list[Any], current_day: int) -> list[Any]:
    out: list[Any] = []
    for e in notes:
        if isinstance(e, str):
            out.append({"day": int(current_day), "text": e})
        elif isinstance(e, dict):
            d = dict(e)
            if "text" not in d:
                d["text"] = world_note_plain(e)
            if "day" not in d:
                d["day"] = int(current_day)
            out.append(d)
        else:
            out.append({"day": int(current_day), "text": world_note_plain(e)})
    return out


def _normalize_news_feed(feed: list[Any], current_day: int) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for it in feed:
        if isinstance(it, dict):
            d = dict(it)
            d.setdefault("day", int(current_day))
            d.setdefault("source", "broadcast")
            t = d.get("text", "")
            d["text"] = str(t)[:140] if t is not None else ""
            out.append(d)
        elif isinstance(it, str):
            out.append({"day": int(current_day), "text": str(it)[:140], "source": "broadcast"})
    return out


def _news_day(entry: dict[str, Any], fallback: int) -> int:
    try:
        return int(entry.get("day", fallback) or fallback)
    except Exception as _omni_sw_95:
        log_swallowed_exception("engine/core/feed_prune.py:95", _omni_sw_95)
        return int(fallback)


def _load_archive(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"version": 1, "world_notes": [], "news_feed": []}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            return {"version": 1, "world_notes": [], "news_feed": []}
        raw.setdefault("version", 1)
        raw.setdefault("world_notes", [])
        raw.setdefault("news_feed", [])
        if not isinstance(raw["world_notes"], list):
            raw["world_notes"] = []
        if not isinstance(raw["news_feed"], list):
            raw["news_feed"] = []
        return raw
    except Exception as _omni_sw_114:
        log_swallowed_exception("engine/core/feed_prune.py:114", _omni_sw_114)
        return {"version": 1, "world_notes": [], "news_feed": []}


def _write_archive(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _tail_cap(lst: list[Any], cap: int) -> None:
    if len(lst) > cap:
        del lst[:-cap]


def prune_world_notes_and_news_feed(state: dict[str, Any], *, archive_path: Path | None = None) -> None:
    """Apply age + length pruning; merge evicted items into archive JSON. Never raises."""
    try:
        path = archive_path if archive_path is not None else DEFAULT_ARCHIVE_PATH
        max_age, max_entries, arch_cap = effective_prune_limits()
        current_day = _current_day(state)
        cutoff = int(current_day) - int(max_age)

        notes = state.setdefault("world_notes", [])
        if not isinstance(notes, list):
            state["world_notes"] = []
            notes = state["world_notes"]

        normalized_notes = _normalize_world_notes(notes, current_day)
        archived_notes: list[Any] = []
        kept_notes: list[Any] = []
        for e in normalized_notes:
            if _note_day(e, current_day) < cutoff:
                archived_notes.append(e)
            else:
                kept_notes.append(e)
        if len(kept_notes) > max_entries:
            archived_notes.extend(kept_notes[:-max_entries])
            kept_notes = kept_notes[-max_entries:]
        notes[:] = kept_notes

        world = state.setdefault("world", {})
        feed = world.setdefault("news_feed", [])
        if not isinstance(feed, list):
            feed = []
        normalized_news = _normalize_news_feed(feed, current_day)
        archived_news: list[dict[str, Any]] = []
        kept_news: list[dict[str, Any]] = []
        for e in normalized_news:
            d = int(_news_day(e, current_day))
            if d < cutoff:
                archived_news.append(e)
            else:
                kept_news.append(e)
        if len(kept_news) > max_entries:
            archived_news.extend(kept_news[:-max_entries])
            kept_news = kept_news[-max_entries:]
        feed[:] = kept_news
        world["news_feed"] = feed

        if not archived_notes and not archived_news:
            return

        arch = _load_archive(path)
        arch["world_notes"].extend(archived_notes)
        arch["news_feed"].extend(archived_news)
        _tail_cap(arch["world_notes"], arch_cap)
        _tail_cap(arch["news_feed"], arch_cap)
        arch["last_pruned_meta_day"] = int(current_day)
        arch["last_pruned_at_utc"] = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
        _write_archive(path, arch)
    except Exception as _omni_sw_186:
        log_swallowed_exception("engine/core/feed_prune.py:186", _omni_sw_186)
