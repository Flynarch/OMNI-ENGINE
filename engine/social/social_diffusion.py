"""Social diffusion system with information distortion.

This module provides:
- Information distortion when gossip spreads between NPCs
- Track what each NPC knows about the player
- Social graph with trust/reputation decay
- NPC-to-NPC rumor propagation
"""
from __future__ import annotations

import hashlib
import os
from typing import Any


def _h32(*parts: Any) -> int:
    """Deterministic hash for social diffusion."""
    s = "|".join(str(p) for p in parts)
    h = hashlib.md5(s.encode("utf-8", errors="ignore")).hexdigest()
    return int(h[:8], 16)


def _clamp(v: int, lo: int, hi: int) -> int:
    return max(lo, min(hi, int(v)))


# Information categories that can be distorted
INFO_CATEGORIES = {
    "combat": {
        "severity": 5,  # How dangerous this info is
        "keywords": ["weapon", "shoot", "kill", "attack", "fight", "gun", "blade"],
        "distortions": {
            "weapon": ["armed", "dangerous", "violent", "mercenary"],
            "shoot": ["fires shots", "violent", "reckless", "dangerous"],
            "kill": ["assassin", "murderer", "cold-blooded", "killer"],
            "attack": ["aggressive", "violent", "threat"],
        },
    },
    "stealth": {
        "severity": 4,
        "keywords": ["sneak", "hide", "secret", "suspicious", "lurk", "shadow"],
        "distortions": {
            "sneak": ["shady", "suspicious", "untrustworthy", "creepy"],
            "hide": ["has secrets", "something to hide", "mysterious"],
            "secret": ["dangerous secrets", "mysterious", "connected"],
            "suspicious": ["under investigation", "wanted", "criminal"],
        },
    },
    "wealth": {
        "severity": 3,
        "keywords": ["money", "cash", "rich", "expensive", "gold", "pay"],
        "distortions": {
            "money": ["loaded", "has cash", "good for paying", "wealthy"],
            "rich": ["loaded", "expensive taste", "high roller"],
            "expensive": ["show-off", "high roller", "wealthy"],
        },
    },
    "social": {
        "severity": 2,
        "keywords": ["friend", "contact", "talk", "meet", "relationship"],
        "distortions": {
            "friend": ["has connections", "well-connected", "network"],
            "contact": ["has contacts", "knows people", "information broker"],
            "relationship": ["close with", "associated with", "loyal to"],
        },
    },
    "hack": {
        "severity": 4,
        "keywords": ["hack", "computer", "system", "data", "breach", "cyber"],
        "distortions": {
            "hack": ["hacker", "cyber criminal", "data thief", "tech expert"],
            "computer": ["tech-savvy", "has skills", "computer expert"],
            "data": ["has information", "data broker", "information trader"],
        },
    },
}


def ensure_social_memory(state: dict[str, Any]) -> dict[str, Any]:
    """Ensure social memory store exists."""
    world = state.setdefault("world", {})
    mem = world.setdefault("social_memory", {})
    if not isinstance(mem, dict):
        mem = {}
        world["social_memory"] = mem
    return mem


def _norm_key(s: Any) -> str:
    return str(s or "").strip().lower()


def npc_social_neighbor_ids(state: dict[str, Any], origin_npc: str) -> list[str]:
    """NPC-to-NPC social neighbors: explicit ``social_graph[origin][other]`` edges plus derived ties.

    Derived ties (when no explicit row or to fill the graph): same non-empty affiliation,
    or same current/home location. Deterministic sorted order.
    """
    origin_npc = str(origin_npc or "").strip()
    npcs = state.get("npcs", {}) or {}
    if not isinstance(npcs, dict) or origin_npc not in npcs:
        return []
    o = npcs.get(origin_npc)
    if not isinstance(o, dict):
        return []
    if o.get("alive") is False:
        try:
            if int(o.get("hp", 1) or 1) <= 0:
                return []
        except Exception:
            return []

    world = state.get("world", {}) or {}
    g = world.get("social_graph", {}) or {}
    if not isinstance(g, dict):
        g = {}

    found: set[str] = set()

    row = g.get(origin_npc)
    if isinstance(row, dict):
        for other, edge in row.items():
            if str(other).startswith("__"):
                continue
            if other == origin_npc:
                continue
            if not isinstance(npcs.get(other), dict):
                continue
            if isinstance(edge, dict):
                try:
                    st = int(edge.get("strength", 55) or 55)
                except Exception:
                    st = 55
                if st < 25:
                    continue
            found.add(str(other))

    aff_o = _norm_key(o.get("affiliation"))
    loc_o = _norm_key(o.get("current_location")) or _norm_key(o.get("home_location"))

    for nid, nd in npcs.items():
        if not isinstance(nid, str) or not isinstance(nd, dict):
            continue
        if nid == origin_npc:
            continue
        if nd.get("alive") is False:
            continue
        try:
            if int(nd.get("hp", 1) or 1) <= 0:
                continue
        except Exception:
            continue
        if nid in found:
            continue
        aff_n = _norm_key(nd.get("affiliation"))
        loc_n = _norm_key(nd.get("current_location")) or _norm_key(nd.get("home_location"))
        if aff_o and aff_n and aff_o == aff_n:
            found.add(nid)
        elif loc_o and loc_n and loc_o == loc_n:
            found.add(nid)

    return sorted(found)


def record_player_info(
    state: dict[str, Any],
    npc_name: str,
    info_category: str,
    original_text: str,
    *,
    confidence: float | None = None,
    apply_trust_delta: bool = True,
) -> None:
    """Record what an NPC knows about the player."""
    mem = ensure_social_memory(state)

    # Get or create NPC's knowledge about player
    npc_knowledge = mem.setdefault(
        npc_name,
        {
            "known_categories": {},
            "trust_in_player": 50,  # Base trust
            "last_update_turn": 0,
        },
    )

    meta = state.get("meta", {}) or {}
    turn = int(meta.get("turn", 0) or 0)

    # Record the info
    category_info = npc_knowledge.setdefault("known_categories", {})
    cat_entry = category_info.setdefault(
        info_category,
        {
            "count": 0,
            "latest_text": "",
            "distortion_level": 0,
            "trust_decay": 0,
            "confidence": 0.75,
        },
    )

    cat_entry["count"] = cat_entry.get("count", 0) + 1
    cat_entry["latest_text"] = original_text
    cat_entry["last_turn"] = turn
    if confidence is not None:
        try:
            cf = float(confidence)
        except Exception:
            cf = 0.75
        cat_entry["confidence"] = max(0.05, min(0.98, cf))
    elif "confidence" not in cat_entry:
        cat_entry["confidence"] = 0.78

    if apply_trust_delta:
        # Update trust based on severity
        severity = INFO_CATEGORIES.get(info_category, {}).get("severity", 3)
        trust_delta = -severity  # Negative info reduces trust
        current_trust = npc_knowledge.get("trust_in_player", 50)
        npc_knowledge["trust_in_player"] = _clamp(current_trust + trust_delta, 0, 100)
    npc_knowledge["last_update_turn"] = turn


def distort_information(
    state: dict[str, Any],
    npc_source: str,
    npc_target: str,
    info_category: str,
    original_text: str,
    *,
    incoming_confidence: float | None = None,
) -> str:
    """Distort information as it spreads from one NPC to another."""
    meta = state.get("meta", {}) or {}
    turn = int(meta.get("turn", 0) or 0)
    day = int(meta.get("day", 1) or 1)

    # Get source NPC's trust
    mem = ensure_social_memory(state)
    source_knowledge = mem.get(npc_source, {})
    if not isinstance(source_knowledge, dict):
        source_knowledge = {}
    source_trust = source_knowledge.get("trust_in_player", 50)

    # Get target NPC's existing knowledge
    target_knowledge = mem.get(npc_target, {})
    if not isinstance(target_knowledge, dict):
        target_knowledge = {}
    target_trust = target_knowledge.get("trust_in_player", 50)

    # Calculate distortion probability — low NPC trust + low source confidence = more garbling
    trust_factor = (source_trust + target_trust) / 200.0
    try:
        ic = float(incoming_confidence) if incoming_confidence is not None else 0.72
    except Exception:
        ic = 0.72
    ic = max(0.05, min(0.98, ic))
    p_distort = min(0.92, (1.0 - trust_factor) * 0.55 + (1.0 - ic) * 0.42)

    # Deterministic roll for this transfer
    r = _h32(day, turn, npc_source, npc_target, info_category, "distort")
    roll = r % 100

    if roll > p_distort * 100:
        # No distortion - pass through (maybe light trim)
        return original_text.strip()

    # Distort the information
    cat_info = INFO_CATEGORIES.get(info_category, {})
    distortions = cat_info.get("distortions", {})

    # Find keywords in original text
    text_lower = original_text.lower()
    for keyword, distorts in distortions.items():
        if keyword in text_lower:
            # Pick a distortion based on deterministic roll
            d_idx = (r >> 4) % len(distorts)
            distorted = distorts[d_idx]

            # Add "they say" framing if high distortion
            if p_distort > 0.5:
                return f"Orang bilang {distorted}."

            return f"{distorted}."

    # Default distortion if no keyword match
    severities = {
        "combat": "berbahaya",
        "stealth": "mencurigakan",
        "wealth": "kaya",
        "social": "terkoneksi",
        "hack": "ahli komputer",
    }
    return f"Menurut orang, {severities.get(info_category, 'bermasalah')}."


def propagate_rumor(state: dict[str, Any], origin_npc: str, rumor_text: str, info_category: str, hop: int = 0) -> list[dict[str, Any]]:
    """Propagate a rumor to NPC social neighbors (not player-edge proxies) with distortion + confidence decay."""
    meta = state.get("meta", {}) or {}
    turn = int(meta.get("turn", 0) or 0)
    day = int(meta.get("day", 1) or 1)

    mem = ensure_social_memory(state)

    # Source confidence: from social_memory if present, else stable default from text hop depth
    src_k = mem.get(origin_npc, {}) if isinstance(mem.get(origin_npc), dict) else {}
    src_cats = src_k.get("known_categories", {}) if isinstance(src_k.get("known_categories"), dict) else {}
    src_cat = src_cats.get(info_category, {}) if isinstance(src_cats.get(info_category), dict) else {}
    try:
        src_conf = float(src_cat.get("confidence", 0.78))
    except Exception:
        src_conf = 0.78
    src_conf = max(0.08, min(0.98, src_conf))

    neighbors = npc_social_neighbor_ids(state, origin_npc)
    if not neighbors:
        return []

    # Limit propagation (bounded); default 3 hops for richer NPC-to-NPC spread (W2+).
    try:
        max_hops = int(os.getenv("OMNI_SOCIAL_DIFFUSION_MAX_HOPS", "3") or 3)
    except ValueError:
        max_hops = 3
    max_hops = max(2, min(6, max_hops))
    if hop >= max_hops:
        return []

    try:
        per_hop = int(os.getenv("OMNI_SOCIAL_DIFFUSION_PER_HOP", "5") or 5)
    except ValueError:
        per_hop = 5
    per_hop = max(1, min(10, per_hop))

    # Deterministic priority order (not alphabetical bias): hash tie-breaker
    scored = sorted(
        neighbors,
        key=lambda nid: (_h32(day, turn, origin_npc, nid, "npc_diff"), nid),
    )
    targets = scored[:per_hop]

    propagated: list[dict[str, Any]] = []

    for npc_target in targets:
        incoming_conf = max(0.06, min(0.97, src_conf * 0.86 - 0.035 - hop * 0.02))
        distorted = distort_information(
            state,
            origin_npc,
            npc_target,
            info_category,
            rumor_text,
            incoming_confidence=incoming_conf,
        )

        mem.setdefault(
            npc_target,
            {"known_categories": {}, "trust_in_player": 50, "last_update_turn": 0},
        )
        cat_info = mem[npc_target].setdefault("known_categories", {})
        prev = cat_info.get(info_category, {})
        prev_count = prev.get("count", 0) if isinstance(prev, dict) else 0
        prev_dist = prev.get("distortion_level", 0) if isinstance(prev, dict) else 0

        cat_info[info_category] = {
            "count": int(prev_count) + 1,
            "latest_text": distorted,
            "distortion_level": int(prev_dist) + 1,
            "last_turn": turn,
            "source": origin_npc,
            "hop": hop + 1,
            "confidence": round(incoming_conf, 4),
        }

        trust = mem[npc_target].get("trust_in_player", 50)
        mem[npc_target]["trust_in_player"] = _clamp(trust - 4, 0, 100)

        propagated.append(
            {
                "from": origin_npc,
                "to": npc_target,
                "original": rumor_text,
                "distorted": distorted,
                "hop": hop + 1,
                "confidence": incoming_conf,
            }
        )

    return propagated


def get_npc_knowledge_summary(state: dict[str, Any], npc_name: str) -> dict[str, Any]:
    """Get what an NPC knows about the player."""
    mem = ensure_social_memory(state)
    knowledge = mem.get(npc_name, {})

    if not knowledge:
        return {"known": False, "categories": []}

    categories = []
    known_cats = knowledge.get("known_categories", {})
    for cat, info in known_cats.items():
        if isinstance(info, dict):
            categories.append(
                {
                    "category": cat,
                    "count": info.get("count", 0),
                    "latest": info.get("latest_text", ""),
                    "distortion": info.get("distortion_level", 0),
                    "hop": info.get("hop", 0),
                    "confidence": info.get("confidence", 0.75),
                }
            )

    return {
        "known": True,
        "trust": knowledge.get("trust_in_player", 50),
        "categories": categories,
    }


def apply_social_decays(state: dict[str, Any]) -> None:
    """Decay social memory and trust over time (called each turn)."""
    meta = state.get("meta", {}) or {}
    turn = int(meta.get("turn", 0) or 0)
    
    mem = ensure_social_memory(state)
    decay_rate = 0.1  # Trust decays 0.1 per turn
    
    decayed_count = 0
    for npc_name, knowledge in list(mem.items()):
        if not isinstance(knowledge, dict):
            continue
        
        # Decay trust
        trust = knowledge.get("trust_in_player", 50)
        new_trust = trust - decay_rate
        if new_trust < 50:  # Don't decay below neutral
            new_trust = 50.0
        knowledge["trust_in_player"] = new_trust
        
        # Age categories - reduce distortion level
        cats = knowledge.get("known_categories", {})
        if isinstance(cats, dict):
            for cat, info in cats.items():
                if isinstance(info, dict):
                    dl = info.get("distortion_level", 0)
                    if dl > 0 and turn % 10 == 0:  # Every 10 turns
                        info["distortion_level"] = max(0, dl - 1)
        
        decayed_count += 1
    
    if decayed_count > 0:
        world = state.setdefault("world", {})
        world["social_memory"] = mem


def queue_rumor_about_player(state: dict[str, Any], rumor_text: str, info_category: str, origin_npc: str | None = None) -> None:
    """Queue a rumor to spread through the social network."""
    meta = state.get("meta", {}) or {}
    turn = int(meta.get("turn", 0) or 0)
    day = int(meta.get("day", 1) or 1)
    
    # Determine origin NPC
    if not origin_npc:
        npcs = state.get("npcs", {}) or {}
        if npcs:
            # Pick a random NPC deterministically
            names = list(npcs.keys())
            if names:
                idx = _h32(day, turn, "origin") % len(names)
                origin_npc = names[idx]
    
    if not origin_npc:
        return
    
    # Record in origin NPC's knowledge (fresh signal — higher confidence)
    record_player_info(state, origin_npc, info_category, rumor_text, confidence=0.84, apply_trust_delta=True)
    
    # Propagate first hop
    propagated = propagate_rumor(state, origin_npc, rumor_text, info_category, hop=0)
    
    # Queue subsequent hops as events
    pending_hops = state.setdefault("pending_events", [])
    for p in propagated:
        pending_hops.append({
            "event_type": "social_diffusion_hop",
            "due_day": day,
            "due_time": 0,  # Immediate next turn
            "triggered": False,
            "payload": {
                "from_npc": p["from"],
                "to_npc": p["to"],
                "rumor": p["distorted"],
                "category": info_category,
                "hop": p["hop"],
            },
        })


def get_social_threat_summary(state: dict[str, Any]) -> dict[str, Any]:
    """Get a summary of social threats (NPCs who know dangerous info)."""
    mem = ensure_social_memory(state)
    threats: list[dict[str, Any]] = []
    
    for npc_name, knowledge in mem.items():
        if not isinstance(knowledge, dict):
            continue
        
        trust = knowledge.get("trust_in_player", 50)
        if trust >= 60:
            continue  # Friendly NPCs aren't threats
        
        cats = knowledge.get("known_categories", {})
        dangerous_cats = ["combat", "hack", "stealth"]
        known_dangerous = []
        
        for cat in dangerous_cats:
            if cat in cats:
                known_dangerous.append(cat)
        
        if known_dangerous:
            threats.append({
                "npc": npc_name,
                "trust": trust,
                "known_categories": known_dangerous,
                "risk_level": 5 - _clamp(int(trust / 20), 0, 4),
            })
    
    # Sort by risk
    threats.sort(key=lambda x: x["risk_level"], reverse=True)
    return {
        "threat_count": len(threats),
        "top_threats": threats[:5],
    }
