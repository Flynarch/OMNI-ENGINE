"""Data-driven action registry (intent → action_id + ctx_patch).

- Load / match: always available.
- Smartphone NL: `action_intent._registry_try_smartphone_nl` via ``other.nl_smartphone_w2`` + ``try_parse_smartphone_nl`` (first branch in ``parse_action_intent``).
- Economy stay NL: `action_intent._registry_try_accommodation_nl` via ``economy.nl_accommodation_stay`` + ``apply_accommodation_nl`` (after smartphone, before travel).
- Sleep NL: `action_intent._registry_try_sleep` (keyword match), then `_registry_try_sleep_hours_nl` for parsed hours / default 8h via ``sleep.nl_duration_hours`` + ``apply_sleep_duration_from_nl`` (after accommodation).
- Combat NL: `action_intent._registry_try_combat` then `_registry_try_combat_keyword_fallback` (keywords from ``combat.nl_ranged_attempt`` / ``combat.nl_melee``).
- Travel NL: `action_intent._registry_try_travel` then `_registry_try_travel_keyword_fallback` (keywords from ``travel.nl_generic``); heuristics in `_apply_travel_heuristics`.
- Skill domains: `action_intent._registry_try_skill_domain` then `_registry_try_skill_domain_keyword_fallback` (keywords from JSON).
- Prefixed match: `match_registry_action_prefixed` for `social.*`, `social.inquiry.*`, `instant.*`, etc. without competing with global priority order.
- Multi-hit: ``iter_registry_matches_by_prefix`` yields every matching action (e.g. several ``instant.nl_stop_*`` STOP flags in one input).
- Inquiry phrases: `inquiry_phrases_match` mirrors ``social.inquiry.*`` keywords (used by `_is_social_inquiry`).
- Optional per-action ``handler`` string; resolved via `action_registry_handlers.apply_registry_handler` (e.g. ``ensure_social_inquiry_shape`` for inquiry NL).
- Allowlist surface: ``allowed_registry_action_ids()`` (same ids as JSON; fed into FFCI intent snapshot).
- Validation: ``is_known_registry_action_id``, ``sanitize_registry_action_id_hint`` for optional LLM field ``registry_action_id_hint``.
- Telemetry: ``registry_hint_alignment`` (parser id vs LLM hint in ``main`` / ``meta``).
- Code-only ids: ``get_registry_action_by_id`` loads ``ctx_patch`` when matching needs Python when keywords cannot express the gate (e.g. ``social.nl_conflict`` AND people-words, ``social.nl_intimacy_private``, ``rest.nl_prefix_60m`` with empty ``keywords_any``). Negotiation synonym list: ``social.nl_negotiation.match.keywords_any`` in JSON. Frasa istirahat singkat: ``rest.nl_istirahat_short``.
- See docs/action-registry-plan.md for full roadmap.
"""

from __future__ import annotations

from engine.core.error_taxonomy import log_swallowed_exception
import json
from pathlib import Path
from collections.abc import Iterator
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
        hdl = a.get("handler")
        if hdl is not None:
            if not isinstance(hdl, str) or not str(hdl).strip():
                raise ValueError(f"actions[{aid}].handler must be non-empty string if set")


def _build_match_result(a: dict[str, Any], doc: dict[str, Any]) -> dict[str, Any]:
    aid = str(a.get("id", "") or "").strip()
    patch = a.get("ctx_patch") if isinstance(a.get("ctx_patch"), dict) else {}
    out: dict[str, Any] = {
        "id": aid,
        "ctx_patch": dict(patch),
        "registry_version": int(doc.get("registry_version", 1) or 1),
    }
    h = a.get("handler")
    if isinstance(h, str) and h.strip():
        out["handler"] = h.strip()
    return out


def inquiry_phrases_match(t: str) -> bool:
    """True if ``t`` (lowercased) hits any ``keywords_any`` on actions with id ``social.inquiry.*``."""
    tnorm = str(t or "").strip().lower()
    if not tnorm:
        return False
    doc = load_registry()
    for a in doc.get("actions", []) or []:
        if not isinstance(a, dict):
            continue
        aid = str(a.get("id", "") or "").strip()
        if not aid.startswith("social.inquiry."):
            continue
        m = a.get("match") if isinstance(a.get("match"), dict) else {}
        kwa = m.get("keywords_any") if isinstance(m.get("keywords_any"), list) else []
        for kw in kwa:
            ks = str(kw or "").strip().lower()
            if ks and ks in tnorm:
                return True
    return False


def get_registry_action_by_id(action_id: str) -> dict[str, Any] | None:
    """Return registry entry ``id`` as a match-shaped dict (ctx_patch/handler/version).

    Used when matching requires Python logic but ``ctx_patch`` stays data-defined.
    Entries with empty ``keywords_any`` never surface from ``match_registry_action``.
    """
    aid = str(action_id or "").strip()
    if not aid:
        return None
    doc = load_registry()
    for a in doc.get("actions", []) or []:
        if not isinstance(a, dict):
            continue
        if str(a.get("id", "") or "").strip() != aid:
            continue
        return _build_match_result(a, doc)
    return None


def list_action_ids() -> list[str]:
    doc = load_registry()
    out: list[str] = []
    for a in doc.get("actions", []) or []:
        if isinstance(a, dict) and str(a.get("id", "") or "").strip():
            out.append(str(a["id"]).strip())
    return sorted(out)


def allowed_registry_action_ids() -> list[str]:
    """Stable ``id`` values from the action registry (FFCI / intent prompt allowlist surface)."""
    return list_action_ids()


def is_known_registry_action_id(action_id: str) -> bool:
    """True if ``action_id`` matches a loaded registry ``id`` (small set — linear scan ok)."""
    aid = str(action_id or "").strip()
    return bool(aid) and aid in set(list_action_ids())


def sanitize_registry_action_id_hint(raw: Any) -> str | None:
    """Return stripped id only if it is a known registry ``id``; else None."""
    aid = str(raw or "").strip()
    if not aid:
        return None
    return aid if is_known_registry_action_id(aid) else None


def registry_hint_alignment(parser_registry_id: str, llm_hint: str | None) -> str:
    """Telemetry label comparing parser ``registry_action_id`` vs optional LLM hint."""
    p = str(parser_registry_id or "").strip()
    h = str(llm_hint or "").strip()
    if not p and not h:
        return "none"
    if p and not h:
        return "parser_only"
    if h and not p:
        return "llm_only"
    return "match" if p == h else "mismatch"


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
        except Exception as _omni_sw_191:
            log_swallowed_exception('engine/core/action_registry.py:191', _omni_sw_191)
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
        return _build_match_result(a, doc)
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
        except Exception as _omni_sw_226:
            log_swallowed_exception('engine/core/action_registry.py:226', _omni_sw_226)
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
        return _build_match_result(a, doc)
    return None


def iter_registry_matches_by_prefix(player_text: str, id_prefix: str) -> Iterator[dict[str, Any]]:
    """Yield every registry action whose ``id`` starts with ``id_prefix`` and whose keywords match (not only first)."""
    t = str(player_text or "").strip().lower()
    pre = str(id_prefix or "").strip()
    if not t or not pre:
        return
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
        except Exception as _omni_sw_261:
            log_swallowed_exception('engine/core/action_registry.py:261', _omni_sw_261)
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
        yield _build_match_result(a, doc)


def merge_ctx_defaults(base: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
    """Shallow merge patch into a copy of base (patch wins)."""
    out = dict(base)
    for k, v in patch.items():
        out[k] = v
    return out
