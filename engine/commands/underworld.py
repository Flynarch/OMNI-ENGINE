from __future__ import annotations

from typing import Any, Callable

from display.renderer import console, format_data_table
from engine.core.error_taxonomy import log_swallowed_exception
from engine.systems.black_market import (
    black_market_accessible,
    buy_black_market_item,
    generate_black_market_inventory,
)
from engine.systems import targeted_hacking
from engine.systems.jobs import execute_gig, generate_gigs


def handle_underworld(
    state: dict[str, Any],
    cmd: str,
    *,
    run_pipeline: Callable[[dict[str, Any], dict[str, Any]], dict[str, Any]],
    ui_err: Callable[[str, str], None],
) -> bool:
    up = cmd.upper()
    if up in ("BLACKMARKET", "DARKNET") or up == "MARKET BLACK" or up == "MARKET BM":
        try:
            if not black_market_accessible(state):
                ui_err("ACCESS DENIED", "CONNECTION REFUSED: Darknet node is offline.")
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
        except Exception as _omni_sw_36:
            log_swallowed_exception('engine/commands/underworld.py:36', _omni_sw_36)
            ui_err("ERROR", "BLACKMARKET error.")
        return True
    if up.startswith("BUY_DARK ") or up.startswith("BM_BUY "):
        parts = cmd.split(maxsplit=1)
        iid = parts[1].strip() if len(parts) >= 2 else ""
        if not iid:
            ui_err("ERROR", "Usage: BUY_DARK <item_id>.")
            return True
        try:
            r = buy_black_market_item(state, iid)
            if not bool(r.get("ok")):
                if r.get("reason") == "not_enough_cash":
                    ui_err("ERROR", "Not enough cash.")
                elif r.get("reason") == "connection_refused":
                    ui_err("ACCESS DENIED", "Darknet node offline.")
                elif r.get("reason") == "not_in_stock":
                    ui_err("ERROR", "Item not in stock today.")
                elif r.get("reason") == "reputation_gate":
                    ui_err("ACCESS DENIED", str(r.get("message") or "Vendor trust too low for this listing."))
                else:
                    ui_err("ERROR", f"BUY_DARK failed: {r.get('reason','error')}")
                return True
            console.print(f"[green]BUY_DARK OK[/green] {r.get('item_id')} price={r.get('price')}")
        except Exception as _omni_sw_62:
            log_swallowed_exception('engine/commands/underworld.py:62', _omni_sw_62)
            ui_err("ERROR", "BUY_DARK error.")
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
        except Exception as _omni_sw_90:
            log_swallowed_exception('engine/commands/underworld.py:90', _omni_sw_90)
            ui_err("ERROR", "GIGS error.")
        return True
    if up.startswith("HACK "):
        parts = cmd.split(maxsplit=1)
        tgt = parts[1].strip().lower() if len(parts) >= 2 else ""
        if not tgt:
            ui_err("ERROR", "Usage: HACK <atm|corp_server|police_archive>.")
            return True
        try:
            r = targeted_hacking.execute_hack(state, tgt)
            if not bool(r.get("ok")):
                ui_err("ERROR", f"HACK failed: {r.get('reason','error')}")
                return True
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
            except Exception as _omni_sw_118:
                log_swallowed_exception('engine/commands/underworld.py:118', _omni_sw_118)
            if bool(r.get("success")):
                console.print("[green]HACK success[/green]")
            else:
                console.print("[yellow]HACK detected[/yellow]")
        except Exception as _omni_sw_124:
            log_swallowed_exception('engine/commands/underworld.py:124', _omni_sw_124)
            ui_err("ERROR", "HACK error.")
        return True
    if up.startswith("WORK "):
        parts = cmd.split(maxsplit=1)
        gid = parts[1].strip() if len(parts) >= 2 else ""
        if not gid:
            ui_err("ERROR", "Usage: WORK <gig_id>.")
            return True
        try:
            r = execute_gig(state, gid)
            if not bool(r.get("ok")):
                if str(r.get("reason", "")) == "daily_gig_limit_reached":
                    ui_err("ERROR", "You are physically and mentally exhausted. Get some sleep before taking more gigs.")
                elif str(r.get("reason", "")) == "hunger_critical":
                    ui_err("ERROR", "You're starving and can't work. Eat first.")
                else:
                    ui_err("ERROR", f"WORK failed: {r.get('reason','error')}")
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
            except Exception as _omni_sw_161:
                log_swallowed_exception('engine/commands/underworld.py:161', _omni_sw_161)
            title = str((g or {}).get("title", gid) or gid)
            if succ:
                eco = state.setdefault("economy", {})
                try:
                    cash0 = int(eco.get("cash", 0) or 0)
                except Exception as _omni_sw_168:
                    log_swallowed_exception('engine/commands/underworld.py:168', _omni_sw_168)
                    cash0 = 0
                eco["cash"] = int(cash0 + payout)
                state.setdefault("world_notes", []).append(f"[Economy] Completed gig '{title}' and earned ${payout}.")
                console.print(f"[green]WORK success[/green] +${payout} ({tmin}m)")
            else:
                if trace_delta > 0:
                    tr = state.setdefault("trace", {})
                    try:
                        tp = int(tr.get("trace_pct", 0) or 0)
                    except Exception as _omni_sw_178:
                        log_swallowed_exception('engine/commands/underworld.py:178', _omni_sw_178)
                        tp = 0
                    tr["trace_pct"] = max(0, min(100, tp + int(trace_delta)))
                    state.setdefault("world_notes", []).append(
                        f"[Economy] Failed gig '{title}'. The botched job left a digital trail, increasing your Trace."
                    )
                else:
                    state.setdefault("world_notes", []).append(f"[Economy] Failed gig '{title}', wasting time with no payout.")
                console.print(f"[yellow]WORK failed[/yellow] (time spent {tmin}m)")
        except Exception as _omni_sw_187:
            log_swallowed_exception('engine/commands/underworld.py:187', _omni_sw_187)
            ui_err("ERROR", "WORK error.")
        return True
    return False

