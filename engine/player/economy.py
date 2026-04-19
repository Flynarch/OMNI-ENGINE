from __future__ import annotations

from engine.core.error_taxonomy import log_swallowed_exception
from engine.core.integration_hooks import record_economy_ledger_line
from engine.npc.relationship import get_top_relationships
from engine.player.market import update_market
from engine.systems.accommodation import process_accommodation_daily
from engine.systems.occupation import accrue_career_salary_and_decay
from engine.systems.property import process_property_daily_economy
from engine.systems.safehouse import process_daily_rent
from engine.systems.smartphone import maybe_police_track_phone_daily

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
        try:
            record_economy_ledger_line(state, "daily_burn", int(-burn), "housing/living costs")
        except Exception as _omni_sw_30:
            log_swallowed_exception('engine/player/economy.py:30', _omni_sw_30)
        # W2-9: career payroll + career-break rep decay (once per sim day).
        try:
            accrue_career_salary_and_decay(state)
        except Exception as _omni_sw_37:
            log_swallowed_exception('engine/player/economy.py:37', _omni_sw_37)
        # Relationship passive: business partners can generate a small deterministic daily income.
        try:
            rels = get_top_relationships(state, limit=12)
            partner_income = 0
            for _nm, rel in rels:
                if str(rel.get("type", "") or "").lower() == "business_partner":
                    st = int(rel.get("strength", 50) or 50)
                    partner_income += max(8, min(80, 8 + st // 2))
            if partner_income > 0:
                econ["cash"] = int(int(econ.get("cash", 0) or 0) + int(partner_income))
                state.setdefault("world_notes", []).append(f"[Economy] Business partner income +${int(partner_income)}.")
        except Exception as _omni_sw_52:
            log_swallowed_exception('engine/player/economy.py:52', _omni_sw_52)
        # W2-10: property maintenance/rent + small-business passive income (Python-only; not action_ctx).
        try:
            process_property_daily_economy(state)
        except Exception as _omni_sw_59:
            log_swallowed_exception('engine/player/economy.py:59', _omni_sw_59)
        # W2-11: powered phone + high trace → small daily trace pressure.
        try:
            maybe_police_track_phone_daily(state)
        except Exception as _omni_sw_66:
            log_swallowed_exception('engine/player/economy.py:66', _omni_sw_66)
        # Market updates once per day (reactive economy layer).
        update_market(state)
        # Safehouse rent processing (optional system).
        try:
            process_daily_rent(state)
        except Exception as _omni_sw_75:
            log_swallowed_exception('engine/player/economy.py:75', _omni_sw_75)
        try:
            process_accommodation_daily(state)
        except Exception as _omni_sw_81:
            log_swallowed_exception('engine/player/economy.py:81', _omni_sw_81)
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
