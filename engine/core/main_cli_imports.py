"""Central import surface for ``main.py`` (REPL + ``handle_special`` + main loop).

Consolidates engine (and related) symbols that were previously imported inside
functions. ``main`` imports this module at load time so dependency resolution
follows PEP 8 and avoids false “lazy import = circular dependency” patterns.

This module must **not** import ``main`` (no cycles).
"""

from __future__ import annotations

from engine.commands.career import handle_career
from engine.commands.commerce import handle_commerce
from engine.commands.economy import handle_economy
from engine.commands.faction_report_cmd import handle_faction_report
from engine.commands.misc import handle_misc
from engine.commands.mobility import handle_mobility
from engine.commands.property_cmd import handle_property
from engine.commands.scene import handle_scene_commands
from engine.commands.session import handle_session
from engine.commands.smartphone_cmd import handle_smartphone
from engine.commands.social_intel import handle_social_intel
from engine.commands.underworld import handle_underworld
from engine.core.action_intent import (
    INTENT_MERGE_FIELD_KEYS,
    apply_intent_plan_precondition_failure,
    apply_parser_registry_anchor_after_llm,
    apply_step_to_action_ctx,
    merge_intent_into_action_ctx,
    select_best_step,
    strip_llm_intent_overlay_on_registry_hint_mismatch,
)
from engine.core.action_registry import registry_hint_alignment
from engine.core.integration_hooks import apply_cross_system_policies, post_turn_integration
from engine.core.intent_plan_runtime import apply_pending_runtime_step, sync_plan_runtime_start
from engine.core.language import communication_quality, player_language_proficiency
from engine.core.reload import try_reload
from engine.core.security_intent import sanitize_player_command_text, security_flags_for_intent_input
from engine.core.telemetry_contract import merge_telemetry_turn_last, snapshot_turn_telemetry
from engine.npc.npc_targeting import apply_npc_targeting
from engine.player.banking import bank_aml_snapshot, bank_deposit, bank_withdraw
from engine.player.language_learning import learn_language
from engine.social.informant_ops import burn_informant, pay_informant
from engine.social.informants import seed_informant_roster
from engine.systems.accommodation import (
    get_stay_here,
    maybe_trigger_stay_raid,
    nightly_rate,
    normalize_stay_kind,
    stay_checkin,
    stay_help_aliases,
    stay_kind_label,
    try_auto_stay_from_intent,
)
from engine.systems.black_market import (
    black_market_accessible,
    buy_black_market_item,
    generate_black_market_inventory,
)
from engine.systems.disguise import activate_disguise, deactivate_disguise
from engine.systems.jobs import execute_gig, generate_gigs
from engine.systems.safehouse import buy_here, ensure_safehouse_here, rent_here, upgrade_security
from engine.systems.safehouse_raid import set_pending_raid_response
from engine.systems.safehouse_stash import (
    stash_put_ammo,
    stash_put_from_bag,
    stash_take_ammo,
    stash_take_to_bag,
)
from engine.systems.scenes import advance_scene
from engine.systems.targeted_hacking import execute_hack
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
from engine.world.atlas import (
    default_city_for_country,
    ensure_country_profile,
    ensure_location_profile,
    is_known_place,
    list_known_cities,
    list_known_countries,
    normalize_country_name,
    resolve_place,
)
from engine.world.districts import describe_location, list_districts, travel_within_city
from engine.world.timers import update_timers
from engine.world.weather import ensure_weather
