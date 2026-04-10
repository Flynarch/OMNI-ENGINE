from __future__ import annotations

import hashlib
from typing import Any


def _clamp_int(v: int, lo: int, hi: int) -> int:
    return max(lo, min(hi, int(v)))


def _norm(s: Any) -> str:
    return str(s or "").strip().lower()


def _det_roll_1_100(*parts: Any) -> int:
    s = "|".join([str(p) for p in parts])
    h = hashlib.md5(s.encode("utf-8", errors="ignore")).hexdigest()
    return (int(h[:8], 16) % 100) + 1


def _sec(npc: dict[str, Any]) -> dict[str, int]:
    """Derived Plutchik secondaries (same logic as UI) for utility scoring."""
    def gi(k: str, default: int) -> int:
        try:
            return int(npc.get(k, default) or default)
        except Exception:
            return default

    joy = gi("joy", gi("affection", 0))
    trust = gi("trust", gi("respect", 50))
    fear = gi("fear", 10)
    surprise = gi("surprise", 0)
    anger = gi("anger", gi("resentment", 0))
    disgust = gi("disgust", 0)
    love = int(round((joy + trust) / 2))
    alarm = int(round((fear + surprise) / 2))
    contempt = int(round((anger + disgust) / 2))
    return {"love": love, "alarm": alarm, "contempt": contempt}


def _belief_summary(npc: dict[str, Any]) -> tuple[int, int]:
    bs = npc.get("belief_summary") or {}
    if not isinstance(bs, dict):
        return (0, 50)
    try:
        sus = int(bs.get("suspicion", 0) or 0)
    except Exception:
        sus = 0
    try:
        rep = int(bs.get("respect", 50) or 50)
    except Exception:
        rep = 50
    return (_clamp_int(sus, 0, 100), _clamp_int(rep, 0, 100))


def _graph_get_edge(world: dict[str, Any], a: str, b: str) -> dict[str, Any] | None:
    g = world.get("social_graph") or {}
    if not isinstance(g, dict):
        return None
    row = g.get(a) or {}
    if not isinstance(row, dict):
        return None
    edge = row.get(b)
    return edge if isinstance(edge, dict) else None


def _graph_set_edge(world: dict[str, Any], a: str, b: str, edge: dict[str, Any]) -> None:
    g = world.setdefault("social_graph", {"__player__": {}})
    if not isinstance(g, dict):
        g = {"__player__": {}}
        world["social_graph"] = g
    row = g.setdefault(a, {})
    if not isinstance(row, dict):
        row = {}
        g[a] = row
    row[b] = dict(edge)


def _graph_bump_player_edge(state: dict[str, Any], npc_name: str, *, delta: int, rel_type: str | None = None) -> None:
    world = state.setdefault("world", {})
    a = "__player__"
    b = str(npc_name)
    meta = state.get("meta", {}) or {}
    day = int(meta.get("day", 1) or 1)
    edge = _graph_get_edge(world, a, b) or {"type": "neutral", "strength": 50, "since_day": day, "last_interaction_day": day}
    try:
        strength = int(edge.get("strength", 50) or 50)
    except Exception:
        strength = 50
    strength = _clamp_int(strength + int(delta), 0, 100)
    edge["strength"] = strength
    edge["last_interaction_day"] = day
    if rel_type:
        edge["type"] = rel_type
    _graph_set_edge(world, a, b, edge)


def _graph_set_player_edge(state: dict[str, Any], npc_name: str, *, rel_type: str, strength: int | None = None) -> None:
    world = state.setdefault("world", {})
    a = "__player__"
    b = str(npc_name)
    meta = state.get("meta", {}) or {}
    day = int(meta.get("day", 1) or 1)
    edge = _graph_get_edge(world, a, b) or {"type": "neutral", "strength": 50, "since_day": day, "last_interaction_day": day}
    edge["type"] = str(rel_type)
    if strength is not None:
        try:
            s = int(strength)
        except Exception:
            s = 50
        edge["strength"] = _clamp_int(s, 0, 100)
    edge["last_interaction_day"] = day
    _graph_set_edge(world, a, b, edge)


def _choose_lod_bucket(name: str, npc: dict[str, Any], *, turn: int, focus: set[str], cur_loc: str) -> int:
    """Return LOD bucket for coarse ticking: 3/6/12 (smaller = more frequent)."""
    if name in focus:
        return 3
    loc = _norm(npc.get("current_location", "")) or _norm(npc.get("home_location", ""))
    if loc and cur_loc and loc == cur_loc:
        return 3
    if npc.get("agenda"):
        return 3
    (sus, _rep) = _belief_summary(npc)
    sec = _sec(npc)
    alarm = sec["alarm"]
    if npc.get("is_contact") is True:
        return 6
    if sus >= 65 or alarm >= 70:
        return 3
    if sus >= 35 or alarm >= 45:
        return 6
    return 12


def _det_pick_location(state: dict[str, Any], *parts: Any) -> str:
    world = state.get("world", {}) or {}
    locs = world.get("locations", {}) or {}
    keys: list[str] = []
    if isinstance(locs, dict):
        keys = [str(k) for k in locs.keys() if str(k).strip()]
    # Always include current player loc as a stable option.
    cur = _norm((state.get("player", {}) or {}).get("location", ""))
    if cur and cur not in keys:
        keys.append(cur)
    if not keys:
        return cur or "unknown"
    keys = sorted(set([_norm(k) for k in keys if _norm(k)]))
    if not keys:
        return cur or "unknown"
    idx = (_det_roll_1_100(*parts) - 1) % len(keys)
    return keys[idx]


def _queue_event(state: dict[str, Any], ev: dict[str, Any]) -> None:
    pe = state.setdefault("pending_events", [])
    if not isinstance(pe, list):
        pe = []
        state["pending_events"] = pe
    pe.append(ev)


def _queue_ripple(state: dict[str, Any], rp: dict[str, Any]) -> None:
    ar = state.setdefault("active_ripples", [])
    if not isinstance(ar, list):
        ar = []
        state["active_ripples"] = ar
    # Dedup by text for non-surfaced.
    text = rp.get("text")
    for x in ar[-25:]:
        if isinstance(x, dict) and x.get("text") == text and not x.get("surfaced"):
            return
    ar.append(rp)


def tick_npc_sim(state: dict[str, Any], action_ctx: dict[str, Any]) -> None:
    """Deterministic NPC simulation tick.

    Complex goals, but bounded:
    - choose up to ~80 NPCs for utility evaluation
    - schedule up to a small number of actions (events/ripples)
    """
    flags = state.get("flags", {}) or {}
    if not bool(flags.get("npc_sim_enabled", True)):
        return

    meta = state.get("meta", {}) or {}
    day = int(meta.get("day", 1) or 1)
    time_min = int(meta.get("time_min", 0) or 0)
    turn = int(meta.get("turn", 0) or 0)

    npcs = state.get("npcs", {}) or {}
    if not isinstance(npcs, dict) or not npcs:
        state.setdefault("meta", {})["npc_sim_last_counts"] = {"evaluated": 0, "actions": 0, "ripples": 0}
        return

    world = state.setdefault("world", {})
    statuses = (world.get("faction_statuses") or {}) if isinstance(world.get("faction_statuses"), dict) else {}
    police_att = str(statuses.get("police", "idle") or "idle").lower()
    cur_loc = _norm((state.get("player", {}) or {}).get("location", ""))

    # Build candidate sets with LOD rules.
    focus: set[str] = set()
    lr = meta.get("last_intent_raw")
    if isinstance(lr, dict) and isinstance(lr.get("targets"), list):
        for t in lr["targets"][:6]:
            if isinstance(t, str):
                focus.add(t)
    nf = meta.get("npc_focus")
    if isinstance(nf, str):
        focus.add(nf)
    contacts = (world.get("contacts") or {}) if isinstance(world.get("contacts"), dict) else {}
    for k in list(contacts.keys())[:25]:
        if isinstance(k, str):
            focus.add(k)

    active_candidates: list[tuple[str, dict[str, Any]]] = []
    coarse_candidates: list[tuple[str, dict[str, Any], int]] = []  # (name,npc,bucket)
    for name, npc in list(npcs.items())[:400]:
        if not isinstance(name, str) or not isinstance(npc, dict):
            continue
        home = _norm(npc.get("current_location", "")) or _norm(npc.get("home_location", ""))
        (sus, _rep) = _belief_summary(npc)
        sec = _sec(npc)
        alarm = sec["alarm"]
        is_active = False
        if name in focus:
            is_active = True
        elif home and cur_loc and home == cur_loc:
            is_active = True
        elif npc.get("agenda"):
            is_active = True
        elif sus >= 65 or alarm >= 70:
            is_active = True
        if is_active:
            active_candidates.append((name, npc))
        else:
            bucket = _choose_lod_bucket(name, npc, turn=turn, focus=focus, cur_loc=cur_loc)
            # Coarse tick on schedule.
            if bucket in (3, 6, 12) and bucket > 0 and (turn % bucket == 0):
                coarse_candidates.append((name, npc, bucket))

    # Cap evaluation budget (active) and coarse budget (lightweight).
    active_candidates = active_candidates[:80]
    coarse_candidates = coarse_candidates[:80]

    actions_scheduled = 0
    ripples_scheduled = 0
    max_actions = 6
    max_ripples = 3
    verbose = bool(flags.get("npc_sim_verbose_notes", False))

    def _prune_intent_queue(planner: dict[str, Any], *, turn_now: int, lod_bucket: int) -> None:
        q = planner.get("intent_queue") or []
        if not isinstance(q, list) or not q:
            planner["intent_queue"] = []
            return
        # Expiry window: keep short to prevent stale actions after travel/state shifts.
        max_age = max(6, int(lod_bucket) * 2)
        keep: list[dict[str, Any]] = []
        for it in q:
            if not isinstance(it, dict):
                continue
            try:
                ct = int(it.get("created_turn", turn_now) or turn_now)
            except Exception:
                ct = turn_now
            if ct >= (turn_now - max_age):
                keep.append(it)
        planner["intent_queue"] = keep[-5:]

    def _ensure_planner(n: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
        planner = n.setdefault("planner", {})
        if not isinstance(planner, dict):
            planner = {}
            n["planner"] = planner
        cds = planner.setdefault("cooldowns", {})
        if not isinstance(cds, dict):
            cds = {}
            planner["cooldowns"] = cds
        return planner, cds

    def _queue_intent(n: dict[str, Any], intent: dict[str, Any]) -> None:
        planner, _cds = _ensure_planner(n)
        lod = int(planner.get("lod_bucket", 6) or 6)
        _prune_intent_queue(planner, turn_now=turn, lod_bucket=lod)
        q = planner.setdefault("intent_queue", [])
        if not isinstance(q, list):
            q = []
            planner["intent_queue"] = q
        # Keep deterministic, bounded queue; avoid stacking identical intent kinds.
        it = dict(intent)
        it.setdefault("created_turn", turn)
        k = _norm(it.get("kind", ""))
        if q:
            last = q[-1]
            if isinstance(last, dict) and _norm(last.get("kind", "")) == k:
                return
        q.append(it)
        planner["intent_queue"] = q[-5:]

    def _exec_intent(name: str, npc: dict[str, Any], intent: dict[str, Any]) -> None:
        nonlocal actions_scheduled, ripples_scheduled
        kind = _norm(intent.get("kind", ""))
        aff = _norm(npc.get("affiliation", "civilian"))
        role = _norm(npc.get("role", "civilian")) or "civilian"
        (sus, rep) = _belief_summary(npc)
        sec = _sec(npc)
        love, alarm, contempt = sec["love"], sec["alarm"], sec["contempt"]
        try:
            loyalty = int(npc.get("loyalty", 50) or 50)
        except Exception:
            loyalty = 50

        # Always respect hard caps.
        if kind in ("ripple", "warn", "rumor", "avoid", "seek_help", "move") and ripples_scheduled >= max_ripples:
            return
        if kind in ("event", "report", "offer", "trade", "sell_info") and actions_scheduled >= max_actions:
            return

        # Intent kinds map to existing scheduling primitives.
        if kind == "avoid":
            _queue_ripple(
                state,
                {
                    "kind": "npc_avoid",
                    "text": f"{name} menghindari keterlibatan (dingin).",
                    "triggered_day": day,
                    "surface_day": day,
                    "surface_time": min(1439, time_min + 8),
                    "surfaced": False,
                    "propagation": "contacts" if npc.get("is_contact") is True else "local_witness",
                    "origin_location": _norm(npc.get("current_location", "")) or _norm(npc.get("home_location", "")) or cur_loc,
                    "origin_faction": aff,
                    "witnesses": [],
                    "surface_attempts": 0,
                    "meta": {"npc": name, "alarm": alarm, "contempt": contempt},
                },
            )
            ripples_scheduled += 1
            actions_scheduled += 1
            _graph_bump_player_edge(state, name, delta=-2, rel_type="nemesis" if contempt >= 90 else "rival" if contempt >= 75 else None)
            return

        if kind == "move":
            here = _norm(npc.get("current_location", "")) or _norm(npc.get("home_location", "")) or cur_loc
            dest = _norm(intent.get("to", "")) or _det_pick_location(state, "npc_move_intent", day, turn, name, here)
            if dest and dest != here:
                # Preserve home_location; move is a current-location change.
                if not _norm(npc.get("home_location", "")):
                    npc["home_location"] = here
                npc["current_location"] = dest
                _queue_ripple(
                    state,
                    {
                        "kind": "npc_move",
                        "text": f"{name} pindah lokasi.",
                        "triggered_day": day,
                        "surface_day": day,
                        "surface_time": min(1439, time_min + 18),
                        "surfaced": False,
                        "propagation": "local_witness",
                        "origin_location": here,
                        "origin_faction": aff,
                        "witnesses": [],
                        "surface_attempts": 0,
                        "meta": {"npc": name, "from": here, "to": dest},
                    },
                )
                ripples_scheduled += 1
                actions_scheduled += 1
            return

        if kind in ("offer", "trade"):
            svc = str(intent.get("service", "") or "").strip() or ("cleaner_alibi" if role == "fixer" else "cheap_goods")
            _queue_event(
                state,
                {
                    "event_type": "npc_offer",
                    "title": f"{name} offers ({svc})",
                    "due_day": day,
                    "due_time": min(1439, time_min + 30),
                    "triggered": False,
                    "payload": {
                        "npc": name,
                        "role": role,
                        "service": svc,
                        "respect": rep,
                        "suspicion": sus,
                        "origin_location": _norm(npc.get("current_location", "")) or _norm(npc.get("home_location", "")) or cur_loc,
                        "origin_faction": aff,
                    },
                },
            )
            actions_scheduled += 1
            return

        if kind in ("sell_info",):
            buyer = _norm(intent.get("buyer_faction", "")) or (aff if aff in ("corporate", "police", "black_market") else "black_market")
            _queue_event(
                state,
                {
                    "event_type": "npc_sell_info",
                    "title": f"{name} sells intel ({buyer})",
                    "due_day": day,
                    "due_time": min(1439, time_min + 35),
                    "triggered": False,
                    "payload": {
                        "npc": name,
                        "buyer_faction": buyer,
                        "suspicion": sus,
                        "origin_location": _norm(npc.get("current_location", "")) or _norm(npc.get("home_location", "")) or cur_loc,
                        "origin_faction": aff,
                    },
                },
            )
            actions_scheduled += 1
            _graph_set_player_edge(state, name, rel_type="informant" if buyer == "police" else "nemesis" if contempt >= 90 else "rival")
            return

        if kind == "seek_help":
            _queue_ripple(
                state,
                {
                    "kind": "npc_seek_help",
                    "text": f"{name}: butuh bantuan / info (ada risiko).",
                    "triggered_day": day,
                    "surface_day": day,
                    "surface_time": min(1439, time_min + 12),
                    "surfaced": False,
                    "propagation": "contacts" if npc.get("is_contact") is True else "local_witness",
                    "origin_location": _norm(npc.get("current_location", "")) or _norm(npc.get("home_location", "")) or cur_loc,
                    "origin_faction": aff,
                    "witnesses": [],
                    "surface_attempts": 0,
                    "meta": {"npc": name, "alarm": alarm, "suspicion": sus, "affiliation": aff},
                },
            )
            ripples_scheduled += 1
            actions_scheduled += 1
            if love >= 85 and loyalty >= 85:
                _graph_set_player_edge(state, name, rel_type="partner")
            elif love >= 85:
                _graph_set_player_edge(state, name, rel_type="lover")
            elif aff in ("corporate", "police"):
                _graph_set_player_edge(state, name, rel_type="handler")
            return

    # Execute queued intents first (bounded), so NPC can "follow through" instead of re-deciding every tick.
    for name, npc in active_candidates[:25]:
        planner, _cds = _ensure_planner(npc)
        lod = int(planner.get("lod_bucket", 3) or 3)
        _prune_intent_queue(planner, turn_now=turn, lod_bucket=lod)
        q = planner.get("intent_queue") or []
        if isinstance(q, list) and q and (actions_scheduled < max_actions or ripples_scheduled < max_ripples):
            intent0 = q.pop(0)
            if isinstance(intent0, dict):
                _exec_intent(name, npc, intent0)
            planner["intent_queue"] = q

    # First: coarse ticks (lightweight, but not "skip total").
    for name, npc, bucket in coarse_candidates:
        planner, cds = _ensure_planner(npc)
        planner["lod_bucket"] = bucket
        planner["last_coarse_turn"] = turn
        _prune_intent_queue(planner, turn_now=turn, lod_bucket=bucket)

        # Lightweight actions for coarse NPCs: move_location / trade refresh / avoid.
        role = _norm(npc.get("role", "civilian")) or "civilian"
        aff = _norm(npc.get("affiliation", "civilian"))
        (sus, rep) = _belief_summary(npc)
        sec = _sec(npc)
        love, alarm, contempt = sec["love"], sec["alarm"], sec["contempt"]

        # Coarse avoid_player: reduce relationship a bit if contempt/alarm high.
        if cds.get("avoid_player", 0) <= turn and (contempt >= 70 or alarm >= 75) and actions_scheduled < max_actions and ripples_scheduled < max_ripples:
            cds["avoid_player"] = turn + bucket
            _queue_intent(npc, {"kind": "avoid"})

        # Coarse move_location for non-contacts (locals/ambient) if alarm very high.
        if npc.get("is_contact") is not True and cds.get("move_location", 0) <= turn and alarm >= 85 and actions_scheduled < max_actions:
            cds["move_location"] = turn + bucket * 2
            _queue_intent(npc, {"kind": "move"})

        # Coarse trade: merchants periodically surface offers even when not active.
        if role == "merchant" and cds.get("trade", 0) <= turn and actions_scheduled < max_actions:
            # Respect-based offer cadence.
            cds["trade"] = turn + max(3, bucket)
            goods = ["electronics", "food", "medical"]
            pick = (_det_roll_1_100("npc_trade", day, turn, name) - 1) % len(goods)
            svc = f"trade:{goods[pick]}"
            _queue_intent(npc, {"kind": "trade", "service": svc})
            # Merchant offers tend to create small "debt" relationship if respect is low.
            if rep >= 78 and sus <= 45:
                _graph_set_player_edge(state, name, rel_type="business_partner")
            elif rep < 55 and sus < 60:
                _graph_set_player_edge(state, name, rel_type="debt")
            else:
                _graph_bump_player_edge(state, name, delta=+1, rel_type="ally" if rep >= 70 else None)

        # Execute at most 1 queued intent per coarse NPC per coarse tick.
        q2 = planner.get("intent_queue") or []
        if isinstance(q2, list) and q2 and (actions_scheduled < max_actions or ripples_scheduled < max_ripples):
            i0 = q2.pop(0)
            if isinstance(i0, dict):
                _exec_intent(name, npc, i0)
            planner["intent_queue"] = q2

    # Second: active utility eval (full).
    for name, npc in active_candidates:
        # Per-NPC cooldowns
        planner, cds = _ensure_planner(npc)
        planner["lod_bucket"] = 3

        last_act = int(planner.get("last_action_turn", -999) or -999)
        if turn - last_act < 1 and name not in focus:
            continue

        aff = _norm(npc.get("affiliation", "civilian"))
        role = _norm(npc.get("role", "civilian"))
        if role == "":
            role = "civilian"

        (sus, rep) = _belief_summary(npc)
        sec = _sec(npc)
        love, alarm, contempt = sec["love"], sec["alarm"], sec["contempt"]
        try:
            opp = int(npc.get("opportunism", 30) or 0)
        except Exception:
            opp = 30
        try:
            loyalty = int(npc.get("loyalty", 50) or 0)
        except Exception:
            loyalty = 50

        # Candidate actions with utility.
        best_action = "idle"
        best_score = 0

        # 1) spread_rumor (contacts) about hacking/trace if suspicion high.
        if actions_scheduled < max_actions and ripples_scheduled < max_ripples:
            if cds.get("spread_rumor", 0) <= turn:
                base = 0
                base += int((sus - 40) / 2)
                base += int((opp - 50) / 3)
                if police_att in ("investigated", "manhunt"):
                    base += 8
                if love >= 70 or loyalty >= 80:
                    base -= 10
                if base > best_score:
                    best_score = base
                    best_action = "spread_rumor"

        # 2) warn_player (contact) if alarm high and love/loyalty decent.
        if actions_scheduled < max_actions and ripples_scheduled < max_ripples:
            if cds.get("warn_player", 0) <= turn and npc.get("is_contact") is True:
                base = 0
                base += int((alarm - 45) / 2)
                base += int((love - 50) / 4)
                base += int((loyalty - 50) / 5)
                base -= int((sus - 50) / 4)
                if base > best_score:
                    best_score = base
                    best_action = "warn_player"

        # 3) report_to_police (informant / police) if suspicion high and opportunism high.
        if actions_scheduled < max_actions:
            if cds.get("report_to_police", 0) <= turn:
                base = 0
                base += int((sus - 55) / 2)
                base += int((opp - 50) / 3)
                if aff == "police" or role == "informant":
                    base += 10
                if love >= 70 or loyalty >= 80:
                    base -= 14
                if base > best_score:
                    best_score = base
                    best_action = "report_to_police"

        # 4) offer_service (fixer/merchant) if respect high and suspicion low.
        if actions_scheduled < max_actions:
            if role in ("fixer", "merchant") and cds.get("offer_service", 0) <= turn:
                base = 0
                base += int((rep - 50) / 3)
                base -= int((sus - 30) / 3)
                base += 6 if role == "fixer" else 3
                if base > best_score:
                    best_score = base
                    best_action = "offer_service"

        # 5) trade (merchant) if respect ok and not too suspicious.
        if actions_scheduled < max_actions:
            if role == "merchant" and cds.get("trade", 0) <= turn:
                base = 0
                base += int((rep - 45) / 3)
                base -= int((sus - 35) / 3)
                base += 4
                if base > best_score:
                    best_score = base
                    best_action = "trade"

        # 6) sell_info (informant/fixer) if opportunism high and suspicion high.
        if actions_scheduled < max_actions:
            if role in ("informant", "fixer") and cds.get("sell_info", 0) <= turn:
                base = 0
                base += int((sus - 50) / 2)
                base += int((opp - 50) / 3)
                if aff in ("police", "corporate", "black_market"):
                    base += 6
                if love >= 70 or loyalty >= 80:
                    base -= 12
                if base > best_score:
                    best_score = base
                    best_action = "sell_info"

        # 7) seek_help (contact asks you / their network) if alarm high.
        if actions_scheduled < max_actions and ripples_scheduled < max_ripples:
            if cds.get("seek_help", 0) <= turn and alarm >= 70:
                base = 0
                base += int((alarm - 55) / 2)
                base += int((love - 50) / 4)
                base -= int((sus - 50) / 4)
                if npc.get("is_contact") is True:
                    base += 4
                if base > best_score:
                    best_score = base
                    best_action = "seek_help"

        # 8) avoid_player (active) if contempt/alarm high.
        if actions_scheduled < max_actions and ripples_scheduled < max_ripples:
            if cds.get("avoid_player", 0) <= turn and (contempt >= 65 or alarm >= 80):
                base = 0
                base += int((contempt - 50) / 2)
                base += int((alarm - 60) / 3)
                base -= int((love - 60) / 4)
                if base > best_score:
                    best_score = base
                    best_action = "avoid_player"

        # 9) move_location (active) for non-contacts if alarm high.
        if actions_scheduled < max_actions:
            if npc.get("is_contact") is not True and cds.get("move_location", 0) <= turn and alarm >= 75:
                base = 0
                base += int((alarm - 60) / 2)
                base += int((sus - 50) / 4)
                if base > best_score:
                    best_score = base
                    best_action = "move_location"

        # Thresholds (deterministic).
        trigger_roll = _det_roll_1_100(day, turn, name, best_action, police_att)
        if best_action == "idle":
            continue
        if best_score < 10:
            continue
        if trigger_roll > min(95, 55 + best_score):
            continue

        # Execute chosen action.
        planner["last_action_turn"] = turn

        if best_action == "spread_rumor" and actions_scheduled < max_actions and ripples_scheduled < max_ripples:
            cds["spread_rumor"] = turn + 3
            txt = f"{name} membisikkan: player mencurigakan (sus={sus})."
            _queue_ripple(
                state,
                {
                    "kind": "npc_rumor",
                    "text": txt,
                    "triggered_day": day,
                    "surface_day": day,
                    "surface_time": min(1439, time_min + 30),
                    "surfaced": False,
                    "propagation": "contacts",
                    "origin_location": cur_loc,
                    "origin_faction": aff,
                    "witnesses": [],
                    "surface_attempts": 0,
                    "meta": {"npc": name, "suspicion": sus},
                },
            )
            ripples_scheduled += 1
            actions_scheduled += 1
            if verbose:
                state.setdefault("world_notes", []).append(f"[NPCSim] rumor by {name}")

        elif best_action == "warn_player" and actions_scheduled < max_actions and ripples_scheduled < max_ripples:
            cds["warn_player"] = turn + 4
            txt = f"{name}: ada tekanan meningkat (police={police_att})."
            _queue_ripple(
                state,
                {
                    "kind": "npc_warn",
                    "text": txt,
                    "triggered_day": day,
                    "surface_day": day,
                    "surface_time": min(1439, time_min + 20),
                    "surfaced": False,
                    "propagation": "contacts",
                    "origin_location": cur_loc,
                    "origin_faction": aff,
                    "witnesses": [],
                    "surface_attempts": 0,
                    "meta": {"npc": name, "police_attention": police_att, "alarm": alarm},
                },
            )
            ripples_scheduled += 1
            actions_scheduled += 1
            _graph_bump_player_edge(state, name, delta=+1, rel_type="ally" if love >= 70 else None)
            if verbose:
                state.setdefault("world_notes", []).append(f"[NPCSim] warn by {name}")

        elif best_action == "report_to_police" and actions_scheduled < max_actions:
            cds["report_to_police"] = turn + 5
            _queue_event(
                state,
                {
                    "event_type": "npc_report",
                    "title": f"NPC report filed: {name}",
                    "due_day": day,
                    "due_time": min(1439, time_min + 45),
                    "triggered": False,
                    "payload": {
                        "reporter": name,
                        "affiliation": aff,
                        "suspicion": sus,
                        "origin_location": _norm(npc.get("current_location", "")) or _norm(npc.get("home_location", "")) or cur_loc,
                        "origin_faction": aff,
                    },
                },
            )
            actions_scheduled += 1
            _graph_set_player_edge(
                state,
                name,
                rel_type="informant" if role == "informant" or aff == "police" else "nemesis" if contempt >= 90 else "rival",
            )
            _graph_bump_player_edge(state, name, delta=-2)
            if verbose:
                state.setdefault("world_notes", []).append(f"[NPCSim] report by {name}")

        elif best_action == "offer_service" and actions_scheduled < max_actions:
            cds["offer_service"] = turn + 6
            service = "cleaner_alibi" if role == "fixer" else "cheap_goods"
            _queue_event(
                state,
                {
                    "event_type": "npc_offer",
                    "title": f"{name} offers a service ({service})",
                    "due_day": day,
                    "due_time": min(1439, time_min + 60),
                    "triggered": False,
                    "payload": {
                        "npc": name,
                        "role": role,
                        "service": service,
                        "respect": rep,
                        "suspicion": sus,
                        "origin_location": _norm(npc.get("current_location", "")) or _norm(npc.get("home_location", "")) or cur_loc,
                        "origin_faction": aff,
                    },
                },
            )
            actions_scheduled += 1
            if role == "fixer" and rep >= 82 and sus <= 35:
                _graph_set_player_edge(state, name, rel_type="mentor")
                _graph_bump_player_edge(state, name, delta=+1)
            elif role == "fixer" and rep < 55:
                _graph_set_player_edge(state, name, rel_type="debt")
                _graph_bump_player_edge(state, name, delta=+1)
            else:
                _graph_bump_player_edge(state, name, delta=+1, rel_type="ally" if rep >= 70 else None)
            if verbose:
                state.setdefault("world_notes", []).append(f"[NPCSim] offer by {name}")

        elif best_action == "trade" and actions_scheduled < max_actions:
            cds["trade"] = turn + 5
            goods = ["electronics", "food", "medical", "transport"]
            pick = (_det_roll_1_100("npc_trade_active", day, turn, name) - 1) % len(goods)
            svc = f"trade:{goods[pick]}"
            _queue_event(
                state,
                {
                    "event_type": "npc_offer",
                    "title": f"{name} offers trade ({svc})",
                    "due_day": day,
                    "due_time": min(1439, time_min + 35),
                    "triggered": False,
                    "payload": {
                        "npc": name,
                        "role": role,
                        "service": svc,
                        "respect": rep,
                        "suspicion": sus,
                        "origin_location": _norm(npc.get("current_location", "")) or _norm(npc.get("home_location", "")) or cur_loc,
                        "origin_faction": aff,
                    },
                },
            )
            actions_scheduled += 1
            _graph_bump_player_edge(state, name, delta=+1, rel_type="ally" if rep >= 70 else None)

        elif best_action == "sell_info" and actions_scheduled < max_actions:
            cds["sell_info"] = turn + 7
            # Who is buying? Prefer faction-aligned buyers.
            buyer = aff if aff in ("corporate", "police", "black_market") else "black_market"
            _queue_event(
                state,
                {
                    "event_type": "npc_sell_info",
                    "title": f"{name} sells intel ({buyer})",
                    "due_day": day,
                    "due_time": min(1439, time_min + 50),
                    "triggered": False,
                    "payload": {
                        "npc": name,
                        "buyer_faction": buyer,
                        "suspicion": sus,
                        "opportunism": opp,
                        "origin_location": _norm(npc.get("current_location", "")) or _norm(npc.get("home_location", "")) or cur_loc,
                        "origin_faction": aff,
                    },
                },
            )
            actions_scheduled += 1
            _graph_set_player_edge(state, name, rel_type="informant" if buyer == "police" else "nemesis" if contempt >= 90 else "rival")
            _graph_bump_player_edge(state, name, delta=-1)

        elif best_action == "seek_help" and actions_scheduled < max_actions and ripples_scheduled < max_ripples:
            cds["seek_help"] = turn + 6
            _queue_ripple(
                state,
                {
                    "kind": "npc_seek_help",
                    "text": f"{name}: butuh bantuan / info (ada risiko).",
                    "triggered_day": day,
                    "surface_day": day,
                    "surface_time": min(1439, time_min + 15),
                    "surfaced": False,
                    "propagation": "contacts" if npc.get("is_contact") is True else "local_witness",
                    "origin_location": _norm(npc.get("current_location", "")) or _norm(npc.get("home_location", "")) or cur_loc,
                    "origin_faction": aff,
                    "witnesses": [],
                    "surface_attempts": 0,
                    "meta": {"npc": name, "alarm": alarm, "suspicion": sus, "affiliation": aff},
                },
            )
            ripples_scheduled += 1
            actions_scheduled += 1
            # Edge typing: handler/lover depending on context.
            if love >= 85 and loyalty >= 85:
                _graph_set_player_edge(state, name, rel_type="partner")
            elif love >= 85:
                _graph_set_player_edge(state, name, rel_type="lover")
            elif aff in ("corporate", "police"):
                _graph_set_player_edge(state, name, rel_type="handler")
            else:
                _graph_bump_player_edge(state, name, delta=+1, rel_type="ally" if love >= 70 else None)

        elif best_action == "avoid_player" and actions_scheduled < max_actions and ripples_scheduled < max_ripples:
            cds["avoid_player"] = turn + 5
            _queue_ripple(
                state,
                {
                    "kind": "npc_avoid",
                    "text": f"{name} menghindari kamu (dingin / defensif).",
                    "triggered_day": day,
                    "surface_day": day,
                    "surface_time": min(1439, time_min + 10),
                    "surfaced": False,
                    "propagation": "contacts" if npc.get("is_contact") is True else "local_witness",
                    "origin_location": _norm(npc.get("current_location", "")) or _norm(npc.get("home_location", "")) or cur_loc,
                    "origin_faction": aff,
                    "witnesses": [],
                    "surface_attempts": 0,
                    "meta": {"npc": name, "alarm": alarm, "contempt": contempt},
                },
            )
            ripples_scheduled += 1
            actions_scheduled += 1
            _graph_bump_player_edge(state, name, delta=-2, rel_type="nemesis" if contempt >= 90 else "rival" if contempt >= 75 else None)

        elif best_action == "move_location" and actions_scheduled < max_actions:
            cds["move_location"] = turn + 8
            here = _norm(npc.get("current_location", "")) or _norm(npc.get("home_location", "")) or cur_loc
            dest = _det_pick_location(state, "npc_move_active", day, turn, name, here)
            if dest and dest != here:
                if not _norm(npc.get("home_location", "")):
                    npc["home_location"] = here
                npc["current_location"] = dest
                _queue_ripple(
                    state,
                    {
                        "kind": "npc_move",
                        "text": f"{name} menghilang dari area (pindah lokasi).",
                        "triggered_day": day,
                        "surface_day": day,
                        "surface_time": min(1439, time_min + 30),
                        "surfaced": False,
                        "propagation": "local_witness",
                        "origin_location": here,
                        "origin_faction": aff,
                        "witnesses": [],
                        "surface_attempts": 0,
                        "meta": {"npc": name, "from": here, "to": dest},
                    },
                )
                ripples_scheduled += 1
                actions_scheduled += 1
                _graph_bump_player_edge(state, name, delta=-1)

    state.setdefault("meta", {})["npc_sim_last_counts"] = {
        "evaluated": len(active_candidates),
        "coarse": len(coarse_candidates),
        "actions": actions_scheduled,
        "ripples": ripples_scheduled,
    }

