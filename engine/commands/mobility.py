from __future__ import annotations

from typing import Any, Callable

from display.renderer import render_district_map_lite
from engine.core.error_taxonomy import log_swallowed_exception
from engine.systems.judicial import block_travel_if_incarcerated, ensure_judicial, fmt_judicial_brief
from engine.systems.vehicles import (
    VEHICLE_TYPES,
    buy_vehicle,
    list_owned_vehicles,
    refuel_vehicle,
    repair_vehicle,
    sell_vehicle,
    set_active_vehicle,
    steal_vehicle,
)
from engine.world.atlas import ensure_location_profile, fmt_profile_short
from engine.world.districts import describe_location, list_districts


def handle_mobility(state: dict[str, Any], cmd: str, *, console: Any, run_pipeline: Callable[[dict[str, Any], dict[str, Any]], dict[str, Any]]) -> bool:
    up = cmd.upper()
    if up == "MAP":
        try:
            render_district_map_lite(state)
        except Exception as _omni_sw_13:
            log_swallowed_exception('engine/commands/mobility.py:13', _omni_sw_13)
            console.print("[red]MAP error.[/red]")
        return True
    if up == "JUDICIAL" or up == "JUDICIAL STATUS":
        try:
            ensure_judicial(state)
            console.print(f"[bold]{fmt_judicial_brief(state)}[/bold]")
            j = state.get("judicial", {}) or {}
            if isinstance(j, dict) and str(j.get("phase", "free") or "") != "free":
                console.print(f"[dim]release_day={j.get('release_day','-')} seized_items={len(j.get('seized_bag_snapshot') or []) if isinstance(j.get('seized_bag_snapshot'), list) else 0}[/dim]")
        except Exception as _omni_sw_25:
            log_swallowed_exception('engine/commands/mobility.py:25', _omni_sw_25)
            console.print("[red]JUDICIAL error.[/red]")
        return True
    if up == "DISTRICTS" or up == "DISTRICT":
        try:
            loc = str((state.get("player", {}) or {}).get("location", "") or "").strip()
            if not loc:
                console.print("[yellow]DISTRICTS: No current location.[/yellow]")
                return True

            current_desc = describe_location(state)
            console.print(f"[bold]Current:[/bold] {current_desc}")
            console.print("")

            districts = list_districts(state, loc)
            console.print("[bold]DISTRICTS in this city:[/bold]")
            for d in districts:
                is_center = " [yellow](city center)[/yellow]" if d.get("is_center") else ""
                console.print(f"- {d.get('name','?')} ({d.get('id','?')}){is_center}")
                console.print(f"  {d.get('desc','-')}")
                services = d.get("services", [])
                console.print(f"  Services: {', '.join(services) if services else 'none'}")
                console.print(f"  Crime={d.get('crime_risk',3)}/5 Police={d.get('police_presence',3)}/5")
        except Exception as _omni_sw_50:
            log_swallowed_exception('engine/commands/mobility.py:50', _omni_sw_50)
            console.print("[red]DISTRICTS error.[/red]")
        return True
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
        except Exception as _omni_sw_70:
            log_swallowed_exception('engine/commands/mobility.py:70', _omni_sw_70)
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
        except Exception as _omni_sw_91:
            log_swallowed_exception('engine/commands/mobility.py:91', _omni_sw_91)
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
        except Exception as _omni_sw_108:
            log_swallowed_exception('engine/commands/mobility.py:108', _omni_sw_108)
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
        except Exception as _omni_sw_126:
            log_swallowed_exception('engine/commands/mobility.py:126', _omni_sw_126)
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
        except Exception as _omni_sw_144:
            log_swallowed_exception('engine/commands/mobility.py:144', _omni_sw_144)
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
        except Exception as _omni_sw_166:
            log_swallowed_exception('engine/commands/mobility.py:166', _omni_sw_166)
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
        except Exception as _omni_sw_187:
            log_swallowed_exception('engine/commands/mobility.py:187', _omni_sw_187)
            console.print("[red]USEVEHICLE error.[/red]")
        return True
    if up == "DRIVE" or up.startswith("DRIVE "):
        try:
            bt = block_travel_if_incarcerated(state)
            if bt:
                console.print(f"[yellow]{bt}[/yellow]")
                return True
            parts = cmd.split(maxsplit=1)
            if len(parts) < 2:
                console.print("[yellow]Usage: DRIVE <dest> [vehicle_type][/yellow]")
                return True
            tail = parts[1].strip()
            toks = tail.split()
            dest = tail
            vid = ""
            if len(toks) >= 2:
                cand = toks[-1].strip().lower()
                try:
                    if cand in VEHICLE_TYPES:
                        vid = cand
                        dest = " ".join(toks[:-1]).strip()
                except Exception as _omni_sw_214:
                    log_swallowed_exception('engine/commands/mobility.py:214', _omni_sw_214)
            ctx: dict[str, Any] = {
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
        except Exception as _omni_sw_228:
            log_swallowed_exception('engine/commands/mobility.py:228', _omni_sw_228)
            console.print("[red]DRIVE error.[/red]")
        return True
    if up == "TRAVELTO" or up.startswith("TRAVELTO "):
        try:
            bt = block_travel_if_incarcerated(state)
            if bt:
                console.print(f"[yellow]{bt}[/yellow]")
                return True
            parts = cmd.split(maxsplit=1)
            if len(parts) < 2:
                console.print("[yellow]Usage: TRAVELTO <district_id>[/yellow]")
                console.print("[dim]Use DISTRICTS to see available districts.[/dim]")
                console.print("[dim]W2-8: pergi ke kota lain lewat bahasa alami / travel — tiket & paspor (internasional).[/dim]")
                return True
            target = parts[1].strip().lower()
            ctx: dict[str, Any] = {
                "action_type": "travel",
                "domain": "evasion",
                "normalized_input": f"travelto {target}",
                "travel_mode": "district",
                "travel_target_district": target,
                "stakes": "low",
            }
            run_pipeline(state, ctx)
            result = ctx.get("travel_result", {})
            if not isinstance(result, dict) or not bool(result.get("ok")):
                msg = str((result.get("message") if isinstance(result, dict) else "") or "Error")
                console.print(f"[red]{msg}[/red]")
                return True
            console.print(f"[green]{result.get('message','')}[/green]")
            if result.get("encounter"):
                enc = result["encounter"]
                if enc.get("type") == "crime":
                    console.print(f"[yellow]Warning: Crime risk {enc.get('risk')}/5 in this area![/yellow]")
                elif enc.get("type") == "police":
                    console.print("[yellow]Warning: Heavy police presence in this area![/yellow]")
        except Exception as _omni_sw_267:
            log_swallowed_exception('engine/commands/mobility.py:267', _omni_sw_267)
            console.print("[red]TRAVELTO error.[/red]")
        return True
    if up == "WHEREAMI":
        p = state.get("player", {}) or {}
        world = state.get("world", {}) or {}
        locs = world.get("locations", {}) or {}
        known = sorted([str(k) for k in locs.keys()]) if isinstance(locs, dict) else []
        console.print("[bold]WHEREAMI[/bold]")
        console.print(f"- loc={p.get('location','-')} year={p.get('year','-')} seed={state.get('meta',{}).get('seed_pack','-')}")
        try:
            loc = str(p.get("location", "") or "").strip()
            if loc:
                prof = ensure_location_profile(state, loc)
                console.print(f"- profile: {fmt_profile_short(prof)}")
        except Exception as _omni_sw_284:
            log_swallowed_exception('engine/commands/mobility.py:284', _omni_sw_284)
        if known:
            console.print(f"- known_locations({len(known)}): " + ", ".join(known[:12]) + (" ..." if len(known) > 12 else ""))
        else:
            console.print("- known_locations: (none)")
        return True
    return False

