from __future__ import annotations

from typing import Any, Callable

from display.renderer import console
from engine.core.error_taxonomy import log_swallowed_exception
from engine.player.banking import bank_aml_snapshot, bank_deposit, bank_withdraw
from engine.systems.accommodation import (
    get_stay_here,
    maybe_trigger_stay_raid,
    nightly_rate,
    normalize_stay_kind,
    stay_checkin,
    stay_help_aliases,
    stay_kind_label,
)


def handle_economy(
    state: dict[str, Any],
    cmd: str,
    *,
    run_pipeline: Callable[[dict[str, Any], dict[str, Any]], dict[str, Any]],
) -> bool:
    up = cmd.upper()
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
                except Exception as _omni_sw_39:
                    log_swallowed_exception('engine/commands/economy.py:39', _omni_sw_39)
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
                except Exception as _omni_sw_58:
                    log_swallowed_exception('engine/commands/economy.py:58', _omni_sw_58)
                console.print(f"[green]BANK deposit OK[/green] {amt} cash→bank (AML log updated)")
                return True
            if sub == "withdraw":
                if len(parts) < 3:
                    console.print("[yellow]Usage: BANK withdraw <amount>[/yellow]")
                    return True
                try:
                    amt = int(parts[2].strip())
                except Exception as _omni_sw_68:
                    log_swallowed_exception('engine/commands/economy.py:68', _omni_sw_68)
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
                except Exception as _omni_sw_86:
                    log_swallowed_exception('engine/commands/economy.py:86', _omni_sw_86)
                console.print(f"[green]BANK withdraw OK[/green] {amt} bank→cash")
                return True
            console.print("[yellow]Pakai: BANK status|deposit <n>|withdraw <n>[/yellow]")
        except Exception as _omni_sw_91:
            log_swallowed_exception('engine/commands/economy.py:91', _omni_sw_91)
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
                except Exception as _omni_sw_130:
                    log_swallowed_exception('engine/commands/economy.py:130', _omni_sw_130)
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
                except Exception as _omni_sw_155:
                    log_swallowed_exception('engine/commands/economy.py:155', _omni_sw_155)
                tier_name = stay_kind_label(str(res.get("kind") or nk), short=True)
                console.print(
                    f"[green]STAY OK[/green] {tier_name} +{res.get('nights_added')}n total_nights={res.get('nights_remaining')} paid={res.get('paid')} cash={res.get('cash_after')}"
                )
                return True
            console.print("[yellow]Pakai: STAY status|hotel <n>|boarding <n>|suite <n>[/yellow]")
            console.print(f"[dim]{stay_help_aliases()}[/dim]")
        except Exception as _omni_sw_164:
            log_swallowed_exception('engine/commands/economy.py:164', _omni_sw_164)
            console.print("[red]STAY error.[/red]")
        return True
    return False

