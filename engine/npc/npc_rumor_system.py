"""NPC rumor system integration.

This module connects social diffusion to NPC behavior:
- Detects when player actions generate gossip-worthy info
- Triggers social diffusion system
- Integrates with NPC emotions for rumor spread
- Reputation gossip: deterministic spread within faction or shared location
"""
from __future__ import annotations

import hashlib
from typing import Any


def _h32(*parts: Any) -> int:
    s = "|".join(str(p) for p in parts)
    return int(hashlib.md5(s.encode("utf-8", errors="ignore")).hexdigest()[:8], 16)


def _npc_suspicion(npc: dict[str, Any]) -> int:
    bs = npc.get("belief_summary")
    if not isinstance(bs, dict):
        return 0
    try:
        return max(0, min(100, int(bs.get("suspicion", 0) or 0)))
    except Exception:
        return 0


def _is_gossip_source(npc: dict[str, Any]) -> bool:
    tags = npc.get("belief_tags", [])
    if isinstance(tags, list) and "Deep_Grudge" in tags:
        return True
    return _npc_suspicion(npc) > 70


def propagate_reputation(state: dict[str, Any], *, max_spreads_per_turn: int = 8) -> int:
    """Deterministic gossip: qualifying NPCs have a 10% chance to raise peers' suspicion.

    Source NPC must have ``Deep_Grudge`` or ``belief_summary.suspicion`` > 70.
    Target must share ``affiliation`` (non-empty, case-insensitive) or same ``current_location``/``home_location``.

    Sets ``npc[rumor_influence_turn]`` on the target to ``meta.turn`` when suspicion rises (for narrative [RUMOR]).
    Returns number of successful spreads this call.
    """
    npcs = state.get("npcs", {}) or {}
    if not isinstance(npcs, dict) or len(npcs) < 2:
        return 0
    meta = state.get("meta", {}) or {}
    turn = int(meta.get("turn", 0) or 0)
    seed = str(meta.get("world_seed", "") or "")
    world_notes = state.setdefault("world_notes", [])

    # Stable iteration order
    items = sorted((str(k), v) for k, v in npcs.items() if isinstance(v, dict))
    spreads = 0

    for a_id, a in items:
        if spreads >= max_spreads_per_turn:
            break
        if a.get("alive") is False or int(a.get("hp", 1) or 1) <= 0:
            continue
        if not _is_gossip_source(a):
            continue
        if _h32(seed, turn, a_id, "gossip_roll") % 10 != 0:
            continue

        aff_a = str(a.get("affiliation", "") or "").strip().lower()
        loc_a = str(a.get("current_location", "") or a.get("home_location", "") or "").strip().lower()

        candidates: list[tuple[str, dict[str, Any], str]] = []
        for b_id, b in items:
            if b_id == a_id:
                continue
            if b.get("alive") is False or int(b.get("hp", 1) or 1) <= 0:
                continue
            aff_b = str(b.get("affiliation", "") or "").strip().lower()
            loc_b = str(b.get("current_location", "") or b.get("home_location", "") or "").strip().lower()
            same_f = bool(aff_a) and aff_a == aff_b
            same_l = bool(loc_a) and loc_a == loc_b and bool(loc_b)
            if same_f:
                candidates.append((b_id, b, "faction"))
            elif same_l:
                candidates.append((b_id, b, "location"))

        if not candidates:
            continue

        candidates.sort(key=lambda x: x[0])
        pick_i = _h32(seed, turn, a_id, "pick_b") % len(candidates)
        b_id, b, kind = candidates[pick_i]

        delta = 5 + (_h32(seed, turn, a_id, b_id, "sus_delta") % 6)  # 5..10
        bs = b.setdefault("belief_summary", {})
        if not isinstance(bs, dict):
            bs = {}
            b["belief_summary"] = bs
        try:
            cur = int(bs.get("suspicion", 0) or 0)
        except Exception:
            cur = 0
        bs["suspicion"] = max(0, min(100, cur + int(delta)))
        b["rumor_influence_turn"] = turn

        if kind == "faction":
            ctx = aff_a or "faction"
        else:
            ctx = f"loc {loc_a}"
        world_notes.append(f"[Gossip] Reputation spread from {a_id} to {b_id} within {ctx}.")
        spreads += 1

    return spreads


def detect_gossip_worthy_action(action_ctx: dict[str, Any], roll_pkg: dict[str, Any]) -> tuple[str | None, str | None]:
    """Detect if the current action is gossip-worthy.
    
    Returns: (info_category, summary_text) or (None, None)
    """
    domain = str(action_ctx.get("domain", "") or "").lower()
    action_type = str(action_ctx.get("action_type", "") or "").lower()
    outcome = str(roll_pkg.get("outcome", "") or "").lower() if roll_pkg else ""
    normalized = str(action_ctx.get("normalized_input", "") or "").lower()
    
    # Combat actions
    if domain == "combat" or "combat" in action_type:
        if any(term in normalized for term in ["shoot", "tembak", "kill", "bunuh", "attack", "serang", "fight", "combat"]):
            return "combat", "memperhatikan kekerasan"
    
    # Stealth actions
    if domain in ("stealth", "evasion"):
        if any(term in normalized for term in ["sneak", "mengendap", "hide", "sembunyi", "lurk", "mengintai", "infiltrate"]):
            return "stealth", "perilaku mencurigakan"
    
    # Hacking
    if domain == "hacking" or "hack" in normalized:
        # More specific: whether it was noisy/quiet and target hint.
        vis = str(action_ctx.get("visibility", "public") or "public").lower()
        vol = "quiet" if vis in ("low", "private", "stealth") else "noisy"
        if "police" in normalized or "polisi" in normalized:
            tgt = "police"
        elif "corporate" in normalized or "korporat" in normalized:
            tgt = "corporate"
        elif "black" in normalized or "gelap" in normalized:
            tgt = "black_market"
        else:
            tgt = "network"
        return "hack", f"hack {tgt} ({vol})"
    
    # Wealth-related actions (spending money, buying expensive things)
    if any(term in normalized for term in ["bought", "membeli", "expensive", "mahal", "cash", "tunai", "paid"]):
        if "bank" in normalized or "deposit" in normalized:
            return "wealth", "transaksi mencurigakan"
    
    # Social (meeting contacts, forming relationships)
    if domain == "social":
        if any(term in normalized for term in ["contact", "kontak", "meet", "temui", "talk", "bicara"]):
            return "social", "koneksi baru"
    
    return None, None


def trigger_rumor_from_action(state: dict[str, Any], action_ctx: dict[str, Any], roll_pkg: dict[str, Any]) -> None:
    """Trigger social diffusion based on player action."""
    try:
        from engine.social.social_diffusion import queue_rumor_about_player
        
        category, summary = detect_gossip_worthy_action(action_ctx, roll_pkg)
        
        if not category or not summary:
            return
        
        # Only trigger on successful/visible actions
        outcome = str(roll_pkg.get("outcome", "") or "").lower() if roll_pkg else ""
        
        # Trigger on good outcomes (visible to NPCs)
        if outcome in ("success", "critical_success", "partial"):
            queue_rumor_about_player(state, summary, category)
        
        # Also trigger on failures in suspicious contexts
        if outcome == "failure" and category in ("combat", "stealth", "hack"):
            # Failed suspicious action = noticed
            queue_rumor_about_player(state, f"{summary} (terdeteksi)", category)
            
    except Exception:
        pass  # Social diffusion is optional enhancement


def apply_social_diffusion_hops(state: dict[str, Any]) -> None:
    """Process pending social diffusion hops from events."""
    pending = state.get("pending_events", []) or []
    if not isinstance(pending, list):
        return
    
    world_notes = state.setdefault("world_notes", [])
    
    # Find and process social_diffusion_hop events
    to_remove = []
    for i, ev in enumerate(pending):
        if not isinstance(ev, dict):
            continue
        
        if ev.get("event_type") == "social_diffusion_hop" and not ev.get("triggered"):
            try:
                from engine.social.social_diffusion import propagate_rumor
                
                payload = ev.get("payload", {})
                if not isinstance(payload, dict):
                    continue
                
                from_npc = payload.get("from_npc", "")
                to_npc = payload.get("to_npc", "")
                rumor = payload.get("rumor", "")
                category = payload.get("category", "")
                hop = payload.get("hop", 0)
                
                if from_npc and to_npc and rumor and category:
                    # Propagate to next hop
                    propagated = propagate_rumor(state, from_npc, rumor, category, hop=hop)
                    
                    # Add world note for verbose tracking
                    if propagated:
                        world_notes.append(f"[SocialDiffusion] {to_npc} mendengar: {rumor}")
                    
                    to_remove.append(i)
                    
            except Exception:
                pass
    
    # Remove processed events
    for i in sorted(to_remove, reverse=True):
        if 0 <= i < len(pending):
            pending.pop(i)
