from __future__ import annotations

from engine.core.error_taxonomy import log_swallowed_exception
from typing import Any, Callable

from rich.table import Table

from display.renderer import console
from engine.systems.crafting import craft, format_recipe_constraints, list_recipes
from engine.world.timers import update_timers


def handle_misc(
    state: dict[str, Any],
    cmd: str,
    *,
    fmt_clock: Callable[[int], str],
) -> bool:
    up = cmd.upper()
    if up == "UI FULL":
        state.setdefault("meta", {})["monitor_mode"] = "full"
        console.print("[green]Monitor: FULL (lebar).[/green]")
        return True
    if up == "UI COMPACT":
        state.setdefault("meta", {})["monitor_mode"] = "compact"
        console.print("[green]Monitor: COMPACT (ringkas).[/green]")
        return True
    if up == "CRAFT" or up.startswith("CRAFT "):
        parts = cmd.split()
        sub = (parts[1] if len(parts) > 1 else "").strip().lower()
        if not sub or sub in ("list", "help", "?"):
            rows = list_recipes()
            if not rows:
                console.print("[yellow]Belum ada resep (recipes.json kosong).[/yellow]")
                return True
            t = Table(title="CRAFT — resep", show_header=True)
            t.add_column("id", style="bold cyan", no_wrap=True)
            t.add_column("kat", style="dim", no_wrap=True)
            t.add_column("syarat", style="yellow")
            t.add_column("butuh", style="dim")
            t.add_column("hasil", style="green")
            t.add_column("m", style="dim", justify="right", no_wrap=True)
            for r in rows:
                rid = str(r.get("id", "") or "")
                cat = str(r.get("category", "") or "").strip() or "—"
                ing = r.get("ingredients") if isinstance(r.get("ingredients"), dict) else {}
                out = r.get("outputs") if isinstance(r.get("outputs"), dict) else {}
                try:
                    tm = int(r.get("time_min", 5) or 5)
                except Exception as _omni_sw_48:
                    log_swallowed_exception('engine/commands/misc.py:48', _omni_sw_48)
                    tm = 5
                t.add_row(
                    rid,
                    cat,
                    format_recipe_constraints(r),
                    ", ".join(f"{k}×{v}" for k, v in ing.items()),
                    ", ".join(f"{k}×{v}" for k, v in out.items()),
                    str(tm),
                )
            console.print(t)
            console.print("[dim]Gunakan: CRAFT <recipe_id>[/dim]")
            return True
        res = craft(state, sub)
        if not res.get("ok"):
            reason = str(res.get("reason", "?") or "?")
            hints = {
                "need_safehouse": " (butuh safehouse aktif di lokasi ini — sewa/beli)",
                "need_room": " (butuh menginap prepaid di lokasi ini — STAY hotel/kos/suite)",
                "need_bench": " (butuh safehouse ATAU kamar prepaid di lokasi ini)",
                "skill_too_low": " (skill tidak cukup)",
                "not_enough_cash": " (cash tidak cukup)",
            }
            console.print(f"[red]Craft gagal: {reason}{hints.get(reason, '')}[/red]")
            return True
        try:
            update_timers(
                state,
                {
                    "action_type": "instant",
                    "instant_minutes": int(res.get("time_min", 8) or 8),
                    "domain": "inventory",
                    "normalized_input": f"craft {sub}",
                },
            )
        except Exception as _omni_sw_85:
            log_swallowed_exception('engine/commands/misc.py:85', _omni_sw_85)
        extra = ""
        try:
            cp = int(res.get("cash_paid", 0) or 0)
            if cp > 0:
                extra = f" (−${cp} cash)"
        except Exception as _omni_sw_92:
            log_swallowed_exception('engine/commands/misc.py:92', _omni_sw_92)
        xp_note = ""
        try:
            xsk = str(res.get("xp_skill", "") or "").strip()
            xam = int(res.get("xp_amount", 0) or 0)
            if xsk and xam > 0:
                xp_note = f" [+{xam} XP {xsk}]"
        except Exception as _omni_sw_100:
            log_swallowed_exception('engine/commands/misc.py:100', _omni_sw_100)
        state.setdefault("world_notes", []).append(f"[Craft] {res.get('label', sub)} → {res.get('summary', '')}.")
        console.print(
            f"[green]Craft OK:[/green] {res.get('label', sub)} (+{int(res.get('time_min', 8) or 8)} min){extra}{xp_note}"
        )
        return True
    if up in ("STATUS", "INFO"):
        meta = state.get("meta", {}) or {}
        tr = state.get("trace", {}) or {}
        eco = state.get("economy", {}) or {}
        try:
            gigs_done = int(meta.get("daily_gigs_done", 0) or 0)
        except Exception as _omni_sw_113:
            log_swallowed_exception('engine/commands/misc.py:113', _omni_sw_113)
            gigs_done = 0
        try:
            hacks_attempted = int(meta.get("daily_hacks_attempted", 0) or 0)
        except Exception as _omni_sw_117:
            log_swallowed_exception('engine/commands/misc.py:117', _omni_sw_117)
            hacks_attempted = 0
        penalty = max(0, int(hacks_attempted) * 10)
        t = Table(title="STATUS", show_header=False)
        t.add_column("k", style="bold cyan", no_wrap=True)
        t.add_column("v")
        t.add_row("Location", str((state.get("player", {}) or {}).get("location", "-") or "-"))
        t.add_row("Clock", f"Day {int(meta.get('day', 1) or 1)} {fmt_clock(int(meta.get('time_min', 0) or 0))}")
        t.add_row("Trace", f"{int(tr.get('trace_pct', 0) or 0)}%")
        t.add_row("Cash/Bank", f"${int(eco.get('cash', 0) or 0)} / ${int(eco.get('bank', 0) or 0)}")
        t.add_row("Daily Gigs", f"{max(0, gigs_done)}/2")
        t.add_row("Neural Fatigue", f"{penalty}% fail penalty")
        console.print(t)
        return True
    return False

