from __future__ import annotations

from typing import Any


def _norm(s: str) -> str:
    return str(s or "").strip().lower()


def list_occupation_templates(state: dict[str, Any]) -> list[dict[str, Any]]:
    world = state.get("world", {}) or {}
    idx = world.get("content_index", {}) or {}
    occ = idx.get("occupations", {}) if isinstance(idx, dict) else {}
    out: list[dict[str, Any]] = []
    if isinstance(occ, dict):
        for _pid, doc in occ.items():
            if not isinstance(doc, dict):
                continue
            temps = doc.get("templates", [])
            if isinstance(temps, list):
                for t in temps:
                    if isinstance(t, dict):
                        out.append(t)
    return out


def pick_occupation_template_id(state: dict[str, Any], occupation: str, background: str) -> str | None:
    blob = f"{occupation} {background}".lower()
    temps = list_occupation_templates(state)
    best: tuple[int, str] | None = None
    for t in temps:
        tid = _norm(str(t.get("id", "") or ""))
        if not tid:
            continue
        match = t.get("match", [])
        if not isinstance(match, list):
            continue
        score = 0
        for m in match[:30]:
            if isinstance(m, str) and m.strip() and m.lower() in blob:
                score += 2
        # Small preference based on obvious keywords.
        if tid in blob:
            score += 3
        if score <= 0:
            continue
        if best is None or score > best[0]:
            best = (score, tid)
    return best[1] if best else None


def apply_occupation_template(state: dict[str, Any], template_id: str) -> bool:
    """Apply starting items/skills/languages for a template. Safe to call once."""
    tid = _norm(template_id)
    if not tid:
        return False
    player = state.setdefault("player", {})
    if not isinstance(player, dict):
        return False
    # Don't re-apply.
    if str(player.get("occupation_template_id", "") or "").strip().lower() == tid and bool(player.get("occupation_template_applied", False)):
        return False

    temps = list_occupation_templates(state)
    tpl = None
    for t in temps:
        if _norm(str(t.get("id", "") or "")) == tid:
            tpl = t
            break
    if not isinstance(tpl, dict):
        return False

    inv = state.setdefault("inventory", {})
    if not isinstance(inv, dict):
        inv = {}
        state["inventory"] = inv
    bag = inv.setdefault("bag_contents", [])
    if not isinstance(bag, list):
        bag = []
        inv["bag_contents"] = bag

    world = state.setdefault("world", {})
    nearby = world.setdefault("nearby_items", [])
    if not isinstance(nearby, list):
        nearby = []
        world["nearby_items"] = nearby

    def _add_bag(item_id: str) -> None:
        iid = _norm(item_id)
        if not iid:
            return
        if iid not in [str(x).lower() for x in bag]:
            bag.append(iid)

    def _add_world(item_id: str) -> None:
        iid = _norm(item_id)
        if not iid:
            return
        if any(isinstance(x, dict) and str(x.get("id", "")).lower() == iid for x in nearby):
            return
        nearby.append({"id": iid, "name": iid})

    for it in tpl.get("items_bag", []) if isinstance(tpl.get("items_bag"), list) else []:
        if isinstance(it, str):
            _add_bag(it)
    for it in tpl.get("items_world", []) if isinstance(tpl.get("items_world"), list) else []:
        if isinstance(it, str):
            _add_world(it)

    # Skills: set starting level (1..10) by raising base+level.
    skills = state.setdefault("skills", {})
    if not isinstance(skills, dict):
        skills = {}
        state["skills"] = skills

    def _ensure_skill_row(key: str) -> dict[str, Any]:
        skills.setdefault(key, {"level": 1, "xp": 0, "base": 10, "last_used_day": 0, "mastery_streak": 0})
        row = skills.get(key)
        if not isinstance(row, dict):
            row = {"level": 1, "xp": 0, "base": 10, "last_used_day": 0, "mastery_streak": 0}
            skills[key] = row
        row.setdefault("level", 1)
        row.setdefault("xp", 0)
        row.setdefault("base", 10)
        return row

    sk = tpl.get("skills", {}) if isinstance(tpl.get("skills"), dict) else {}
    for k, lvl in sk.items():
        if not isinstance(k, str):
            continue
        try:
            lv = int(lvl or 1)
        except Exception:
            lv = 1
        lv = max(1, min(10, lv))
        row = _ensure_skill_row(_norm(k))
        # boost base slightly and set level
        row["level"] = max(int(row.get("level", 1) or 1), lv)
        row["base"] = max(int(row.get("base", 10) or 10), 10 + (lv - 1) * 2)

    # Languages: bump proficiency.
    langs = player.setdefault("languages", {})
    if not isinstance(langs, dict):
        langs = {}
        player["languages"] = langs
    lconf = tpl.get("languages", {}) if isinstance(tpl.get("languages"), dict) else {}
    for code, prof in lconf.items():
        if not isinstance(code, str):
            continue
        try:
            p = int(prof or 0)
        except Exception:
            p = 0
        p = max(0, min(100, p))
        cur = int(langs.get(code.lower(), 0) or 0)
        langs[code.lower()] = max(cur, p)

    player["occupation_template_id"] = tid
    player["occupation_template_applied"] = True
    state.setdefault("world_notes", []).append(f"[Occupation] template applied: {tid}")
    return True

