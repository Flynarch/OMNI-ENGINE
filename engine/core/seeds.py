from __future__ import annotations

from engine.core.error_taxonomy import log_swallowed_exception
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
SEEDS_DIR = ROOT / "data" / "seeds"

# Kunci yang boleh di-merge dari seed (tidak menimpa player/bio/economy dari boot).
_MERGEABLE_TOP = frozenset(
    {"npcs", "pending_events", "active_ripples", "world_notes", "reputation", "skills", "trace", "world"}
)
_LIST_EXTEND = frozenset({"pending_events", "active_ripples", "world_notes"})


def list_seed_names() -> list[str]:
    if not SEEDS_DIR.is_dir():
        return []
    return sorted(p.stem for p in SEEDS_DIR.glob("*.json"))


def _deep_merge_dict(dst: dict[str, Any], src: dict[str, Any]) -> None:
    for k, v in src.items():
        if isinstance(v, dict) and isinstance(dst.get(k), dict):
            _deep_merge_dict(dst[k], v)  # type: ignore[arg-type]
        else:
            dst[k] = v


def apply_seed_pack(state: dict[str, Any], pack_name: str | None) -> bool:
    """
    Merge isi data/seeds/<pack_name>.json ke state (setelah boot economy).
    Mengembalikan False jika file tidak ada atau nama diabaikan.
    """
    if not pack_name or str(pack_name).strip().lower() in ("none", "-", "no", ""):
        return False
    name = str(pack_name).strip()
    path = SEEDS_DIR / f"{name}.json"
    if not path.is_file():
        return False
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception as _omni_sw_44:
        log_swallowed_exception('engine/core/seeds.py:44', _omni_sw_44)
        return False
    if not isinstance(raw, dict):
        return False

    for key in _MERGEABLE_TOP:
        if key not in raw:
            continue
        chunk = raw[key]
        if key in _LIST_EXTEND:
            if not isinstance(chunk, list):
                continue
            state.setdefault(key, [])
            if isinstance(state[key], list):
                state[key].extend(chunk)
            continue
        if key == "world" and isinstance(chunk, dict):
            # Allow seed packs to seed scene/world objects (e.g., nearby items).
            state.setdefault("world", {})
            if isinstance(state["world"], dict):
                _deep_merge_dict(state["world"], chunk)  # type: ignore[arg-type]
            continue
        if key == "npcs" and isinstance(chunk, dict):
            npcs = state.setdefault("npcs", {})
            for nid, npc in chunk.items():
                if not isinstance(npc, dict):
                    continue
                slot = npcs.setdefault(str(nid), {})
                if isinstance(slot, dict):
                    _deep_merge_dict(slot, npc)
                else:
                    npcs[str(nid)] = dict(npc)
            continue
        if key == "reputation" and isinstance(chunk, dict):
            state.setdefault("reputation", {}).update(chunk)
            continue
        if key == "skills" and isinstance(chunk, dict):
            skills = state.setdefault("skills", {})
            for sk, sv in chunk.items():
                if isinstance(sv, dict):
                    skills.setdefault(sk, {}).update(sv)
                else:
                    skills[sk] = sv
            continue
        if key == "trace" and isinstance(chunk, dict):
            state.setdefault("trace", {}).update(chunk)
            continue

    state.setdefault("meta", {})["seed_pack"] = name
    return True
