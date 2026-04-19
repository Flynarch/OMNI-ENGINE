from __future__ import annotations

from typing import Any

from engine.core.error_taxonomy import log_swallowed_exception
from engine.core.factions import sync_faction_statuses_from_trace
from engine.systems.judicial import apply_arrest_sentence
from engine.systems.property import seize_owned_vehicles_on_arrest


def execute_arrest(state: dict[str, Any], *, bribery_attempt: bool = False) -> None:
    """Arrest outcome: financial penalty, hands cleared, trace reset, scene cleared, W2-12 sentence + seized bag."""
    meta = state.setdefault("meta", {})
    try:
        d = int(meta.get("day", 1) or 1)
    except Exception as _omni_sw_11:
        log_swallowed_exception('engine/systems/arrest.py:11', _omni_sw_11)
        d = 1
    # Time skip (legacy) + W2-12 sentence timer from post-skip calendar day.
    meta["day"] = int(d + 2)
    meta["time_min"] = 480

    eco = state.setdefault("economy", {})
    eco["cash"] = 0
    try:
        bank = int(eco.get("bank", 0) or 0)
    except Exception as _omni_sw_21:
        log_swallowed_exception('engine/systems/arrest.py:21', _omni_sw_21)
        bank = 0
    eco["bank"] = int(max(0, (bank * 85) // 100))

    inv = state.setdefault("inventory", {})
    if not isinstance(inv, dict):
        inv = {}
        state["inventory"] = inv
    inv.setdefault("r_hand", "-")
    inv.setdefault("l_hand", "-")
    inv["r_hand"] = "-"
    inv["l_hand"] = "-"
    aw = str(inv.get("active_weapon_id", "") or "").strip()
    inv["active_weapon_id"] = ""
    if aw and isinstance(inv.get("weapons"), dict) and aw in inv["weapons"]:
        try:
            del inv["weapons"][aw]
        except Exception as _omni_sw_38:
            log_swallowed_exception('engine/systems/arrest.py:38', _omni_sw_38)
    if "r_hand_weapon" in inv:
        inv["r_hand_weapon"] = None

    tr = state.setdefault("trace", {})
    tr["trace_pct"] = 0
    tr["trace_status"] = "Ghost"
    try:
        sync_faction_statuses_from_trace(state)
    except Exception as _omni_sw_50:
        log_swallowed_exception('engine/systems/arrest.py:50', _omni_sw_50)
    state["active_scene"] = None

    try:
        seize_owned_vehicles_on_arrest(state)
    except Exception as _omni_sw_59:
        log_swallowed_exception('engine/systems/arrest.py:59', _omni_sw_59)
    try:
        apply_arrest_sentence(state, sentence_days=3, bribery_attempt=bribery_attempt)
    except Exception as _omni_sw_66:
        log_swallowed_exception('engine/systems/arrest.py:66', _omni_sw_66)
    msg = "[Arrest] Booked. Sentence active — travel restricted until release day."
    if bribery_attempt:
        msg += " Extra count: attempted bribery."
    state.setdefault("world_notes", []).append(msg)
