from __future__ import annotations

import random
from typing import Any

from engine.systems.hacking import ensure_location_factions


CONDITION_DEGRADE = {
    1: {"uses": 20, "event": "major_damage"},   # Pristine -> Good
    2: {"uses": 15, "event": "harsh_condition"},  # Good -> Fair
    3: {"uses": 10, "event": "combat_damage"},  # Fair -> Poor
    4: {"uses": 5, "event": "critical_failure"},  # Poor -> Broken
}


def roll_d100(state: dict[str, Any] | None = None, action_ctx: dict[str, Any] | None = None) -> int:
    """Combat roll helper. Prefer deterministic roll when state/action_ctx provided."""
    if isinstance(state, dict) and isinstance(action_ctx, dict):
        try:
            from engine.core.rng import roll_for_action

            return int(roll_for_action(state, action_ctx, salt="combat"))
        except Exception:
            pass
    return random.randint(1, 100)


def get_active_weapon(inventory: dict[str, Any]) -> dict[str, Any] | None:
    weapons = inventory.get("weapons", {})
    active_id = str(inventory.get("active_weapon_id", "")).strip()
    if active_id and isinstance(weapons, dict) and isinstance(weapons.get(active_id), dict):
        return weapons[active_id]
    # Backward-compat fallback
    legacy = inventory.get("r_hand_weapon")
    if isinstance(legacy, dict):
        return legacy
    return None


def is_ranged_combat(action_ctx: dict[str, Any]) -> bool:
    return action_ctx.get("combat_style") == "ranged"


def weapon_uses_ammo(weapon: dict[str, Any]) -> bool:
    return str(weapon.get("kind", "")).lower() == "firearm" or "ammo" in weapon


def apply_combat_gates(state: dict[str, Any], action_ctx: dict[str, Any]) -> None:
    """Set action_ctx['combat_blocked'] sebelum roll jika tembakan tidak mungkin."""
    if action_ctx.get("domain") != "combat":
        return
    inv = state.setdefault("inventory", {})
    w = get_active_weapon(inv)

    flags = state.setdefault("flags", {})
    if is_ranged_combat(action_ctx):
        if not isinstance(w, dict):
            action_ctx["combat_blocked"] = "no_weapon"
            return
        if int(w.get("condition_tier", 2)) >= 5:
            action_ctx["combat_blocked"] = "broken"
            return
        if bool(w.get("jammed")) or bool(flags.get("weapon_jammed")):
            action_ctx["combat_blocked"] = "jammed"
            return
        if weapon_uses_ammo(w) and int(w.get("ammo", 0)) < 1:
            action_ctx["combat_blocked"] = "out_of_ammo"
            return
        return

    # Melee: senjata rusak total tidak bisa dipakai
    if isinstance(w, dict) and int(w.get("condition_tier", 2)) >= 5:
        action_ctx["combat_blocked"] = "broken"


def resolve_combat_after_roll(state: dict[str, Any], action_ctx: dict[str, Any], roll_pkg: dict[str, Any]) -> None:
    """Setelah roll: jam (Poor), atau kurangi amunisi + degradasi. Tanpa amunisi jika jam."""
    if action_ctx.get("domain") != "combat":
        return
    if action_ctx.get("combat_blocked"):
        return

    inv = state.setdefault("inventory", {})
    w = get_active_weapon(inv)
    if not isinstance(w, dict):
        return

    tier = int(w.get("condition_tier", 2))
    if tier >= 5:
        return

    if roll_pkg.get("roll") is None:
        return

    roll = int(roll_pkg["roll"])
    flags = state.setdefault("flags", {})
    outcome = str(roll_pkg.get("outcome", "") or "")

    if is_ranged_combat(action_ctx) and weapon_uses_ammo(w):
        if flags.get("weapon_jammed"):
            return
        jammed, crit_jam = jam_check(w, roll)
        if jammed:
            flags["weapon_jammed"] = True
            flags["jam_critical"] = crit_jam
            w["jammed"] = True
            # Combat status effect: jam shock (short), critical jam is stronger.
            try:
                from engine.systems.effects import add_effect

                add_effect(
                    state,
                    target=state.setdefault("player", {}),
                    effect_id="jam_shock",
                    kind="shock",
                    duration_min=18 if crit_jam else 10,
                    stacks=1,
                    max_stacks=2,
                    stacking="refresh",
                    source="combat",
                    meta={"reason": "jam", "critical": bool(crit_jam)},
                )
            except Exception:
                pass
            return
        flags["ammo_ok"] = consume_ammo(w, 1)
        degrade_weapon(w, event="combat_damage")
    else:
        degrade_weapon(w, event="combat_damage")

    # Combat status effect: bleeding risk on critical failure / rough outcomes.
    try:
        if "Critical Failure" in outcome:
            from engine.systems.effects import add_effect

            add_effect(
                state,
                target=state.setdefault("player", {}),
                effect_id="bleeding",
                kind="bleed",
                duration_min=60,
                stacks=1,
                max_stacks=3,
                stacking="stack",
                source="combat",
                meta={"reason": "critical_failure"},
            )
    except Exception:
        pass

    # World attention: combat tends to increase investigation/trace pressure,
    # unless phrased as stealth/private action.
    try:
        from engine.core.factions import sync_faction_statuses_from_trace

        visibility = str(action_ctx.get("visibility", "public") or "public").lower()
        if visibility in ("low", "private", "stealth"):
            delta = 6
        else:
            # Success/failure both create noise; better outcomes are louder.
            if "Critical" in outcome:
                delta = 22
            elif "Success" in outcome:
                delta = 18
            elif "Failure" in outcome:
                delta = 14
            else:
                delta = 12

        trace = state.setdefault("trace", {})
        pct = int(trace.get("trace_pct", 0) or 0)
        pct = max(0, min(100, pct + int(delta)))
        trace["trace_pct"] = pct
        trace["trace_status"] = "Ghost" if pct <= 25 else "Flagged" if pct <= 50 else "Investigated" if pct <= 75 else "Manhunt"
        sync_faction_statuses_from_trace(state)
    except Exception:
        pass

    # Faction impact: if target is affiliated (police/corporate/black_market),
    # adjust world.factions in a directed way (beyond generic trace noise).
    try:
        ensure_location_factions(state)
        world = state.setdefault("world", {})
        factions = world.setdefault("factions", {})
        npcs = state.get("npcs", {}) or {}

        def _contains_any(h: str, needles: tuple[str, ...]) -> bool:
            s = (h or "").lower()
            return any(n in s for n in needles)

        def _infer_target_affiliation() -> str | None:
            # 1) Explicit targets -> NPC affiliation
            targets = action_ctx.get("targets")
            if isinstance(targets, list) and isinstance(npcs, dict):
                for t in targets[:4]:
                    if isinstance(t, str) and t in npcs and isinstance(npcs[t], dict):
                        aff = str(npcs[t].get("affiliation", "") or "").strip().lower()
                        if aff in ("police", "corporate", "black_market"):
                            return aff
            # 2) Keyword hints
            norm = str(action_ctx.get("normalized_input", "") or "")
            if _contains_any(norm, ("polisi", "police", "patroli", "keamanan", "satpam", "security")):
                return "police"
            if _contains_any(norm, ("korporat", "corporate", "karyawan", "pegawai", "perusahaan")):
                return "corporate"
            if _contains_any(norm, ("pasar gelap", "black market", "black_market", "gang", "preman")):
                return "black_market"
            return None

        tgt = _infer_target_affiliation()
        if tgt:
            outcome = str(roll_pkg.get("outcome", "") or "")
            success = "Success" in outcome
            crit = "Critical" in outcome
            # Scale by visibility: stealth impacts factions less immediately.
            vis = str(action_ctx.get("visibility", "public") or "public").lower()
            scale = 0.5 if vis in ("low", "private", "stealth") else 1.0
            mag = 14 if crit else 10 if success else 6
            mag = int(mag * scale)

            # Apply directed deltas per conflict model (v1).
            if tgt == "police":
                factions["police"]["stability"] = max(0, int(factions["police"].get("stability", 50)) - mag)
                factions["police"]["power"] = max(0, int(factions["police"].get("power", 50)) - int(mag * 0.6))
                factions["corporate"]["power"] = min(100, int(factions["corporate"].get("power", 50)) + int(mag * 0.3))
                factions["black_market"]["power"] = min(100, int(factions["black_market"].get("power", 50)) + int(mag * 0.4))
                state.setdefault("world_notes", []).append("[Combat] Bentrokan dengan aparat memicu eskalasi perhatian.")
            elif tgt == "corporate":
                factions["corporate"]["stability"] = max(0, int(factions["corporate"].get("stability", 50)) - mag)
                factions["corporate"]["power"] = max(0, int(factions["corporate"].get("power", 50)) - int(mag * 0.5))
                factions["police"]["power"] = min(100, int(factions["police"].get("power", 50)) + int(mag * 0.5))
                factions["black_market"]["power"] = min(100, int(factions["black_market"].get("power", 50)) + int(mag * 0.2))
                state.setdefault("world_notes", []).append("[Combat] Kekerasan terhadap pihak korporat menggeser keseimbangan keamanan.")
            else:  # black_market
                factions["black_market"]["stability"] = max(0, int(factions["black_market"].get("stability", 50)) - mag)
                factions["black_market"]["power"] = max(0, int(factions["black_market"].get("power", 50)) - int(mag * 0.6))
                factions["police"]["power"] = min(100, int(factions["police"].get("power", 50)) + int(mag * 0.7))
                factions["corporate"]["power"] = min(100, int(factions["corporate"].get("power", 50)) + int(mag * 0.2))
                state.setdefault("world_notes", []).append("[Combat] Kekerasan di jalur gelap memicu operasi penertiban.")

            # Clamp
            for f in ("corporate", "police", "black_market"):
                for k in ("stability", "power"):
                    factions[f][k] = max(0, min(100, int(factions[f].get(k, 50) or 50)))
    except Exception:
        pass

    try:
        from engine.npc.npc_combat_ai import apply_npc_combat_followup

        apply_npc_combat_followup(state, action_ctx, roll_pkg)
    except Exception:
        pass


def jam_check(weapon: dict[str, Any], roll: int) -> tuple[bool, bool]:
    # Poor condition (4): jam on 1-15; 1-5 also critical-failure consequences.
    tier = int(weapon.get("condition_tier", 2))
    if tier != 4:
        return False, False
    jammed = 1 <= roll <= 15
    crit_from_jam = 1 <= roll <= 5
    return jammed, crit_from_jam


def degrade_weapon(weapon: dict[str, Any], *, event: str | None = None) -> None:
    tier = int(weapon.get("condition_tier", 2))
    uses = int(weapon.get("use_count", 0)) + 1
    weapon["use_count"] = uses
    if tier >= 5:
        return
    rule = CONDITION_DEGRADE.get(tier)
    if not rule:
        return
    should_degrade = uses >= int(rule["uses"]) or (event is not None and event == rule["event"])
    if should_degrade:
        weapon["condition_tier"] = min(5, tier + 1)
        weapon["use_count"] = 0


def consume_ammo(weapon: dict[str, Any], amount: int = 1) -> bool:
    ammo = int(weapon.get("ammo", 0))
    if ammo < amount:
        return False
    weapon["ammo"] = ammo - amount
    return True

