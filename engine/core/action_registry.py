"""Data-driven action registry (intent → action_id + ctx_patch).

- Load / match: always available.
- Sleep NL: `action_intent._registry_try_sleep` (after accommodation).
- Combat NL: `action_intent._registry_try_combat` (before legacy combat_terms).
- Travel NL: `action_intent._registry_try_travel` (before `_TRAVEL_LEGACY_KEYWORDS`); heuristics in `_apply_travel_heuristics`.
- Skill domains: `action_intent._registry_try_skill_domain` for `hacking.*`, `medical.*`, `driving.*`, `stealth.*` (before legacy domain elifs).
- Prefixed match: `match_registry_action_prefixed` for `social.*`, `social.inquiry.*`, `instant.*`, etc. without competing with global priority order.
- See docs/action-registry-plan.md for full roadmap.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
REGISTRY_PATH = ROOT / "data" / "action_registry" / "registry_v1.json"

_cached: dict[str, Any] | None = None


def _read_registry_file() -> dict[str, Any]:
    if not REGISTRY_PATH.exists():
        return {"registry_version": 0, "actions": []}
    return json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))


def load_registry(*, force: bool = False) -> dict[str, Any]:
    global _cached
    if _cached is not None and not force:
        return _cached
    doc = _read_registry_file()
    _validate_registry_doc(doc)
    _cached = doc
    return doc


def _validate_registry_doc(doc: Any) -> None:
    if not isinstance(doc, dict):
        raise ValueError("registry root must be object")
    if "actions" not in doc:
        raise ValueError("registry.actions required")
    acts = doc["actions"]
    if not isinstance(acts, list):
        raise ValueError("registry.actions must be list")
    seen: set[str] = set()
    for i, a in enumerate(acts):
        if not isinstance(a, dict):
            raise ValueError(f"actions[{i}] must be object")
        aid = str(a.get("id", "") or "").strip()
        if not aid:
            raise ValueError(f"actions[{i}].id required")
        if aid in seen:
            raise ValueError(f"duplicate action id: {aid}")
        seen.add(aid)
        m = a.get("match")
        if not isinstance(m, dict):
            raise ValueError(f"actions[{aid}].match must be object")
        kwa = m.get("keywords_any")
        if kwa is not None:
            if not isinstance(kwa, list) or not all(isinstance(x, str) for x in kwa):
                raise ValueError(f"actions[{aid}].match.keywords_any must be list[str]")
        patch = a.get("ctx_patch")
        if patch is not None and not isinstance(patch, dict):
            raise ValueError(f"actions[{aid}].ctx_patch must be object")


def list_action_ids() -> list[str]:
    doc = load_registry()
    out: list[str] = []
    for a in doc.get("actions", []) or []:
        if isinstance(a, dict) and str(a.get("id", "") or "").strip():
            out.append(str(a["id"]).strip())
    return sorted(out)


def match_registry_action(player_text: str) -> dict[str, Any] | None:
    """First matching action wins (ordered by priority ascending, then file order)."""
    t = str(player_text or "").strip().lower()
    if not t:
        return None
    doc = load_registry()
    rows: list[tuple[int, int, dict[str, Any]]] = []
    for idx, a in enumerate(doc.get("actions", []) or []):
        if not isinstance(a, dict):
            continue
        try:
            pri = int(a.get("priority", 100))
        except Exception:
            pri = 100
        rows.append((pri, idx, a))
    rows.sort(key=lambda x: (x[0], x[1]))
    for _pri, _idx, a in rows:
        m = a.get("match") if isinstance(a.get("match"), dict) else {}
        kwa = m.get("keywords_any") if isinstance(m.get("keywords_any"), list) else []
        hit = False
        for kw in kwa:
            ks = str(kw or "").strip().lower()
            if ks and ks in t:
                hit = True
                break
        if not hit:
            continue
        aid = str(a.get("id", "") or "").strip()
        patch = a.get("ctx_patch") if isinstance(a.get("ctx_patch"), dict) else {}
        return {"id": aid, "ctx_patch": dict(patch), "registry_version": int(doc.get("registry_version", 1) or 1)}
    return None


def match_registry_action_prefixed(player_text: str, id_prefix: str) -> dict[str, Any] | None:
    """Like ``match_registry_action`` but only actions whose ``id`` startswith ``id_prefix``."""
    t = str(player_text or "").strip().lower()
    pre = str(id_prefix or "").strip()
    if not t or not pre:
        return None
    doc = load_registry()
    rows: list[tuple[int, int, dict[str, Any]]] = []
    for idx, a in enumerate(doc.get("actions", []) or []):
        if not isinstance(a, dict):
            continue
        aid = str(a.get("id", "") or "").strip()
        if not aid.startswith(pre):
            continue
        try:
            pri = int(a.get("priority", 100))
        except Exception:
            pri = 100
        rows.append((pri, idx, a))
    rows.sort(key=lambda x: (x[0], x[1]))
    for _pri, _idx, a in rows:
        m = a.get("match") if isinstance(a.get("match"), dict) else {}
        kwa = m.get("keywords_any") if isinstance(m.get("keywords_any"), list) else []
        hit = False
        for kw in kwa:
            ks = str(kw or "").strip().lower()
            if ks and ks in t:
                hit = True
                break
        if not hit:
            continue
        aid = str(a.get("id", "") or "").strip()
        patch = a.get("ctx_patch") if isinstance(a.get("ctx_patch"), dict) else {}
        return {"id": aid, "ctx_patch": dict(patch), "registry_version": int(doc.get("registry_version", 1) or 1)}
    return None


def merge_ctx_defaults(base: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
    """Shallow merge patch into a copy of base (patch wins)."""
    out = dict(base)
    for k, v in patch.items():
        out[k] = v
    return out
