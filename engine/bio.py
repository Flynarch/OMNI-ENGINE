from __future__ import annotations

from typing import Any


def update_bio(state: dict[str, Any], action_ctx: dict[str, Any]) -> None:
    bio = state.setdefault("bio", {})
    blood = float(bio.get("blood_volume", 5.0))
    if blood >= 4.25:
        bio["bp_state"] = "Stable"
    elif blood >= 3.5:
        bio["bp_state"] = "Low"
    elif blood >= 3.0:
        bio["bp_state"] = "Critical"
    else:
        bio["bp_state"] = "Flatline"

    # Infection x blood recovery
    recovery_mod = 0
    for inj in state.get("injuries", []):
        inf = float(inj.get("infection_pct", 0))
        if 20 <= inf <= 50:
            recovery_mod = -10
        elif inf > 50:
            bio["blood_recovery_blocked"] = True
    bio["blood_recovery_modifier_pct"] = recovery_mod

    if action_ctx.get("rested_minutes", 0) > 0:
        debt = float(bio.get("sleep_debt", 0.0))
        debt -= (action_ctx["rested_minutes"] / 90.0) * 4.0
        bio["sleep_debt"] = max(0.0, round(debt, 2))

    debt = float(bio.get("sleep_debt", 0.0))
    sanity = int(bio.get("sanity_debt", 0))
    hall = "none"
    if debt > 42 or sanity >= 80:
        hall = "visual"
    elif debt > 30 or sanity >= 60:
        hall = "auditory"
    bio["hallucination_type"] = hall
    bio["narrator_drift_state"] = "psychotic" if sanity >= 90 else "stable"
    bio["hygiene_tax_active"] = int(bio.get("hours_since_shower", 0)) > 48
    state.setdefault("flags", {})["hallucination_active"] = hall != "none"

