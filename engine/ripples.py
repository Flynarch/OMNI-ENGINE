from __future__ import annotations

from typing import Any


def _clamp_int(v: int, lo: int, hi: int) -> int:
    return max(lo, min(hi, int(v)))


def _pick_npc_targets(state: dict[str, Any], rp: dict[str, Any]) -> list[dict[str, Any]]:
    npcs = state.get("npcs", {}) or {}
    if not isinstance(npcs, dict) or not npcs:
        return []

    propagation = str(rp.get("propagation", "local_witness") or "local_witness").lower()
    origin_loc = str(rp.get("origin_location", "") or "").strip().lower()
    origin_faction = str(rp.get("origin_faction", "") or "").strip().lower()
    witnesses = rp.get("witnesses") if isinstance(rp.get("witnesses"), list) else []
    witnesses = [w for w in witnesses if isinstance(w, str)]

    targets: list[dict[str, Any]] = []

    # Highest priority: explicit witnesses.
    if witnesses:
        for w in witnesses[:8]:
            npc = npcs.get(w)
            if isinstance(npc, dict):
                targets.append(npc)
        return targets

    # Otherwise: infer by propagation scope.
    if propagation in ("local", "local_witness", "witness"):
        for _name, npc in list(npcs.items())[:80]:
            if not isinstance(npc, dict):
                continue
            loc = str(npc.get("current_location", "") or "").strip().lower() or str(npc.get("home_location", "") or "").strip().lower()
            if origin_loc and loc and loc == origin_loc:
                targets.append(npc)
        return targets[:6]

    if propagation in ("contacts", "contact_network"):
        contacts = (state.get("world", {}) or {}).get("contacts", {}) or {}
        if isinstance(contacts, dict):
            # Apply only to contacts currently present in state.npcs.
            relay_allowed = bool(rp.get("relay_pending") is True)
            for name in list(contacts.keys())[:24]:
                npc = npcs.get(str(name))
                if not isinstance(npc, dict):
                    continue
                if origin_faction:
                    aff = str(npc.get("affiliation", "") or "").strip().lower()
                    if aff == origin_faction:
                        targets.append(npc)
                        continue
                    # High-trust relay contact can still inform, but only after delay.
                    if relay_allowed and int(npc.get("trust", 0) or 0) >= 85:
                        targets.append(npc)
                else:
                    targets.append(npc)
        return targets[:6]

    # Faction_network/broadcast: do not apply NPC emotion changes by default.
    return []


def apply_ripple_effects(state: dict[str, Any], rp: dict[str, Any]) -> None:
    """Apply ripple effects to state, with logical targeting.

    rp schema (subset):
    - impact:
        - npc_emotions: {emotion_name: delta_int}
        - factions: {faction_name: {stability: delta_int, power: delta_int}}
    - witnesses: optional list of NPC names
    - propagation: local_witness / contacts / faction_network / broadcast
    """
    if not isinstance(rp, dict):
        return
    impact = rp.get("impact") or rp.get("payload") or {}
    if not isinstance(impact, dict) or not impact:
        return

    # NPC emotion impacts.
    npc_em = impact.get("npc_emotions")
    if isinstance(npc_em, dict) and npc_em:
        targets = _pick_npc_targets(state, rp)
        if targets:
            try:
                # Ensure emotion_state channels exist if using Plutchik foundation.
                from engine.npc_emotions import ensure_emotion_state, touch_emotion

                turn = int(state.get("meta", {}).get("turn", 0) or 0)
                for npc in targets:
                    ensure_emotion_state(npc)
                    for emo, d in list(npc_em.items())[:12]:
                        if not isinstance(emo, str):
                            continue
                        try:
                            delta = int(d)
                        except Exception:
                            continue
                        cur = _clamp_int(npc.get(emo, 0), 0, 100)
                        npc[emo] = _clamp_int(cur + delta, 0, 100)
                        # Medium severity by default; callers can override by setting rp.impact_severity
                        sev = _clamp_int(int(impact.get("severity", 35) or 35), 0, 100)
                        touch_emotion(npc, emo, severity=sev, turn=turn, kind="ripple")
            except Exception:
                pass

    # Faction impacts.
    f_imp = impact.get("factions")
    if isinstance(f_imp, dict) and f_imp:
        world = state.setdefault("world", {})
        factions = world.setdefault("factions", {})
        if isinstance(factions, dict):
            for fname, delta in list(f_imp.items())[:8]:
                if not isinstance(fname, str) or not isinstance(delta, dict):
                    continue
                row = factions.setdefault(fname, {})
                if not isinstance(row, dict):
                    continue
                for k in ("stability", "power"):
                    if k in delta:
                        try:
                            dd = int(delta.get(k, 0))
                        except Exception:
                            dd = 0
                        row[k] = _clamp_int(int(row.get(k, 50) or 50) + dd, 0, 100)
