from __future__ import annotations

from engine.core.error_taxonomy import log_swallowed_exception
from typing import Any


def cleanup_dead_npcs(state: dict[str, Any]) -> None:
    """Keep dead NPCs from breaking interactions; optionally archive them per location.

    This does not delete NPCs (keeps determinism / references stable). It:
    - forces canonical dead fields (alive=False, hp=0)
    - records dead NPCs into world.locations[loc].dead_npcs for observability
    """
    npcs = state.get("npcs", {}) or {}
    if not isinstance(npcs, dict) or not npcs:
        return

    world = state.setdefault("world", {})
    locs = world.setdefault("locations", {})
    if not isinstance(locs, dict):
        locs = {}
        world["locations"] = locs

    for name, npc in list(npcs.items())[:400]:
        if not isinstance(npc, dict):
            continue
        try:
            alive = bool(npc.get("alive", True))
        except Exception as _omni_sw_28:
            log_swallowed_exception('engine/npc/dead_npc.py:28', _omni_sw_28)
            alive = True
        try:
            hp = int(npc.get("hp", 1) or 1)
        except Exception as _omni_sw_32:
            log_swallowed_exception('engine/npc/dead_npc.py:32', _omni_sw_32)
            hp = 1
        if alive and hp > 0:
            continue
        npc["alive"] = False
        npc["hp"] = 0
        npc.setdefault("dead_turn", int((state.get("meta", {}) or {}).get("turn", 0) or 0))
        npc.setdefault("dead_reason", "unknown")

        loc = str(npc.get("current_location", "") or npc.get("home_location", "") or "").strip().lower()
        if not loc:
            continue
        slot = locs.setdefault(loc, {})
        if not isinstance(slot, dict):
            continue
        grave = slot.setdefault("dead_npcs", [])
        if not isinstance(grave, list):
            grave = []
            slot["dead_npcs"] = grave
        # Dedup by name.
        if name not in [str(x) for x in grave[-80:]]:
            grave.append(str(name))
            slot["dead_npcs"] = grave[-120:]

