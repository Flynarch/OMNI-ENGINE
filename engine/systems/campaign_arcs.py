from __future__ import annotations

import json
from pathlib import Path
from typing import Any
import warnings

from engine.core.error_taxonomy import log_swallowed_exception
from engine.social.reputation_lanes import lane_score
from engine.social.ripple_queue import enqueue_ripple
from engine.systems.quests import (
    create_black_market_delivery_quest,
    create_corp_infiltration_quest,
    create_trace_cleanup_quest,
)


ARC_ID = "city_operator_arc"
_CACHED_PACK: dict[str, Any] | None = None


def _norm(v: Any) -> str:
    return str(v or "").strip().lower()


def _ensure_arc_state(state: dict[str, Any]) -> dict[str, Any]:
    world = state.setdefault("world", {})
    arcs = world.setdefault(
        "arc_campaign",
        {
            "enabled": True,
            "active_arc": ARC_ID,
            "last_eval_day": 0,
            "milestones": {},
            "ending_state": "",
            "history": [],
        },
    )
    if not isinstance(arcs, dict):
        arcs = {
            "enabled": True,
            "active_arc": ARC_ID,
            "last_eval_day": 0,
            "milestones": {},
            "ending_state": "",
            "history": [],
        }
        world["arc_campaign"] = arcs
    arcs.setdefault("enabled", True)
    arcs.setdefault("active_arc", ARC_ID)
    arcs.setdefault("last_eval_day", 0)
    if not isinstance(arcs.get("milestones"), dict):
        arcs["milestones"] = {}
    if not isinstance(arcs.get("history"), list):
        arcs["history"] = []
    arcs.setdefault("ending_state", "")
    if not isinstance(arcs.get("ripple_tag_suppress"), dict):
        arcs["ripple_tag_suppress"] = {}
    return arcs


def _pack_path() -> Path:
    return Path(__file__).resolve().parents[2] / "data" / "packs" / "core" / "campaign_arcs.json"


def _load_pack() -> dict[str, Any]:
    global _CACHED_PACK
    if isinstance(_CACHED_PACK, dict):
        return _CACHED_PACK
    p = _pack_path()
    try:
        if not p.exists():
            _CACHED_PACK = {}
            return _CACHED_PACK
        doc = json.loads(p.read_text(encoding="utf-8"))
        _CACHED_PACK = doc if isinstance(doc, dict) else {}
        return _CACHED_PACK
    except Exception as e:
        warnings.warn(f"campaign_arcs pack warning: failed to load ({e})", RuntimeWarning, stacklevel=2)
        _CACHED_PACK = {}
        return _CACHED_PACK


_VALID_COND_TYPES = frozenset(
    {
        "economy_total_gte",
        "trace_pct_lte",
        "trace_pct_gte",
        "police_attention_not_in",
        "any_faction_power_stability_gte",
        "all_milestones_completed",
        "quest_active",
        "ripple_seen",
        "reputation_lane_gte",
    }
)
_VALID_ACTION_TYPES = frozenset(
    {
        "world_note",
        "schedule_event_if_missing",
        "enqueue_ripple",
        "activate_quest",
        "suppress_ripple_tag",
    }
)


def validate_campaign_pack(doc: Any) -> list[str]:
    errs: list[str] = []
    arcs = doc.get("arcs") if isinstance(doc, dict) else None
    if not isinstance(arcs, list):
        return ["missing arcs list"]
    for i, a in enumerate(arcs[:32]):
        if not isinstance(a, dict):
            errs.append(f"arc[{i}]: must be object")
            continue
        aid = str(a.get("id", "") or "").strip()
        if not aid:
            errs.append(f"arc[{i}]: missing id")
        ms = a.get("milestones")
        if not isinstance(ms, list) or not ms:
            errs.append(f"arc[{i}] id={aid or '?'}: missing milestones")
        se = a.get("soft_endings")
        if se is not None and not isinstance(se, list):
            errs.append(f"arc[{i}] id={aid or '?'}: soft_endings must be list")
        for j, m in enumerate((ms if isinstance(ms, list) else [])[:64]):
            if not isinstance(m, dict):
                errs.append(f"arc[{i}] milestone[{j}]: must be object")
                continue
            mid = str(m.get("id", "") or "").strip()
            if not mid:
                errs.append(f"arc[{i}] milestone[{j}]: missing id")
            when = m.get("when")
            if not isinstance(when, dict):
                errs.append(f"arc[{i}] milestone[{j}] id={mid or '?'}: missing when")
            else:
                for c in (when.get("all") or [])[:24]:
                    if isinstance(c, dict):
                        errs.extend(_validate_condition_node(c, ctx=f"arc[{i}] milestone[{j}] id={mid}"))
            acts = m.get("actions")
            if not isinstance(acts, list):
                errs.append(f"arc[{i}] milestone[{j}] id={mid or '?'}: actions must be list")
            else:
                for k, act in enumerate(acts[:24]):
                    if isinstance(act, dict):
                        errs.extend(_validate_action_node(act, ctx=f"arc[{i}] milestone[{j}] action[{k}]"))
        soft_list = se if isinstance(se, list) else []
        for j, se_row in enumerate(soft_list[:24]):
            if not isinstance(se_row, dict):
                errs.append(f"arc[{i}] soft_ending[{j}]: must be object")
                continue
            when = se_row.get("when")
            if not isinstance(when, dict):
                errs.append(f"arc[{i}] soft_ending[{j}]: missing when")
            else:
                for c in (when.get("all") or [])[:24]:
                    if isinstance(c, dict):
                        errs.extend(_validate_condition_node(c, ctx=f"arc[{i}] soft_ending[{j}]"))
    return errs


def _validate_condition_node(c: dict[str, Any], *, ctx: str) -> list[str]:
    errs: list[str] = []
    t = _norm(c.get("type", ""))
    if not t:
        errs.append(f"{ctx}: condition missing type")
        return errs
    if t not in _VALID_COND_TYPES:
        errs.append(f"{ctx}: unknown condition type '{t}'")
    if t == "quest_active":
        if not str(c.get("quest_id", "") or "").strip() and not str(c.get("quest_kind", "") or "").strip():
            errs.append(f"{ctx}: quest_active needs quest_id or quest_kind")
    if t == "ripple_seen" and not str(c.get("tag", "") or "").strip():
        errs.append(f"{ctx}: ripple_seen needs tag")
    if t == "trace_pct_gte" and "value" not in c:
        errs.append(f"{ctx}: trace_pct_gte needs value")
    if t == "reputation_lane_gte":
        if not str(c.get("lane", "") or "").strip():
            errs.append(f"{ctx}: reputation_lane_gte needs lane")
        if "value" not in c and "threshold" not in c:
            errs.append(f"{ctx}: reputation_lane_gte needs value or threshold")
    return errs


def _validate_action_node(act: dict[str, Any], *, ctx: str) -> list[str]:
    errs: list[str] = []
    t = _norm(act.get("type", ""))
    if not t:
        errs.append(f"{ctx}: action missing type")
        return errs
    if t not in _VALID_ACTION_TYPES:
        errs.append(f"{ctx}: unknown action type '{t}'")
    if t == "activate_quest":
        if not str(act.get("quest_kind", "") or "").strip() and not str(act.get("quest_id", "") or "").strip():
            errs.append(f"{ctx}: activate_quest needs quest_kind or quest_id")
    if t == "suppress_ripple_tag":
        if not str(act.get("tag", "") or "").strip():
            errs.append(f"{ctx}: suppress_ripple_tag needs tag")
        cd = act.get("cooldown_days", 1)
        try:
            if int(cd) < 1:
                errs.append(f"{ctx}: suppress_ripple_tag cooldown_days must be >= 1")
        except Exception:
            errs.append(f"{ctx}: suppress_ripple_tag cooldown_days must be int")
    return errs


def is_ripple_tag_suppressed_for_followups(state: dict[str, Any], tag: str, *, day: int) -> bool:
    """True while current day is within the inclusive cooldown window for this normalized tag."""
    arcs = (state.get("world", {}) or {}).get("arc_campaign", {}) or {}
    if not isinstance(arcs, dict):
        return False
    sup = arcs.get("ripple_tag_suppress")
    if not isinstance(sup, dict):
        return False
    lk = _norm(tag)
    if not lk or lk not in sup:
        return False
    try:
        until_inclusive = int(sup[lk])
    except Exception:
        return False
    return int(day) <= until_inclusive


def record_surfaced_ripple_tags(state: dict[str, Any], rp: dict[str, Any], *, day: int) -> None:
    """Record ripple tags when a ripple actually surfaces (deterministic memory for arc conditions)."""
    if not isinstance(rp, dict) or bool(rp.get("dropped_by_propagation")):
        return
    try:
        from engine.social.ripple_followups import _derive_ripple_tags
    except Exception as e:
        log_swallowed_exception("engine/systems/campaign_arcs.py:record_tags_import", e)
        return
    origin_faction = _norm(rp.get("origin_faction", ""))
    impact = rp.get("impact") if isinstance(rp.get("impact"), dict) else {}
    trace_pressure = 0
    if isinstance(impact, dict):
        try:
            trace_pressure = int(impact.get("trace_delta", 0) or 0)
        except Exception:
            trace_pressure = 0
    tags = _derive_ripple_tags(rp, origin_faction=origin_faction, trace_pressure=trace_pressure)
    tags.add("kind:" + _norm(rp.get("kind", "")))
    world = state.setdefault("world", {})
    seen = world.setdefault("ripple_tag_seen", {})
    if not isinstance(seen, dict):
        seen = {}
        world["ripple_tag_seen"] = seen
    d = int(day)
    for tg in list(tags)[:48]:
        k = _norm(tg)
        if not k:
            continue
        if k not in seen:
            seen[k] = d


def _pending_event_exists(state: dict[str, Any], event_type: str, *, day: int, title_contains: str = "") -> bool:
    events = state.get("pending_events", []) or []
    if not isinstance(events, list):
        return False
    needle = _norm(title_contains)
    for ev in events[-120:]:
        if not isinstance(ev, dict):
            continue
        if bool(ev.get("triggered")):
            continue
        if str(ev.get("event_type", "") or "") != event_type:
            continue
        try:
            due_day = int(ev.get("due_day", 0) or 0)
        except Exception:
            due_day = 0
        if due_day < int(day):
            continue
        if needle and needle not in _norm(ev.get("title", "")):
            continue
        return True
    return False


def _mark_milestone(arcs: dict[str, Any], milestone_id: str, *, day: int) -> bool:
    ms = arcs.setdefault("milestones", {})
    row = ms.get(milestone_id)
    if isinstance(row, dict) and row.get("completed"):
        return False
    ms[milestone_id] = {"completed": True, "day": int(day)}
    arcs["milestones"] = ms
    return True


def _economy_total(state: dict[str, Any]) -> int:
    eco = state.get("economy", {}) or {}
    try:
        cash = int(eco.get("cash", 0) or 0)
    except Exception:
        cash = 0
    try:
        bank = int(eco.get("bank", 0) or 0)
    except Exception:
        bank = 0
    return int(cash + bank)


def _trace_pct(state: dict[str, Any]) -> int:
    tr = state.get("trace", {}) or {}
    try:
        return int(tr.get("trace_pct", 0) or 0)
    except Exception:
        return 0


def _police_attention(state: dict[str, Any]) -> str:
    statuses = ((state.get("world", {}) or {}).get("faction_statuses", {}) or {})
    return _norm(statuses.get("police", "idle"))


def _any_faction_power_stability_gte(state: dict[str, Any], *, power: int, stability: int) -> bool:
    factions = ((state.get("world", {}) or {}).get("factions", {}) or {})
    if not isinstance(factions, dict):
        return False
    for _name, row in list(factions.items())[:30]:
        if not isinstance(row, dict):
            continue
        try:
            pw = int(row.get("power", 50) or 50)
            st = int(row.get("stability", 50) or 50)
        except Exception:
            pw, st = 50, 50
        if pw >= int(power) and st >= int(stability):
            return True
    return False


def _all_done(arcs: dict[str, Any], ids: list[str]) -> bool:
    ms = arcs.get("milestones", {}) or {}
    if not isinstance(ms, dict):
        return False
    for mid in ids:
        row = ms.get(mid)
        if not (isinstance(row, dict) and bool(row.get("completed"))):
            return False
    return True


def _when_all_milestones_completed(arcs: dict[str, Any], ids: list[str]) -> bool:
    return _all_done(arcs, ids)


def _eval_condition(state: dict[str, Any], arcs: dict[str, Any], cond: dict[str, Any]) -> bool:
    """Evaluate a single condition node (deterministic, small opcode set)."""
    if not isinstance(cond, dict):
        return False
    t = _norm(cond.get("type", ""))
    if t == "economy_total_gte":
        try:
            v = int(cond.get("value", 0) or 0)
        except Exception:
            v = 0
        return _economy_total(state) >= v
    if t == "trace_pct_lte":
        try:
            v = int(cond.get("value", 100) or 100)
        except Exception:
            v = 100
        return _trace_pct(state) <= v
    if t == "trace_pct_gte":
        try:
            v = int(cond.get("value", 0) or 0)
        except Exception:
            v = 0
        return _trace_pct(state) >= v
    if t == "police_attention_not_in":
        vals = cond.get("values")
        if not isinstance(vals, list):
            return True
        deny = {_norm(x) for x in vals if isinstance(x, str) and _norm(x)}
        return _police_attention(state) not in deny
    if t == "any_faction_power_stability_gte":
        try:
            pw = int(cond.get("power", 60) or 60)
        except Exception:
            pw = 60
        try:
            st = int(cond.get("stability", 40) or 40)
        except Exception:
            st = 40
        return _any_faction_power_stability_gte(state, power=pw, stability=st)
    if t == "all_milestones_completed":
        ids = cond.get("ids")
        if not isinstance(ids, list):
            return False
        want = [str(x) for x in ids if isinstance(x, str) and str(x).strip()]
        return _when_all_milestones_completed(arcs, want)
    if t == "quest_active":
        qid = str(cond.get("quest_id", "") or "").strip()
        kind = _norm(cond.get("quest_kind", "") or cond.get("kind", ""))
        quests = state.get("quests", {}) or {}
        active = quests.get("active") if isinstance(quests, dict) else []
        if not isinstance(active, list):
            return False
        for q in active[-80:]:
            if not isinstance(q, dict):
                continue
            if str(q.get("status", "active") or "active") not in ("active", "overdue"):
                continue
            if qid and str(q.get("id", "") or "") == qid:
                return True
            if kind and _norm(q.get("kind", "")) == kind:
                return True
        return False
    if t == "ripple_seen":
        tag = _norm(cond.get("tag", ""))
        if not tag:
            return False
        seen = (state.get("world", {}) or {}).get("ripple_tag_seen") or {}
        if not isinstance(seen, dict):
            return False
        return tag in seen
    if t == "reputation_lane_gte":
        lane = str(cond.get("lane", "") or "").strip().lower()
        raw = cond.get("value") if "value" in cond else cond.get("threshold", 0)
        try:
            th = int(raw or 0)
        except Exception:
            th = 0
        return lane_score(state, lane) >= th
    return False


def _eval_when(state: dict[str, Any], arcs: dict[str, Any], when: dict[str, Any]) -> bool:
    if not isinstance(when, dict):
        return False
    all_nodes = when.get("all")
    if isinstance(all_nodes, list) and all_nodes:
        for c in all_nodes[:16]:
            if not _eval_condition(state, arcs, c if isinstance(c, dict) else {}):
                return False
    all_ms = when.get("all_milestones_completed")
    if isinstance(all_ms, list) and all_ms:
        want = [str(x) for x in all_ms if isinstance(x, str) and str(x).strip()]
        if not _when_all_milestones_completed(arcs, want):
            return False
    return True


def _apply_action(state: dict[str, Any], arcs: dict[str, Any], *, day: int, time_min: int, action: dict[str, Any]) -> None:
    if not isinstance(action, dict):
        return
    t = _norm(action.get("type", ""))
    if t == "world_note":
        txt = str(action.get("text", "") or "").strip()
        if txt:
            state.setdefault("world_notes", []).append(txt)
        return
    if t == "schedule_event_if_missing":
        et = str(action.get("event_type", "") or "").strip()
        title = str(action.get("title", et) or et).strip()
        try:
            due_in = int(action.get("due_in_min", 10) or 10)
        except Exception:
            due_in = 10
        payload = action.get("payload") if isinstance(action.get("payload"), dict) else {}
        if not et:
            return
        if _pending_event_exists(state, et, day=day, title_contains=title):
            return
        pl = dict(payload)
        loc = _norm((payload or {}).get("location", "")) or _norm(((state.get("player", {}) or {}).get("location", "")))
        if loc:
            pl.setdefault("location", loc)
        state.setdefault("pending_events", []).append(
            {
                "event_type": et,
                "title": title,
                "due_day": int(day),
                "due_time": min(1439, int(time_min) + max(0, due_in)),
                "triggered": False,
                "payload": pl,
            }
        )
        return
    if t == "enqueue_ripple":
        kind = str(action.get("kind", "") or "").strip() or "arc_milestone"
        txt = str(action.get("text", "") or "").strip()
        if not txt:
            return
        prop = str(action.get("propagation", "broadcast") or "broadcast")
        of = str(action.get("origin_faction", "civilian") or "civilian")
        try:
            surf_in = int(action.get("surface_in_min", 10) or 10)
        except Exception:
            surf_in = 10
        tags = action.get("tags") if isinstance(action.get("tags"), list) else []
        meta0 = action.get("meta") if isinstance(action.get("meta"), dict) else {}
        loc = _norm(((state.get("player", {}) or {}).get("location", ""))) or "unknown"
        enqueue_ripple(
            state,
            {
                "kind": kind,
                "text": txt,
                "triggered_day": int(day),
                "surface_day": int(day),
                "surface_time": min(1439, int(time_min) + max(0, surf_in)),
                "surfaced": False,
                "propagation": prop,
                "origin_location": loc,
                "origin_faction": _norm(of) or "civilian",
                "witnesses": [],
                "surface_attempts": 0,
                "tags": [str(x) for x in tags if isinstance(x, str)][:12],
                "meta": dict(meta0),
            },
        )
        return
    if t == "activate_quest":
        _apply_activate_quest(state, action)
        return
    if t == "suppress_ripple_tag":
        tag = _norm(action.get("tag", ""))
        if not tag:
            return
        try:
            cd = int(action.get("cooldown_days", 1) or 1)
        except Exception:
            cd = 1
        cd = max(1, cd)
        until_inclusive = int(day) + cd - 1
        sup = arcs.setdefault("ripple_tag_suppress", {})
        if not isinstance(sup, dict):
            sup = {}
            arcs["ripple_tag_suppress"] = sup
        sup[tag] = until_inclusive
        return


def _apply_activate_quest(state: dict[str, Any], action: dict[str, Any]) -> None:
    qid_want = str(action.get("quest_id", "") or "").strip()
    kind = _norm(action.get("quest_kind", "") or action.get("kind", ""))
    loc = _norm(action.get("origin_location", "")) or _norm(((state.get("player", {}) or {}).get("location", "")))
    if not loc:
        loc = "unknown"
    quests = state.get("quests", {}) or {}
    active = quests.get("active") if isinstance(quests, dict) else []
    if not isinstance(active, list):
        active = []
    if qid_want:
        for q in active[-80:]:
            if not isinstance(q, dict):
                continue
            if str(q.get("id", "") or "") != qid_want:
                continue
            if str(q.get("status", "active") or "active") in ("active", "overdue"):
                return
    if not kind:
        return
    trace_snapshot = int(((state.get("trace", {}) or {}).get("trace_pct", 0) or 0))
    if kind == "trace_cleanup":
        create_trace_cleanup_quest(state, origin_location=loc, trace_snapshot=trace_snapshot)
    elif kind in ("corp_infiltration", "corp"):
        create_corp_infiltration_quest(state, origin_location=loc)
    elif kind in ("bm_delivery", "black_market_delivery"):
        try:
            bm_p = int(action.get("bm_power", 65) or 65)
        except Exception:
            bm_p = 65
        try:
            bm_s = int(action.get("bm_stability", 35) or 35)
        except Exception:
            bm_s = 35
        create_black_market_delivery_quest(state, origin_location=loc, bm_power=bm_p, bm_stability=bm_s)
    else:
        return


def evaluate_arc_campaign_daily(state: dict[str, Any], *, day: int) -> dict[str, Any]:
    """Daily long-horizon arc layer on top of sandbox (soft, deterministic, non-blocking)."""
    arcs = _ensure_arc_state(state)
    if not bool(arcs.get("enabled", True)):
        return {"disabled": 1}
    try:
        last = int(arcs.get("last_eval_day", 0) or 0)
    except Exception:
        last = 0
    if last == int(day):
        return {"skipped": 1}
    arcs["last_eval_day"] = int(day)

    meta = state.get("meta", {}) or {}
    try:
        time_min = int(meta.get("time_min", 0) or 0)
    except Exception:
        time_min = 0

    completed = 0
    pack = _load_pack()
    for msg in validate_campaign_pack(pack):
        warnings.warn(f"campaign_arcs pack warning: {msg}", RuntimeWarning, stacklevel=2)
    arcs_list = pack.get("arcs") if isinstance(pack.get("arcs"), list) else []
    arc_def = None
    for a in arcs_list[:16]:
        if isinstance(a, dict) and str(a.get("id", "") or "").strip() == str(arcs.get("active_arc", ARC_ID) or ARC_ID):
            arc_def = a
            break
    milestones = (arc_def or {}).get("milestones") if isinstance(arc_def, dict) else []
    if not isinstance(milestones, list):
        milestones = []
    for m in milestones[:64]:
        if not isinstance(m, dict):
            continue
        mid = str(m.get("id", "") or "").strip()
        when = m.get("when") if isinstance(m.get("when"), dict) else {}
        if not mid or not _eval_when(state, arcs, when):
            continue
        if _mark_milestone(arcs, mid, day=int(day)):
            completed += 1
            acts = m.get("actions") if isinstance(m.get("actions"), list) else []
            for act in acts[:12]:
                try:
                    _apply_action(state, arcs, day=int(day), time_min=int(time_min), action=act if isinstance(act, dict) else {})
                except Exception as e:
                    log_swallowed_exception("engine/systems/campaign_arcs.py:action", e)
            hist = arcs.setdefault("history", [])
            if isinstance(hist, list):
                hist.append({"day": int(day), "milestone": mid})
                del hist[: max(0, len(hist) - 30)]
            state.setdefault("world_notes", []).append(f"[Arc] Milestone unlocked: {mid}.")

    if not str(arcs.get("ending_state", "") or "") and isinstance(arc_def, dict):
        soft = arc_def.get("soft_endings") if isinstance(arc_def.get("soft_endings"), list) else []
        picked = ""
        for se in soft[:12]:
            if not isinstance(se, dict):
                continue
            sid = str(se.get("id", "") or "").strip()
            when = se.get("when") if isinstance(se.get("when"), dict) else {}
            if sid and _eval_when(state, arcs, when):
                picked = sid
                break
        if picked:
            arcs["ending_state"] = picked
            state.setdefault("world_notes", []).append(f"[Arc] Soft ending reached: {picked}. Dunia tetap berjalan.")
            enqueue_ripple(
                state,
                {
                    "kind": "arc_soft_ending",
                    "text": "Satu bab kariermu terasa lengkap, tapi kota ini belum pernah benar-benar selesai.",
                    "triggered_day": int(day),
                    "surface_day": int(day),
                    "surface_time": min(1439, int(time_min) + 25),
                    "surfaced": False,
                    "propagation": "broadcast",
                    "origin_location": _norm(((state.get("player", {}) or {}).get("location", ""))) or "unknown",
                    "origin_faction": "civilian",
                    "witnesses": [],
                    "surface_attempts": 0,
                    "tags": ["arc", "soft_ending"],
                    "meta": {"arc": str(arcs.get("active_arc", ARC_ID) or ARC_ID), "ending_state": picked},
                },
            )
            completed += 1

    state.setdefault("world", {})["arc_campaign"] = arcs
    return {"completed": completed, "ending_state": str(arcs.get("ending_state", "") or "")}
