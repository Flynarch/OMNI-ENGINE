from __future__ import annotations

from engine.core.error_taxonomy import log_swallowed_exception
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
LOC_DIR = ROOT / "data" / "locations"


class LocationPresetError(RuntimeError):
    pass


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        log_swallowed_exception('engine/world/location_presets.py:19', e)
        raise LocationPresetError(f"Invalid JSON: {path}") from e


def _require(cond: bool, msg: str) -> None:
    if not cond:
        raise LocationPresetError(msg)


def load_location_preset(loc_key: str) -> dict[str, Any] | None:
    """Load a location preset JSON if it exists; return None if not found."""
    lk = str(loc_key or "").strip().lower()
    if not lk:
        return None
    path = LOC_DIR / f"{lk}.json"
    if not path.exists():
        return None
    doc = _read_json(path)
    _require(isinstance(doc, dict), f"Location preset must be an object: {path}")
    # Allowed keys (strict enough to avoid wild state injection).
    allowed = {"notes", "nearby_items", "npcs", "tags", "city_stats"}
    for k in doc.keys():
        _require(k in allowed, f"Unknown key '{k}' in {path} (allowed: {sorted(list(allowed))})")

    out: dict[str, Any] = {"loc_key": lk}
    tags = doc.get("tags", [])
    _require(isinstance(tags, list) and all(isinstance(x, str) for x in tags), f"{path}: tags must be list[str]")
    # Keep tags compact and safe.
    cleaned_tags: list[str] = []
    for t in tags[:20]:
        s = str(t or "").strip().lower()
        if not s:
            continue
        if s not in cleaned_tags:
            cleaned_tags.append(s)
    out["tags"] = cleaned_tags[:12]
    notes = doc.get("notes", [])
    _require(isinstance(notes, list) and all(isinstance(x, str) for x in notes), f"{path}: notes must be list[str]")
    out["notes"] = notes[:10]

    nearby = doc.get("nearby_items", [])
    _require(isinstance(nearby, list), f"{path}: nearby_items must be a list")
    # nearby items support dict with id/name or string ids.
    cleaned: list[Any] = []
    for it in nearby[:40]:
        if isinstance(it, str):
            s = it.strip()
            if s:
                cleaned.append({"id": s, "name": s})
        elif isinstance(it, dict):
            iid = str(it.get("id", it.get("item_id", it.get("name", ""))) or "").strip()
            if iid:
                cleaned.append({"id": iid, "name": str(it.get("name", iid) or iid)})
    out["nearby_items"] = cleaned

    npcs = doc.get("npcs", {})
    _require(isinstance(npcs, dict), f"{path}: npcs must be an object (dict)")
    cleaned_npcs: dict[str, Any] = {}
    for name, n in list(npcs.items())[:60]:
        if not isinstance(name, str) or not isinstance(n, dict):
            continue
        nm = name.strip()
        if not nm:
            continue
        # Minimal safe subset: role/affiliation/is_contact + disposition
        entry: dict[str, Any] = {"name": nm}
        if "role" in n:
            entry["role"] = str(n.get("role", "") or "")
        if "affiliation" in n:
            entry["affiliation"] = str(n.get("affiliation", "") or "")
        if "is_contact" in n:
            entry["is_contact"] = bool(n.get("is_contact"))
        try:
            entry["disposition_score"] = int(n.get("disposition_score", 50) or 50)
        except Exception as _omni_sw_93:
            log_swallowed_exception('engine/world/location_presets.py:93', _omni_sw_93)
            entry["disposition_score"] = 50
        if "disposition_label" in n:
            entry["disposition_label"] = str(n.get("disposition_label", "Neutral") or "Neutral")
        cleaned_npcs[nm] = entry
    out["npcs"] = cleaned_npcs
    city_stats = doc.get("city_stats", {})
    _require(isinstance(city_stats, dict), f"{path}: city_stats must be an object (dict)")
    cleaned_stats: dict[str, float] = {}
    for k, v in city_stats.items():
        if not isinstance(k, str):
            continue
        kk = str(k).strip()
        if not kk:
            continue
        if isinstance(v, (int, float)):
            cleaned_stats[kk] = float(v)
    out["city_stats"] = cleaned_stats
    return out


def apply_location_preset_if_first_visit(state: dict[str, Any], loc_key: str) -> bool:
    """Apply preset once per location. Returns True if applied."""
    lk = str(loc_key or "").strip().lower()
    if not lk:
        return False
    world = state.setdefault("world", {})
    locs = world.setdefault("locations", {})
    if not isinstance(locs, dict):
        locs = {}
        world["locations"] = locs
    locs.setdefault(lk, {})
    slot = locs.get(lk)
    if not isinstance(slot, dict):
        slot = {}
        locs[lk] = slot

    if bool(slot.get("preset_applied", False)):
        return False

    preset = load_location_preset(lk)
    slot["preset_applied"] = True  # mark even if no preset file, to avoid repeated filesystem checks
    if preset is None:
        locs[lk] = slot
        world["locations"] = locs
        return False

    # Apply preset into the location slot (does not overwrite if slot already has persistence).
    if "tags" not in slot:
        slot["tags"] = list(preset.get("tags") or [])
    if "nearby_items" not in slot:
        slot["nearby_items"] = list(preset.get("nearby_items") or [])
    if "npcs" not in slot:
        slot["npcs"] = dict(preset.get("npcs") or {})
    if "city_stats" not in slot:
        slot["city_stats"] = dict(preset.get("city_stats") or {})
    notes = preset.get("notes") or []
    if isinstance(notes, list) and notes:
        state.setdefault("world_notes", []).extend([f"[LocationPreset:{lk}] {x}" for x in notes[:6]])
    tg = preset.get("tags") or []
    if isinstance(tg, list) and tg:
        state.setdefault("world_notes", []).append(f"[LocationTags:{lk}] " + ", ".join([str(x) for x in tg[:10]]))

    locs[lk] = slot
    world["locations"] = locs
    return True

