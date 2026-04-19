"""District system for intra-city travel and local services.

This module provides:
- District definitions per city
- Intra-city travel mechanics
- Local services per district
- District-based spawns and events
"""
from __future__ import annotations

import hashlib
from typing import Any


def travel_is_district_mode(action_ctx: dict[str, Any]) -> bool:
    """True for TRAVELTO-style moves; W2-8 intercity gates use natural travel only."""
    return str((action_ctx or {}).get("travel_mode", "") or "").strip().lower() == "district"


def _h32(*parts: Any) -> int:
    """Deterministic hash for district generation."""
    s = "|".join(str(p) for p in parts)
    h = hashlib.md5(s.encode("utf-8", errors="ignore")).hexdigest()
    return int(h[:8], 16)


def _pick(r: int, items: list[str]) -> str:
    """Pick from list deterministically."""
    if not items:
        return "-"
    return items[r % len(items)]


# Default district templates per city archetype
_CITY_ARCHETYPES: dict[str, list[dict[str, Any]]] = {
    "metropolis": [
        {"id": "downtown", "name": "Downtown", "desc": "Business district, high surveillance", "services": ["bank", "shop_tech", "hotel"], "crime_risk": 2, "police_presence": 5, "tech_level": "high"},
        {"id": "financial", "name": "Financial District", "desc": "Corporate towers, heavy security", "services": ["bank", "shop_tech"], "crime_risk": 1, "police_presence": 5, "tech_level": "cutting_edge"},
        {"id": "old_town", "name": "Old Town", "desc": "Historic quarter, narrow streets", "services": ["market", "safehouse"], "crime_risk": 3, "police_presence": 2, "tech_level": "medium"},
        {"id": "harbor", "name": "Harbor District", "desc": "Port area, industrial, smuggling routes", "services": ["black_market", "warehouse"], "crime_risk": 5, "police_presence": 3, "tech_level": "medium"},
        {"id": "suburbs", "name": "Suburbs", "desc": "Residential areas, quieter", "services": ["kos", "market"], "crime_risk": 1, "police_presence": 2, "tech_level": "medium"},
        {"id": "slums", "name": "Urban Slums", "desc": "Poor district, informal economy", "services": ["black_market", "safehouse"], "crime_risk": 5, "police_presence": 1, "tech_level": "low"},
        {"id": "entertainment", "name": "Entertainment District", "desc": "Nightlife, clubs, hotels", "services": ["hotel", "bar", "disguise"], "crime_risk": 3, "police_presence": 3, "tech_level": "high"},
        {"id": "industrial", "name": "Industrial Zone", "desc": "Factories, warehouses", "services": ["warehouse", "black_market"], "crime_risk": 4, "police_presence": 2, "tech_level": "medium"},
    ],
    "tropical": [
        {"id": "central", "name": "Central Business District", "desc": "Modern offices, malls", "services": ["bank", "shop_tech", "hotel"], "crime_risk": 2, "police_presence": 4, "tech_level": "high"},
        {"id": "old_city", "name": "Old City", "desc": "Colonial architecture, markets", "services": ["market", "kos"], "crime_risk": 3, "police_presence": 2, "tech_level": "medium"},
        {"id": "waterfront", "name": "Waterfront", "desc": "Harbor, fishing villages", "services": ["black_market", "warehouse"], "crime_risk": 4, "police_presence": 2, "tech_level": "low"},
        {"id": "kampong", "name": "Kampong", "desc": "Traditional neighborhoods", "services": ["safehouse", "market"], "crime_risk": 3, "police_presence": 1, "tech_level": "low"},
        {"id": "new_development", "name": "New Development", "desc": "Modern housing complexes", "services": ["kos", "shop_tech"], "crime_risk": 2, "police_presence": 3, "tech_level": "high"},
        {"id": "red_light", "name": "Red Light District", "desc": "Entertainment and vice", "services": ["bar", "disguise", "black_market"], "crime_risk": 5, "police_presence": 2, "tech_level": "medium"},
    ],
    "east_asian": [
        {"id": "shinjuku", "name": "Central Ward", "desc": "Business and entertainment", "services": ["bank", "shop_tech", "hotel"], "crime_risk": 2, "police_presence": 5, "tech_level": "cutting_edge"},
        {"id": "finance", "name": "Financial Quarter", "desc": "Corporate towers", "services": ["bank", "shop_tech"], "crime_risk": 1, "police_presence": 5, "tech_level": "cutting_edge"},
        {"id": "old_town", "name": "Historic District", "desc": "Traditional architecture", "services": ["market", "kos"], "crime_risk": 2, "police_presence": 3, "tech_level": "medium"},
        {"id": "docks", "name": "Port Area", "desc": "Shipping and warehouses", "services": ["black_market", "warehouse"], "crime_risk": 4, "police_presence": 2, "tech_level": "medium"},
        {"id": "residential_east", "name": "Residential East", "desc": "Quiet neighborhoods", "services": ["kos", "market"], "crime_risk": 1, "police_presence": 2, "tech_level": "high"},
        {"id": "vice", "name": "Entertainment Quarter", "desc": "Nightlife and vice", "services": ["bar", "disguise", "hotel"], "crime_risk": 4, "police_presence": 3, "tech_level": "high"},
    ],
    "western": [
        {"id": "midtown", "name": "Midtown", "desc": "Business district", "services": ["bank", "shop_tech", "hotel"], "crime_risk": 2, "police_presence": 4, "tech_level": "high"},
        {"id": "financial", "name": "Financial District", "desc": "Banks and corporations", "services": ["bank", "shop_tech"], "crime_risk": 1, "police_presence": 5, "tech_level": "high"},
        {"id": "historic", "name": "Historic Quarter", "desc": "Old city center", "services": ["market", "kos", "bar"], "crime_risk": 2, "police_presence": 3, "tech_level": "medium"},
        {"id": "port", "name": "Port District", "desc": "Docks and shipping", "services": ["black_market", "warehouse"], "crime_risk": 4, "police_presence": 2, "tech_level": "medium"},
        {"id": "suburban", "name": "Suburbs", "desc": "Residential areas", "services": ["kos", "market"], "crime_risk": 1, "police_presence": 2, "tech_level": "high"},
        {"id": "underside", "name": "Undercity", "desc": "Poor district, crime hub", "services": ["black_market", "safehouse"], "crime_risk": 5, "police_presence": 1, "tech_level": "low"},
    ],
}

# Service definitions
SERVICES = {
    "bank": {"name": "Bank", "desc": "ATM, deposits, withdrawals", "time_cost": 10},
    "shop_tech": {"name": "Tech Shop", "desc": "Electronics, burner phones", "time_cost": 15},
    "hotel": {"name": "Hotel", "desc": "Short-term accommodation", "time_cost": 5},
    "kos": {"name": "Boarding House", "desc": "Budget accommodation", "time_cost": 5},
    "market": {"name": "Market", "desc": "Food, supplies, street vendors", "time_cost": 20},
    "safehouse": {"name": "Safehouse", "desc": "Secure storage, hideout", "time_cost": 5},
    "black_market": {"name": "Black Market", "desc": "Illegal goods, weapons, ammo", "time_cost": 15},
    "warehouse": {"name": "Warehouse", "desc": "Storage, smuggling drop", "time_cost": 10},
    "bar": {"name": "Bar/Club", "desc": "Socializing, intel gathering", "time_cost": 30},
    "disguise": {"name": "Disguise Shop", "desc": "Costumes, identity goods", "time_cost": 10},
}


def _detect_city_archetype(city: str, country: str) -> str:
    """Detect city archetype for district generation."""
    city_lower = str(city or "").lower()
    country_lower = str(country or "").lower()
    
    # East Asian
    if country_lower in ("japan", "south korea", "taiwan", "china"):
        return "east_asian"
    
    # Tropical/developing
    if country_lower in ("indonesia", "philippines", "thailand", "vietnam", "malaysia", "india", "brazil", "nigeria", "kenya"):
        return "tropical"
    
    # Major western metropolis
    if city_lower in ("new york", "london", "paris", "los angeles", "chicago", "toronto", "sydney", "berlin", "madrid"):
        return "metropolis"
    
    # Default western
    return "western"


def ensure_city_districts(state: dict[str, Any], city: str, country: str | None = None) -> list[dict[str, Any]]:
    """Ensure districts exist for a city, generating deterministically if needed."""
    world = state.setdefault("world", {})
    districts_store = world.setdefault("city_districts", {})
    if not isinstance(districts_store, dict):
        districts_store = {}
        world["city_districts"] = districts_store

    city_key = str(city or "").strip().lower()
    
    # Return cached if exists
    if city_key in districts_store and isinstance(districts_store[city_key], list):
        return districts_store[city_key]

    meta = state.get("meta", {}) or {}
    seed = str(meta.get("seed_pack", "") or "")
    
    # Detect country if not provided
    if not country:
        from engine.world.atlas import resolve_place
        country, _ = resolve_place(city)
        if not country:
            country = ""
    
    archetype = _detect_city_archetype(city, country)
    templates = _CITY_ARCHETYPES.get(archetype, _CITY_ARCHETYPES["western"])
    
    districts: list[dict[str, Any]] = []
    for i, tmpl in enumerate(templates):
        r = _h32(seed, city_key, tmpl["id"])
        
        district: dict[str, Any] = {
            "id": tmpl["id"],
            "name": tmpl["name"],
            "desc": tmpl["desc"],
            "services": list(tmpl.get("services", [])),
            "crime_risk": int(tmpl.get("crime_risk", 3)),
            "police_presence": int(tmpl.get("police_presence", 3)),
            "tech_level": str(tmpl.get("tech_level", "medium")),
            "travel_time_from_center": i * 5,  # minutes from city center
        }
        
        # Deterministic NPC spawn chance per district
        district["npc_density"] = max(1, min(5, 3 + (r % 5) - 2))
        district["event_chance"] = max(1, min(10, (r >> 4) % 10))
        
        districts.append(district)
    
    # Mark a random district as "city_center" (default spawn point)
    center_idx = _h32(seed, city_key, "center") % len(districts)
    for d in districts:
        d["is_center"] = (districts.index(d) == center_idx)
    
    districts_store[city_key] = districts
    world["city_districts"] = districts_store
    return districts


def get_district(state: dict[str, Any], city: str, district_id: str) -> dict[str, Any] | None:
    """Get a specific district by ID."""
    districts = ensure_city_districts(state, city)
    for d in districts:
        if d.get("id") == district_id:
            return d
    return None


def list_districts(state: dict[str, Any], city: str) -> list[dict[str, Any]]:
    """List all districts in a city."""
    return ensure_city_districts(state, city)


def district_neighbor_ids(state: dict[str, Any], city: str, district_id: str) -> list[str]:
    """W2-4: deterministic ring neighbors on ordered district list (no geo pathfinding)."""
    cid = str(city or "").strip().lower()
    did = str(district_id or "").strip().lower()
    dists = list_districts(state, cid)
    if not dists:
        return []
    ids = [str(d.get("id", "") or "").strip().lower() for d in dists if isinstance(d, dict) and d.get("id")]
    ids = [x for x in ids if x]
    if did not in ids:
        return []
    i = ids.index(did)
    n = len(ids)
    out: list[str] = []
    if n > 1:
        out.append(ids[(i - 1) % n])
        out.append(ids[(i + 1) % n])
    return out


def district_heat_snapshot(state: dict[str, Any], city: str, district_id: str) -> int:
    """Max heat level at city key for player-visible district scope."""
    ck = str(city or "").strip().lower()
    dk = str(district_id or "").strip().lower()
    if not ck or not dk:
        return 0
    world = state.get("world", {}) or {}
    hm = world.get("heat_map", {}) if isinstance(world.get("heat_map"), dict) else {}
    loc_map = hm.get(ck) if isinstance(hm, dict) else None
    if not isinstance(loc_map, dict):
        return 0
    best = 0
    for sk, row in loc_map.items():
        if not isinstance(row, dict):
            continue
        if sk != "__all__" and sk != dk:
            continue
        try:
            best = max(best, int(row.get("level", 0) or 0))
        except Exception:
            continue
    return max(0, min(100, best))


def is_valid_district(state: dict[str, Any], city: str, district_id: str) -> bool:
    """Return True if district_id exists for city."""
    cid = str(city or "").strip().lower()
    did = str(district_id or "").strip().lower()
    if not (cid and did):
        return False
    d = get_district(state, cid, did)
    return isinstance(d, dict) and str(d.get("id", "") or "").strip().lower() == did


def default_district_for_city(state: dict[str, Any], city: str) -> str:
    """Deterministically pick a default district for a city (prefer center)."""
    cid = str(city or "").strip().lower()
    if not cid:
        return ""
    districts = ensure_city_districts(state, cid)
    if not districts:
        return ""
    centers = [d for d in districts if isinstance(d, dict) and bool(d.get("is_center", False)) and d.get("id")]
    if centers:
        return str(centers[0].get("id") or "").strip().lower()
    ids = sorted([str(d.get("id")) for d in districts if isinstance(d, dict) and str(d.get("id", "")).strip()])
    return str(ids[0]).strip().lower() if ids else ""


def get_current_district(state: dict[str, Any]) -> dict[str, Any] | None:
    """Get the player's current district."""
    player = state.get("player", {}) or {}
    location = str(player.get("location", "") or "").strip().lower()
    district_id = str(player.get("district", "") or "").strip()
    
    if not location or not district_id:
        return None
    
    return get_district(state, location, district_id)


def travel_within_city(state: dict[str, Any], target_district_id: str) -> dict[str, Any]:
    """Handle intra-city travel to a different district."""
    current = get_current_district(state)
    
    if not current:
        return {"ok": False, "reason": "not_in_district", "message": "You are not in any district."}
    
    city = str(state.get("player", {}).get("location", "") or "").strip().lower()
    target = get_district(state, city, target_district_id)
    
    if not target:
        return {"ok": False, "reason": "invalid_district", "message": f"Unknown district: {target_district_id}"}
    
    if current.get("id") == target_district_id:
        return {"ok": False, "reason": "same_district", "message": "You are already there."}
    
    # Calculate travel time based on distance and transport mode
    dist_diff = abs(current.get("travel_time_from_center", 0) - target.get("travel_time_from_center", 0))
    base_time = max(5, dist_diff * 2)  # minimum 5 minutes, scales with distance
    
    # Weather affects travel time
    try:
        from engine.world.weather import travel_minutes_modifier
        loc = str(state.get("player", {}).get("location", "") or "").strip().lower()
        meta = state.get("meta", {}) or {}
        day = int(meta.get("day", 1) or 1)
        weather_slot = (state.get("world", {}).get("locations", {}) or {}).get(loc) or {}
        weather = weather_slot.get("weather", {}) or {}
        weather_kind = str(weather.get("kind", "clear") or "clear")
        weather_mod = travel_minutes_modifier(weather_kind)
        base_time += weather_mod
    except Exception:
        pass

    # Apply time to state (trace tier friction is applied inside update_timers for all travel).
    from engine.world.timers import update_timers
    ctx = {
        "action_type": "travel",
        "domain": "evasion",
        "normalized_input": f"travel to {target.get('name', target_district_id)}",
        "travel_minutes": base_time,
        "stakes": "low",
    }
    update_timers(state, ctx)
    
    # Update player location
    state["player"]["district"] = target_district_id
    
    # Crime risk during travel
    crime_risk = target.get("crime_risk", 3)
    police_presence = target.get("police_presence", 3)
    tech_level = str(target.get("tech_level", "medium") or "medium").lower()
    # Cyber crackdown can add extra police presence in high-tech districts.
    try:
        meta0 = state.get("meta", {}) or {}
        day0 = int(meta0.get("day", 1) or 1)
        loc_slot = (state.get("world", {}) or {}).get("locations", {}) or {}
        slot = loc_slot.get(city) if isinstance(loc_slot, dict) else None
        ca = slot.get("cyber_alert") if isinstance(slot, dict) else None
        if isinstance(ca, dict) and int(ca.get("until_day", 0) or 0) >= day0:
            lvl = int(ca.get("level", 0) or 0)
            if lvl >= 60 and tech_level in ("high", "cutting_edge"):
                police_presence = min(5, int(police_presence) + 1)
    except Exception:
        pass
    
    # Roll for random encounter during travel
    meta = state.get("meta", {}) or {}
    seed = str(meta.get("seed_pack", "") or "")
    turn = int(meta.get("turn", 0) or 0)
    roll = _h32(seed, city, current.get("id"), target_district_id, turn) % 100
    
    encounter = None
    if roll < crime_risk * 5:  # Crime encounter chance
        encounter = {"type": "crime", "risk": crime_risk}
        # Apply trace if caught in illegal area
        if target.get("id") in ("slums", "underside", "vice", "black_market"):
            from engine.core.trace import update_trace
            trace_inc = crime_risk * 2
            try:
                tr = state.setdefault("trace", {})
                current_trace = int(tr.get("trace_pct", 0) or 0)
                tr["trace_pct"] = min(100, current_trace + trace_inc)
            except Exception:
                pass
    elif roll > 95 - police_presence * 3:  # Police encounter
        encounter = {"type": "police", "presence": police_presence}
        # Check for illegal items
        try:
            from engine.social.police_check import maybe_schedule_weapon_check
            maybe_schedule_weapon_check(state)
        except Exception:
            pass
        # Cyber crackdown: police stops are more likely to check devices/IDs.
        try:
            loc_slot = (state.get("world", {}) or {}).get("locations", {}) or {}
            slot = loc_slot.get(city) if isinstance(loc_slot, dict) else None
            ca = slot.get("cyber_alert") if isinstance(slot, dict) else None
            if isinstance(ca, dict) and int(ca.get("level", 0) or 0) >= 60 and tech_level in ("high", "cutting_edge"):
                state.setdefault("world_notes", []).append("[Cyber] checkpoint: device checks intensified in this district.")
        except Exception:
            pass
    
    return {
        "ok": True,
        "from": current.get("id"),
        "to": target_district_id,
        "to_name": target.get("name"),
        "travel_time": base_time,
        "encounter": encounter,
        "crime_risk": crime_risk,
        "police_presence": police_presence,
        "message": f"Traveled to {target.get('name')} ({target.get('desc')}) in {base_time} minutes."
    }


def get_district_services(district: dict[str, Any]) -> list[dict[str, Any]]:
    """Get service details for a district."""
    services = district.get("services", [])
    return [SERVICES.get(s, {"name": s, "desc": "Unknown service", "time_cost": 10}) for s in services]


def describe_location(state: dict[str, Any]) -> str:
    """Get a description of current location including district."""
    player = state.get("player", {}) or {}
    location = str(player.get("location", "") or "").strip()
    district_id = str(player.get("district", "") or "").strip()
    
    if not district_id:
        return f"You are in {location}. No specific district."
    
    district = get_current_district(state)
    if not district:
        return f"You are in {location}. District: {district_id}"
    
    services = district.get("services", [])
    services_str = ", ".join([SERVICES.get(s, {}).get("name", s) for s in services]) if services else "none"
    
    return (
        f"You are in {location}, {district.get('name', district_id)} district. "
        f"{district.get('desc', '')} "
        f"Services: {services_str}. "
        f"Crime risk: {district.get('crime_risk', 3)}/5. "
        f"Police presence: {district.get('police_presence', 3)}/5."
    )
