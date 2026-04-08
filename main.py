from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

from rich.table import Table

from ai.client import stream_response
from ai.intent_resolver import resolve_intent
from ai.parser import apply_memory_hash_to_state, enforce_stop_sequence_output, parse_memory_hash, record_ai_parse_health
from ai.turn_prompt import build_system_prompt, build_turn_package, get_narration_lang
from display.renderer import console, render_monitor, stream_render
from engine.action_intent import parse_action_intent
from engine.bio import update_bio
from engine.combat import apply_combat_gates, resolve_combat_after_roll
from engine.economy import update_economy
from engine.inventory import update_inventory
from engine.inventory_ops import apply_inventory_ops
from engine.modifiers import compute_roll_package, stop_sequence_check
from engine.npcs import update_npcs
from engine.skills import update_skills
from engine.seeds import list_seed_names
from engine.state import CURRENT, PREVIOUS, backup_state, initialize_state, load_state, save_state
from engine.timers import update_timers
from engine.trace import update_trace
from engine.world import world_tick
from engine.hacking import apply_hacking_after_roll
from engine.npc_emotions import apply_npc_emotion_after_roll
from engine.npc_targeting import apply_npc_targeting


def _ask(prompt: str) -> str:
    return input(prompt).strip()


def _fmt_clock(time_min: int) -> str:
    t = int(time_min or 0)
    h = max(0, min(23, t // 60))
    m = max(0, min(59, t % 60))
    return f"{h:02d}:{m:02d}"


def _expand_alias(cmd: str) -> str:
    raw = cmd.strip()
    if not raw:
        return raw
    parts = raw.split(maxsplit=1)
    head = parts[0].upper()
    tail = parts[1] if len(parts) > 1 else ""
    # Nice-to-have aliases (no engine logic change; just input sugar).
    if head == "T" and tail:
        return f"travel {tail}"
    if head == "H" and tail:
        return f"hack {tail}"
    if head == "S" and tail:
        return f"talk {tail}"
    return raw


def boot_sequence() -> dict[str, Any]:
    console.print("[bold red]OMNI-ENGINE v6.8[/bold red]")
    fields = ["name", "age", "location", "year", "occupation", "background"]
    data: dict[str, Any] = {}
    for f in fields:
        raw = _ask(f"{f}: ")
        if raw.upper().startswith("QUICK BOOT "):
            parts = raw.split(maxsplit=3)
            if len(parts) == 4:
                data["location"], data["year"] = parts[2], parts[3]
                data.setdefault("name", "Generated Subject")
                data.setdefault("occupation", "Operator")
                data.setdefault("background", "Quick boot profile")
                break
        data[f] = raw
    seeds = list_seed_names()
    default_seed = "default" if "default" in seeds else (seeds[0] if seeds else "")
    hint = f"Seed pack [{default_seed or 'none'} / minimal / none]: "
    seed_raw = _ask(hint).strip()
    if not seed_raw:
        seed_pack = default_seed if default_seed else None
    else:
        seed_pack = seed_raw
    if seed_pack and str(seed_pack).lower() in ("none", "-", "no"):
        seed_pack = None
    return initialize_state(data, seed_pack=seed_pack)


def run_pipeline(state: dict[str, Any], action_ctx: dict[str, Any]) -> dict[str, Any]:
    world_tick(state, action_ctx)
    apply_inventory_ops(state, action_ctx)
    update_timers(state, action_ctx)
    update_bio(state, action_ctx)
    update_skills(state, action_ctx)
    update_npcs(state, action_ctx)
    update_economy(state, action_ctx)
    update_trace(state, action_ctx)
    update_inventory(state, action_ctx)
    apply_combat_gates(state, action_ctx)

    roll_pkg = compute_roll_package(state, action_ctx)
    # Skill progression happens after roll resolution (deterministic).
    try:
        from engine.skills import apply_skill_xp_after_roll

        apply_skill_xp_after_roll(state, action_ctx, roll_pkg)
    except Exception:
        pass

    # Domain-specific effects after roll (e.g., hacking consequences).
    apply_hacking_after_roll(state, action_ctx, roll_pkg)

    # NPC emotion/relationship consequences (informant/betrayal, romance, etc).
    apply_npc_emotion_after_roll(state, action_ctx, roll_pkg)

    resolve_combat_after_roll(state, action_ctx, roll_pkg)

    stop_sequence_check(state, action_ctx)
    return roll_pkg


def log_turn_outcome(state: dict[str, Any], action_ctx: dict[str, Any], roll_pkg: dict[str, Any]) -> None:
    notes = state.setdefault("world_notes", [])
    outcome = str(roll_pkg.get("outcome", "Unknown"))
    evt_count = len(state.get("triggered_events_this_turn", []) or [])
    ripple_count = len(state.get("surfacing_ripples_this_turn", []) or [])
    notes.append(
        f"Turn {int(state.get('meta', {}).get('turn', 0)) + 1}: action={action_ctx.get('action_type','instant')} domain={action_ctx.get('domain','evasion')} outcome={outcome} events={evt_count} ripples={ripple_count}"
    )


def _snapshot_metrics(state: dict[str, Any]) -> dict[str, Any]:
    eco = state.get("economy", {}) or {}
    tr = state.get("trace", {}) or {}
    world = state.get("world", {}) or {}
    statuses = world.get("faction_statuses", {}) or {}
    pe = state.get("pending_events", []) or []
    ar = state.get("active_ripples", []) or []
    return {
        "cash": int(eco.get("cash", 0) or 0),
        "bank": int(eco.get("bank", 0) or 0),
        "debt": int(eco.get("debt", 0) or 0),
        "trace": int(tr.get("trace_pct", 0) or 0),
        "att_police": str(statuses.get("police", "-")),
        "att_corporate": str(statuses.get("corporate", "-")),
        "att_black_market": str(statuses.get("black_market", "-")),
        "queued_events": len(pe) if isinstance(pe, list) else 0,
        "queued_ripples": len(ar) if isinstance(ar, list) else 0,
    }


def _compute_diff(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for k in ("cash", "bank", "debt", "trace"):
        try:
            out[k] = int(after.get(k, 0) or 0) - int(before.get(k, 0) or 0)
        except Exception:
            out[k] = 0
    for fk in ("att_police", "att_corporate", "att_black_market"):
        if before.get(fk) != after.get(fk):
            out[fk] = {"from": before.get(fk), "to": after.get(fk)}
    # Always include queued counts (not deltas) for UI "What Changed".
    out["queued_events"] = int(after.get("queued_events", 0) or 0)
    out["queued_ripples"] = int(after.get("queued_ripples", 0) or 0)
    return out


def handle_special(state: dict[str, Any], cmd: str) -> bool:
    up = cmd.upper()
    if up == "HELP":
        console.print("[bold]HELP — Commands[/bold]")
        console.print("[dim]Core[/dim]")
        console.print("- HELP")
        console.print("- QUEST")
        console.print("- ATLAS [country]")
        console.print("- LANG id|en")
        console.print("- NARRATION compact|cinematic")
        console.print("- MODE NORMAL|IRONMAN")
        console.print("- UNDO  (Normal only)")
        console.print("- SAVE STATE")
        console.print("- WORLD_BRIEF")
        console.print("- INTENT_DEBUG")
        console.print("")
        console.print("[dim]Intel & tools[/dim]")
        console.print("- NPC <name>")
        console.print("- WHO")
        console.print("- HEAT")
        console.print("- OFFERS [role]   (contoh: OFFERS fixer)")
        console.print("- MARKET")
        console.print("- NPCSIM_STATS")
        console.print("- WHEREAMI")
        console.print("")
        console.print("[dim]Aliases[/dim]")
        console.print("- T <dest>  => travel <dest>")
        console.print("- H <text>  => hack <text>")
        console.print("- S <text>  => talk <text>")
        return True
    if up == "ATLAS" or up.startswith("ATLAS "):
        parts = cmd.split(maxsplit=2)
        world = state.get("world", {}) or {}
        atlas = world.get("atlas", {}) or {}
        gp = atlas.get("geopolitics", {}) if isinstance(atlas, dict) else {}
        try:
            t = int((gp.get("tension_idx", 0) if isinstance(gp, dict) else 0) or 0)
        except Exception:
            t = 0
        console.print("[bold]ATLAS[/bold]")
        console.print(f"- tension_idx={t}/100")
        if isinstance(gp, dict):
            sanc = gp.get("active_sanctions", []) or []
            if isinstance(sanc, list) and sanc:
                last = sanc[-1] if isinstance(sanc[-1], dict) else None
                if isinstance(last, dict):
                    console.print(f"- last_sanction: day={last.get('day','-')} {last.get('a','?')}↔{last.get('b','?')}")

        want = parts[1].strip().lower() if len(parts) >= 2 else ""
        try:
            from engine.atlas import ensure_country_profile, ensure_location_profile

            if not want:
                # Default to player's current country.
                loc = str((state.get("player", {}) or {}).get("location", "") or "").strip()
                prof = ensure_location_profile(state, loc) if loc else {}
                want = str((prof.get("country") if isinstance(prof, dict) else "") or "").strip().lower()
            if want:
                c = ensure_country_profile(state, want)
                console.print(f"- country={c.get('name', want)} currency={c.get('currency','-')} lang={c.get('dominant_lang','-')} law={c.get('law_level','-')} econ={c.get('econ_style','-')}")
                rel = c.get("relations", {}) if isinstance(c, dict) else {}
                if isinstance(rel, dict) and rel:
                    allies = [k for k, v in rel.items() if isinstance(v, dict) and str(v.get('stance','')).lower() == "ally"]
                    rivals = [k for k, v in rel.items() if isinstance(v, dict) and str(v.get('stance','')).lower() == "rival"]
                    if allies:
                        console.print("- allies: " + ", ".join(allies[:6]) + (" ..." if len(allies) > 6 else ""))
                    if rivals:
                        console.print("- rivals: " + ", ".join(rivals[:6]) + (" ..." if len(rivals) > 6 else ""))
        except Exception:
            pass
        return True
    if up == "DISGUISE" or up.startswith("DISGUISE "):
        parts = cmd.split(maxsplit=2)
        if len(parts) < 2:
            d = (state.get("player", {}) or {}).get("disguise") or {}
            if isinstance(d, dict) and d.get("active"):
                console.print(f"[yellow]DISGUISE aktif: {d.get('persona','?')} until D{d.get('until_day','?')} {_fmt_clock(int(d.get('until_time',0) or 0))}[/yellow]")
            else:
                console.print("[yellow]DISGUISE tidak aktif. Pakai: DISGUISE <persona> | DISGUISE OFF[/yellow]")
            return True
        arg = parts[1].strip()
        if arg.lower() in ("off", "stop", "none"):
            try:
                from engine.disguise import deactivate_disguise

                deactivate_disguise(state, reason="manual")
            except Exception:
                pass
            console.print("[green]DISGUISE off.[/green]")
            return True
        try:
            from engine.disguise import activate_disguise

            ok = activate_disguise(state, arg)
            if not ok:
                console.print("[red]DISGUISE gagal: cash tidak cukup (butuh ~40).[/red]")
            else:
                console.print(f"[green]DISGUISE aktif: {arg}[/green]")
        except Exception:
            console.print("[red]DISGUISE error.[/red]")
        return True
    if up == "SAFEHOUSE" or up.startswith("SAFEHOUSE "):
        parts = cmd.split(maxsplit=3)
        sub = parts[1].strip().lower() if len(parts) >= 2 else "status"
        try:
            from engine.safehouse import ensure_safehouse_here, rent_here, buy_here, upgrade_security

            row = ensure_safehouse_here(state)
            if sub in ("status", "info"):
                console.print("[bold]SAFEHOUSE[/bold]")
                console.print(f"- loc={str((state.get('player',{}) or {}).get('location','-'))}")
                console.print(f"- status={row.get('status','none')} rent_per_day={row.get('rent_per_day',0)} security=L{row.get('security_level',1)} delinquent={row.get('delinquent_days',0)}")
                st = row.get("stash") or []
                if isinstance(st, list) and st:
                    console.print(f"- stash({len(st)}): " + ", ".join([str(x) for x in st[:10]]) + (" ..." if len(st) > 10 else ""))
                return True
            if sub == "rent":
                ok = rent_here(state)
                console.print("[green]SAFEHOUSE rent OK[/green]" if ok else "[red]SAFEHOUSE rent gagal (butuh cash >= 50).[/red]")
                return True
            if sub == "buy":
                ok = buy_here(state)
                console.print("[green]SAFEHOUSE buy OK[/green]" if ok else "[red]SAFEHOUSE buy gagal (butuh cash >= 600).[/red]")
                return True
            if sub == "upgrade":
                ok = upgrade_security(state)
                console.print("[green]SAFEHOUSE upgrade OK[/green]" if ok else "[red]SAFEHOUSE upgrade gagal (butuh safehouse + cash).[/red]")
                return True
            if sub == "stash" and len(parts) >= 4:
                act = parts[2].strip().lower()
                item = parts[3].strip()
                stash = row.setdefault("stash", [])
                if not isinstance(stash, list):
                    stash = []
                    row["stash"] = stash
                inv = state.get("inventory", {}) or {}
                bag = inv.get("bag_contents", []) or []
                if act in ("put", "store"):
                    if isinstance(bag, list) and item in [str(x) for x in bag]:
                        inv["bag_contents"] = [x for x in bag if str(x) != item]
                        stash.append(item)
                        console.print(f"[green]STASH put {item}[/green]")
                    else:
                        console.print("[red]Item tidak ada di bag.[/red]")
                    return True
                if act in ("take", "get"):
                    if item in [str(x) for x in stash]:
                        row["stash"] = [x for x in stash if str(x) != item]
                        if isinstance(bag, list):
                            bag.append(item)
                            inv["bag_contents"] = bag[-40:]
                        console.print(f"[green]STASH take {item}[/green]")
                    else:
                        console.print("[red]Item tidak ada di stash.[/red]")
                    return True
            console.print("[yellow]Pakai: SAFEHOUSE status|rent|buy|upgrade|stash put <id>|stash take <id>[/yellow]")
        except Exception:
            console.print("[red]SAFEHOUSE error.[/red]")
        return True
    if up == "WEATHER":
        try:
            from engine.weather import ensure_weather

            meta = state.get("meta", {}) or {}
            day = int(meta.get("day", 1) or 1)
            loc = str((state.get("player", {}) or {}).get("location", "") or "").strip().lower()
            if not loc:
                console.print("[yellow]WEATHER: lokasi kosong.[/yellow]")
                return True
            w = ensure_weather(state, loc, day)
            console.print(f"[bold]WEATHER[/bold] {loc}: {w.get('kind','-')} (day {day})")
        except Exception:
            console.print("[red]WEATHER error.[/red]")
        return True
    if up == "SKILLS":
        sk = state.get("skills", {}) or {}
        if not isinstance(sk, dict) or not sk:
            console.print("[yellow]SKILLS kosong.[/yellow]")
            return True
        console.print("[bold]SKILLS[/bold]")
        for k in ("hacking", "social", "combat", "stealth", "evasion"):
            row = sk.get(k) if isinstance(sk.get(k), dict) else {}
            if not isinstance(row, dict):
                continue
            console.print(f"- {k}: lvl={row.get('level',1)} xp={row.get('xp',0)} cur={row.get('current',row.get('base',10))} decay={row.get('decay_penalty',0)}")
        return True
    if up == "QUEST" or up.startswith("QUEST "):
        q = state.get("quests", {}) or {}
        if not isinstance(q, dict):
            console.print("[yellow]QUEST: tidak ada data quest.[/yellow]")
            return True
        active = q.get("active") if isinstance(q.get("active"), list) else []
        done = q.get("completed") if isinstance(q.get("completed"), list) else []
        failed = q.get("failed") if isinstance(q.get("failed"), list) else []
        meta = state.get("meta", {}) or {}
        day = int(meta.get("day", 1) or 1)

        console.print("[bold]QUESTS[/bold]")
        console.print(f"- active={len(active)} completed={len(done)} failed={len(failed)} day={day}")
        if not active:
            console.print("[dim]Tidak ada quest aktif.[/dim]")
            return True

        tbl = Table(title="Active Quests")
        tbl.add_column("id", no_wrap=True)
        tbl.add_column("kind", no_wrap=True)
        tbl.add_column("step", justify="right")
        tbl.add_column("deadline", justify="right")
        tbl.add_column("objective")
        tbl.add_column("reward", no_wrap=True)
        for quest in active[:15]:
            if not isinstance(quest, dict):
                continue
            qid = str(quest.get("id", "?") or "?")
            kind = str(quest.get("kind", "-") or "-")
            step = int(quest.get("step", 0) or 0)
            steps = quest.get("steps") if isinstance(quest.get("steps"), list) else []
            obj = "-"
            if steps and 0 <= step < len(steps) and isinstance(steps[step], dict):
                obj = str(steps[step].get("desc", steps[step].get("name", "-")) or "-")
            dl = int(quest.get("deadline_day", 0) or 0)
            rew = quest.get("reward") if isinstance(quest.get("reward"), dict) else {}
            cash = int(rew.get("cash", 0) or 0) if isinstance(rew, dict) else 0
            tr = int(rew.get("trace_delta", 0) or 0) if isinstance(rew, dict) else 0
            rew_s = f"cash {cash:+d}, trace {tr:+d}"
            if quest.get("status") == "overdue":
                rew_s = "OVERDUE: reward reduced"
            tbl.add_row(qid, kind, f"{step+1}/{max(1,len(steps))}", str(dl), obj, rew_s)
        console.print(tbl)
        return True
    # UNDO (Normal mode only): restore previous.json into current in-memory state.
    if up == "UNDO":
        iron = bool((state.get("flags", {}) or {}).get("ironman_mode", False))
        if iron:
            console.print("[red]IRONMAN mode aktif: UNDO dinonaktifkan.[/red]")
            return True
        if PREVIOUS.exists():
            try:
                restored = load_state(PREVIOUS)
                state.clear()
                state.update(restored)
                console.print("[green]UNDO: restored previous turn.[/green]")
            except Exception:
                console.print("[red]UNDO gagal: previous.json tidak bisa dibaca.[/red]")
        else:
            console.print("[yellow]UNDO tidak tersedia (previous.json belum ada).[/yellow]")
        return True
    if up == "MODE" or up.startswith("MODE "):
        parts = cmd.split(maxsplit=2)
        if len(parts) < 2:
            iron = bool((state.get("flags", {}) or {}).get("ironman_mode", False))
            console.print(f"[yellow]Mode: {'IRONMAN' if iron else 'NORMAL'}[/yellow]")
            console.print("[dim]Pakai: MODE NORMAL | MODE IRONMAN[/dim]")
            return True
        mode = parts[1].strip().lower()
        if mode not in ("normal", "ironman"):
            console.print("[red]Pakai: MODE NORMAL | MODE IRONMAN[/red]")
            return True
        state.setdefault("flags", {})["ironman_mode"] = (mode == "ironman")
        console.print(f"[green]Mode set → {mode.upper()}[/green]")
        return True
    if up == "SAVE STATE":
        console.print(json.dumps(state, ensure_ascii=False, indent=2))
        return True
    if up == "WORLD_BRIEF":
        lang = get_narration_lang(state)
        if lang == "en":
            turn_package = "WORLD_BRIEF: summarize the world from the player character's POV in <=400 words."
        else:
            turn_package = "WORLD_BRIEF: rangkum dunia dari sudut pandang karakter pemain, maksimal ~400 kata, Bahasa Indonesia."
        try:
            for chunk in stream_response(build_system_prompt(state), turn_package):
                stream_render(chunk)
            console.print()
        except Exception:
            console.print("[red]// SIGNAL LOST //[/red]")
        return True
    if up == "INTENT_DEBUG":
        meta = state.get("meta", {}) or {}
        console.print("[bold cyan]// INTENT DEBUG //[/bold cyan]")
        console.print(f"last_intent_source={meta.get('last_intent_source', '-')}")
        raw = meta.get("last_intent_raw")
        if raw is not None:
            console.print("last_intent_raw=")
            console.print(json.dumps(raw, ensure_ascii=False, indent=2))
        else:
            console.print("last_intent_raw=(none)")
        return True
    if up == "LANG" or up.startswith("LANG "):
        parts = cmd.split(maxsplit=2)
        if len(parts) < 2:
            console.print(f"[yellow]Bahasa narasi: {get_narration_lang(state)} (ketik: LANG id | LANG en)[/yellow]")
            return True
        code = parts[1].lower()
        if code not in ("id", "en"):
            console.print("[red]Pakai: LANG id atau LANG en[/red]")
            return True
        state.setdefault("player", {})["language"] = code
        if os.getenv("NARRATION_LANG", "").strip():
            console.print("[dim]Catatan: NARRATION_LANG di .env menimpa — kosongkan untuk pakai LANG.[/dim]")
        console.print(f"[green]Narasi AI → {'Bahasa Indonesia' if code == 'id' else 'English'}[/green]")
        return True
    if up == "NARRATION" or up.startswith("NARRATION "):
        parts = cmd.split(maxsplit=2)
        if len(parts) < 2:
            style = str(state.get("player", {}).get("narration_style", "cinematic") or "cinematic").lower()
            console.print(f"[yellow]Narasi style: {style} (ketik: NARRATION compact | NARRATION cinematic)[/yellow]")
            return True
        style = parts[1].strip().lower()
        if style not in ("compact", "cinematic"):
            console.print("[red]Pakai: NARRATION compact | NARRATION cinematic[/red]")
            return True
        state.setdefault("player", {})["narration_style"] = style
        console.print(f"[green]Narasi style → {style}[/green]")
        return True
    if up == "HEAT":
        world = state.get("world", {}) or {}
        hh = world.get("hacking_heat", {}) or {}
        loc = str(state.get("player", {}).get("location", "") or "").strip().lower()
        tbl = Table(title="HEAT (per target @ lokasi)")
        tbl.add_column("target", no_wrap=True)
        tbl.add_column("heat", justify="right")
        tbl.add_column("noise", justify="right")
        tbl.add_column("signal", justify="right")
        tbl.add_column("rekomendasi")
        rows = 0
        if isinstance(hh, dict):
            for k, v in hh.items():
                if not isinstance(k, str) or not isinstance(v, dict):
                    continue
                if loc and not k.startswith(loc + "|"):
                    continue
                target = k.split("|", 1)[1] if "|" in k else k
                try:
                    heat = int(v.get("heat", 0) or 0)
                except Exception:
                    heat = 0
                try:
                    noise = int(v.get("noise", 0) or 0)
                except Exception:
                    noise = 0
                try:
                    signal = int(v.get("signal", 0) or 0)
                except Exception:
                    signal = 0
                rec = "OK"
                if heat >= 75 or signal >= 75:
                    rec = "COVER TRACKS / jeda / stealth"
                elif heat >= 45 or noise >= 45:
                    rec = "stealth / jeda"
                tbl.add_row(str(target), str(heat), str(noise), str(signal), rec)
                rows += 1
        if rows == 0:
            console.print("[yellow]HEAT: tidak ada data untuk lokasi ini.[/yellow]")
        else:
            console.print(tbl)
        return True
    if up == "OFFERS" or up.startswith("OFFERS "):
        parts = cmd.split(maxsplit=2)
        want_role = parts[1].strip().lower() if len(parts) >= 2 else ""
        econ = (state.get("world", {}) or {}).get("npc_economy", {}) or {}
        offers = econ.get("offers", {}) if isinstance(econ, dict) else {}
        if not isinstance(offers, dict) or not offers:
            console.print("[yellow]OFFERS: tidak ada offer aktif.[/yellow]")
            return True
        meta = state.get("meta", {}) or {}
        day = int(meta.get("day", 1) or 1)
        out: list[str] = []
        for k in sorted(list(offers.keys())):
            v = offers.get(k)
            if not isinstance(v, dict):
                continue
            role = str(v.get("role", "") or "").strip().lower()
            if want_role and role != want_role:
                continue
            npc = str(v.get("npc", k))
            svc = str(v.get("service", "offer"))
            try:
                exp = int(v.get("expires_day", day) or day)
            except Exception:
                exp = day
            ttl = max(0, exp - day)
            out.append(f"- {npc} ({role}): {svc} (ttl {ttl}d)")
        if not out:
            console.print(f"[yellow]OFFERS: tidak ada offer untuk role '{want_role}'.[/yellow]")
        else:
            console.print(f"[bold]OFFERS{' ' + want_role if want_role else ''}[/bold]")
            for line in out[:25]:
                console.print(line)
        return True
    if up == "NPC" or up.startswith("NPC "):
        parts = cmd.split(maxsplit=2)
        if len(parts) < 2:
            console.print("[yellow]Pakai: NPC <nama>[/yellow]")
            return True
        name = parts[1]
        npcs = state.get("npcs", {}) or {}
        if not isinstance(npcs, dict) or name not in npcs or not isinstance(npcs.get(name), dict):
            console.print(f"[red]NPC tidak ditemukan: {name}[/red]")
            return True
        npc = npcs.get(name) or {}
        bs = npc.get("belief_summary") or {}
        if not isinstance(bs, dict):
            bs = {}
        sus = bs.get("suspicion", 0)
        rep = bs.get("respect", 50)
        g = (state.get("world", {}) or {}).get("social_graph", {}) or {}
        edge = {}
        if isinstance(g, dict):
            p = g.get("__player__", {}) or {}
            if isinstance(p, dict):
                e = p.get(name)
                if isinstance(e, dict):
                    edge = e
        console.print(f"[bold]NPC: {name}[/bold]")
        console.print(f"- role={npc.get('role','-')} aff={npc.get('affiliation','civilian')} mood={npc.get('mood','-')}")
        console.print(f"- loc={npc.get('current_location', npc.get('home_location','-'))} home={npc.get('home_location','-')}")
        console.print(f"- belief: suspicion={sus} respect={rep}")
        if edge:
            console.print(f"- edge(player↔npc): type={edge.get('type','-')} strength={edge.get('strength','-')} last_day={edge.get('last_interaction_day','-')}")
        snips = npc.get("belief_snippets") or []
        if isinstance(snips, list) and snips:
            console.print("  snippets (latest 3):")
            for it in snips[-3:]:
                if not isinstance(it, dict):
                    continue
                console.print(f"  - ({it.get('source','?')}) {it.get('topic','?')}: {str(it.get('claim','-'))[:120]}")
        return True
    if up == "MARKET":
        eco = state.get("economy", {}) or {}
        mkt = eco.get("market", {}) or {}
        # Location-specific market snapshot (if present).
        try:
            loc = str(state.get("player", {}).get("location", "") or "").strip().lower()
            slot = ((state.get("world", {}) or {}).get("locations", {}) or {}).get(loc)
            if isinstance(slot, dict) and isinstance(slot.get("market"), dict) and slot.get("market"):
                mkt = slot.get("market") or mkt
        except Exception:
            pass
        mi = (state.get("meta", {}) or {}).get("market_index") or {}
        if not isinstance(mkt, dict) or not mkt:
            console.print("[yellow]MARKET: data market kosong.[/yellow]")
            return True
        tbl = Table(title="MARKET")
        tbl.add_column("category", no_wrap=True)
        tbl.add_column("price_idx", justify="right")
        tbl.add_column("scarcity", justify="right")
        if isinstance(mi, dict) and mi:
            tbl.caption = f"idx_avg price={mi.get('price_avg','-')} (Δ{mi.get('d_price','0')}) | scarcity={mi.get('scarcity_avg','-')} (Δ{mi.get('d_scarcity','0')})"
        for cat in ("electronics", "medical", "weapons", "food", "transport"):
            row = mkt.get(cat) if isinstance(mkt.get(cat), dict) else {}
            if not isinstance(row, dict):
                continue
            tbl.add_row(cat, str(row.get("price_idx", "-")), str(row.get("scarcity", "-")))
        console.print(tbl)
        return True
    if up == "WHO":
        npcs = state.get("npcs", {}) or {}
        if not isinstance(npcs, dict) or not npcs:
            console.print("[yellow]WHO: tidak ada NPC di state.[/yellow]")
            return True
        loc = str(state.get("player", {}).get("location", "") or "").strip().lower()
        console.print("[bold]WHO[/bold]")
        shown = 0
        for name, npc in list(npcs.items())[:40]:
            if not isinstance(npc, dict):
                continue
            role = npc.get("role", "-")
            aff = npc.get("affiliation", "civilian")
            mood = npc.get("mood", "-")
            here = str(npc.get("current_location", npc.get("home_location", "")) or "").strip().lower()
            tag = "here" if loc and here == loc else ("remote" if here else "-")
            console.print(f"- {name}: role={role} aff={aff} mood={mood} loc={tag}")
            shown += 1
            if shown >= 20:
                break
        return True
    if up == "NPCSIM_STATS":
        meta = state.get("meta", {}) or {}
        c = meta.get("npc_sim_last_counts") or {}
        console.print("[bold]NPCSIM_STATS[/bold]")
        console.print(json.dumps(c, ensure_ascii=False, indent=2))
        return True
    if up == "WHEREAMI":
        p = state.get("player", {}) or {}
        world = state.get("world", {}) or {}
        locs = world.get("locations", {}) or {}
        known = sorted([str(k) for k in locs.keys()]) if isinstance(locs, dict) else []
        console.print("[bold]WHEREAMI[/bold]")
        console.print(f"- loc={p.get('location','-')} year={p.get('year','-')} seed={state.get('meta',{}).get('seed_pack','-')}")
        # Location profile (culture/econ/law background).
        try:
            from engine.atlas import ensure_location_profile, fmt_profile_short

            loc = str(p.get("location", "") or "").strip()
            if loc:
                prof = ensure_location_profile(state, loc)
                console.print(f"- profile: {fmt_profile_short(prof)}")
        except Exception:
            pass
        if known:
            console.print(f"- known_locations({len(known)}): " + ", ".join(known[:12]) + (" ..." if len(known) > 12 else ""))
        else:
            console.print("- known_locations: (none)")
        return True
    if cmd.lower() in ("quit", "exit"):
        if _ask("Keluar? [Y/N]: ").lower() in ("y", "yes"):
            backup_state()
            save_state(state)
            raise SystemExit(0)
        return True
    return False


def main() -> None:
    if CURRENT.exists() and _ask("Lanjutkan sesi sebelumnya? [Y/N]: ").lower() in ("y", "yes"):
        state = load_state()
    else:
        state = boot_sequence()
        backup_state()
        save_state(state)

    while True:
        render_monitor(state)
        cmd = _expand_alias(_ask("> "))
        if not cmd:
            continue
        if handle_special(state, cmd):
            continue

        metrics_before = _snapshot_metrics(state)

        # 1) Intent resolution: prefer LLM, fallback to heuristic parser.
        intent = resolve_intent(state, cmd)
        if intent:
            action_ctx = parse_action_intent(cmd)
            for key in (
                "action_type",
                "domain",
                "combat_style",
                "social_mode",
                "social_context",
                "intent_note",
                "targets",
                "stakes",
                "risk_level",
                "time_cost_min",
                "travel_destination",
                "inventory_ops",
            ):
                if key in intent and intent[key] is not None:
                    action_ctx[key] = intent[key]
            try:
                conf = float(intent.get("confidence", 0.0))
            except Exception:
                conf = 0.0
            action_ctx["intent_confidence"] = conf
            meta = state.setdefault("meta", {})
            meta["last_intent_source"] = "llm"
            meta["last_intent_raw"] = intent
            stakes = intent.get("stakes")
            if isinstance(stakes, str):
                action_ctx["has_stakes"] = stakes not in ("none", "low")
                if action_ctx.get("domain") == "social" and action_ctx.get("social_mode") == "conflict":
                    action_ctx["has_stakes"] = True
                if action_ctx.get("domain") == "combat":
                    if str(action_ctx.get("intent_note", "")).strip().lower() not in ("switch_weapon", "equip_weapon_only"):
                        action_ctx["has_stakes"] = True
            norm = str(action_ctx.get("normalized_input", cmd)).lower()
            if action_ctx.get("domain") == "combat" and action_ctx.get("combat_style") == "ranged":
                if any(w in norm for w in ("tembak", "menembak", "shoot", "fire")):
                    action_ctx["has_stakes"] = True
            if action_ctx.get("domain") == "combat" and action_ctx.get("action_type") != "combat":
                action_ctx["action_type"] = "combat"
            try:
                tcm = int(intent.get("time_cost_min", 0) or 0)
            except Exception:
                tcm = 0
            if tcm > 0:
                if action_ctx.get("action_type") == "travel":
                    action_ctx["travel_minutes"] = max(5, min(240, tcm))
                else:
                    action_ctx["instant_minutes"] = max(1, min(60, tcm))
        else:
            action_ctx = parse_action_intent(cmd)
            meta = state.setdefault("meta", {})
            meta["last_intent_source"] = "parser_fallback"
            meta["last_intent_raw"] = None

        # Visibility hint (for attention/trace scaling on combat/hacking).
        cmd_norm = str(action_ctx.get("normalized_input", cmd) or cmd).lower()
        stealth_terms = ("diam-diam", "mengendap", "sembunyi", "stealth", "tidak terlihat", "tanpa diketahui")
        if str(action_ctx.get("domain", "")).lower() in ("combat", "hacking"):
            action_ctx["visibility"] = "low" if any(t in cmd_norm for t in stealth_terms) else "public"

        # Deterministic pickup augmentation:
        # Jika player menyebut sebuah objek yang ada di scene (state.world.nearby_items),
        # tambahkan `inventory_ops: pickup` agar aksi pickup tidak "wasted turn"
        # meski LLM gagal / tidak ngeluarin inventory_ops.
        cmd_lower = str(cmd).lower()
        inv_ops = action_ctx.get("inventory_ops")
        if not isinstance(inv_ops, list):
            inv_ops = []
            action_ctx["inventory_ops"] = inv_ops

        nearby = (state.get("world", {}) or {}).get("nearby_items", []) or []
        candidates: list[tuple[str, str]] = []
        if isinstance(nearby, list):
            for elem in nearby[:25]:
                if isinstance(elem, dict):
                    item_id = str(elem.get("id") or elem.get("item_id") or elem.get("name") or "").strip()
                    item_name = str(elem.get("name") or elem.get("id") or item_id or "").strip()
                    if item_id:
                        candidates.append((item_id, item_name or item_id))
                elif isinstance(elem, str):
                    s = elem.strip()
                    if s:
                        candidates.append((s, s))

        def _contains_candidate(item_id: str, item_name: str) -> bool:
            item_id_l = item_id.lower()
            item_name_l = item_name.lower()
            if item_id_l and item_id_l in cmd_lower:
                return True
            if item_name_l and item_name_l in cmd_lower:
                return True
            # Handle ids like "laptop1" vs "laptop" in player text.
            base_id = "".join([ch for ch in item_id_l if not ch.isdigit()]).strip()
            return bool(base_id and base_id in cmd_lower)

        already_pickups = {
            str(op.get("item_id", "")).strip()
            for op in inv_ops
            if isinstance(op, dict) and str(op.get("op", "")).lower() == "pickup"
        }
        for item_id, item_name in candidates:
            if item_id in already_pickups:
                continue
            if _contains_candidate(item_id, item_name):
                inv_ops.append(
                    {
                        "op": "pickup",
                        "item_id": item_id,
                        "to": "pocket",
                        "time_cost_min": 2,
                    }
                )
                already_pickups.add(item_id)

        # NPC targeting enhancement (e.g. "orang itu" → npc_focus).
        apply_npc_targeting(state, action_ctx, cmd)

        roll_pkg = run_pipeline(state, action_ctx)

        metrics_after = _snapshot_metrics(state)
        state.setdefault("meta", {})["last_turn_diff"] = _compute_diff(metrics_before, metrics_after)

        package = build_turn_package(state, cmd, roll_pkg, action_ctx)
        system_prompt = build_system_prompt(state)

        text = ""
        try:
            for chunk in stream_response(system_prompt, package):
                text += chunk
                stream_render(chunk)
            console.print()
        except Exception:
            console.print("[red]// SIGNAL LOST //[/red]")
            try:
                for chunk in stream_response(system_prompt, package):
                    text += chunk
                    stream_render(chunk)
                console.print()
            except Exception:
                console.print("[red]Stream gagal, output parsial disimpan.[/red]")

        if text:
            text = enforce_stop_sequence_output(text, bool(state.get("flags", {}).get("stop_sequence_active")))
            record_ai_parse_health(state, text)
            mh = parse_memory_hash(text)
            apply_memory_hash_to_state(state, mh)

        # Stop sequence enforcement in UI/runtime contract
        if state.get("flags", {}).get("stop_sequence_active"):
            console.print("\nApa rencanamu?")

        log_turn_outcome(state, action_ctx, roll_pkg)
        state.setdefault("meta", {})["turn"] = int(state["meta"].get("turn", 0)) + 1
        backup_state()
        save_state(state)


if __name__ == "__main__":
    main()

