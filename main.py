from __future__ import annotations

from engine.core.error_taxonomy import log_swallowed_exception
from engine.core.feed_prune import world_note_plain
import asyncio
import difflib
import json
import os
import sys
from pathlib import Path
from typing import Any

import aioconsole

from rich.table import Table

from ai.async_llm_ui import run_narration_stream_with_heartbeat
from ai.client import stream_response  # sync bridge + session handlers
from ai.intent_resolver import resolve_intent_async
from ai.parser import apply_memory_hash_to_state, enforce_stop_sequence_output, parse_memory_hash, record_ai_parse_health
from ai.turn_prompt import build_system_prompt, build_turn_package, get_narration_lang
from display.renderer import console, format_data_table, render_monitor, stream_render
from engine.core.action_intent import apply_active_scene_intent_lock, normalize_action_ctx, parse_action_intent
from engine.core.errors import record_error
from engine.core.ffci import (
    abuse_allow_custom_intent,
    clamp_suggested_dc_ctx,
    ffci_enabled,
    ffci_shadow_only,
    record_custom_high_risk,
    update_ffci_custom_streak,
)
from engine.core.pipeline import run_pipeline
from engine.npc.npc_utility_ai import evaluate_npc_goals
from engine.player.boot_economy import format_boot_economy_preview
from engine.core.seeds import list_seed_names
from engine.core.main_cli_imports import (
    INTENT_MERGE_FIELD_KEYS,
    VEHICLE_TYPES,
    activate_disguise,
    advance_scene,
    apply_cross_system_policies,
    apply_intent_plan_precondition_failure,
    apply_npc_targeting,
    apply_parser_registry_anchor_after_llm,
    apply_pending_runtime_step,
    apply_step_to_action_ctx,
    bank_aml_snapshot,
    bank_deposit,
    bank_withdraw,
    black_market_accessible,
    burn_informant,
    buy_black_market_item,
    buy_here,
    buy_vehicle,
    communication_quality,
    deactivate_disguise,
    default_city_for_country,
    describe_location,
    ensure_country_profile,
    ensure_location_profile,
    ensure_safehouse_here,
    ensure_weather,
    execute_gig,
    execute_hack,
    generate_black_market_inventory,
    generate_gigs,
    get_stay_here,
    handle_career,
    handle_commerce,
    handle_economy,
    handle_faction_report,
    handle_misc,
    handle_mobility,
    handle_property,
    handle_scene_commands,
    handle_session,
    handle_smartphone,
    handle_social_intel,
    handle_underworld,
    is_known_place,
    learn_language,
    list_districts,
    list_known_cities,
    list_known_countries,
    list_owned_vehicles,
    maybe_trigger_stay_raid,
    merge_intent_into_action_ctx,
    merge_telemetry_turn_last,
    nightly_rate,
    normalize_country_name,
    normalize_stay_kind,
    pay_informant,
    player_language_proficiency,
    post_turn_integration,
    refuel_vehicle,
    registry_hint_alignment,
    rent_here,
    repair_vehicle,
    sanitize_player_command_text,
    security_flags_for_intent_input,
    seed_informant_roster,
    select_best_step,
    sell_vehicle,
    set_active_vehicle,
    set_pending_raid_response,
    snapshot_turn_telemetry,
    stash_put_ammo,
    stash_put_from_bag,
    stash_take_ammo,
    stash_take_to_bag,
    stay_checkin,
    stay_help_aliases,
    stay_kind_label,
    steal_vehicle,
    strip_llm_intent_overlay_on_registry_hint_mismatch,
    sync_plan_runtime_start,
    travel_within_city,
    try_auto_stay_from_intent,
    try_reload,
    update_timers,
    upgrade_security,
)
from engine.core.state import CURRENT, PREVIOUS, backup_state, initialize_state, load_state, save_state
from engine.systems.shop import buy_item, get_capacity_status, list_shop_quotes, sell_item, sell_item_all, sell_item_n, quote_item


def _ask(prompt: str) -> str:
    return input(prompt).strip()


async def _ainput_line(prompt: str) -> str:
    """Non-blocking-friendly stdin for the asyncio game loop (aioconsole)."""
    return (await aioconsole.ainput(prompt)).rstrip("\r\n").strip()


def _record_soft_error(state: dict[str, Any], scope: str, err: Exception) -> None:
    try:
        record_error(state, scope, err)
    except Exception as _omni_sw_42:
        log_swallowed_exception('main.py:42', _omni_sw_42)
def _load_occupation_templates() -> list[dict[str, Any]]:
    """Boot-time helper: read core occupations templates (optional)."""
    try:
        path = Path(__file__).resolve().parent / "data" / "packs" / "core" / "occupations.json"
        if not path.exists():
            return []
        doc = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(doc, dict):
            return []
        temps = doc.get("templates", [])
        if not isinstance(temps, list):
            return []
        out: list[dict[str, Any]] = []
        for t in temps[:30]:
            if isinstance(t, dict) and isinstance(t.get("id"), str):
                out.append(t)
        return out
    except Exception as _omni_sw_63:
        log_swallowed_exception('main.py:63', _omni_sw_63)
        return []


def _label_from_template_id(template_id: str, temps: list[dict[str, Any]]) -> str:
    """Human-ish occupation string from template id (for economy keywords + display)."""
    tid = (template_id or "").strip().lower()
    if not tid:
        return ""
    for t in temps:
        if not isinstance(t, dict):
            continue
        if str(t.get("id", "")).strip().lower() != tid:
            continue
        name = str(t.get("name", "") or "").strip()
        if name:
            return name.split("/")[0].strip()
        return tid.replace("_", " ").title()
    return tid.replace("_", " ").title()


def _print_boot_keyword_examples() -> None:
    """Mini keyword hints per tier (Rich OK here; not inside input() prompts)."""
    console.print(
        "\n[bold]Contoh kata kunci tier ekonomi awal[/bold] [dim](occupation + background)[/dim]"
    )
    console.print(
        "  [bold]Tinggi:[/bold] ceo, director, lawyer, engineer, manager, dokter, pilot, investor"
    )
    console.print(
        "  [bold]Menengah:[/bold] tidak ada kata di atas/bawah yang dominan, atau campuran seimbang"
    )
    console.print(
        "  [bold]Rendah:[/bold] student, driver, unemployed, cashier, waiter, buruh, mahasiswa, gig"
    )


def _boot_role_step(data: dict[str, Any], temps: list[dict[str, Any]]) -> None:
    """Step (2): template loadout + occupation/background text (mutates data)."""
    console.print("\n[bold](2) Peran[/bold] [dim]— template loadout + occupation/background[/dim]")
    if temps:
        console.print("\n[bold cyan]Template loadout[/bold cyan] [dim]— skill + peralatan awal (bukan nominal uang)[/dim]")
        for t in temps[:10]:
            console.print(f"  [dim]-[/dim] [bold]{t.get('id', '-')}[/bold]: {t.get('name', '')}")
        pick = _ask("Template [ketik id / Enter = nanti otomatis dari teks occupation+background]: ").strip().lower()
        if pick and pick not in ("auto", "none", "-", "skip"):
            data["occupation_template_id"] = pick.strip().lower()
        else:
            data.pop("occupation_template_id", None)
    else:
        data.pop("occupation_template_id", None)

    console.print("\n[bold green]Profil teks[/bold green] [dim]— kata kunci untuk tier ekonomi awal[/dim]")
    def_occ = ""
    if data.get("occupation_template_id"):
        def_occ = _label_from_template_id(str(data["occupation_template_id"]), temps)
    occ_hint = f" (Enter = '{def_occ}' dari template)" if def_occ else " (bebas; kosong ≈ ekonomi menengah)"
    raw_occ = _ask(f"occupation{occ_hint}: ")
    if not str(raw_occ).strip() and def_occ:
        data["occupation"] = def_occ
        console.print(f"[dim]→ occupation diisi otomatis: {def_occ}[/dim]")
    else:
        data["occupation"] = str(raw_occ).strip()

    raw_bg = _ask("background (lore singkat; kosong = netral untuk ekonomi): ")
    data["background"] = str(raw_bg).strip()


def _bootstrap_location_input(*, seed_pack: str | None = None) -> str:
    """Location picker with manual override (deterministic normalization remains in engine)."""
    cities = list_known_cities()
    countries = list_known_countries()
    if not cities:
        return _ask("location: ").strip().lower()

    top_cities = [c for c in ("jakarta", "london", "tokyo", "nyc", "paris", "berlin", "mumbai", "singapore") if c in cities]
    if not top_cities:
        top_cities = cities[:8]

    console.print("[dim]Location mode: [1] pick city  [2] search  [3] manual[/dim]")
    mode = (_ask("location_mode [1/2/3, default=1]: ").strip().lower() or "1")

    if mode == "1":
        console.print("[dim]Popular cities:[/dim] " + ", ".join(top_cities))
        pick = _ask("pick_city [enter for manual]: ").strip().lower()
        if pick:
            return pick
        return _ask("location(manual): ").strip().lower()

    # Seed used only for deterministic country->city mapping during boot.
    seed_for_country_city = str(seed_pack or "").strip()

    if mode == "2":
        for _ in range(2):
            q = _ask("search keyword(city/country): ").strip().lower()
            if not q:
                break
            city_hits = [x for x in cities if q in x][:8]
            country_hits = [x for x in countries if q in x][:8]
            opts: list[str] = []
            if city_hits:
                console.print("[dim]City hits:[/dim]")
                for c in city_hits:
                    opts.append(c)
                    console.print(f"[dim]  {len(opts)}. {c}[/dim]")
            if country_hits:
                console.print("[dim]Country hits:[/dim]")
                for c in country_hits:
                    if c not in opts:
                        opts.append(c)
                        console.print(f"[dim]  {len(opts)}. {c}[/dim]")
            if not opts:
                pool = sorted(set(cities + countries))
                near = difflib.get_close_matches(q, pool, n=5, cutoff=0.65)
                if near:
                    console.print("[dim]Did you mean:[/dim] " + ", ".join(near))
                continue
            picked = _ask("choose [index/name] or Enter to re-search: ").strip().lower()
            if not picked:
                continue
            if picked.isdigit():
                ix = int(picked)
                if 1 <= ix <= len(opts):
                    picked = opts[ix - 1]
            # If country selected, map deterministically to a default city.
            if is_known_place(picked):
                c, kind = resolve_place(picked)
                if kind == "country":
                    dc = default_city_for_country(c, seed=seed_for_country_city)
                    if isinstance(dc, str) and dc.strip():
                        return dc.strip().lower()
            return picked.strip().lower()
        return _ask("location(manual): ").strip().lower()

    # Manual mode.
    raw = _ask("location(manual): ").strip().lower()
    if raw and not is_known_place(raw):
        pool = sorted(set(cities + countries))
        near = difflib.get_close_matches(raw.lower(), pool, n=5, cutoff=0.65)
        if near:
            console.print("[dim]Unknown place. Suggestions:[/dim]")
            for i, nm in enumerate(near, start=1):
                console.print(f"[dim]  {i}. {nm}[/dim]")
            retry = _ask("pick [index/name] or Enter keep manual: ").strip().lower()
            if retry:
                if retry.isdigit():
                    ix = int(retry)
                    if 1 <= ix <= len(near):
                        return near[ix - 1]
                return retry
    return raw


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
    console.print("[bold red]OMNI-ENGINE v6.9[/bold red]")
    console.print(
        "[bold]Setup karakter — wizard 3 langkah[/bold]\n"
        "[dim]"
        "[bold](1) Identitas[/bold]: nama, umur, tahun.\n"
        "[bold](2) Peran[/bold]: template loadout (skill/item) + occupation/background (kata kunci tier ekonomi awal).\n"
        "[bold](3) Preview + konfirmasi[/bold]: perkiraan tier/rentang ekonomi, lalu Y/N sebelum seed pack & lokasi.\n"
        "[/dim]"
    )
    console.print(
        "[dim]• [cyan]Template[/cyan] = loadout: skill awal + barang. [bold]Tidak[/bold] mengganti nominal uang secara langsung.\n"
        "• [green]occupation[/green] + [green]background[/green] = teks bebas; engine memetakan [bold]tier ekonomi awal[/bold] "
        "(cash, bank, burn, FICO, CC) lewat kata kunci. Keduanya kosong ≈ tier [bold]menengah[/bold].\n"
        "• [magenta]background[/magenta] = lore singkat; ikut keyword ekonomi + pencocokan template otomatis bila template tidak dipilih.\n"
        "[/dim]"
    )
    _print_boot_keyword_examples()

    data: dict[str, Any] = {}
    while True:
        data = {}
        quick_exit = False

        # --- (1) Identity ---
        console.print("\n[bold](1) Identitas[/bold] [dim]— atau ketik QUICK BOOT <lokasi> <tahun>[/dim]")
        for key in ("name", "age", "year"):
            raw = _ask(f"{key}: ")
            if raw.upper().startswith("QUICK BOOT "):
                parts = raw.split(maxsplit=3)
                if len(parts) == 4:
                    data["location"], data["year"] = parts[2].strip().lower(), parts[3]
                    data.setdefault("name", "Generated Subject")
                    data.setdefault("occupation", "Operator")
                    data.setdefault("background", "Quick boot profile")
                    quick_exit = True
                    break
            data[key] = raw

        temps = _load_occupation_templates()

        if quick_exit:
            console.print("\n[bold cyan]Ringkasan QUICK BOOT (default)[/bold cyan]")
            console.print(f"  nama: {data.get('name')}")
            console.print(f"  tahun: {data.get('year')}")
            console.print(f"  lokasi: {data.get('location')}")
            console.print(f"  occupation: {data.get('occupation')}")
            console.print(f"  background: {data.get('background')}")
            console.print("\n[bold](3) Preview ekonomi awal[/bold] [dim](perkiraan tier/rentang)[/dim]")
            console.print(
                format_boot_economy_preview(
                    str(data.get("occupation", "") or ""),
                    str(data.get("background", "") or ""),
                    data.get("year"),
                )
            )
            yn = _ask("Lanjutkan? [Y/N, default=Y]: ").strip().lower()
            if yn in ("n", "no"):
                console.print("[dim]Ulangi dari identitas…[/dim]")
                continue
            break

        while True:
            _boot_role_step(data, temps)
            console.print("\n[bold](3) Preview ekonomi awal + konfirmasi[/bold]")
            occ = str(data.get("occupation", "") or "")
            bg = str(data.get("background", "") or "")
            yr = data.get("year")
            console.print(format_boot_economy_preview(occ, bg, yr))
            tid = data.get("occupation_template_id")
            console.print("\n[bold]Ringkasan sebelum seed & lokasi[/bold]")
            console.print(f"  Template loadout: {tid or '(otomatis / tidak ada)'}")
            console.print(f"  occupation: {occ or '(kosong)'}")
            console.print(f"  background: {bg or '(kosong)'}")
            console.print(f"  tahun: {yr}")
            yn = _ask("Lanjutkan? [Y/N, default=Y]: ").strip().lower()
            if yn not in ("n", "no"):
                break
            console.print("[dim]Kembali mengisi peran (template + occupation + background)…[/dim]")
        break

    # Seed pack selection (do this BEFORE location picker so country->city mapping is seed-based).
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

    if "location" not in data:
        data["location"] = _bootstrap_location_input(seed_pack=seed_pack)
    return initialize_state(data, seed_pack=seed_pack)


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
    notes = state.get("world_notes", []) or []
    player = state.get("player", {}) or {}
    # Hacking heat aggregate (current location only).
    hh = world.get("hacking_heat", {}) or {}
    loc = str(player.get("location", "") or "").strip().lower()
    heat_sum = 0
    if isinstance(hh, dict) and loc:
        for k, v in hh.items():
            if not isinstance(k, str) or not isinstance(v, dict):
                continue
            if not k.startswith(loc + "|"):
                continue
            try:
                heat_sum += int(v.get("heat", 0) or 0)
            except Exception as _omni_sw_380:
                log_swallowed_exception('main.py:380', _omni_sw_380)
    # Weather kind (if cached on the current location slot).
    weather_kind = "-"
    try:
        slot = (world.get("locations", {}) or {}).get(loc) if loc else None
        if isinstance(slot, dict):
            w = slot.get("weather", {}) or {}
            if isinstance(w, dict) and w.get("kind"):
                weather_kind = str(w.get("kind"))
    except Exception as e:
        log_swallowed_exception('main.py:390', e)
        try:
            record_error(state, "main.snapshot_metrics.weather", e)
        except Exception as _omni_sw_395:
            log_swallowed_exception('main.py:395', _omni_sw_395)
    # Safehouse status at current location.
    sh_status = "none"
    sh_sec = 0
    sh_delin = 0
    try:
        sh = world.get("safehouses", {}) or {}
        row = sh.get(loc) if isinstance(sh, dict) and loc else None
        if isinstance(row, dict):
            sh_status = str(row.get("status", "none") or "none")
            sh_sec = int(row.get("security_level", 0) or 0)
            sh_delin = int(row.get("delinquent_days", 0) or 0)
    except Exception as e:
        log_swallowed_exception('main.py:408', e)
        _record_soft_error(state, "main.snapshot_metrics.safehouse", e)
    # Disguise status.
    d = player.get("disguise", {}) or {}
    dis_active = bool(d.get("active", False)) if isinstance(d, dict) else False
    dis_persona = str(d.get("persona", "") or "") if isinstance(d, dict) else ""
    # Skill XP snapshot for deltas.
    skills = state.get("skills", {}) or {}
    skill_xp: dict[str, int] = {}
    if isinstance(skills, dict):
        for k in ("hacking", "social", "combat", "stealth", "evasion"):
            row = skills.get(k)
            if isinstance(row, dict):
                try:
                    skill_xp[k] = int(row.get("xp", 0) or 0)
                except Exception as _omni_sw_423:
                    log_swallowed_exception('main.py:423', _omni_sw_423)
                    skill_xp[k] = 0
    return {
        "day": int((state.get("meta", {}) or {}).get("day", 1) or 1),
        "time_min": int((state.get("meta", {}) or {}).get("time_min", 0) or 0),
        "cash": int(eco.get("cash", 0) or 0),
        "bank": int(eco.get("bank", 0) or 0),
        "debt": int(eco.get("debt", 0) or 0),
        "trace": int(tr.get("trace_pct", 0) or 0),
        "att_police": str(statuses.get("police", "-")),
        "att_corporate": str(statuses.get("corporate", "-")),
        "att_black_market": str(statuses.get("black_market", "-")),
        "queued_events": len(pe) if isinstance(pe, list) else 0,
        "queued_ripples": len(ar) if isinstance(ar, list) else 0,
        "world_notes_len": len(notes) if isinstance(notes, list) else 0,
        "heat_sum": int(heat_sum),
        "weather_kind": weather_kind,
        "safehouse_status": sh_status,
        "safehouse_sec": int(sh_sec),
        "safehouse_delin": int(sh_delin),
        "disguise_active": dis_active,
        "disguise_persona": dis_persona,
        "skill_xp": skill_xp,
    }


def _compute_diff(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for k in ("cash", "bank", "debt", "trace"):
        try:
            out[k] = int(after.get(k, 0) or 0) - int(before.get(k, 0) or 0)
        except Exception as _omni_sw_454:
            log_swallowed_exception('main.py:454', _omni_sw_454)
            out[k] = 0
    # Turn audit: notes added this turn.
    try:
        out["notes_added_count"] = int(after.get("world_notes_len", 0) or 0) - int(before.get("world_notes_len", 0) or 0)
    except Exception as _omni_sw_459:
        log_swallowed_exception('main.py:459', _omni_sw_459)
        out["notes_added_count"] = 0
    # Heat delta (aggregate; not perfect but high-signal).
    try:
        out["heat_sum"] = int(after.get("heat_sum", 0) or 0) - int(before.get("heat_sum", 0) or 0)
    except Exception as _omni_sw_464:
        log_swallowed_exception('main.py:464', _omni_sw_464)
        out["heat_sum"] = 0
    # Skill XP deltas per domain.
    sx_before = before.get("skill_xp") if isinstance(before.get("skill_xp"), dict) else {}
    sx_after = after.get("skill_xp") if isinstance(after.get("skill_xp"), dict) else {}
    xp_d: dict[str, int] = {}
    if isinstance(sx_before, dict) and isinstance(sx_after, dict):
        for k in ("hacking", "social", "combat", "stealth", "evasion"):
            try:
                xp_d[k] = int(sx_after.get(k, 0) or 0) - int(sx_before.get(k, 0) or 0)
            except Exception as _omni_sw_474:
                log_swallowed_exception('main.py:474', _omni_sw_474)
                xp_d[k] = 0
    out["xp_delta"] = xp_d
    for fk in ("att_police", "att_corporate", "att_black_market"):
        if before.get(fk) != after.get(fk):
            out[fk] = {"from": before.get(fk), "to": after.get(fk)}
    # Always include queued counts (not deltas) for UI "What Changed".
    out["queued_events"] = int(after.get("queued_events", 0) or 0)
    out["queued_ripples"] = int(after.get("queued_ripples", 0) or 0)
    # Always include effect/status snapshots (not deltas) for UI.
    out["effects"] = {
        "weather": after.get("weather_kind", "-"),
        "safehouse": {
            "status": after.get("safehouse_status", "none"),
            "sec": after.get("safehouse_sec", 0),
            "delin": after.get("safehouse_delin", 0),
        },
        "disguise": {"active": bool(after.get("disguise_active", False)), "persona": after.get("disguise_persona", "")},
    }
    # Time delta (minutes) across day rollover.
    try:
        bday = int(before.get("day", 1) or 1)
        aday = int(after.get("day", 1) or 1)
        bt = int(before.get("time_min", 0) or 0)
        at = int(after.get("time_min", 0) or 0)
        out["time_elapsed_min"] = (aday - bday) * 1440 + (at - bt)
    except Exception as _omni_sw_500:
        log_swallowed_exception('main.py:500', _omni_sw_500)
        out["time_elapsed_min"] = 0
    return out


def _scene_blocks_command(state: dict[str, Any], up_cmd: str) -> bool:
    """Return True if an active scene should block this command."""
    try:
        flags = state.get("flags", {}) or {}
        if not (isinstance(flags, dict) and bool(flags.get("scenes_enabled", True))):
            return False
        if not isinstance(state.get("active_scene"), dict):
            return False
        sc = state.get("active_scene") or {}
        stype = str((sc.get("scene_type", "") if isinstance(sc, dict) else "") or "").strip().lower()
        if up_cmd == "SCENE" or up_cmd.startswith("SCENE "):
            return False
        if up_cmd in ("HELP", "QUIT", "EXIT"):
            return False
        if up_cmd == "EAT" or up_cmd.startswith("EAT "):
            # Survival exception: allow only on explicitly safe scene types.
            return stype not in {"drop_pickup"}
        return True
    except Exception as _omni_sw_523:
        log_swallowed_exception('main.py:523', _omni_sw_523)
        return False


def _special_turn_profile(cmd: str) -> dict[str, Any]:
    up = str(cmd or "").strip().upper()
    if not up:
        return {"consume": False, "action_type": "instant", "domain": "other"}

    # Scene info commands are utility; scene actions consume turn.
    if up == "SCENE" or up == "SCENE OPTIONS":
        return {"consume": False, "action_type": "instant", "domain": "other"}
    if up.startswith("SCENE "):
        return {"consume": True, "action_type": "scene", "domain": "other"}

    # Utility/info/session commands (non-turn).
    non_turn_exact = {
        "UI FULL",
        "UI COMPACT",
        "STATUS",
        "INFO",
        "MARKET",
        "DISTRICTS",
        "DISTRICT",
        "MYCAR",
        "MYVEHICLE",
        "VEHICLES",
        "WHEREAMI",
        "MAP",
        "JUDICIAL",
        "JUDICIAL STATUS",
        "HEAT",
        "UNDO",
        "MODE",
        "SAVE STATE",
        "WORLD_BRIEF",
        "LANG",
        "NARRATION",
        "FACTION_REPORT",
        "FACTION_REPORT FULL",
    }
    if up in non_turn_exact:
        return {"consume": False, "action_type": "instant", "domain": "other"}
    if up.startswith("OFFERS"):
        return {"consume": False, "action_type": "instant", "domain": "other"}
    if up.startswith("SHOP"):
        return {"consume": False, "action_type": "instant", "domain": "other"}
    if up.startswith("PRICE"):
        return {"consume": False, "action_type": "instant", "domain": "other"}
    if up.startswith("BANK") and " " not in up:
        return {"consume": False, "action_type": "instant", "domain": "other"}

    # Mutating or time-consuming special commands.
    if up.startswith("HACK"):
        return {"consume": True, "action_type": "instant", "domain": "hacking"}
    if up == "PHONE" or up.startswith("PHONE HELP") or up == "SMARTPHONE" or up.startswith("SMARTPHONE HELP"):
        return {"consume": False, "action_type": "instant", "domain": "other"}
    if up.startswith("PHONE STATUS") or up.startswith("SMARTPHONE STATUS"):
        return {"consume": False, "action_type": "instant", "domain": "other"}
    if up.startswith("PHONE ") or up.startswith("SMARTPHONE "):
        return {"consume": True, "action_type": "instant", "domain": "other"}
    if up.startswith("CAREER PROMOTE"):
        return {"consume": True, "action_type": "instant", "domain": "other"}
    if up.startswith("WORK"):
        return {"consume": True, "action_type": "work", "domain": "other"}
    if up.startswith("DRIVE") or up.startswith("TRAVELTO"):
        return {"consume": True, "action_type": "travel", "domain": "evasion"}
    if up.startswith("EAT"):
        return {"consume": True, "action_type": "instant", "domain": "other"}
    if up.startswith("BUY") or up.startswith("SELL"):
        return {"consume": True, "action_type": "instant", "domain": "other"}
    if up.startswith("BUY_DARK") or up.startswith("BM_BUY"):
        return {"consume": True, "action_type": "instant", "domain": "other"}
    if up.startswith("STAY"):
        return {"consume": True, "action_type": "rest", "domain": "other"}
    if up.startswith("BUYVEHICLE") or up.startswith("SELLVEHICLE") or up.startswith("REFUEL") or up.startswith("REPAIR") or up.startswith("STEALVEHICLE") or up.startswith("USEVEHICLE"):
        return {"consume": True, "action_type": "instant", "domain": "other"}

    return {"consume": False, "action_type": "instant", "domain": "other"}


def _finalize_special_turn(state: dict[str, Any], cmd: str, metrics_before: dict[str, Any]) -> None:
    metrics_after = _snapshot_metrics(state)
    diff = _compute_diff(metrics_before, metrics_after)
    prof = _special_turn_profile(cmd)
    meta = state.setdefault("meta", {})
    meta["last_turn_diff"] = diff
    meta["last_turn_audit"] = {
        "turn": int(meta.get("turn", 0) or 0),
        "action_type": str(prof.get("action_type", "instant") or "instant"),
        "domain": str(prof.get("domain", "other") or "other"),
        "special_command": True,
        "command": str(cmd or ""),
        "diff": diff,
        "time_elapsed_min": int(diff.get("time_elapsed_min", 0) or 0),
    }
    meta["turn"] = int(meta.get("turn", 0) or 0) + 1
    backup_state()
    save_state(state)


def handle_special(state: dict[str, Any], cmd: str) -> bool:
    up = cmd.upper()
    def _ui_err(kind: str, msg: str) -> None:
        k = str(kind or "ERROR").strip().upper()
        if k in ("ACCESS DENIED", "DENIED"):
            console.print(f"[bold yellow][!][/bold yellow] ACCESS DENIED: {msg}")
        else:
            console.print(f"[bold red][!][/bold red] ERROR: {msg}")

    # Refactor batch: command dispatch modules (behavior-preserving extraction).
    try:
        if handle_faction_report(state, cmd):
            return True
        if handle_property(state, cmd):
            return True
        if handle_smartphone(state, cmd, run_pipeline=run_pipeline):
            return True
        if handle_career(state, cmd):
            return True
        if handle_misc(state, cmd, fmt_clock=_fmt_clock):
            return True
        if handle_underworld(state, cmd, run_pipeline=run_pipeline, ui_err=_ui_err):
            return True
        if handle_economy(state, cmd, run_pipeline=run_pipeline):
            return True
        if handle_scene_commands(state, cmd, run_pipeline=run_pipeline, scene_blocks_command=_scene_blocks_command):
            return True
        if handle_mobility(state, cmd, console=console, run_pipeline=run_pipeline):
            return True
        if handle_commerce(
            state,
            cmd,
            console=console,
            table_cls=Table,
            list_shop_quotes=list_shop_quotes,
            buy_item=buy_item,
            sell_item=sell_item,
            sell_item_all=sell_item_all,
            sell_item_n=sell_item_n,
            quote_item=quote_item,
            get_capacity_status=get_capacity_status,
            run_pipeline=run_pipeline,
        ):
            return True
        if handle_session(
            state,
            cmd,
            console=console,
            previous_path=PREVIOUS,
            load_state=load_state,
            get_narration_lang=get_narration_lang,
            stream_response=stream_response,
            build_system_prompt=build_system_prompt,
            stream_render=stream_render,
        ):
            return True
        if handle_social_intel(state, cmd, console=console, table_cls=Table):
            return True
    except Exception as _omni_sw_695:
        log_swallowed_exception('main.py:710', _omni_sw_695)

    if up == "UI FULL":
        state.setdefault("meta", {})["monitor_mode"] = "full"
        console.print("[green]Monitor: FULL (lebar).[/green]")
        return True
    if up == "UI COMPACT":
        state.setdefault("meta", {})["monitor_mode"] = "compact"
        console.print("[green]Monitor: COMPACT (ringkas).[/green]")
        return True
    if up in ("STATUS", "INFO"):
        meta = state.get("meta", {}) or {}
        tr = state.get("trace", {}) or {}
        eco = state.get("economy", {}) or {}
        try:
            gigs_done = int(meta.get("daily_gigs_done", 0) or 0)
        except Exception as _omni_sw_712:
            log_swallowed_exception('main.py:712', _omni_sw_712)
            gigs_done = 0
        try:
            hacks_attempted = int(meta.get("daily_hacks_attempted", 0) or 0)
        except Exception as _omni_sw_716:
            log_swallowed_exception('main.py:716', _omni_sw_716)
            hacks_attempted = 0
        penalty = max(0, int(hacks_attempted) * 10)
        t = Table(title="STATUS", show_header=False)
        t.add_column("k", style="bold cyan", no_wrap=True)
        t.add_column("v")
        t.add_row("Location", str((state.get("player", {}) or {}).get("location", "-") or "-"))
        t.add_row("Clock", f"Day {int(meta.get('day', 1) or 1)} {_fmt_clock(int(meta.get('time_min', 0) or 0))}")
        t.add_row("Trace", f"{int(tr.get('trace_pct', 0) or 0)}%")
        t.add_row("Cash/Bank", f"${int(eco.get('cash', 0) or 0)} / ${int(eco.get('bank', 0) or 0)}")
        t.add_row("Daily Gigs", f"{max(0, gigs_done)}/2")
        t.add_row("Neural Fatigue", f"{penalty}% fail penalty")
        console.print(t)
        return True
    if up in ("BLACKMARKET", "DARKNET") or up == "MARKET BLACK" or up == "MARKET BM":
        try:
            if not black_market_accessible(state):
                _ui_err("ACCESS DENIED", "CONNECTION REFUSED: Darknet node is offline.")
                return True
            inv = generate_black_market_inventory(state)
            items = inv.get("items", [])
            if not isinstance(items, list) or not items:
                console.print(format_data_table("BLACK MARKET", ["item_id", "name", "price"], [], theme="magenta"))
                console.print("[dim]- (no stock)[/dim]")
                return True
            rows: list[list[str]] = []
            for it in items[:8]:
                if not isinstance(it, dict):
                    continue
                rows.append([str(it.get("id", "?")), str(it.get("name", it.get("id", "-"))), "$" + str(it.get("price", "?"))])
            console.print(format_data_table("BLACK MARKET", ["item_id", "name", "price"], rows, theme="magenta"))
            console.print("[dim]Use: BUY_DARK <item_id>[/dim]")
        except Exception as _omni_sw_751:
            log_swallowed_exception('main.py:751', _omni_sw_751)
            _ui_err("ERROR", "BLACKMARKET error.")
        return True
    if up.startswith("BUY_DARK ") or up.startswith("BM_BUY "):
        parts = cmd.split(maxsplit=1)
        iid = parts[1].strip() if len(parts) >= 2 else ""
        if not iid:
            _ui_err("ERROR", "Usage: BUY_DARK <item_id>.")
            return True
        try:
            r = buy_black_market_item(state, iid)
            if not bool(r.get("ok")):
                if r.get("reason") == "not_enough_cash":
                    _ui_err("ERROR", "Not enough cash.")
                elif r.get("reason") == "connection_refused":
                    _ui_err("ACCESS DENIED", "Darknet node offline.")
                elif r.get("reason") == "not_in_stock":
                    _ui_err("ERROR", "Item not in stock today.")
                else:
                    _ui_err("ERROR", f"BUY_DARK failed: {r.get('reason','error')}")
                return True
            console.print(f"[green]BUY_DARK OK[/green] {r.get('item_id')} price={r.get('price')}")
        except Exception as _omni_sw_775:
            log_swallowed_exception('main.py:775', _omni_sw_775)
            _ui_err("ERROR", "BUY_DARK error.")
        return True
    if up in ("GIGS", "JOBS"):
        try:
            gigs = generate_gigs(state)
            if not gigs:
                console.print(format_data_table("GIGS", ["id", "title", "skill", "diff", "time_m", "payout"], [], theme="cyan"))
                console.print("[dim]- (none)[/dim]")
                return True
            rows: list[list[str]] = []
            for g in gigs[:6]:
                if not isinstance(g, dict):
                    continue
                rows.append(
                    [
                        str(g.get("id", "?")),
                        str(g.get("title", "-")),
                        str(g.get("req_skill", "-")),
                        str(g.get("difficulty", "-")),
                        str(g.get("time_cost_mins", "-")),
                        "$" + str(g.get("payout_cash", "-")),
                    ]
                )
            console.print(format_data_table("GIGS", ["id", "title", "skill", "diff", "time_m", "payout"], rows, theme="cyan"))
            console.print("[dim]Use: WORK <gig_id>[/dim]")
        except Exception as _omni_sw_804:
            log_swallowed_exception('main.py:804', _omni_sw_804)
            _ui_err("ERROR", "GIGS error.")
        return True
    if up.startswith("HACK "):
        parts = cmd.split(maxsplit=1)
        tgt = parts[1].strip().lower() if len(parts) >= 2 else ""
        if not tgt:
            _ui_err("ERROR", "Usage: HACK <atm|corp_server|police_archive>.")
            return True
        try:
            r = execute_hack(state, tgt)
            if not bool(r.get("ok")):
                _ui_err("ERROR", f"HACK failed: {r.get('reason','error')}")
                return True
            # Always advance time even if detected (attempt took time).
            mins = 60 if tgt in ("corp_server", "police_archive") else 30
            try:
                run_pipeline(
                    state,
                    {
                        "action_type": "instant",
                        "domain": "hacking",
                        "normalized_input": f"hack {tgt}",
                        "instant_minutes": mins,
                        "stakes": "medium",
                    },
                )
            except Exception as _omni_sw_833:
                log_swallowed_exception('main.py:833', _omni_sw_833)
            if bool(r.get("success")):
                console.print("[green]HACK success[/green]")
            else:
                console.print("[yellow]HACK detected[/yellow]")
        except Exception as _omni_sw_839:
            log_swallowed_exception('main.py:839', _omni_sw_839)
            _ui_err("ERROR", "HACK error.")
        return True
    if up.startswith("WORK "):
        parts = cmd.split(maxsplit=1)
        gid = parts[1].strip() if len(parts) >= 2 else ""
        if not gid:
            _ui_err("ERROR", "Usage: WORK <gig_id>.")
            return True
        try:
            r = execute_gig(state, gid)
            if not bool(r.get("ok")):
                if str(r.get("reason", "")) == "daily_gig_limit_reached":
                    _ui_err("ERROR", "You are physically and mentally exhausted. Get some sleep before taking more gigs.")
                else:
                    _ui_err("ERROR", f"WORK failed: {r.get('reason','error')}")
                return True
            g = r.get("gig") if isinstance(r.get("gig"), dict) else {}
            tmin = int(r.get("time_cost_mins", 120) or 120)
            payout = int(r.get("payout_cash", 0) or 0)
            succ = bool(r.get("success"))
            trace_delta = int(r.get("trace_delta", 0) or 0)
            try:
                run_pipeline(
                    state,
                    {
                        "action_type": "instant",
                        "domain": str((g or {}).get("req_skill", "other") or "other"),
                        "normalized_input": f"work {gid}",
                        "instant_minutes": max(1, min(720, tmin)),
                        "stakes": "low",
                    },
                )
            except Exception as _omni_sw_874:
                log_swallowed_exception('main.py:874', _omni_sw_874)
            title = str((g or {}).get("title", gid) or gid)
            if succ:
                eco = state.setdefault("economy", {})
                try:
                    cash0 = int(eco.get("cash", 0) or 0)
                except Exception as _omni_sw_881:
                    log_swallowed_exception('main.py:881', _omni_sw_881)
                    cash0 = 0
                eco["cash"] = int(cash0 + payout)
                state.setdefault("world_notes", []).append(f"[Economy] Completed gig '{title}' and earned ${payout}.")
                console.print(f"[green]WORK success[/green] +${payout} ({tmin}m)")
            else:
                if trace_delta > 0:
                    tr = state.setdefault("trace", {})
                    try:
                        tp = int(tr.get("trace_pct", 0) or 0)
                    except Exception as _omni_sw_891:
                        log_swallowed_exception('main.py:891', _omni_sw_891)
                        tp = 0
                    tr["trace_pct"] = max(0, min(100, tp + int(trace_delta)))
                    state.setdefault("world_notes", []).append(
                        f"[Economy] Failed gig '{title}'. The botched job left a digital trail, increasing your Trace."
                    )
                else:
                    state.setdefault("world_notes", []).append(f"[Economy] Failed gig '{title}', wasting time with no payout.")
                console.print(f"[yellow]WORK failed[/yellow] (time spent {tmin}m)")
        except Exception as _omni_sw_900:
            log_swallowed_exception('main.py:900', _omni_sw_900)
            _ui_err("ERROR", "WORK error.")
        return True
    # Single blocking gatekeeper for scenes (ONE place).
    if _scene_blocks_command(state, up):
        if up == "EAT" or up.startswith("EAT "):
            console.print("[yellow]Situasi tidak memungkinkan untuk makan sekarang.[/yellow]")
            return True
        console.print("[yellow]Scene active. Use: SCENE | SCENE OPTIONS | SCENE <action>[/yellow]")
        return True

    if up == "SCENE" or up.startswith("SCENE "):
        parts = cmd.split(maxsplit=2)
        sub = parts[1].strip().lower() if len(parts) >= 2 else "status"
        sc = state.get("active_scene")
        if not isinstance(sc, dict) or not sc:
            console.print("[yellow]SCENE: (none active)[/yellow]")
            return True
        if sub in ("status", "info"):
            console.print("[bold]SCENE[/bold]")
            console.print(f"- type={sc.get('scene_type','-')} phase={sc.get('phase','-')}")
            exp = sc.get("expires_at") if isinstance(sc.get("expires_at"), dict) else {}
            if isinstance(exp, dict) and exp:
                console.print(f"- deadline: day{exp.get('day','?')} t{exp.get('time_min','?')}")
            return True
        if sub in ("options", "opts"):
            opts = sc.get("next_options") or []
            if not isinstance(opts, list) or not opts:
                console.print("[yellow]SCENE OPTIONS: (none)[/yellow]")
                return True
            console.print("[bold]SCENE OPTIONS[/bold]")
            for o in opts[:12]:
                if isinstance(o, str):
                    console.print(f"- {o}")
            return True

        # Action (approach/take/abort/wait)
        act = sub

        action_ctx: dict[str, Any] = {
            "action_type": "instant",
            "domain": "other",
            "normalized_input": f"scene {act}",
            "instant_minutes": 2,
            "stakes": "low",
            "scene_action": act,
        }
        # Optional argument (e.g. SCENE BRIBE 500)
        if len(parts) >= 3 and isinstance(parts[2], str) and parts[2].strip():
            action_ctx["scene_arg"] = parts[2].strip()
            if act in ("bribe",):
                try:
                    action_ctx["bribe_amount"] = int(parts[2].strip())
                except Exception as _omni_sw_954:
                    log_swallowed_exception('main.py:954', _omni_sw_954)
                    action_ctx["bribe_amount"] = 0
        res = advance_scene(state, action_ctx)
        if not bool(res.get("ok")):
            console.print(f"[red]SCENE failed[/red] {res.get('reason','error')}")
            return True
        # WAIT consumes 5 minutes by spec.
        if act in ("wait",) and bool(res.get("ok")):
            action_ctx["instant_minutes"] = 5
        try:
            run_pipeline(state, action_ctx)
        except Exception as e:
            log_swallowed_exception('main.py:965', e)
            _record_soft_error(state, "main.scene.run_pipeline", e)
        if bool(res.get("ended")):
            console.print("[green]SCENE resolved[/green]")
        else:
            console.print(f"[green]SCENE OK[/green] phase={res.get('phase_after', '-')}")
        # Show any engine messages for clarity.
        for m in (res.get("messages") or [])[:4]:
            if isinstance(m, str) and m.strip():
                console.print(f"[dim]- {m}[/dim]")
        return True

    if up == "HELP":
        console.print("[bold cyan]Mulai cepat[/bold cyan]")
        console.print(
            "[dim]Ketik bebas bahasa alami (game akan parse) atau perintah keras: "
            "`TALK <nama>` ngobrol, `INFORMANTS` jaringan informan, `WORLD_BRIEF` ringkasan dunia, "
            "`DISTRICTS` daftar distrik kota, `UI FULL` stat lebar. "
            "Nama seperti Operator_Link = ID kontak di engine, bukan error.[/dim]"
        )
        console.print("")
        console.print("[bold]HELP — Commands[/bold]")
        console.print("[dim]Core[/dim]")
        console.print("- HELP")
        console.print("- UI COMPACT | UI FULL (HUD ringkas vs lebar; default env OMNI_MONITOR_MODE=compact)")
        console.print("- STATUS | INFO  (ringkasan kondisi harian: gigs cap + neural fatigue)")
        console.print("- SCENE | SCENE OPTIONS | SCENE <action>  (contextual; see SCENE OPTIONS)")
        console.print("- QUEST")
        console.print("- ATLAS [country]")
        console.print("- COUNTRIES")
        console.print("- CITIES [country]")
        console.print("- LANGS")
        console.print("- LEARN_LANG <code> [class|book|immersion]")
        console.print("- LANG id|en")
        console.print("- NARRATION compact|cinematic")
        console.print("- MODE NORMAL|IRONMAN")
        console.print("- UNDO  (Normal only)")
        console.print("- SAVE STATE")
        console.print("- SHOWER | HYGIENE | MANDI  (reset hygiene clock, ~15m)")
        console.print("- RELOAD  (fill active firearm mag from reserve ammo)")
        console.print("- WORLD_BRIEF")
        console.print("- INTENT_DEBUG")
        console.print("")
        console.print("[dim]Intel & tools[/dim]")
        console.print("- NPC <name>")
        console.print("- WHO")
        console.print("- HEAT")
        console.print("- OFFERS [role]   (contoh: OFFERS fixer)")
        console.print("- MARKET            (legal market snapshot)")
        console.print("- BLACKMARKET       (night-only underground market)")
        console.print("- MARKET BM         (alias for BLACKMARKET)")
        console.print("- BUY_DARK <item_id>  (buy from Black Market; cash only)")
        console.print("- SAFEHOUSE stash putammo <ammo_id> <rounds> | stash takeammo <ammo_id> <rounds>")
        console.print("- SAFEHOUSE raid comply|hide|bribe <amt>|flee|negotiate|show_permit  (respon saat ada pending raid)")
        console.print("- SAFEHOUSE burn  (abandon safehouse, clear stash)")
        console.print("- BANK status|deposit <n>|withdraw <n>")
        console.print("- STAY status|hotel|boarding|suite <nights>")
        console.print("- GIGS | JOBS       (list freelance contracts)")
        console.print("- WORK <gig_id>     (spend hours to complete a gig)")
        console.print("- CAREER | CAREER PROMOTE [track] | CAREER TRACK <id> | CAREER BREAK ON|OFF")
        console.print("- PROPERTY (assets) | PROPERTY PRICES <city> | PROPERTY BUY APARTMENT|HOUSE|BUSINESS <city>")
        console.print("- PROPERTY RENT APARTMENT <city> | PROPERTY SELL <asset_id> | PROPERTY BUY VEHICLE <vehicle_id>")
        console.print("[dim]  boarding = budget/shared room (Indonesian: kost); aliases: kos kost dorm hostel guesthouse[/dim]")
        console.print("- NPCSIM_STATS")
        console.print("- WHEREAMI")
        console.print("")
        console.print("[dim]Districts & Intra-city[/dim]")
        console.print("- DISTRICTS        (list districts in current city)")
        console.print("- TRAVELTO <id>    (travel to a district within the city)")
        console.print("")
        console.print("[dim]Vehicles[/dim]")
        console.print("- MYCAR            (list owned vehicles)")
        console.print("- BUYVEHICLE <type> (bicycle|motorcycle|car_standard|car_sports|car_van)")
        console.print("- SELLVEHICLE <type>")
        console.print("- USEVEHICLE <type>|OFF   (set active vehicle for TRAVEL)")
        console.print("- DRIVE <dest> [type]     (travel using vehicle; uses active if omitted)")
        console.print("- REFUEL <type> [amount]")
        console.print("- REPAIR <type> [amount]")
        console.print("- STEALVEHICLE <type>  (illegal!)")
        console.print("")
        console.print("[dim]Aliases[/dim]")
        console.print("- T <dest>  => travel <dest>")
        console.print("- H <text>  => hack <text>")
        console.print("- S <text>  => talk <text>")
        return True
    if up in ("SHOWER", "HYGIENE", "MANDI"):
        try:
            ctx = {
                "action_type": "instant",
                "domain": "social",
                "social_mode": "non_conflict",
                "normalized_input": "shower",
                "instant_minutes": 15,
                "stakes": "low",
            }
            run_pipeline(state, ctx)
            console.print("[green]Engine: mandi/selesai — jam hygiene direset (~15m).[/green]")
        except Exception as _omni_sw_1062:
            log_swallowed_exception('main.py:1062', _omni_sw_1062)
            console.print("[red]SHOWER error.[/red]")
        return True
    if up == "RELOAD":
        try:
            r = try_reload(state)
            if r.get("ok"):
                console.print(
                    f"[green]Reload +{r.get('loaded')} (mag {r.get('mag_after')} / reserve {r.get('reserve_after')}).[/green]"
                )
            else:
                console.print(f"[yellow]Reload tidak jalan: {r.get('reason')}[/yellow]")
            ctx = {
                "action_type": "instant",
                "domain": "combat",
                "social_mode": "conflict",
                "normalized_input": "reload",
                "instant_minutes": 2,
                "stakes": "low",
            }
            run_pipeline(state, ctx)
        except Exception as _omni_sw_1085:
            log_swallowed_exception('main.py:1085', _omni_sw_1085)
            console.print("[red]RELOAD error.[/red]")
        return True
    if up == "ATLAS" or up.startswith("ATLAS "):
        parts = cmd.split(maxsplit=2)
        world = state.get("world", {}) or {}
        atlas = world.get("atlas", {}) or {}
        gp = atlas.get("geopolitics", {}) if isinstance(atlas, dict) else {}
        try:
            t = int((gp.get("tension_idx", 0) if isinstance(gp, dict) else 0) or 0)
        except Exception as _omni_sw_1095:
            log_swallowed_exception('main.py:1095', _omni_sw_1095)
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
        except Exception as e:
            log_swallowed_exception('main.py:1126', e)
            _record_soft_error(state, "main.atlas.country_profile", e)
        return True
    if up == "COUNTRIES":
        try:
            xs = list_known_countries()
            console.print("[bold]COUNTRIES[/bold]")
            console.print(f"- total={len(xs)}")
            console.print(", ".join(xs[:60]) + (" ..." if len(xs) > 60 else ""))
        except Exception as _omni_sw_1137:
            log_swallowed_exception('main.py:1137', _omni_sw_1137)
            console.print("[red]COUNTRIES error.[/red]")
        return True
    if up == "CITIES" or up.startswith("CITIES "):
        parts = cmd.split(maxsplit=2)
        want = parts[1].strip() if len(parts) >= 2 else ""
        try:
            if want:
                c = normalize_country_name(want)
                xs = list_known_cities(c)
                console.print("[bold]CITIES[/bold]")
                console.print(f"- country={c} cities={len(xs)}")
                seed = str((state.get("meta", {}) or {}).get("world_seed", "") or (state.get("meta", {}) or {}).get("seed_pack", "") or "")
                dc = default_city_for_country(c, seed=seed)
                if dc:
                    console.print(f"- default_city={dc}")
                if xs:
                    console.print(", ".join(xs[:80]) + (" ..." if len(xs) > 80 else ""))
                else:
                    console.print("(none mapped yet)")
            else:
                xs = list_known_cities()
                console.print("[bold]CITIES[/bold]")
                console.print(f"- total={len(xs)}")
                console.print(", ".join(xs[:80]) + (" ..." if len(xs) > 80 else ""))
        except Exception as _omni_sw_1164:
            log_swallowed_exception('main.py:1164', _omni_sw_1164)
            console.print("[red]CITIES error.[/red]")
        return True
    if up == "LANGS":
        try:
            p = state.get("player", {}) or {}
            loc = str(p.get("location", "") or "").strip().lower()
            prof = player_language_proficiency(state)
            console.print("[bold]LANGS[/bold]")
            if prof:
                # Sort by proficiency desc
                rows = sorted(list(prof.items()), key=lambda kv: int(kv[1]), reverse=True)
                console.print("- player_languages: " + ", ".join([f"{k}({v})" for k, v in rows[:12]]) + (" ..." if len(rows) > 12 else ""))
            else:
                console.print("- player_languages: (none)")
            if loc:
                lc = communication_quality(state, {"domain": "social", "normalized_input": "langs"})
                console.print(f"- local_lang={lc.local_lang} shared={lc.shared} translator={lc.translator_level} quality={lc.quality} year={lc.sim_year} epoch={lc.tech_epoch}")
            else:
                console.print("- local_lang: (unknown)")
        except Exception as _omni_sw_1186:
            log_swallowed_exception('main.py:1186', _omni_sw_1186)
            console.print("[red]LANGS error.[/red]")
        return True
    if up == "LEARN_LANG" or up.startswith("LEARN_LANG "):
        parts = cmd.split(maxsplit=3)
        if len(parts) < 2:
            console.print("[yellow]Usage: LEARN_LANG <code> [class|book|immersion][/yellow]")
            return True
        code = parts[1].strip().lower()
        method = parts[2].strip().lower() if len(parts) >= 3 else "class"
        try:
            # Preview first (no mutation) so we can validate cash/items/region safely.
            res0 = learn_language(state, code, method=method, preview=True)
            if not bool(res0.get("ok", False)):
                console.print(f"[red]LEARN_LANG failed: {res0.get('reason','error')}[/red]")
                return True
            cost = int(res0.get("cash_cost", 0) or 0)
            mins = int(res0.get("minutes", 0) or 0)

            # Pay cost (before applying learning).
            eco = state.setdefault("economy", {})
            cash = int(eco.get("cash", 0) or 0)
            if cash < cost:
                console.print("[red]Not enough cash.[/red]")
                return True
            eco["cash"] = cash - cost

            # Apply learning after payment.
            res = learn_language(state, code, method=method, preview=False)

            # Advance time via pipeline (so world continues).
            try:
                ctx = {
                    "action_type": "instant",
                    "domain": "social",
                    "social_mode": "non_conflict",
                    "normalized_input": f"learn_lang {code} {method}",
                    "instant_minutes": mins,
                    "stakes": "low",
                }
                run_pipeline(state, ctx)
            except Exception as _omni_sw_1229:
                log_swallowed_exception('main.py:1229', _omni_sw_1229)
                # Fallback: no pipeline, but still move time.
                update_timers(state, {"action_type": "instant", "instant_minutes": mins})

            console.print(f"[green]LEARN_LANG {code} ({method}) +{res.get('delta',0)} → {res.get('new_prof',0)} (cost {cost}, time {mins}m)[/green]")
        except Exception as _omni_sw_1236:
            log_swallowed_exception('main.py:1236', _omni_sw_1236)
            console.print("[red]LEARN_LANG error.[/red]")
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
                deactivate_disguise(state, reason="manual")
            except Exception as _omni_sw_1254:
                log_swallowed_exception('main.py:1254', _omni_sw_1254)
            console.print("[green]DISGUISE off.[/green]")
            return True
        try:
            ok = activate_disguise(state, arg)
            if not ok:
                console.print("[red]DISGUISE gagal: cash tidak cukup (butuh ~40).[/red]")
            else:
                console.print(f"[green]DISGUISE aktif: {arg}[/green]")
        except Exception as _omni_sw_1266:
            log_swallowed_exception('main.py:1266', _omni_sw_1266)
            console.print("[red]DISGUISE error.[/red]")
        return True
    if up == "SAFEHOUSE" or up.startswith("SAFEHOUSE "):
        parts = cmd.split(maxsplit=5)
        sub = parts[1].strip().lower() if len(parts) >= 2 else "status"
        try:
            row = ensure_safehouse_here(state)
            if sub in ("status", "info"):
                console.print("[bold]SAFEHOUSE[/bold]")
                console.print(f"- loc={str((state.get('player',{}) or {}).get('location','-'))}")
                console.print(f"- status={row.get('status','none')} rent_per_day={row.get('rent_per_day',0)} security=L{row.get('security_level',1)} delinquent={row.get('delinquent_days',0)}")
                if row.get("last_raid_day"):
                    console.print(f"- raid: last_day={row.get('last_raid_day')} count={row.get('raid_count',0)} cooldown_until_day={row.get('raid_cooldown_until_day',0)}")
                st = row.get("stash") or []
                if isinstance(st, list) and st:
                    console.print(f"- stash({len(st)}): " + ", ".join([str(x) for x in st[:10]]) + (" ..." if len(st) > 10 else ""))
                sa = row.get("stash_ammo") or {}
                if isinstance(sa, dict) and sa:
                    items = [f"{k}={int(v or 0)}" for k, v in list(sa.items())[:8] if str(k).strip()]
                    if items:
                        console.print("- stash_ammo: " + ", ".join(items) + (" ..." if len(sa) > 8 else ""))
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
                # Ammo stash ops: SAFEHOUSE stash putammo <ammo_id> <rounds> | takeammo <ammo_id> <rounds>
                if act in ("putammo", "storeammo", "ammo_put") and len(parts) >= 5:
                    aid = item
                    try:
                        n = int(parts[4].strip())
                    except Exception as _omni_sw_1311:
                        log_swallowed_exception('main.py:1311', _omni_sw_1311)
                        n = 0
                    try:
                        r = stash_put_ammo(state, aid, rounds=n)
                        if r.get("ok"):
                            console.print(f"[green]STASH ammo put {aid} -{r.get('rounds')}[/green]")
                        else:
                            console.print(f"[red]STASH ammo put gagal: {r.get('reason','error')}[/red]")
                    except Exception as _omni_sw_1321:
                        log_swallowed_exception('main.py:1321', _omni_sw_1321)
                        console.print("[red]STASH ammo put error.[/red]")
                    return True
                if act in ("takeammo", "getammo", "ammo_take") and len(parts) >= 5:
                    aid = item
                    try:
                        n = int(parts[4].strip())
                    except Exception as _omni_sw_1328:
                        log_swallowed_exception('main.py:1328', _omni_sw_1328)
                        n = 0
                    try:
                        r = stash_take_ammo(state, aid, rounds=n)
                        if r.get("ok"):
                            console.print(f"[green]STASH ammo take {aid} +{r.get('rounds')}[/green]")
                        else:
                            console.print(f"[red]STASH ammo take gagal: {r.get('reason','error')}[/red]")
                    except Exception as _omni_sw_1338:
                        log_swallowed_exception('main.py:1338', _omni_sw_1338)
                        console.print("[red]STASH ammo take error.[/red]")
                    return True
                if act in ("put", "store"):
                    try:
                        r = stash_put_from_bag(state, item)
                        if r.get("ok"):
                            console.print(f"[green]STASH put {item}[/green]")
                        else:
                            console.print(f"[red]STASH put gagal: {r.get('reason','error')}[/red]")
                    except Exception as _omni_sw_1350:
                        log_swallowed_exception('main.py:1350', _omni_sw_1350)
                        console.print("[red]STASH put error.[/red]")
                    return True
                if act in ("take", "get"):
                    try:
                        r = stash_take_to_bag(state, item)
                        if r.get("ok"):
                            console.print(f"[green]STASH take {item}[/green]")
                        else:
                            console.print(f"[red]STASH take gagal: {r.get('reason','error')}[/red]")
                    except Exception as _omni_sw_1362:
                        log_swallowed_exception('main.py:1362', _omni_sw_1362)
                        console.print("[red]STASH take error.[/red]")
                    return True
            if sub == "raid" and len(parts) >= 3:
                act = parts[2].strip().lower()
                amt = 0
                if act in ("bribe", "pay", "suap") and len(parts) >= 4:
                    try:
                        amt = int(parts[3].strip())
                    except Exception as _omni_sw_1371:
                        log_swallowed_exception('main.py:1371', _omni_sw_1371)
                        amt = 0
                try:
                    r = set_pending_raid_response(state, action=act, bribe_amount=amt)
                    if r.get("ok"):
                        console.print(f"[green]SAFEHOUSE RAID set: {r.get('action')} bribe={r.get('bribe_amount',0)}[/green]")
                        # Spend some time reacting.
                        mins = 3
                        if str(r.get("action")) == "hide":
                            mins = 6
                        elif str(r.get("action")) == "flee":
                            mins = 5
                        elif str(r.get("action")) == "bribe":
                            mins = 4
                            # Pay bribe upfront.
                            eco = state.setdefault("economy", {})
                            cash = int(eco.get("cash", 0) or 0)
                            if cash >= amt and amt > 0:
                                eco["cash"] = cash - amt
                            else:
                                console.print("[yellow]Bribe amount invalid / cash kurang; tetap dicatat sebagai attempt.[/yellow]")
                        try:
                            run_pipeline(
                                state,
                                {
                                    "action_type": "instant",
                                    "domain": "other",
                                    "normalized_input": f"safehouse raid {r.get('action')}",
                                    "instant_minutes": mins,
                                    "stakes": "medium",
                                },
                            )
                        except Exception as _omni_sw_1405:
                            log_swallowed_exception('main.py:1405', _omni_sw_1405)
                    else:
                        console.print(f"[red]SAFEHOUSE RAID gagal: {r.get('reason','error')}[/red]")
                except Exception as _omni_sw_1409:
                    log_swallowed_exception('main.py:1409', _omni_sw_1409)
                    console.print("[red]SAFEHOUSE RAID error.[/red]")
                return True
            if sub in ("burn", "abandon"):
                # Burn the current safehouse: clear stash and disable safehouse status (you lose it).
                try:
                    row["stash"] = []
                    row["status"] = "none"
                    row["rent_per_day"] = 0
                    row["delinquent_days"] = 0
                    row["raid_cooldown_until_day"] = 0
                    state.setdefault("world_notes", []).append(
                        f"[Safehouse] BURN safehouse @ {str((state.get('player',{}) or {}).get('location','-'))}"
                    )
                    console.print("[yellow]SAFEHOUSE burned: stash cleared, status set to none.[/yellow]")
                except Exception as _omni_sw_1424:
                    log_swallowed_exception('main.py:1424', _omni_sw_1424)
                    console.print("[red]SAFEHOUSE burn error.[/red]")
                return True
            console.print("[yellow]Pakai: SAFEHOUSE status|rent|buy|upgrade|stash put <id>|stash take <id>|stash putammo <ammo_id> <rounds>|stash takeammo <ammo_id> <rounds>|raid comply|hide|bribe <amt>|flee|negotiate|show_permit|burn[/yellow]")
        except Exception as _omni_sw_1428:
            log_swallowed_exception('main.py:1428', _omni_sw_1428)
            console.print("[red]SAFEHOUSE error.[/red]")
        return True
    if up == "BANK" or up.startswith("BANK "):
        parts = cmd.split(maxsplit=2)
        sub = parts[1].strip().lower() if len(parts) >= 2 else "status"
        try:
            econ = state.setdefault("economy", {})
            cash = int(econ.get("cash", 0) or 0)
            bank = int(econ.get("bank", 0) or 0)
            debt = int(econ.get("debt", 0) or 0)
            fico = int(econ.get("fico", 600) or 600)
            if sub in ("status", "info"):
                aml = bank_aml_snapshot(state)
                console.print("[bold]BANK[/bold]")
                console.print(f"- cash={cash} bank={bank} debt={debt} fico={fico}")
                console.print(f"- aml_status={aml.get('aml_status')} threshold={aml.get('aml_threshold')}")
                console.print(f"- deposits_72h_total={aml.get('deposit_window_72h_total')} over={aml.get('deposit_window_over_threshold')}")
                return True
            if sub == "deposit":
                if len(parts) < 3:
                    console.print("[yellow]Usage: BANK deposit <amount>[/yellow]")
                    return True
                try:
                    amt = int(parts[2].strip())
                except Exception as _omni_sw_1455:
                    log_swallowed_exception('main.py:1455', _omni_sw_1455)
                    console.print("[red]BANK deposit: amount tidak valid.[/red]")
                    return True
                res = bank_deposit(state, amt)
                if not bool(res.get("ok")):
                    console.print(f"[red]BANK deposit gagal: {res.get('reason','error')}[/red]")
                    return True
                try:
                    run_pipeline(
                        state,
                        {
                            "action_type": "instant",
                            "domain": "other",
                            "normalized_input": f"bank deposit {amt}",
                            "instant_minutes": 5,
                            "stakes": "low",
                            "cash_deposit": float(res.get("cash_deposit", 0) or 0),
                        },
                    )
                except Exception as _omni_sw_1474:
                    log_swallowed_exception('main.py:1474', _omni_sw_1474)
                console.print(f"[green]BANK deposit OK[/green] {amt} cash→bank (AML log updated)")
                return True
            if sub == "withdraw":
                if len(parts) < 3:
                    console.print("[yellow]Usage: BANK withdraw <amount>[/yellow]")
                    return True
                try:
                    amt = int(parts[2].strip())
                except Exception as _omni_sw_1484:
                    log_swallowed_exception('main.py:1484', _omni_sw_1484)
                    console.print("[red]BANK withdraw: amount tidak valid.[/red]")
                    return True
                res = bank_withdraw(state, amt)
                if not bool(res.get("ok")):
                    console.print(f"[red]BANK withdraw gagal: {res.get('reason','error')}[/red]")
                    return True
                try:
                    run_pipeline(
                        state,
                        {
                            "action_type": "instant",
                            "domain": "other",
                            "normalized_input": f"bank withdraw {amt}",
                            "instant_minutes": 5,
                            "stakes": "low",
                        },
                    )
                except Exception as _omni_sw_1502:
                    log_swallowed_exception('main.py:1502', _omni_sw_1502)
                console.print(f"[green]BANK withdraw OK[/green] {amt} bank→cash")
                return True
            console.print("[yellow]Pakai: BANK status|deposit <n>|withdraw <n>[/yellow]")
        except Exception as _omni_sw_1507:
            log_swallowed_exception('main.py:1507', _omni_sw_1507)
            console.print("[red]BANK error.[/red]")
        return True
    if up == "STAY" or up.startswith("STAY "):
        parts = cmd.split(maxsplit=3)
        sub = parts[1].strip().lower() if len(parts) >= 2 else "status"
        try:
            loc = str((state.get("player", {}) or {}).get("location", "") or "").strip() or "-"
            if sub in ("status", "info"):
                row = get_stay_here(state)
                console.print("[bold]STAY[/bold]")
                console.print(f"- loc={loc}")
                if row and str(row.get("kind", "none")) in ("hotel", "kos", "suite"):
                    lk = str(row.get("kind", "none"))
                    console.print(
                        f"- {stay_kind_label(lk)} — nights_left={row.get('nights_remaining',0)} rate/night={row.get('rate_per_night',0)}"
                    )
                else:
                    console.print("- (no prepaid stay — bed only / street; safehouse is separate: SAFEHOUSE)")
                for tier in ("hotel", "kos", "suite"):
                    ql = stay_kind_label(tier)
                    console.print(f"- quote {ql}: {nightly_rate(state, tier)}/night (scaled by food market)")
                console.print(f"[dim]{stay_help_aliases()}[/dim]")
                return True
            nk = normalize_stay_kind(sub)
            if nk:
                n_raw = parts[2].strip() if len(parts) >= 3 else "1"
                try:
                    nn = int(n_raw)
                except Exception as _omni_sw_1546:
                    log_swallowed_exception('main.py:1546', _omni_sw_1546)
                    nn = 1
                rr = maybe_trigger_stay_raid(state)
                if bool(rr.get("triggered")):
                    console.print("[red]STAY interrupted[/red] Authorities tracked your location. Use SCENE responses now.")
                    return True
                res = stay_checkin(state, nk, nn)
                if not bool(res.get("ok")):
                    r = str(res.get("reason", "error"))
                    if r == "not_enough_cash":
                        console.print(f"[red]STAY gagal: cash kurang (need {res.get('need','?')}, have {res.get('cash',0)}).[/red]")
                    else:
                        console.print(f"[red]STAY gagal: {r}[/red]")
                    return True
                try:
                    run_pipeline(
                        state,
                        {
                            "action_type": "instant",
                            "domain": "other",
                            "normalized_input": f"stay {nk} {nn}",
                            "instant_minutes": 15,
                            "stakes": "low",
                        },
                    )
                except Exception as _omni_sw_1571:
                    log_swallowed_exception('main.py:1571', _omni_sw_1571)
                tier_name = stay_kind_label(str(res.get("kind") or nk), short=True)
                console.print(
                    f"[green]STAY OK[/green] {tier_name} +{res.get('nights_added')}n total_nights={res.get('nights_remaining')} paid={res.get('paid')} cash={res.get('cash_after')}"
                )
                return True
            console.print("[yellow]Pakai: STAY status|hotel <n>|boarding <n>|suite <n>[/yellow]")
            console.print(f"[dim]{stay_help_aliases()}[/dim]")
        except Exception as _omni_sw_1580:
            log_swallowed_exception('main.py:1580', _omni_sw_1580)
            console.print("[red]STAY error.[/red]")
        return True
    if up == "WEATHER":
        try:
            meta = state.get("meta", {}) or {}
            day = int(meta.get("day", 1) or 1)
            loc = str((state.get("player", {}) or {}).get("location", "") or "").strip().lower()
            if not loc:
                console.print("[yellow]WEATHER: lokasi kosong.[/yellow]")
                return True
            w = ensure_weather(state, loc, day)
            console.print(f"[bold]WEATHER[/bold] {loc}: {w.get('kind','-')} (day {day})")
        except Exception as _omni_sw_1595:
            log_swallowed_exception('main.py:1595', _omni_sw_1595)
            console.print("[red]WEATHER error.[/red]")
            return True
    # DISTRICT COMMANDS
    if up == "DISTRICTS" or up == "DISTRICT":
        try:
            loc = str((state.get("player", {}) or {}).get("location", "") or "").strip()
            if not loc:
                console.print("[yellow]DISTRICTS: No current location.[/yellow]")
                return True
            
            # Show current location description
            current_desc = describe_location(state)
            console.print(f"[bold]Current:[/bold] {current_desc}")
            console.print("")
            
            # List all districts in current city
            districts = list_districts(state, loc)
            console.print("[bold]DISTRICTS in this city:[/bold]")
            for d in districts:
                is_center = " [yellow](city center)[/yellow]" if d.get("is_center") else ""
                console.print(f"- {d.get('name','?')} ({d.get('id','?')}){is_center}")
                console.print(f"  {d.get('desc','-')}")
                services = d.get("services", [])
                console.print(f"  Services: {', '.join(services) if services else 'none'}")
                console.print(f"  Crime={d.get('crime_risk',3)}/5 Police={d.get('police_presence',3)}/5")
        except Exception as _omni_sw_1623:
            log_swallowed_exception('main.py:1623', _omni_sw_1623)
            console.print("[red]DISTRICTS error.[/red]")
        return True
    # VEHICLE COMMANDS
    if up == "MYCAR" or up == "MYVEHICLE" or up == "VEHICLES":
        try:
            vehicles = list_owned_vehicles(state)
            console.print("[bold]VEHICLES[/bold]")
            if not vehicles:
                console.print("[dim]No vehicles owned. Use BUYVEHICLE to purchase.[/dim]")
                console.print("[dim]Available types: bicycle, motorcycle, car_standard, car_sports, car_van[/dim]")
                return True
            
            for v in vehicles:
                stolen = " [red](STOLEN)[/red]" if v.get("stolen") else ""
                fuel_status = f"fuel={v.get('fuel', 0)}"
                cond = v.get("condition", 100)
                cond_color = "green" if cond > 70 else ("yellow" if cond > 30 else "red")
                console.print(f"- {v.get('name','?')} {fuel_status} cond=[{cond_color}]{cond}[/{cond_color}]{stolen}")
        except Exception as _omni_sw_1644:
            log_swallowed_exception('main.py:1644', _omni_sw_1644)
            console.print("[red]MYCAR error.[/red]")
        return True
    if up == "BUYVEHICLE" or up.startswith("BUYVEHICLE "):
        try:
            parts = cmd.split(maxsplit=2)
            if len(parts) < 2:
                console.print("[yellow]Usage: BUYVEHICLE <type>[/yellow]")
                console.print("[dim]Types: bicycle, motorcycle, car_standard, car_sports, car_van[/dim]")
                return True
            
            vtype = parts[1].strip().lower()
            result = buy_vehicle(state, vtype)
            
            if not result.get("ok"):
                console.print(f"[red]BUYVEHICLE failed: {result.get('message', result.get('reason','error'))}[/red]")
                if result.get("reason") == "not_enough_cash":
                    console.print(f"[yellow]Need: {result.get('need')} | Have: {result.get('cash')}[/yellow]")
            else:
                console.print(f"[green]BUYVEHICLE OK[/green] {result.get('name')} for {result.get('price')} cash. Remaining: {result.get('cash_remaining')}")
        except Exception as _omni_sw_1666:
            log_swallowed_exception('main.py:1666', _omni_sw_1666)
            console.print("[red]BUYVEHICLE error.[/red]")
        return True
    if up == "SELLVEHICLE" or up.startswith("SELLVEHICLE "):
        try:
            parts = cmd.split(maxsplit=2)
            if len(parts) < 2:
                console.print("[yellow]Usage: SELLVEHICLE <type>[/yellow]")
                return True
            
            vtype = parts[1].strip().lower()
            result = sell_vehicle(state, vtype)
            
            if not result.get("ok"):
                console.print(f"[red]SELLVEHICLE failed: {result.get('reason','error')}[/red]")
            else:
                console.print(f"[green]SELLVEHICLE OK[/green] Sold for {result.get('price')}. Cash: {result.get('cash')}")
        except Exception as _omni_sw_1685:
            log_swallowed_exception('main.py:1685', _omni_sw_1685)
            console.print("[red]SELLVEHICLE error.[/red]")
        return True
    if up == "REFUEL" or up.startswith("REFUEL "):
        try:
            parts = cmd.split(maxsplit=3)
            if len(parts) < 2:
                console.print("[yellow]Usage: REFUEL <type> [amount][/yellow]")
                return True
            
            vtype = parts[1].strip().lower()
            amount = int(parts[2].strip()) if len(parts) >= 3 else None
            result = refuel_vehicle(state, vtype, amount)
            
            if not result.get("ok"):
                console.print(f"[red]REFUEL failed: {result.get('reason','error')}[/red]")
            else:
                console.print(f"[green]REFUEL OK[/green] +{result.get('fuel_added')} fuel. Now: {result.get('fuel_now')}. Cost: {result.get('cost')}")
        except Exception as _omni_sw_1705:
            log_swallowed_exception('main.py:1705', _omni_sw_1705)
            console.print("[red]REFUEL error.[/red]")
        return True
    if up == "REPAIR" or up.startswith("REPAIR "):
        try:
            parts = cmd.split(maxsplit=3)
            if len(parts) < 2:
                console.print("[yellow]Usage: REPAIR <type> [amount][/yellow]")
                return True
            
            vtype = parts[1].strip().lower()
            amount = int(parts[2].strip()) if len(parts) >= 3 else None
            result = repair_vehicle(state, vtype, amount)
            
            if not result.get("ok"):
                console.print(f"[red]REPAIR failed: {result.get('reason','error')}[/red]")
            else:
                console.print(f"[green]REPAIR OK[/green] +{result.get('repaired')} condition. Now: {result.get('condition_now')}%. Cost: {result.get('cost')}")
        except Exception as _omni_sw_1725:
            log_swallowed_exception('main.py:1725', _omni_sw_1725)
            console.print("[red]REPAIR error.[/red]")
        return True
    if up == "STEALVEHICLE" or up.startswith("STEALVEHICLE "):
        try:
            parts = cmd.split(maxsplit=2)
            if len(parts) < 2:
                console.print("[yellow]Usage: STEALVEHICLE <type>[/yellow]")
                console.print("[red]Warning: Illegal! May increase trace.[/red]")
                return True
            
            vtype = parts[1].strip().lower()
            console.print("[yellow]Attempting to steal...[/yellow]")
            result = steal_vehicle(state, vtype)
            
            if not result.get("ok"):
                if result.get("caught"):
                    console.print(f"[red]CAUGHT![/red] Trace +{result.get('trace_added')}. Roll: {result.get('roll')} vs Difficulty: {result.get('difficulty')}")
                else:
                    console.print(f"[red]STEALVEHICLE failed: {result.get('reason','error')}[/red]")
            else:
                console.print(f"[green]STEALVEHICLE OK[/green] Stole {result.get('name')}! Condition: {result.get('condition')}%")
        except Exception as _omni_sw_1749:
            log_swallowed_exception('main.py:1749', _omni_sw_1749)
            console.print("[red]STEALVEHICLE error.[/red]")
        return True
    if up == "USEVEHICLE" or up.startswith("USEVEHICLE "):
        try:
            parts = cmd.split(maxsplit=2)
            if len(parts) < 2:
                console.print("[yellow]Usage: USEVEHICLE <type>|OFF[/yellow]")
                return True
            arg = parts[1].strip().lower()
            if arg in ("off", "none", "-", "no"):
                r = set_active_vehicle(state, "")
            else:
                r = set_active_vehicle(state, arg)
            if r.get("ok"):
                av = r.get("active_vehicle_id") or "(none)"
                console.print(f"[green]Active vehicle set:[/green] {av}")
            else:
                console.print(f"[red]USEVEHICLE failed:[/red] {r.get('reason','error')}")
        except Exception as _omni_sw_1770:
            log_swallowed_exception('main.py:1770', _omni_sw_1770)
            console.print("[red]USEVEHICLE error.[/red]")
        return True
    if up == "DRIVE" or up.startswith("DRIVE "):
        try:
            parts = cmd.split(maxsplit=2)
            if len(parts) < 2:
                console.print("[yellow]Usage: DRIVE <dest> [vehicle_type][/yellow]")
                return True
            tail = parts[1].strip() if len(parts) == 2 else parts[2].strip()
            toks = tail.split()
            dest = tail
            vid = ""
            if len(toks) >= 2:
                # last token could be vehicle id
                cand = toks[-1].strip().lower()
                try:
                    if cand in VEHICLE_TYPES:
                        vid = cand
                        dest = " ".join(toks[:-1]).strip()
                except Exception as _omni_sw_1792:
                    log_swallowed_exception('main.py:1792', _omni_sw_1792)
            ctx = {
                "action_type": "travel",
                "domain": "evasion",
                "normalized_input": f"drive {dest}",
                "travel_destination": dest,
                "travel_minutes": 30,
                "stakes": "low",
            }
            if vid:
                ctx["vehicle_id"] = vid
            run_pipeline(state, ctx)
            console.print(f"[green]DRIVE queued.[/green] dest={dest}" + (f" vehicle={vid}" if vid else ""))
        except Exception as _omni_sw_1806:
            log_swallowed_exception('main.py:1806', _omni_sw_1806)
            console.print("[red]DRIVE error.[/red]")
        return True
    if up == "TRAVELTO" or up.startswith("TRAVELTO "):
        try:
            parts = cmd.split(maxsplit=1)
            if len(parts) < 2:
                console.print("[yellow]Usage: TRAVELTO <district_id>[/yellow]")
                console.print("[dim]Use DISTRICTS to see available districts.[/dim]")
                return True
            
            target = parts[1].strip().lower()
            result = travel_within_city(state, target)
            
            if not result.get("ok"):
                console.print(f"[red]{result.get('message','Error')}[/red]")
            else:
                console.print(f"[green]{result.get('message','')}[/green]")
                if result.get("encounter"):
                    enc = result["encounter"]
                    if enc.get("type") == "crime":
                        console.print(f"[yellow]Warning: Crime risk {enc.get('risk')}/5 in this area![/yellow]")
                    elif enc.get("type") == "police":
                        console.print(f"[yellow]Warning: Heavy police presence in this area![/yellow]")
        except Exception as _omni_sw_1832:
            log_swallowed_exception('main.py:1832', _omni_sw_1832)
            console.print("[red]TRAVELTO error.[/red]")
        return True
    if up == "WHEREAMI":
        try:
            current_desc = describe_location(state)
            console.print(f"[bold]WHEREAMI[/bold]")
            console.print(current_desc)
        except Exception as _omni_sw_1842:
            log_swallowed_exception('main.py:1842', _omni_sw_1842)
            # Fallback to basic location
            loc = str((state.get("player", {}) or {}).get("location", "") or "-").strip()
            console.print(f"[bold]WHEREAMI[/bold] {loc}")
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
            except Exception as _omni_sw_1915:
                log_swallowed_exception('main.py:1915', _omni_sw_1915)
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
                except Exception as _omni_sw_2008:
                    log_swallowed_exception('main.py:2008', _omni_sw_2008)
                    heat = 0
                try:
                    noise = int(v.get("noise", 0) or 0)
                except Exception as _omni_sw_2012:
                    log_swallowed_exception('main.py:2012', _omni_sw_2012)
                    noise = 0
                try:
                    signal = int(v.get("signal", 0) or 0)
                except Exception as _omni_sw_2016:
                    log_swallowed_exception('main.py:2016', _omni_sw_2016)
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
            except Exception as _omni_sw_2052:
                log_swallowed_exception('main.py:2052', _omni_sw_2052)
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
    if up == "INFORMANTS" or up.startswith("INFORMANTS "):
        try:
            loc = str((state.get("player", {}) or {}).get("location", "") or "").strip().lower()
            did = str((state.get("player", {}) or {}).get("district", "") or "").strip().lower()
            seed_informant_roster(state, loc=loc, district=did)
            roster = ((state.get("world", {}) or {}).get("informant_roster", {}) or {})
            inf = ((state.get("world", {}) or {}).get("informants", {}) or {})
            key = loc + ("|" + did if did else "")
            row = roster.get(key) if isinstance(roster, dict) else None
            names = (row.get("names") if isinstance(row, dict) else []) or []
            if not isinstance(names, list) or not names:
                console.print("[yellow]INFORMANTS: tidak ada roster (seed NPC dulu / content pack belum ada).[/yellow]")
                return True
            tbl = Table(title=f"INFORMANTS @ {key}")
            tbl.add_column("name", no_wrap=True)
            tbl.add_column("aff", no_wrap=True)
            tbl.add_column("reliability", justify="right")
            tbl.add_column("greed", justify="right")
            for nm in names[:12]:
                prof = inf.get(nm) if isinstance(inf, dict) else {}
                if not isinstance(prof, dict):
                    prof = {}
                tbl.add_row(
                    str(nm),
                    str(prof.get("affiliation", "-")),
                    str(int(prof.get("reliability", 50) or 50)),
                    str(int(prof.get("greed", 40) or 40)),
                )
            console.print(tbl)
            console.print("[dim]Commands: INFORMANT PAY <name> <amount> | INFORMANT BURN <name>[/dim]")
        except Exception as _omni_sw_2095:
            log_swallowed_exception('main.py:2095', _omni_sw_2095)
            console.print("[red]INFORMANTS error.[/red]")
        return True
    if up == "INFORMANT" or up.startswith("INFORMANT "):
        try:
            parts = cmd.split(maxsplit=3)
            if len(parts) < 3:
                console.print("[yellow]Usage: INFORMANT PAY <name> <amount> | INFORMANT BURN <name>[/yellow]")
                return True
            act = parts[1].strip().lower()
            name = parts[2].strip()
            if act == "pay":
                if len(parts) < 4:
                    console.print("[yellow]Usage: INFORMANT PAY <name> <amount>[/yellow]")
                    return True
                try:
                    amt = int(parts[3].strip())
                except Exception as _omni_sw_2114:
                    log_swallowed_exception('main.py:2114', _omni_sw_2114)
                    amt = 0
                r = pay_informant(state, name, amt)
                if not r.get("ok"):
                    msg = str(r.get("message", "") or "")
                    if r.get("reason") == "premium_intel_locked" and msg:
                        console.print(f"[yellow]PAY blocked:[/yellow] {msg} (cap {r.get('cap','?')})")
                    else:
                        console.print(f"[red]PAY failed:[/red] {r.get('reason','error')}")
                else:
                    console.print(f"[green]PAY OK[/green] cash {r.get('cash_delta')} reliability {r.get('reliability_before')}→{r.get('reliability_after')}")
                return True
            if act == "burn":
                r = burn_informant(state, name)
                if not r.get("ok"):
                    console.print(f"[red]BURN failed:[/red] {r.get('reason','error')}")
                else:
                    msg = "BURN OK"
                    if r.get("backlash_scheduled"):
                        msg += " (backlash: npc_report scheduled)"
                    console.print(f"[green]{msg}[/green] roll={r.get('backlash_roll')} chance={r.get('backlash_chance')}")
                return True
            console.print("[red]Unknown INFORMANT action. Use PAY/BURN.[/red]")
        except Exception as _omni_sw_2137:
            log_swallowed_exception('main.py:2137', _omni_sw_2137)
            console.print("[red]INFORMANT error.[/red]")
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
        if isinstance(npc, dict) and (npc.get("alive") is False or int(npc.get("hp", 1) or 1) <= 0):
            console.print(f"[bold]NPC: {name}[/bold] [red](DEAD)[/red]")
            console.print(f"- reason={npc.get('dead_reason','unknown')} dead_turn={npc.get('dead_turn','-')}")
            console.print(f"- loc={npc.get('current_location', npc.get('home_location','-'))} home={npc.get('home_location','-')}")
            return True
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
        except Exception as _omni_sw_2192:
            log_swallowed_exception('main.py:2192', _omni_sw_2192)
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
    if up == "SHOP" or up.startswith("SHOP "):
        parts = cmd.split(maxsplit=5)
        arg1 = parts[1].strip().lower() if len(parts) >= 2 else ""
        arg2 = parts[2].strip().lower() if len(parts) >= 3 else ""
        arg3 = parts[3].strip().lower() if len(parts) >= 4 else ""
        arg4 = parts[4].strip().lower() if len(parts) >= 5 else ""
        arg5 = parts[5].strip().lower() if len(parts) >= 6 else ""
        role = ""
        only_avail = False
        page = 1
        tag = ""
        if arg1 == "roles":
            try:
                loc = str((state.get("player", {}) or {}).get("location", "") or "").strip().lower()
                slot = ((state.get("world", {}) or {}).get("locations", {}) or {}).get(loc)
                roles_here: list[str] = []
                if isinstance(slot, dict):
                    npcs = slot.get("npcs") or {}
                    if isinstance(npcs, dict):
                        for _nm, row in list(npcs.items())[:120]:
                            if not isinstance(row, dict):
                                continue
                            rr = str(row.get("role", "") or "").strip().lower()
                            if rr and rr not in roles_here:
                                roles_here.append(rr)
                if roles_here:
                    console.print("[bold]SHOP roles[/bold]")
                    console.print("- " + ", ".join(roles_here))
                else:
                    console.print("[yellow]SHOP roles: tidak ada role NPC di lokasi ini (preset belum ada atau belum diaplikasikan).[/yellow]")
            except Exception as _omni_sw_2241:
                log_swallowed_exception('main.py:2241', _omni_sw_2241)
                console.print("[red]SHOP roles error.[/red]")
            return True
        # parse page syntax: "page 2" in arg2/arg3
        def _parse_page_token(tok: str) -> int | None:
            t = str(tok or "").strip().lower()
            if t.startswith("page"):
                # supports "page2" too
                try:
                    n = int(t.replace("page", "").strip() or "0")
                    return n if n >= 1 else None
                except Exception as _omni_sw_2252:
                    log_swallowed_exception('main.py:2252', _omni_sw_2252)
                    return None
            return None

        p2 = _parse_page_token(arg2)
        p3 = _parse_page_token(arg3)
        p4 = _parse_page_token(arg4)
        p5 = _parse_page_token(arg5)
        if p2 is not None:
            page = p2
        if p3 is not None:
            page = p3
        if p4 is not None:
            page = p4
        if p5 is not None:
            page = p5
        # tag filter syntax: "tag <x>"
        if arg1 == "tag" and arg2:
            tag = arg2
            role = ""
        elif arg2 == "tag" and arg3:
            tag = arg3
        elif arg3 == "tag" and arg4:
            tag = arg4
        elif arg4 == "tag" and arg5:
            tag = arg5
        if arg1 in ("available", "avail", "in_stock"):
            only_avail = True
        else:
            if arg1 and arg1 != "tag":
                role = arg1
        if arg2 in ("available", "avail", "in_stock"):
            only_avail = True
        if arg3 in ("available", "avail", "in_stock"):
            only_avail = True
        if arg4 in ("available", "avail", "in_stock"):
            only_avail = True
        if arg5 in ("available", "avail", "in_stock"):
            only_avail = True
        offset = max(0, (page - 1) * 12)
        quotes = list_shop_quotes(state, limit=12, role=(role or None), offset=offset, tag=(tag or None))
        if not quotes:
            console.print("[yellow]SHOP: tidak ada item (content pack belum ter-load).[/yellow]")
            return True
        # Hint: show available roles at this location (from location preset slot).
        try:
            loc = str((state.get("player", {}) or {}).get("location", "") or "").strip().lower()
            slot = ((state.get("world", {}) or {}).get("locations", {}) or {}).get(loc)
            roles_here: list[str] = []
            if isinstance(slot, dict):
                npcs = slot.get("npcs") or {}
                if isinstance(npcs, dict):
                    for _nm, row in list(npcs.items())[:80]:
                        if not isinstance(row, dict):
                            continue
                        rr = str(row.get("role", "") or "").strip().lower()
                        if rr and rr not in roles_here:
                            roles_here.append(rr)
            if roles_here:
                console.print("[dim]roles here: " + ", ".join(roles_here[:10]) + "[/dim]")
        except Exception as _omni_sw_2312:
            log_swallowed_exception('main.py:2312', _omni_sw_2312)
        # Show cash + capacity snapshot (helps players understand BUY failures).
        try:
            eco = state.get("economy", {}) or {}
            cash = int((eco.get("cash", 0) if isinstance(eco, dict) else 0) or 0)
            cap = get_capacity_status(state)
            console.print(f"[dim]cash={cash} | pocket={cap.pocket_used}/{cap.pocket_cap} | bag={cap.bag_used}/{cap.bag_cap}[/dim]")
        except Exception as _omni_sw_2320:
            log_swallowed_exception('main.py:2320', _omni_sw_2320)
        if only_avail:
            quotes = [q for q in quotes if q.available]
        title = f"SHOP ({role})" if role else "SHOP"
        if only_avail:
            title += " [available]"
        if tag:
            title += f" [tag={tag}]"
        if page > 1:
            title += f" [page {page}]"
        try:
            rows: list[list[str]] = []
            for i, q in enumerate(quotes, start=1):
                stock = "OK" if q.available else "SOLD OUT"
                rows.append([str(i), str(q.item_id), str(q.name), str(q.category), str(stock), str(q.buy_price), str(q.sell_price)])
            console.print(format_data_table(title, ["#", "item_id", "name", "cat", "stock", "buy", "sell"], rows, theme="default"))
        except Exception as _omni_sw_2339:
            log_swallowed_exception('main.py:2339', _omni_sw_2339)
            tbl = Table(title=title)
            tbl.add_column("#", justify="right", no_wrap=True)
            tbl.add_column("item_id", no_wrap=True)
            tbl.add_column("name")
            tbl.add_column("cat", no_wrap=True)
            tbl.add_column("stock", no_wrap=True)
            tbl.add_column("buy", justify="right")
            tbl.add_column("sell", justify="right")
            for i, q in enumerate(quotes, start=1):
                stock = "OK" if q.available else "SOLD OUT"
                tbl.add_row(str(i), q.item_id, q.name, q.category, stock, str(q.buy_price), str(q.sell_price))
            console.print(tbl)
        console.print(
            "[dim]Use: SHOP [role] [tag <x>] [available] [page N] | BUY <item_id> [xN] [bag|pocket] [counter|dead_drop|courier] | SELL <item_id> [ALL] | PRICE <item_id>[/dim]"
        )
        return True
    if up == "PRICE" or up.startswith("PRICE "):
        parts = cmd.split(maxsplit=2)
        if len(parts) < 2:
            console.print("[yellow]Usage: PRICE <item_id>[/yellow]")
            return True
        q = quote_item(state, parts[1].strip())
        if q is None:
            console.print("[red]Unknown item_id.[/red]")
            return True
        console.print(f"[bold]PRICE[/bold] {q.item_id} ({q.name})")
        console.print(f"- cat={q.category} base={q.base_price} price_idx={q.price_idx} scarcity={q.scarcity}")
        console.print(f"- buy={q.buy_price} sell={q.sell_price}")
        if q.available:
            console.print("- stock=OK")
        else:
            console.print(f"- stock=SOLD OUT ({q.sold_out_reason})")
        return True
    if up == "BUY" or up.startswith("BUY "):
        parts = cmd.split(maxsplit=5)
        if len(parts) < 2:
            console.print("[yellow]Usage: BUY <item_id> [xN] [bag|pocket] [counter|dead_drop|courier][/yellow]")
            return True
        iid = parts[1].strip()
        qty = 1
        prefer = "bag"
        delivery = "counter"
        for tok in parts[2:]:
            t = str(tok).strip().lower()
            if t.startswith("x") and len(t) >= 2:
                try:
                    qty = max(1, min(50, int(t[1:])))
                except Exception as _omni_sw_2387:
                    log_swallowed_exception('main.py:2387', _omni_sw_2387)
                    qty = 1
            elif t in ("bag", "pocket"):
                prefer = t
            elif t in ("counter", "dead_drop", "deaddrop", "dead", "drop", "courier", "meet"):
                delivery = t

        bought = 0
        last_err = None
        last_res = None
        for _ in range(qty):
            res = buy_item(state, iid, prefer=prefer, delivery=delivery)
            last_res = res
            if not bool(res.get("ok")):
                last_err = res
                break
            bought += 1
        if bought <= 0:
            res = last_err or last_res or {}
            reason = res.get("reason", "error")
            detail = res.get("detail")
            if reason == "sold_out":
                console.print(f"[red]BUY failed: SOLD OUT[/red] ({detail})")
            elif reason == "not_enough_cash":
                console.print(f"[red]BUY failed: not enough cash[/red] need={res.get('need')} cash={res.get('cash')}")
            elif reason == "no_capacity":
                console.print(
                    "[red]BUY failed: no capacity[/red] "
                    f"size={res.get('size')} pocket={res.get('pocket_used')}/{res.get('pocket_cap')} bag={res.get('bag_used')}/{res.get('bag_cap')}"
                )
            else:
                console.print(f"[red]BUY failed: {reason}[/red]")
            return True
        # success (maybe partial)
        q = (last_res or {}).get("quote")
        cash_after = (last_res or {}).get("cash_after")
        placed = (last_res or {}).get("placed_to", prefer)
        if placed == "delivery_pending":
            d = (last_res or {}).get("delivery", "?")
            due = (last_res or {}).get("delivery_due_in_min", "?")
            fee = (last_res or {}).get("delivery_fee", 0)
            console.print(f"[yellow]Delivery scheduled[/yellow] via={d} fee={fee} due~{due}min (pickup required)")
        if bought == 1 and q:
            console.print(f"[green]BUY OK[/green] {q.item_id} price={q.buy_price} cash={cash_after} to={placed}")
        elif q:
            console.print(f"[green]BUY OK[/green] {q.item_id} x{bought} cash={cash_after} (last_to={placed})")
            if last_err:
                console.print(f"[yellow]Stopped early: {last_err.get('reason','error')}[/yellow]")
        else:
            console.print(f"[green]BUY OK[/green] x{bought}")
        return True
    if up == "SELL" or up.startswith("SELL "):
        parts = cmd.split(maxsplit=3)
        if len(parts) < 2:
            console.print("[yellow]Usage: SELL <item_id> [ALL][/yellow]")
            return True
        iid = parts[1].strip()
        tok = parts[2].strip() if len(parts) >= 3 else ""
        all_mode = tok.upper() == "ALL"
        qty_mode = tok.lower().startswith("x") and len(tok) >= 2
        if all_mode:
            res = sell_item_all(state, iid)
        elif qty_mode:
            try:
                n = int(tok[1:])
            except Exception as _omni_sw_2452:
                log_swallowed_exception('main.py:2452', _omni_sw_2452)
                n = 1
            res = sell_item_n(state, iid, n=n)
        else:
            res = sell_item(state, iid)
        if not bool(res.get("ok")):
            console.print(f"[red]SELL failed: {res.get('reason','error')}[/red]")
            return True
        q = res.get("quote")
        if q:
            if all_mode:
                console.print(
                    f"[green]SELL ALL OK[/green] {q.item_id} n={res.get('count',0)} unit={q.sell_price} gain={res.get('gain',0)} cash={res.get('cash_after')}"
                )
            elif qty_mode:
                console.print(
                    f"[green]SELL x OK[/green] {q.item_id} n={res.get('count',0)} unit={q.sell_price} gain={res.get('gain',0)} cash={res.get('cash_after')}"
                )
            else:
                console.print(f"[green]SELL OK[/green] {q.item_id} price={q.sell_price} cash={res.get('cash_after')}")
        else:
            console.print("[green]SELL OK[/green]")
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

    asyncio.run(game_loop_async(state))


async def game_loop_async(state: dict[str, Any]) -> None:
    async def _process_pending_utility_ai() -> None:
        world = state.setdefault("world", {})
        if not isinstance(world, dict):
            return
        try:
            pend_day = int(world.get("pending_utility_ai_day", 0) or 0)
        except Exception:
            pend_day = 0
        if pend_day <= 0:
            return
        try:
            await evaluate_npc_goals(state, batch_size=50)
        except Exception as _omni_sw_utility_ai_async:
            log_swallowed_exception("main.py:utility_ai_async", _omni_sw_utility_ai_async)
        finally:
            if int(world.get("pending_utility_ai_day", 0) or 0) == pend_day:
                world["pending_utility_ai_day"] = 0

    while True:
        await _process_pending_utility_ai()
        render_monitor(state)
        cmd_raw = _expand_alias(await _ainput_line("> "))
        cmd = sanitize_player_command_text(cmd_raw)
        if not cmd:
            continue
        # WORLD_BRIEF: async stream (same heartbeat as turn narration).
        up_brief = cmd.strip().upper()
        if up_brief == "WORLD_BRIEF":
            lang = get_narration_lang(state)
            if lang == "en":
                tp = "WORLD_BRIEF: summarize the world from the player character's POV in <=400 words."
            else:
                tp = (
                    "WORLD_BRIEF: rangkum dunia dari sudut pandang karakter pemain, "
                    "maksimal ~400 kata, Bahasa Indonesia."
                )
            try:
                await run_narration_stream_with_heartbeat(
                    build_system_prompt(state),
                    tp,
                    console=console,
                    stream_render=stream_render,
                    label="Ringkasan dunia",
                )
            except Exception as _omni_sw_1947:
                log_swallowed_exception("main.py:world_brief", _omni_sw_1947)
                console.print("[red]// SIGNAL LOST //[/red]")
            continue
        # Global scene blocker (non-special path).
        up0 = cmd.upper()
        if _scene_blocks_command(state, up0):
            if up0 == "EAT" or up0.startswith("EAT "):
                console.print("[yellow]Situasi tidak memungkinkan untuk makan sekarang.[/yellow]")
                continue
            console.print("[yellow]Scene active. Use: SCENE | SCENE OPTIONS | SCENE <action>[/yellow]")
            continue
        metrics_before = _snapshot_metrics(state)
        if handle_special(state, cmd):
            if bool(_special_turn_profile(cmd).get("consume", False)):
                _finalize_special_turn(state, cmd, metrics_before)
            continue

        # 1) Intent resolution: LLM-first when FFCI enabled; meta/special stay fast-path above.
        meta = state.setdefault("meta", {})
        action_ctx = parse_action_intent(cmd)
        parser_registry_id = str(action_ctx.get("registry_action_id") or "").strip()
        if parser_registry_id:
            meta["resolved_action_id"] = parser_registry_id
            meta["intent_resolution"] = "registry"
        apply_pending_runtime_step(state, action_ctx)
        intent = None
        if ffci_enabled() and security_flags_for_intent_input(cmd).get("block_resolver"):
            meta["fallback_reason"] = "security_blocked"
        elif ffci_enabled():
            intent = await resolve_intent_async(state, cmd)

        if intent and ffci_shadow_only():
            meta["last_intent_source"] = "parser_fallback"
            meta["last_intent_raw"] = None
            meta["fallback_reason"] = "ffci_shadow_only"
            meta["ffci_shadow_llm_intent"] = dict(intent) if isinstance(intent, dict) else intent
            meta["llm_domain_raw"] = str((intent or {}).get("domain", "") or "").lower()
        elif intent:
            meta.pop("_parser_intent_snapshot_before_llm_merge", None)
            if parser_registry_id:
                meta["_parser_intent_snapshot_before_llm_merge"] = {
                    k: action_ctx[k] for k in INTENT_MERGE_FIELD_KEYS if k in action_ctx
                }
            merge_intent_into_action_ctx(action_ctx, intent)
            if parser_registry_id:
                apply_parser_registry_anchor_after_llm(action_ctx, meta, parser_registry_id)
            try:
                lh0 = str(action_ctx.get("llm_registry_action_id_hint") or "").strip()
                pr0 = str(action_ctx.get("registry_action_id") or "").strip()
                snap0 = meta.get("_parser_intent_snapshot_before_llm_merge")
                if (
                    pr0
                    and lh0
                    and registry_hint_alignment(pr0, lh0) == "mismatch"
                    and isinstance(snap0, dict)
                ):
                    for _k in INTENT_MERGE_FIELD_KEYS:
                        if _k in snap0:
                            action_ctx[_k] = snap0[_k]
                        else:
                            action_ctx.pop(_k, None)
                    strip_llm_intent_overlay_on_registry_hint_mismatch(action_ctx)
                    apply_parser_registry_anchor_after_llm(action_ctx, meta, parser_registry_id)
            except Exception as _omni_sw_2600:
                log_swallowed_exception('main.py:2600', _omni_sw_2600)
            meta.pop("_parser_intent_snapshot_before_llm_merge", None)
            clamp_suggested_dc_ctx(action_ctx)
            if not ffci_shadow_only():
                update_ffci_custom_streak(meta, action_ctx)
            allow_custom, ab_reason = abuse_allow_custom_intent(state, action_ctx)
            if not allow_custom:
                meta["ffci_custom_streak"] = 0
                action_ctx = parse_action_intent(cmd)
                apply_pending_runtime_step(state, action_ctx)
                pr2 = str(action_ctx.get("registry_action_id") or "").strip()
                if pr2:
                    meta["resolved_action_id"] = pr2
                    meta["intent_resolution"] = "registry"
                else:
                    meta.pop("resolved_action_id", None)
                    meta.pop("intent_resolution", None)
                meta["last_intent_source"] = "parser_fallback"
                meta["last_intent_raw"] = None
                meta["fallback_reason"] = ab_reason or "ffci_abuse_guard"
                meta["ffci_abuse_blocked"] = True
                meta["normalized_domain"] = str(action_ctx.get("domain", "") or "").lower()
                meta["custom_path_used"] = str(action_ctx.get("action_type", "") or "").lower() == "custom"
                meta["llm_domain_raw"] = ""
                state.setdefault("world_notes", []).append("[FFCI] High-risk custom intent rate-limited for today; using parser path.")
            else:
                meta["last_intent_source"] = "llm"
                meta["last_intent_raw"] = intent
                meta["fallback_reason"] = None
                meta["ffci_abuse_blocked"] = False
                record_custom_high_risk(state, action_ctx)
                meta["llm_domain_raw"] = str((intent or {}).get("domain", "") or "").lower()
                meta["normalized_domain"] = str(action_ctx.get("domain", "") or "").lower()
                meta["custom_path_used"] = str(action_ctx.get("action_type", "") or "").lower() == "custom"

            if meta.get("last_intent_source") == "llm":
                # Intent v2 plan execution: pick the first valid step by preconditions and overlay it.
                if int(action_ctx.get("intent_version", 1) or 1) == 2 and isinstance(action_ctx.get("intent_plan"), dict):
                    sid = select_best_step(action_ctx, state)
                    plan_obj = action_ctx.get("intent_plan") if isinstance(action_ctx.get("intent_plan"), dict) else {}
                    steps_list = plan_obj.get("steps") if isinstance(plan_obj.get("steps"), list) else []
                    n_plan = sum(1 for s in steps_list if isinstance(s, dict) and str(s.get("step_id", "") or "").strip())
                    if sid is None and n_plan > 0:
                        apply_intent_plan_precondition_failure(state, action_ctx, reason="NO_VALID_STEP")
                    if isinstance(sid, str) and sid.strip():
                        action_ctx["step_now_id"] = sid.strip()
                        steps = (action_ctx.get("intent_plan") or {}).get("steps")
                        if isinstance(steps, list):
                            for st in steps:
                                if isinstance(st, dict) and str(st.get("step_id", "") or "").strip() == action_ctx["step_now_id"]:
                                    apply_step_to_action_ctx(action_ctx, st)
                                    break
                    clamp_suggested_dc_ctx(action_ctx)
                    if (
                        isinstance(sid, str)
                        and sid.strip()
                        and not bool(action_ctx.get("intent_plan_blocked"))
                    ):
                        try:
                            sync_plan_runtime_start(state, action_ctx, source="llm")
                        except Exception as _omni_sw_2663:
                            log_swallowed_exception('main.py:2663', _omni_sw_2663)
                stakes = action_ctx.get("stakes")
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
        else:
            meta["last_intent_source"] = "parser_fallback" if ffci_enabled() else "ffci_disabled"
            meta["last_intent_raw"] = None
            if str(meta.get("fallback_reason", "") or "") != "security_blocked":
                meta["fallback_reason"] = "resolver_none" if ffci_enabled() else "ffci_disabled"
            meta["normalized_domain"] = str(action_ctx.get("domain", "") or "").lower()
            meta["custom_path_used"] = str(action_ctx.get("action_type", "") or "").lower() == "custom"
            meta["llm_domain_raw"] = ""
            if not ffci_enabled():
                meta["ffci_disabled"] = True

        try:
            shadow_norm = normalize_action_ctx(action_ctx)
            mismatches: list[str] = []
            for k in ("action_type", "domain", "roll_domain", "instant_minutes", "travel_minutes"):
                if k in shadow_norm and shadow_norm.get(k) != action_ctx.get(k):
                    mismatches.append(k)
            if mismatches:
                meta = state.setdefault("meta", {})
                meta["action_ctx_shadow_mismatch"] = int(meta.get("action_ctx_shadow_mismatch", 0) or 0) + 1
                state.setdefault("world_notes", []).append(
                    f"[ActionCtxShadow] mismatch keys={','.join(mismatches)}"
                )
        except Exception as e:
            log_swallowed_exception('main.py:2703', e)
            _record_soft_error(state, "main.action_ctx_shadow", e)

        # Registry hint telemetry (parser id vs optional LLM hint after merge).
        try:
            lh = str(action_ctx.get("llm_registry_action_id_hint") or "").strip()
            pr_final = str(action_ctx.get("registry_action_id") or "").strip()
            if lh:
                meta["llm_registry_action_id_hint"] = lh
            else:
                meta.pop("llm_registry_action_id_hint", None)
            meta["registry_hint_alignment"] = registry_hint_alignment(pr_final, lh or None)
            if meta.get("registry_hint_alignment") == "mismatch":
                meta["registry_hint_mismatch"] = True
            else:
                meta.pop("registry_hint_mismatch", None)
        except Exception as _omni_sw_2721:
            log_swallowed_exception('main.py:2721', _omni_sw_2721)
            meta.pop("llm_registry_action_id_hint", None)
            meta.pop("registry_hint_alignment", None)
            meta.pop("registry_hint_mismatch", None)

        ra_sync = str(meta.get("registry_hint_alignment", "") or "").strip()
        if ra_sync:
            action_ctx["registry_hint_alignment"] = ra_sync
        else:
            action_ctx.pop("registry_hint_alignment", None)
        if meta.get("registry_hint_mismatch"):
            action_ctx["registry_hint_mismatch"] = True
        else:
            action_ctx.pop("registry_hint_mismatch", None)

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
        try:
            apply_npc_targeting(state, action_ctx, cmd)
        except Exception as _omni_sw_2801:
            log_swallowed_exception('main.py:2801', _omni_sw_2801)
        # Optional: NL "menginap semalam" / "stay one night" → deterministic prepaid stay (OMNI_AUTO_STAY_INTENT=1).
        try:
            auto_r = try_auto_stay_from_intent(state, action_ctx)
            if bool(auto_r.get("applied")):
                action_ctx["accommodation_auto_applied"] = True
                action_ctx["accommodation_auto_detail"] = {
                    "kind": auto_r.get("kind"),
                    "nights": auto_r.get("nights"),
                }
                try:
                    tn = stay_kind_label(str(auto_r.get("kind") or ""), short=True)
                    console.print(
                        f"[dim]Engine: prepaid stay applied — {tn} +{int(auto_r.get('nights') or 0)}n (OMNI_AUTO_STAY_INTENT)[/dim]"
                    )
                except Exception as _omni_sw_2820:
                    log_swallowed_exception('main.py:2820', _omni_sw_2820)
        except Exception as _omni_sw_2822:
            log_swallowed_exception('main.py:2822', _omni_sw_2822)
        apply_active_scene_intent_lock(state, action_ctx, cmd)

        try:
            apply_cross_system_policies(state, action_ctx)
        except Exception as _omni_sw_2831:
            log_swallowed_exception('main.py:2831', _omni_sw_2831)
        roll_pkg = run_pipeline(state, action_ctx)
        try:
            merge_telemetry_turn_last(state, snapshot_turn_telemetry(state, action_ctx, roll_pkg))
        except Exception as _omni_sw_2839:
            log_swallowed_exception('main.py:2839', _omni_sw_2839)
        metrics_after = _snapshot_metrics(state)
        try:
            post_turn_integration(
                state,
                action_ctx,
                roll_pkg,
                player_cmd=cmd,
                metrics_before=metrics_before,
                metrics_after=metrics_after,
            )
        except Exception as _omni_sw_2854:
            log_swallowed_exception('main.py:2854', _omni_sw_2854)
        diff = _compute_diff(metrics_before, metrics_after)
        meta = state.setdefault("meta", {})
        meta["last_turn_diff"] = diff
        # What Changed v2: attach "notes added" slice (bounded) for transparent simulation.
        try:
            n0 = int(metrics_before.get("world_notes_len", 0) or 0)
        except Exception as _omni_sw_2862:
            log_swallowed_exception('main.py:2862', _omni_sw_2862)
            n0 = 0
        notes = state.get("world_notes", []) or []
        added: list[str] = []
        if isinstance(notes, list) and n0 < len(notes):
            for x in notes[n0:][-6:]:
                s = world_note_plain(x)
                added.append(s if len(s) <= 160 else (s[:157] + "..."))
        commerce_notes: list[str] = []
        for s in added:
            ss = str(s)
            if ss.startswith("[Shop]") or ss.startswith("[Bank]") or ss.startswith("[Stay]"):
                commerce_notes.append(ss if len(ss) <= 200 else (ss[:197] + "..."))
        meta["last_turn_audit"] = {
            "turn": int(meta.get("turn", 0) or 0),
            "action_type": str(action_ctx.get("action_type", "instant") or "instant"),
            "domain": str(action_ctx.get("domain", "") or ""),
            "time_cost_min": int(action_ctx.get("time_cost_min", 0) or 0),
            "diff": diff,
            "notes_added": added,
            "commerce_notes": commerce_notes,
            "time_elapsed_min": int(diff.get("time_elapsed_min", 0) or 0),
            "time_breakdown": action_ctx.get("time_breakdown", []),
            "language_ctx": action_ctx.get("language_ctx", {}),
        }

        package = build_turn_package(state, cmd, roll_pkg, action_ctx)
        system_prompt = build_system_prompt(state)

        # Narration: async httpx stream + heartbeat until first token; state unchanged until chunks arrive.
        text = ""
        try:
            text = await run_narration_stream_with_heartbeat(
                system_prompt,
                package,
                console=console,
                stream_render=stream_render,
                label="Narasi",
            )
        except Exception as _omni_sw_2897:
            log_swallowed_exception("main.py:2897", _omni_sw_2897)
            console.print("[red]// SIGNAL LOST //[/red]")
            try:
                text = await run_narration_stream_with_heartbeat(
                    system_prompt,
                    package,
                    console=console,
                    stream_render=stream_render,
                    label="Narasi",
                )
            except Exception as _omni_sw_2904:
                log_swallowed_exception("main.py:2904", _omni_sw_2904)
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

