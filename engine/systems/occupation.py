from __future__ import annotations

from typing import Any

_TRACK_ORDER = ("normal", "kriminal", "politik", "bisnis", "underground", "militer", "sosial")


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


def get_career_paths_index(state: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Merged career path defs from frozen pack extras (last pack wins per track id)."""
    world = state.get("world", {}) or {}
    idx = world.get("content_index", {}) or {}
    occ = idx.get("occupations", {}) if isinstance(idx, dict) else {}
    paths: dict[str, dict[str, Any]] = {}
    if isinstance(occ, dict):
        for _pid, doc in occ.items():
            if not isinstance(doc, dict):
                continue
            cps = doc.get("career_paths", [])
            if not isinstance(cps, list):
                continue
            for p in cps:
                if not isinstance(p, dict):
                    continue
                pid = _norm(str(p.get("id", "") or ""))
                if pid:
                    paths[pid] = p
    return paths


def list_career_paths(state: dict[str, Any]) -> list[dict[str, Any]]:
    """Deterministic order for UI/tests."""
    ix = get_career_paths_index(state)
    return [ix[k] for k in _TRACK_ORDER if k in ix]


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
        if tid in blob:
            score += 3
        if score <= 0:
            continue
        if best is None or score > best[0]:
            best = (score, tid)
    return best[1] if best else None


def _default_career_shell() -> dict[str, Any]:
    return {
        "active_track": "normal",
        "on_break": False,
        "permanent_stain": False,
        "tracks": {},
        "events_done": [],
        "last_career_econ_day": 0,
        "cross_track_switches": 0,
    }


def ensure_career(state: dict[str, Any]) -> dict[str, Any]:
    player = state.setdefault("player", {})
    if not isinstance(player, dict):
        return _default_career_shell()
    c = player.get("career")
    if not isinstance(c, dict):
        c = _default_career_shell()
        player["career"] = c
    c.setdefault("active_track", "normal")
    c.setdefault("on_break", False)
    c.setdefault("permanent_stain", False)
    tracks = c.setdefault("tracks", {})
    if not isinstance(tracks, dict):
        tracks = {}
        c["tracks"] = tracks
    c.setdefault("events_done", [])
    if not isinstance(c.get("events_done"), list):
        c["events_done"] = []
    c.setdefault("last_career_econ_day", 0)
    c.setdefault("cross_track_switches", 0)
    ix = get_career_paths_index(state)
    for tid in _TRACK_ORDER:
        if tid not in ix:
            continue
        if tid not in tracks or not isinstance(tracks.get(tid), dict):
            tracks[tid] = {"level": 0, "rep": 22, "last_active_day": int((state.get("meta", {}) or {}).get("day", 1) or 1)}
        else:
            row = tracks[tid]
            row.setdefault("level", 0)
            row.setdefault("rep", 22)
            row.setdefault("last_active_day", int((state.get("meta", {}) or {}).get("day", 1) or 1))
    return c


def get_career_path(state: dict[str, Any], track_id: str) -> dict[str, Any] | None:
    p = get_career_paths_index(state).get(_norm(track_id))
    return p if isinstance(p, dict) else None


def _skill_level(state: dict[str, Any], key: str) -> int:
    skills = state.get("skills", {}) or {}
    if not isinstance(skills, dict):
        return 1
    row = skills.get(str(key))
    if not isinstance(row, dict):
        return 1
    try:
        return max(1, int(row.get("level", 1) or 1))
    except Exception:
        return 1


def _contact_count(state: dict[str, Any]) -> int:
    c = (state.get("world", {}) or {}).get("contacts", {})
    if not isinstance(c, dict):
        return 0
    n = 0
    for v in c.values():
        if isinstance(v, dict) and bool(v.get("is_contact")):
            n += 1
    return n


def _level_row(path: dict[str, Any], level_index: int) -> dict[str, Any] | None:
    lv = path.get("levels", [])
    if not isinstance(lv, list) or level_index < 0 or level_index >= len(lv):
        return None
    row = lv[level_index]
    return row if isinstance(row, dict) else None


def career_title_for_level(state: dict[str, Any], track_id: str, level_index: int) -> str:
    path = get_career_path(state, track_id)
    if not path:
        return "-"
    row = _level_row(path, level_index)
    if not row:
        return "-"
    return str(row.get("title", "-") or "-")


def career_daily_salary_usd(state: dict[str, Any]) -> int:
    """W2-9: daily pay scales with city_stats.min/avg wage and career pay_mult."""
    from engine.world.atlas import get_city_stats_for_travel

    ensure_career(state)
    c = state.get("player", {}).get("career", {})
    if not isinstance(c, dict):
        return 0
    if bool(c.get("on_break")):
        return 0
    at = _norm(str(c.get("active_track", "normal") or "normal"))
    path = get_career_path(state, at)
    if not path:
        return 0
    tr = (c.get("tracks", {}) or {}).get(at)
    if not isinstance(tr, dict):
        return 0
    try:
        lvl = int(tr.get("level", 0) or 0)
    except Exception:
        lvl = 0
    row = _level_row(path, lvl)
    if not row:
        return 0
    try:
        pm = float(row.get("pay_mult", 0.0) or 0.0)
    except Exception:
        pm = 0.0
    if pm <= 0.0:
        return 0
    loc = str((state.get("player", {}) or {}).get("location", "") or "").strip().lower()
    stats = get_city_stats_for_travel(state, loc) if loc else {}
    try:
        min_m = float(stats.get("min_wage_monthly_usd", 520.0) or 520.0)
    except Exception:
        min_m = 520.0
    try:
        avg_m = float(stats.get("avg_salary_monthly_usd", min_m * 1.12) or min_m)
    except Exception:
        avg_m = min_m * 1.12
    avg_m = max(min_m, avg_m)
    try:
        col = float(stats.get("cost_of_living_index", 50.0) or 50.0)
    except Exception:
        col = 50.0
    min_d = max(4.0, min_m / 22.0)
    avg_d = max(min_d, avg_m / 22.0)
    nlev = max(1, len(path.get("levels", []) or []) - 1)
    tier = min(1.0, max(0.0, float(lvl) / float(nlev)))
    base_d = min_d + (avg_d - min_d) * tier
    col_adj = 1.0 + max(-0.12, min(0.35, (col - 50.0) / 220.0))
    return int(max(0, round(base_d * pm * col_adj)))


def accrue_career_salary_and_decay(state: dict[str, Any]) -> None:
    """Once per sim-day economic cycle: salary (if working) or slow rep decay on break."""
    ensure_career(state)
    c = state.setdefault("player", {}).setdefault("career", {})
    if not isinstance(c, dict):
        return
    meta = state.get("meta", {}) or {}
    try:
        day = int(meta.get("day", 1) or 1)
    except Exception:
        day = 1
    try:
        last = int(c.get("last_career_econ_day", 0) or 0)
    except Exception:
        last = 0
    if last >= day:
        return
    c["last_career_econ_day"] = day

    tracks = c.get("tracks", {})
    if not isinstance(tracks, dict):
        return

    if bool(c.get("on_break")):
        for _tid, row in tracks.items():
            if not isinstance(row, dict):
                continue
            try:
                r = int(row.get("rep", 0) or 0)
            except Exception:
                r = 0
            row["rep"] = max(0, r - 1)
        state.setdefault("world_notes", []).append("[Career] Career break: reputasi tiap jalur merosot perlahan.")
        return

    pay = career_daily_salary_usd(state)
    if pay > 0:
        econ = state.setdefault("economy", {})
        econ["cash"] = int(econ.get("cash", 0) or 0) + int(pay)
        state.setdefault("world_notes", []).append(f"[Career] Gaji ({c.get('active_track', '')}) +${int(pay)}.")


def set_career_break(state: dict[str, Any], on: bool) -> None:
    ensure_career(state)
    c = state.setdefault("player", {}).setdefault("career", {})
    if isinstance(c, dict):
        c["on_break"] = bool(on)


def mark_permanent_career_stain(state: dict[str, Any]) -> None:
    """W2-9: criminal record / fugitive history — no command clears this."""
    ensure_career(state)
    c = state.setdefault("player", {}).setdefault("career", {})
    if isinstance(c, dict):
        c["permanent_stain"] = True


def clear_permanent_career_stain(state: dict[str, Any]) -> bool:
    """Always refuse (API exists so callers can attempt; gameplay never clears)."""
    ensure_career(state)
    _ = state
    return False


def grant_career_event(state: dict[str, Any], event_id: str) -> None:
    eid = str(event_id or "").strip()
    if not eid:
        return
    ensure_career(state)
    c = state.setdefault("player", {}).setdefault("career", {})
    if not isinstance(c, dict):
        return
    done = c.setdefault("events_done", [])
    if not isinstance(done, list):
        done = []
        c["events_done"] = done
    if eid not in done:
        done.append(eid)


def _events_has(c: dict[str, Any], event_id: str) -> bool:
    done = c.get("events_done", [])
    if not isinstance(done, list):
        return False
    return str(event_id or "").strip() in [str(x) for x in done]


def set_active_career_track(state: dict[str, Any], track_id: str) -> dict[str, Any]:
    """W2-9: cross-track allowed; other tracks lose a slice of rep."""
    ensure_career(state)
    tid = _norm(track_id)
    if not tid or get_career_path(state, tid) is None:
        return {"ok": False, "reason": "unknown_track"}
    c = state.setdefault("player", {}).setdefault("career", {})
    if not isinstance(c, dict):
        return {"ok": False, "reason": "bad_state"}
    prev = _norm(str(c.get("active_track", "") or ""))
    c["active_track"] = tid
    try:
        c["cross_track_switches"] = int(c.get("cross_track_switches", 0) or 0) + 1
    except Exception:
        c["cross_track_switches"] = 1
    penalty = 4
    tracks = c.get("tracks", {})
    if isinstance(tracks, dict) and prev and prev != tid:
        for k, row in tracks.items():
            if not isinstance(row, dict):
                continue
            if _norm(k) == tid:
                continue
            try:
                r = int(row.get("rep", 0) or 0)
            except Exception:
                r = 0
            row["rep"] = max(0, r - penalty)
        state.setdefault("world_notes", []).append(
            f"[Career] Pindah jalur aktif ke '{tid}': reputasi jalur lain terkikis karena persepsi split-focus."
        )
    return {"ok": True, "active_track": tid, "prev": prev or None, "rep_penalty_other_tracks": penalty}


def promote_career(state: dict[str, Any], track_id: str | None = None) -> dict[str, Any]:
    """Deterministic promotion gate — ignores action_ctx / intent; only state + pack data."""
    ensure_career(state)
    c = state.setdefault("player", {}).setdefault("career", {})
    if not isinstance(c, dict):
        return {"ok": False, "reason": "bad_state"}
    tid = _norm(str(track_id or c.get("active_track", "normal") or "normal"))
    path = get_career_path(state, tid)
    if not path:
        return {"ok": False, "reason": "unknown_track", "track": tid}
    tracks = c.get("tracks", {})
    if not isinstance(tracks, dict):
        return {"ok": False, "reason": "no_tracks"}
    row_t = tracks.get(tid)
    if not isinstance(row_t, dict):
        return {"ok": False, "reason": "no_track_row"}
    try:
        cur = int(row_t.get("level", 0) or 0)
    except Exception:
        cur = 0
    levels = path.get("levels", [])
    if not isinstance(levels, list):
        return {"ok": False, "reason": "bad_path"}
    next_idx = cur + 1
    if next_idx >= len(levels):
        return {"ok": False, "reason": "max_level", "track": tid}
    req = _level_row(path, next_idx)
    if not isinstance(req, dict):
        return {"ok": False, "reason": "bad_level_row"}
    stain = bool(c.get("permanent_stain"))
    if stain and bool(req.get("blocked_if_stain")):
        return {"ok": False, "reason": "permanent_stain", "track": tid}
    sk = _norm(str(req.get("skill", "streetwise") or "streetwise"))
    try:
        ms = int(req.get("min_skill", 1) or 1)
    except Exception:
        ms = 1
    try:
        mr = int(req.get("min_rep", 0) or 0)
    except Exception:
        mr = 0
    try:
        mc = int(req.get("min_contacts", 0) or 0)
    except Exception:
        mc = 0
    try:
        min_cash = int(req.get("min_cash", 0) or 0)
    except Exception:
        min_cash = 0
    ev = str(req.get("required_event", "") or "").strip()
    sl = _skill_level(state, sk)
    if sl < ms:
        return {"ok": False, "reason": "skill", "need": ms, "have": sl, "skill": sk}
    try:
        rep = int(row_t.get("rep", 0) or 0)
    except Exception:
        rep = 0
    if rep < mr:
        return {"ok": False, "reason": "rep", "need": mr, "have": rep}
    if _contact_count(state) < mc:
        return {"ok": False, "reason": "contacts", "need": mc}
    eco = state.get("economy", {}) or {}
    try:
        cash = int(eco.get("cash", 0) or 0)
    except Exception:
        cash = 0
    if cash < min_cash:
        return {"ok": False, "reason": "cash", "need": min_cash, "have": cash}
    if ev and not _events_has(c, ev):
        return {"ok": False, "reason": "event", "need": ev}
    row_t["level"] = next_idx
    meta = state.get("meta", {}) or {}
    try:
        row_t["last_active_day"] = int(meta.get("day", 1) or 1)
    except Exception:
        row_t["last_active_day"] = 1
    title = str(req.get("title", "") or "")
    state.setdefault("world_notes", []).append(f"[Career] Promosi '{tid}' → {title} (level {next_idx}).")
    return {"ok": True, "track": tid, "level": next_idx, "title": title}


def apply_occupation_template(state: dict[str, Any], template_id: str) -> bool:
    """Apply starting items/skills/languages for a template. Safe to call once."""
    tid = _norm(template_id)
    if not tid:
        return False
    player = state.setdefault("player", {})
    if not isinstance(player, dict):
        return False
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
        row["level"] = max(int(row.get("level", 1) or 1), lv)
        row["base"] = max(int(row.get("base", 10) or 10), 10 + (lv - 1) * 2)

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


def fmt_career_engine_brief(state: dict[str, Any]) -> str:
    """Single line for [ENGINE] / prompts (may include coarse numbers; narrator must not read aloud)."""
    ensure_career(state)
    c = state.get("player", {}).get("career", {})
    if not isinstance(c, dict):
        return "career=-"
    at = str(c.get("active_track", "-") or "-")
    tr = (c.get("tracks", {}) or {}).get(at)
    lvl = int((tr or {}).get("level", 0) or 0) if isinstance(tr, dict) else 0
    title = career_title_for_level(state, at, lvl)
    br = "break" if bool(c.get("on_break")) else "active"
    st = "stain" if bool(c.get("permanent_stain")) else "clean"
    pay = career_daily_salary_usd(state)
    return f"track={at} title={title} lvl={lvl} mode={br} record={st} daily_pay_usd_if_paid={pay}"
