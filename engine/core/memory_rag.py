"""Lightweight archive RAG for long-horizon narration memory.

This module keeps a tiny TF-IDF-like index sidecar for ``save/archive.json`` and
returns top-k relevant archived notes for a query (usually latest player input).
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from pathlib import Path
from typing import Any

from engine.core.error_taxonomy import log_swallowed_exception

_TOKEN_RE = re.compile(r"[a-z0-9_]{2,}", re.I)
_STOPWORDS = frozenset(
    {
        "the",
        "and",
        "for",
        "with",
        "that",
        "this",
        "from",
        "into",
        "about",
        "kamu",
        "yang",
        "dan",
        "untuk",
        "dari",
        "ke",
        "di",
        "ini",
        "itu",
        "aku",
        "saya",
    }
)
_MAX_DOCS = 12000
_RECENCY_HALF_LIFE_DAYS = 14.0


def _index_path_for_archive(archive_path: Path) -> Path:
    return archive_path.with_name("archive_memory_index.json")


def _tokenize(text: str) -> list[str]:
    if not text:
        return []
    toks = [t.lower() for t in _TOKEN_RE.findall(text)]
    return [t for t in toks if t not in _STOPWORDS]


def _text_from_world_note(entry: Any) -> tuple[int, str]:
    if isinstance(entry, dict):
        try:
            day = int(entry.get("day", 1) or 1)
        except Exception:
            day = 1
        txt = str(entry.get("text", "") or "").strip()
        return day, txt
    if isinstance(entry, str):
        return 1, entry.strip()
    return 1, str(entry or "").strip()


def _text_from_news(entry: Any) -> tuple[int, str]:
    if isinstance(entry, dict):
        try:
            day = int(entry.get("day", 1) or 1)
        except Exception:
            day = 1
        txt = str(entry.get("text", "") or "").strip()
        src = str(entry.get("source", "") or "").strip()
        return day, f"{src}: {txt}" if src else txt
    if isinstance(entry, str):
        return 1, entry.strip()
    return 1, str(entry or "").strip()


def _doc_id(source: str, day: int, text: str) -> str:
    seed = f"{source}|{day}|{text}".encode("utf-8", errors="ignore")
    return hashlib.sha1(seed).hexdigest()[:20]


def _load_index(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"version": 1, "doc_count": 0, "df": {}, "docs": []}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        log_swallowed_exception("engine/core/memory_rag.py:load_index", e)
        return {"version": 1, "doc_count": 0, "df": {}, "docs": []}
    if not isinstance(raw, dict):
        return {"version": 1, "doc_count": 0, "df": {}, "docs": []}
    docs = raw.get("docs")
    df = raw.get("df")
    if not isinstance(docs, list):
        docs = []
    if not isinstance(df, dict):
        df = {}
    return {
        "version": 1,
        "doc_count": int(raw.get("doc_count", len(docs)) or len(docs)),
        "df": {str(k): int(v or 0) for k, v in df.items() if str(k)},
        "docs": docs,
    }


def _save_index(path: Path, idx: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(idx, ensure_ascii=False, indent=2), encoding="utf-8")


def _load_archive_docs_for_fallback(archive_path: Path) -> list[dict[str, Any]]:
    """Fallback: parse archive.json directly when sidecar index is missing/corrupt."""
    if not archive_path.exists():
        return []
    try:
        raw = json.loads(archive_path.read_text(encoding="utf-8"))
    except Exception as e:
        log_swallowed_exception("engine/core/memory_rag.py:load_archive_fallback", e)
        return []
    if not isinstance(raw, dict):
        return []
    docs: list[dict[str, Any]] = []
    for e in (raw.get("world_notes") or [])[:_MAX_DOCS]:
        day, txt = _text_from_world_note(e)
        if txt:
            docs.append({"source": "world_note", "day": int(day), "text": txt[:360]})
    for e in (raw.get("news_feed") or [])[:_MAX_DOCS]:
        day, txt = _text_from_news(e)
        if txt:
            docs.append({"source": "news_feed", "day": int(day), "text": txt[:360]})
    return docs[-_MAX_DOCS:]


def _add_doc(idx: dict[str, Any], *, source: str, day: int, text: str) -> None:
    t = str(text or "").strip()
    if not t:
        return
    terms = _tokenize(t)
    if not terms:
        return
    did = _doc_id(source, day, t)
    docs = idx.get("docs")
    if not isinstance(docs, list):
        return
    if any(isinstance(d, dict) and str(d.get("id", "")) == did for d in docs):
        return
    tf: dict[str, int] = {}
    for tok in terms[:128]:
        tf[tok] = int(tf.get(tok, 0) or 0) + 1
    df = idx.get("df")
    if isinstance(df, dict):
        for tok in tf.keys():
            df[tok] = int(df.get(tok, 0) or 0) + 1
    docs.append(
        {
            "id": did,
            "source": source,
            "day": int(day),
            "text": t[:360],
            "tf": tf,
            "len": int(sum(tf.values()) or 1),
        }
    )
    idx["doc_count"] = int(idx.get("doc_count", 0) or 0) + 1
    if len(docs) > _MAX_DOCS:
        # Keep newest tail. Rebuild df/doc_count cheaply.
        idx["docs"] = docs[-_MAX_DOCS:]
        _rebuild_df(idx)


def _rebuild_df(idx: dict[str, Any]) -> None:
    docs = idx.get("docs") if isinstance(idx.get("docs"), list) else []
    df: dict[str, int] = {}
    for d in docs:
        if not isinstance(d, dict):
            continue
        tf = d.get("tf")
        if not isinstance(tf, dict):
            continue
        for tok in tf.keys():
            sk = str(tok or "")
            if sk:
                df[sk] = int(df.get(sk, 0) or 0) + 1
    idx["df"] = df
    idx["doc_count"] = len(docs)


def append_archived_entries_to_index(archive_path: Path, archived_notes: list[Any], archived_news: list[Any]) -> None:
    """Append newly archived entries into sidecar memory index."""
    try:
        ip = _index_path_for_archive(archive_path)
        idx = _load_index(ip)
        for e in archived_notes[:4096]:
            day, txt = _text_from_world_note(e)
            _add_doc(idx, source="world_note", day=day, text=txt)
        for e in archived_news[:4096]:
            day, txt = _text_from_news(e)
            _add_doc(idx, source="news_feed", day=day, text=txt)
        _save_index(ip, idx)
    except Exception as e:
        log_swallowed_exception("engine/core/memory_rag.py:append_index", e)


def recall_archive_memories(query: str, *, archive_path: Path, limit: int = 3) -> list[dict[str, Any]]:
    """Return top-k relevant archived snippets using simple TF-IDF cosine scoring."""
    try:
        q_terms = _tokenize(str(query or ""))
        if not q_terms:
            return []
        ip = _index_path_for_archive(archive_path)
        idx = _load_index(ip)
        docs = idx.get("docs") if isinstance(idx.get("docs"), list) else []
        if docs:
            df = idx.get("df") if isinstance(idx.get("df"), dict) else {}
            n_docs = max(1, int(idx.get("doc_count", len(docs)) or len(docs)))
        else:
            # Fallback path when index does not exist yet / got corrupted.
            fb_docs = _load_archive_docs_for_fallback(archive_path)
            if not fb_docs:
                return []
            docs = []
            df: dict[str, int] = {}
            for d in fb_docs:
                terms = _tokenize(str(d.get("text", "") or ""))
                if not terms:
                    continue
                tf: dict[str, int] = {}
                for tok in terms[:128]:
                    tf[tok] = int(tf.get(tok, 0) or 0) + 1
                docs.append(
                    {
                        "id": _doc_id(str(d.get("source", "archive")), int(d.get("day", 1) or 1), str(d.get("text", "") or "")),
                        "source": str(d.get("source", "archive") or "archive"),
                        "day": int(d.get("day", 1) or 1),
                        "text": str(d.get("text", "") or "")[:360],
                        "tf": tf,
                        "len": int(sum(tf.values()) or 1),
                    }
                )
                for tok in tf.keys():
                    df[tok] = int(df.get(tok, 0) or 0) + 1
            if not docs:
                return []
            n_docs = len(docs)

        q_tf: dict[str, int] = {}
        for t in q_terms[:128]:
            q_tf[t] = int(q_tf.get(t, 0) or 0) + 1
        q_w: dict[str, float] = {}
        q_norm_sq = 0.0
        for t, c in q_tf.items():
            idf = math.log((1.0 + n_docs) / (1.0 + float(int(df.get(t, 0) or 0)))) + 1.0
            w = float(c) * idf
            q_w[t] = w
            q_norm_sq += w * w
        q_norm = math.sqrt(q_norm_sq) if q_norm_sq > 0 else 0.0
        if q_norm <= 0:
            return []

        newest_day = 1
        for d in docs:
            if isinstance(d, dict):
                try:
                    newest_day = max(newest_day, int(d.get("day", 1) or 1))
                except Exception:
                    continue

        scored: list[tuple[float, dict[str, Any]]] = []
        for d in docs[-_MAX_DOCS:]:
            if not isinstance(d, dict):
                continue
            tf = d.get("tf")
            if not isinstance(tf, dict):
                continue
            dot = 0.0
            d_norm_sq = 0.0
            for tok, raw_c in tf.items():
                try:
                    c = float(raw_c)
                except Exception:
                    continue
                idf = math.log((1.0 + n_docs) / (1.0 + float(int(df.get(str(tok), 0) or 0)))) + 1.0
                dw = c * idf
                d_norm_sq += dw * dw
                qw = q_w.get(str(tok), 0.0)
                if qw:
                    dot += qw * dw
            if dot <= 0.0 or d_norm_sq <= 0.0:
                continue
            semantic = dot / (q_norm * math.sqrt(d_norm_sq))
            try:
                age_days = max(0, newest_day - int(d.get("day", newest_day) or newest_day))
            except Exception:
                age_days = 0
            recency = math.exp(-float(age_days) / _RECENCY_HALF_LIFE_DAYS)
            # Blend semantic relevance with recency so very old but exact matches can still rank.
            score = (0.85 * semantic) + (0.15 * recency)
            if score > 0:
                scored.append((score, d))
        scored.sort(key=lambda x: x[0], reverse=True)
        out: list[dict[str, Any]] = []
        for score, d in scored[: max(1, min(8, int(limit or 3)))]:
            out.append(
                {
                    "score": float(score),
                    "source": str(d.get("source", "") or ""),
                    "day": int(d.get("day", 1) or 1),
                    "text": str(d.get("text", "") or ""),
                }
            )
        return out
    except Exception as e:
        log_swallowed_exception("engine/core/memory_rag.py:recall", e)
        return []
