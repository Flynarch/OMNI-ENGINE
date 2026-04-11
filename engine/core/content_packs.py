from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
PACKS_DIR = ROOT / "data" / "packs"


class PackError(RuntimeError):
    pass


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        raise PackError(f"Invalid JSON: {path}") from e


def _require(cond: bool, msg: str) -> None:
    if not cond:
        raise PackError(msg)


def validate_pack(doc: Any, *, path_hint: str = "") -> dict[str, Any]:
    _require(isinstance(doc, dict), f"Pack must be a JSON object{': ' + path_hint if path_hint else ''}")
    pack_id = doc.get("pack_id")
    _require(isinstance(pack_id, str) and pack_id.strip(), f"pack_id must be a non-empty string{': ' + path_hint if path_hint else ''}")
    version = doc.get("version")
    _require(isinstance(version, int) and version >= 1, f"version must be int >= 1{': ' + path_hint if path_hint else ''}")
    psc = doc.get("pack_schema_version")
    if psc is not None:
        _require(
            isinstance(psc, int) and 1 <= psc <= 99,
            "pack_schema_version must be an integer from 1 to 99 when present",
        )
    _require(isinstance(doc.get("name"), str) and doc.get("name").strip(), "name must be a non-empty string")
    _require(isinstance(doc.get("description"), str), "description must be a string")

    items = doc.get("items", [])
    roles = doc.get("roles", [])
    services = doc.get("services", [])
    _require(isinstance(items, list), "items must be a list")
    _require(isinstance(roles, list), "roles must be a list")
    _require(isinstance(services, list), "services must be a list")

    # Validate services
    svc_ids: set[str] = set()
    for i, s in enumerate(services):
        _require(isinstance(s, dict), f"services[{i}] must be object")
        sid = s.get("id")
        _require(isinstance(sid, str) and sid.strip(), f"services[{i}].id must be non-empty string")
        _require(sid not in svc_ids, f"duplicate service id: {sid}")
        svc_ids.add(sid)
        _require(isinstance(s.get("name"), str) and str(s.get("name")).strip(), f"services[{i}].name must be non-empty string")
        _require(isinstance(s.get("domain"), str) and str(s.get("domain")).strip(), f"services[{i}].domain must be non-empty string")

    # Validate roles
    role_ids: set[str] = set()
    for i, r in enumerate(roles):
        _require(isinstance(r, dict), f"roles[{i}] must be object")
        rid = r.get("id")
        _require(isinstance(rid, str) and rid.strip(), f"roles[{i}].id must be non-empty string")
        _require(rid not in role_ids, f"duplicate role id: {rid}")
        role_ids.add(rid)
        _require(isinstance(r.get("name"), str) and str(r.get("name")).strip(), f"roles[{i}].name must be non-empty string")
        svcs = r.get("services", [])
        _require(isinstance(svcs, list), f"roles[{i}].services must be a list")
        for j, sid in enumerate(svcs):
            _require(isinstance(sid, str) and sid.strip(), f"roles[{i}].services[{j}] must be a string")
            _require(sid in svc_ids, f"roles[{i}] references unknown service id: {sid}")

    # Validate items
    item_ids: set[str] = set()
    for i, it in enumerate(items):
        _require(isinstance(it, dict), f"items[{i}] must be object")
        iid = it.get("id")
        _require(isinstance(iid, str) and iid.strip(), f"items[{i}].id must be non-empty string")
        _require(iid not in item_ids, f"duplicate item id: {iid}")
        item_ids.add(iid)
        _require(isinstance(it.get("name"), str) and str(it.get("name")).strip(), f"items[{i}].name must be non-empty string")
        size = it.get("size", 1)
        _require(isinstance(size, int) and 1 <= size <= 6, f"items[{i}].size must be int 1..6")
        tags = it.get("tags", [])
        _require(isinstance(tags, list) and all(isinstance(x, str) for x in tags), f"items[{i}].tags must be list[str]")
        bp = it.get("base_price", 0)
        _require(isinstance(bp, int) and bp >= 0, f"items[{i}].base_price must be int >= 0")
        rarity = it.get("rarity", "common")
        _require(isinstance(rarity, str), f"items[{i}].rarity must be string")

    return {
        "pack_id": pack_id,
        "version": version,
        "name": doc.get("name"),
        "description": doc.get("description"),
        "items": items,
        "roles": roles,
        "services": services,
    }


def load_pack(pack_id: str) -> dict[str, Any]:
    pid = str(pack_id or "").strip().lower()
    _require(pid != "", "pack_id required")
    path = PACKS_DIR / pid / "pack.json"
    _require(path.exists(), f"Pack not found: {pid} (expected {path})")
    doc = _read_json(path)
    return validate_pack(doc, path_hint=str(path))


def _load_pack_extras(pack_id: str) -> dict[str, Any]:
    """Load optional extra data files for a pack folder (determinism: frozen in meta)."""
    pid = str(pack_id or "").strip().lower()
    base = PACKS_DIR / pid
    out: dict[str, Any] = {}

    occ_path = base / "occupations.json"
    if occ_path.exists():
        doc = _read_json(occ_path)
        if not isinstance(doc, dict):
            raise PackError(f"occupations.json must be object: {occ_path}")
        if not isinstance(doc.get("templates", []), list):
            raise PackError(f"occupations.json templates must be list: {occ_path}")
        cps = doc.get("career_paths", None)
        if cps is not None:
            if not isinstance(cps, list):
                raise PackError(f"occupations.json career_paths must be list: {occ_path}")
            for i, p in enumerate(cps):
                _require(isinstance(p, dict), f"occupations.json career_paths[{i}] must be object: {occ_path}")
                pid = p.get("id")
                _require(isinstance(pid, str) and pid.strip(), f"occupations.json career_paths[{i}].id required: {occ_path}")
                lv = p.get("levels", [])
                _require(isinstance(lv, list) and lv, f"occupations.json career_paths[{i}].levels must be non-empty list: {occ_path}")
        out["occupations"] = doc
    return out


def _strict_extras_enabled(state: dict[str, Any], strict_extras: bool | None) -> bool:
    if isinstance(strict_extras, bool):
        return strict_extras
    meta = state.get("meta", {}) or {}
    flags = meta.get("flags", {}) if isinstance(meta, dict) else {}
    if isinstance(flags, dict) and bool(flags.get("strict_pack_extras", False)):
        return True
    env = str(os.environ.get("OMNI_STRICT_PACK_EXTRAS", "") or "").strip().lower()
    if env in ("1", "true", "yes", "on"):
        return True
    env2 = str(os.environ.get("STRICT_PACK_VALIDATION", "") or "").strip().lower()
    return env2 in ("1", "true", "yes", "on")


def freeze_packs_into_state(
    state: dict[str, Any],
    *,
    pack_ids: list[str] | None = None,
    strict_extras: bool | None = None,
) -> dict[str, Any]:
    """Load packs and freeze snapshot into `state.meta.content_packs`.

    Determinism: once frozen, saves keep the same pack snapshot, independent of filesystem changes.
    """
    meta = state.setdefault("meta", {})
    cur = meta.get("content_packs")
    if isinstance(cur, dict) and cur.get("packs"):
        return cur

    want = pack_ids or ["core"]
    strict_mode = _strict_extras_enabled(state, strict_extras)
    packs: list[dict[str, Any]] = []
    extras: dict[str, Any] = {}
    for pid in want[:8]:
        packs.append(load_pack(pid))
        try:
            extras[pid] = _load_pack_extras(pid)
        except PackError:
            if strict_mode:
                raise
            # Runtime-safe default: if extras are invalid/missing, keep game running.
            extras[pid] = {}

    snap = {"pack_ids": want, "packs": packs, "extras": extras}
    meta["content_packs"] = snap
    return snap


def apply_pack_effects(state: dict[str, Any]) -> None:
    """Apply pack-derived knobs into runtime state (non-destructive merges)."""
    meta = state.get("meta", {}) or {}
    cp = meta.get("content_packs") or {}
    if not isinstance(cp, dict):
        return
    packs = cp.get("packs") or []
    if not isinstance(packs, list):
        return
    extras = cp.get("extras") or {}
    if not isinstance(extras, dict):
        extras = {}

    inv = state.setdefault("inventory", {})
    sizes = inv.setdefault("item_sizes", {})
    if not isinstance(sizes, dict):
        sizes = {}
        inv["item_sizes"] = sizes

    # Merge sizes (pack wins only if key not already set).
    for pack in packs:
        if not isinstance(pack, dict):
            continue
        for it in pack.get("items", []) or []:
            if not isinstance(it, dict):
                continue
            iid = str(it.get("id", "") or "").strip()
            if not iid:
                continue
            if iid not in sizes:
                try:
                    sizes[iid] = int(it.get("size", 1) or 1)
                except Exception:
                    sizes[iid] = 1

    # Store a compact index for future use (market/services).
    world = state.setdefault("world", {})
    world.setdefault("content_index", {})
    idx = world.get("content_index")
    if not isinstance(idx, dict):
        idx = {}
        world["content_index"] = idx

    items_idx: dict[str, dict[str, Any]] = {}
    roles_idx: dict[str, dict[str, Any]] = {}
    services_idx: dict[str, dict[str, Any]] = {}
    for pack in packs:
        if not isinstance(pack, dict):
            continue
        for it in pack.get("items", []) or []:
            if isinstance(it, dict) and isinstance(it.get("id"), str):
                items_idx[str(it["id"])] = dict(it)
        for r in pack.get("roles", []) or []:
            if isinstance(r, dict) and isinstance(r.get("id"), str):
                roles_idx[str(r["id"])] = dict(r)
        for s in pack.get("services", []) or []:
            if isinstance(s, dict) and isinstance(s.get("id"), str):
                services_idx[str(s["id"])] = dict(s)
    idx["items"] = items_idx
    idx["roles"] = roles_idx
    idx["services"] = services_idx
    # Expose occupations templates (if present).
    occ = {}
    for pid, ex in extras.items():
        if isinstance(ex, dict) and isinstance(ex.get("occupations"), dict):
            occ[str(pid)] = ex.get("occupations")
    if occ:
        idx["occupations"] = occ

