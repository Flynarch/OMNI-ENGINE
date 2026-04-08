from __future__ import annotations

from engine.market import update_market

def update_economy(state: dict, action_ctx: dict) -> None:
    econ = state.setdefault("economy", {})
    meta = state.setdefault("meta", {})
    day, t = int(meta.get("day", 1)), int(meta.get("time_min", 0))
    last = int(econ.get("last_economic_cycle_day", 0))
    # Sekali per hari simulasi: jangan mengandalkan time_min==0 (timer bisa loncat 1439→D+1 01:01).
    if last < day:
        burn = int(econ.get("daily_burn", 0))
        cash = int(econ.get("cash", 0))
        bank = int(econ.get("bank", 0))
        if cash >= burn:
            cash -= burn
        else:
            bank -= (burn - cash)
            cash = 0
        econ["cash"] = cash
        if bank < 0:
            econ["debt"] = int(econ.get("debt", 0)) + abs(bank)
            bank = 0
        econ["bank"] = bank
        econ["last_economic_cycle_day"] = day
        # Market updates once per day (reactive economy layer).
        update_market(state)
        # Safehouse rent processing (optional system).
        try:
            from engine.safehouse import process_daily_rent

            process_daily_rent(state)
        except Exception:
            pass

    # FICO checks (event-driven from action context)
    fico = int(econ.get("fico", 600))
    payment = action_ctx.get("payment_event")
    if payment == "missed":
        fico -= 20
    elif payment == "late":
        fico -= 10
    elif payment == "on_time":
        fico += 5
    elif payment == "debt_cleared":
        fico += 15
    econ["fico"] = max(300, min(850, fico))

    # AML checks
    threshold = int(econ.get("aml_threshold", 10000))
    deposits = econ.setdefault("deposit_log", [])
    new_dep = action_ctx.get("cash_deposit")
    if isinstance(new_dep, (int, float)) and new_dep > 0:
        deposits.append({"day": day, "time_min": t, "amount": float(new_dep)})
        if float(new_dep) > threshold:
            econ["aml_status"] = "ACTIVE:Threshold"

    # Structuring: deposits in 72h window exceed threshold
    window_hours = 72
    now_abs_h = day * 24 + (t // 60)
    total = 0.0
    for d in deposits:
        abs_h = int(d.get("day", 0)) * 24 + (int(d.get("time_min", 0)) // 60)
        if now_abs_h - abs_h <= window_hours:
            total += float(d.get("amount", 0))
    if total > threshold:
        econ["aml_status"] = "ACTIVE:Structuring"
    elif not str(econ.get("aml_status", "CLEAR")).startswith("ACTIVE"):
        econ["aml_status"] = "CLEAR"
