"""Utility AI (needs + daily goals) — deterministic, bounded, RimWorld/DF-inspired.

Each NPC tracks **pressure** 0–100 per need (higher = more urgent). Once per calendar day,
``evaluate_npc_goals`` may schedule seek-job / relocate / contact-player style outcomes using
existing ripples + world_notes (no LLM).
"""

from __future__ import annotations

import asyncio
import hashlib
from typing import Any

from engine.core.error_taxonomy import log_swallowed_exception
from engine.npc.npc_agenda import ensure_npc_has_agenda_fields
from engine.social.ripple_queue import enqueue_ripple
from engine.world.districts import default_district_for_city, district_heat_snapshot, district_neighbor_ids


NEED_KEYS = ("financial", "security", "social")


def _h(*parts: Any) -> int:
    s = "|".join(str(p) for p in parts)
    return int(hashlib.md5(s.encode("utf-8", errors="ignore")).hexdigest()[:8], 16)


def _clamp(v: int, lo: int, hi: int) -> int:
    return max(lo, min(hi, int(v)))


def _norm(s: Any) -> str:
    return str(s or "").strip().lower()


def ensure_npc_utility_fields(npc: dict[str, Any], *, name: str, seed: str, day: int) -> dict[str, Any]:
    """Ensure ``utility_needs`` + ``utility_planner`` exist with deterministic baselines."""
    up = npc.setdefault("utility_planner", {})
    if not isinstance(up, dict):
        up = {}
        npc["utility_planner"] = up
    up.setdefault("last_eval_day", 0)
    up.setdefault("cooldown_until_day", 0)
    up.setdefault("last_action", "")

    needs = npc.get("utility_needs")
    if not isinstance(needs, dict) or not needs:
        base_f = 18 + (_h("ufin", seed, name) % 35)
        base_s = 16 + (_h("usec", seed, name) % 38)
        base_o = 20 + (_h("usoc", seed, name) % 32)
        npc["utility_needs"] = {
            "financial": _clamp(base_f, 0, 100),
            "security": _clamp(base_s, 0, 100),
            "social": _clamp(base_o, 0, 100),
        }
    else:
        for k in NEED_KEYS:
            needs.setdefault(k, 25)
            try:
                needs[k] = _clamp(int(needs[k]), 0, 100)
            except Exception as _omni_sw_48:
                log_swallowed_exception("engine/npc/npc_utility_ai.py:48", _omni_sw_48)
                needs[k] = 25
    return up


def _belief_pair(npc: dict[str, Any]) -> tuple[int, int]:
    bs = npc.get("belief_summary") or {}
    if not isinstance(bs, dict):
        return (0, 50)
    try:
        sus = int(bs.get("suspicion", 0) or 0)
    except Exception:
        sus = 0
    try:
        rep = int(bs.get("respect", 50) or 50)
    except Exception:
        rep = 50
    return (_clamp(sus, 0, 100), _clamp(rep, 0, 100))


def _plutchik_alarm(npc: dict[str, Any]) -> int:
    try:
        fear = int(npc.get("fear", 10) or 0)
    except Exception:
        fear = 10
    try:
        surprise = int(npc.get("surprise", 0) or 0)
    except Exception:
        surprise = 0
    return _clamp(int(round((fear + surprise) / 2)), 0, 100)


def _player_edge_strength(state: dict[str, Any], npc_name: str) -> int:
    world = state.get("world", {}) or {}
    g = world.get("social_graph") or {}
    if not isinstance(g, dict):
        return 40
    row = g.get("__player__") or {}
    if not isinstance(row, dict):
        return 40
    edge = row.get(npc_name)
    if not isinstance(edge, dict):
        return 40
    try:
        return _clamp(int(edge.get("strength", 40) or 40), 0, 100)
    except Exception:
        return 40


def _adjust_pressures_from_state(state: dict[str, Any], name: str, npc: dict[str, Any], *, day: int, seed: str) -> None:
    """Situational pressure — called before action selection."""
    needs = npc.get("utility_needs")
    if not isinstance(needs, dict):
        return
    sus, rep = _belief_pair(npc)
    alarm = _plutchik_alarm(npc)
    edge = _player_edge_strength(state, name)

    city = _norm(npc.get("current_location", "")) or _norm(npc.get("home_location", ""))
    did = str(npc.get("district", "") or "").strip().lower() or (
        default_district_for_city(state, city) if city else ""
    )
    heat = district_heat_snapshot(state, city, did) if city and did else 0

    # Financial: low respect / failed money agenda nudges urgency.
    ag = npc.get("w2_agenda") if isinstance(npc.get("w2_agenda"), dict) else {}
    fin = int(needs.get("financial", 30) or 30)
    if str(ag.get("goal_outcome", "") or "") == "failed" and str(ag.get("daily_goal", "") or "") == "earn_money":
        fin += 14
    if rep < 38:
        fin += 6
    fin += (_h("fin_d", seed, day, name) % 5)
    needs["financial"] = _clamp(fin, 0, 100)

    # Security: suspicion, alarm, local heat.
    sec = int(needs.get("security", 25) or 25)
    sec += sus // 4 + alarm // 5 + heat // 6
    sec += (_h("sec_d", seed, day, name) % 4)
    needs["security"] = _clamp(sec, 0, 100)

    # Social: isolation from player + moderate alarm (seek company).
    soc = int(needs.get("social", 28) or 28)
    soc += (100 - edge) // 5
    if edge < 45:
        soc += 8
    soc += (_h("soc_d", seed, day, name) % 4)
    needs["social"] = _clamp(soc, 0, 100)


def _daily_drift(needs: dict[str, Any], *, name: str, day: int, seed: str) -> None:
    """Slowly rising pressure (life costs / loneliness) — capped."""
    for k in NEED_KEYS:
        try:
            v = int(needs.get(k, 0) or 0)
        except Exception:
            v = 25
        bump = 2 + (_h("drift", k, seed, day, name) % 5)
        needs[k] = _clamp(v + bump, 0, 100)


def _pick_best_action(
    needs: dict[str, Any], *, name: str, day: int, seed: str
) -> tuple[str, int]:
    """Return (action_key, score). action_key in seek_job | move_district | contact_player | none."""
    f = int(needs.get("financial", 0) or 0)
    s = int(needs.get("security", 0) or 0)
    o = int(needs.get("social", 0) or 0)
    # Weighted utility (integer)
    u_job = f * 100 + (_h("wj", seed, name, day) % 40)
    u_mov = int(s * 110 + (_h("wm", seed, name, day) % 45))
    u_con = int(o * 105 + (_h("wc", seed, name, day) % 50))
    best = max((u_job, "seek_job"), (u_mov, "move_district"), (u_con, "contact_player"), key=lambda x: x[0])
    if best[0] < 5000:  # ~50 equivalent threshold on 0–100 need scale
        return ("none", best[0])
    return (best[1], best[0])


def _align_agenda_with_seek_job(npc: dict[str, Any], *, day: int) -> None:
    """Keep W2 agenda in sync when utility AI pushes job-seeking (runs after daily agenda tick)."""
    ensure_npc_has_agenda_fields(npc)
    ag = npc.get("w2_agenda")
    if not isinstance(ag, dict):
        return
    ag["daily_goal"] = "earn_money"
    ag["goal_outcome"] = ""
    try:
        gd = int(ag.get("goal_deadline_day", 0) or 0)
    except Exception:
        gd = 0
    if gd < int(day):
        ag["goal_deadline_day"] = int(day) + 2
    try:
        prog = int(ag.get("goal_progress", 0) or 0)
    except Exception:
        prog = 0
    # Boost progress without auto-completing here; npc_agenda daily tick resolves >=100.
    ag["goal_progress"] = min(95, prog + 22)
    npc["w2_agenda"] = ag


def _apply_action_seek_job(
    state: dict[str, Any], name: str, npc: dict[str, Any], needs: dict[str, Any], *, day: int
) -> None:
    up = npc.setdefault("utility_planner", {})
    if up.get("job_seeking_until_day") and int(day) <= int(up.get("job_seeking_until_day", 0) or 0):
        return
    up["job_seeking_until_day"] = int(day) + 4
    up["last_action"] = "seek_job"
    needs["financial"] = _clamp(int(needs.get("financial", 0) or 0) - 22, 0, 100)
    _align_agenda_with_seek_job(npc, day=int(day))
    enqueue_ripple(
        state,
        {
            "kind": "npc_utility_seek_job",
            "text": f"{name} mencari pekerjaan sampingan / gig (tekanan ekonomi).",
            "triggered_day": int(day),
            "surface_day": int(day),
            "surface_time": min(1439, 11 * 60),
            "surfaced": False,
            "propagation": "local_witness",
            "origin_location": _norm(npc.get("current_location", "")) or _norm(npc.get("home_location", "")) or "unknown",
            "origin_faction": _norm(npc.get("affiliation", "civilian")),
            "witnesses": [],
            "surface_attempts": 0,
            "meta": {"npc": name, "utility": "seek_job"},
        },
    )
    state.setdefault("world_notes", []).append(f"[NPC] {name} mulai aktif cari kerja / gig.")


def _apply_action_move_district(
    state: dict[str, Any], name: str, npc: dict[str, Any], needs: dict[str, Any], *, day: int, seed: str
) -> None:
    city = _norm(npc.get("current_location", "")) or _norm(npc.get("home_location", ""))
    if not city:
        return
    cur = str(npc.get("district", "") or "").strip().lower() or default_district_for_city(state, city)
    if not cur:
        return
    nbr = district_neighbor_ids(state, city, cur)
    if not nbr:
        return
    dest = nbr[_h("move", seed, day, name, cur) % len(nbr)]
    here = cur
    npc["district"] = dest
    if not _norm(npc.get("home_location", "")):
        npc["home_location"] = city
    needs["security"] = _clamp(int(needs.get("security", 0) or 0) - 20, 0, 100)
    npc.setdefault("utility_planner", {})["last_action"] = "move_district"
    enqueue_ripple(
        state,
        {
            "kind": "npc_utility_relocate",
            "text": f"{name} pindah distrik (mencari lingkungan lebih aman / peluang).",
            "triggered_day": int(day),
            "surface_day": int(day),
            "surface_time": min(1439, 13 * 60),
            "surfaced": False,
            "propagation": "local_witness",
            "origin_location": city,
            "origin_faction": _norm(npc.get("affiliation", "civilian")),
            "witnesses": [],
            "surface_attempts": 0,
            "meta": {"npc": name, "utility": "move", "from_district": here, "to_district": dest},
        },
    )
    state.setdefault("world_notes", []).append(f"[NPC] {name} memindahkan aktivitas ke distrik lain ({dest}).")


def _apply_action_contact_player(
    state: dict[str, Any], name: str, npc: dict[str, Any], needs: dict[str, Any], *, day: int
) -> None:
    needs["social"] = _clamp(int(needs.get("social", 0) or 0) - 18, 0, 100)
    pl = npc.setdefault("utility_planner", {})
    pl["last_action"] = "contact_player"
    pl["wants_contact_day"] = int(day)
    loc = _norm(npc.get("current_location", "")) or _norm(npc.get("home_location", "")) or "unknown"
    enqueue_ripple(
        state,
        {
            "kind": "npc_utility_contact",
            "text": f"{name} mencoba menghubungi kamu (butuh bantuan / kontak).",
            "triggered_day": int(day),
            "surface_day": int(day),
            "surface_time": min(1439, 10 * 60),
            "surfaced": False,
            "propagation": "contacts" if npc.get("is_contact") is True else "local_witness",
            "origin_location": loc,
            "origin_faction": _norm(npc.get("affiliation", "civilian")),
            "witnesses": [],
            "surface_attempts": 0,
            "meta": {"npc": name, "utility": "contact_player"},
        },
    )
    state.setdefault("world_notes", []).append(
        f"[NPC] {name} meninggalkan jejak kontak — pertimbangkan TALK {name} atau SMARTPHONE."
    )


async def evaluate_npc_goals(state: dict[str, Any], *, batch_size: int = 50) -> dict[str, int]:
    """Run once per calendar day. Batched + cooperative to avoid blocking the async game loop."""
    world = state.setdefault("world", {})
    meta = state.get("meta", {}) or {}
    day = int(meta.get("day", 1) or 1)
    seed = str(meta.get("seed_pack", "") or meta.get("world_seed", "") or "default")

    try:
        last = int(world.get("last_utility_ai_day", 0) or 0)
    except Exception as _omni_sw_228:
        log_swallowed_exception("engine/npc/npc_utility_ai.py:228", _omni_sw_228)
        last = 0
    if last == day:
        return {"skipped": 1, "evaluated": 0, "actions": 0}

    flags = state.get("flags", {}) or {}
    if not bool(flags.get("npc_utility_ai_enabled", True)):
        world["last_utility_ai_day"] = int(day)
        return {"disabled": 1}

    npcs = state.get("npcs", {}) or {}
    if not isinstance(npcs, dict) or not npcs:
        world["last_utility_ai_day"] = int(day)
        return {"evaluated": 0, "actions": 0}

    world["last_utility_ai_day"] = int(day)

    stats = {"evaluated": 0, "seek_job": 0, "move_district": 0, "contact_player": 0}
    max_actions = 8
    actions = 0

    names = sorted([str(n) for n in npcs.keys() if isinstance(n, str)])[:96]
    bs = max(1, int(batch_size or 50))
    processed = 0

    for i, nm in enumerate(names):
        npc = npcs.get(nm)
        if not isinstance(npc, dict):
            continue
        if npc.get("alive") is False:
            continue
        if npc.get("ambient") is True:
            continue

        ensure_npc_utility_fields(npc, name=nm, seed=seed, day=day)
        needs = npc.setdefault("utility_needs", {})
        if not isinstance(needs, dict):
            continue

        _daily_drift(needs, name=nm, day=day, seed=seed)
        _adjust_pressures_from_state(state, nm, npc, day=day, seed=seed)

        up = npc.get("utility_planner") or {}
        if int(up.get("cooldown_until_day", 0) or 0) > int(day):
            stats["evaluated"] += 1
            processed += 1
            if processed % bs == 0:
                await asyncio.sleep(0)
            continue

        act, _score = _pick_best_action(needs, name=nm, day=day, seed=seed)
        stats["evaluated"] += 1

        if act != "none" and actions < max_actions:
            try:
                if act == "seek_job":
                    _apply_action_seek_job(state, nm, npc, needs, day=day)
                    stats["seek_job"] += 1
                elif act == "move_district":
                    _apply_action_move_district(state, nm, npc, needs, day=day, seed=seed)
                    stats["move_district"] += 1
                elif act == "contact_player":
                    _apply_action_contact_player(state, nm, npc, needs, day=day)
                    stats["contact_player"] += 1
            except Exception as e:
                log_swallowed_exception("engine/npc/npc_utility_ai.py:action", e)
            else:
                actions += 1
                up = npc.setdefault("utility_planner", {})
                up["cooldown_until_day"] = int(day) + 1 + (_h("cd", seed, nm, day) % 2)
                up["last_eval_day"] = int(day)
                npcs[nm] = npc
        processed += 1
        if (i + 1) % bs == 0:
            await asyncio.sleep(0)

    state["npcs"] = npcs
    state["world"] = world
    stats["actions"] = actions
    return stats
