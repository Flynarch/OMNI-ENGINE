"""District system for intra-city travel and local services.

This module provides:
- District definitions per city
- Intra-city travel mechanics
- Local services per district
- District-based spawns and events
"""
from __future__ import annotations

from engine.core.error_taxonomy import log_swallowed_exception
from engine.world.atlas import resolve_place
import hashlib
import heapq
import json
from pathlib import Path
from typing import Any

_LOC_DATA_DIR = Path(__file__).resolve().parents[2] / "data" / "locations"

# #region agent log
def _dbg(hypothesisId: str, location: str, message: str, data: dict[str, Any] | None = None, runId: str = "pre-fix") -> None:
    try:
        payload = {
            "sessionId": "014e33",
            "runId": str(runId),
            "hypothesisId": str(hypothesisId),
            "location": str(location),
            "message": str(message),
            "data": data or {},
            "timestamp": __import__("time").time_ns() // 1_000_000,
        }
        with open("debug-014e33.log", "a", encoding="utf-8") as f:
            f.write(json.dumps(payload, ensure_ascii=False) + "\n")
    except Exception:
        return

# #endregion


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


def _build_adjacency_from_edges(edges: list[dict[str, Any]]) -> dict[str, dict[str, int]]:
    """Undirected weighted graph: id -> {neighbor: minutes}."""
    adj: dict[str, dict[str, int]] = {}
    for e in edges[:128]:
        if not isinstance(e, dict):
            continue
        a = str(e.get("from", "") or "").strip().lower()
        b = str(e.get("to", "") or "").strip().lower()
        try:
            w = int(e.get("minutes", 0) or 0)
        except Exception:
            w = 0
        if not a or not b or w <= 0:
            continue
        adj.setdefault(a, {})[b] = w
        adj.setdefault(b, {})[a] = w
    return adj


def _shortest_path_minutes(
    adj: dict[str, dict[str, int]], start: str, end: str
) -> tuple[list[str], int] | None:
    """Dijkstra; returns (path node ids, total minutes) or None."""
    if start == end:
        return [start], 0
    if start not in adj or end not in adj:
        return None
    inf = 10**9
    dist: dict[str, int] = {start: 0}
    prev: dict[str, str | None] = {start: None}
    pq: list[tuple[int, str]] = [(0, start)]
    while pq:
        d, u = heapq.heappop(pq)
        if d > int(dist.get(u, inf)):
            continue
        if u == end:
            path: list[str] = []
            cur: str | None = end
            while cur is not None:
                path.append(cur)
                cur = prev.get(cur)
            path.reverse()
            return path, d
        for v, w in (adj.get(u) or {}).items():
            nd = d + int(w)
            if nd < int(dist.get(v, inf)):
                dist[v] = nd
                prev[v] = u
                heapq.heappush(pq, (nd, str(v)))
    return None


def _travel_times_from_center(adj: dict[str, dict[str, int]], center_id: str, all_ids: list[str]) -> dict[str, int]:
    """Minutes from center along graph (fallback 0 for unreachable)."""
    out: dict[str, int] = {}
    cid = str(center_id or "").strip().lower()
    for did in all_ids:
        dk = str(did or "").strip().lower()
        if dk == cid:
            out[dk] = 0
            continue
        sp = _shortest_path_minutes(adj, cid, dk) if cid in adj and dk in adj else None
        out[dk] = int(sp[1]) if sp else 0
    return out


def _load_district_override_bundle(city_key: str) -> tuple[list[dict[str, Any]], dict[str, dict[str, int]]] | None:
    """Load optional ``data/locations/<city>_districts.json`` (data-driven graph + profiles)."""
    ck = str(city_key or "").strip().lower()
    if not ck:
        return None
    path = _LOC_DATA_DIR / f"{ck}_districts.json"
    if not path.exists():
        return None
    _dbg(
        "A",
        "engine/world/districts.py:_load_district_override_bundle",
        "override bundle found",
        {"city_key": ck, "path": str(path)},
    )
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        log_swallowed_exception("engine/world/districts.py:load_override", e)
        _dbg(
            "A",
            "engine/world/districts.py:_load_district_override_bundle",
            "override bundle json load failed",
            {"city_key": ck, "path": str(path), "err": repr(e)},
        )
        return None
    if not isinstance(doc, dict):
        return None
    raw_ds = doc.get("districts")
    if not isinstance(raw_ds, list) or not raw_ds:
        return None
    districts: list[dict[str, Any]] = []
    for row in raw_ds[:24]:
        if not isinstance(row, dict):
            continue
        did = str(row.get("id", "") or "").strip().lower()
        if not did:
            continue
        d: dict[str, Any] = {
            "id": did,
            "name": str(row.get("name", did) or did),
            "desc": str(row.get("desc", "") or ""),
            "services": [str(x) for x in (row.get("services") or []) if isinstance(x, str)][:16],
            "crime_risk": int(row.get("crime_risk", 3) or 3),
            "police_presence": int(row.get("police_presence", 3) or 3),
            "tech_level": str(row.get("tech_level", "medium") or "medium"),
            "travel_time_from_center": int(row.get("travel_time_from_center", 0) or 0),
        }
        if "danger_level" in row:
            try:
                d["danger_level"] = max(1, min(5, int(row.get("danger_level", 3) or 3)))
            except Exception:
                d["danger_level"] = max(1, min(5, int(d.get("crime_risk", 3) or 3)))
        if "economic_tier" in row:
            d["economic_tier"] = str(row.get("economic_tier", "mid") or "mid")
        if "npc_density" in row:
            try:
                d["npc_density"] = max(1, min(5, int(row.get("npc_density", 3) or 3)))
            except Exception:
                d["npc_density"] = 3
        if bool(row.get("is_center")):
            d["is_center"] = True
        districts.append(d)

    if not districts:
        return None
    # Exactly one center; else first is_center or first row
    centers = [x for x in districts if isinstance(x, dict) and x.get("is_center")]
    if len(centers) != 1:
        for x in districts:
            x.pop("is_center", None)
        districts[0]["is_center"] = True

    gdoc = doc.get("district_graph") if isinstance(doc.get("district_graph"), dict) else {}
    edges = gdoc.get("edges") if isinstance(gdoc.get("edges"), list) else []
    adj = _build_adjacency_from_edges([e for e in edges if isinstance(e, dict)])
    ids = [str(d.get("id", "")) for d in districts if isinstance(d, dict) and d.get("id")]
    center_id = ""
    for d in districts:
        if d.get("is_center"):
            center_id = str(d.get("id", "") or "").strip().lower()
            break
    if not center_id and ids:
        center_id = str(ids[0]).strip().lower()
    if adj and center_id:
        tmap = _travel_times_from_center(adj, center_id, ids)
        for d in districts:
            di = str(d.get("id", "") or "").strip().lower()
            if di in tmap:
                d["travel_time_from_center"] = int(tmap[di])
    for d in districts:
        dk = str(d.get("id", "") or "").strip().lower()
        if dk:
            adj.setdefault(dk, {})
    # Deterministic npc_density / event_chance if missing
    meta_seed = str(doc.get("version", "1") or "1")
    for d in districts:
        if "npc_density" not in d:
            r = _h32(meta_seed, ck, d.get("id"))
            d["npc_density"] = max(1, min(5, 3 + (r % 5) - 2))
        if "event_chance" not in d:
            r2 = _h32(meta_seed, ck, d.get("id"), "ev")
            d["event_chance"] = max(1, min(10, (r2 >> 4) % 10))
    return districts, adj


def _get_adjacency_for_city(state: dict[str, Any], city_key: str) -> dict[str, dict[str, int]]:
    ck = str(city_key or "").strip().lower()
    world = state.get("world", {}) or {}
    graphs = world.get("district_graphs") if isinstance(world.get("district_graphs"), dict) else {}
    g = graphs.get(ck) if isinstance(graphs, dict) else None
    return g if isinstance(g, dict) else {}


def district_travel_minutes(state: dict[str, Any], city: str, from_id: str, to_id: str) -> int:
    """Deterministic travel minutes between districts (graph path or legacy radial fallback)."""
    fk = str(city or "").strip().lower()
    a = str(from_id or "").strip().lower()
    b = str(to_id or "").strip().lower()
    if not fk or not a or not b or a == b:
        return max(0, 0 if a == b else 5)
    adj = _get_adjacency_for_city(state, fk)
    if adj and a in adj and b in adj:
        sp = _shortest_path_minutes(adj, a, b)
        if sp:
            _dbg(
                "C",
                "engine/world/districts.py:district_travel_minutes",
                "graph shortest path used",
                {"city": fk, "from": a, "to": b, "minutes": int(sp[1]), "path": sp[0], "adj_nodes": len(adj)},
            )
            return max(1, int(sp[1]))
        _dbg(
            "C",
            "engine/world/districts.py:district_travel_minutes",
            "graph present but no path",
            {"city": fk, "from": a, "to": b, "adj_nodes": len(adj)},
        )
    fa = get_district(state, fk, a)
    fb = get_district(state, fk, b)
    try:
        dfa = int((fa or {}).get("travel_time_from_center", 0) or 0)
        dfb = int((fb or {}).get("travel_time_from_center", 0) or 0)
    except Exception:
        dfa, dfb = 0, 0
    _dbg(
        "C",
        "engine/world/districts.py:district_travel_minutes",
        "fallback radial diff used",
        {"city": fk, "from": a, "to": b, "dfa": dfa, "dfb": dfb, "minutes": max(5, abs(dfa - dfb) * 2), "adj_nodes": len(adj) if isinstance(adj, dict) else 0},
    )
    return max(5, abs(dfa - dfb) * 2)


def district_path_ids(state: dict[str, Any], city: str, from_id: str, to_id: str) -> list[str]:
    """Ordered district ids along shortest path (including endpoints)."""
    fk = str(city or "").strip().lower()
    a = str(from_id or "").strip().lower()
    b = str(to_id or "").strip().lower()
    if not fk or not a or not b or a == b:
        return [a] if a else []
    adj = _get_adjacency_for_city(state, fk)
    if adj and a in adj and b in adj:
        sp = _shortest_path_minutes(adj, a, b)
        if sp:
            _dbg(
                "D",
                "engine/world/districts.py:district_path_ids",
                "graph path used",
                {"city": fk, "from": a, "to": b, "path": sp[0], "minutes": int(sp[1])},
            )
            return list(sp[0])
        _dbg(
            "D",
            "engine/world/districts.py:district_path_ids",
            "graph present but no path",
            {"city": fk, "from": a, "to": b, "adj_nodes": len(adj)},
        )
    _dbg(
        "D",
        "engine/world/districts.py:district_path_ids",
        "fallback direct path used",
        {"city": fk, "from": a, "to": b, "adj_nodes": len(adj) if isinstance(adj, dict) else 0},
    )
    return [a, b]


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

    bundle = _load_district_override_bundle(city_key)
    if bundle is not None:
        districts_ov, adj_ov = bundle
        if districts_ov:
            districts_store[city_key] = districts_ov
            if adj_ov:
                wg = world.setdefault("district_graphs", {})
                if not isinstance(wg, dict):
                    wg = {}
                    world["district_graphs"] = wg
                wg[city_key] = adj_ov
            _dbg(
                "B",
                "engine/world/districts.py:ensure_city_districts",
                "override bundle applied",
                {"city_key": city_key, "districts": len(districts_ov), "adj_nodes": len(adj_ov) if isinstance(adj_ov, dict) else 0},
            )
            return districts_ov

    meta = state.get("meta", {}) or {}
    seed = str(meta.get("seed_pack", "") or "")
    
    # Detect country if not provided
    if not country:
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
    """Neighbors: explicit graph edges if loaded; else ring on ordered district list."""
    cid = str(city or "").strip().lower()
    did = str(district_id or "").strip().lower()
    adj = _get_adjacency_for_city(state, cid)
    if adj and did in adj:
        return sorted([str(k) for k in adj[did].keys()])
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
        except Exception as _omni_sw_219:
            log_swallowed_exception('engine/world/districts.py:219', _omni_sw_219)
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
    
    cur_id = str(current.get("id", "") or "").strip().lower()
    tgt_id = str(target.get("id", "") or "").strip().lower()
    base_time = district_travel_minutes(state, city, cur_id, tgt_id)
    if base_time < 5:
        base_time = max(5, base_time)
    
    # Apply time to state. Shared travel modifiers (weather/restrictions/trace)
    # are centralized in update_timers for deterministic sequencing.
    ctx = {
        "action_type": "travel",
        "domain": "evasion",
        "normalized_input": f"travel to {target.get('name', target_district_id)}",
        "travel_minutes": base_time,
        "stakes": "low",
    }
    # Lazy: shop/timers can pull ``districts`` during their init — avoid cycle at module load.
    import engine.world.timers as _timers_mod

    _timers_mod.update_timers(state, ctx)
    
    # Update player location
    state["player"]["district"] = target_district_id
    
    # Crime risk during travel
    try:
        crime_risk = int(target.get("crime_risk", 3) or 3)
    except Exception:
        crime_risk = 3
    danger_lv = crime_risk
    if isinstance(target.get("danger_level"), (int, float)):
        try:
            danger_lv = max(crime_risk, int(target.get("danger_level", crime_risk) or crime_risk))
        except Exception:
            danger_lv = crime_risk
    try:
        police_presence = int(target.get("police_presence", 3) or 3)
    except Exception:
        police_presence = 3
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
    except Exception as _omni_sw_324:
        log_swallowed_exception('engine/world/districts.py:324', _omni_sw_324)
    # Roll for random encounter during travel
    meta = state.get("meta", {}) or {}
    seed = str(meta.get("seed_pack", "") or "")
    turn = int(meta.get("turn", 0) or 0)
    roll = _h32(seed, city, current.get("id"), target_district_id, turn) % 100
    
    encounter = None
    rough_ids = frozenset({"slums", "underside", "vice", "black_market", "east_end", "camden"})
    if roll < max(crime_risk, danger_lv) * 5:  # Crime encounter chance
        encounter = {"type": "crime", "risk": max(crime_risk, danger_lv)}
        # Apply trace if caught in illegal area
        if str(target.get("id", "") or "") in rough_ids:
            trace_inc = max(crime_risk, danger_lv) * 2
            try:
                tr = state.setdefault("trace", {})
                current_trace = int(tr.get("trace_pct", 0) or 0)
                tr["trace_pct"] = min(100, current_trace + trace_inc)
            except Exception as _omni_sw_344:
                log_swallowed_exception('engine/world/districts.py:344', _omni_sw_344)
    elif roll > 95 - police_presence * 3:  # Police encounter
        encounter = {"type": "police", "presence": police_presence}
        # Check for illegal items (lazy: ``police_check`` imports this module for ``get_district``).
        try:
            from engine.social.police_check import maybe_schedule_weapon_check

            maybe_schedule_weapon_check(state)
        except Exception as _omni_sw_352:
            log_swallowed_exception('engine/world/districts.py:352', _omni_sw_352)
        # Cyber crackdown: police stops are more likely to check devices/IDs.
        try:
            loc_slot = (state.get("world", {}) or {}).get("locations", {}) or {}
            slot = loc_slot.get(city) if isinstance(loc_slot, dict) else None
            ca = slot.get("cyber_alert") if isinstance(slot, dict) else None
            if isinstance(ca, dict) and int(ca.get("level", 0) or 0) >= 60 and tech_level in ("high", "cutting_edge"):
                state.setdefault("world_notes", []).append("[Cyber] checkpoint: device checks intensified in this district.")
        except Exception as _omni_sw_361:
            log_swallowed_exception('engine/world/districts.py:361', _omni_sw_361)
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
