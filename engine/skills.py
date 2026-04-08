from __future__ import annotations

from typing import Any


def _ensure_skill(state: dict[str, Any], key: str) -> dict[str, Any]:
    skills = state.setdefault("skills", {})
    if not isinstance(skills, dict):
        skills = {}
        state["skills"] = skills
    skills.setdefault(key, {"level": 1, "xp": 0, "base": 10, "last_used_day": 0, "mastery_streak": 0})
    row = skills.get(key)
    if not isinstance(row, dict):
        row = {"level": 1, "xp": 0, "base": 10, "last_used_day": 0, "mastery_streak": 0}
        skills[key] = row
    row.setdefault("level", 1)
    row.setdefault("xp", 0)
    row.setdefault("base", 10)
    row.setdefault("last_used_day", 0)
    row.setdefault("mastery_streak", 0)
    return row


def update_skills(state: dict, action_ctx: dict) -> None:
    """Passive maintenance: decay + compute current (progression is applied after roll)."""
    day = int(state.get("meta", {}).get("day", 1))
    for key in ("hacking", "social", "combat", "stealth", "evasion"):
        s = _ensure_skill(state, key)
        base = float(s.get("base", 10))
        last = int(s.get("last_used_day", day))
        d = max(0, day - last)
        penalty = 0 if d < 14 else -5 * ((d - 14) // 7)
        s["decay_active"] = d >= 14
        s["decay_penalty"] = penalty
        lvl = int(s.get("level", 1) or 1)
        # Level contributes small permanent base bonus.
        s["current"] = max(10, base + penalty + min(25, (lvl - 1) * 2))
        s["mastery_active"] = int(s.get("mastery_streak", 0) or 0) >= 3


def apply_skill_xp_after_roll(state: dict[str, Any], action_ctx: dict[str, Any], roll_pkg: dict[str, Any]) -> None:
    """Progression: award XP to domain skill after a resolved action."""
    domain = str(action_ctx.get("domain", "") or "").lower()
    if domain not in ("hacking", "social", "combat", "stealth", "evasion"):
        return
    meta = state.get("meta", {}) or {}
    day = int(meta.get("day", 1) or 1)
    s = _ensure_skill(state, domain)
    s["last_used_day"] = day

    stakes = str(action_ctx.get("stakes", "") or "").lower()
    base_xp = 3 if stakes in ("medium", "high") else 1
    outcome = str(roll_pkg.get("outcome", "") or "")
    if "Critical" in outcome:
        base_xp += 3
    elif outcome == "Success":
        base_xp += 2
    elif outcome == "Failure":
        base_xp += 1
    # No-roll actions still can give tiny XP.
    if roll_pkg.get("roll") is None:
        base_xp = 1

    xp = int(s.get("xp", 0) or 0) + base_xp
    lvl = int(s.get("level", 1) or 1)
    # Level-up curve: 20, 35, 55, 80... (approx).
    need = 15 + (lvl * 5) + (lvl * lvl)
    while xp >= need and lvl < 20:
        xp -= need
        lvl += 1
        need = 15 + (lvl * 5) + (lvl * lvl)
        s["mastery_streak"] = int(s.get("mastery_streak", 0) or 0) + 1
    s["xp"] = xp
    s["level"] = lvl
