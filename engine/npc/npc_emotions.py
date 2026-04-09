from __future__ import annotations

import hashlib
from typing import Any

from engine.core.factions import sync_faction_statuses_from_trace
from engine.npc.npcs import ensure_ambient_npcs


def _clamp_int(v: int, lo: int, hi: int) -> int:
    return max(lo, min(hi, int(v)))


# Plutchik primary emotions (foundation).
_PRIMARY = ("joy", "trust", "fear", "surprise", "sadness", "disgust", "anger", "anticipation")


def _ensure_primary_fields(npc: dict[str, Any]) -> None:
    """Back-compat: if older saves used different keys, map them into Plutchik primaries."""
    # Legacy -> primary mapping.
    if "joy" not in npc and "affection" in npc:
        npc["joy"] = npc.get("affection", 0)
    if "anger" not in npc and "resentment" in npc:
        npc["anger"] = npc.get("resentment", 0)
    if "anticipation" not in npc and "jealousy" in npc:
        npc["anticipation"] = npc.get("jealousy", 0)
    # respect was a proxy for trust in the previous iteration
    if "trust" not in npc and "respect" in npc:
        npc["trust"] = npc.get("respect", 50)

    npc.setdefault("joy", 0)
    npc.setdefault("trust", 50)
    npc.setdefault("fear", 10)
    npc.setdefault("surprise", 0)
    npc.setdefault("sadness", 0)
    npc.setdefault("disgust", 0)
    npc.setdefault("anger", 0)
    npc.setdefault("anticipation", 0)


def _ensure_emotion_state(npc: dict[str, Any]) -> dict[str, Any]:
    _ensure_primary_fields(npc)
    es = npc.setdefault("emotion_state", {})
    if not isinstance(es, dict):
        es = {}
        npc["emotion_state"] = es
    # Ensure primary channels exist (Plutchik).
    for ch in _PRIMARY:
        slot = es.setdefault(ch, {})
        if not isinstance(slot, dict):
            es[ch] = {}
            slot = es[ch]
        slot.setdefault("severity", 0)
        slot.setdefault("last_turn", 0)
        slot.setdefault("last_kind", "none")
    return es


def _touch_emotion(npc: dict[str, Any], channel: str, *, severity: int, turn: int, kind: str) -> None:
    es = _ensure_emotion_state(npc)
    slot = es.get(channel)
    if not isinstance(slot, dict):
        return
    # Keep the strongest recent event as the "memory anchor".
    sev = _clamp_int(severity, 0, 100)
    prev = _clamp_int(slot.get("severity", 0), 0, 100)
    slot["severity"] = max(prev, sev)
    slot["last_turn"] = int(turn)
    slot["last_kind"] = str(kind or "event")


# Public wrappers (used by other engine modules, eg ripple effects).
def ensure_emotion_state(npc: dict[str, Any]) -> dict[str, Any]:
    return _ensure_emotion_state(npc)


def touch_emotion(npc: dict[str, Any], channel: str, *, severity: int, turn: int, kind: str) -> None:
    _touch_emotion(npc, channel, severity=severity, turn=turn, kind=kind)


def decay_npc_emotions(state: dict[str, Any]) -> None:
    """Decay NPC emotions towards baselines each turn.

    Decay is inversely proportional to event severity:
    - low severity fades normally
    - high severity becomes very slow / near-permanent
    """
    npcs = state.get("npcs", {}) or {}
    if not isinstance(npcs, dict) or not npcs:
        return
    turn = int(state.get("meta", {}).get("turn", 0) or 0)

    # Baselines for Plutchik primaries.
    base = {"joy": 0, "trust": 50, "fear": 10, "surprise": 0, "sadness": 0, "disgust": 0, "anger": 0, "anticipation": 0}
    # How many points can decay per turn at severity=0.
    base_step = {"joy": 1.0, "trust": 1.5, "fear": 2.0, "surprise": 2.2, "sadness": 1.4, "disgust": 2.0, "anger": 2.0, "anticipation": 1.8}

    for _name, npc in npcs.items():
        if not isinstance(npc, dict):
            continue
        _ensure_primary_fields(npc)
        es = _ensure_emotion_state(npc)
        for ch, b in base.items():
            slot = es.get(ch, {})
            if not isinstance(slot, dict):
                continue
            last_turn = int(slot.get("last_turn", 0) or 0)
            dt = max(0, turn - last_turn)
            if dt <= 0:
                continue
            sev = _clamp_int(slot.get("severity", 0), 0, 100)
            # Severity curve: sev=0 -> 1.0, sev=50 -> ~0.25, sev=80 -> ~0.04, sev=95 -> ~0.0025
            factor = ((100 - sev) / 100) ** 2
            step = float(base_step.get(ch, 1.0)) * factor * dt
            if step <= 0:
                continue

            cur = float(_clamp_int(npc.get(ch, b), 0, 100))
            target = float(b)
            if cur > target:
                cur = max(target, cur - step)
            elif cur < target:
                cur = min(target, cur + step)
            npc[ch] = _clamp_int(int(round(cur)), 0, 100)

            # As it fades, reduce stored severity slowly too.
            if sev > 0:
                slot["severity"] = _clamp_int(int(round(sev * 0.98)), 0, 100)

        # If major negatives cooled down, let mood normalize.
        try:
            if int(npc.get("fear", 10) or 0) <= 18 and int(npc.get("anger", 0) or 0) <= 10:
                if str(npc.get("mood", "")) in ("betrayed", "scared", "angry"):
                    npc["mood"] = "calm"
        except Exception:
            pass


def _secondary_emotions(npc: dict[str, Any]) -> dict[str, int]:
    """Derived labels from Plutchik primaries for UI/narration (not stored/decayed separately)."""
    _ensure_primary_fields(npc)
    joy = _clamp_int(npc.get("joy", 0), 0, 100)
    trust = _clamp_int(npc.get("trust", 50), 0, 100)
    fear = _clamp_int(npc.get("fear", 10), 0, 100)
    surprise = _clamp_int(npc.get("surprise", 0), 0, 100)
    anger = _clamp_int(npc.get("anger", 0), 0, 100)
    disgust = _clamp_int(npc.get("disgust", 0), 0, 100)
    anticipation = _clamp_int(npc.get("anticipation", 0), 0, 100)

    # Common secondaries (subset).
    love = int(round((joy + trust) / 2))
    alarm = int(round((fear + surprise) / 2))
    contempt = int(round((anger + disgust) / 2))
    aggressiveness = int(round((anger + anticipation) / 2))
    return {"love": love, "alarm": alarm, "contempt": contempt, "aggressiveness": aggressiveness}


def _trace_status_from_pct(pct: int) -> str:
    # Keep aligned with engine/trace.py + monitor.
    if pct <= 25:
        return "Ghost"
    if pct <= 50:
        return "Flagged"
    if pct <= 75:
        return "Investigated"
    return "Manhunt"


def _set_trace_pct(state: dict[str, Any], new_pct: int) -> None:
    tr = state.setdefault("trace", {})
    pct = _clamp_int(new_pct, 0, 100)
    tr["trace_pct"] = pct
    tr["trace_status"] = _trace_status_from_pct(pct)
    sync_faction_statuses_from_trace(state)


def _det_roll_1_100(*parts: Any) -> int:
    s = "|".join([str(p) for p in parts])
    h = hashlib.md5(s.encode("utf-8", errors="ignore")).hexdigest()
    return (int(h[:8], 16) % 100) + 1


def _attention_to_base_inform_pct(att: str) -> int:
    att = (att or "idle").lower()
    if att == "idle":
        return 5
    if att == "aware":
        return 12
    if att == "investigated":
        return 25
    if att == "manhunt":
        return 40
    return 5


def apply_npc_emotion_after_roll(state: dict[str, Any], action_ctx: dict[str, Any], roll_pkg: dict[str, Any]) -> None:
    """Apply deterministic NPC emotion/relationship impacts after roll.

    v1: model "informant/betrayal" via police attention tier + NPC psych stats.
    """
    domain = str(action_ctx.get("domain", "") or "").lower()
    if domain not in ("social", "combat", "hacking"):
        return

    # Ensure we have at least ambient NPCs for social beats.
    if domain == "social":
        ensure_ambient_npcs(state, action_ctx)

    npcs = state.get("npcs", {}) or {}
    if not isinstance(npcs, dict) or not npcs:
        return

    # Decide affected NPCs.
    affected: list[str] = []
    targets = action_ctx.get("targets")
    if isinstance(targets, list):
        for t in targets[:6]:
            if isinstance(t, str) and t in npcs:
                affected.append(t)

    if not affected and domain in ("social", "combat", "hacking"):
        # If no explicit targets, affect a small crowd subset.
        ambient = [n for n, v in npcs.items() if isinstance(v, dict) and v.get("ambient") is True]
        if ambient:
            affected = ambient[:2]
        else:
            affected = list(npcs.keys())[:2]

    if not affected:
        return

    # Persist the primary focus NPC so pronouns like "orang itu" work next turn.
    if affected:
        state.setdefault("meta", {})["npc_focus"] = affected[0]

    # Police attention tier.
    statuses = (state.get("world", {}) or {}).get("faction_statuses", {}) or {}
    police_att = statuses.get("police", "idle")

    # Visibility hint.
    visibility = str(action_ctx.get("visibility", "public") or "public").lower()
    stealth = visibility in ("low", "private", "stealth")

    outcome = str(roll_pkg.get("outcome", "") or "")
    success = any(k in outcome for k in ("Success", "Critical Success", "No Roll"))

    social_mode = str(action_ctx.get("social_mode", "none") or "none").lower()
    conflict = social_mode == "conflict" or str(action_ctx.get("intent_note", "")).lower() == "social_conflict"
    if domain == "combat":
        conflict = True

    for npc_name in affected:
        npc = npcs.get(npc_name)
        if not isinstance(npc, dict):
            continue

        # Defaults (in case older states exist).
        npc.setdefault("affiliation", "civilian")
        _ensure_primary_fields(npc)
        npc.setdefault("opportunism", 30)
        npc.setdefault("loyalty", 50)
        npc.setdefault("mood", "calm")

        joy = _clamp_int(npc.get("joy", 0), 0, 100)
        trust = _clamp_int(npc.get("trust", 50), 0, 100)
        fear = _clamp_int(npc.get("fear", 10), 0, 100)
        surprise = _clamp_int(npc.get("surprise", 0), 0, 100)
        sadness = _clamp_int(npc.get("sadness", 0), 0, 100)
        disgust = _clamp_int(npc.get("disgust", 0), 0, 100)
        anger = _clamp_int(npc.get("anger", 0), 0, 100)
        anticipation = _clamp_int(npc.get("anticipation", 0), 0, 100)
        opportunism = _clamp_int(npc.get("opportunism", 30), 0, 100)
        loyalty = _clamp_int(npc.get("loyalty", 50), 0, 100)
        affiliation = str(npc.get("affiliation", "civilian") or "civilian").lower()
        turn = int(state.get("meta", {}).get("turn", 0) or 0)
        cmd = str(action_ctx.get("normalized_input", "") or "")

        # Pemancing (triggers) untuk emosi berbasis kondisi pemain & kata kunci.
        bad_hygiene = False
        if domain == "social":
            stats = (state.get("player", {}) or {}).get("social_stats", {}) or {}
            if not isinstance(stats, dict):
                stats = {}
            bio = state.get("bio", {}) or {}
            bad_hygiene = bool(bio.get("hygiene_tax_active")) or int(stats.get("hygiene", 0) or 0) <= -3
            if bad_hygiene:
                npc["disgust"] = _clamp_int(disgust + 10, 0, 100)
                npc["trust"] = _clamp_int(trust - 6, 0, 100)
                _touch_emotion(npc, "disgust", severity=55, turn=turn, kind="bad_hygiene")
                _touch_emotion(npc, "trust", severity=45, turn=turn, kind="bad_hygiene")
                # Slightly suppress joy when disgust is high.
                if npc["disgust"] >= 40:
                    npc["joy"] = _clamp_int(joy - 2, 0, 100)
                    _touch_emotion(npc, "joy", severity=20, turn=turn, kind="disgust_suppression")

            # Trust/joy trigger from outfit/speaking (even without conflict).
            outfit = int(stats.get("outfit", 0) or 0)
            speaking = int(stats.get("speaking", 0) or 0)
            looks = int(stats.get("looks", 0) or 0)
            # Small positive bump on good presentation if the interaction succeeds.
            if success and (outfit + speaking + looks) >= 18:
                npc["trust"] = _clamp_int(int(npc.get("trust", trust)) + 4, 0, 100)
                npc["joy"] = _clamp_int(int(npc.get("joy", joy)) + 2, 0, 100)
                _touch_emotion(npc, "trust", severity=30, turn=turn, kind="good_presentation")
                _touch_emotion(npc, "joy", severity=25, turn=turn, kind="good_presentation")

            # Anticipation/anger trigger by keywords (explicit jealousy themes).
            if any(k in cmd for k in ("cemburu", "selingkuh", "pacar", "mantan", "gebetan")):
                npc["anticipation"] = _clamp_int(anticipation + 10, 0, 100)
                npc["anger"] = _clamp_int(anger + 4, 0, 100)
                _touch_emotion(npc, "anticipation", severity=70, turn=turn, kind="jealousy_keyword")
                _touch_emotion(npc, "anger", severity=55, turn=turn, kind="jealousy_keyword")

        # Informant/betrayal chance for conflict beats.
        if conflict:
            base = _attention_to_base_inform_pct(police_att)
            # NPC psychology influences betrayal.
            base += 0  # keep deterministic
            # Higher tiers of police attention make betrayal dramatically more likely.
            if str(police_att).lower() == "investigated":
                base += 25
            elif str(police_att).lower() == "manhunt":
                base += 40
            # If you fail the conflict beat, witnesses often panic and talk more.
            if not success:
                base += 10
            base += int(max(0, anger - 50) / 5)  # up to +10
            base += int(max(0, opportunism - 50) / 5)  # up to +10
            base -= int(max(0, _secondary_emotions(npc).get("love", 0) - 70) / 3)  # reduce if in love
            base -= int(max(0, loyalty - 70) / 4)  # reduce if loyal

            # Stealth keeps it quieter (local rumor only).
            if stealth:
                base = int(base * 0.5)

            # Police-linked NPCs are less likely to inform "against" themselves.
            if affiliation == "police":
                base = int(base * 0.2)

            # Keep inside bounds.
            betray_chance = _clamp_int(base, 0, 100)

            # Deterministic influence check.
            roll = _det_roll_1_100(npc_name, state.get("meta", {}).get("turn", 0), domain, outcome, police_att)
            if roll <= betray_chance:
                # Betray: raise trace.
                delta = 8
                if police_att in ("investigated", "manhunt"):
                    delta = 14
                if stealth:
                    delta = 6

                _set_trace_pct(state, int(state.get("trace", {}).get("trace_pct", 0) or 0) + delta)
                npc["mood"] = "betrayed"
                npc["fear"] = _clamp_int(fear + 15, 0, 100)
                npc["anger"] = _clamp_int(anger + 12, 0, 100)
                npc["trust"] = _clamp_int(trust - 14, 0, 100)
                npc["disgust"] = _clamp_int(disgust + 10, 0, 100)
                npc["sadness"] = _clamp_int(sadness + 6, 0, 100)
                _touch_emotion(npc, "fear", severity=75, turn=turn, kind="betrayal")
                _touch_emotion(npc, "anger", severity=85, turn=turn, kind="betrayal")
                _touch_emotion(npc, "trust", severity=80, turn=turn, kind="betrayal")
                _touch_emotion(npc, "disgust", severity=70, turn=turn, kind="betrayal")
                _touch_emotion(npc, "sadness", severity=70, turn=turn, kind="betrayal")
                npc["last_contact_day"] = int(state.get("meta", {}).get("day", 1))
                state.setdefault("world_notes", []).append(
                    f"[NPC] {npc_name} mengkhianati rumor ke polisi (att={police_att})."
                )
            else:
                # Not enough to betray: they get scared and keep it local.
                npc["mood"] = "scared" if not success else "angry"
                npc["fear"] = _clamp_int(fear + (12 if not success else 6), 0, 100)
                npc["anger"] = _clamp_int(anger + (8 if not success else 3), 0, 100)
                sev = 35 if not success else 20
                _touch_emotion(npc, "fear", severity=sev, turn=turn, kind="conflict_witness")
                _touch_emotion(npc, "anger", severity=sev, turn=turn, kind="conflict_witness")
                if not success:
                    npc["trust"] = _clamp_int(int(npc.get("trust", trust)) - 4, 0, 100)
                    _touch_emotion(npc, "trust", severity=25, turn=turn, kind="conflict_failure")
        else:
            # Non-conflict social: success can build trust/affection.
            if domain == "social" and success:
                love = _secondary_emotions(npc).get("love", 0)
                npc["mood"] = "attracted" if love >= 60 else "friendly"
                # If player presentation is poor (eg hygiene), the "bonding" gain is heavily muted.
                trust_gain = 8
                joy_gain = 10
                if bad_hygiene:
                    trust_gain = 2
                    joy_gain = 3
                npc["trust"] = _clamp_int(npc.get("trust", 50) + trust_gain, 0, 100)
                npc["joy"] = _clamp_int(joy + joy_gain, 0, 100)
                npc["fear"] = _clamp_int(fear - 4, 0, 100)
                _touch_emotion(npc, "trust", severity=25, turn=turn, kind="positive_social")
                _touch_emotion(npc, "joy", severity=30, turn=turn, kind="positive_social")

                # If affection is high, they may hide you (reduce trace).
                if _secondary_emotions(npc).get("love", 0) >= 80 and police_att in ("aware", "investigated", "manhunt"):
                    # Chance based on loyalty; deterministic.
                    help_base = _clamp_int(int(npc.get("loyalty", 50)), 0, 100)
                    roll = _det_roll_1_100(npc_name, state.get("meta", {}).get("turn", 0), "help", outcome, police_att)
                    if roll <= help_base:
                        _set_trace_pct(state, int(state.get("trace", {}).get("trace_pct", 0) or 0) - 8)
                        state.setdefault("world_notes", []).append(f"[NPC] {npc_name} menutupi jejakmu (affection & loyalty).")
                        _touch_emotion(npc, "trust", severity=55, turn=turn, kind="hide_player")

        # Promote to global contact when relationship is strong (or explicitly flagged).
        is_contact = bool(npc.get("is_contact") is True)
        cur_trust = _clamp_int(npc.get("trust", trust), 0, 100)
        cur_love = _clamp_int(_secondary_emotions(npc).get("love", 0), 0, 100)
        if is_contact or cur_love >= 80 or cur_trust >= 75:
            npc["is_contact"] = True
            world = state.setdefault("world", {})
            contacts = world.setdefault("contacts", {})
            if isinstance(contacts, dict):
                # Store a stable snapshot; location-specific fields can still exist in local copies.
                contacts[npc_name] = dict(npc)

        # Belief update from direct interaction (witness-level confidence).
        try:
            from engine.npc.npcs import add_belief_snippet

            topic = "world_rumor"
            if domain == "social":
                topic = "player_help" if (not conflict and success) else "player_lie" if conflict and not success else "player_social"
            elif domain == "combat":
                topic = "player_violence"
            elif domain == "hacking":
                topic = "player_hacking"

            # Bias: if NPC already distrusts, they interpret worse.
            bias = 0.0
            try:
                bias = -0.2 if int(npc.get("trust", 50) or 0) <= 30 else 0.1 if int(npc.get("trust", 50) or 0) >= 80 else 0.0
            except Exception:
                bias = 0.0

            claim = f"Interaksi langsung: {domain} outcome={outcome}"
            add_belief_snippet(
                state,
                npc,
                topic=topic,
                claim=claim,
                source="witness",
                origin="direct",
                confidence=0.9 if domain in ("social", "combat") else 0.85,
                bias=bias,
            )
        except Exception:
            pass

