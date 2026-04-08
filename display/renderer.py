from __future__ import annotations

from typing import Any

from rich.console import Console, Group
from rich.columns import Columns
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from engine.combat import get_active_weapon

console = Console()


def _fmt_clock(time_min: int) -> str:
    t = int(time_min) % (24 * 60)
    h, m = t // 60, t % 60
    return f"{h:02d}:{m:02d}"


def _weapon_line(inv: dict[str, Any], flags: dict[str, Any]) -> str:
    w = get_active_weapon(inv)
    if not isinstance(w, dict):
        return "Weapon: (unarmed / none)"
    kind = str(w.get("kind", "?"))
    ammo = w.get("ammo", "-")
    tier = w.get("condition_tier", "?")
    aid = str(inv.get("active_weapon_id", "") or "").strip() or "legacy"
    jam = " [JAM]" if flags.get("weapon_jammed") else ""
    return f"Weapon: {aid} | {kind} | ammo={ammo} | tier={tier}{jam}"


def _fmt_items(items: Any, max_items: int = 6) -> str:
    """Compact list for UI: shows ids/names, truncated."""
    if not isinstance(items, list) or not items:
        return "-"
    previews: list[str] = []
    for x in items[:max_items]:
        if isinstance(x, dict):
            if "id" in x and x.get("id"):
                previews.append(str(x.get("id")))
            elif "name" in x and x.get("name"):
                previews.append(str(x.get("name")))
            else:
                previews.append(str(x))
        else:
            previews.append(str(x))
    extra = ""
    if len(items) > max_items:
        extra = f" +{len(items) - max_items} more"
    return ", ".join(previews) + extra


def _fmt_npc_briefs(npcs: Any, max_n: int = 4) -> str:
    if not isinstance(npcs, dict) or not npcs:
        return "-"
    rows: list[str] = []
    # Prefer non-ambient first (if present), then by fear desc.
    items = list(npcs.items())
    def _key(it: tuple[str, Any]) -> tuple[int, int]:
        _name, data = it
        if not isinstance(data, dict):
            return (1, 0)
        ambient = 1 if data.get("ambient") is True else 0
        try:
            fear = int(data.get("fear", 0) or 0)
        except Exception:
            fear = 0
        return (ambient, -fear)

    items.sort(key=_key)
    for name, data in items[:max_n]:
        if not isinstance(data, dict):
            continue
        mood = str(data.get("mood", "-"))
        aff = str(data.get("affiliation", data.get("faction", "civilian")))
        trust = data.get("trust", "-")
        fear = data.get("fear", "-")
        # Keep line short for panel layout.
        rows.append(f"{name}: {mood} ({aff}) T={trust} F={fear}")
    return "\n".join(rows) if rows else "-"


def _sec_emotions(npc: dict[str, Any]) -> dict[str, int]:
    """Derived Plutchik secondaries for compact UI."""
    def _gi(k: str, default: int) -> int:
        try:
            return int(npc.get(k, default) or default)
        except Exception:
            return default

    joy = _gi("joy", _gi("affection", 0))
    trust = _gi("trust", _gi("respect", 50))
    fear = _gi("fear", 10)
    surprise = _gi("surprise", 0)
    anger = _gi("anger", _gi("resentment", 0))
    disgust = _gi("disgust", 0)
    love = int(round((joy + trust) / 2))
    alarm = int(round((fear + surprise) / 2))
    contempt = int(round((anger + disgust) / 2))
    return {"love": love, "alarm": alarm, "contempt": contempt}


def _fmt_intel_items(state: dict[str, Any]) -> list[str]:
    """Return a few high-signal intel lines (news + surfaced ripples)."""
    meta = state.get("meta", {}) or {}
    day = int(meta.get("day", 1) or 1)
    world = state.get("world", {}) or {}
    news = world.get("news_feed", []) or []
    lines: list[str] = []

    if isinstance(news, list) and news:
        # Back-compat: older saves may contain strings.
        normalized: list[dict[str, Any]] = []
        for it in news[-20:]:
            if isinstance(it, dict):
                normalized.append(it)
            elif isinstance(it, str):
                normalized.append({"day": day, "text": it, "source": "broadcast"})
        todays = [x for x in normalized if isinstance(x, dict) and int(x.get("day", -1)) == day]
        for it in (todays[-2:] if todays else normalized[-2:]):
            txt = str(it.get("text", "-"))
            src = str(it.get("source", "broadcast"))
            if len(txt) > 90:
                txt = txt[:87] + "..."
            lines.append(f"(news:{src}) {txt}")

    surf = state.get("surfacing_ripples_this_turn", []) or []
    if isinstance(surf, list) and surf:
        for rp in surf[:2]:
            if not isinstance(rp, dict):
                continue
            txt = str(rp.get("text", "-"))
            prop = str(rp.get("propagation", "local_witness"))
            kind = str(rp.get("kind", "") or "").strip().lower()
            label = kind.upper() if kind else "RIPPLE"
            if len(txt) > 90:
                txt = txt[:87] + "..."
            lines.append(f"({label}:{prop}) {txt}")
    return lines


def _fmt_npc_offers(state: dict[str, Any], max_n: int = 3) -> list[str]:
    world = state.get("world", {}) or {}
    econ = world.get("npc_economy", {}) or {}
    if not isinstance(econ, dict):
        return []
    offers = econ.get("offers", {}) or {}
    if not isinstance(offers, dict) or not offers:
        return []
    meta = state.get("meta", {}) or {}
    day = int(meta.get("day", 1) or 1)
    out: list[str] = []
    # Deterministic order.
    for _k in sorted(list(offers.keys()))[: max_n * 2]:
        v = offers.get(_k)
        if not isinstance(v, dict):
            continue
        npc = str(v.get("npc", _k))
        role = str(v.get("role", "?"))
        svc = str(v.get("service", "offer"))
        try:
            exp = int(v.get("expires_day", day) or day)
        except Exception:
            exp = day
        ttl = max(0, exp - day)
        out.append(f"(offer:{role}) {npc}: {svc} (ttl {ttl}d)")
        if len(out) >= max_n:
            break
    return out


def render_monitor(state: dict[str, Any]) -> None:
    bio = state.get("bio", {})
    tr = state.get("trace", {})
    inv = state.get("inventory", {})
    eco = state.get("economy", {})
    player = state.get("player", {})
    meta = state.get("meta", {})
    flags = state.get("flags", {})

    bp = bio.get("bp_state", "Stable")
    bp_style = {"Stable": "green", "Low": "yellow", "Critical": "red", "Flatline": "bright_red"}.get(bp, "white")
    trace_style = {"Ghost": "green", "Flagged": "yellow", "Investigated": "dark_orange", "Manhunt": "red"}.get(
        tr.get("trace_status", "Ghost"), "white"
    )

    day = int(meta.get("day", 1))
    clock = _fmt_clock(int(meta.get("time_min", 0)))
    turn = int(meta.get("turn", 0))
    seed = meta.get("seed_pack") or "-"

    left = Text()
    mid = Text()
    right_prefix = Text()
    right_suffix = Text()

    left.append("OMNI-ENGINE v6.8\n", style="bold red")
    lang = str(player.get("language", "id")).lower()
    left.append(
        f"{player.get('name', '?')} | Day {day} {clock} | Turn {turn} | Lang: {lang} | Seed: {seed}\n",
        style="bold white",
    )
    left.append(f"Loc: {player.get('location', '-')} | Year: {player.get('year', '-')}\n", style="dim")
    # Location profile summary (culture/econ background).
    try:
        from engine.atlas import ensure_location_profile, fmt_profile_short

        loc_s = str(player.get("location", "") or "").strip()
        if loc_s:
            prof = ensure_location_profile(state, loc_s)
            left.append(f"Profile: {fmt_profile_short(prof)}\n", style="dim")
    except Exception:
        pass
    social = player.get("social_stats", {}) or {}
    if isinstance(social, dict):
        left.append(
            f"Social: looks={int(social.get('looks', 0) or 0)} | outfit={int(social.get('outfit', 0) or 0)} | "
            f"hygiene={int(social.get('hygiene', 0) or 0)} | speaking={int(social.get('speaking', 0) or 0)}\n",
            style="dim",
        )
    left.append(f"BP: {bp}  ", style=bp_style)
    left.append(f"Blood: {bio.get('blood_volume', 5.0)}/{bio.get('blood_max', 5.0)}L\n")
    left.append(f"Trace: {tr.get('trace_pct', 0)}% [{tr.get('trace_status', 'Ghost')}]\n", style=trace_style)
    # Disguise / Safehouse / Weather (new integrated systems; keep compact).
    try:
        d = (player.get("disguise", {}) or {}) if isinstance(player, dict) else {}
        if isinstance(d, dict) and bool(d.get("active", False)):
            persona = str(d.get("persona", "?") or "?")
            ud = d.get("until_day", "?")
            ut = _fmt_clock(int(d.get("until_time", 0) or 0))
            left.append(f"Disguise: {persona} (until D{ud} {ut})\n", style="yellow")
    except Exception:
        pass
    try:
        cur_loc2 = str(player.get("location", "") or "").strip().lower()
        sh = (world.get("safehouses", {}) or {}) if isinstance(world, dict) else {}
        row = sh.get(cur_loc2) if isinstance(sh, dict) else None
        if isinstance(row, dict) and str(row.get("status", "none")) != "none":
            st = str(row.get("status", "rent"))
            sec = int(row.get("security_level", 1) or 1)
            rent = int(row.get("rent_per_day", 0) or 0)
            dd = int(row.get("delinquent_days", 0) or 0)
            left.append(f"Safehouse: {st} L{sec} rent={rent}/d delin={dd}\n", style="cyan")
        slotw = (world.get("locations", {}) or {}).get(cur_loc2) if cur_loc2 else None
        if isinstance(slotw, dict):
            w = slotw.get("weather", {}) or {}
            if isinstance(w, dict) and w.get("kind"):
                left.append(f"Weather: {w.get('kind')}\n", style="dim")
    except Exception:
        pass

    world = state.get("world", {}) or {}
    nearby = world.get("nearby_items", []) or []
    contacts = world.get("contacts", {}) or {}
    contact_n = len(contacts) if isinstance(contacts, dict) else 0
    news = world.get("news_feed", []) or []
    nearby_preview = "-"
    if isinstance(nearby, list) and nearby:
        labels: list[str] = []
        for x in nearby[:6]:
            if isinstance(x, dict):
                labels.append(str(x.get("id", x.get("name", "-"))))
            else:
                labels.append(str(x))
        nearby_preview = ", ".join(labels)
    left.append(
        f"Nearby: {len(nearby) if isinstance(nearby, list) else 0} | {nearby_preview}  | Contacts: {contact_n}\n",
        style="magenta",
    )

    # Location restrictions / districts (high-signal gameplay blockers).
    try:
        cur_loc = str(player.get("location", "") or "").strip().lower()
        slot = (world.get("locations", {}) or {}).get(cur_loc) if cur_loc else None
        if isinstance(slot, dict):
            restr = slot.get("restrictions", {}) or {}
            areas = slot.get("areas", {}) or {}
            bits: list[str] = []
            if isinstance(restr, dict):
                try:
                    psu = int(restr.get("police_sweep_until_day", 0) or 0)
                except Exception:
                    psu = 0
                try:
                    clu = int(restr.get("corporate_lockdown_until_day", 0) or 0)
                except Exception:
                    clu = 0
                if psu >= day:
                    att = str(restr.get("police_sweep_attention", "investigated") or "investigated").lower()
                    bits.append(f"[bold yellow]SWEEP[/] (att={att}, until D{psu})")
                if clu >= day:
                    bits.append(f"[bold red]LOCKDOWN[/] (until D{clu})")
            area_bits: list[str] = []
            if isinstance(areas, dict):
                for an, arow in list(areas.items())[:8]:
                    if not isinstance(an, str) or not isinstance(arow, dict):
                        continue
                    if not bool(arow.get("restricted", False)):
                        continue
                    try:
                        au = int(arow.get("until_day", 0) or 0)
                    except Exception:
                        au = 0
                    if au < day:
                        continue
                    area_bits.append(f"{an}(D{au})")
            if bits or area_bits:
                left.append("Restrictions: ", style="bold")
                if bits:
                    left.append(" | ".join(bits) + "\n", style="dim")
                else:
                    left.append("-\n", style="dim")
                if area_bits:
                    left.append("Areas: " + ", ".join(area_bits) + "\n", style="dim")
    except Exception:
        pass

    # NPCSim counters (debug/perf feedback).
    nsc = meta.get("npc_sim_last_counts") or {}
    if isinstance(nsc, dict) and nsc:
        try:
            ev = int(nsc.get("evaluated", 0) or 0)
        except Exception:
            ev = 0
        try:
            co = int(nsc.get("coarse", 0) or 0)
        except Exception:
            co = 0
        try:
            ac = int(nsc.get("actions", 0) or 0)
        except Exception:
            ac = 0
        try:
            rp = int(nsc.get("ripples", 0) or 0)
        except Exception:
            rp = 0
        left.append(f"NPCSim: eval={ev} coarse={co} actions={ac} ripples={rp}\n", style="dim")

    # NPC offers (fixer/merchant services) from deterministic NPC sim.
    offers_lines = _fmt_npc_offers(state, max_n=3)
    if offers_lines:
        left.append("Offers:\n", style="bold")
        for ln in offers_lines:
            left.append(f"- {ln}\n", style="dim")

    # News feed (rate-limited headlines).
    if isinstance(news, list) and news:
        day = int(meta.get("day", 1))
        todays = [x for x in news[-8:] if isinstance(x, dict) and int(x.get("day", -1)) == day]
        if not todays:
            todays = [x for x in news[-2:] if isinstance(x, dict)]
        if todays:
            left.append("News:\n", style="bold")
            for it in todays[-2:]:
                txt = str(it.get("text", "-"))
                src = str(it.get("source", "broadcast"))
                if len(txt) > 90:
                    txt = txt[:87] + "..."
                left.append(f"- ({src}) {txt}\n", style="dim")

    factions = world.get("factions", {}) or {}
    if isinstance(factions, dict) and factions:
        statuses = world.get("faction_statuses", {}) or {}
        if not isinstance(statuses, dict):
            statuses = {}

        def _fget(name: str) -> str:
            f = factions.get(name, {}) or {}
            if not isinstance(f, dict):
                return f"{name}: st=- pw=-"
            st = f.get("stability", "-")
            pw = f.get("power", "-")
            att = statuses.get(name, "-")
            return f"{name}: st={st} pw={pw} att={att}"

        left.append(
            "Factions: "
            + " | ".join([_fget("corporate"), _fget("police"), _fget("black_market")])
            + "\n",
            style="dim",
        )

    # Hacking heat (cooldown pressure) for current location.
    hh = world.get("hacking_heat", {}) or {}
    if isinstance(hh, dict) and hh:
        loc = str(player.get("location", "") or "").strip().lower()
        vals: dict[str, dict[str, int]] = {
            "corporate": {"heat": 0, "noise": 0, "signal": 0},
            "police": {"heat": 0, "noise": 0, "signal": 0},
            "black_market": {"heat": 0, "noise": 0, "signal": 0},
        }
        for k, v in hh.items():
            if not isinstance(k, str) or not isinstance(v, dict):
                continue
            if loc and not k.startswith(loc + "|"):
                continue
            target = k.split("|", 1)[1] if "|" in k else ""
            if target in vals:
                try:
                    vals[target]["heat"] = int(v.get("heat", 0) or 0)
                except Exception:
                    vals[target]["heat"] = 0
                try:
                    vals[target]["noise"] = int(v.get("noise", 0) or 0)
                except Exception:
                    vals[target]["noise"] = 0
                try:
                    vals[target]["signal"] = int(v.get("signal", 0) or 0)
                except Exception:
                    vals[target]["signal"] = 0

        def _heat_cell(x: int, noise: int, signal: int) -> str:
            if x >= 75:
                return f"[bold red]{x}(n{noise}/s{signal})[/]"
            if x >= 45:
                return f"[yellow]{x}(n{noise}/s{signal})[/]"
            return f"[dim]{x}(n{noise}/s{signal})[/]"

        left.append(
            "Heat: "
            + f"corp={_heat_cell(vals['corporate']['heat'], vals['corporate']['noise'], vals['corporate']['signal'])} "
            + f"police={_heat_cell(vals['police']['heat'], vals['police']['noise'], vals['police']['signal'])} "
            + f"bm={_heat_cell(vals['black_market']['heat'], vals['black_market']['noise'], vals['black_market']['signal'])}\n",
            style="dim",
        )

    mid.append(
        f"Cash: {eco.get('cash', 0)} | Bank: {eco.get('bank', 0)} | Burn: {eco.get('daily_burn', 0)}/d | "
        f"FICO: {eco.get('fico', 600)} | Debt: {eco.get('debt', 0)}\n",
        style="green",
    )
    # Market index (daily delta) – compact, high-signal.
    mi = meta.get("market_index") or {}
    if isinstance(mi, dict) and int(mi.get("day", 0) or 0) == day:
        try:
            pavg = int(mi.get("price_avg", 100) or 100)
        except Exception:
            pavg = 100
        try:
            savg = int(mi.get("scarcity_avg", 0) or 0)
        except Exception:
            savg = 0
        try:
            dp = int(mi.get("d_price", 0) or 0)
        except Exception:
            dp = 0
        try:
            ds = int(mi.get("d_scarcity", 0) or 0)
        except Exception:
            ds = 0
        mid.append(f"MktIdx: price={pavg} (Δ{dp:+d}) | scarcity={savg} (Δ{ds:+d})\n", style="dim")
    mkt = eco.get("market", {}) or {}
    if isinstance(mkt, dict) and mkt:
        try:
            w = mkt.get("weapons", {}) if isinstance(mkt.get("weapons"), dict) else {}
            e = mkt.get("electronics", {}) if isinstance(mkt.get("electronics"), dict) else {}
            t = mkt.get("transport", {}) if isinstance(mkt.get("transport"), dict) else {}
            mid.append(
                f"Market: weapons idx={w.get('price_idx', '-')} sc={w.get('scarcity', '-')} | "
                f"elec idx={e.get('price_idx', '-')} sc={e.get('scarcity', '-')} | "
                f"transport idx={t.get('price_idx', '-')} sc={t.get('scarcity', '-')}\n",
                style="dim",
            )
        except Exception:
            pass
    mid.append(
        f"CC: {player.get('cc', 0)} | Econ: {player.get('econ_tier', '-')} | "
        f"StopSeq: {flags.get('stop_sequence_active', False)} | Hallu: {flags.get('hallucination_active', False)}\n",
        style="cyan",
    )
    mid.append(_weapon_line(inv, flags) + "\n", style="yellow")
    pocket = inv.get("pocket_contents", [])
    bag = inv.get("bag_contents", [])
    pc = int(inv.get("pocket_capacity", 4) or 4)
    bc = int(inv.get("bag_capacity", 12) or 12)
    pocket_preview = _fmt_items(pocket, max_items=6)
    bag_preview = _fmt_items(bag, max_items=6)
    mid.append(
        f"Hands: R={inv.get('r_hand', '-')} | L={inv.get('l_hand', '-')}\n"
        f"POCKET({len(pocket) if isinstance(pocket, list) else 0}/{pc}): {pocket_preview}\n"
        f"BAG({len(bag) if isinstance(bag, list) else 0}/{bc}): {bag_preview}\n"
    )
    trig = state.get("triggered_events_this_turn", []) or []
    surf = state.get("surfacing_ripples_this_turn", []) or []
    notes = state.get("world_notes", []) or []
    right_prefix.append(f"Triggered: {len(trig)} | Surfacing: {len(surf)}\n", style="cyan")

    # Intel feed (news + surfaced ripples).
    intel = _fmt_intel_items(state)
    if intel:
        right_prefix.append("IntelFeed:\n", style="bold")
        for line in intel[:4]:
            right_prefix.append(f"- {line}\n", style="dim")

    # Impact summary from surfaced ripples (faction deltas).
    impact_lines: list[str] = []
    if isinstance(surf, list):
        for rp in surf[:6]:
            if not isinstance(rp, dict):
                continue
            impact = rp.get("impact") or rp.get("payload") or {}
            if not isinstance(impact, dict):
                continue
            f_imp = impact.get("factions")
            if not isinstance(f_imp, dict) or not f_imp:
                continue
            bits: list[str] = []
            for fname, dd in list(f_imp.items())[:3]:
                if not isinstance(fname, str) or not isinstance(dd, dict):
                    continue
                ds = dd.get("stability", 0)
                dp = dd.get("power", 0)
                try:
                    ds_i = int(ds)
                except Exception:
                    ds_i = 0
                try:
                    dp_i = int(dp)
                except Exception:
                    dp_i = 0
                bits.append(f"{fname} st{ds_i:+d} pw{dp_i:+d}")
            if bits:
                impact_lines.append(" | ".join(bits))
    if impact_lines:
        right_prefix.append("Impact:\n", style="bold")
        for s in impact_lines[:3]:
            right_prefix.append(f"- {s}\n", style="dim")

    # What Changed (always show, even when 0 deltas).
    diff = meta.get("last_turn_diff") or {}
    if isinstance(diff, dict):
        try:
            cash_d = int(diff.get("cash", 0) or 0)
        except Exception:
            cash_d = 0
        try:
            bank_d = int(diff.get("bank", 0) or 0)
        except Exception:
            bank_d = 0
        try:
            debt_d = int(diff.get("debt", 0) or 0)
        except Exception:
            debt_d = 0
        try:
            tr_d = int(diff.get("trace", 0) or 0)
        except Exception:
            tr_d = 0
        qe = diff.get("queued_events", 0)
        qr = diff.get("queued_ripples", 0)
        att_bits: list[str] = []
        for k, label in (("att_police", "police"), ("att_corporate", "corp"), ("att_black_market", "bm")):
            v = diff.get(k)
            if isinstance(v, dict):
                att_bits.append(f"{label} {v.get('from','-')}→{v.get('to','-')}")
        att_s = (" | " + " | ".join(att_bits)) if att_bits else ""
        right_prefix.append("WhatChanged:\n", style="bold")
        right_prefix.append(
            f"Δ cash={cash_d:+d} bank={bank_d:+d} debt={debt_d:+d} trace={tr_d:+d} | queued ev={qe} rp={qr}{att_s}\n",
            style="bold cyan",
        )
    parse_miss = meta.get("last_ai_missing_sections") or []
    if parse_miss:
        right_prefix.append(f"AI missing: {', '.join(parse_miss[:6])}\n", style="magenta")
    if notes:
        right_prefix.append("WorldNotes:\n", style="bold")
        tail = notes[-2:]
        for n in tail:
            s = str(n)
            if len(s) > 140:
                s = s[:137] + "..."
            right_prefix.append(f"- {s}\n", style="dim")

    # World queue preview (pending events).
    pe = state.get("pending_events", []) or []
    if isinstance(pe, list) and pe:
        right_prefix.append("WorldQueue:\n", style="bold")
        for ev in pe[:3]:
            if not isinstance(ev, dict):
                continue
            title = ev.get("title", ev.get("event_type", "?"))
            dd = ev.get("due_day", "?")
            dt = ev.get("due_time", "?")
            right_prefix.append(f"- {title} @day{dd} t{dt}\n", style="dim")

    # NPC emotion/affiliation snapshot (keeps the “mind” visible).
    npcs = state.get("npcs", {}) or {}
    npc_names: list[str] = []

    last_raw = meta.get("last_intent_raw")
    if isinstance(last_raw, dict):
        targs = last_raw.get("targets")
        if isinstance(targs, list):
            for t in targs:
                if isinstance(t, str) and t in npcs and t not in npc_names:
                    npc_names.append(t)

    if not npc_names and isinstance(npcs, dict):
        items = list(npcs.items())

        def _key(it: tuple[str, Any]) -> tuple[int, int]:
            _name, data = it
            if not isinstance(data, dict):
                return (1, 0)
            ambient = 1 if data.get("ambient") is True else 0
            try:
                fear = int(data.get("fear", 0) or 0)
            except Exception:
                fear = 0
            return (ambient, -fear)

        items.sort(key=_key)
        for name, _ in items[:4]:
            if isinstance(name, str):
                npc_names.append(name)

    # Belief snippets preview for focus NPC (target if any, else npc_focus).
    belief_lines: list[str] = []
    focus_name: str | None = None
    if npc_names:
        focus_name = npc_names[0]
    else:
        mf = meta.get("npc_focus")
        if isinstance(mf, str) and mf in (state.get("npcs", {}) or {}):
            focus_name = mf
    if focus_name and isinstance(npcs, dict) and isinstance(npcs.get(focus_name), dict):
        bsn = (npcs.get(focus_name) or {}).get("belief_snippets") or []
        if isinstance(bsn, list) and bsn:
            tail = [x for x in bsn[-2:] if isinstance(x, dict)]
            for it in tail:
                src = str(it.get("source", "-"))
                conf = it.get("confidence", None)
                try:
                    conf_s = f"{float(conf):.2f}"
                except Exception:
                    conf_s = "-"
                claim = str(it.get("claim", it.get("topic", "-")))
                if len(claim) > 90:
                    claim = claim[:87] + "..."
                belief_lines.append(f"({src} c={conf_s}) {claim}")
            if belief_lines:
                right_prefix.append(f"Beliefs: {focus_name}\n", style="bold")
                for line in belief_lines:
                    right_prefix.append(f"- {line}\n", style="dim")

    npc_table = Table(title="NPC Minds", box=None, show_header=True, header_style="bold")
    npc_table.add_column("Name", overflow="fold")
    npc_table.add_column("Mood", width=10)
    npc_table.add_column("Aff", width=10)
    npc_table.add_column("Love", width=4, justify="right")
    npc_table.add_column("Alarm", width=4, justify="right")
    npc_table.add_column("Cont", width=4, justify="right")

    if npc_names:
        for name in npc_names:
            data = npcs.get(name, {}) or {}
            if not isinstance(data, dict):
                continue
            mood = str(data.get("mood", "-"))
            aff = str(data.get("affiliation", data.get("faction", "civilian")))
            sec = _sec_emotions(data)

            def _fmt_meter(v: int, *, kind: str) -> str:
                v = int(v)
                if kind == "love":
                    style = "green" if v >= 70 else "yellow" if v >= 45 else "dim"
                    mark = "↑" if v >= 70 else ""
                elif kind == "alarm":
                    style = "bold red" if v >= 70 else "dark_orange" if v >= 45 else "dim"
                    mark = "!" if v >= 70 else ""
                else:  # contempt
                    style = "bold magenta" if v >= 70 else "yellow" if v >= 45 else "dim"
                    mark = "*" if v >= 70 else ""
                # keep width compact: e.g. "72↑"
                return f"[{style}]{v:02d}{mark}[/]"

            # Affiliation color coding for quick read.
            aff_l = aff.lower()
            if aff_l == "police":
                aff_style = "bold red"
            elif aff_l == "corporate":
                aff_style = "bold cyan"
            elif aff_l == "black_market":
                aff_style = "bold magenta"
            else:
                aff_style = "dim"
            npc_table.add_row(
                name[:18],
                mood[:10],
                f"[{aff_style}]{aff[:10]}[/]",
                _fmt_meter(int(sec.get("love", 0) or 0), kind="love"),
                _fmt_meter(int(sec.get("alarm", 0) or 0), kind="alarm"),
                _fmt_meter(int(sec.get("contempt", 0) or 0), kind="contempt"),
            )
    else:
        npc_table.add_row("-", "-", "-", "-", "-", "-")

    # Last intent audit line (helps align AI behavior with engine intent)
    last_source = meta.get("last_intent_source") or "-"
    raw = meta.get("last_intent_raw")
    if isinstance(raw, dict):
        dom = raw.get("domain", "-")
        note = raw.get("intent_note", "-")
        conf = raw.get("confidence", None)
        if isinstance(conf, (int, float)):
            conf_s = f"{conf:.2f}"
        else:
            conf_s = str(conf) if conf is not None else "-"
        right_suffix.append(f"LastIntent: source={last_source} domain={dom} note={note} conf={conf_s}\n", style="magenta")
    else:
        right_suffix.append(f"LastIntent: source={last_source}\n", style="magenta")

    right_group = Group([right_prefix, npc_table, right_suffix])
    console.print(Panel(Columns([left, mid, right_group], expand=True, equal=True), title="OMNI_MONITOR"))


def stream_render(text_chunk: str) -> None:
    console.print(text_chunk, end="")
