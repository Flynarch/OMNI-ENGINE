from __future__ import annotations

"""Freelance gigs (WORK). W2-9 employed salary is paid in the daily economy cycle via occupation.accrue_career_salary_and_decay."""

import hashlib
from typing import Any

from engine.core.rng import det_roll_1_100


def _seed_key(state: dict[str, Any]) -> str:
    meta = state.get("meta", {}) or {}
    seed = str(meta.get("world_seed", "") or meta.get("seed_pack", "") or "").strip()
    return seed or "seed"


def _day(state: dict[str, Any]) -> int:
    meta = state.get("meta", {}) or {}
    try:
        return int(meta.get("day", 1) or 1)
    except Exception:
        return 1


def _turn(state: dict[str, Any]) -> int:
    meta = state.get("meta", {}) or {}
    try:
        return int(meta.get("turn", 0) or 0)
    except Exception:
        return 0


def _loc(state: dict[str, Any]) -> str:
    return str((state.get("player", {}) or {}).get("location", "") or "").strip().lower()


def _occupation(state: dict[str, Any]) -> str:
    p = state.get("player", {}) or {}
    if isinstance(p, dict):
        occ = str(p.get("occupation", "") or "").strip()
        if occ:
            return occ
    bio = state.get("bio", {}) or {}
    if isinstance(bio, dict):
        occ = str(bio.get("occupation", "") or "").strip()
        if occ:
            return occ
    return "freelancer"


def _occ_profile(occ: str) -> tuple[str, str]:
    o = str(occ or "").strip().lower()
    # map to (req_skill, vibe)
    if any(k in o for k in ("hack", "hacker", "it", "cyber", "program", "engineer", "dev")):
        return ("hacking", "Data Extraction")
    if any(k in o for k in ("driver", "courier", "delivery", "rideshare", "taxi", "pilot")):
        return ("driving", "Courier Run")
    if any(k in o for k in ("med", "doctor", "nurse", "paramedic")):
        return ("medical", "Emergency Shift")
    if any(k in o for k in ("social", "sales", "negotiat", "lawyer", "diplomat", "recruit")):
        return ("social", "Client Negotiation")
    if any(k in o for k in ("guard", "security", "soldier", "combat", "merc")):
        return ("combat", "Protection Detail")
    if any(k in o for k in ("stealth", "spy", "thief", "infiltrat")):
        return ("stealth", "Quiet Retrieval")
    return ("streetwise", "Odd Job")


def generate_gigs(state: dict[str, Any]) -> list[dict[str, Any]]:
    """Return 2–3 deterministic gigs based on (seed, day, location, occupation)."""
    seed = _seed_key(state)
    day = _day(state)
    loc = _loc(state) or "unknown"
    occ = _occupation(state)
    req_skill, base_title = _occ_profile(occ)
    h = hashlib.md5(f"{seed}|{day}|{loc}|{occ}|gigs_v1".encode("utf-8", errors="ignore")).hexdigest()
    n = 2 + (int(h[:2], 16) % 2)  # 2..3
    gigs: list[dict[str, Any]] = []
    for i in range(n):
        hi = hashlib.md5(f"{h}|{i}".encode("utf-8", errors="ignore")).hexdigest()
        difficulty = 1 + (int(hi[:2], 16) % 10)  # 1..10
        time_cost = 120 + (int(hi[2:4], 16) % 361)  # 120..480
        payout = int(max(50, (difficulty * 90) + (time_cost * 0.9)))
        gid = f"gig_{hi[4:12]}_{i}"
        title = f"{base_title} — {loc.replace('_', ' ').title()}"
        gigs.append(
            {
                "id": gid,
                "title": title,
                "req_skill": req_skill,
                "difficulty": int(difficulty),
                "time_cost_mins": int(time_cost),
                "payout_cash": int(payout),
            }
        )
    return gigs


def _skill_level(state: dict[str, Any], key: str) -> int:
    skills = state.get("skills", {}) or {}
    if not isinstance(skills, dict):
        return 1
    row = skills.get(str(key)) if isinstance(key, str) else None
    if not isinstance(row, dict):
        return 1
    try:
        return max(1, int(row.get("level", 1) or 1))
    except Exception:
        return 1


def execute_gig(state: dict[str, Any], gig_id: str) -> dict[str, Any]:
    meta = state.setdefault("meta", {})
    if not isinstance(meta, dict):
        meta = {}
        state["meta"] = meta
    try:
        done_today = int(meta.get("daily_gigs_done", 0) or 0)
    except Exception:
        done_today = 0
    if done_today >= 2:
        state.setdefault("world_notes", []).append(
            "[Economy] You are physically and mentally exhausted. Get some sleep before taking more gigs."
        )
        return {
            "ok": False,
            "reason": "daily_gig_limit_reached",
            "error_message": "[!] ERROR: You are physically and mentally exhausted. Get some sleep before taking more gigs.",
        }

    gigs = generate_gigs(state)
    target = None
    for g in gigs:
        if isinstance(g, dict) and str(g.get("id", "") or "") == str(gig_id or ""):
            target = g
            break
    if not isinstance(target, dict):
        return {"ok": False, "reason": "unknown_gig"}

    req = str(target.get("req_skill", "") or "")
    diff = int(target.get("difficulty", 1) or 1)
    lvl = _skill_level(state, req)
    bio = state.get("bio", {}) or {}
    try:
        hunger = float(bio.get("hunger", 0.0) or 0.0)
    except Exception:
        hunger = 0.0
    hunger_penalty = 0
    if hunger >= 86.0:
        state.setdefault("world_notes", []).append(
            "[Bio] You are too hungry to work. Eat first before attempting another gig."
        )
        return {
            "ok": False,
            "reason": "hunger_critical",
            "error_message": "[!] ERROR: You're starving and can't work. Eat first.",
        }
    if hunger >= 66.0:
        hunger_penalty = 20
    elif hunger >= 41.0:
        hunger_penalty = 8

    # Chance model (simple, deterministic): higher skill offsets difficulty.
    chance = 45 + max(0, (lvl - 1) * 6) - (diff * 5) - hunger_penalty
    chance = max(5, min(95, int(chance)))
    roll = det_roll_1_100(_seed_key(state), _day(state), _turn(state), _loc(state), req, diff, "gig_roll_v1", str(gig_id))
    success = int(roll) <= int(chance)
    trace_delta = 0
    # Risk hooks: illegal/grey jobs can raise Trace on failure.
    if not success and req in ("hacking", "stealth", "security"):
        trace_delta = 10
    meta["daily_gigs_done"] = int(done_today + 1)
    if success:
        try:
            from engine.social.reputation_lanes import bump_lane

            if req in ("hacking", "security"):
                bump_lane(state, "underground", 2)
            if req in ("streetwise", "stealth"):
                bump_lane(state, "street", 2)
                bump_lane(state, "criminal", 1)
            if req in ("management",):
                bump_lane(state, "corporate", 2)
                bump_lane(state, "political", 1)
        except Exception:
            pass
    return {
        "ok": True,
        "gig": dict(target),
        "success": bool(success),
        "roll": int(roll),
        "chance": int(chance),
        "time_cost_mins": int(target.get("time_cost_mins", 120) or 120),
        "payout_cash": int(target.get("payout_cash", 0) or 0),
        "trace_delta": int(trace_delta),
        "hunger_penalty": int(hunger_penalty),
    }

