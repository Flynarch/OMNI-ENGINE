from __future__ import annotations

from typing import Any


_PRONOUN_HINTS = (
    "orang itu",
    "dia",
    "ia",
    "beliau",
    "si dia",
    "orang tadi",
    "yang tadi",
)


def _norm(s: str) -> str:
    return str(s or "").strip().lower()


def _pick_by_affiliation(state: dict[str, Any], affiliation: str) -> str | None:
    npcs = state.get("npcs", {}) or {}
    if not isinstance(npcs, dict) or not npcs:
        return None
    aff = _norm(affiliation)
    for name, data in npcs.items():
        if not isinstance(data, dict):
            continue
        if _norm(data.get("affiliation", "")) == aff:
            return str(name)
    return None


def _pick_best_focus(state: dict[str, Any]) -> str | None:
    """Fallback focus if meta.npc_focus missing.

    Prefer non-ambient NPCs, then higher fear.
    """
    npcs = state.get("npcs", {}) or {}
    if not isinstance(npcs, dict) or not npcs:
        return None
    items = list(npcs.items())

    def _key(it: tuple[str, Any]) -> tuple[int, int]:
        _name, data = it
        if not isinstance(data, dict):
            return (1, 0)
        ambient = 1 if data.get("ambient") is True else 0
        try:
            fear = int(data.get("fear", 0) or 0)
        except Exception:
            fear = 0
        return (ambient, -fear)

    items.sort(key=_key)
    return str(items[0][0]) if items else None


def apply_npc_targeting(state: dict[str, Any], action_ctx: dict[str, Any], cmd: str) -> None:
    """Populate action_ctx['targets'] using npc_focus, pronouns, and affiliation hints.

    This keeps player commands like "orang itu" stable across turns.
    """
    domain = _norm(action_ctx.get("domain", ""))
    if domain != "social":
        return

    norm_cmd = _norm(action_ctx.get("normalized_input", cmd) or cmd)

    # Ensure targets list exists.
    targets = action_ctx.get("targets")
    if not isinstance(targets, list):
        targets = []
        action_ctx["targets"] = targets

    # If player explicitly names an NPC (exact match), keep it.
    npcs = state.get("npcs", {}) or {}
    if isinstance(npcs, dict) and targets:
        # Keep only those that exist; do not invent.
        action_ctx["targets"] = [t for t in targets if isinstance(t, str) and t in npcs]
        targets = action_ctx["targets"]

    if targets:
        return

    # Affiliation hinting via text.
    if any(w in norm_cmd for w in ("polisi", "police", "petugas", "patroli", "keamanan")):
        picked = _pick_by_affiliation(state, "police")
        if picked:
            action_ctx["targets"] = [picked]
            return
    if any(w in norm_cmd for w in ("korporat", "corporate", "karyawan", "pegawai", "perusahaan")):
        picked = _pick_by_affiliation(state, "corporate")
        if picked:
            action_ctx["targets"] = [picked]
            return
    if any(w in norm_cmd for w in ("gang", "preman", "pasar gelap", "black market", "black_market")):
        picked = _pick_by_affiliation(state, "black_market")
        if picked:
            action_ctx["targets"] = [picked]
            return

    # Pronoun → npc_focus.
    if any(p in norm_cmd for p in _PRONOUN_HINTS):
        meta = state.get("meta", {}) or {}
        focus = meta.get("npc_focus")
        if isinstance(focus, str) and focus and isinstance(npcs, dict) and focus in npcs:
            action_ctx["targets"] = [focus]
            return
        best = _pick_best_focus(state)
        if best:
            action_ctx["targets"] = [best]

