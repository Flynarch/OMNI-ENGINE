from __future__ import annotations

import re
from typing import Any

MH_BLOCK = re.compile(r"<MEMORY_HASH>(.*?)</MEMORY_HASH>", re.DOTALL)
SECTION_TAGS = [
    "OMNI_MONITOR",
    "INTERNAL_LOGIC",
    "SENSORY_FEED",
    "EVENT_LOG",
    "INTERACTION_NODE",
    "MEMORY_HASH",
]


def extract_memory_hash_block(text: str) -> str:
    m = MH_BLOCK.search(text)
    return m.group(1).strip() if m else ""


def parse_memory_hash(text: str) -> dict[str, Any]:
    block = extract_memory_hash_block(text)
    out: dict[str, Any] = {}
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
    state.setdefault("memory_hash", {}).update(mh)
    state.setdefault("meta", {})["memory_hash_raw"] = mh.get("raw", "")
    # NPC label sync: "Name [Label]"
    npc_line = mh.get("npc_status", "")
    pairs = re.findall(r"([^,\[]+)\s*\[([A-Za-z]+)\]", npc_line)
    midpoint = {"Devoted": 95, "Friendly": 80, "Neutral": 60, "Cold": 40, "Hostile": 20, "Enemy": 5}
    for name, label in pairs:
        n = state.setdefault("npcs", {}).setdefault(name.strip(), {})
        n["disposition_label"] = label
        n["disposition_score"] = midpoint.get(label, n.get("disposition_score", 50))

    # New ripples from 🌊 section
    ripple_line = str(mh.get("active_ripples", "")).strip()
    if ripple_line and ripple_line != "-":
        cur_day = int(state.get("meta", {}).get("day", 1))
        origin_loc = str(state.get("player", {}).get("location", "") or "").strip().lower()
        for raw in [x.strip() for x in ripple_line.split("|") if x.strip()]:
            state.setdefault("active_ripples", []).append(
                {
                    "text": raw,
                    "triggered_day": cur_day,
                    "surface_day": cur_day + 1,
                    "surface_time": 8 * 60,
                    "surfaced": False,
                    # Default: local witness/rumor unless engine explicitly sets broader scope.
                    "propagation": "local_witness",
                    "visibility": "local",
                    "origin_location": origin_loc,
                    "witnesses": [],
                    "surface_attempts": 0,
                }
            )


def enforce_stop_sequence_output(text: str, stop_sequence_active: bool) -> str:
    if not stop_sequence_active:
        return text

    # Strip INTERACTION_NODE block if present.
    stripped = re.sub(r"<INTERACTION_NODE>.*?</INTERACTION_NODE>", "", text, flags=re.DOTALL)
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

