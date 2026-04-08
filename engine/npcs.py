from __future__ import annotations

import hashlib
from typing import Any


def _label(score: int) -> str:
    return "Devoted" if score >= 90 else "Friendly" if score >= 70 else "Neutral" if score >= 50 else "Cold" if score >= 30 else "Hostile" if score >= 10 else "Enemy"


def _clamp_int(v: int, lo: int, hi: int) -> int:
    return max(lo, min(hi, int(v)))


def _now(state: dict[str, Any]) -> tuple[int, int, int]:
    meta = state.get("meta", {}) or {}
    return int(meta.get("day", 1) or 1), int(meta.get("time_min", 0) or 0), int(meta.get("turn", 0) or 0)


def _ensure_belief_fields(n: dict[str, Any]) -> None:
    """Ensure belief memory is present for contacts (and safe for others)."""
    bs = n.setdefault("belief_snippets", [])
    if not isinstance(bs, list):
        n["belief_snippets"] = []
    summ = n.setdefault("belief_summary", {})
    if not isinstance(summ, dict):
        summ = {}
        n["belief_summary"] = summ
    summ.setdefault("suspicion", 0)  # 0..100
    summ.setdefault("respect", 50)  # 0..100 (kognitif; beda dari trust Plutchik)
    summ.setdefault("last_turn", 0)


def _snippet_id(*parts: Any) -> str:
    s = "|".join([str(p) for p in parts])
    h = hashlib.md5(s.encode("utf-8", errors="ignore")).hexdigest()
    return h[:12]


def add_belief_snippet(
    state: dict[str, Any],
    npc: dict[str, Any],
    *,
    topic: str,
    claim: str,
    source: str,
    origin: str,
    confidence: float,
    bias: float,
    truthiness: float | None = None,
) -> None:
    """Append a bounded belief snippet and update belief_summary + disposition/trust drift."""
    _ensure_belief_fields(npc)
    day, time_min, turn = _now(state)

    conf = float(max(0.0, min(1.0, confidence)))
    b = float(max(-1.0, min(1.0, bias)))
    tid = _snippet_id(topic, claim, source, origin, day)
    entry = {
        "id": tid,
        "topic": str(topic),
        "claim": str(claim)[:180],
        "source": str(source),
        "origin": str(origin),
        "day": day,
        "time_min": time_min,
        "confidence": round(conf, 3),
        "bias": round(b, 3),
    }
    if truthiness is not None:
        entry["truthiness"] = float(max(0.0, min(1.0, truthiness)))

    # Dedup by id.
    bs = npc.get("belief_snippets") or []
    if isinstance(bs, list):
        for it in bs[-30:]:
            if isinstance(it, dict) and it.get("id") == tid:
                return
    npc["belief_snippets"].append(entry)
    npc["belief_snippets"] = npc["belief_snippets"][-20:]

    # Update belief summary.
    summ = npc.get("belief_summary") or {}
    if not isinstance(summ, dict):
        summ = {}
        npc["belief_summary"] = summ
    sus = _clamp_int(summ.get("suspicion", 0), 0, 100)
    rep = _clamp_int(summ.get("respect", 50), 0, 100)

    # Topic weight: negative topics raise suspicion; positive lower it.
    t = str(topic).lower()
    neg = t in ("player_hacking", "player_trace", "player_violence", "player_crime", "player_lie")
    pos = t in ("player_help", "player_honesty", "player_generosity")
    w = 8
    if t in ("player_trace", "player_violence"):
        w = 12
    if pos:
        w = 10

    # Bias pushes interpretation: negative bias increases suspicion, positive decreases.
    bias_factor = 1.0 + (-b * 0.6)  # b=-1 => +0.6 suspicion; b=+1 => -0.6 suspicion
    delta = int(round(w * conf * bias_factor))
    if neg:
        sus = _clamp_int(sus + delta, 0, 100)
        rep = _clamp_int(rep - int(delta / 2), 0, 100)
    elif pos:
        sus = _clamp_int(sus - int(delta / 2), 0, 100)
        rep = _clamp_int(rep + delta, 0, 100)
    else:
        # neutral info slightly shifts towards confidence: small respect bump
        rep = _clamp_int(rep + int(delta / 4), 0, 100)

    summ["suspicion"] = sus
    summ["respect"] = rep
    summ["last_turn"] = turn

    # Apply small deterministic drift to disposition_score and Plutchik trust.
    try:
        ds = int(npc.get("disposition_score", 50) or 50)
    except Exception:
        ds = 50
    try:
        tr = int(npc.get("trust", 50) or 50)
    except Exception:
        tr = 50
    # Suspicion high hurts disposition/trust; respect helps.
    ds += int((rep - 50) / 25) - int((sus - 30) / 20)
    tr += int((rep - 50) / 30) - int((sus - 35) / 25)
    npc["disposition_score"] = _clamp_int(ds, 0, 100)
    npc["trust"] = _clamp_int(tr, 0, 100)


def apply_beliefs_from_ripple(state: dict[str, Any], rp: dict[str, Any]) -> None:
    """Update NPC beliefs from a surfaced ripple (only for NPCs who can logically know it)."""
    if not isinstance(rp, dict) or rp.get("dropped_by_propagation"):
        return
    npcs = state.get("npcs", {}) or {}
    if not isinstance(npcs, dict) or not npcs:
        return

    text = str(rp.get("text", "") or "")
    prop = str(rp.get("propagation", "local_witness") or "local_witness").lower()
    origin_loc = str(rp.get("origin_location", "") or "").strip().lower()
    origin_faction = str(rp.get("origin_faction", "") or "").strip().lower()
    witnesses = rp.get("witnesses") if isinstance(rp.get("witnesses"), list) else []
    witnesses = [w for w in witnesses if isinstance(w, str)]

    # Topic inference (v1).
    t_low = text.lower()
    if t_low.startswith("[hack]") or "hack" in t_low:
        topic = "player_hacking"
    elif "manhunt" in t_low or "investigation" in t_low or "checkpoint" in t_low or "trace" in t_low:
        topic = "player_trace"
    elif "strike" in t_low or "raid" in t_low:
        topic = "world_conflict"
    else:
        topic = "world_rumor"

    # Confidence by channel.
    conf_map = {"local_witness": 0.85, "witness": 0.85, "contacts": 0.65, "contact_network": 0.65, "broadcast": 0.75, "faction_network": 0.7}
    confidence = conf_map.get(prop, 0.55)

    # Determine targets who can know it (bounded).
    targets: list[tuple[str, dict[str, Any]]] = []
    if witnesses:
        for w in witnesses[:8]:
            d = npcs.get(w)
            if isinstance(d, dict):
                targets.append((w, d))
    else:
        if prop in ("local", "local_witness", "witness"):
            for name, d in list(npcs.items())[:80]:
                if not isinstance(d, dict):
                    continue
                loc = str(d.get("current_location", "") or "").strip().lower() or str(d.get("home_location", "") or "").strip().lower()
                if origin_loc and loc and loc == origin_loc:
                    targets.append((str(name), d))
            targets = targets[:6]
        elif prop in ("contacts", "contact_network", "broadcast", "faction_network"):
            contacts = (state.get("world", {}) or {}).get("contacts", {}) or {}
            if isinstance(contacts, dict):
                relay_allowed = bool(rp.get("relay_pending") is True)
                for name in list(contacts.keys())[:24]:
                    d = npcs.get(str(name))
                    if not isinstance(d, dict):
                        continue
                    if prop == "faction_network" and origin_faction:
                        aff = str(d.get("affiliation", "") or "").strip().lower()
                        if aff != origin_faction:
                            continue
                    if prop in ("contacts", "contact_network") and origin_faction:
                        aff = str(d.get("affiliation", "") or "").strip().lower()
                        if aff == origin_faction:
                            targets.append((str(name), d))
                            continue
                        if relay_allowed and int(d.get("trust", 0) or 0) >= 85:
                            targets.append((str(name), d))
                    else:
                        targets.append((str(name), d))
            targets = targets[:6]

    if not targets:
        return

    for name, npc in targets:
        # Bias: faction-aligned NPCs interpret info differently.
        bias = 0.0
        aff = str(npc.get("affiliation", "") or "").strip().lower()
        if origin_faction and aff:
            if aff == origin_faction:
                bias = +0.2  # more charitable to own side
            elif aff in ("police", "corporate", "black_market") and origin_faction in ("police", "corporate", "black_market"):
                bias = -0.15  # rival framing
        add_belief_snippet(
            state,
            npc,
            topic=topic,
            claim=text.replace("\n", " ").strip(),
            source=prop,
            origin=origin_faction or "world",
            confidence=confidence,
            bias=bias,
        )

        # Optional: rumor spreading (rate-limited, contact-only).
        if npc.get("is_contact") is True and topic in ("player_hacking", "player_trace") and confidence >= 0.65:
            try:
                meta = state.setdefault("meta", {})
                turn = int(meta.get("turn", 0) or 0)
                last = int(meta.get("last_rumor_turn", -999) or -999)
                if turn - last >= 1 and int(npc.get("opportunism", 30) or 0) >= 70:
                    meta["last_rumor_turn"] = turn
                    state.setdefault("active_ripples", []).append(
                        {
                            "text": f"[Rumor] {name}: {text.replace('[', '').replace(']', '')[:90]}",
                            "triggered_day": int(meta.get("day", 1) or 1),
                            "surface_day": int(meta.get("day", 1) or 1) + 1,
                            "surface_time": 8 * 60,
                            "surfaced": False,
                            "propagation": "contacts",
                            "origin_location": origin_loc or str(state.get("player", {}).get("location", "") or "").strip().lower(),
                            "origin_faction": aff or origin_faction or "",
                            "witnesses": [],
                            "surface_attempts": 0,
                        }
                    )
            except Exception:
                pass


def _ensure_psych_fields(n: dict) -> None:
    """Add NPC psychology fields (safe defaults if missing)."""
    n.setdefault("affiliation", "civilian")
    # Plutchik primaries
    n.setdefault("joy", n.get("affection", 0))
    n.setdefault("trust", n.get("trust", n.get("respect", 50)))
    n.setdefault("fear", 10)
    n.setdefault("surprise", 0)
    n.setdefault("sadness", 0)
    n.setdefault("disgust", 0)
    n.setdefault("anger", n.get("resentment", 0))
    n.setdefault("anticipation", n.get("jealousy", 0))
    n.setdefault("opportunism", 30)
    n.setdefault("loyalty", 50)
    n.setdefault("mood", "calm")
    _ensure_belief_fields(n)


def ensure_ambient_npcs(state: dict, action_ctx: dict) -> None:
    """Kalau pemain berinteraksi sosial tapi state kosong, isi NPC keramaian supaya dialog punya anchor."""
    if action_ctx.get("domain") != "social":
        return
    note = action_ctx.get("intent_note", "")
    if note not in ("social_dialogue", "social_scan_crowd", "social_inquiry"):
        return
    npcs = state.setdefault("npcs", {})
    if len(npcs) >= 2:
        return
    day = int(state.get("meta", {}).get("day", 1))
    loc = str(state.get("player", {}).get("location", "") or "").strip()
    for name, score in (("Orang di trotoar", 52), ("Pengunjung warung", 48)):
        if name not in npcs:
            npcs[name] = {
                "name": name,
                "disposition_score": score,
                "disposition_label": _label(score),
                "last_contact_day": day,
                "ambient": True,
                "role": "crowd",
                "home_location": loc,
                "current_location": loc,
                "affiliation": "civilian",
                "joy": 0,
                "trust": 50,
                "fear": 10,
                "surprise": 0,
                "sadness": 0,
                "disgust": 0,
                "anger": 0,
                "anticipation": 0,
                "opportunism": 30,
                "loyalty": 50,
                "mood": "calm",
            }


def update_npcs(state: dict, action_ctx: dict) -> None:
    # Organic news propagation during social talk (rate-limited).
    try:
        if str(action_ctx.get("domain", "") or "").lower() == "social":
            meta = state.get("meta", {}) or {}
            turn = int(meta.get("turn", 0) or 0)
            last = int(meta.get("last_gossip_turn", -999) or -999)
            if turn - last >= 3:
                world = state.get("world", {}) or {}
                news = world.get("news_feed", []) or []
                if isinstance(news, list) and news:
                    pick = None
                    for it in reversed(news[-10:]):
                        if isinstance(it, dict) and it.get("text"):
                            pick = it
                            break
                    if isinstance(pick, dict):
                        txt = str(pick.get("text", "-"))
                        src = str(pick.get("source", "broadcast"))
                        targs = action_ctx.get("targets")
                        if isinstance(targs, list) and targs and isinstance(targs[0], str):
                            npc = (state.get("npcs", {}) or {}).get(targs[0])
                            if isinstance(npc, dict):
                                add_belief_snippet(
                                    state,
                                    npc,
                                    topic="world_news",
                                    claim=txt,
                                    source=f"gossip:{src}",
                                    origin="conversation",
                                    confidence=0.7,
                                    bias=0.0,
                                )
                                state.setdefault("world_notes", []).append(f"[Gossip] {targs[0]} shares: {txt[:90]}")
                                action_ctx["npc_gossip"] = txt[:140]
                                meta["last_gossip_turn"] = turn
    except Exception:
        pass
    ensure_ambient_npcs(state, action_ctx)
    try:
        from engine.npc_emotions import decay_npc_emotions

        decay_npc_emotions(state)
    except Exception:
        pass
    day = int(state.get("meta", {}).get("day", 1))
    time_min = int(state.get("meta", {}).get("time_min", 0))
    world_notes = state.setdefault("world_notes", [])
    contacts = state.setdefault("world", {}).setdefault("contacts", {})
    for name, n in state.setdefault("npcs", {}).items():
        if not isinstance(n, dict):
            continue
        n.setdefault("name", name)
        _ensure_psych_fields(n)
        lc = int(n.get("last_contact_day", day))
        if day - lc > 20:
            n["disposition_score"] = max(0, int(n.get("disposition_score", 50)) - 10)
            n["last_contact_day"] = day
            world_notes.append(f"NPC neglect decay: {n['name']} disposition worsened.")
        s = int(n.get("disposition_score", 50))
        n["disposition_label"] = _label(s)

        # Autonomous agenda tick: NPCs act while player does other things.
        agenda = n.get("agenda")
        if agenda and time_min % 120 == 0:
            n["agenda_tick"] = int(n.get("agenda_tick", 0)) + 1
            world_notes.append(f"NPC:{n['name']} advanced agenda: {agenda}")
            # Consistent low-impact disposition drift from autonomous pressure.
            if "hunt" in str(agenda).lower() or "revenge" in str(agenda).lower():
                n["disposition_score"] = max(0, int(n.get("disposition_score", 50)) - 1)
                n["disposition_label"] = _label(int(n["disposition_score"]))

        # Keep global contacts in sync if flagged.
        if isinstance(contacts, dict) and n.get("is_contact") is True:
            contacts[str(name)] = dict(n)
