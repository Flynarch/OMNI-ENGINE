from __future__ import annotations

from typing import Any


def execute_arrest(state: dict[str, Any], *, bribery_attempt: bool = False) -> None:
    """Arrest outcome: time skip, financial penalty, hands cleared, trace reset, scene cleared."""
    meta = state.setdefault("meta", {})
    try:
        d = int(meta.get("day", 1) or 1)
    except Exception:
        d = 1
    meta["day"] = int(d + 2)
    meta["time_min"] = 480

    eco = state.setdefault("economy", {})
    eco["cash"] = 0
    try:
        bank = int(eco.get("bank", 0) or 0)
    except Exception:
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
        except Exception:
            pass
    if "r_hand_weapon" in inv:
        inv["r_hand_weapon"] = None

    tr = state.setdefault("trace", {})
    tr["trace_pct"] = 0
    tr["trace_status"] = "Ghost"
    try:
        from engine.core.factions import sync_faction_statuses_from_trace

        sync_faction_statuses_from_trace(state)
    except Exception:
        pass

    state["active_scene"] = None

    try:
        from engine.systems.property import seize_owned_vehicles_on_arrest

        seize_owned_vehicles_on_arrest(state)
    except Exception:
        pass

    msg = "[Arrest] You were arrested, fined heavily, and contraband was confiscated. Released after 2 days."
    if bribery_attempt:
        msg += " Additional charges for attempted bribery."
    state.setdefault("world_notes", []).append(msg)
