from __future__ import annotations

import json
from pathlib import Path
from typing import Any
import warnings

from engine.systems.campaign_arcs import is_ripple_tag_suppressed_for_followups
from engine.systems.quests import (
    create_black_market_delivery_quest,
    create_corp_infiltration_quest,
    create_trace_cleanup_quest,
)


def _norm(v: Any) -> str:
    return str(v or "").strip().lower()


def _pending_event_exists(state: dict[str, Any], event_type: str, *, npc: str = "", day: int = 0) -> bool:
    pending = state.get("pending_events", []) or []
    if not isinstance(pending, list):
        return False
    want_npc = str(npc or "").strip()
    for ev in pending[-80:]:
        if not isinstance(ev, dict):
            continue
        if bool(ev.get("triggered")):
            continue
        if str(ev.get("event_type", "") or "").strip() != event_type:
            continue
        if day > 0 and int(ev.get("due_day", 0) or 0) < day:
            continue
        payload = ev.get("payload") if isinstance(ev.get("payload"), dict) else {}
        if want_npc and str(payload.get("npc", "") or "").strip() != want_npc:
            continue
        return True
    return False


def _has_active_quest(state: dict[str, Any], *, kind: str, origin_location: str = "") -> bool:
    quests = state.get("quests", {}) or {}
    active = quests.get("active") if isinstance(quests, dict) else []
    if not isinstance(active, list):
        return False
    k = _norm(kind)
    ol = _norm(origin_location)
    for q in active[-80:]:
        if not isinstance(q, dict):
            continue
        if _norm(q.get("kind", "")) != k:
            continue
        if str(q.get("status", "active") or "active") not in ("active", "overdue"):
            continue
        if ol and _norm(q.get("origin_location", "")) != ol:
            continue
        return True
    return False


def _schedule_npc_offer_followup(state: dict[str, Any], *, npc: str, day: int, time_min: int) -> bool:
    if not npc:
        return False
    if _pending_event_exists(state, "npc_offer", npc=npc, day=day):
        return False
    npcs = state.get("npcs", {}) or {}
    row = npcs.get(npc) if isinstance(npcs, dict) else None
    role = "contact" if not isinstance(row, dict) else str(row.get("role", "contact") or "contact")
    loc = ""
    if isinstance(row, dict):
        loc = _norm(row.get("current_location", "") or row.get("home_location", ""))
    state.setdefault("pending_events", []).append(
        {
            "event_type": "npc_offer",
            "title": f"{npc} wants to reconnect",
            "due_day": int(day),
            "due_time": min(1439, int(time_min) + 5),
            "triggered": False,
            "payload": {
                "npc": npc,
                "role": role,
                "service": "contact_followup",
                "location": loc,
                "source": "ripple_followup",
            },
        }
    )
    state.setdefault("world_notes", []).append(f"[Ripple] Follow-up scheduled: {npc} may have something actionable for you.")
    return True


IMPLICIT_TAGS_BY_KIND: dict[str, set[str]] = {
    "npc_utility_contact": {"utility_contact", "contact_hook"},
    # police_pressure only; trace_pressure comes from impact.trace_delta > 0 (real investigation bump).
    "npc_report": {"police_pressure"},
    "corporate_lockdown": {"corporate_pressure"},
    "quest_offer": {"quest_hook", "black_market"},
}

DEFAULT_FOLLOWUP_RULES: list[dict[str, Any]] = [
    {"id": "contact_to_offer", "match_tags_any": {"utility_contact", "contact_hook"}, "actions": ("event_npc_offer_from_meta_npc",)},
    {"id": "police_trace_cleanup", "match_tags_any": {"police_pressure", "trace_pressure"}, "actions": ("quest_trace_cleanup",)},
    {"id": "corp_lockdown_infiltration", "match_tags_any": {"corporate_pressure"}, "actions": ("quest_corp_infiltration",)},
    {"id": "black_market_delivery_hook", "match_tags_any": {"black_market", "quest_hook"}, "actions": ("quest_bm_delivery",)},
]
_CACHED_RULES: list[dict[str, Any]] | None = None


def _pack_path() -> Path:
    return Path(__file__).resolve().parents[2] / "data" / "packs" / "core" / "ripple_followups.json"


def _normalize_rule(raw: dict[str, Any]) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None
    rid = str(raw.get("id", "") or "").strip() or "rule"
    acts = raw.get("actions")
    if not isinstance(acts, list):
        return None
    actions = tuple([str(a).strip() for a in acts if isinstance(a, str) and str(a).strip()])
    if not actions:
        return None
    rule: dict[str, Any] = {"id": rid, "actions": actions}
    for key in ("match_tags_any", "match_tags_all"):
        vals = raw.get(key)
        if isinstance(vals, list):
            vv = {_norm(x) for x in vals if isinstance(x, str) and _norm(x)}
            if vv:
                rule[key] = vv
    mk = raw.get("match_kind")
    if isinstance(mk, str) and _norm(mk):
        rule["match_kind"] = _norm(mk)
    has_matcher = bool(rule.get("match_tags_any") or rule.get("match_tags_all") or rule.get("match_kind"))
    if not has_matcher:
        return None
    return rule


def validate_followup_rules_doc(doc: Any) -> list[str]:
    """Light schema validator for ripple follow-up rule packs."""
    errs: list[str] = []
    rows = doc.get("followup_rules") if isinstance(doc, dict) else None
    if not isinstance(rows, list):
        return ["missing followup_rules list"]
    for i, row in enumerate(rows[:128]):
        if not isinstance(row, dict):
            errs.append(f"rule[{i}]: must be object")
            continue
        rid = str(row.get("id", "") or "").strip()
        if not rid:
            errs.append(f"rule[{i}]: missing id")
        acts = row.get("actions")
        if not isinstance(acts, list) or not any(isinstance(a, str) and str(a).strip() for a in acts):
            errs.append(f"rule[{i}] id={rid or '?'}: invalid actions")
        has_matcher = False
        t_any = row.get("match_tags_any")
        if isinstance(t_any, list) and any(isinstance(x, str) and _norm(x) for x in t_any):
            has_matcher = True
        t_all = row.get("match_tags_all")
        if isinstance(t_all, list) and any(isinstance(x, str) and _norm(x) for x in t_all):
            has_matcher = True
        mk = row.get("match_kind")
        if isinstance(mk, str) and _norm(mk):
            has_matcher = True
        if not has_matcher:
            errs.append(f"rule[{i}] id={rid or '?'}: needs matcher (match_tags_any/match_tags_all/match_kind)")
    return errs


def _load_followup_rules() -> list[dict[str, Any]]:
    global _CACHED_RULES
    if isinstance(_CACHED_RULES, list):
        return _CACHED_RULES
    p = _pack_path()
    try:
        if not p.exists():
            _CACHED_RULES = [dict(x) for x in DEFAULT_FOLLOWUP_RULES]
            return _CACHED_RULES
        doc = json.loads(p.read_text(encoding="utf-8"))
        rows = doc.get("followup_rules") if isinstance(doc, dict) else []
        for msg in validate_followup_rules_doc(doc):
            warnings.warn(f"ripple_followups pack warning: {msg}", RuntimeWarning, stacklevel=2)
        parsed: list[dict[str, Any]] = []
        if isinstance(rows, list):
            for i, r in enumerate(rows[:64]):
                nr = _normalize_rule(r)
                if isinstance(nr, dict):
                    parsed.append(nr)
                else:
                    warnings.warn(
                        f"ripple_followups pack warning: skipping invalid rule at index {i}",
                        RuntimeWarning,
                        stacklevel=2,
                    )
        if not parsed:
            parsed = [dict(x) for x in DEFAULT_FOLLOWUP_RULES]
        _CACHED_RULES = parsed
        return _CACHED_RULES
    except Exception:
        _CACHED_RULES = [dict(x) for x in DEFAULT_FOLLOWUP_RULES]
        return _CACHED_RULES


def _derive_ripple_tags(rp: dict[str, Any], *, origin_faction: str, trace_pressure: int) -> set[str]:
    tags: set[str] = set()
    src = rp.get("tags")
    if isinstance(src, list):
        for t in src[:24]:
            if isinstance(t, str):
                n = _norm(t)
                if n:
                    tags.add(n)
    kind = _norm(rp.get("kind", ""))
    tags.update(IMPLICIT_TAGS_BY_KIND.get(kind, set()))
    if origin_faction:
        tags.add(f"faction:{origin_faction}")
        if origin_faction == "black_market":
            tags.add("black_market")
        if origin_faction == "police":
            tags.add("police_pressure")
    if trace_pressure > 0:
        tags.add("trace_pressure")
    return tags


def _rule_matches(rule: dict[str, Any], *, tags: set[str]) -> bool:
    any_tags = rule.get("match_tags_any")
    if isinstance(any_tags, (set, tuple, list)) and any_tags:
        want = {_norm(x) for x in any_tags if isinstance(x, str)}
        if not (want & tags):
            return False
    all_tags = rule.get("match_tags_all")
    if isinstance(all_tags, (set, tuple, list)) and all_tags:
        want_all = {_norm(x) for x in all_tags if isinstance(x, str)}
        if not want_all.issubset(tags):
            return False
    mk = _norm(rule.get("match_kind", ""))
    if mk:
        kinds = {t[len("kind:") :] for t in tags if t.startswith("kind:")}
        if mk not in kinds:
            return False
    return True


def trigger_followups_from_surfaced_ripple(state: dict[str, Any], rp: dict[str, Any]) -> dict[str, Any]:
    """Deterministic ripple -> actionable follow-up bridge.

    Rules stay intentionally small:
    - utility contact ripple -> npc_offer event
    - police/trace pressure ripple -> trace_cleanup quest
    - corporate lockdown ripple -> corp_infiltration quest
    """
    if not isinstance(rp, dict):
        return {"scheduled": 0, "quests": 0, "events": 0}
    if rp.get("dropped_by_propagation"):
        return {"scheduled": 0, "quests": 0, "events": 0, "skipped": 1}
    if rp.get("followup_processed") is True:
        return {"scheduled": 0, "quests": 0, "events": 0, "skipped": 1}

    meta = state.get("meta", {}) or {}
    day = int(meta.get("day", 1) or 1)
    time_min = int(meta.get("time_min", 0) or 0)
    origin_location = _norm(rp.get("origin_location", "")) or _norm((state.get("player", {}) or {}).get("location", ""))
    origin_faction = _norm(rp.get("origin_faction", ""))
    impact = rp.get("impact") if isinstance(rp.get("impact"), dict) else {}
    meta_rp = rp.get("meta") if isinstance(rp.get("meta"), dict) else {}

    stats = {"scheduled": 0, "quests": 0, "events": 0}

    trace_pressure = 0
    if isinstance(impact, dict):
        try:
            trace_pressure = int(impact.get("trace_delta", 0) or 0)
        except Exception:
            trace_pressure = 0
    tags = _derive_ripple_tags(rp, origin_faction=origin_faction, trace_pressure=trace_pressure)
    tags.add("kind:" + _norm(rp.get("kind", "")))

    for tg in tags:
        if is_ripple_tag_suppressed_for_followups(state, str(tg), day=day):
            return {"scheduled": 0, "quests": 0, "events": 0, "skipped": 1, "suppressed": 1}

    for rule in _load_followup_rules():
        if not _rule_matches(rule, tags=tags):
            continue
        acts = rule.get("actions")
        if not isinstance(acts, (tuple, list)):
            continue
        for act in acts:
            if act == "event_npc_offer_from_meta_npc":
                npc = str(meta_rp.get("npc", "") or "").strip()
                if not npc and "black_market" in tags:
                    npc = "Broker_Shade"
                if _schedule_npc_offer_followup(state, npc=npc, day=day, time_min=time_min):
                    stats["scheduled"] += 1
                    stats["events"] += 1
            elif act == "quest_trace_cleanup":
                q = create_trace_cleanup_quest(
                    state,
                    origin_location=origin_location,
                    trace_snapshot=int(((state.get("trace", {}) or {}).get("trace_pct", 0) or 0)),
                )
                if isinstance(q, dict) and q.get("id"):
                    stats["scheduled"] += 1
                    stats["quests"] += 1
            elif act == "quest_corp_infiltration":
                q2 = create_corp_infiltration_quest(state, origin_location=origin_location)
                if isinstance(q2, dict) and q2.get("id"):
                    stats["scheduled"] += 1
                    stats["quests"] += 1
            elif act == "quest_bm_delivery":
                if _has_active_quest(state, kind="bm_delivery", origin_location=origin_location):
                    continue
                try:
                    bm_power = int(meta_rp.get("bm_power", 65) or 65)
                except Exception:
                    bm_power = 65
                try:
                    bm_stability = int(meta_rp.get("bm_stability", 35) or 35)
                except Exception:
                    bm_stability = 35
                q3 = create_black_market_delivery_quest(
                    state,
                    origin_location=origin_location,
                    bm_power=bm_power,
                    bm_stability=bm_stability,
                )
                if isinstance(q3, dict) and q3.get("id"):
                    stats["scheduled"] += 1
                    stats["quests"] += 1

    rp["followup_processed"] = True
    return stats
