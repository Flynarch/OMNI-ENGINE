from __future__ import annotations

from engine.core.error_taxonomy import log_swallowed_exception
from typing import Any

from engine.world.atlas import ensure_location_profile
from engine.core.language import _split_lang, player_language_proficiency
from engine.world.time_model import sim_year_from_state, tech_epoch_for_year


def _clamp(v: int, lo: int, hi: int) -> int:
    return max(lo, min(hi, int(v)))


def can_learn_here(state: dict[str, Any], lang_code: str) -> bool:
    loc = str((state.get("player", {}) or {}).get("location", "") or "").strip().lower()
    if not loc:
        return False
    prof = ensure_location_profile(state, loc)
    ll = str((prof.get("language") if isinstance(prof, dict) else "") or "").lower()
    return lang_code.lower() in _split_lang(ll)


def learn_language(
    state: dict[str, Any],
    lang_code: str,
    *,
    method: str = "class",
    preview: bool = False,
) -> dict[str, Any]:
    """Apply language learning.

    Returns {ok, minutes, cash_cost, delta, new_prof, reason}. If preview=True, does not mutate state.
    """
    code = str(lang_code or "").strip().lower()
    if not code:
        return {"ok": False, "reason": "missing_code", "minutes": 0, "cash_cost": 0, "delta": 0}

    method_n = str(method or "class").strip().lower()
    if method_n not in ("class", "book", "immersion"):
        method_n = "class"

    profs = player_language_proficiency(state)
    cur = int(profs.get(code, 0) or 0)

    inv = state.get("inventory", {}) or {}
    bag = inv.get("bag_contents", []) or []
    has_phrasebook = isinstance(bag, list) and any(str(x).lower() == "phrasebook" for x in bag)

    year = sim_year_from_state(state)
    world = state.get("world", {}) or {}
    try:
        tp = float((world.get("tech_progress", 0.0) if isinstance(world, dict) else 0.0) or 0.0)
    except Exception as _omni_sw_53:
        log_swallowed_exception('engine/player/language_learning.py:53', _omni_sw_53)
        tp = 0.0
    epoch = tech_epoch_for_year(year, tech_progress=tp)

    # Base costs/time/deltas (MVP; balance knobs can be added later).
    if method_n == "class":
        minutes = 180
        cash_cost = 200
        delta = 8
    elif method_n == "book":
        minutes = 120
        cash_cost = 20
        delta = 4
        if not has_phrasebook:
            return {"ok": False, "reason": "need_phrasebook", "minutes": 0, "cash_cost": 0, "delta": 0}
    else:  # immersion
        minutes = 240
        cash_cost = 0
        delta = 6
        if not can_learn_here(state, code):
            return {"ok": False, "reason": "not_in_language_region", "minutes": 0, "cash_cost": 0, "delta": 0}

    # Earlier eras make self-learning slower (less media exposure), but still possible.
    if epoch.translator_level == "none":
        delta = max(2, int(delta * 0.75))

    new_prof = _clamp(cur + delta, 0, 100)

    if not preview:
        # Apply to state.
        p = state.setdefault("player", {})
        langs = p.setdefault("languages", {})
        if not isinstance(langs, dict):
            langs = {}
            p["languages"] = langs
        langs[code] = int(new_prof)

        # Optional: bump a general 'languages' skill slightly (if present).
        sk = state.setdefault("skills", {})
        if isinstance(sk, dict):
            row = sk.setdefault("languages", {"level": 1, "xp": 0, "base": 10, "last_used_day": 0, "mastery_streak": 0})
            if isinstance(row, dict):
                row["xp"] = int(row.get("xp", 0) or 0) + 2

    return {
        "ok": True,
        "reason": "ok",
        "method": method_n,
        "minutes": int(minutes),
        "cash_cost": int(cash_cost),
        "delta": int(new_prof - cur),
        "new_prof": int(new_prof),
        "year": int(year),
    }

