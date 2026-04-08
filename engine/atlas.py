from __future__ import annotations

import hashlib
from typing import Any


def _h32(*parts: Any) -> int:
    s = "|".join(str(p) for p in parts)
    h = hashlib.md5(s.encode("utf-8", errors="ignore")).hexdigest()
    return int(h[:8], 16)


def _pick(r: int, items: list[str]) -> str:
    if not items:
        return "-"
    return items[r % len(items)]


def _norm_loc(loc: str) -> str:
    return str(loc or "").strip()


# Tiny built-in map for common real-world anchors (extendable later).
_CITY_TO_COUNTRY = {
    "jakarta": "indonesia",
    "london": "united kingdom",
    "tokyo": "japan",
    "new york": "united states",
    "nyc": "united states",
    "los angeles": "united states",
    "singapore": "singapore",
    "paris": "france",
    "berlin": "germany",
    "mumbai": "india",
}

_COUNTRY_ALIASES = {
    "usa": "united states",
    "us": "united states",
    "uk": "united kingdom",
    "u.k.": "united kingdom",
    "england": "united kingdom",
}

# Fixed pool to build deterministic relations (expand later).
_COUNTRY_POOL = [
    "indonesia",
    "united states",
    "united kingdom",
    "japan",
    "india",
    "germany",
    "france",
    "singapore",
]

_ICONIC_OVERRIDES: dict[str, dict[str, str]] = {
    # Oil/gas heavy
    "iran": {"resource_bias": "oil_gas", "econ_style": "resource"},
    "saudi arabia": {"resource_bias": "oil_gas", "econ_style": "resource"},
    "uae": {"resource_bias": "oil_gas", "econ_style": "resource"},
    "venezuela": {"resource_bias": "oil_gas", "econ_style": "resource"},
    "norway": {"resource_bias": "oil_gas", "econ_style": "resource"},
    "russia": {"resource_bias": "oil_gas", "econ_style": "resource"},
    # Finance/service hub
    "switzerland": {"resource_bias": "finance", "econ_style": "service", "tech_level": "high"},
    "singapore": {"resource_bias": "finance", "econ_style": "service", "tech_level": "high"},
    # Manufacturing/tech
    "japan": {"resource_bias": "manufacturing", "econ_style": "industrial", "tech_level": "cutting_edge"},
    "germany": {"resource_bias": "manufacturing", "econ_style": "industrial", "tech_level": "high"},
    "china": {"resource_bias": "manufacturing", "econ_style": "industrial", "tech_level": "high"},
    # Big mixed economies
    "united states": {"resource_bias": "finance", "econ_style": "consumer", "tech_level": "high"},
    "usa": {"resource_bias": "finance", "econ_style": "consumer", "tech_level": "high"},
    "brazil": {"resource_bias": "agri", "econ_style": "resource"},
    "india": {"resource_bias": "agri", "econ_style": "industrial"},
    "australia": {"resource_bias": "minerals", "econ_style": "resource"},
}

_RESOURCE_BIASES = ["oil_gas", "manufacturing", "agri", "minerals", "finance"]


def ensure_country_profile(state: dict[str, Any], country: str) -> dict[str, Any]:
    """Ensure country exists in atlas with deterministic relations scaffold."""
    world = state.setdefault("world", {})
    atlas = ensure_world_atlas(state)
    countries = atlas.get("countries", {})
    if not isinstance(countries, dict):
        countries = {}
        atlas["countries"] = countries

    meta = state.get("meta", {}) or {}
    seed = str(meta.get("seed_pack", "") or "")
    day0 = int(meta.get("day", 1) or 1)

    c = str(country or "").strip().lower()
    c = _COUNTRY_ALIASES.get(c, c)
    if not c:
        c = "unknown"

    langs = {
        "indonesia": ["id", "id+en"],
        "united states": ["en"],
        "united kingdom": ["en"],
        "japan": ["ja", "ja+en"],
        "india": ["hi+en", "en"],
        "germany": ["de+en", "de"],
        "france": ["fr+en", "fr"],
        "singapore": ["en+zh", "en"],
    }
    currencies = {
        "indonesia": "IDR",
        "united states": "USD",
        "united kingdom": "GBP",
        "japan": "JPY",
        "india": "INR",
        "germany": "EUR",
        "france": "EUR",
        "singapore": "SGD",
    }

    if c not in countries or not isinstance(countries.get(c), dict):
        rr = _h32(seed, "country_profile", c)
        # Defaults
        econ_style = _pick(rr >> 2, ["consumer", "industrial", "service", "resource"])
        law_level = _pick(rr >> 1, ["lenient", "standard", "strict"])
        tech_level = _pick(rr >> 4, ["low", "medium", "high"])
        corruption = _pick(rr >> 6, ["low", "medium", "high"])
        resource_bias = _pick(rr >> 8, _RESOURCE_BIASES)
        # Curated overrides for iconic countries (earth-like flavor).
        ov = _ICONIC_OVERRIDES.get(c) or _ICONIC_OVERRIDES.get(c.replace(".", "")) or {}
        if isinstance(ov, dict) and ov:
            econ_style = str(ov.get("econ_style", econ_style))
            law_level = str(ov.get("law_level", law_level))
            tech_level = str(ov.get("tech_level", tech_level))
            resource_bias = str(ov.get("resource_bias", resource_bias))
        countries[c] = {
            "name": c,
            "currency": currencies.get(c, "CR"),
            "dominant_lang": _pick(rr, langs.get(c, ["en"])),
            "law_level": law_level,
            "econ_style": econ_style,
            "tech_level": tech_level,
            "corruption": corruption,
            "resource_bias": resource_bias,
            "created_day": day0,
            "sig": f"{seed}:{c}:{rr}",
        }

    row = countries.get(c) if isinstance(countries.get(c), dict) else {}
    if not isinstance(row, dict):
        row = {"name": c}

    # Relations graph (deterministic, symmetric not guaranteed but stable).
    row.setdefault("relations", {})
    rel = row.get("relations", {})
    if not isinstance(rel, dict) or not rel:
        rel = {}
        rr2 = _h32(seed, "country_rel", c)
        pool = [x for x in _COUNTRY_POOL if x != c]
        # Pick 2 allies + 2 rivals deterministically.
        if pool:
            a1 = pool[rr2 % len(pool)]
            a2 = pool[(rr2 >> 3) % len(pool)]
            r1 = pool[(rr2 >> 7) % len(pool)]
            r2 = pool[(rr2 >> 11) % len(pool)]
            for x in (a1, a2):
                if x != c:
                    rel[x] = {"stance": "ally", "trade": 60 + int((_h32(seed, "trade", c, x) % 31))}
            for x in (r1, r2):
                if x != c:
                    rel[x] = {"stance": "rival", "trade": 15 + int((_h32(seed, "trade", c, x) % 26))}
        row["relations"] = rel

    # Global indices bucket for later ticks.
    row.setdefault("sanctioned", False)
    row.setdefault("conflict_risk", int((_h32(seed, "risk", c) % 60) + 20))  # 20..79
    row.setdefault("market_profile", {})
    row.setdefault("market", {})
    countries[c] = row
    atlas["countries"] = countries
    world["atlas"] = atlas
    return row


def ensure_country_market(
    state: dict[str, Any],
    country: str,
    *,
    global_market: dict[str, dict[str, int]],
    day: int,
    sanctions_level: int = 0,
    tension_idx: int = 0,
) -> dict[str, Any]:
    """Compute/cached market baseline for a country (global → country layer)."""
    row = ensure_country_profile(state, country)
    mp = row.get("market_profile", {}) if isinstance(row, dict) else {}
    if not isinstance(mp, dict):
        mp = {}
    last = int(mp.get("last_update_day", 0) or 0)
    if last == day and isinstance(row.get("market"), dict) and row.get("market"):
        return row

    rb = str(row.get("resource_bias", "manufacturing") or "manufacturing").lower()
    econ_style = str(row.get("econ_style", "service") or "service").lower()
    law = str(row.get("law_level", "standard") or "standard").lower()
    tech = str(row.get("tech_level", "medium") or "medium").lower()
    corr = str(row.get("corruption", "medium") or "medium").lower()
    sanc = max(0, min(5, int(sanctions_level)))
    tens = max(0, min(100, int(tension_idx)))

    # Start from global baseline.
    base: dict[str, dict[str, int]] = {}
    for cat in ("electronics", "medical", "weapons", "food", "transport"):
        g = global_market.get(cat) if isinstance(global_market.get(cat), dict) else {"price_idx": 100, "scarcity": 0}
        try:
            px = int((g or {}).get("price_idx", 100) or 100)
        except Exception:
            px = 100
        try:
            sc = int((g or {}).get("scarcity", 0) or 0)
        except Exception:
            sc = 0
        base[cat] = {"price_idx": px, "scarcity": sc}

    def bump(cat: str, dpx: int = 0, dsc: int = 0) -> None:
        if cat not in base:
            return
        base[cat]["price_idx"] = max(60, min(320, int(base[cat]["price_idx"]) + int(dpx)))
        base[cat]["scarcity"] = max(0, min(100, int(base[cat]["scarcity"]) + int(dsc)))

    # Resource bias
    if rb == "oil_gas":
        bump("transport", dpx=-18, dsc=-6)  # proxy for fuel cheaper/available
        bump("food", dpx=+2, dsc=+0)  # imports can be pricier
    elif rb == "manufacturing":
        bump("electronics", dpx=-12, dsc=-4)
        bump("transport", dpx=-2, dsc=-1)
    elif rb == "agri":
        bump("food", dpx=-14, dsc=-6)
        bump("medical", dpx=-2, dsc=-1)
    elif rb == "minerals":
        bump("electronics", dpx=-5, dsc=-2)
        bump("weapons", dpx=-3, dsc=-1)
    elif rb == "finance":
        bump("electronics", dpx=+2, dsc=-2)  # stable supply but higher cost of living
        bump("medical", dpx=+1, dsc=-1)

    # Econ style
    if econ_style == "consumer":
        bump("food", dpx=+2, dsc=+1)
        bump("electronics", dpx=+2, dsc=+0)
    elif econ_style == "service":
        bump("medical", dpx=+2, dsc=+0)
    elif econ_style == "industrial":
        bump("electronics", dpx=-3, dsc=-1)
    elif econ_style == "resource":
        bump("transport", dpx=-3, dsc=-1)

    # Law/corruption/tech
    if law in ("strict", "militarized"):
        bump("weapons", dpx=+4, dsc=+6)
    if corr == "high":
        for cat in base.keys():
            bump(cat, dpx=+1, dsc=+1)
    if tech in ("high", "cutting_edge"):
        bump("electronics", dpx=-2, dsc=-2)
        bump("medical", dpx=-1, dsc=-1)

    # Sanctions / tension (country-specific effect)
    if sanc > 0:
        bump("electronics", dpx=+4 * sanc, dsc=+3 * sanc)
        bump("transport", dpx=+3 * sanc, dsc=+2 * sanc)
    if tens >= 70:
        bump("transport", dpx=+2, dsc=+1)

    mp.update(
        {
            "resource_bias": rb,
            "econ_style": econ_style,
            "law_level": law,
            "tech_level": tech,
            "corruption": corr,
            "sanctions_level": sanc,
            "tension_idx": tens,
            "last_update_day": day,
        }
    )
    row["market_profile"] = mp
    row["market"] = base
    # Cache back.
    world = state.setdefault("world", {})
    atlas = ensure_world_atlas(state)
    countries = atlas.get("countries", {})
    if isinstance(countries, dict):
        countries[str(row.get("name", country)).strip().lower()] = row
        atlas["countries"] = countries
    world["atlas"] = atlas
    return row


def ensure_geopolitics(state: dict[str, Any]) -> dict[str, Any]:
    """Ensure atlas has geopolitics state (tension/sanctions)."""
    world = state.setdefault("world", {})
    atlas = ensure_world_atlas(state)
    atlas.setdefault("geopolitics", {})
    gp = atlas.get("geopolitics", {})
    if not isinstance(gp, dict):
        gp = {}
        atlas["geopolitics"] = gp
    gp.setdefault("last_tick_day", 0)
    gp.setdefault("tension_idx", 0)  # 0..100
    gp.setdefault("active_sanctions", [])  # list of {day, a, b, kind}
    atlas["geopolitics"] = gp
    world["atlas"] = atlas
    return gp


def _resolve_country(loc: str) -> tuple[str, str]:
    """Return (country_name, location_kind) where kind is 'country' or 'city'."""
    raw = _norm_loc(loc)
    low = raw.lower()
    low = _COUNTRY_ALIASES.get(low, low)

    # Heuristic: if user inputs a known country name only.
    if low in set(_COUNTRY_ALIASES.values()) or low in (
        "indonesia",
        "united states",
        "united kingdom",
        "japan",
        "france",
        "germany",
        "india",
        "singapore",
    ):
        return (low, "country")

    # Parse "city, country" or "city country"
    if "," in low:
        parts = [p.strip() for p in low.split(",") if p.strip()]
        if len(parts) >= 2:
            return (_COUNTRY_ALIASES.get(parts[-1], parts[-1]), "city")
    toks = [t for t in low.split() if t]
    if len(toks) >= 2:
        tail2 = " ".join(toks[-2:])
        tail1 = toks[-1]
        if tail2 in _COUNTRY_ALIASES:
            return (_COUNTRY_ALIASES[tail2], "city")
        if tail1 in _COUNTRY_ALIASES:
            return (_COUNTRY_ALIASES[tail1], "city")

    # Known city anchors.
    if low in _CITY_TO_COUNTRY:
        return (_CITY_TO_COUNTRY[low], "city")

    # Fallback: treat as city with generated country bucket.
    # This keeps "khayalan" cities consistent but still gives a country background.
    bucket = _pick(_h32("country_bucket", low), ["indonesia", "united states", "united kingdom", "japan", "india", "germany", "france", "singapore"])
    return (bucket, "city")


def ensure_world_atlas(state: dict[str, Any]) -> dict[str, Any]:
    world = state.setdefault("world", {})
    atlas = world.setdefault("atlas", {"countries": {}, "version": 1})
    if not isinstance(atlas, dict):
        atlas = {"countries": {}, "version": 1}
        world["atlas"] = atlas
    atlas.setdefault("countries", {})
    atlas.setdefault("version", 1)
    return atlas


def ensure_location_profile(state: dict[str, Any], loc: str) -> dict[str, Any]:
    """Create and cache a deterministic culture/econ/law profile for a location."""
    loc_s = _norm_loc(loc)
    loc_key = loc_s.strip().lower()
    world = state.setdefault("world", {})
    world.setdefault("locations", {})
    locs = world.get("locations")
    if not isinstance(locs, dict):
        locs = {}
        world["locations"] = locs
    locs.setdefault(loc_key, {})
    slot = locs.get(loc_key)
    if not isinstance(slot, dict):
        slot = {}
        locs[loc_key] = slot

    prof = slot.get("profile")
    if isinstance(prof, dict) and prof.get("name") == loc_s:
        return prof

    meta = state.get("meta", {}) or {}
    seed = str(meta.get("seed_pack", "") or "")
    day0 = int(meta.get("day", 1) or 1)

    country, kind = _resolve_country(loc_s)

    r = _h32(seed, "loc_profile", loc_key)
    langs = {
        "indonesia": ["id", "id+en"],
        "united states": ["en"],
        "united kingdom": ["en"],
        "japan": ["ja", "ja+en"],
        "india": ["hi+en", "en"],
        "germany": ["de+en", "de"],
        "france": ["fr+en", "fr"],
        "singapore": ["en+zh", "en"],
    }
    currencies = {
        "indonesia": "IDR",
        "united states": "USD",
        "united kingdom": "GBP",
        "japan": "JPY",
        "india": "INR",
        "germany": "EUR",
        "france": "EUR",
        "singapore": "SGD",
    }

    law_level = _pick(r, ["lenient", "standard", "strict", "militarized"])
    corruption = _pick(r >> 1, ["low", "medium", "high"])
    nightlife = _pick(r >> 2, ["quiet", "mixed", "active", "24_7"])
    tech = _pick(r >> 3, ["low", "medium", "high", "cutting_edge"])

    profile = {
        "name": loc_s,
        "kind": kind,  # city|country
        "country": country,
        "language": _pick(r >> 4, langs.get(country, ["en"])),
        "currency": currencies.get(country, "CR"),
        "law_level": law_level,
        "corruption": corruption,
        "nightlife": nightlife,
        "tech_level": tech,
        "created_day": day0,
        "sig": f"{seed}:{loc_key}:{r}",
    }

    # Cache into location slot.
    slot["profile"] = profile
    locs[loc_key] = slot

    # Also cache country summary into atlas for global view later.
    try:
        ensure_country_profile(state, country)
        ensure_geopolitics(state)
    except Exception:
        pass
    return profile


def fmt_profile_short(profile: dict[str, Any]) -> str:
    """1-line UI-friendly summary."""
    if not isinstance(profile, dict) or not profile:
        return "-"
    name = str(profile.get("name", "-"))
    country = str(profile.get("country", "-"))
    lang = str(profile.get("language", "-"))
    cur = str(profile.get("currency", "-"))
    law = str(profile.get("law_level", "-"))
    tech = str(profile.get("tech_level", "-"))
    return f"{name} ({country}) | lang={lang} | cur={cur} | law={law} | tech={tech}"

