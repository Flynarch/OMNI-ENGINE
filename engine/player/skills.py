from __future__ import annotations

from typing import Any

_SKILL_KEYS = (
    "hacking",
    "social",
    "social_engineering",
    "combat",
    "stealth",
    "evasion",
    "driving",
    "medical",
    "streetwise",
    "languages",
    "negotiation",
    "management",
    "finance",
    "legal",
    "investigation",
    "operations",
    "intimidation",
)


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
    """Passive maintenance: decay + compute current (progression is applied after roll).

    W2-9 career promotion gates read `skills[*].level` from this module (deterministic).
    """
    try:
        from engine.core.character_stats import ensure_player_character_stats

        ensure_player_character_stats(state)
    except Exception:
        pass
    day = int(state.get("meta", {}).get("day", 1))
    total_decay_penalty = 0
    any_mastery_active = False
    for key in _SKILL_KEYS:
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
        total_decay_penalty += int(penalty)
        any_mastery_active = any_mastery_active or bool(s["mastery_active"])
    action_ctx["skill_decay_penalty"] = int(total_decay_penalty)
    action_ctx["mastery_active"] = bool(any_mastery_active)


def _resolve_xp_skill_key(action_ctx: dict[str, Any]) -> str | None:
    domain = str(action_ctx.get("domain", "") or "").lower()
    note = str(action_ctx.get("intent_note", "") or "").lower()
    norm = str(action_ctx.get("normalized_input", "") or "").lower()
    if domain in _SKILL_KEYS:
        if domain == "social":
            if any(k in note for k in ("negotiat", "deal", "contract", "lobby")) or any(
                k in norm for k in ("negosiasi", "deal", "kontrak", "lobi")
            ):
                return "negotiation"
            if any(k in note for k in ("intimid", "threat", "pressure")) or any(
                k in norm for k in ("intimidasi", "ancam", "paksa", "pressure")
            ):
                return "intimidation"
            if any(k in note for k in ("investigat", "intel", "case")) or any(
                k in norm for k in ("investigasi", "intel", "case", "kasus", "interogasi")
            ):
                return "investigation"
        return domain
    if domain == "other":
        if any(k in note for k in ("bank", "finance", "investment", "launder")) or any(
            k in norm for k in ("bank", "investasi", "finance", "launder", "cuci uang")
        ):
            return "finance"
        if any(k in note for k in ("legal", "law", "court", "audit")) or any(
            k in norm for k in ("legal", "hukum", "court", "audit", "izin")
        ):
            return "legal"
        if any(k in note for k in ("operations", "logistics", "supply")) or any(
            k in norm for k in ("operasi", "logistik", "supply", "rantai pasok")
        ):
            return "operations"
        if any(k in note for k in ("management", "team")) or any(
            k in norm for k in ("manajemen", "kelola tim", "manage team")
        ):
            return "management"
    return None


def apply_skill_xp_after_roll(state: dict[str, Any], action_ctx: dict[str, Any], roll_pkg: dict[str, Any]) -> None:
    """Progression: award XP to domain skill after a resolved action."""
    skill_key = _resolve_xp_skill_key(action_ctx)
    if skill_key not in _SKILL_KEYS:
        return
    meta = state.get("meta", {}) or {}
    day = int(meta.get("day", 1) or 1)
    s = _ensure_skill(state, str(skill_key))
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

    mentor_bonus = 0
    try:
        from engine.npc.relationship import get_relationship

        targets = action_ctx.get("targets") if isinstance(action_ctx.get("targets"), list) else []
        focus = str((state.get("meta", {}) or {}).get("npc_focus", "") or "").strip()
        cand: list[str] = [str(x) for x in targets if isinstance(x, str)]
        if focus:
            cand.append(focus)
        for nm in cand[:4]:
            rel = get_relationship(state, nm)
            if str(rel.get("type", "")).lower() == "mentor":
                st = int(rel.get("strength", 50) or 50)
                mentor_bonus = max(1, min(3, 1 + (st // 40)))
                break
    except Exception:
        mentor_bonus = 0

    xp = int(s.get("xp", 0) or 0) + base_xp + int(mentor_bonus)
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
