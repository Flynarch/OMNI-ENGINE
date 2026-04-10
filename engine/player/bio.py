from __future__ import annotations

from typing import Any

from engine.core.balance import BALANCE, get_balance_snapshot


def _elapsed_minutes_from_ctx(action_ctx: dict[str, Any]) -> int:
    """Prefer `time_breakdown` from update_timers; else infer from action_type."""
    tb = action_ctx.get("time_breakdown")
    if isinstance(tb, list) and tb:
        total = 0
        for it in tb:
            if isinstance(it, dict):
                total += int(it.get("minutes", 0) or 0)
        return max(0, total)
    kind = str(action_ctx.get("action_type", "") or "")
    if kind == "travel":
        return max(0, int(action_ctx.get("travel_minutes", 0) or 0))
    if kind in ("rest", "sleep"):
        return max(0, int(action_ctx.get("rested_minutes", 0) or 0))
    return max(0, int(action_ctx.get("instant_minutes", 0) or 0))


_SHOWER_WORDS = ("mandi", "shower", "guyur", "bilas", "bath", "keramas", "wash up", "shampoo", "sapu badan")


def _shower_intent(action_ctx: dict[str, Any]) -> bool:
    norm = str(action_ctx.get("normalized_input", "") or "").lower()
    return any(w in norm for w in _SHOWER_WORDS)


def _mood_label(score: float) -> str:
    if score >= 80.0:
        return "great"
    if score >= 60.0:
        return "okay"
    if score >= 40.0:
        return "meh"
    if score >= 20.0:
        return "bad"
    return "broken"


def _hunger_label(score: float) -> str:
    if score <= 20.0:
        return "full"
    if score <= 40.0:
        return "okay"
    if score <= 65.0:
        return "hungry"
    if score <= 85.0:
        return "starving"
    return "critical"


def execute_sleep(state: dict[str, Any], action_ctx: dict[str, Any]) -> None:
    bio = state.setdefault("bio", {})
    if str(action_ctx.get("action_type", "") or "").lower() != "sleep":
        return
    try:
        mins = int(action_ctx.get("rested_minutes", 8 * 60) or 8 * 60)
    except Exception:
        mins = 8 * 60
    mins = max(60, min(12 * 60, mins))
    hrs = mins / 60.0
    action_ctx["rested_minutes"] = mins
    action_ctx["sleep_duration_h"] = round(hrs, 2)
    if hrs >= 7.0:
        action_ctx["sleep_quality"] = "good"
    elif hrs >= 4.0:
        action_ctx["sleep_quality"] = "okay"
    else:
        action_ctx["sleep_quality"] = "poor"
    action_ctx["hunger_rate_mult"] = 0.5

    try:
        debt = float(bio.get("sleep_debt", 0.0) or 0.0)
    except Exception:
        debt = 0.0
    if hrs >= 8.0:
        debt = 0.0
        if hrs > 8.0:
            action_ctx["sleep_mood_bonus"] = 4
    else:
        debt = max(0.0, round(debt * max(0.0, 1.0 - (hrs / 8.0)), 2))
    bio["sleep_debt"] = max(0.0, round(debt, 2))


def update_hunger(state: dict[str, Any], action_ctx: dict[str, Any]) -> None:
    bio = state.setdefault("bio", {})
    prev_label = str(bio.get("hunger_label", "full") or "full").strip().lower()
    try:
        hunger = float(bio.get("hunger", 0.0) or 0.0)
    except Exception:
        hunger = 0.0
    elapsed = _elapsed_minutes_from_ctx(action_ctx)
    try:
        mult = float(action_ctx.get("hunger_rate_mult", 1.0) or 1.0)
    except Exception:
        mult = 1.0
    mult = max(0.0, min(2.0, mult))
    hunger += (max(0, elapsed) / 60.0) * 4.0 * mult
    hunger = max(0.0, min(100.0, round(hunger, 2)))
    label = _hunger_label(hunger)
    bio["hunger"] = hunger
    bio["hunger_label"] = label
    if label == "critical" and prev_label != "critical":
        state.setdefault("world_notes", []).append(
            "[Bio] Critical hunger reached. Your body is shutting down; find food immediately."
        )


def update_mood(state: dict[str, Any], action_ctx: dict[str, Any]) -> None:
    bio = state.setdefault("bio", {})
    eco = state.setdefault("economy", {})

    try:
        raw_base = bio.get("mood_score", 50.0)
        base = float(50.0 if raw_base is None else raw_base)
    except Exception:
        base = 50.0
    score = max(0.0, min(100.0, base))

    try:
        sleep_debt = float(bio.get("sleep_debt", 0.0) or 0.0)
    except Exception:
        sleep_debt = 0.0
    score -= min(20.0, sleep_debt * 1.5)

    stress_raw = bio.get("acute_stress", False)
    if isinstance(stress_raw, bool):
        score -= 8.0 if stress_raw else 0.0
    else:
        try:
            stress = float(stress_raw or 0.0)
        except Exception:
            stress = 0.0
        score -= min(15.0, max(0.0, stress))

    try:
        sanity_debt = float(bio.get("sanity_debt", 0) or 0.0)
    except Exception:
        sanity_debt = 0.0
    score -= min(35.0, sanity_debt * 1.25)

    if bool(bio.get("hygiene_tax_active", False)):
        score -= 4.0

    try:
        cash = float(eco.get("cash", 0) or 0.0)
    except Exception:
        cash = 0.0
    if cash <= 0:
        score -= 6.0

    try:
        debt = float(eco.get("debt", 0) or 0.0)
    except Exception:
        debt = 0.0
    score -= min(18.0, max(0.0, debt) / 500.0)

    hunger = float(bio.get("hunger", 0.0) or 0.0)
    if hunger >= 86:
        score -= 25
    elif hunger >= 66:
        score -= 15
    elif hunger >= 41:
        score -= 5

    try:
        score += float(action_ctx.get("sleep_mood_bonus", 0) or 0)
    except Exception:
        pass

    _ = action_ctx

    score = max(0.0, min(100.0, round(score, 2)))
    label = _mood_label(score)

    hist_raw = bio.get("mood_history", [])
    history = list(hist_raw) if isinstance(hist_raw, list) else []
    history.append(label)
    history = history[-5:]
    recent = history[-3:]
    mental_spiral = len(recent) == 3 and all(x in ("bad", "broken") for x in recent)

    bio["mood_score"] = score
    bio["mood_label"] = label
    bio["mood_history"] = history
    bio["mental_spiral"] = bool(mental_spiral)


def update_bio(state: dict[str, Any], action_ctx: dict[str, Any]) -> None:
    """Blood pressure, infection vs recovery, sleep debt, hallucination tier, hygiene clock.

    Called once per turn after `update_timers` so `time_breakdown` is usually available.
    Thresholds come from `get_balance_snapshot` / `BAL_BIO_*` env overrides.
    """
    snap = get_balance_snapshot(state)
    bio = state.setdefault("bio", {})

    def _float_snap(key: str, default: float) -> float:
        v = snap.get(key)
        if v is None:
            return float(getattr(BALANCE, key, default))
        try:
            return float(v)
        except Exception:
            return float(default)

    def _int_snap(key: str, default: int) -> int:
        v = snap.get(key)
        if v is None:
            return int(getattr(BALANCE, key, default))
        try:
            return int(v)
        except Exception:
            return int(default)

    blood = float(bio.get("blood_volume", 5.0))
    st = _float_snap("bio_bp_stable_min", BALANCE.bio_bp_stable_min)
    lo = _float_snap("bio_bp_low_min", BALANCE.bio_bp_low_min)
    cr = _float_snap("bio_bp_critical_min", BALANCE.bio_bp_critical_min)
    if blood >= st:
        bio["bp_state"] = "Stable"
    elif blood >= lo:
        bio["bp_state"] = "Low"
    elif blood >= cr:
        bio["bp_state"] = "Critical"
    else:
        bio["bp_state"] = "Flatline"

    injuries = state.get("injuries")
    if not isinstance(injuries, list):
        injuries = []
    mid_lo = _int_snap("bio_infection_mid_low", BALANCE.bio_infection_mid_low)
    mid_hi = _int_snap("bio_infection_mid_high", BALANCE.bio_infection_mid_high)
    pen = _int_snap("bio_infection_recovery_penalty", BALANCE.bio_infection_recovery_penalty)

    max_inf = 0.0
    for inj in injuries:
        if not isinstance(inj, dict):
            continue
        try:
            max_inf = max(max_inf, float(inj.get("infection_pct", 0) or 0))
        except Exception:
            continue

    recovery_mod = 0
    blocked = False
    if mid_lo <= max_inf <= mid_hi:
        recovery_mod = -pen
    elif max_inf > mid_hi:
        blocked = True

    bio["blood_recovery_modifier_pct"] = recovery_mod
    bio["blood_recovery_blocked"] = bool(blocked)

    rest_clear = _float_snap("bio_rest_debt_clear_per_90min", BALANCE.bio_rest_debt_clear_per_90min)
    rested = int(action_ctx.get("rested_minutes", 0) or 0)
    if rested > 0 and str(action_ctx.get("action_type", "") or "").lower() != "sleep":
        debt = float(bio.get("sleep_debt", 0.0))
        debt -= (rested / 90.0) * rest_clear
        bio["sleep_debt"] = max(0.0, round(debt, 2))

    debt = float(bio.get("sleep_debt", 0.0))
    sanity = int(bio.get("sanity_debt", 0) or 0)
    sd_vis = _float_snap("bio_sleep_debt_visual", BALANCE.bio_sleep_debt_visual)
    sd_aud = _float_snap("bio_sleep_debt_audio", BALANCE.bio_sleep_debt_audio)
    sv = _int_snap("bio_sanity_visual", BALANCE.bio_sanity_visual)
    sa = _int_snap("bio_sanity_audio", BALANCE.bio_sanity_audio)
    sp = _int_snap("bio_sanity_psychotic", BALANCE.bio_sanity_psychotic)

    hall = "none"
    if debt > sd_vis or sanity >= sv:
        hall = "visual"
    elif debt > sd_aud or sanity >= sa:
        hall = "auditory"
    bio["hallucination_type"] = hall
    bio["narrator_drift_state"] = "psychotic" if sanity >= sp else "stable"

    h_tax = _int_snap("bio_hygiene_hours_tax", BALANCE.bio_hygiene_hours_tax)
    hrs = float(bio.get("hours_since_shower", 0) or 0)
    if _shower_intent(action_ctx):
        bio["hours_since_shower"] = 0.0
    else:
        mins = _elapsed_minutes_from_ctx(action_ctx)
        hrs += mins / 60.0
        bio["hours_since_shower"] = round(hrs, 2)

    bio["hygiene_tax_active"] = float(bio.get("hours_since_shower", 0) or 0) > float(h_tax)

    state.setdefault("flags", {})["hallucination_active"] = hall != "none"
    execute_sleep(state, action_ctx)
    update_hunger(state, action_ctx)
    update_mood(state, action_ctx)
