from __future__ import annotations

import json
import re
from typing import Any

from engine.core.errors import record_error

MH_BLOCK = re.compile(r"<MEMORY_HASH>(.*?)</MEMORY_HASH>", re.DOTALL)
SECTION_TAGS = [
    "OMNI_MONITOR",
    "INTERNAL_LOGIC",
    "SENSORY_FEED",
    "EVENT_LOG",
    "INTERACTION_NODE",
    "MEMORY_HASH",
]

# Shown only to the LLM / parser; never echo raw blocks to the player console.
_PLAYER_HIDDEN_XML_SECTIONS: tuple[str, ...] = (
    "INTERNAL_LOGIC",
    "INTERACTION_NODE",
    "EVENT_LOG",
    "MEMORY_HASH",
)


def filter_narration_for_player_display(text: str) -> str:
    """Remove internal XML sections and OMNI_MONITOR wrappers for terminal output.

    Callers must keep the **full** model response for ``parse_memory_hash`` and audits;
    this function is **display-only** (Rich console).
    """
    if not text or not str(text).strip():
        return ""
    t = str(text)
    # Opening tags may include attributes (`<INTERNAL_LOGIC tone="cold">`); be strict on tag name only.
    _open = lambda tag: rf"<{tag}(?:\s[^>]*)?>"
    for tag in _PLAYER_HIDDEN_XML_SECTIONS:
        t = re.sub(rf"{_open(tag)}.*?</{tag}\s*>", "", t, flags=re.DOTALL | re.IGNORECASE)
    # Unclosed / truncated stream: drop from opening tag to end of string.
    for tag in _PLAYER_HIDDEN_XML_SECTIONS:
        t = re.sub(rf"{_open(tag)}.*", "", t, flags=re.DOTALL | re.IGNORECASE)
    # Orphan closers / stray delimiters (model sometimes breaks pairs)
    for tag in _PLAYER_HIDDEN_XML_SECTIONS:
        t = re.sub(rf"</{tag}\s*>", "", t, flags=re.IGNORECASE)
        t = re.sub(_open(tag), "", t, flags=re.IGNORECASE)
    # Visible "main" narration: prose from OMNI_MONITOR without XML delimiters.
    t = re.sub(r"</?OMNI_MONITOR(?:\s[^>]*)?>", "", t, flags=re.IGNORECASE)
    t = re.sub(r"</?SENSORY_FEED(?:\s[^>]*)?>", "", t, flags=re.IGNORECASE)
    t = re.sub(r"\n{3,}", "\n\n", t.strip())
    return t


def extract_memory_hash_block(text: str) -> str:
    m = MH_BLOCK.search(text)
    return m.group(1).strip() if m else ""


def parse_memory_hash(text: str) -> dict[str, Any]:
    block = extract_memory_hash_block(text)
    out: dict[str, Any] = {}
    # v2: allow a JSON object inside the MEMORY_HASH block (in addition to emoji lines).
    # Backward compatible: if JSON parse fails, we still parse emoji lines.
    v2_obj: dict[str, Any] | None = None
    try:
        s = block.strip()
        if s.startswith("{") and s.endswith("}"):
            obj = json.loads(s)
            if isinstance(obj, dict):
                v2_obj = obj
        else:
            a = s.find("{")
            b = s.rfind("}")
            if a != -1 and b != -1 and b > a:
                obj = json.loads(s[a : b + 1])
                if isinstance(obj, dict):
                    v2_obj = obj
    except Exception:
        v2_obj = None
    mapping = {
        "🎯": "active_objective",
        "📜": "committed_actions",
        "🤝": "npc_status",
        "🏷": "aliases",
        "📍": "item_locations",
        "🩺": "persistent_injuries",
        "🩻": "permanent_damage_log",
        "⏰": "pending_events",
        "💬": "npc_debts_grudges",
        "🌊": "active_ripples",
        "⚡": "mastery_streak",
        "📊": "trauma_debuff",
        "🎓": "skill_decay",
        "📚": "resolved_ripples",
    }
    for line in block.splitlines():
        s = line.strip()
        for emo, key in mapping.items():
            if s.startswith(emo):
                out[key] = s[len(emo) :].strip(" :")
    if isinstance(v2_obj, dict) and v2_obj:
        out["v2"] = v2_obj
    out["raw"] = block
    return out


def validate_ai_sections(text: str) -> list[str]:
    missing: list[str] = []
    for tag in SECTION_TAGS:
        if f"<{tag}>" not in text or f"</{tag}>" not in text:
            missing.append(tag)
    return missing


def validate_tag_balance(text: str) -> list[str]:
    """Tag pembuka/penutup harus sama jumlahnya (cegah blok terpotong stream)."""
    issues: list[str] = []
    for tag in SECTION_TAGS:
        o = text.count(f"<{tag}>")
        c = text.count(f"</{tag}>")
        if o != c:
            issues.append(f"{tag} open={o} close={c}")
    return issues


def validate_memory_hash_delimiters(text: str) -> list[str]:
    issues: list[str] = []
    has_o = "<MEMORY_HASH>" in text
    has_c = "</MEMORY_HASH>" in text
    if has_o and not has_c:
        issues.append("MEMORY_HASH unclosed")
    if has_c and not has_o:
        issues.append("MEMORY_HASH orphan_close")
    return issues


def validate_memory_hash_nonempty(text: str) -> list[str]:
    issues: list[str] = []
    block = extract_memory_hash_block(text)
    if "<MEMORY_HASH>" in text and "</MEMORY_HASH>" in text and not block.strip():
        issues.append("MEMORY_HASH empty")
    return issues


def apply_memory_hash_to_state(state: dict[str, Any], mh: dict[str, Any]) -> None:
    """Store AI continuity data WITHOUT mutating mechanical state.

    CRITICAL ARCHITECTURE: The LLM is a narrator. It must not directly mutate
    simulation-critical state like NPC disposition, memories, or world queues.
    """
    mh2 = dict(mh) if isinstance(mh, dict) else {"raw": str(mh)}
    state.setdefault("memory_hash", {}).update(mh2)
    try:
        state.setdefault("meta", {})["memory_hash_raw"] = mh2.get("raw", "")
    except Exception:
        state.setdefault("meta", {})["memory_hash_raw"] = ""
    # For auditability only; never drive mechanics directly.
    if any(k in mh2 for k in ("npc_status", "active_ripples", "v2")):
        state.setdefault("world_notes", []).append("[AI] memory_hash received (read-only; no state mutation applied).")


def _clamp_int(v: Any, lo: int, hi: int, default: int) -> int:
    try:
        n = int(v)
    except Exception:
        n = int(default)
    return max(int(lo), min(int(hi), int(n)))


def _clamp_float(v: Any, lo: float, hi: float, default: float) -> float:
    try:
        x = float(v)
    except Exception:
        x = float(default)
    return max(float(lo), min(float(hi), float(x)))


def _apply_npc_memory_deltas(state: dict[str, Any], deltas: list[Any]) -> None:
    npcs = state.get("npcs", {}) or {}
    if not isinstance(npcs, dict):
        return
    meta = state.get("meta", {}) or {}
    cur_day = _clamp_int(meta.get("day", 1), 1, 999999, 1)
    cur_time = _clamp_int(meta.get("time_min", 0), 0, 1439, 0)

    added_total = 0
    for row in deltas[:8]:
        if not isinstance(row, dict):
            continue
        npc_id = str(row.get("npc_id", "") or "").strip()
        if not npc_id:
            continue
        npc = npcs.get(npc_id)
        if not isinstance(npc, dict):
            try:
                record_error(state, "ai.memory_hash_v2", Exception(f"Unknown npc_id in npc_memory_deltas: {npc_id}"))
            except Exception:
                pass
            continue

        mems = npc.setdefault("memories", [])
        if not isinstance(mems, list):
            mems = []
            npc["memories"] = mems

        adds = row.get("memories_add", [])
        if not isinstance(adds, list):
            adds = []
        for m in adds[:5]:
            if added_total >= 6:
                break
            if not isinstance(m, dict):
                continue
            mid = str(m.get("memory_id", "") or "").strip()
            kind = str(m.get("kind", "") or "").strip().lower()
            summary = str(m.get("summary", "") or "").strip()
            if not (mid and kind and summary):
                continue

            when = m.get("when") if isinstance(m.get("when"), dict) else {}
            day = _clamp_int((when or {}).get("day", cur_day), 1, 999999, cur_day)
            tmin = _clamp_int((when or {}).get("time_min", cur_time), 0, 1439, cur_time)
            imp = _clamp_int(m.get("importance", 30), 0, 100, 30)
            val = _clamp_int(m.get("valence", 0), -100, 100, 0)
            conf = _clamp_float(m.get("confidence", 0.7), 0.0, 1.0, 0.7)
            tags = m.get("tags", [])
            if not isinstance(tags, list):
                tags = []
            tags2 = [str(x)[:24] for x in tags[:8] if isinstance(x, (str, int, float)) and str(x).strip()]

            rec = {
                "memory_id": mid[:40],
                "kind": kind[:32],
                "summary": summary[:180],
                "when": {"day": int(day), "time_min": int(tmin)},
                "importance": int(imp),
                "valence": int(val),
                "confidence": float(conf),
                "tags": tags2,
            }
            mems.append(rec)
            added_total += 1

        # Optional updates: small subset
        ups = row.get("memories_update", [])
        if isinstance(ups, list) and ups:
            for u in ups[:6]:
                if not isinstance(u, dict):
                    continue
                mid = str(u.get("memory_id", "") or "").strip()
                if not mid:
                    continue
                setv = u.get("set") if isinstance(u.get("set"), dict) else {}
                if not setv:
                    continue
                for rec in mems[-60:]:
                    if isinstance(rec, dict) and str(rec.get("memory_id", "") or "") == mid:
                        if "importance" in setv:
                            rec["importance"] = _clamp_int(setv.get("importance"), 0, 100, int(rec.get("importance", 30) or 30))
                        if "valence" in setv:
                            rec["valence"] = _clamp_int(setv.get("valence"), -100, 100, int(rec.get("valence", 0) or 0))
                        break

        # Bound list size (keep most important + most recent)
        try:
            def _key(x: dict[str, Any]) -> tuple[int, int, int]:
                w = x.get("when") if isinstance(x.get("when"), dict) else {}
                d = _clamp_int(w.get("day", 1), 1, 999999, 1)
                tm = _clamp_int(w.get("time_min", 0), 0, 1439, 0)
                imp = _clamp_int(x.get("importance", 0), 0, 100, 0)
                return (imp, d, tm)

            mems2 = [x for x in mems if isinstance(x, dict) and x.get("memory_id")]
            mems2.sort(key=_key, reverse=True)
            npc["memories"] = mems2[:50]
        except Exception:
            npc["memories"] = mems[-50:]


def enforce_stop_sequence_output(text: str, stop_sequence_active: bool) -> str:
    if not stop_sequence_active:
        return text

    # Strip INTERACTION_NODE block if present (allow attributes on opening tag).
    stripped = re.sub(
        r"<INTERACTION_NODE(?:\s[^>]*)?>.*?</INTERACTION_NODE\s*>",
        "",
        text,
        flags=re.DOTALL | re.IGNORECASE,
    )
    stripped = stripped.rstrip()
    if not stripped.endswith("Apa rencanamu?"):
        stripped += "\nApa rencanamu?"
    return stripped


def record_ai_parse_health(state: dict[str, Any], text: str) -> None:
    missing = validate_ai_sections(text)
    balance = validate_tag_balance(text)
    mh_delim = validate_memory_hash_delimiters(text)
    mh_empty = validate_memory_hash_nonempty(text)
    meta = state.setdefault("meta", {})
    meta["last_ai_missing_sections"] = missing
    meta["last_ai_tag_balance_errors"] = balance
    meta["last_ai_memory_hash_issues"] = mh_delim + mh_empty
    combined = missing + balance + mh_delim + mh_empty
    if combined:
        note = "AI parse: " + ", ".join(combined[:12])
        if len(combined) > 12:
            note += f" … (+{len(combined) - 12})"
        state.setdefault("world_notes", []).append(note)

