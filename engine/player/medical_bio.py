"""W2-13: pain, trauma, addiction, withdrawal — daily tick + roll modifiers (engine authority)."""
from __future__ import annotations

from engine.core.error_taxonomy import log_swallowed_exception
from typing import Any


def _bio(state: dict[str, Any]) -> dict[str, Any]:
    b = state.setdefault("bio", {})
    if not isinstance(b, dict):
        b = {}
        state["bio"] = b
    return b


def ensure_medical_bio(state: dict[str, Any]) -> dict[str, Any]:
    b = _bio(state)
    for k, dv in (
        ("pain_level", 0),
        ("trauma_stress", 0),
        ("addiction_opioid", 0),
        ("addiction_stim", 0),
        ("withdrawal_level", 0),
        ("last_substance_day", 0),
    ):
        if k not in b:
            b[k] = dv
        try:
            if k == "last_substance_day":
                b[k] = max(0, int(b.get(k, 0) or 0))
            else:
                b[k] = max(0, min(100, int(b.get(k, 0) or 0)))
        except Exception as _omni_sw_32:
            log_swallowed_exception('engine/player/medical_bio.py:32', _omni_sw_32)
            b[k] = dv
    return b


def tick_medical_daily(state: dict[str, Any], *, day: int) -> None:
    world = state.setdefault("world", {})
    if not isinstance(world, dict):
        return
    try:
        last = int(world.get("last_medical_bio_day", 0) or 0)
    except Exception as _omni_sw_43:
        log_swallowed_exception('engine/player/medical_bio.py:43', _omni_sw_43)
        last = 0
    if last == int(day):
        return
    world["last_medical_bio_day"] = int(day)
    state["world"] = world

    b = ensure_medical_bio(state)
    pain = int(b.get("pain_level", 0) or 0)
    b["pain_level"] = max(0, pain - 4)

    ts = int(b.get("trauma_stress", 0) or 0)
    b["trauma_stress"] = max(0, ts - 2)

    opi = int(b.get("addiction_opioid", 0) or 0)
    stm = int(b.get("addiction_stim", 0) or 0)

    last_sub = int(b.get("last_substance_day", 0) or 0)
    dep = max(opi, stm)
    wdraw = int(b.get("withdrawal_level", 0) or 0)
    if dep >= 25 and last_sub > 0 and int(day) - last_sub >= 2:
        wdraw = min(100, wdraw + 6 + (dep // 25))
    elif dep < 15:
        wdraw = max(0, wdraw - 8)
    else:
        wdraw = max(0, wdraw - 3)
    b["withdrawal_level"] = wdraw

    if bool(b.get("mental_spiral", False)):
        b["trauma_stress"] = min(100, int(b.get("trauma_stress", 0) or 0) + 1)


def medical_roll_modifiers(state: dict[str, Any], domain: str) -> list[tuple[str, int]]:
    """Bounded penalties; cannot grant net positive bypass."""
    ensure_medical_bio(state)
    b = state.get("bio", {}) or {}
    if not isinstance(b, dict):
        return []
    out: list[tuple[str, int]] = []
    dom = str(domain or "").lower()

    pain = int(b.get("pain_level", 0) or 0)
    if pain >= 40:
        out.append(("Pain", -min(12, pain // 10)))

    ts = int(b.get("trauma_stress", 0) or 0)
    if ts >= 45:
        out.append(("Trauma stress", -min(10, ts // 12)))

    w = int(b.get("withdrawal_level", 0) or 0)
    if w >= 35:
        pen = min(18, 6 + w // 10)
        if dom == "medical":
            out.append(("Withdrawal (medical focus)", +min(4, w // 30)))
        else:
            out.append(("Withdrawal", -pen))
    return out


def record_substance_use(state: dict[str, Any], *, kind: str) -> None:
    """Deterministic hook when stims/opioids consumed (call from commerce/medical if item tagged)."""
    meta = state.get("meta", {}) or {}
    try:
        day = int(meta.get("day", 1) or 1)
    except Exception as _omni_sw_107:
        log_swallowed_exception('engine/player/medical_bio.py:107', _omni_sw_107)
        day = 1
    b = ensure_medical_bio(state)
    b["last_substance_day"] = int(day)
    k = str(kind or "").strip().lower()
    if k in ("opioid", "opiate"):
        b["addiction_opioid"] = min(100, int(b.get("addiction_opioid", 0) or 0) + 8)
        b["withdrawal_level"] = max(0, int(b.get("withdrawal_level", 0) or 0) - 25)
    elif k == "sedative":
        b["addiction_opioid"] = min(100, int(b.get("addiction_opioid", 0) or 0) + 4)
        b["withdrawal_level"] = max(0, int(b.get("withdrawal_level", 0) or 0) - 15)
    elif k in ("stim", "stimulant", "chrome"):
        b["addiction_stim"] = min(100, int(b.get("addiction_stim", 0) or 0) + 6)
        b["withdrawal_level"] = max(0, int(b.get("withdrawal_level", 0) or 0) - 20)
