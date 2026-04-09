from __future__ import annotations

import hashlib
import re
import unicodedata
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


def _norm_place_key(raw: str) -> str:
    """Normalize free-text place input for tolerant deterministic matching."""
    s = str(raw or "").strip().lower()
    if not s:
        return ""
    # Strip accents/diacritics (deterministic and locale-agnostic enough for aliases).
    s = unicodedata.normalize("NFKD", s)
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    # Treat punctuation/separators as spaces.
    s = s.replace("_", " ").replace("-", " ")
    s = s.replace(",", " ").replace(".", " ").replace("'", " ")
    # Collapse duplicate whitespace.
    s = re.sub(r"\s+", " ", s).strip()
    return s


# Tiny built-in map for common real-world anchors (extendable later).
_CITY_TO_COUNTRY = {
    "jakarta": "indonesia",
    "london": "united kingdom",
    "tokyo": "japan",
    "new york": "united states",
    "nyc": "united states",
    "los angeles": "united states",
    "san francisco": "united states",
    "seattle": "united states",
    "chicago": "united states",
    "washington dc": "united states",
    "miami": "united states",
    "toronto": "canada",
    "vancouver": "canada",
    "montreal": "canada",
    "mexico city": "mexico",
    "sao paulo": "brazil",
    "rio de janeiro": "brazil",
    "buenos aires": "argentina",
    "santiago": "chile",
    "bogota": "colombia",
    "lima": "peru",
    "madrid": "spain",
    "barcelona": "spain",
    "valencia": "spain",
    "seville": "spain",
    "rome": "italy",
    "milan": "italy",
    "naples": "italy",
    "amsterdam": "netherlands",
    "rotterdam": "netherlands",
    "brussels": "belgium",
    "zurich": "switzerland",
    "geneva": "switzerland",
    "vienna": "austria",
    "stockholm": "sweden",
    "gothenburg": "sweden",
    "oslo": "norway",
    "helsinki": "finland",
    "copenhagen": "denmark",
    "warsaw": "poland",
    "krakow": "poland",
    "prague": "czechia",
    "budapest": "hungary",
    "bucharest": "romania",
    "cluj-napoca": "romania",
    "istanbul": "turkey",
    "ankara": "turkey",
    "izmir": "turkey",
    "moscow": "russia",
    "st petersburg": "russia",
    "kyiv": "ukraine",
    "dubai": "uae",
    "abu dhabi": "uae",
    "doha": "qatar",
    "riyadh": "saudi arabia",
    "tehran": "iran",
    "baghdad": "iraq",
    "cairo": "egypt",
    "alexandria": "egypt",
    "lagos": "nigeria",
    "kano": "nigeria",
    "abidjan": "cote d'ivoire",
    "nairobi": "kenya",
    "mombasa": "kenya",
    "johannesburg": "south africa",
    "cape town": "south africa",
    "casablanca": "morocco",
    "marrakesh": "morocco",
    "singapore": "singapore",
    "paris": "france",
    "lyon": "france",
    "marseille": "france",
    "berlin": "germany",
    "munich": "germany",
    "hamburg": "germany",
    "mumbai": "india",
    # Capitals / defaults for expanded pool (so choosing a country maps to a real city).
    "ottawa": "canada",
    "canberra": "australia",
    "wellington": "new zealand",
    "islamabad": "pakistan",
    "pretoria": "south africa",
    "abuja": "nigeria",
    "rabat": "morocco",
    "brasilia": "brazil",
    "bern": "switzerland",
    "delhi": "india",
    "bangalore": "india",
    "hyderabad": "india",
    "karachi": "pakistan",
    "lahore": "pakistan",
    "bangkok": "thailand",
    "chiang mai": "thailand",
    "hanoi": "vietnam",
    "ho chi minh city": "vietnam",
    "manila": "philippines",
    "cebu": "philippines",
    "kuala lumpur": "malaysia",
    "penang": "malaysia",
    "hong kong": "china",
    "shanghai": "china",
    "beijing": "china",
    "shenzhen": "china",
    "guangzhou": "china",
    "seoul": "south korea",
    "busan": "south korea",
    "taipei": "taiwan",
    "kaohsiung": "taiwan",
    "sydney": "australia",
    "melbourne": "australia",
    "brisbane": "australia",
    "perth": "australia",
    "auckland": "new zealand",
    "christchurch": "new zealand",
    # Additional major anchors for broader Earth-only travel coverage.
    "lisbon": "portugal",
    "porto": "portugal",
    "athens": "greece",
    "thessaloniki": "greece",
    "dublin": "ireland",
    "belfast": "united kingdom",
    "edinburgh": "united kingdom",
    "glasgow": "united kingdom",
    "reykjavik": "iceland",
    "bratislava": "slovakia",
    "sofia": "bulgaria",
    "belgrade": "serbia",
    "zagreb": "croatia",
    "ljubljana": "slovenia",
    "sarajevo": "bosnia and herzegovina",
    "tunis": "tunisia",
    "algiers": "algeria",
    "addis ababa": "ethiopia",
    "accra": "ghana",
    "dar es salaam": "tanzania",
    "kampala": "uganda",
    "dakar": "senegal",
    "luanda": "angola",
    "kinshasa": "democratic republic of the congo",
    "chennai": "india",
    "kolkata": "india",
    "pune": "india",
    "osaka": "japan",
    "nagoya": "japan",
    "fukuoka": "japan",
    "sapporo": "japan",
    "taichung": "taiwan",
    "guadalajara": "mexico",
    "monterrey": "mexico",
    "medellin": "colombia",
    "quito": "ecuador",
    "la paz": "bolivia",
    "san jose": "costa rica",
    "panama city": "panama",
    "havana": "cuba",
    "san juan": "puerto rico",
    "muscat": "oman",
    "amman": "jordan",
    "beirut": "lebanon",
    "jerusalem": "israel",
    "tel aviv": "israel",
}

_COUNTRY_ALIASES = {
    "usa": "united states",
    "us": "united states",
    "uk": "united kingdom",
    "u.k.": "united kingdom",
    "england": "united kingdom",
    "u.a.e.": "uae",
    "united arab emirates": "uae",
    "russian federation": "russia",
    "czech republic": "czechia",
    "holland": "netherlands",
    "south korea": "south korea",
    "korea, south": "south korea",
    "republic of korea": "south korea",
    "ivory coast": "cote d'ivoire",
    "cote divoire": "cote d'ivoire",
    "cote d ivoire": "cote d'ivoire",
    "dr congo": "democratic republic of the congo",
    "drc": "democratic republic of the congo",
    "congo-kinshasa": "democratic republic of the congo",
    "uae": "uae",
}

_CITY_TO_COUNTRY_NORM = {_norm_place_key(k): v for k, v in _CITY_TO_COUNTRY.items()}
_COUNTRY_ALIASES_NORM = {_norm_place_key(k): _norm_place_key(v) for k, v in _COUNTRY_ALIASES.items()}

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
    "canada",
    "mexico",
    "brazil",
    "argentina",
    "chile",
    "colombia",
    "peru",
    "spain",
    "italy",
    "netherlands",
    "belgium",
    "switzerland",
    "austria",
    "sweden",
    "norway",
    "finland",
    "denmark",
    "poland",
    "czechia",
    "hungary",
    "romania",
    "turkey",
    "russia",
    "ukraine",
    "qatar",
    "saudi arabia",
    "iran",
    "iraq",
    "egypt",
    "morocco",
    "nigeria",
    "kenya",
    "south africa",
    "pakistan",
    "thailand",
    "vietnam",
    "philippines",
    "malaysia",
    "china",
    "south korea",
    "taiwan",
    "australia",
    "new zealand",
    # Expanded coverage (kept deterministic; same profile generator path).
    "uae",
    "portugal",
    "greece",
    "ireland",
    "iceland",
    "slovakia",
    "bulgaria",
    "serbia",
    "croatia",
    "slovenia",
    "bosnia and herzegovina",
    "tunisia",
    "algeria",
    "ethiopia",
    "ghana",
    "cote d'ivoire",
    "tanzania",
    "uganda",
    "senegal",
    "angola",
    "democratic republic of the congo",
    "ecuador",
    "bolivia",
    "costa rica",
    "panama",
    "cuba",
    "puerto rico",
    "oman",
    "jordan",
    "lebanon",
    "israel",
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

_COUNTRY_CANON_BY_NORM: dict[str, str] = {}
for _name in (set(_COUNTRY_POOL) | set(_ICONIC_OVERRIDES.keys()) | set(_COUNTRY_ALIASES.values())):
    if isinstance(_name, str) and _name.strip():
        _COUNTRY_CANON_BY_NORM[_norm_place_key(_name)] = _name


def normalize_country_name(raw: str) -> str:
    c = _norm_place_key(raw)
    c = _COUNTRY_ALIASES_NORM.get(c, c)
    return _COUNTRY_CANON_BY_NORM.get(c, c)


def is_known_place(raw: str) -> bool:
    """Earth-only allowlist check.

    Known if it matches:
    - a mapped city in `_CITY_TO_COUNTRY`
    - a country in `_COUNTRY_POOL`
    - a curated override in `_ICONIC_OVERRIDES`
    - a canonical country alias value
    """
    low = _norm_place_key(raw)
    if not low:
        return False
    if low in _CITY_TO_COUNTRY_NORM:
        return True
    c = normalize_country_name(low)
    if c in _COUNTRY_POOL:
        return True
    if c in _ICONIC_OVERRIDES:
        return True
    if c in set(_COUNTRY_ALIASES.values()):
        return True
    return False


def resolve_place(raw: str) -> tuple[str, str]:
    """Return (canonical_country, kind) where kind is 'city' or 'country'."""
    low = _norm_place_key(raw)
    if low in _CITY_TO_COUNTRY_NORM:
        return (_CITY_TO_COUNTRY_NORM[low], "city")
    c = normalize_country_name(low)
    if c in _COUNTRY_POOL or c in _ICONIC_OVERRIDES or c in set(_COUNTRY_ALIASES.values()):
        return (c, "country")
    return ("unknown", "unknown")


def default_city_for_country(country: str, *, seed: str = "") -> str | None:
    """Pick a deterministic default city for a country (Earth-only)."""
    c = normalize_country_name(country)
    cities = [city for city, cc in _CITY_TO_COUNTRY.items() if cc == c]
    if not cities:
        return None
    r = _h32(seed or "seed", "default_city", c)
    return cities[r % len(cities)]


def list_known_cities(country: str | None = None) -> list[str]:
    """List known city anchors; optionally filter by country."""
    if country:
        c = normalize_country_name(country)
        out = sorted([k for k, v in _CITY_TO_COUNTRY.items() if v == c])
        return out
    return sorted(list(_CITY_TO_COUNTRY.keys()))


def list_known_countries() -> list[str]:
    """List known countries supported by Atlas pool/overrides."""
    base = set(_COUNTRY_POOL)
    base |= set(_ICONIC_OVERRIDES.keys())
    base |= set(_COUNTRY_ALIASES.values())
    return sorted([normalize_country_name(x) for x in base if isinstance(x, str) and x.strip()])


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

    # Lightweight real-world mappings for the expanded pool (fallback remains deterministic).
    langs = {
        "indonesia": ["id", "id+en"],
        "united states": ["en"],
        "united kingdom": ["en"],
        "japan": ["ja", "ja+en"],
        "india": ["hi+en", "en"],
        "germany": ["de+en", "de"],
        "france": ["fr+en", "fr"],
        "singapore": ["en+zh", "en"],
        "canada": ["en+fr", "en"],
        "mexico": ["es", "es+en"],
        "brazil": ["pt", "pt+en"],
        "argentina": ["es"],
        "chile": ["es"],
        "colombia": ["es"],
        "peru": ["es"],
        "spain": ["es"],
        "italy": ["it", "it+en"],
        "netherlands": ["nl+en", "nl"],
        "belgium": ["nl+fr", "fr"],
        "switzerland": ["de+fr+it", "de"],
        "austria": ["de"],
        "sweden": ["sv+en", "sv"],
        "norway": ["no+en", "no"],
        "finland": ["fi+en", "fi"],
        "denmark": ["da+en", "da"],
        "poland": ["pl", "pl+en"],
        "czechia": ["cs", "cs+en"],
        "hungary": ["hu", "hu+en"],
        "romania": ["ro", "ro+en"],
        "turkey": ["tr", "tr+en"],
        "russia": ["ru", "ru+en"],
        "ukraine": ["uk", "uk+en"],
        "qatar": ["ar+en", "en"],
        "saudi arabia": ["ar+en", "ar"],
        "iran": ["fa", "fa+en"],
        "iraq": ["ar", "ar+en"],
        "egypt": ["ar", "ar+en"],
        "morocco": ["ar+fr", "ar"],
        "nigeria": ["en"],
        "kenya": ["en+sw", "en"],
        "south africa": ["en", "en+af"],
        "pakistan": ["ur+en", "en"],
        "thailand": ["th", "th+en"],
        "vietnam": ["vi", "vi+en"],
        "philippines": ["en+tl", "en"],
        "malaysia": ["ms+en", "en"],
        "china": ["zh", "zh+en"],
        "south korea": ["ko", "ko+en"],
        "taiwan": ["zh", "zh+en"],
        "australia": ["en"],
        "new zealand": ["en"],
        "uae": ["ar+en", "en"],
        "portugal": ["pt", "pt+en"],
        "greece": ["el", "el+en"],
        "ireland": ["en", "en+ga"],
        "iceland": ["is+en", "is"],
        "slovakia": ["sk", "sk+en"],
        "bulgaria": ["bg", "bg+en"],
        "serbia": ["sr", "sr+en"],
        "croatia": ["hr", "hr+en"],
        "slovenia": ["sl", "sl+en"],
        "bosnia and herzegovina": ["bs+hr+sr", "bs"],
        "tunisia": ["ar+fr", "ar"],
        "algeria": ["ar+fr", "ar"],
        "ethiopia": ["am+en", "am"],
        "ghana": ["en"],
        "cote d'ivoire": ["fr", "fr+en"],
        "tanzania": ["sw+en", "sw"],
        "uganda": ["en+sw", "en"],
        "senegal": ["fr+wo", "fr"],
        "angola": ["pt", "pt+en"],
        "democratic republic of the congo": ["fr+ln", "fr"],
        "ecuador": ["es"],
        "bolivia": ["es", "es+qu"],
        "costa rica": ["es", "es+en"],
        "panama": ["es", "es+en"],
        "cuba": ["es"],
        "puerto rico": ["es+en", "es"],
        "oman": ["ar+en", "ar"],
        "jordan": ["ar+en", "ar"],
        "lebanon": ["ar+fr", "ar"],
        "israel": ["he+ar+en", "he"],
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
        "canada": "CAD",
        "mexico": "MXN",
        "brazil": "BRL",
        "argentina": "ARS",
        "chile": "CLP",
        "colombia": "COP",
        "peru": "PEN",
        "spain": "EUR",
        "italy": "EUR",
        "netherlands": "EUR",
        "belgium": "EUR",
        "switzerland": "CHF",
        "austria": "EUR",
        "sweden": "SEK",
        "norway": "NOK",
        "finland": "EUR",
        "denmark": "DKK",
        "poland": "PLN",
        "czechia": "CZK",
        "hungary": "HUF",
        "romania": "RON",
        "turkey": "TRY",
        "russia": "RUB",
        "ukraine": "UAH",
        "qatar": "QAR",
        "saudi arabia": "SAR",
        "iran": "IRR",
        "iraq": "IQD",
        "egypt": "EGP",
        "morocco": "MAD",
        "nigeria": "NGN",
        "kenya": "KES",
        "south africa": "ZAR",
        "pakistan": "PKR",
        "thailand": "THB",
        "vietnam": "VND",
        "philippines": "PHP",
        "malaysia": "MYR",
        "china": "CNY",
        "south korea": "KRW",
        "taiwan": "TWD",
        "australia": "AUD",
        "new zealand": "NZD",
        "uae": "AED",
        "portugal": "EUR",
        "greece": "EUR",
        "ireland": "EUR",
        "iceland": "ISK",
        "slovakia": "EUR",
        "bulgaria": "BGN",
        "serbia": "RSD",
        "croatia": "EUR",
        "slovenia": "EUR",
        "bosnia and herzegovina": "BAM",
        "tunisia": "TND",
        "algeria": "DZD",
        "ethiopia": "ETB",
        "ghana": "GHS",
        "cote d'ivoire": "XOF",
        "tanzania": "TZS",
        "uganda": "UGX",
        "senegal": "XOF",
        "angola": "AOA",
        "democratic republic of the congo": "CDF",
        "ecuador": "USD",
        "bolivia": "BOB",
        "costa rica": "CRC",
        "panama": "PAB",
        "cuba": "CUP",
        "puerto rico": "USD",
        "oman": "OMR",
        "jordan": "JOD",
        "lebanon": "LBP",
        "israel": "ILS",
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
    row.setdefault("history_idx", {})
    row.setdefault("market_profile", {})
    row.setdefault("market", {})
    countries[c] = row
    atlas["countries"] = countries
    world["atlas"] = atlas
    return row


def ensure_country_history_idx(state: dict[str, Any], country: str, *, sim_year: int | None = None) -> dict[str, Any]:
    """Compute abstract real-world-leaning history indices for a country at a given sim year.

    Stored in `world.atlas.countries[country].history_idx` with `last_year` caching.
    """
    row = ensure_country_profile(state, country)
    hidx = row.get("history_idx") if isinstance(row, dict) else None
    if not isinstance(hidx, dict):
        hidx = {}
        row["history_idx"] = hidx

    meta = state.get("meta", {}) or {}
    if sim_year is None:
        try:
            sim_year = int(meta.get("sim_year", 0) or 0)
        except Exception:
            sim_year = 0
    if not sim_year:
        try:
            from engine.world.time_model import sim_year_from_state

            sim_year = sim_year_from_state(state)
        except Exception:
            sim_year = 2025
    y = int(sim_year)

    last = int(hidx.get("last_year", 0) or 0)
    if last == y and hidx:
        return hidx

    seed = str(meta.get("world_seed", "") or meta.get("seed_pack", "") or "")
    c = normalize_country_name(country)
    rr = _h32(seed, "history", c, y)

    # Era tags
    if y < 1900:
        era = "pre_modern"
    elif y < 1914:
        era = "early_modern"
    elif y <= 1918:
        era = "ww1"
    elif y < 1939:
        era = "interwar"
    elif y <= 1945:
        era = "ww2"
    elif y < 1991:
        era = "cold_war"
    elif y < 2001:
        era = "post_cold_war"
    elif y < 2020:
        era = "globalized"
    else:
        era = "contemporary"

    # war status (none|regional|world)
    war = "none"
    if era in ("ww1", "ww2"):
        war = "world"
    elif era in ("cold_war",):
        war = "regional" if (rr % 3) == 0 else "none"
    elif y >= 2001 and (rr % 7) == 0:
        war = "regional"

    # border controls (0..100)
    border = 20 + int(rr % 35)  # baseline 20..54
    if war == "world":
        border += 35
    elif war == "regional":
        border += 18
    if y < 1950:
        border += 10
    border = max(0, min(100, border))

    # censorship (0..100)
    censor = 15 + int((_h32(seed, "censor", c, y) % 55))  # 15..69
    if war != "none":
        censor += 15
    # some countries trend higher, but keep abstract
    if c in ("russia", "china", "iran"):
        censor += 12
    censor = max(0, min(100, censor))

    # discrimination (0..100) – higher in earlier eras, gradually declines.
    discr = 25 + int((_h32(seed, "discr", c, y) % 45))  # 25..69
    if y < 1950:
        discr += 20
    elif y < 1980:
        discr += 10
    elif y >= 2010:
        discr -= 8
    discr = max(0, min(100, discr))

    # slavery legal (abstract; only for early eras)
    slavery = False
    if y <= 1865:
        slavery = c in ("united states", "brazil") or (rr % 10) == 0

    hidx.update(
        {
            "last_year": y,
            "era_tag": era,
            "war_status": war,
            "border_controls": int(border),
            "discrimination_idx": int(discr),
            "censorship_idx": int(censor),
            "slavery_legal": bool(slavery),
        }
    )
    row["history_idx"] = hidx
    return hidx


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
    # History indices (year-aware constraints) influence markets as well.
    try:
        meta = state.get("meta", {}) or {}
        sy = int(meta.get("sim_year", 0) or 0)
    except Exception:
        sy = 0
    hi = ensure_country_history_idx(state, country, sim_year=sy)
    war = str((hi.get("war_status") if isinstance(hi, dict) else "none") or "none").lower()
    border = int((hi.get("border_controls", 0) if isinstance(hi, dict) else 0) or 0)

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

    # History constraints: border controls and war add friction/scarcity.
    if war == "world":
        bump("transport", dpx=+6, dsc=+8)
        bump("electronics", dpx=+4, dsc=+6)
        bump("food", dpx=+2, dsc=+4)
    elif war == "regional":
        bump("transport", dpx=+3, dsc=+4)
        bump("electronics", dpx=+2, dsc=+3)
    if border >= 80:
        bump("transport", dpx=+3, dsc=+3)
        bump("electronics", dpx=+2, dsc=+2)
    elif border >= 60:
        bump("transport", dpx=+2, dsc=+2)

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
    raw_low = str(raw or "").strip().lower()
    low = _norm_place_key(raw)
    low = _COUNTRY_ALIASES_NORM.get(low, low)

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
    if "," in raw_low:
        parts = [_norm_place_key(p) for p in raw_low.split(",") if p.strip()]
        if len(parts) >= 2:
            return (_COUNTRY_ALIASES_NORM.get(parts[-1], parts[-1]), "city")
    toks = [t for t in low.split() if t]
    if len(toks) >= 2:
        tail2 = " ".join(toks[-2:])
        tail1 = toks[-1]
        if tail2 in _COUNTRY_ALIASES_NORM:
            return (_COUNTRY_ALIASES_NORM[tail2], "city")
        if tail1 in _COUNTRY_ALIASES_NORM:
            return (_COUNTRY_ALIASES_NORM[tail1], "city")

    # Known city anchors.
    if low in _CITY_TO_COUNTRY_NORM:
        return (_CITY_TO_COUNTRY_NORM[low], "city")

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
    # Reuse country profile for language/currency when possible (expanded pool support).
    cprof = ensure_country_profile(state, country)
    dom_lang = str(cprof.get("dominant_lang", "en") or "en") if isinstance(cprof, dict) else "en"
    currency = str(cprof.get("currency", "CR") or "CR") if isinstance(cprof, dict) else "CR"

    law_level = _pick(r, ["lenient", "standard", "strict", "militarized"])
    corruption = _pick(r >> 1, ["low", "medium", "high"])
    nightlife = _pick(r >> 2, ["quiet", "mixed", "active", "24_7"])
    tech = _pick(r >> 3, ["low", "medium", "high", "cutting_edge"])

    profile = {
        "name": loc_s,
        "kind": kind,  # city|country
        "country": country,
        "language": dom_lang,
        "currency": currency,
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

