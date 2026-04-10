from __future__ import annotations

from typing import Any


def _clamp_int(v: Any, lo: int, hi: int, default: int) -> int:
    try:
        n = int(v)
    except Exception:
        n = int(default)
    return max(lo, min(hi, n))


def _edge_for_player(world: dict[str, Any], npc_name: str) -> dict[str, Any]:
    g = world.get("social_graph") if isinstance(world.get("social_graph"), dict) else {}
    row = g.get("__player__") if isinstance(g, dict) and isinstance(g.get("__player__"), dict) else {}
    edge = row.get(str(npc_name)) if isinstance(row, dict) else {}
    return edge if isinstance(edge, dict) else {}


def _norm_type(edge_type: str, strength: int, disposition: str) -> str:
    t = str(edge_type or "").strip().lower()
    if t in ("ally", "friend") and strength >= 80:
        return "close_friend"
    if t:
        return t
    d = str(disposition or "").strip().lower()
    if d in ("devoted", "friendly"):
        return "friend"
    if d in ("hostile", "enemy"):
        return "enemy"
    return "neutral"


def get_relationship(state: dict[str, Any], npc_name: str) -> dict[str, Any]:
    npcs = state.get("npcs", {}) if isinstance(state.get("npcs"), dict) else {}
    npc = npcs.get(str(npc_name)) if isinstance(npcs, dict) else {}
    npc = npc if isinstance(npc, dict) else {}
    world = state.get("world", {}) if isinstance(state.get("world"), dict) else {}
    edge = _edge_for_player(world, str(npc_name))

    disposition = str(npc.get("disposition_label", "Neutral") or "Neutral")
    strength = _clamp_int(edge.get("strength", npc.get("disposition_score", 50)), 0, 100, 50)
    since_day = _clamp_int(edge.get("since_day", npc.get("last_contact_day", 0)), 0, 999999, 0)
    last_interaction_day = _clamp_int(edge.get("last_interaction_day", npc.get("last_contact_day", 0)), 0, 999999, 0)

    bs = npc.get("belief_summary") if isinstance(npc.get("belief_summary"), dict) else {}
    suspicion = float(_clamp_int((bs or {}).get("suspicion", 0), 0, 100, 0))
    trust = float(_clamp_int(npc.get("trust", 50), 0, 100, 50))
    rel_type = _norm_type(str(edge.get("type", "") or ""), strength, disposition)

    return {
        "type": rel_type,
        "strength": int(strength),
        "disposition": disposition,
        "trust": float(trust),
        "suspicion": float(suspicion),
        "since_day": int(since_day),
        "last_interaction_day": int(last_interaction_day),
    }


def get_top_relationships(state: dict[str, Any], *, limit: int = 3) -> list[tuple[str, dict[str, Any]]]:
    world = state.get("world", {}) if isinstance(state.get("world"), dict) else {}
    g = world.get("social_graph") if isinstance(world.get("social_graph"), dict) else {}
    row = g.get("__player__") if isinstance(g, dict) and isinstance(g.get("__player__"), dict) else {}
    if not isinstance(row, dict) or not row:
        return []
    scored: list[tuple[int, str, dict[str, Any]]] = []
    for npc_name in row.keys():
        if not isinstance(npc_name, str):
            continue
        rel = get_relationship(state, npc_name)
        rel_type = str(rel.get("type", "neutral") or "neutral").lower()
        type_boost = 12 if rel_type in ("partner", "mentor", "nemesis") else 8 if rel_type in ("close_friend", "ally", "enemy", "rival") else 0
        score = int(rel.get("strength", 50) or 50) + type_boost
        scored.append((score, npc_name, rel))
    scored.sort(key=lambda x: (-x[0], x[1].lower()))
    out: list[tuple[str, dict[str, Any]]] = []
    for _score, name, rel in scored[: max(1, int(limit))]:
        out.append((name, rel))
    return out

