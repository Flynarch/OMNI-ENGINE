from __future__ import annotations

import hashlib
import random
from typing import Any


def _hash_to_seed(text: str) -> int:
    h = hashlib.md5(text.encode("utf-8", errors="ignore")).hexdigest()
    return int(h[:8], 16)


def ensure_location_factions(state: dict[str, Any]) -> None:
    """Ensure factions are per-location and stable.

    - Baseline is deterministic per (seed_pack|location).
    - Faction deltas persist per location across travel (no accidental reset).
    """
    world = state.setdefault("world", {})
    world.setdefault("conflict_model", "corporate_vs_police_with_black_market")
    world.setdefault("locations", {})
    loc_store = world.get("locations")
    if not isinstance(loc_store, dict):
        loc_store = {}
        world["locations"] = loc_store

    loc = str(state.get("player", {}).get("location", "") or "").strip().lower()
    meta = state.get("meta", {}) or {}
    # Use stable world_seed so baselines don't change when travel loads a different location seed pack.
    world_seed = str((meta.get("world_seed", "") if isinstance(meta, dict) else "") or "").strip().lower()
    if not world_seed:
        world_seed = str((meta.get("seed_pack", "") if isinstance(meta, dict) else "") or "").strip().lower()
    base_key = f"{world_seed}|{loc}"
    if not loc:
        return

    loc_store.setdefault(loc, {})
    slot = loc_store.get(loc)
    if not isinstance(slot, dict):
        slot = {}
        loc_store[loc] = slot
    slot.setdefault("factions_seed_key", "")
    factions = slot.setdefault("factions", {})
    if not isinstance(factions, dict):
        factions = {}
        slot["factions"] = factions

    # Ensure keys exist even if factions was partially seeded.
    factions.setdefault("corporate", {"stability": 50, "power": 50})
    factions.setdefault("police", {"stability": 50, "power": 50})
    factions.setdefault("black_market", {"stability": 50, "power": 50})

    # Only (re)seed when we enter a new location/seed_pack context.
    if str(slot.get("factions_seed_key", "")) == base_key and factions:
        # Make sure world.factions points to the active location's factions dict.
        world["factions"] = factions
        return
    slot["factions_seed_key"] = base_key

    rng = random.Random(_hash_to_seed(base_key))
    # Location baseline (v1)
    corp_st = max(10, min(90, 50 + rng.randint(-18, 18)))
    pol_st = max(10, min(90, 50 + rng.randint(-18, 18)))
    bm_st = max(10, min(90, 50 + rng.randint(-18, 18)))

    # Power derived from stability, plus a little chaos.
    factions["corporate"]["stability"] = corp_st
    factions["police"]["stability"] = pol_st
    factions["black_market"]["stability"] = bm_st

    factions["corporate"]["power"] = max(10, min(100, 40 + (corp_st // 2) + rng.randint(-10, 20)))
    factions["police"]["power"] = max(10, min(100, 40 + (pol_st // 2) + rng.randint(-10, 20)))
    factions["black_market"]["power"] = max(10, min(100, 40 + (bm_st // 2) + rng.randint(-10, 20)))

    # Point world-level view to active location factions (mutations persist in slot dict).
    slot["factions"] = factions
    loc_store[loc] = slot
    world["locations"] = loc_store
    world["factions"] = factions


def _contains_any(hay: str, needles: list[str]) -> bool:
    h = hay.lower()
    return any(n in h for n in needles)


def _cash_apply(econ: dict[str, Any], delta: int) -> None:
    if delta == 0:
        return
    cash = int(econ.get("cash", 0) or 0) + int(delta)
    econ["cash"] = cash
    # If cash drops below 0, mirror into bank/debt in a way consistent with update_economy.
    if cash < 0:
        deficit = abs(cash)
        bank = int(econ.get("bank", 0) or 0)
        if bank >= deficit:
            bank -= deficit
            econ["bank"] = bank
            econ["cash"] = 0
        else:
            econ["cash"] = 0
            econ["bank"] = 0
            econ["debt"] = int(econ.get("debt", 0) or 0) + (deficit - bank)


def ensure_hacking_heat(state: dict[str, Any]) -> dict[str, Any]:
    world = state.setdefault("world", {})
    hh = world.setdefault("hacking_heat", {})
    if not isinstance(hh, dict):
        hh = {}
        world["hacking_heat"] = hh
    world.setdefault("last_hacking_heat_decay_day", 0)
    return hh


def decay_hacking_heat(state: dict[str, Any]) -> None:
    """Daily decay of hacking heat (cooldown).

    This does NOT change sim clock; it just relaxes accumulated heat once per day.
    """
    meta = state.get("meta", {}) or {}
    day = int(meta.get("day", 1) or 1)
    world = state.setdefault("world", {})
    last = int(world.get("last_hacking_heat_decay_day", 0) or 0)
    if last >= day:
        return
    world["last_hacking_heat_decay_day"] = day

    hh = ensure_hacking_heat(state)
    for k in list(hh.keys()):
        row = hh.get(k)
        if not isinstance(row, dict):
            hh.pop(k, None)
            continue
        try:
            heat = int(row.get("heat", 0) or 0)
        except Exception:
            heat = 0
        try:
            signal = int(row.get("signal", 0) or 0)
        except Exception:
            signal = 0
        try:
            noise = int(row.get("noise", 0) or 0)
        except Exception:
            noise = 0
        # Cooldown curve: decays faster when low, slower when very high.
        dec = 18 if heat <= 40 else 12 if heat <= 75 else 8
        heat = max(0, heat - dec)
        # Noise decays faster than signal; signal is "subtle fingerprint".
        noise = max(0, noise - (24 if noise <= 40 else 16 if noise <= 75 else 10))
        signal = max(0, signal - (10 if signal <= 40 else 8 if signal <= 75 else 6))
        if heat <= 0:
            hh.pop(k, None)
        else:
            row["heat"] = heat
            row["signal"] = signal
            row["noise"] = noise


def _inv_tokens(inv: dict[str, Any]) -> list[str]:
    toks: list[str] = []
    for key in ("r_hand", "l_hand", "worn"):
        v = inv.get(key)
        if isinstance(v, str) and v.strip() and v.strip() != "-":
            toks.append(v.strip().lower())
    for key in ("pocket_contents", "bag_contents"):
        arr = inv.get(key) or []
        if isinstance(arr, list):
            for x in arr[:40]:
                if isinstance(x, str):
                    toks.append(x.lower())
                elif isinstance(x, dict):
                    toks.append(str(x.get("id", x.get("name", "")) or "").lower())
    return [t for t in toks if t]


def _has_any_tool(inv: dict[str, Any], needles: tuple[str, ...]) -> bool:
    toks = _inv_tokens(inv)
    for t in toks:
        if any(n in t for n in needles):
            return True
    return False


def _heat_key(state: dict[str, Any], target: str) -> str:
    loc = str(state.get("player", {}).get("location", "") or "").strip().lower()
    return f"{loc}|{target}".strip("|")

def _roll_to_grade(roll_pkg: dict[str, Any], *, bonus_margin: int = 0) -> str:
    """Return: critical_success/success/partial/failure/critical_failure."""
    oc = str(roll_pkg.get("outcome", "") or "")
    if "Critical Success" in oc:
        return "critical_success"
    if "Critical Failure" in oc:
        return "critical_failure"
    if "Success" in oc:
        return "success"
    if "Failure" in oc:
        # Partial success: near miss (roll just above threshold), with gear/skill margin.
        try:
            roll = int(roll_pkg.get("roll", 0) or 0)
            thr = int(roll_pkg.get("net_threshold", 0) or 0)
        except Exception:
            return "failure"
        margin = 10 + max(0, int(bonus_margin))
        if roll > thr and roll <= (thr + margin):
            return "partial"
        return "failure"
    return "failure"


def _is_cover_tracks(normalized: str) -> bool:
    n = normalized.lower()
    return any(
        k in n
        for k in (
            "cover tracks",
            "cover jejak",
            "hapus jejak",
            "hapus log",
            "bersihkan log",
            "clean logs",
            "clear logs",
            "wipe logs",
            "hapus bukti",
            "hapus evidence",
            "bersihkan jejak",
        )
    )


def _push_news(state: dict[str, Any], *, text: str, source: str) -> None:
    """Append a bounded headline into world.news_feed."""
    from engine.social.news import push_news

    push_news(state, text=text, source=source)


def _enqueue_ripple(state: dict[str, Any], rp: dict[str, Any]) -> None:
    """Add a ripple to active_ripples with shared dedup semantics."""
    from engine.social.ripple_queue import enqueue_ripple

    enqueue_ripple(state, rp)


def apply_hacking_after_roll(
    state: dict[str, Any],
    action_ctx: dict[str, Any],
    roll_pkg: dict[str, Any],
) -> None:
    """Apply deterministic world+economy consequences for hacking rolls."""
    if str(action_ctx.get("domain", "")).lower() != "hacking":
        return

    ensure_location_factions(state)
    world = state.setdefault("world", {})
    factions = world.setdefault("factions", {})
    econ = state.setdefault("economy", {})

    inv = state.get("inventory", {}) or {}
    # Tooling: allow inventory to influence heat/trace/econ scaling.
    stealth_tool = _has_any_tool(inv, ("vpn", "proxy", "tor", "burner", "spoof", "scrambler"))
    exploit_tool = _has_any_tool(inv, ("exploit", "kit", "zero_day", "0day", "payload"))
    forensic_tool = _has_any_tool(inv, ("forensic", "sniffer", "log", "scanner"))

    normalized = str(action_ctx.get("normalized_input", "") or "").lower()
    visibility = str(action_ctx.get("visibility", "public") or "public").lower()
    stealth = visibility in ("low", "private", "stealth")

    # "Penting" targets force attention and stronger consequences.
    critical_keywords = (
        "penting",
        "utama",
        "core",
        "server",
        "database",
        "pusat",
        "infrastruktur",
        "utama",
        "gateway",
        "controller",
        "operator",
        "kunci",
        "main",
        "backbone",
        "data center",
        "data-center",
        "telekom",
        "jaringan",
    )
    is_critical = any(k in normalized for k in critical_keywords)

    # Detection/attention scales:
    # - stealth + not critical => mostly quiet (local): low trace delta + small faction shifts.
    # - otherwise => noticeable/investigated faster.
    if is_critical:
        trace_delta = 60
        faction_scale = 1.2
        econ_scale = 1.0
    elif stealth:
        trace_delta = 8
        faction_scale = 0.4
        econ_scale = 0.8
    else:
        trace_delta = 18
        faction_scale = 1.0
        econ_scale = 1.0
    target = "corporate"
    if _contains_any(normalized, ["polisi", "police", "security", "keamanan", "agen keamanan"]):
        target = "police"
    elif _contains_any(normalized, ["pasar gelap", "black market", "blackmarket", "pasar", "gelap"]):
        target = "black_market"

    outcome = str(roll_pkg.get("outcome", "") or "")
    success = any(s in outcome for s in ("Success", "Critical Success"))
    cover_tracks = _is_cover_tracks(normalized)

    # Heat model (cooldown/pressure) per location+target.
    # Heat makes future hacks noisier and less profitable until it cools down.
    hh = ensure_hacking_heat(state)
    hk = _heat_key(state, target)
    row = hh.setdefault(hk, {"heat": 0})
    try:
        heat = int((row or {}).get("heat", 0) or 0)
    except Exception:
        heat = 0

    # Skill/gear can widen "partial success" band a bit.
    hack_skill = 0
    try:
        sk = (state.get("skills", {}) or {}).get("hacking")
        if isinstance(sk, dict):
            hack_skill = int(sk.get("current", sk.get("base", 10)) or 0)
        else:
            hack_skill = int(sk or 0)
    except Exception:
        hack_skill = 0
    bonus_margin = min(12, max(0, hack_skill // 10) + (3 if exploit_tool else 0))
    grade = _roll_to_grade(roll_pkg, bonus_margin=bonus_margin)

    # Apply tooling modifiers.
    if stealth_tool:
        trace_delta = int(trace_delta * 0.85)
    if exploit_tool:
        econ_scale = float(econ_scale) * 1.1
        faction_scale = float(faction_scale) * 1.05
    if forensic_tool and not stealth:
        # Using noisy forensic tools can increase signature.
        trace_delta = int(trace_delta * 1.1)

    # Heat influences (soft) scaling; keep bounded so it doesn't explode.
    # Use noise component if present, otherwise fallback to heat.
    try:
        noise_level = int((row or {}).get("noise", heat) or heat)
    except Exception:
        noise_level = heat
    try:
        signal_level = int((row or {}).get("signal", heat // 2) or (heat // 2))
    except Exception:
        signal_level = heat // 2

    heat_trace_boost = 1.0 + min(0.60, noise_level / 180.0)  # up to +60%
    heat_econ_penalty = max(0.60, 1.0 - (heat / 220.0))  # down to 60%
    trace_delta = int(trace_delta * heat_trace_boost)
    econ_scale = float(econ_scale) * heat_econ_penalty

    # Heat gain per attempt (bigger for critical/public/failure).
    gain = 4
    if not stealth:
        gain += 3
    if is_critical:
        gain += 10
    if grade in ("failure", "critical_failure"):
        gain += 4
    if stealth_tool:
        gain = max(1, int(gain * 0.7))
    if exploit_tool:
        gain += 1  # aggressive tooling leaves traces
    heat = max(0, min(100, heat + gain))
    row["heat"] = heat
    row["last_day"] = int(state.get("meta", {}).get("day", 1) or 1)

    # Signal vs noise:
    # - stealth reduces noise, but still increases signal (fingerprints)
    # - public increases noise heavily
    if stealth:
        noise_level = max(0, noise_level + max(1, int(gain * 0.4)))
        signal_level = max(0, signal_level + max(1, int(gain * (2.0 if stealth_tool else 2.3))))
    else:
        noise_level = max(0, noise_level + max(2, int(gain * (2.0 if forensic_tool else 1.8))))
        signal_level = max(0, signal_level + max(1, int(gain * 0.9)))
    row["noise"] = min(100, noise_level)
    row["signal"] = min(100, signal_level)

    # District/city cyber alert: translate hacking noise into local crackdown context for NPCs/district travel.
    try:
        loc = str(state.get("player", {}).get("location", "") or "").strip().lower()
        did = str((state.get("player", {}) or {}).get("district", "") or "").strip().lower()
        if loc:
            world = state.setdefault("world", {})
            locs = world.setdefault("locations", {})
            if isinstance(locs, dict):
                locs.setdefault(loc, {})
                slot = locs.get(loc)
                if isinstance(slot, dict):
                    ca = slot.setdefault("cyber_alert", {})
                    if not isinstance(ca, dict):
                        ca = {}
                    meta2 = state.get("meta", {}) or {}
                    day2 = int(meta2.get("day", 1) or 1)
                    # Level tracks the loudest noise in the last day; decay happens via daily hacking heat decay.
                    level = max(int(ca.get("level", 0) or 0), int(row.get("noise", 0) or 0))
                    ca["level"] = max(0, min(100, level))
                    ca["last_day"] = day2
                    ca["district"] = did
                    # Keep a short-lived flag for district systems (1-2 days depending on strictness).
                    until = int(ca.get("until_day", 0) or 0)
                    extra = 2 if ca["level"] >= 75 else 1
                    ca["until_day"] = max(until, day2 + extra)
                    slot["cyber_alert"] = ca
                    locs[loc] = slot
                    world["locations"] = locs
                    if ca["level"] >= 60:
                        state.setdefault("world_notes", []).append(
                            f"[Cyber] alert level={ca['level']} @ {loc}" + (f" district={did}" if did else "")
                        )
    except Exception:
        pass

    # Cover tracks mode: convert the hacking action into trace/heat cleanup.
    # Does not change sim clock or scheduling; just changes the effect of this hacking turn.
    if cover_tracks:
        tr = state.setdefault("trace", {})
        cur_pct = int(tr.get("trace_pct", 0) or 0)
        if grade in ("success", "critical_success"):
            cut = 18 if stealth else 12
            if stealth_tool:
                cut += 6
            if is_critical:
                cut -= 6  # harder to erase on critical targets
            cut = max(6, min(30, cut))
            tr["trace_pct"] = max(0, cur_pct - cut)
            # also cool heat for this target
            row["heat"] = max(0, int(row.get("heat", 0) or 0) - 14)
            row["noise"] = max(0, int(row.get("noise", 0) or 0) - 18)
            row["signal"] = max(0, int(row.get("signal", 0) or 0) - 8)
            world.setdefault("world_notes", []).append("[Hack] Cover tracks sukses (jejak berkurang).")
        elif grade == "partial":
            cut = 6
            tr["trace_pct"] = max(0, cur_pct - cut)
            row["noise"] = max(0, int(row.get("noise", 0) or 0) - 6)
            world.setdefault("world_notes", []).append("[Hack] Cover tracks parsial (jejak berkurang sedikit).")
        else:
            # Failed cleanup makes noise.
            tr["trace_pct"] = min(100, cur_pct + (6 if stealth else 10))
            world.setdefault("world_notes", []).append("[Hack] Cover tracks gagal (malah meninggalkan jejak).")

        # Emit a ripple about cleanup attempt (propagation depends on stealth).
        try:
            meta = state.get("meta", {}) or {}
            day = int(meta.get("day", 1) or 1)
            time_min = int(meta.get("time_min", 0) or 0)
            loc = str(state.get("player", {}).get("location", "") or "").strip().lower()
            prop = "local_witness" if stealth else "contacts"
            txt = f"[Hack] cover_tracks: {grade} (target={target})."
            _enqueue_ripple(
                state,
                {
                    "text": txt,
                    "triggered_day": day,
                    "surface_day": day,
                    "surface_time": min(1439, time_min + 20),
                    "surfaced": False,
                    "propagation": prop,
                    "visibility": "local" if prop == "local_witness" else "network",
                    "origin_location": loc,
                    "origin_faction": target,
                    "witnesses": [],
                    "surface_attempts": 0,
                    "impact": {"severity": 40, "factions": {}},
                },
            )
            _push_news(state, text=txt.replace("[Hack] ", ""), source=prop)
        except Exception:
            pass
        return

    # Conflict model v1:
    # - Hacking corporate weakens corporate stability; police tightens; black market gains power.
    # - Hacking police strengthens police; corporate destabilizes; black market opportunistically grows.
    # - Hacking black-market destabilizes it; police pressure increases; corporate can profit.
    # Helper for scaled int deltas.
    def _d(v: int) -> int:
        return int(v * float(faction_scale))

    def _econ_d(v: int) -> int:
        return int(v * float(econ_scale))

    # Partial success downgrades effects (smaller wins, still noisy).
    eff_scale = 1.0
    if grade == "partial":
        eff_scale = 0.45
    elif grade in ("critical_success",):
        eff_scale = 1.15
    elif grade in ("critical_failure",):
        eff_scale = 1.0

    def _ds(v: int) -> int:
        return int(v * float(eff_scale))

    if target == "corporate":
        if grade in ("success", "critical_success", "partial"):
            factions["corporate"]["stability"] = max(0, int(factions["corporate"]["stability"]) - _d(10))
            factions["corporate"]["power"] = max(0, int(factions["corporate"]["power"]) - _d(_ds(8)))
            factions["police"]["stability"] = max(0, int(factions["police"]["stability"]) - _d(2))
            factions["police"]["power"] = min(100, int(factions["police"]["power"]) + _d(_ds(5)))
            factions["black_market"]["power"] = min(100, int(factions["black_market"]["power"]) + _d(_ds(10)))

            _cash_apply(econ, +_econ_d(_ds(180)))
            world.setdefault("world_notes", []).append("[Hack] Keamanan korporat retak (volume " + ("quiet" if stealth and not is_critical else "public") + ").")
        else:
            factions["corporate"]["stability"] = max(0, int(factions["corporate"]["stability"]) - _d(5))
            factions["police"]["power"] = min(100, int(factions["police"]["power"]) + _d(10))
            factions["black_market"]["stability"] = max(0, int(factions["black_market"]["stability"]) - _d(4))
            _cash_apply(econ, -_econ_d(90))
            world.setdefault("world_notes", []).append("[Hack] Akses korporat terendus (trace meningkat).")
    elif target == "police":
        if grade in ("success", "critical_success", "partial"):
            factions["police"]["stability"] = max(0, int(factions["police"]["stability"]) - _d(12))
            factions["police"]["power"] = max(0, int(factions["police"]["power"]) - _d(_ds(10)))
            factions["corporate"]["stability"] = max(0, int(factions["corporate"]["stability"]) + _d(2))
            factions["black_market"]["power"] = min(100, int(factions["black_market"]["power"]) + _d(_ds(7)))
            _cash_apply(econ, +_econ_d(_ds(140)))
            world.setdefault("world_notes", []).append("[Hack] Protokol keamanan polisi melemah (trace " + ("kecil" if stealth and not is_critical else "signifikan") + ").")
        else:
            factions["police"]["stability"] = max(0, int(factions["police"]["stability"]) - _d(4))
            factions["police"]["power"] = min(100, int(factions["police"]["power"]) + _d(12))
            factions["corporate"]["stability"] = max(0, int(factions["corporate"]["stability"]) - _d(6))
            _cash_apply(econ, -_econ_d(110))
            world.setdefault("world_notes", []).append("[Hack] Gangguan terdeteksi di jaringan polisi (trace meningkat).")
    else:  # black_market
        if grade in ("success", "critical_success", "partial"):
            factions["black_market"]["stability"] = max(0, int(factions["black_market"]["stability"]) - _d(10))
            factions["black_market"]["power"] = max(0, int(factions["black_market"]["power"]) - _d(_ds(8)))
            factions["police"]["power"] = min(100, int(factions["police"]["power"]) + _d(_ds(8)))
            factions["corporate"]["power"] = min(100, int(factions["corporate"]["power"]) + _d(_ds(4)))
            _cash_apply(econ, +_econ_d(_ds(110)))
            world.setdefault("world_notes", []).append("[Hack] Pasar gelap mengalami kebocoran (trace " + ("kecil" if stealth and not is_critical else "signifikan") + ").")
        else:
            factions["black_market"]["stability"] = max(0, int(factions["black_market"]["stability"]) - _d(3))
            factions["black_market"]["power"] = min(100, int(factions["black_market"]["power"]) + _d(6))
            factions["police"]["power"] = min(100, int(factions["police"]["power"]) + _d(14))
            _cash_apply(econ, -_econ_d(130))
            world.setdefault("world_notes", []).append("[Hack] Upaya ganggu pasar gelap gagal (trace meningkat).")

    # Attention pressure always rises; critical targets rise much faster.
    state.setdefault("trace", {}).setdefault("trace_pct", 0)
    cur = int(state["trace"].get("trace_pct", 0) or 0)
    if grade in ("failure", "critical_failure"):
        # Failures generally generate more noise than clean success.
        trace_delta = int(trace_delta * 1.3)
    new_pct = min(100, cur + int(trace_delta))
    state["trace"]["trace_pct"] = new_pct
    state["trace"]["trace_status"] = "Ghost" if new_pct <= 25 else "Flagged" if new_pct <= 50 else "Investigated" if new_pct <= 75 else "Manhunt"

    # Clamp sanity.
    for k in ("stability", "power"):
        for f in ("corporate", "police", "black_market"):
            try:
                factions[f][k] = max(0, min(100, int(factions[f].get(k, 50))))
            except Exception:
                factions[f][k] = 50

    # Sync faction attention from trace pressure.
    try:
        from engine.core.factions import sync_faction_statuses_from_trace

        sync_faction_statuses_from_trace(state)
    except Exception:
        pass

    # Structured ripple: information + small aftershock (avoid double-counting the main hack deltas above).
    try:
        meta = state.get("meta", {}) or {}
        day = int(meta.get("day", 1) or 1)
        time_min = int(meta.get("time_min", 0) or 0)
        loc = str(state.get("player", {}).get("location", "") or "").strip().lower()

        if stealth and not is_critical:
            propagation = "local_witness"
        elif is_critical:
            propagation = "broadcast"
        else:
            propagation = "contacts"

        # Aftershock magnitude is intentionally small.
        sev = 75 if is_critical else 55 if not stealth else 35
        if not success:
            sev = min(95, int(sev + 10))

        # Small faction ripples (separate from immediate effects).
        f_after: dict[str, dict[str, int]] = {}
        if target == "corporate":
            f_after = {"corporate": {"stability": -2 if success else -1}, "police": {"power": +1}}
        elif target == "police":
            f_after = {"police": {"stability": -2 if success else -1, "power": +1}}
        else:
            f_after = {"black_market": {"stability": -2 if success else -1}, "police": {"power": +1}}

        # Human-readable text (short, for IntelFeed).
        vol = "quiet" if stealth and not is_critical else "broadcast" if is_critical else "contacts"
        ok = "sukses" if success else "gagal"
        txt = f"[Hack] {ok}: target={target} ({vol})."

        _enqueue_ripple(
            state,
            {
                "text": txt,
                "triggered_day": day,
                "surface_day": day,
                "surface_time": min(1439, time_min + 30),
                "surfaced": False,
                "propagation": propagation,
                "visibility": "local" if propagation == "local_witness" else "network",
                "origin_location": loc,
                "origin_faction": target,
                "witnesses": [],
                "surface_attempts": 0,
                "impact": {"severity": sev, "factions": f_after},
            },
        )
        _push_news(state, text=txt.replace("[Hack] ", ""), source=propagation)
    except Exception:
        pass

