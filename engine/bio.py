from __future__ import annotations

from typing import Any

from engine.balance import BALANCE, get_balance_snapshot


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
    if rested > 0:
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
