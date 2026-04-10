"""Vehicle system for travel, chase, and escape mechanics.

This module provides:
- Vehicle ownership and management
- Travel speed modifiers
- Fuel consumption
- Chase and escape mechanics
- Vehicle-based crimes
"""
from __future__ import annotations

import hashlib
from typing import Any


def _h32(*parts: Any) -> int:
    """Deterministic hash."""
    s = "|".join(str(p) for p in parts)
    h = hashlib.md5(s.encode("utf-8", errors="ignore")).hexdigest()
    return int(h[:8], 16)


def _clamp(v: int, lo: int, hi: int) -> int:
    return max(lo, min(hi, int(v)))


def _set_trace_pct(state: dict[str, Any], pct: int) -> None:
    tr = state.setdefault("trace", {})
    p = _clamp(int(pct), 0, 100)
    tr["trace_pct"] = p
    tr["trace_status"] = "Ghost" if p <= 25 else "Flagged" if p <= 50 else "Investigated" if p <= 75 else "Manhunt"
    try:
        from engine.core.factions import sync_faction_statuses_from_trace

        sync_faction_statuses_from_trace(state)
    except Exception:
        pass


# Vehicle definitions
VEHICLE_TYPES = {
    "bicycle": {
        "name": "Bicycle",
        "speed": 15,  # km/h
        "fuel_cost_per_km": 0,  # No fuel
        "maintenance_cost": 5,  # Per day
        "capacity": 1,
        "crime_risk": 0,
        "police_interest": 0,
        "stealth": 10,
        "desc": "Quiet, no fuel cost, but slow and visible.",
    },
    "motorcycle": {
        "name": "Motorcycle",
        "speed": 60,
        "fuel_cost_per_km": 0.5,
        "maintenance_cost": 10,
        "capacity": 2,
        "crime_risk": 3,
        "police_interest": 3,
        "stealth": 5,
        "desc": "Fast and agile. Good for quick escapes.",
    },
    "car_standard": {
        "name": "Standard Car",
        "speed": 80,
        "fuel_cost_per_km": 1.0,
        "maintenance_cost": 20,
        "capacity": 4,
        "crime_risk": 2,
        "police_interest": 2,
        "stealth": 3,
        "desc": "Balanced speed and capacity. Common.",
    },
    "car_sports": {
        "name": "Sports Car",
        "speed": 150,
        "fuel_cost_per_km": 2.0,
        "maintenance_cost": 50,
        "capacity": 2,
        "crime_risk": 5,
        "police_interest": 5,
        "stealth": 1,
        "desc": "Extremely fast. Very noticeable.",
    },
    "car_van": {
        "name": "Van",
        "speed": 70,
        "fuel_cost_per_km": 1.5,
        "maintenance_cost": 25,
        "capacity": 8,
        "crime_risk": 4,
        "police_interest": 4,
        "stealth": 4,
        "desc": "Good cargo space. Can hide inside.",
    },
    "taxi": {
        "name": "Taxi",
        "speed": 80,
        "fuel_cost_per_km": 0,  # Player doesn't pay
        "maintenance_cost": 0,
        "capacity": 4,
        "crime_risk": 1,
        "police_interest": 1,
        "stealth": 2,
        "desc": "Cheap transport. Driver may remember you.",
    },
    "boat_small": {
        "name": "Small Boat",
        "speed": 30,
        "fuel_cost_per_km": 1.5,
        "maintenance_cost": 30,
        "capacity": 6,
        "crime_risk": 4,
        "police_interest": 3,
        "stealth": 6,
        "desc": "Good for water routes and smuggling.",
    },
    "boat_speed": {
        "name": "Speedboat",
        "speed": 80,
        "fuel_cost_per_km": 3.0,
        "maintenance_cost": 60,
        "capacity": 4,
        "crime_risk": 6,
        "police_interest": 6,
        "stealth": 2,
        "desc": "Very fast on water. Expensive.",
    },
    "helicopter": {
        "name": "Helicopter",
        "speed": 200,
        "fuel_cost_per_km": 10.0,
        "maintenance_cost": 200,
        "capacity": 6,
        "crime_risk": 10,
        "police_interest": 10,
        "stealth": 0,
        "desc": "Extremely fast. Impossible to hide.",
    },
}


def ensure_vehicle_state(state: dict[str, Any]) -> dict[str, Any]:
    """Ensure vehicle state exists."""
    inv = state.setdefault("inventory", {})
    vstate = inv.setdefault("vehicles", {})
    if not isinstance(vstate, dict):
        vstate = {}
        inv["vehicles"] = vstate
    inv.setdefault("active_vehicle_id", "")
    return vstate


def set_active_vehicle(state: dict[str, Any], vehicle_id: str | None) -> dict[str, Any]:
    """Select a vehicle to be used for future travel (if available)."""
    inv = state.setdefault("inventory", {})
    vstate = ensure_vehicle_state(state)
    vid = str(vehicle_id or "").strip().lower()
    if not vid:
        inv["active_vehicle_id"] = ""
        return {"ok": True, "active_vehicle_id": ""}
    if vid not in vstate:
        return {"ok": False, "reason": "not_owned"}
    inv["active_vehicle_id"] = vid
    return {"ok": True, "active_vehicle_id": vid}


def _travel_minutes_by_speed(base_minutes: int, *, speed: int) -> int:
    """Convert walking/transit minutes into vehicle minutes using a baseline speed."""
    base = max(1, int(base_minutes))
    sp = max(5, int(speed or 0))
    baseline_speed = 40  # abstract baseline for default travel_minutes
    mins = int(round(base * (baseline_speed / float(sp))))
    return max(4, min(600, mins))


def apply_vehicle_to_travel(state: dict[str, Any], action_ctx: dict[str, Any]) -> None:
    """Hook: when action_type==travel, optionally apply vehicle modifiers (time/fuel/condition/trace)."""
    if str(action_ctx.get("action_type", "") or "") != "travel":
        return
    inv = state.get("inventory", {}) or {}
    if not isinstance(inv, dict):
        return
    vstate = ensure_vehicle_state(state)
    if not isinstance(vstate, dict) or not vstate:
        return

    # Vehicle selection priority: explicit -> active -> none.
    vid = str(action_ctx.get("vehicle_id", "") or "").strip().lower()
    if not vid:
        vid = str(inv.get("active_vehicle_id", "") or "").strip().lower()
    if not vid:
        return
    if vid not in vstate:
        return

    vdata = vstate.get(vid) if isinstance(vstate.get(vid), dict) else None
    vtype = VEHICLE_TYPES.get(vid, {})
    if not isinstance(vdata, dict) or not isinstance(vtype, dict) or not vtype:
        return

    # Skip if broken.
    cond = int(vdata.get("condition", 0) or 0)
    if cond <= 0:
        state.setdefault("world_notes", []).append(f"[Vehicle] Travel fallback: {vid} broken.")
        return

    # Compute minutes.
    base_minutes = int(action_ctx.get("travel_minutes", 30) or 30)
    new_minutes = _travel_minutes_by_speed(base_minutes, speed=int(vtype.get("speed", 40) or 40))

    # Fuel proxy based on base distance.
    # We keep it simple: minutes roughly represent a few to tens of km.
    distance_km = max(1.0, float(base_minutes) * 0.8)
    if not consume_fuel(state, vid, distance_km):
        state.setdefault("world_notes", []).append(f"[Vehicle] Not enough fuel for {vid}; traveled without vehicle.")
        return

    # Apply updated travel minutes; timers will still add weather/restrictions on top.
    action_ctx["travel_minutes"] = new_minutes
    action_ctx.setdefault("time_breakdown", []).insert(0, {"label": f"vehicle:{vid}", "minutes": int(new_minutes)})
    action_ctx["vehicle_used"] = vid

    # Wear and tear.
    degrade_vehicle(state, vid, 1)

    # District/city context increases roadblock checks.
    police_presence = 0
    try:
        p = state.get("player", {}) or {}
        loc = str(p.get("location", "") or "").strip().lower()
        did = str(p.get("district", "") or "").strip().lower()
        if loc and did:
            from engine.world.districts import get_district

            d = get_district(state, loc, did)
            if isinstance(d, dict):
                police_presence = int(d.get("police_presence", 0) or 0)
    except Exception:
        police_presence = 0

    # Encounter / attention: stolen + high police_interest + district police presence bumps trace deterministically.
    try:
        pi = int(vtype.get("police_interest", 0) or 0)
    except Exception:
        pi = 0
    if bool(vdata.get("stolen")) or pi >= 4 or police_presence >= 4:
        meta = state.get("meta", {}) or {}
        day = int(meta.get("day", 1) or 1)
        turn = int(meta.get("turn", 0) or 0)
        r = _h32(day, turn, vid, "road_check") % 100
        chance = min(80, 10 + pi * 8 + (20 if bool(vdata.get("stolen")) else 0) + police_presence * 6)
        if r < chance:
            tr = state.setdefault("trace", {})
            cur = int(tr.get("trace_pct", 0) or 0)
            bump = 6 + (10 if bool(vdata.get("stolen")) else 0) + (2 if police_presence >= 4 else 0)
            _set_trace_pct(state, cur + bump)
            state.setdefault("world_notes", []).append(
                f"[Vehicle] Road check while using {vid} (trace +{bump}, district_police={police_presence})."
            )


def buy_vehicle(state: dict[str, Any], vehicle_id: str) -> dict[str, Any]:
    """Purchase a vehicle."""
    vtype = VEHICLE_TYPES.get(vehicle_id)
    if not vtype:
        return {"ok": False, "reason": "unknown_vehicle", "message": f"Unknown vehicle: {vehicle_id}"}
    
    vstate = ensure_vehicle_state(state)
    
    # Check if player already owns this type
    if vehicle_id in vstate:
        return {"ok": False, "reason": "already_owned", "message": f"You already own a {vtype['name']}."}
    
    # Check cash
    eco = state.get("economy", {}) or {}
    cash = int(eco.get("cash", 0) or 0)
    
    # Base prices
    base_prices = {
        "bicycle": 50,
        "motorcycle": 500,
        "car_standard": 2000,
        "car_sports": 10000,
        "car_van": 3000,
        "taxi": 0,  # Rent only
        "boat_small": 5000,
        "boat_speed": 15000,
        "helicopter": 100000,
    }
    
    price = base_prices.get(vehicle_id, 1000)
    if cash < price:
        return {"ok": False, "reason": "not_enough_cash", "need": price, "cash": cash}
    
    # Deduct cash
    eco["cash"] = cash - price
    
    # Add vehicle
    meta = state.get("meta", {}) or {}
    day = int(meta.get("day", 1) or 1)
    
    vstate[vehicle_id] = {
        "type": vehicle_id,
        "name": vtype["name"],
        "fuel": 100,  # Full tank
        "condition": 100,
        "owned_since_day": day,
        "stolen": False,
    }
    
    state.setdefault("world_notes", []).append(f"[Vehicle] Purchased {vtype['name']}.")
    
    return {
        "ok": True,
        "vehicle": vehicle_id,
        "name": vtype["name"],
        "price": price,
        "cash_remaining": eco["cash"],
    }


def sell_vehicle(state: dict[str, Any], vehicle_id: str) -> dict[str, Any]:
    """Sell a vehicle."""
    vstate = ensure_vehicle_state(state)
    
    if vehicle_id not in vstate:
        return {"ok": False, "reason": "not_owned"}
    
    vtype = VEHICLE_TYPES.get(vehicle_id, {})
    vdata = vstate[vehicle_id]
    
    # Sell for 50% of original value
    base_prices = {
        "bicycle": 50, "motorcycle": 500, "car_standard": 2000,
        "car_sports": 10000, "car_van": 3000, "taxi": 0,
        "boat_small": 5000, "boat_speed": 15000, "helicopter": 100000,
    }
    original = base_prices.get(vehicle_id, 1000)
    sell_price = int(original * 0.5)
    
    # Reduce for poor condition
    condition = int(vdata.get("condition", 100) or 100)
    sell_price = int(sell_price * (condition / 100))
    
    eco = state.get("economy", {}) or {}
    eco["cash"] = int(eco.get("cash", 0) or 0) + sell_price
    
    del vstate[vehicle_id]
    state.setdefault("world_notes", []).append(f"[Vehicle] Sold {vtype.get('name', vehicle_id)} for {sell_price}.")
    
    return {"ok": True, "sold": vehicle_id, "price": sell_price, "cash": eco["cash"]}


def refuel_vehicle(state: dict[str, Any], vehicle_id: str, amount: int | None = None) -> dict[str, Any]:
    """Refuel a vehicle."""
    vstate = ensure_vehicle_state(state)
    
    if vehicle_id not in vstate:
        return {"ok": False, "reason": "not_owned"}
    
    vdata = vstate[vehicle_id]
    vtype = VEHICLE_TYPES.get(vehicle_id, {})
    
    current_fuel = int(vdata.get("fuel", 0) or 0)
    if amount is None:
        amount = 100 - current_fuel  # Fill to full
    
    amount = _clamp(amount, 0, 100 - current_fuel)
    
    # Calculate fuel cost
    fuel_cost_per_unit = vtype.get("fuel_cost_per_km", 1.0)
    cost = int(amount * fuel_cost_per_unit * 2)  # Scale for game economy
    
    eco = state.get("economy", {}) or {}
    cash = int(eco.get("cash", 0) or 0)
    
    if cash < cost:
        return {"ok": False, "reason": "not_enough_cash", "need": cost, "cash": cash}
    
    eco["cash"] = cash - cost
    vdata["fuel"] = current_fuel + amount
    
    return {
        "ok": True,
        "vehicle": vehicle_id,
        "fuel_added": amount,
        "fuel_now": vdata["fuel"],
        "cost": cost,
        "cash_remaining": eco["cash"],
    }


def get_vehicle_stats(state: dict[str, Any], vehicle_id: str) -> dict[str, Any]:
    """Get vehicle statistics."""
    vstate = ensure_vehicle_state(state)
    
    if vehicle_id not in vstate:
        return {"owned": False}
    
    vdata = vstate[vehicle_id]
    vtype = VEHICLE_TYPES.get(vehicle_id, {})
    
    return {
        "owned": True,
        "type": vehicle_id,
        "name": vtype.get("name", vehicle_id),
        "fuel": vdata.get("fuel", 0),
        "condition": vdata.get("condition", 100),
        "speed": vtype.get("speed", 80),
        "stolen": vdata.get("stolen", False),
        "owned_since": vdata.get("owned_since_day", 0),
    }


def list_owned_vehicles(state: dict[str, Any]) -> list[dict[str, Any]]:
    """List all owned vehicles."""
    vstate = ensure_vehicle_state(state)
    result = []
    for vid in vstate:
        result.append(get_vehicle_stats(state, vid))
    return result


def consume_fuel(state: dict[str, Any], vehicle_id: str, distance_km: float) -> bool:
    """Consume fuel for a journey. Returns False if not enough fuel."""
    vstate = ensure_vehicle_state(state)
    
    if vehicle_id not in vstate:
        return False
    
    vdata = vstate[vehicle_id]
    vtype = VEHICLE_TYPES.get(vehicle_id, {})
    
    fuel_per_km = vtype.get("fuel_cost_per_km", 1.0)
    fuel_needed = int(distance_km * fuel_per_km)
    
    current_fuel = int(vdata.get("fuel", 0) or 0)
    if current_fuel < fuel_needed:
        return False
    
    vdata["fuel"] = current_fuel - fuel_needed
    return True


def degrade_vehicle(state: dict[str, Any], vehicle_id: str, damage: int) -> None:
    """Degrade vehicle condition."""
    vstate = ensure_vehicle_state(state)
    
    if vehicle_id not in vstate:
        return
    
    vdata = vstate[vehicle_id]
    current = int(vdata.get("condition", 100) or 100)
    new_condition = _clamp(current - damage, 0, 100)
    vdata["condition"] = new_condition
    
    # Record breakdown
    if new_condition <= 0:
        state.setdefault("world_notes", []).append(f"[Vehicle] {VEHICLE_TYPES.get(vehicle_id, {}).get('name', vehicle_id)} has broken down!")
    elif new_condition <= 25:
        state.setdefault("world_notes", []).append(f"[Vehicle] {VEHICLE_TYPES.get(vehicle_id, {}).get('name', vehicle_id)} needs repair!")


def repair_vehicle(state: dict[str, Any], vehicle_id: str, amount: int | None = None) -> dict[str, Any]:
    """Repair vehicle condition."""
    vstate = ensure_vehicle_state(state)
    
    if vehicle_id not in vstate:
        return {"ok": False, "reason": "not_owned"}
    
    vdata = vstate[vehicle_id]
    vtype = VEHICLE_TYPES.get(vehicle_id, {})
    
    current = int(vdata.get("condition", 100) or 100)
    if amount is None:
        amount = 100 - current
    
    amount = _clamp(amount, 0, 100 - current)
    
    # Repair cost
    base_prices = {
        "bicycle": 5, "motorcycle": 50, "car_standard": 200,
        "car_sports": 1000, "car_van": 300, "taxi": 0,
        "boat_small": 500, "boat_speed": 1500, "helicopter": 10000,
    }
    base_cost = base_prices.get(vehicle_id, 100)
    cost = int((amount / 100) * base_cost * 2)
    
    eco = state.get("economy", {}) or {}
    cash = int(eco.get("cash", 0) or 0)
    
    if cash < cost:
        return {"ok": False, "reason": "not_enough_cash", "need": cost, "cash": cash}
    
    eco["cash"] = cash - cost
    vdata["condition"] = current + amount
    
    return {
        "ok": True,
        "vehicle": vehicle_id,
        "repaired": amount,
        "condition_now": vdata["condition"],
        "cost": cost,
    }


def travel_with_vehicle(state: dict[str, Any], vehicle_id: str, distance_km: float) -> dict[str, Any]:
    """Travel using a vehicle."""
    vstate = ensure_vehicle_state(state)
    
    if vehicle_id not in vstate:
        return {"ok": False, "reason": "not_owned"}
    
    vdata = vstate[vehicle_id]
    vtype = VEHICLE_TYPES.get(vehicle_id, {})
    
    # Check fuel
    if not consume_fuel(state, vehicle_id, distance_km):
        return {"ok": False, "reason": "no_fuel", "message": "Not enough fuel!"}
    
    # Check condition
    condition = int(vdata.get("condition", 100) or 100)
    if condition < 20:
        # Chance of breakdown
        r = _h32(state.get("meta", {}).get("turn", 0), "breakdown")
        if r % 100 < 30:
            degrade_vehicle(state, vehicle_id, 20)
            return {
                "ok": False,
                "reason": "breakdown",
                "message": "Vehicle broke down!",
                "breakdown_chance": True,
            }
    
    # Calculate travel time
    speed = vtype.get("speed", 80)
    travel_time_min = int((distance_km / speed) * 60)
    
    # Apply time
    from engine.world.timers import update_timers
    update_timers(state, {
        "action_type": "travel",
        "domain": "evasion",
        "normalized_input": f"travel by {vtype.get('name', vehicle_id)}",
        "instant_minutes": travel_time_min,
        "stakes": "low",
    })
    
    # Stealth modifier - faster vehicles more visible
    stealth = vtype.get("stealth", 5)
    crime_risk = vtype.get("crime_risk", 2)
    police_interest = vtype.get("police_interest", 2)
    
    # Roll for encounter
    meta = state.get("meta", {}) or {}
    turn = int(meta.get("turn", 0) or 0)
    day = int(meta.get("day", 1) or 1)
    
    encounter_chance = police_interest * 5
    r = _h32(day, turn, vehicle_id, "encounter")
    
    encounter = None
    if r % 100 < encounter_chance:
        encounter = {"type": "police_check", "vehicle": vehicle_id}
        # Stolen vehicle = serious trouble
        if vdata.get("stolen"):
            tr = state.setdefault("trace", {})
            current_trace = int(tr.get("trace_pct", 0) or 0)
            _set_trace_pct(state, current_trace + 15)
            encounter["stolen_vehicle"] = True
    
    # Condition degrades with use
    degrade_vehicle(state, vehicle_id, 1)
    
    return {
        "ok": True,
        "vehicle": vehicle_id,
        "distance": distance_km,
        "time_minutes": travel_time_min,
        "fuel_used": vtype.get("fuel_cost_per_km", 1.0) * distance_km,
        "condition": vdata.get("condition", 100),
        "encounter": encounter,
    }


def chase_attempt(state: dict[str, Any], pursuer_vehicle: str | None, target_vehicle: str | None) -> dict[str, Any]:
    """Attempt to chase or escape from another vehicle."""
    meta = state.get("meta", {}) or {}
    turn = int(meta.get("turn", 0) or 0)
    day = int(meta.get("day", 1) or 1)
    
    # Determine speeds
    pursuer_speed = 0
    target_speed = 0
    
    if pursuer_vehicle:
        vtype = VEHICLE_TYPES.get(pursuer_vehicle, {})
        pursuer_speed = vtype.get("speed", 80)
        # Condition affects speed
        vstate = ensure_vehicle_state(state)
        if pursuer_vehicle in vstate:
            cond = int(vstate[pursuer_vehicle].get("condition", 100) or 100)
            pursuer_speed = int(pursuer_speed * (cond / 100))
    
    if target_vehicle:
        vtype = VEHICLE_TYPES.get(target_vehicle, {})
        target_speed = vtype.get("speed", 80)
        vstate = ensure_vehicle_state(state)
        if target_vehicle in vstate:
            cond = int(vstate[target_vehicle].get("condition", 100) or 100)
            target_speed = int(target_speed * (cond / 100))
    
    # Speed difference determines base chance
    if pursuer_speed and target_speed:
        speed_diff = pursuer_speed - target_speed
        base_escape_chance = 50 + (speed_diff / 2)  # Faster = better escape
    elif pursuer_speed:
        base_escape_chance = 70  # Chasing empty vehicle
    elif target_speed:
        base_escape_chance = 30  # Being chased by faster vehicle
    else:
        base_escape_chance = 50
    
    # Environmental modifiers
    from engine.world.weather import ensure_weather
    loc = str(state.get("player", {}).get("location", "") or "").strip().lower()
    weather = ensure_weather(state, loc, day)
    weather_kind = str(weather.get("kind", "clear") or "clear")
    
    if weather_kind in ("rain", "storm"):
        base_escape_chance -= 15  # Worse conditions
    
    # Stealth modifiers
    if pursuer_vehicle:
        pursuer_stealth = VEHICLE_TYPES.get(pursuer_vehicle, {}).get("stealth", 5)
        base_escape_chance -= pursuer_stealth
    
    base_escape_chance = _clamp(base_escape_chance, 5, 95)
    
    # Roll
    r = _h32(day, turn, pursuer_vehicle or "foot", target_vehicle or "foot", "chase")
    roll = r % 100
    
    escape_success = roll < base_escape_chance
    
    return {
        "escape_success": escape_success,
        "pursuer_speed": pursuer_speed,
        "target_speed": target_speed,
        "roll": roll,
        "threshold": base_escape_chance,
        "weather_modifier": weather_kind,
    }


def steal_vehicle(state: dict[str, Any], vehicle_id: str) -> dict[str, Any]:
    """Attempt to steal a vehicle."""
    meta = state.get("meta", {}) or {}
    turn = int(meta.get("turn", 0) or 0)
    day = int(meta.get("day", 1) or 1)
    
    vtype = VEHICLE_TYPES.get(vehicle_id)
    if not vtype:
        return {"ok": False, "reason": "unknown_vehicle"}
    
    # Base difficulty based on vehicle type
    base_difficulty = 30 + (vtype.get("crime_risk", 2) * 10)
    
    # Skill modifier
    skills = state.get("skills", {}) or {}
    stealth_skill = int((skills.get("stealth", {}) or {}).get("level", 1) or 1)
    base_difficulty -= stealth_skill * 3
    
    base_difficulty = _clamp(base_difficulty, 10, 90)
    
    # Roll
    r = _h32(day, turn, vehicle_id, "steal")
    roll = r % 100
    
    if roll < base_difficulty:
        # Failed - caught!
        tr = state.setdefault("trace", {})
        current_trace = int(tr.get("trace_pct", 0) or 0)
        trace_increase = 10 + vtype.get("crime_risk", 2) * 5
        _set_trace_pct(state, current_trace + trace_increase)
        
        return {
            "ok": False,
            "caught": True,
            "roll": roll,
            "difficulty": base_difficulty,
            "trace_added": trace_increase,
        }
    
    # Success - add stolen vehicle
    vstate = ensure_vehicle_state(state)
    vstate[vehicle_id] = {
        "type": vehicle_id,
        "name": vtype["name"],
        "fuel": 50,  # Half tank
        "condition": _clamp(50 + (r % 30), 30, 80),  # Random condition
        "owned_since_day": day,
        "stolen": True,
    }
    
    state.setdefault("world_notes", []).append(f"[Vehicle] Stolen {vtype['name']}! (TRACE +{10 + vtype.get('crime_risk', 2) * 5})")
    
    return {
        "ok": True,
        "vehicle": vehicle_id,
        "name": vtype["name"],
        "stolen": True,
        "roll": roll,
        "condition": vstate[vehicle_id]["condition"],
    }


def get_vehicle_for_travel(state: dict[str, Any]) -> tuple[str | None, dict[str, Any] | None]:
    """Get the best available vehicle for travel, considering fuel and condition."""
    vstate = ensure_vehicle_state(state)
    
    candidates = []
    for vid, vdata in vstate.items():
        fuel = int(vdata.get("fuel", 0) or 0)
        condition = int(vdata.get("condition", 0) or 0)
        
        if fuel > 0 and condition > 20:
            vtype = VEHICLE_TYPES.get(vid, {})
            candidates.append((vid, vdata, vtype))
    
    if not candidates:
        return None, None
    
    # Sort by speed (prefer faster)
    candidates.sort(key=lambda x: x[2].get("speed", 0), reverse=True)
    
    return candidates[0][0], candidates[0][1]
