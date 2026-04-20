from __future__ import annotations

import os
from typing import Any

from rich import box
from rich.console import Console, Group
from rich.columns import Columns
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from engine.core.character_stats import ensure_player_character_stats
from engine.core.feed_prune import world_note_plain
from engine.core.trace import get_trace_tier
from engine.npc.relationship import get_top_relationships
from engine.social.suspicion_ui import get_heat_brief, get_suspicion_brief
from engine.systems.combat import get_active_weapon
from engine.systems.occupation import career_daily_salary_usd, career_title_for_level, ensure_career
from engine.systems.property import ensure_player_assets, list_asset_entries
from engine.systems.smartphone import _smartphone_status_summary, ensure_smartphone
from engine.world.atlas import ensure_location_profile, fmt_profile_short
from engine.world.districts import district_heat_snapshot, district_neighbor_ids, get_current_district, get_district
from engine.world.faction_report import build_faction_macro_report

console = Console()


def format_data_table(title: str, headers: list[str], rows: list[list[str]], *, theme: str = "default") -> Table:
    """Small Rich table helper to standardize CLI UX."""
    t = Table(title=title, box=box.SQUARE)
    if theme == "magenta":
        t.title_style = "bold magenta"
        header_style = "bold magenta"
    elif theme == "cyan":
        t.title_style = "bold cyan"
        header_style = "bold cyan"
    else:
        t.title_style = "bold"
        header_style = "bold"
    for h in headers:
        t.add_column(str(h), header_style=header_style, no_wrap=True if len(str(h)) <= 10 else False)
    for r in rows:
        t.add_row(*[str(x) for x in r])
    return t


def _monitor_mode(state: dict[str, Any]) -> str:
    mm = str((state.get("meta", {}) or {}).get("monitor_mode", "")).strip().lower()
    if mm in ("full", "compact"):
        return mm
    v = os.getenv("OMNI_MONITOR_MODE", "compact").strip().lower()
    return "full" if v in ("full", "wide", "verbose") else "compact"


def _fmt_clock(time_min: int) -> str:
    t = int(time_min) % (24 * 60)
    h, m = t // 60, t % 60
    return f"{h:02d}:{m:02d}"


def _intel_ripple_label(kind: str) -> str:
    """Short labels for IntelFeed (utility AI and other high-signal kinds)."""
    k = str(kind or "").strip().lower()
    aliases: dict[str, str] = {
        "npc_utility_seek_job": "NPC_JOB",
        "npc_utility_relocate": "NPC_MOVE",
        "npc_utility_contact": "NPC_CONTACT",
    }
    if k in aliases:
        return aliases[k]
    return k.upper() if k else "RIPPLE"


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
        for rp in surf[:3]:
            if not isinstance(rp, dict):
                continue
            txt = str(rp.get("text", "-"))
            prop = str(rp.get("propagation", "local_witness"))
            kind = str(rp.get("kind", "") or "").strip().lower()
            label = _intel_ripple_label(kind)
            if len(txt) > 90:
                txt = txt[:87] + "..."
            lines.append(f"({label}:{prop}) {txt}")
    return lines


def _fmt_active_scene(state: dict[str, Any]) -> list[str]:
    sc = state.get("active_scene")
    if not isinstance(sc, dict) or not sc:
        return []
    st = str(sc.get("scene_type", "") or "").strip()
    ph = str(sc.get("phase", "") or "").strip()
    exp = sc.get("expires_at") if isinstance(sc.get("expires_at"), dict) else {}
    try:
        ed = int((exp or {}).get("day", 0) or 0)
    except Exception:
        ed = 0
    try:
        et = int((exp or {}).get("time_min", 0) or 0)
    except Exception:
        et = 0
    opts = sc.get("next_options") or []
    if not isinstance(opts, list):
        opts = []
    lines: list[str] = []
    lines.append(f"ActiveScene: {st or '-'} phase={ph or '-'}")
    if ed > 0:
        lines.append(f"deadline: day{ed} {_fmt_clock(et)}")
    if opts:
        # show a few options
        preview = [str(x) for x in opts[:8] if isinstance(x, str)]
        if preview:
            lines.append("options: " + " | ".join(preview))
    return lines


def _fmt_scene_queue(state: dict[str, Any]) -> list[str]:
    q = state.get("scene_queue", [])
    if not isinstance(q, list) or not q:
        return []
    # Preview up to 3 queued scene types.
    types: list[str] = []
    for it in q[:8]:
        if not isinstance(it, dict):
            continue
        st = str(it.get("scene_type", "") or "").strip()
        if st:
            types.append(st)
        if len(types) >= 3:
            break
    if not types:
        return ["SceneQueue: (items queued)"]
    extra = ""
    if len(q) > len(types):
        extra = f" (+{len(q) - len(types)} more)"
    return [f"SceneQueue: {', '.join(types)}{extra}"]


def _fmt_scene_lock_reason(state: dict[str, Any]) -> list[str]:
    sc = state.get("active_scene")
    if not isinstance(sc, dict) or not sc:
        return []
    st = str(sc.get("scene_type", "") or "").strip()
    ph = str(sc.get("phase", "") or "").strip()
    if not st:
        return []
    return [f"SceneLock: resolve {st}({ph or '-'}) first"]


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


def _compact_hook_text(state: dict[str, Any], *, max_len: int = 72) -> str:
    """One scannable hook line for [HOOK]; empty string if nothing worth showing."""
    pe = state.get("pending_events") or []
    if isinstance(pe, list) and pe:
        ev0 = pe[0]
        if isinstance(ev0, dict):
            title = str(ev0.get("title", ev0.get("event_type", "")) or "").strip()
            if title:
                extra = f" @d{ev0.get('due_day', '?')} t{ev0.get('due_time', '?')}"
                s = title + extra
                return s if len(s) <= max_len else s[: max_len - 1] + "…"
    intel = _fmt_intel_items(state)
    if intel:
        line0 = intel[0]
        if len(line0) > max_len:
            return line0[: max_len - 1] + "…"
        return line0
    world = state.get("world", {}) or {}
    news = world.get("news_feed", []) or []
    if isinstance(news, list) and news:
        last = news[-1]
        if isinstance(last, dict):
            nt = str(last.get("text", "") or "").strip()
            if nt:
                if len(nt) > max_len:
                    return nt[: max_len - 1] + "…"
                return nt
    return ""


def _fmt_character_stats_line(state: dict[str, Any]) -> str:
    """W2-6 HUD: one-line seven core stats (abbrev)."""
    try:
        cs = ensure_player_character_stats(state)
    except Exception:
        return "C50 A50 S50 I50 P50 L50 W50"
    return (
        f"C{cs['charisma']} A{cs['agility']} S{cs['strength']} I{cs['intelligence']} "
        f"P{cs['perception']} L{cs['luck']} W{cs['willpower']}"
    )


def _condition_parts(state: dict[str, Any]) -> tuple[int, int, int, str]:
    meta = state.get("meta", {}) or {}
    try:
        gigs_done = int(meta.get("daily_gigs_done", 0) or 0)
    except Exception:
        gigs_done = 0
    try:
        hacks_attempted = int(meta.get("daily_hacks_attempted", 0) or 0)
    except Exception:
        hacks_attempted = 0
    gigs_done = max(0, gigs_done)
    penalty = max(0, hacks_attempted * 10)
    style = "bold red" if gigs_done >= 2 or penalty >= 30 else "yellow"
    return gigs_done, hacks_attempted, penalty, style


def _build_compact_monitor_vm(state: dict[str, Any]) -> dict[str, Any]:
    meta = state.get("meta", {}) or {}
    eco = state.get("economy", {}) or {}
    player = state.get("player", {}) or {}
    tr = state.get("trace", {}) or {}
    bio = state.get("bio", {}) or {}
    rep = state.get("reputation", {}) or {}
    day = int(meta.get("day", 1) or 1)
    clock = _fmt_clock(int(meta.get("time_min", 0) or 0))
    loc_raw = str(player.get("location", "-") or "-").strip()
    loc_display = loc_raw.replace("_", " ").title() if loc_raw and loc_raw != "-" else loc_raw
    cash = int(eco.get("cash", 0) or 0)
    bank = int(eco.get("bank", 0) or 0)
    burn = int(eco.get("daily_burn", 0) or 0)
    bp = str(bio.get("bp_state", "Stable") or "Stable")
    mood_label = str(bio.get("mood_label", "meh") or "meh").strip().lower()
    hunger_label = str(bio.get("hunger_label", "full") or "full").strip().lower()
    try:
        sleep_debt = float(bio.get("sleep_debt", 0.0) or 0.0)
    except Exception:
        sleep_debt = 0.0
    mood_emojis = {
        "great": "😄",
        "okay": "🙂",
        "meh": "😐",
        "bad": "😞",
        "broken": "💔",
    }
    hunger_emojis = {
        "full": "🍽️",
        "okay": "🥗",
        "hungry": "🍞",
        "starving": "🥀",
        "critical": "☠️",
    }
    mood_emoji = mood_emojis.get(mood_label, "😐")
    hunger_emoji = hunger_emojis.get(hunger_label, "🍽️")
    rep_scores = rep.get("scores", {}) if isinstance(rep.get("scores"), dict) else {}
    label_to_score = {
        "hostile": 20.0,
        "bad": 30.0,
        "poor": 35.0,
        "neutral": 50.0,
        "good": 70.0,
        "trusted": 85.0,
        "ally": 90.0,
    }
    def _rep_score(raw: Any, label_raw: Any) -> float:
        try:
            if raw is not None:
                return max(0.0, min(100.0, float(raw)))
        except Exception:
            pass
        return float(label_to_score.get(str(label_raw or "Neutral").strip().lower(), 50.0))
    rep_map = {
        "criminal": _rep_score(rep_scores.get("criminal"), rep.get("criminal_label")),
        "corporate": _rep_score(rep_scores.get("corporate"), rep.get("corporate_label")),
        "political": _rep_score(rep_scores.get("political"), rep.get("political_label")),
        "street": _rep_score(rep_scores.get("street"), rep.get("civilian_label")),
        "underground": _rep_score(rep_scores.get("underground"), rep.get("underground_label", rep.get("global_label", "Neutral"))),
    }
    rep_top_key, rep_top_val = max(rep_map.items(), key=lambda kv: kv[1])
    rep_emoji = "🏆" if rep_top_val >= 80 else "⭐" if rep_top_val >= 65 else "•"
    rel_summary = "-"
    try:
        top_rels = get_top_relationships(state, limit=3)
        chunks: list[str] = []
        for nm, rel in top_rels:
            rtype = str((rel or {}).get("type", "neutral") or "neutral").replace("_", " ").title()
            chunks.append(f"{nm}: {rtype}")
        if chunks:
            rel_summary = " | ".join(chunks)
    except Exception:
        pass
    # W2-7: binary energy readout (sleep survival).
    if sleep_debt >= 4.0:
        energy_label = "Exhausted"
        energy_emoji = "😴"
    else:
        energy_label = "Rested"
        energy_emoji = "💪"
    try:
        _tier = get_trace_tier(state)
        trace_pct = int(_tier.get("trace_pct", 0) or 0)
        tier_lbl = str(_tier.get("tier_id", "Ghost") or "Ghost")
    except Exception:
        trace_pct = int(tr.get("trace_pct", 0) or 0)
        tier_lbl = str(tr.get("trace_status", "Ghost") or "Ghost")
    career_hud = ""
    try:
        ensure_career(state)
        c = (state.get("player", {}) or {}).get("career", {}) or {}
        if isinstance(c, dict):
            at = str(c.get("active_track", "-") or "-")
            tr = (c.get("tracks", {}) or {}).get(at) or {}
            lvl = int((tr or {}).get("level", 0) or 0) if isinstance(tr, dict) else 0
            title = career_title_for_level(state, at, lvl)
            br = "break" if bool(c.get("on_break")) else "aktif"
            bits = [f"{at}: {title}", br]
            if bool(c.get("permanent_stain")):
                bits.append("noda permanen")
            if not bool(c.get("on_break")):
                pay = int(career_daily_salary_usd(state) or 0)
                if pay > 0:
                    bits.append(f"~${pay}/hari")
            career_hud = " | ".join(bits)
    except Exception:
        career_hud = ""
    property_hud = ""
    try:
        ensure_player_assets(state)
        ent = list_asset_entries(state)
        if ent:
            n = len(ent)
            kinds = {}
            for e in ent[:12]:
                if not isinstance(e, dict):
                    continue
                k = str(e.get("kind", "?") or "?")
                kinds[k] = kinds.get(k, 0) + 1
            bits = [f"{n} aset", ", ".join(f"{k}:{v}" for k, v in sorted(kinds.items()))]
            property_hud = " | ".join(bits)[:110]
    except Exception:
        property_hud = ""
    smartphone_hud = ""
    try:
        sp = ensure_smartphone(state)
        smartphone_hud = _smartphone_status_summary(sp)
    except Exception:
        smartphone_hud = ""
    return {
        "day": day,
        "clock": clock,
        "loc_display": loc_display,
        "cash": cash,
        "bank": bank,
        "burn": burn,
        "bp": bp,
        "trace_pct": trace_pct,
        "tier_lbl": tier_lbl,
        "mood_label": mood_label,
        "mood_emoji": mood_emoji,
        "hunger_label": hunger_label,
        "hunger_emoji": hunger_emoji,
        "rep_top_key": rep_top_key,
        "rep_top_val": rep_top_val,
        "rep_emoji": rep_emoji,
        "rel_summary": rel_summary,
        "energy_label": energy_label,
        "energy_emoji": energy_emoji,
        "career_hud": career_hud,
        "property_hud": property_hud,
        "smartphone_hud": smartphone_hud,
    }


def _build_full_monitor_vm(state: dict[str, Any]) -> dict[str, Any]:
    meta = state.get("meta", {}) or {}
    player = state.get("player", {}) or {}
    tr = state.get("trace", {}) or {}
    day = int(meta.get("day", 1) or 1)
    clock = _fmt_clock(int(meta.get("time_min", 0) or 0))
    turn = int(meta.get("turn", 0) or 0)
    seed = meta.get("seed_pack") or "-"
    try:
        _tier = get_trace_tier(state)
        trace_pct = int(_tier.get("trace_pct", 0) or 0)
        tier_lbl = str(_tier.get("tier_id", "Ghost") or "Ghost")
    except Exception:
        trace_pct = int(tr.get("trace_pct", 0) or 0)
        tier_lbl = str(tr.get("trace_status", "Ghost") or "Ghost")
    return {
        "day": day,
        "clock": clock,
        "turn": turn,
        "seed": seed,
        "player_name": player.get("name", "?"),
        "player_lang": str(player.get("language", "id")).lower(),
        "player_loc": player.get("location", "-"),
        "player_year": player.get("year", "-"),
        "trace_pct": trace_pct,
        "tier_lbl": tier_lbl,
    }


def _render_monitor_compact(state: dict[str, Any]) -> None:
    """Vertical tagged HUD (one line per category); type UI FULL for the wide panel."""
    bio = state.get("bio", {})
    tr = state.get("trace", {}) or {}
    eco = state.get("economy", {}) or {}
    player = state.get("player", {}) or {}
    meta = state.get("meta", {}) or {}
    world = state.get("world", {}) or {}
    vm = _build_compact_monitor_vm(state)
    day = int(vm["day"])
    clock = str(vm["clock"])
    loc_display = str(vm["loc_display"])
    cash = int(vm["cash"])
    bank = int(vm["bank"])
    burn = int(vm["burn"])
    trace_pct = int(vm["trace_pct"])
    tier_lbl = str(vm["tier_lbl"])
    bp = str(vm["bp"])
    mood_label = str(vm.get("mood_label", "meh") or "meh")
    mood_emoji = str(vm.get("mood_emoji", "😐") or "😐")
    hunger_label = str(vm.get("hunger_label", "full") or "full")
    hunger_emoji = str(vm.get("hunger_emoji", "🍽️") or "🍽️")
    rep_top_key = str(vm.get("rep_top_key", "street") or "street")
    rep_top_val = float(vm.get("rep_top_val", 50.0) or 50.0)
    rep_emoji = str(vm.get("rep_emoji", "•") or "•")
    rel_summary = str(vm.get("rel_summary", "-") or "-")
    energy_label = str(vm.get("energy_label", "Rested") or "Rested")
    energy_emoji = str(vm.get("energy_emoji", "💪") or "💪")
    if trace_pct > 75:
        trace_val_style = "bold red"
    elif trace_pct > 50:
        trace_val_style = "bold yellow"
    else:
        trace_val_style = "yellow"

    t = Text()
    t.append("[INFO] ", style="bold cyan")
    t.append(f"{player.get('name', '?')} | Day {day} ({clock}) | Loc: {loc_display}\n", style="cyan")

    t.append("[ECON] ", style="bold green")
    t.append(f"Cash: ${cash} | Bank: ${bank} | Burn: {burn}/d\n", style="green")
    ch = str(vm.get("career_hud", "") or "").strip()
    if ch:
        t.append("[CAREER] ", style="bold green")
        t.append(f"{ch}\n", style="green")
    ph = str(vm.get("property_hud", "") or "").strip()
    if ph:
        t.append("[ASSETS] ", style="bold green")
        t.append(f"{ph}\n", style="green")
    sh = str(vm.get("smartphone_hud", "") or "").strip()
    if sh:
        t.append("[PHONE] ", style="bold cyan")
        t.append(f"{sh}\n", style="cyan")

    t.append("[STAT] ", style="bold yellow")
    t.append("Trace: ", style="yellow")
    t.append(f"{trace_pct}% [{tier_lbl}]", style=trace_val_style)
    t.append(f" | BP: {bp}\n", style="yellow")
    t.append("[ATTR] ", style="bold yellow")
    t.append(f"{_fmt_character_stats_line(state)}\n", style="yellow")
    gigs_done, _hacks_attempted, penalty, cond_style = _condition_parts(state)
    t.append("[CONDITION] ", style=cond_style)
    t.append(f"Gigs: {gigs_done}/2 | Hack Penalty: -{penalty}%\n", style=cond_style)
    t.append("[MOOD] ", style="bold blue")
    t.append(f"Mood: {mood_emoji} {mood_label.title()}\n", style="blue")
    t.append("[HUNGER] ", style="bold magenta")
    t.append(f"Hunger: {hunger_emoji} {hunger_label.title()}\n", style="magenta")
    t.append("[REP] ", style="bold white")
    t.append(f"Rep: {rep_emoji} {rep_top_key.title()} ({rep_top_val:.1f})\n", style="white")
    if len(rel_summary) > 72:
        rel_summary = rel_summary[:70] + "…"
    t.append("[REL] ", style="bold white")
    t.append(f"👥 {rel_summary}\n", style="white")
    t.append("[ENERGY] ", style="bold cyan")
    t.append(f"Energy: {energy_emoji} {energy_label}\n", style="cyan")

    nearby = world.get("nearby_items", []) or []
    ids: list[str] = []
    if isinstance(nearby, list) and nearby:
        for x in nearby[:8]:
            if isinstance(x, dict):
                ids.append(str(x.get("id", x.get("name", "-"))))
            else:
                ids.append(str(x))
    near_s = ", ".join(ids) if ids else "-"
    if len(near_s) > 72:
        near_s = near_s[:70] + "…"
    t.append("[NEAR] ", style="bold magenta")
    t.append(f"{near_s}\n", style="magenta")

    hook = _compact_hook_text(state)
    hook_line = hook if hook else "-"
    if len(hook_line) > 72:
        hook_line = hook_line[:70] + "…"
    t.append("[HOOK] ", style="bold red")
    t.append(f"{hook_line}\n", style="red")

    if meta.get("registry_hint_mismatch"):
        t.append("[INTENT] ", style="bold yellow")
        t.append("⚠ Parser/registry resolution — LLM registry id hint mismatch\n", style="yellow")

    sc = state.get("active_scene")
    if isinstance(sc, dict) and sc:
        opts = sc.get("next_options") or []
        stype = str(sc.get("scene_type", "-") or "-").strip() or "-"
        if isinstance(opts, list) and opts:
            pv = [str(x) for x in opts[:6] if isinstance(x, str)]
            if pv:
                sc_line = " | ".join(pv)
                if len(sc_line) > 72:
                    sc_line = sc_line[:70] + "…"
                t.append("[SCENE] ", style="bold red")
                t.append(f"{stype} - Opsi: {sc_line}\n", style="bold red")

    t.append("[TIP] ", style="dim")
    t.append("TALK · INFORMANTS · WORLD_BRIEF · DISTRICTS · MARKET · BLACKMARKET · BUY_DARK · HELP\n", style="dim")

    panel_w = min(console.width - 4, 82) if console.width else 82
    console.print(
        Panel(
            t,
            title="[bold cyan]OMNI_MONITOR[/]",
            box=box.SQUARE,
            border_style="bold cyan",
            width=panel_w,
            subtitle="[dim]FICO=credit · idx=market · UI FULL=full HUD[/dim]",
        )
    )


def _render_monitor_full(state: dict[str, Any]) -> None:
    bio = state.get("bio", {})
    tr = state.get("trace", {})
    inv = state.get("inventory", {})
    eco = state.get("economy", {})
    player = state.get("player", {})
    meta = state.get("meta", {})
    flags = state.get("flags", {})
    world = state.get("world", {}) or {}

    bp = bio.get("bp_state", "Stable")
    bp_style = {"Stable": "green", "Low": "yellow", "Critical": "red", "Flatline": "bright_red"}.get(bp, "white")
    try:
        _tier_f = get_trace_tier(state)
        trace_pct_ui = int(_tier_f.get("trace_pct", 0) or 0)
        tier_lbl_f = str(_tier_f.get("tier_id", "Ghost") or "Ghost")
    except Exception:
        trace_pct_ui = int(tr.get("trace_pct", 0) or 0)
        tier_lbl_f = str(tr.get("trace_status", "Ghost") or "Ghost")
    if trace_pct_ui > 75:
        trace_style = "bold red"
    elif trace_pct_ui > 50:
        trace_style = "bold yellow"
    else:
        trace_style = {"Ghost": "green", "Flagged": "yellow", "Investigated": "dark_orange", "Manhunt": "red"}.get(
            tr.get("trace_status", "Ghost"), "yellow"
        )

    vm = _build_full_monitor_vm(state)
    day = int(vm["day"])
    clock = str(vm["clock"])
    turn = int(vm["turn"])
    seed = vm["seed"]

    left = Text()
    mid = Text()
    right_prefix = Text()
    right_suffix = Text()

    left.append("OMNI-ENGINE v6.9\n", style="bold black on cyan")
    lang = str(player.get("language", "id")).lower()
    left.append(f"{vm['player_name']} | Day {day} {clock} | Turn {turn} | Lang: {lang} | Seed: {seed}\n", style="bold white")
    left.append(f"Loc: {vm['player_loc']} | Year: {vm['player_year']}\n", style="dim")
    # Sim year / tech epoch (translation tech realism).
    try:
        sy = int((meta.get("sim_year", 0) or 0))
    except Exception:
        sy = 0
    te = meta.get("tech_epoch") or {}
    if sy:
        if isinstance(te, dict):
            left.append(
                f"SimYear: {sy} | Tech: {te.get('name','-')} (translator {te.get('translator_level','-')})\n",
                style="dim",
            )
        else:
            left.append(f"SimYear: {sy}\n", style="dim")
    # Location profile summary (culture/econ background).
    try:
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
    left.append(f"Attrs: {_fmt_character_stats_line(state)}\n", style="dim")
    try:
        sd_e = float(bio.get("sleep_debt", 0.0) or 0.0)
    except Exception:
        sd_e = 0.0
    if sd_e >= 4.0:
        left.append("Energy: 😴 Exhausted\n", style="cyan")
    else:
        left.append("Energy: 💪 Rested\n", style="cyan")
    left.append(f"[+] BP: {bp}\n", style=bp_style)
    left.append(
        f"[+] Blood: {bio.get('blood_volume', 5.0)}/{bio.get('blood_max', 5.0)}L\n",
        style="dim",
    )
    left.append(
        f"[TRACE] {trace_pct_ui}% [{tier_lbl_f}]\n",
        style=trace_style,
    )
    gigs_done, _hacks_attempted, penalty, cond_style = _condition_parts(state)
    left.append(f"[CONDITION] Gigs: {gigs_done}/2 | Hack Penalty: -{penalty}%\n", style=cond_style)
    # Local investigation pressure (Heat/Suspicion) — label + a few reasons only.
    try:
        hb = get_heat_brief(state)
        sb = get_suspicion_brief(state)
        if isinstance(hb, dict):
            hlabel = str(hb.get("label", "none") or "none")
            hrs = hb.get("reasons", []) or []
            hline = f"Heat: {hlabel}"
            if isinstance(hrs, list) and hrs:
                hline += " (" + ", ".join([str(x) for x in hrs[:2]]) + ")"
            left.append(hline + "\n", style="dim")
        if isinstance(sb, dict):
            slabel = str(sb.get("label", "none") or "none")
            srs = sb.get("reasons", []) or []
            sline = f"Suspicion: {slabel}"
            if isinstance(srs, list) and srs:
                sline += " (" + ", ".join([str(x) for x in srs[:2]]) + ")"
            left.append(sline + "\n", style="dim")
    except Exception:
        pass
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

    # Language barrier status (what the player can communicate locally).
    try:
        lc = (meta.get("last_turn_audit") or {}).get("language_ctx") if isinstance(meta.get("last_turn_audit"), dict) else None
        if isinstance(lc, dict) and lc.get("local_lang"):
            shared = "yes" if bool(lc.get("shared", False)) else "no"
            tl = str(lc.get("translator_level", "none") or "none")
            q = int(lc.get("quality", 0) or 0)
            left.append(f"LocalLang: {lc.get('local_lang')} | shared={shared} | xlate={tl} q={q}\n", style="dim")
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
        if ev != 0 or co != 0 or ac != 0 or rp != 0:
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
        f"[$] Cash: {eco.get('cash', 0)} | Bank: {eco.get('bank', 0)} | Burn: {eco.get('daily_burn', 0)}/d | "
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
        mid.append(f"[$] MktIdx: price={pavg} (Δ{dp:+d}) | scarcity={savg} (Δ{ds:+d})\n", style="dim")
    mkt = eco.get("market", {}) or {}
    if isinstance(mkt, dict) and mkt:
        try:
            w = mkt.get("weapons", {}) if isinstance(mkt.get("weapons"), dict) else {}
            e = mkt.get("electronics", {}) if isinstance(mkt.get("electronics"), dict) else {}
            t = mkt.get("transport", {}) if isinstance(mkt.get("transport"), dict) else {}
            mid.append(
                f"[$] Market: weapons idx={w.get('price_idx', '-')} sc={w.get('scarcity', '-')} | "
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
    mid.append("[!] " + _weapon_line(inv, flags) + "\n", style="yellow")
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
    trig_n = len(trig) if isinstance(trig, list) else 0
    surf_n = len(surf) if isinstance(surf, list) else 0
    if trig_n > 0 or surf_n > 0:
        right_prefix.append(f"Triggered: {trig_n} | Surfacing: {surf_n}\n", style="cyan")

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
        right_prefix.append("> sys.delta: ", style="dim")
        right_prefix.append(
            f"cash={cash_d:+d} bank={bank_d:+d} debt={debt_d:+d} trace={tr_d:+d} | queued ev={qe} rp={qr}{att_s}\n",
            style="bold cyan",
        )
        # What Changed v2: effects + skill XP + notes added this turn.
        aud = meta.get("last_turn_audit") or {}
        if isinstance(aud, dict):
            try:
                eff = (diff.get("effects") or {}) if isinstance(diff.get("effects"), dict) else {}
                w = eff.get("weather", "-") if isinstance(eff, dict) else "-"
                sh = eff.get("safehouse", {}) if isinstance(eff, dict) else {}
                dis = eff.get("disguise", {}) if isinstance(eff, dict) else {}
                sh_s = "-"
                if isinstance(sh, dict) and str(sh.get("status", "none")) != "none":
                    sh_s = f"{sh.get('status','rent')} L{sh.get('sec',1)} delin={sh.get('delin',0)}"
                dis_s = "-"
                if isinstance(dis, dict) and bool(dis.get("active", False)):
                    dis_s = str(dis.get("persona", "persona"))
                if (w not in ("", "-", None)) or sh_s != "-" or dis_s != "-":
                    right_prefix.append(f"> sys.effects: weather={w} | safehouse={sh_s} | disguise={dis_s}\n", style="dim")
            except Exception:
                pass
            try:
                xd = diff.get("xp_delta") if isinstance(diff.get("xp_delta"), dict) else {}
                if isinstance(xd, dict):
                    bits = []
                    for k in ("hacking", "social", "combat", "stealth", "evasion"):
                        v = int(xd.get(k, 0) or 0)
                        if v:
                            bits.append(f"{k}+{v}")
                    if bits:
                        right_prefix.append("> sys.xp: " + ", ".join(bits) + "\n", style="dim")
            except Exception:
                pass
            try:
                added = aud.get("notes_added", [])
                if isinstance(added, list) and added:
                    for s in added[-4:]:
                        right_prefix.append(f"> sys.audit: {str(s)}\n", style="dim")
            except Exception:
                pass
            # Time breakdown (transparent sim clock).
            try:
                tb = aud.get("time_breakdown", [])
                tel = int(aud.get("time_elapsed_min", 0) or 0)
                if isinstance(tb, list) and tb:
                    bits = []
                    for it in tb[:6]:
                        if not isinstance(it, dict):
                            continue
                        lbl = str(it.get("label", "") or "")
                        try:
                            mm = int(it.get("minutes", 0) or 0)
                        except Exception:
                            mm = 0
                        if mm <= 0:
                            continue
                        bits.append(f"{lbl}+{mm}m")
                    if bits:
                        right_prefix.append(f"> sys.time: +{tel}m (" + ", ".join(bits) + ")\n", style="dim")
            except Exception:
                pass
    parse_miss = meta.get("last_ai_missing_sections") or []
    if parse_miss:
        right_prefix.append(f"AI missing: {', '.join(parse_miss[:6])}\n", style="magenta")
    if notes:
        right_prefix.append("WorldNotes:\n", style="bold")
        tail_n = 2
        if isinstance(notes, list) and notes:
            recent = notes[-5:]
            if any("[NPC]" in str(x) for x in recent):
                tail_n = 3
        tail = notes[-tail_n:]
        for n in tail:
            s = world_note_plain(n)
            if len(s) > 140:
                s = s[:137] + "..."
            right_prefix.append(f"- {s}\n", style="dim")

    # Active scene (encounter) preview.
    try:
        sc_lines = _fmt_active_scene(state)
        if sc_lines:
            right_prefix.append("Scene:\n", style="bold")
            # Lock reason first.
            for ln in _fmt_scene_lock_reason(state)[:1]:
                right_prefix.append(f"- {ln}\n", style="dim")
            for ln in sc_lines[:6]:
                right_prefix.append(f"- {ln}\n", style="dim")
    except Exception:
        pass

    # Scene queue preview (queued encounters behind an active scene).
    try:
        sq = _fmt_scene_queue(state)
        if sq:
            right_prefix.append("SceneQueue:\n", style="bold")
            for ln in sq[:3]:
                right_prefix.append(f"- {ln}\n", style="dim")
    except Exception:
        pass

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

    npc_table = Table(
        title="NPC Minds",
        caption="[dim]Baris = NPC/kontak yang dilacak engine (nama bisa berupa handle, bukan semua warga di jalan)[/dim]",
        box=box.SIMPLE_HEAVY,
        border_style="magenta",
        show_header=True,
        header_style="bold magenta",
    )
    npc_table.add_column("Name", overflow="fold")
    npc_table.add_column("Mood", width=10)
    npc_table.add_column("Aff", width=10)
    npc_table.add_column("Love", width=4, justify="right")
    npc_table.add_column("Alarm", width=6, justify="right")
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
        npc_table.add_row("[dim](no tracked NPCs)[/]", "", "", "", "", "")

    # Last intent audit line (helps align AI behavior with engine intent)
    last_source = meta.get("last_intent_source") or "-"
    raw = meta.get("last_intent_raw")
    reg_mis = " hint_mismatch=yes" if meta.get("registry_hint_mismatch") else ""
    if isinstance(raw, dict):
        dom = raw.get("domain", "-")
        note = raw.get("intent_note", "-")
        conf = raw.get("confidence", None)
        if isinstance(conf, (int, float)):
            conf_s = f"{conf:.2f}"
        else:
            conf_s = str(conf) if conf is not None else "-"
        right_suffix.append(
            f"LastIntent: source={last_source} domain={dom} note={note} conf={conf_s}{reg_mis}\n",
            style="magenta",
        )
    else:
        right_suffix.append(f"LastIntent: source={last_source}{reg_mis}\n", style="magenta")

    right_group = Group(right_prefix, npc_table, right_suffix)
    console.print(
        Panel(
            Columns([left, mid, right_group], expand=True, equal=True),
            title="[bold cyan]OMNI_MONITOR[/]",
            box=box.SQUARE,
            border_style="bold cyan",
            subtitle="[dim]CC=cybercreds · FICO=kredit · idx/sc=indeks & kelangkaan pasar · Burn=biaya hidup/hari[/dim]",
        )
    )


def render_monitor(state: dict[str, Any]) -> None:
    if _monitor_mode(state) == "compact":
        _render_monitor_compact(state)
    else:
        _render_monitor_full(state)


def render_district_map_lite(state: dict[str, Any]) -> None:
    """W2-4: current district, ring neighbors, heat markers (Rich)."""
    try:
        p = state.get("player", {}) or {}
        city = str(p.get("location", "") or "").strip().lower()
        did = str(p.get("district", "") or "").strip().lower()
        if not city or not did:
            console.print("[yellow]MAP: set location + district first (travel / TRAVELTO).[/yellow]")
            return
        cur = get_current_district(state) or get_district(state, city, did) or {}
        cur_name = str(cur.get("name", did) or did)
        nh = district_neighbor_ids(state, city, did)
        h0 = district_heat_snapshot(state, city, did)

        def _heat_tag(hv: int) -> str:
            if hv >= 70:
                return "[bold red]HOT[/]"
            if hv >= 40:
                return "[yellow]warm[/]"
            return "[dim]cool[/]"

        lines = [
            f"[bold cyan]MAP[/] [dim]{city}[/]",
            f"  [bold]You:[/] {cur_name} ({did}) — heat {_heat_tag(h0)} ({h0})",
            "  [bold]Neighbors:[/]",
        ]
        if not nh:
            lines.append("    [dim](none / single district)[/]")
        for nid in nh:
            d2 = get_district(state, city, nid) or {}
            nm = str(d2.get("name", nid) or nid)
            hv = district_heat_snapshot(state, city, nid)
            lines.append(f"    - {nm} [dim]({nid})[/] {_heat_tag(hv)} ({hv})")
        console.print("\n".join(lines))
    except Exception:
        console.print("[red]MAP error.[/red]")


def render_faction_report(state: dict[str, Any], *, full: bool = False) -> None:
    """W2-1: deterministic macro faction summary (compact or full)."""
    pkg = build_faction_macro_report(state, full=full)
    title = "FACTION REPORT (full)" if full else "FACTION REPORT"
    rows: list[list[str]] = []
    for f in pkg.get("factions", []) or []:
        if not isinstance(f, dict):
            continue
        fid = str(f.get("id", "?"))
        dp = f.get("d_pw")
        ds = f.get("d_st")
        dps = "n/a" if dp is None else f"{int(dp):+d}"
        dss = "n/a" if ds is None else f"{int(ds):+d}"
        rows.append(
            [
                fid,
                str(int(f.get("power", 0) or 0)),
                str(int(f.get("stability", 0) or 0)),
                str(f.get("attention", "-")),
                dps,
                dss,
            ]
        )
    hot = pkg.get("hot", {}) or {}
    hot_lines: list[str] = []
    if isinstance(hot, dict):
        for fid, h in sorted(hot.items(), key=lambda x: str(x[0])):
            if not isinstance(h, dict):
                continue
            loc = str(h.get("loc", "") or "-") or "-"
            try:
                hv = int(h.get("heat", 0) or 0)
            except Exception:
                hv = 0
            hot_lines.append(f"{fid}: {loc or '—'} (heat {hv})")

    t = format_data_table(
        title,
        ["faction", "power", "stab", "attention", "Δ3d pw", "Δ3d st"],
        rows,
        theme="cyan",
    )
    console.print(t)
    if hot_lines:
        console.print("[bold]Hot spots (3d, ripple-tagged):[/bold]")
        for ln in hot_lines:
            console.print(f"  [dim]{ln}[/]")
    if full and isinstance(pkg.get("top_causes"), dict):
        console.print("[bold]Top ripple causes (3d):[/bold]")
        for fid, causes in sorted(pkg["top_causes"].items(), key=lambda x: str(x[0])):
            console.print(f"  [cyan]{fid}[/]")
            if not causes:
                console.print("    [dim](none logged)[/]")
                continue
            for c in causes[:3]:
                if not isinstance(c, dict):
                    continue
                k = str(c.get("kind", "") or "")
                tx = str(c.get("text", "") or "")
                if len(tx) > 72:
                    tx = tx[:69] + "..."
                console.print(f"    [dim]d{c.get('day', '?')}[/] [{k}] {tx}")


def stream_render(text_chunk: str) -> None:
    console.print(text_chunk, end="")
