from __future__ import annotations

from dataclasses import dataclass
from typing import Any


def _get_int_from_env(env: dict[str, str], key: str, default: int) -> int:
    raw = str(env.get(key, "") or "").strip()
    if raw == "":
        return int(default)
    try:
        return int(float(raw))
    except Exception:
        return int(default)


def _get_float_from_env(env: dict[str, str], key: str, default: float) -> float:
    raw = str(env.get(key, "") or "").strip()
    if raw == "":
        return float(default)
    try:
        return float(raw)
    except Exception:
        return float(default)


def _as_dict(b: "Balance") -> dict[str, Any]:
    return {
        "disguise_default_duration_min": b.disguise_default_duration_min,
        "disguise_cost_cash": b.disguise_cost_cash,
        "disguise_trace_relief": b.disguise_trace_relief,
        "disguise_public_risk_add": b.disguise_public_risk_add,
        "disguise_risk_cap": b.disguise_risk_cap,
        "disguise_caught_trace_spike": b.disguise_caught_trace_spike,
        "safehouse_rent_deposit": b.safehouse_rent_deposit,
        "safehouse_rent_default_per_day": b.safehouse_rent_default_per_day,
        "safehouse_buy_price": b.safehouse_buy_price,
        "safehouse_upgrade_base_cost": b.safehouse_upgrade_base_cost,
        "safehouse_security_max": b.safehouse_security_max,
        "safehouse_lay_low_base_decay": b.safehouse_lay_low_base_decay,
        "safehouse_delinquent_report_day": b.safehouse_delinquent_report_day,
        "safehouse_landlord_report_trace_delta": b.safehouse_landlord_report_trace_delta,
        "hotel_night_base": b.hotel_night_base,
        "kos_night_base": b.kos_night_base,
        "suite_night_base": b.suite_night_base,
        "accommodation_trace_relief_base": b.accommodation_trace_relief_base,
        "travel_friction_police_sweep_min": b.travel_friction_police_sweep_min,
        "travel_friction_lockdown_min": b.travel_friction_lockdown_min,
        "weather_travel_storm_min": b.weather_travel_storm_min,
        "weather_travel_rain_min": b.weather_travel_rain_min,
        "weather_travel_fog_min": b.weather_travel_fog_min,
        "weather_travel_windy_min": b.weather_travel_windy_min,
        "weather_stealth_bonus_rain_fog": b.weather_stealth_bonus_rain_fog,
        "weather_stealth_bonus_storm": b.weather_stealth_bonus_storm,
        "skill_mod_per_level": b.skill_mod_per_level,
        "skill_mod_max_cap": b.skill_mod_max_cap,
        "lang_barrier_scale_pct": b.lang_barrier_scale_pct,
        "disguise_social_roll_bonus": b.disguise_social_roll_bonus,
        "disguise_stealth_roll_bonus": b.disguise_stealth_roll_bonus,
        "weather_roll_mod_scale_pct": b.weather_roll_mod_scale_pct,
        "npc_pursuit_days": b.npc_pursuit_days,
        "npc_surrender_morale": b.npc_surrender_morale,
        "npc_backup_trace_delta": b.npc_backup_trace_delta,
        "bio_bp_stable_min": b.bio_bp_stable_min,
        "bio_bp_low_min": b.bio_bp_low_min,
        "bio_bp_critical_min": b.bio_bp_critical_min,
        "bio_infection_mid_low": b.bio_infection_mid_low,
        "bio_infection_mid_high": b.bio_infection_mid_high,
        "bio_infection_recovery_penalty": b.bio_infection_recovery_penalty,
        "bio_sleep_debt_visual": b.bio_sleep_debt_visual,
        "bio_sleep_debt_audio": b.bio_sleep_debt_audio,
        "bio_sanity_visual": b.bio_sanity_visual,
        "bio_sanity_audio": b.bio_sanity_audio,
        "bio_sanity_psychotic": b.bio_sanity_psychotic,
        "bio_hygiene_hours_tax": b.bio_hygiene_hours_tax,
        "bio_rest_debt_clear_per_90min": b.bio_rest_debt_clear_per_90min,
    }


@dataclass(frozen=True)
class Balance:
    # Disguise
    disguise_default_duration_min: int = 8 * 60
    disguise_cost_cash: int = 40
    disguise_trace_relief: int = 4
    disguise_public_risk_add: int = 12
    disguise_risk_cap: int = 90
    disguise_caught_trace_spike: int = 18

    # Safehouse
    safehouse_rent_deposit: int = 50
    safehouse_rent_default_per_day: int = 25
    safehouse_buy_price: int = 600
    safehouse_upgrade_base_cost: int = 120
    safehouse_security_max: int = 5
    safehouse_lay_low_base_decay: int = 2  # + security_level
    safehouse_delinquent_report_day: int = 2
    safehouse_landlord_report_trace_delta: int = 3

    # Short-term accommodation (hotel/kos/suite) — distinct from safehouse.
    hotel_night_base: int = 80
    kos_night_base: int = 35
    suite_night_base: int = 220
    accommodation_trace_relief_base: int = 1  # trace decay on rest/sleep vs safehouse

    # Restrictions / travel friction (minutes)
    travel_friction_police_sweep_min: int = 12
    travel_friction_lockdown_min: int = 15

    # Weather
    weather_travel_storm_min: int = 25
    weather_travel_rain_min: int = 12
    weather_travel_fog_min: int = 10
    weather_travel_windy_min: int = 6
    weather_stealth_bonus_rain_fog: int = 6
    weather_stealth_bonus_storm: int = 4

    # Rolls / progression tuning (modifiers.py)
    skill_mod_per_level: int = 2  # bonus per skill level above 1, capped
    skill_mod_max_cap: int = 24
    lang_barrier_scale_pct: int = 100  # scale language penalty (100 = 1:1)
    disguise_social_roll_bonus: int = 4
    disguise_stealth_roll_bonus: int = 6
    weather_roll_mod_scale_pct: int = 100  # scale weather stealth modifier

    # NPC combat follow-up (npc_combat_ai.py)
    npc_pursuit_days: int = 2  # pursuit flag duration (game days)
    npc_surrender_morale: int = 22  # at or below → surrender
    npc_backup_trace_delta: int = 4  # extra trace when NPC calls backup

    # Bio (engine/bio.py) — blood, infection, sleep, sanity, hygiene
    bio_bp_stable_min: float = 4.25
    bio_bp_low_min: float = 3.5
    bio_bp_critical_min: float = 3.0
    bio_infection_mid_low: int = 20
    bio_infection_mid_high: int = 50
    bio_infection_recovery_penalty: int = 10
    bio_sleep_debt_visual: float = 42.0
    bio_sleep_debt_audio: float = 30.0
    bio_sanity_visual: int = 80
    bio_sanity_audio: int = 60
    bio_sanity_psychotic: int = 90
    bio_hygiene_hours_tax: int = 48
    bio_rest_debt_clear_per_90min: float = 4.0  # hours of sleep debt cleared per 90min rest


BALANCE = Balance()


def get_balance_snapshot(state: dict[str, Any]) -> dict[str, Any]:
    """Return the effective balance config snapshot for this state.

    - If `state.meta.balance` exists: use it (frozen per save, deterministic).
    - Else: read `BAL_*` overrides from environment and return a dict.
    """
    meta = state.get("meta", {}) or {}
    snap = meta.get("balance")
    if isinstance(snap, dict) and snap:
        return snap
    # Read from env on-demand; caller can freeze it into state.
    import os

    env = dict(os.environ)
    d = _as_dict(BALANCE)
    # Disguise
    d["disguise_default_duration_min"] = _get_int_from_env(env, "BAL_DISGUISE_DEFAULT_DURATION_MIN", d["disguise_default_duration_min"])
    d["disguise_cost_cash"] = _get_int_from_env(env, "BAL_DISGUISE_COST_CASH", d["disguise_cost_cash"])
    d["disguise_trace_relief"] = _get_int_from_env(env, "BAL_DISGUISE_TRACE_RELIEF", d["disguise_trace_relief"])
    d["disguise_public_risk_add"] = _get_int_from_env(env, "BAL_DISGUISE_PUBLIC_RISK_ADD", d["disguise_public_risk_add"])
    d["disguise_risk_cap"] = _get_int_from_env(env, "BAL_DISGUISE_RISK_CAP", d["disguise_risk_cap"])
    d["disguise_caught_trace_spike"] = _get_int_from_env(env, "BAL_DISGUISE_CAUGHT_TRACE_SPIKE", d["disguise_caught_trace_spike"])
    # Safehouse
    d["safehouse_rent_deposit"] = _get_int_from_env(env, "BAL_SAFEHOUSE_RENT_DEPOSIT", d["safehouse_rent_deposit"])
    d["safehouse_rent_default_per_day"] = _get_int_from_env(env, "BAL_SAFEHOUSE_RENT_PER_DAY", d["safehouse_rent_default_per_day"])
    d["safehouse_buy_price"] = _get_int_from_env(env, "BAL_SAFEHOUSE_BUY_PRICE", d["safehouse_buy_price"])
    d["safehouse_upgrade_base_cost"] = _get_int_from_env(env, "BAL_SAFEHOUSE_UPGRADE_BASE_COST", d["safehouse_upgrade_base_cost"])
    d["safehouse_security_max"] = _get_int_from_env(env, "BAL_SAFEHOUSE_SECURITY_MAX", d["safehouse_security_max"])
    d["safehouse_lay_low_base_decay"] = _get_int_from_env(env, "BAL_SAFEHOUSE_LAY_LOW_BASE_DECAY", d["safehouse_lay_low_base_decay"])
    d["safehouse_delinquent_report_day"] = _get_int_from_env(env, "BAL_SAFEHOUSE_DELINQUENT_REPORT_DAY", d["safehouse_delinquent_report_day"])
    d["safehouse_landlord_report_trace_delta"] = _get_int_from_env(env, "BAL_SAFEHOUSE_LANDLORD_REPORT_TRACE_DELTA", d["safehouse_landlord_report_trace_delta"])
    d["hotel_night_base"] = _get_int_from_env(env, "BAL_HOTEL_NIGHT_BASE", d["hotel_night_base"])
    d["kos_night_base"] = _get_int_from_env(env, "BAL_KOS_NIGHT_BASE", d["kos_night_base"])
    d["suite_night_base"] = _get_int_from_env(env, "BAL_SUITE_NIGHT_BASE", d["suite_night_base"])
    d["accommodation_trace_relief_base"] = _get_int_from_env(env, "BAL_ACCOMMODATION_TRACE_RELIEF_BASE", d["accommodation_trace_relief_base"])
    # Travel friction
    d["travel_friction_police_sweep_min"] = _get_int_from_env(env, "BAL_TRAVEL_FRICTION_POLICE_SWEEP_MIN", d["travel_friction_police_sweep_min"])
    d["travel_friction_lockdown_min"] = _get_int_from_env(env, "BAL_TRAVEL_FRICTION_LOCKDOWN_MIN", d["travel_friction_lockdown_min"])
    # Weather
    d["weather_travel_storm_min"] = _get_int_from_env(env, "BAL_WEATHER_TRAVEL_STORM_MIN", d["weather_travel_storm_min"])
    d["weather_travel_rain_min"] = _get_int_from_env(env, "BAL_WEATHER_TRAVEL_RAIN_MIN", d["weather_travel_rain_min"])
    d["weather_travel_fog_min"] = _get_int_from_env(env, "BAL_WEATHER_TRAVEL_FOG_MIN", d["weather_travel_fog_min"])
    d["weather_travel_windy_min"] = _get_int_from_env(env, "BAL_WEATHER_TRAVEL_WINDY_MIN", d["weather_travel_windy_min"])
    d["weather_stealth_bonus_rain_fog"] = _get_int_from_env(env, "BAL_WEATHER_STEALTH_BONUS_RAIN_FOG", d["weather_stealth_bonus_rain_fog"])
    d["weather_stealth_bonus_storm"] = _get_int_from_env(env, "BAL_WEATHER_STEALTH_BONUS_STORM", d["weather_stealth_bonus_storm"])
    d["skill_mod_per_level"] = _get_int_from_env(env, "BAL_SKILL_MOD_PER_LEVEL", d["skill_mod_per_level"])
    d["skill_mod_max_cap"] = _get_int_from_env(env, "BAL_SKILL_MOD_MAX_CAP", d["skill_mod_max_cap"])
    d["lang_barrier_scale_pct"] = _get_int_from_env(env, "BAL_LANG_BARRIER_SCALE_PCT", d["lang_barrier_scale_pct"])
    d["disguise_social_roll_bonus"] = _get_int_from_env(env, "BAL_DISGUISE_SOCIAL_ROLL_BONUS", d["disguise_social_roll_bonus"])
    d["disguise_stealth_roll_bonus"] = _get_int_from_env(env, "BAL_DISGUISE_STEALTH_ROLL_BONUS", d["disguise_stealth_roll_bonus"])
    d["weather_roll_mod_scale_pct"] = _get_int_from_env(env, "BAL_WEATHER_ROLL_MOD_SCALE_PCT", d["weather_roll_mod_scale_pct"])
    d["npc_pursuit_days"] = _get_int_from_env(env, "BAL_NPC_PURSUIT_DAYS", d["npc_pursuit_days"])
    d["npc_surrender_morale"] = _get_int_from_env(env, "BAL_NPC_SURRENDER_MORALE", d["npc_surrender_morale"])
    d["npc_backup_trace_delta"] = _get_int_from_env(env, "BAL_NPC_BACKUP_TRACE_DELTA", d["npc_backup_trace_delta"])
    d["bio_bp_stable_min"] = _get_float_from_env(env, "BAL_BIO_BP_STABLE_MIN", float(d["bio_bp_stable_min"]))
    d["bio_bp_low_min"] = _get_float_from_env(env, "BAL_BIO_BP_LOW_MIN", float(d["bio_bp_low_min"]))
    d["bio_bp_critical_min"] = _get_float_from_env(env, "BAL_BIO_BP_CRITICAL_MIN", float(d["bio_bp_critical_min"]))
    d["bio_infection_mid_low"] = _get_int_from_env(env, "BAL_BIO_INFECTION_MID_LOW", d["bio_infection_mid_low"])
    d["bio_infection_mid_high"] = _get_int_from_env(env, "BAL_BIO_INFECTION_MID_HIGH", d["bio_infection_mid_high"])
    d["bio_infection_recovery_penalty"] = _get_int_from_env(env, "BAL_BIO_INFECTION_RECOVERY_PENALTY", d["bio_infection_recovery_penalty"])
    d["bio_sleep_debt_visual"] = _get_float_from_env(env, "BAL_BIO_SLEEP_DEBT_VISUAL", float(d["bio_sleep_debt_visual"]))
    d["bio_sleep_debt_audio"] = _get_float_from_env(env, "BAL_BIO_SLEEP_DEBT_AUDIO", float(d["bio_sleep_debt_audio"]))
    d["bio_sanity_visual"] = _get_int_from_env(env, "BAL_BIO_SANITY_VISUAL", d["bio_sanity_visual"])
    d["bio_sanity_audio"] = _get_int_from_env(env, "BAL_BIO_SANITY_AUDIO", d["bio_sanity_audio"])
    d["bio_sanity_psychotic"] = _get_int_from_env(env, "BAL_BIO_SANITY_PSYCHOTIC", d["bio_sanity_psychotic"])
    d["bio_hygiene_hours_tax"] = _get_int_from_env(env, "BAL_BIO_HYGIENE_HOURS_TAX", d["bio_hygiene_hours_tax"])
    d["bio_rest_debt_clear_per_90min"] = _get_float_from_env(env, "BAL_BIO_REST_DEBT_CLEAR_PER_90MIN", float(d["bio_rest_debt_clear_per_90min"]))
    return d


def freeze_balance_into_state(state: dict[str, Any]) -> dict[str, Any]:
    """Freeze effective balance config into `state.meta.balance` if not present."""
    meta = state.setdefault("meta", {})
    if isinstance(meta.get("balance"), dict) and meta.get("balance"):
        return meta["balance"]
    snap = get_balance_snapshot(state)
    meta["balance"] = dict(snap)
    return meta["balance"]


