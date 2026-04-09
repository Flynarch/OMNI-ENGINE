"""Social diffusion system with information distortion.

This module provides:
- Information distortion when gossip spreads between NPCs
- Track what each NPC knows about the player
- Social graph with trust/reputation decay
- NPC-to-NPC rumor propagation
"""
from __future__ import annotations

import hashlib
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


def record_player_info(state: dict[str, Any], npc_name: str, info_category: str, original_text: str) -> None:
    """Record what an NPC knows about the player."""
    mem = ensure_social_memory(state)
    
    # Get or create NPC's knowledge about player
    npc_knowledge = mem.setdefault(npc_name, {
        "known_categories": {},
        "trust_in_player": 50,  # Base trust
        "last_update_turn": 0,
    })
    
    meta = state.get("meta", {}) or {}
    turn = int(meta.get("turn", 0) or 0)
    
    # Record the info
    category_info = npc_knowledge.setdefault("known_categories", {})
    cat_entry = category_info.setdefault(info_category, {
        "count": 0,
        "latest_text": "",
        "distortion_level": 0,
        "trust_decay": 0,
    })
    
    cat_entry["count"] = cat_entry.get("count", 0) + 1
    cat_entry["latest_text"] = original_text
    cat_entry["last_turn"] = turn
    
    # Update trust based on severity
    severity = INFO_CATEGORIES.get(info_category, {}).get("severity", 3)
    trust_delta = -severity  # Negative info reduces trust
    current_trust = npc_knowledge.get("trust_in_player", 50)
    npc_knowledge["trust_in_player"] = _clamp(current_trust + trust_delta, 0, 100)
    npc_knowledge["last_update_turn"] = turn


def distort_information(state: dict[str, Any], npc_source: str, npc_target: str, info_category: str, original_text: str) -> str:
    """Distort information as it spreads from one NPC to another."""
    meta = state.get("meta", {}) or {}
    turn = int(meta.get("turn", 0) or 0)
    day = int(meta.get("day", 1) or 1)
    
    # Get source NPC's trust
    mem = ensure_social_memory(state)
    source_knowledge = mem.get(npc_source, {})
    source_trust = source_knowledge.get("trust_in_player", 50)
    
    # Get target NPC's existing knowledge
    target_knowledge = mem.get(npc_target, {})
    target_trust = target_knowledge.get("trust_in_player", 50)
    
    # Calculate distortion probability
    # Low trust = more distortion
    trust_factor = (source_trust + target_trust) / 200  # 0 to 1
    distortion_chance = 1 - trust_factor  # Inverse: 0% to 100%
    
    # Deterministic roll for this transfer
    r = _h32(day, turn, npc_source, npc_target, info_category, "distort")
    roll = r % 100
    
    if roll > distortion_chance * 100:
        # No distortion - pass through
        return original_text
    
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
            if distortion_chance > 0.5:
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
    """Propagate a rumor to connected NPCs with distortion."""
    meta = state.get("meta", {}) or {}
    turn = int(meta.get("turn", 0) or 0)
    day = int(meta.get("day", 1) or 1)
    
    world = state.get("world", {}) or {}
    social_graph = world.get("social_graph", {}) or {}
    mem = ensure_social_memory(state)
    
    # Get origin NPC's connections
    origin_edges = social_graph.get("__player__", {}).get(origin_npc, {})
    if not isinstance(origin_edges, dict):
        origin_edges = {}
    
    # Find NPCs connected to origin (contacts, allies, etc.)
    npcs = state.get("npcs", {}) or {}
    connections: list[dict[str, Any]] = []
    
    for npc_name, npc_data in list(npcs.items())[:100]:
        if npc_name == origin_npc:
            continue
        
        npc_edge = social_graph.get("__player__", {}).get(npc_name, {})
        edge_type = npc_edge.get("type", "neutral") if isinstance(npc_edge, dict) else "neutral"
        edge_strength = npc_edge.get("strength", 50) if isinstance(npc_edge, dict) else 50
        
        # Only propagate to close connections
        if edge_type in ("ally", "friend", "lover") or edge_strength >= 70:
            connections.append({
                "npc": npc_name,
                "edge_type": edge_type,
                "strength": edge_strength,
            })
    
    # Limit propagation (bounded)
    max_hops = 2
    if hop >= max_hops:
        return []
    
    propagated: list[dict[str, Any]] = []
    
    for conn in connections[:8]:  # Max 8 recipients per hop
        npc_target = conn["npc"]
        
        # Distort the rumor
        distorted = distort_information(state, origin_npc, npc_target, info_category, rumor_text)
        
        # Record what target now knows
        if npc_target not in mem:
            mem[npc_target] = {"known_categories": {}, "trust_in_player": 50}
        
        cat_info = mem[npc_target].setdefault("known_categories", {})
        cat_info[info_category] = {
            "count": cat_info.get(info_category, {}).get("count", 0) + 1,
            "latest_text": distorted,
            "distortion_level": cat_info.get(info_category, {}).get("distortion_level", 0) + 1,
            "last_turn": turn,
            "source": origin_npc,
            "hop": hop + 1,
        }
        
        # Reduce trust slightly with each hop
        trust = mem[npc_target].get("trust_in_player", 50)
        mem[npc_target]["trust_in_player"] = _clamp(trust - 5, 0, 100)
        
        propagated.append({
            "from": origin_npc,
            "to": npc_target,
            "original": rumor_text,
            "distorted": distorted,
            "hop": hop + 1,
        })
    
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
            categories.append({
                "category": cat,
                "count": info.get("count", 0),
                "latest": info.get("latest_text", ""),
                "distortion": info.get("distortion_level", 0),
                "hop": info.get("hop", 0),
            })
    
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
    
    # Record in origin NPC's knowledge
    record_player_info(state, origin_npc, info_category, rumor_text)
    
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
