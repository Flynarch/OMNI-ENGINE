"""NPC rumor system integration.

This module connects social diffusion to NPC behavior:
- Detects when player actions generate gossip-worthy info
- Triggers social diffusion system
- Integrates with NPC emotions for rumor spread
"""
from __future__ import annotations

from typing import Any


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
