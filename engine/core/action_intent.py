from __future__ import annotations

import re
from typing import Any

from engine.core.action_registry import (
    get_registry_action_by_id,
    inquiry_phrases_match,
    iter_registry_matches_by_prefix,
    match_registry_action,
    match_registry_action_prefixed,
    sanitize_registry_action_id_hint,
)
from engine.core.action_registry_handlers import apply_registry_handler
from engine.core.errors import record_error
from engine.systems.combat import get_active_weapon

# Amati keramaian / cari orang di sekitar (bukan combat, bukan evasion).
_SOCIAL_SCAN_PHRASES = (
    "mencari orang",
    "cari orang",
    "orang sekitar",
    "lihat sekitar",
    "lihat orang",
    "perhatikan sekitar",
    "perhatiin sekitar",
    "siapa di sekitar",
    "ada siapa",
    "cek sekitar",
    "intip sekitar",
    "pantau sekitar",
    "keliling cari",
    "scope crowd",
    "look around for",
    "who's around",
    "siapa saja di",
)
_PEOPLE_WORDS = ("cewe", "cewek", "cowo", "cowok", "wanita", "pria", "orang", "orang-orang", "manusia", "warga")

_SOCIAL_CONFLICT_WORDS = (
    "ancam",
    "mengancam",
    "paksa",
    "memaksa",
    "intimidasi",
    "blackmail",
    "peras",
    "memeras",
    "ultimatum",
    "tipu",
    "menipu",
    "bohong",
    "negosiasi",
    "tawar",
    "tawar-menawar",
    "manipulasi",
    "yakinkan",
    "gaslight",
)


def _is_social_inquiry(t: str) -> bool:
    """Tanya info (bukan evasion). Frasa substring diselaraskan dengan ``social.inquiry.*`` di registry."""
    tnorm = (t or "").strip().lower()
    if not tnorm:
        return False
    try:
        return inquiry_phrases_match(tnorm)
    except Exception:
        return "?" in tnorm


def _is_social_dialogue(t: str) -> bool:
    """Ajakan bicara / ngobrol — prioritas di atas scan keramaian."""
    if any(
        k in t
        for k in (
            "bicara",
            "berbicara",
            "ngobrol",
            "obrol",
            "sapa",
            "salam",
            "halo",
            "hai ",
            "hey ",
            "greet",
            "talk to",
            "speak to",
            "chat ",
        )
    ):
        return True
    if any(p in t for p in ("dengan orang", "ke orang", "sama orang", "orang di sekitar")):
        return True
    return False


def _parse_accommodation_intent(t: str) -> dict[str, Any] | None:
    """Detect prepaid short-stay phrasing (hotel/boarding/suite night).

    Does not mutate state — only hints the narrator / turn package. Actual charges
    are applied via `STAY <tier> <nights>` (or future engine hooks).
    """
    t = (t or "").strip().lower()
    if not t:
        return None
    night_ok = (
        "semalam" in t
        or "semaleman" in t
        or "satu malam" in t
        or "overnight" in t
        or "one night" in t
        or bool(re.search(r"\b1\s*(?:malam|night|nights)\b", t))
        or bool(re.search(r"\b(\d+)\s*(?:malam|night|nights)\b", t))
    )
    if not night_ok:
        return None
    lodging_ok = any(
        k in t
        for k in (
            "hotel",
            "motel",
            "inn",
            "hostel",
            "guesthouse",
            "kos",
            "kost",
            "boarding",
            "dorm",
            "suite",
            "penthouse",
            "luxury",
            "nginap",
            "menginap",
            "booking",
            "check in",
            "check-in",
            "reservasi",
            "reservation",
            "sewa kamar",
            "book a room",
            "book room",
            "kamar",
        )
    )
    if not lodging_ok and ("stay" in t or "menginap" in t):
        lodging_ok = True
    if not lodging_ok:
        return None
    # Travel-only "pergi ke X" without lodging intent — skip (destination trip, not a room booking).
    if "pergi ke" in t or "menuju" in t:
        if not any(k in t for k in ("nginap", "menginap", "stay", "booking", "check in", "check-in", "hotel", "hostel", "kos", "kost", "suite", "kamar")):
            return None
    nights = 1
    m = re.search(r"\b(\d+)\s*(?:malam|night|nights)\b", t)
    if m:
        nights = max(1, min(365, int(m.group(1))))
    if re.search(r"\b(?:satu|1)\s+malam\b", t) or "semalam" in t or "one night" in t or re.search(r"\b1\s+night\b", t):
        nights = 1
    kind: str | None = None
    if any(x in t for x in ("suite", "penthouse")) or ("luxury" in t and "hotel" in t):
        kind = "suite"
    elif any(x in t for x in ("hostel", "dorm", "guesthouse", "kos", "kost", "boarding")):
        kind = "kos"
    elif any(x in t for x in ("hotel", "motel", "inn")):
        kind = "hotel"
    return {"nights": nights, "kind": kind, "parser": "accommodation_nl"}


_INTIMACY_FORCE_BLOCK = (
    "paksa",
    "memaksa",
    "perkosa",
    "rape",
    "coerce",
    "forced",
)


def _is_intimacy_private(t: str) -> bool:
    """Consensual private intimacy (engine: fade-to-black + aftermath). Blocked if coercion cues."""
    t = (t or "").strip().lower()
    if not t:
        return False
    if any(b in t for b in _INTIMACY_FORCE_BLOCK):
        return False
    if any(k in t for k in _SOCIAL_CONFLICT_WORDS):
        return False
    return any(
        k in t
        for k in (
            "have sex",
            "make love",
            "making love",
            "sleep with",
            "slept with",
            "hook up",
            "hookup",
            "get laid",
            "bed with",
            "in bed with",
            "love making",
            "bercinta",
            "berhubungan badan",
            "hubungan badan",
            "berhubungan intim",
            "hubungan intim",
        )
    )


def _registry_try_intimacy_private_nl(ctx: dict[str, Any], t: str, player_input: str) -> bool:
    """Consensual private intimacy; guard ``_is_intimacy_private``; ``ctx_patch`` + handler di registry."""
    if not _is_intimacy_private(t):
        return False
    m = get_registry_action_by_id("social.nl_intimacy_private")
    if not m:
        return False
    patch = m.get("ctx_patch") if isinstance(m.get("ctx_patch"), dict) else {}
    for k, v in patch.items():
        ctx[k] = v
    ctx["registry_action_id"] = str(m.get("id", "") or "").strip()
    _invoke_registry_handler_from_match(m, ctx, t, player_input)
    return True


def _is_social_scan(t: str) -> bool:
    if any(p in t for p in _SOCIAL_SCAN_PHRASES):
        return True
    # "coba cari ... cewe" / "cari wanita di sekitar"
    if "cari" in t and any(w in t for w in _PEOPLE_WORDS):
        return True
    if any(w in t for w in ("mengintai", "mengamati", "mata-matai", "people watching", "perhatiin orang")):
        return True
    return False


def _parse_sleep_hours(t: str) -> int | None:
    txt = str(t or "").strip().lower()
    if not txt:
        return None
    # Explicit duration first so "aku mau tidur 6 jam" is not treated as default 8h.
    m = re.search(r"\b(?:aku|saya)\s+mau\s+tidur\s+(\d{1,2})(?:\s*(?:jam|hours?|h))?\b", txt)
    if m:
        try:
            return max(1, min(12, int(m.group(1))))
        except Exception:
            return 8
    m = re.search(r"\b(?:sleep|tidur)\s+(\d{1,2})(?:\s*(?:jam|hours?|h))?\b", txt)
    if m:
        try:
            return max(1, min(12, int(m.group(1))))
        except Exception:
            return 8
    m = re.search(r"\b(\d{1,2})\s*(?:jam|hours?|h)\b", txt)
    if m and ("tidur" in txt or "sleep" in txt):
        try:
            return max(1, min(12, int(m.group(1))))
        except Exception:
            return 8
    # Natural-language sleep intent (no duration → default 8h).
    if re.search(r"\b(ingin|pengen)\s+tidur\b", txt):
        return 8
    if any(p in txt for p in ("want to sleep", "need to sleep", "going to sleep", "gonna sleep")):
        return 8
    if re.search(r"\b(try|need)\s+to\s+sleep\b", txt):
        return 8
    if re.search(r"\b(coba|try)\s+(tidur|to\s+sleep)\b", txt):
        return 8
    if re.search(r"\bperlu\s+tidur\b", txt):
        return 8
    if "istirahat tidur" in txt or "rest and sleep" in txt or "get some sleep" in txt:
        return 8
    if txt in ("sleep", "tidur", "aku mau tidur", "saya mau tidur"):
        return 8
    return None


def _invoke_registry_handler_from_match(m: dict[str, Any], ctx: dict[str, Any], t: str, raw: str) -> None:
    hn = str((m or {}).get("handler") or "").strip()
    if not hn:
        return
    try:

        apply_registry_handler(hn, ctx, t, raw)
    except Exception:
        pass


def _registry_try_sleep(ctx: dict[str, Any], t: str, player_input: str) -> bool:
    """Apply sleep intent from action registry when it is not a prepaid-stay booking."""
    if _parse_accommodation_intent(t) is not None:
        return False
    m = match_registry_action(player_input)
    if not m or not str(m.get("id", "") or "").startswith("sleep."):
        return False
    patch = m.get("ctx_patch") if isinstance(m.get("ctx_patch"), dict) else {}
    for k, v in patch.items():
        ctx[k] = v
    ctx["registry_action_id"] = str(m.get("id", "") or "").strip()
    _invoke_registry_handler_from_match(m, ctx, t, player_input)
    return True


_NL_ATTEMPT_MARKERS = (
    "mencoba",
    "try to",
    "trying to",
    "coba ",
    "ingin ",
    "want to",
    "going to",
)


def _registry_try_combat(ctx: dict[str, Any], t: str, player_input: str) -> bool:
    """Apply combat intent from action registry (ranged/melee); legacy elif remains fallback."""
    m = match_registry_action(player_input)
    if not m or not str(m.get("id", "") or "").startswith("combat."):
        return False
    patch = m.get("ctx_patch") if isinstance(m.get("ctx_patch"), dict) else {}
    for k, v in patch.items():
        if k == "intent_note":
            continue
        ctx[k] = v
    ctx["registry_action_id"] = str(m.get("id", "") or "").strip()
    if any(x in t for x in _NL_ATTEMPT_MARKERS):
        ctx["intent_note"] = "nl_attempt"
    _invoke_registry_handler_from_match(m, ctx, t, player_input)
    return True


_TRAVEL_LEGACY_KEYWORDS = (
    "travel",
    "pergi ke",
    "naik",
    "menuju",
    "balik ke",
    "pulang ke",
    "kembali ke",
    "balik",
    "pulang",
    "kembali",
)


def _apply_travel_heuristics(ctx: dict[str, Any], t: str, player_input: str) -> None:
    """Shared travel NL: duration hints, destination extract, vehicle hints (registry + legacy)."""
    ctx["action_type"] = "travel"
    if any(k in t for k in ["dekat", "sekitar", "deket", "dekat sini", "sekitar sini", "dekat sana"]):
        ctx["travel_minutes"] = 10
    elif any(k in t for k in ["balik", "pulang", "kembali"]) and any(k in t for k in ["ke"]):
        ctx["travel_minutes"] = 15
    elif any(k in t for k in ["jauh", "jauhnya", "jauh banget", "antar kota", "beda kota", "lintas", "seberang", "lumayan jauh"]):
        ctx["travel_minutes"] = 90
    else:
        ctx["travel_minutes"] = 30

    m = re.search(r"\b(?:ke|menuju|pulang ke|balik ke|kembali ke)\s+([a-zA-Z][a-zA-Z0-9\s\-']{2,40})", t)
    if m:
        dest_raw = m.group(1).strip()
        for cut in (" dengan ", " pakai ", " untuk ", " agar ", " lalu ", " sambil ", " sebelum ", " setelah ", " dan ", ","):
            if cut in (" " + dest_raw + " "):
                dest_raw = dest_raw.split(cut.strip(), 1)[0].strip()
        dest_raw = dest_raw.strip(" .,!?:;\"'")
        if dest_raw:
            ctx["travel_destination"] = dest_raw
    if not ctx.get("travel_destination"):
        m2 = re.search(r"\b(?:head to|heading to|commute to)\s+([a-zA-Z][a-zA-Z0-9\s\-']{2,40})", t)
        if m2:
            dest_raw = m2.group(1).strip()
            for cut in (" dengan ", " pakai ", " untuk ", " agar ", " lalu ", " sambil ", " sebelum ", " setelah ", " dan ", ","):
                if cut in (" " + dest_raw + " "):
                    dest_raw = dest_raw.split(cut.strip(), 1)[0].strip()
            dest_raw = dest_raw.strip(" .,!?:;\"'")
            if dest_raw:
                ctx["travel_destination"] = dest_raw
    try:

        def _contains_term(hay: str, needle: str) -> bool:
            n = str(needle or "").strip().lower()
            if not n:
                return False
            return re.search(rf"(?<![a-z0-9_]){re.escape(n)}(?![a-z0-9_])", hay) is not None

        veh_map = {
            "sepeda": "bicycle",
            "bicycle": "bicycle",
            "bike": "bicycle",
            "motor": "motorcycle",
            "motorcycle": "motorcycle",
            "moge": "motorcycle",
            "mobil": "car_standard",
            "car": "car_standard",
            "sedan": "car_standard",
            "van": "car_van",
            "minivan": "car_van",
            "sportscar": "car_sports",
            "sports car": "car_sports",
            "sport": "car_sports",
        }
        for vid in ("bicycle", "motorcycle", "car_standard", "car_sports", "car_van"):
            if _contains_term(t, vid):
                ctx["vehicle_id"] = vid
                break
        if "vehicle_id" not in ctx:
            for k, vid in veh_map.items():
                if _contains_term(t, k):
                    ctx["vehicle_id"] = vid
                    break
        if "vehicle_id" in ctx:
            ctx.setdefault("intent_note", "travel_by_vehicle")
    except Exception:
        pass


def _registry_try_travel(ctx: dict[str, Any], t: str, player_input: str) -> bool:
    """Registry-first travel NL; `_TRAVEL_LEGACY_KEYWORDS` remains fallback."""
    m = match_registry_action(player_input)
    if not m or not str(m.get("id", "") or "").startswith("travel."):
        return False
    patch = m.get("ctx_patch") if isinstance(m.get("ctx_patch"), dict) else {}
    for k, v in patch.items():
        if k == "intent_note":
            continue
        ctx[k] = v
    ctx["registry_action_id"] = str(m.get("id", "") or "").strip()
    _apply_travel_heuristics(ctx, t, player_input)
    _invoke_registry_handler_from_match(m, ctx, t, player_input)
    return True


_SKILL_DOMAIN_PREFIXES = ("hacking.", "medical.", "driving.", "stealth.")

_HACKING_LEGACY_KEYWORDS = ("hack", "retas", "bypass", "terminal")
_MEDICAL_LEGACY_KEYWORDS = ("rawat", "obati", "jahit luka")
_DRIVING_LEGACY_KEYWORDS = ("nyetir", "driving", "mengemudi")
_STEALTH_LEGACY_KEYWORDS = ("mengendap", "stealth", "diam-diam")


def _registry_try_skill_domain(ctx: dict[str, Any], t: str, player_input: str) -> bool:
    """Registry-first domain hints (hacking / medical / driving / stealth); legacy elif remains."""
    m = match_registry_action(player_input)
    if not m:
        return False
    aid = str(m.get("id", "") or "").strip()
    if not any(aid.startswith(p) for p in _SKILL_DOMAIN_PREFIXES):
        return False
    patch = m.get("ctx_patch") if isinstance(m.get("ctx_patch"), dict) else {}
    for k, v in patch.items():
        ctx[k] = v
    ctx["registry_action_id"] = aid
    _invoke_registry_handler_from_match(m, ctx, t, player_input)
    return True


_SOCIAL_NL_PREFIX = "social."


def _registry_try_social_nl(ctx: dict[str, Any], t: str, player_input: str) -> bool:
    """Registry-first social dialogue / crowd scan (subset of legacy `_is_*` heuristics)."""
    m = match_registry_action_prefixed(player_input, _SOCIAL_NL_PREFIX)
    if not m:
        return False
    aid = str(m.get("id", "") or "").strip()
    if not aid.startswith(_SOCIAL_NL_PREFIX):
        return False
    patch = m.get("ctx_patch") if isinstance(m.get("ctx_patch"), dict) else {}
    for k, v in patch.items():
        ctx[k] = v
    ctx["registry_action_id"] = aid
    _invoke_registry_handler_from_match(m, ctx, t, player_input)
    return True


_NEGOTIATION_NL_KEYWORDS = ("negosiasi", "bohong", "yakinkan")


def _registry_try_social_negotiation_nl(ctx: dict[str, Any], t: str, player_input: str) -> bool:
    """Deception / negotiation phrasing; ``ctx_patch`` + handler live in ``social.nl_negotiation`` (code-resolved id)."""
    if not any(k in t for k in _NEGOTIATION_NL_KEYWORDS):
        return False
    m = get_registry_action_by_id("social.nl_negotiation")
    if not m:
        return False
    patch = m.get("ctx_patch") if isinstance(m.get("ctx_patch"), dict) else {}
    for k, v in patch.items():
        ctx[k] = v
    ctx["registry_action_id"] = str(m.get("id", "") or "").strip()
    _invoke_registry_handler_from_match(m, ctx, t, player_input)
    return True


def _registry_try_social_conflict_nl(ctx: dict[str, Any], t: str, player_input: str) -> bool:
    """Conflict toward people (AND of cues); ``ctx_patch`` is ``social.nl_conflict`` in registry (code-resolved id)."""
    if not (any(k in t for k in _SOCIAL_CONFLICT_WORDS) and any(w in t for w in _PEOPLE_WORDS)):
        return False
    m = get_registry_action_by_id("social.nl_conflict")
    if not m:
        return False
    patch = m.get("ctx_patch") if isinstance(m.get("ctx_patch"), dict) else {}
    for k, v in patch.items():
        ctx[k] = v
    ctx["registry_action_id"] = str(m.get("id", "") or "").strip()
    _invoke_registry_handler_from_match(m, ctx, t, player_input)
    return True


_SOCIAL_INQUIRY_PREFIX = "social.inquiry."

# Satu kata / slang: istirahat singkat (60m), tanpa substring "istirahat tidur" (itu tidur).
_REST_ISTIRAHAT_EXACT: frozenset[str] = frozenset(
    {
        "istirahat",
        "istirahat.",
        "gw istirahat",
        "gua istirahat",
        "gue istirahat",
    }
)


def _registry_try_rest_short_nl(ctx: dict[str, Any], t: str, player_input: str) -> bool:
    """Istirahat singkat 60m: frasa ID di registry ``rest.nl_*``, plus ``rest …`` (inggris)."""
    t2 = str(t or "").strip().lower()
    m: dict[str, Any] | None = None
    m = match_registry_action_prefixed(str(player_input or ""), "rest.")
    if not m or not str(m.get("id", "") or "").strip().startswith("rest."):
        m = None
    if m is None and t2.startswith("rest "):
        m = get_registry_action_by_id("rest.nl_prefix_60m")
    if m is None and t2 in _REST_ISTIRAHAT_EXACT:
        m = get_registry_action_by_id("rest.nl_prefix_60m")
    if not m:
        return False
    patch = m.get("ctx_patch") if isinstance(m.get("ctx_patch"), dict) else {}
    for k, v in patch.items():
        ctx[k] = v
    ctx["registry_action_id"] = str(m.get("id", "") or "").strip()
    _invoke_registry_handler_from_match(m, ctx, t, player_input)
    return True


def _registry_try_social_inquiry_nl(ctx: dict[str, Any], t: str, player_input: str) -> bool:
    """Subset of `_is_social_inquiry` phrases via registry (`?` + question cues in JSON)."""
    m = match_registry_action_prefixed(player_input, _SOCIAL_INQUIRY_PREFIX)
    if not m:
        return False
    aid = str(m.get("id", "") or "").strip()
    if not aid.startswith(_SOCIAL_INQUIRY_PREFIX):
        return False
    patch = m.get("ctx_patch") if isinstance(m.get("ctx_patch"), dict) else {}
    for k, v in patch.items():
        ctx[k] = v
    ctx["registry_action_id"] = aid
    _invoke_registry_handler_from_match(m, ctx, t, player_input)
    return True


_INSTANT_NL_PREFIX = "instant."

_TRIVIAL_LEGACY_KEYWORDS = ("lihat status", "cek tas", "jalan santai", "minum air")


def _apply_trivial_realism_flags(ctx: dict[str, Any]) -> None:
    ctx["trivial_action"] = True
    ctx["trivial"] = True
    ctx["uncertain"] = False
    ctx["has_stakes"] = False
    ctx["risk_level"] = "low"


def _registry_try_instant_physically_impossible(ctx: dict[str, Any], t: str, player_input: str) -> bool:
    """Realism gate — mustahil fisik; ``instant.nl_physically_impossible``."""
    m = match_registry_action_prefixed(str(player_input or ""), _INSTANT_NL_PREFIX)
    if not m or str(m.get("id", "") or "").strip() != "instant.nl_physically_impossible":
        return False
    patch = m.get("ctx_patch") if isinstance(m.get("ctx_patch"), dict) else {}
    for k, v in patch.items():
        ctx[k] = v
    ctx["registry_action_id"] = str(m.get("id", "") or "").strip()
    _invoke_registry_handler_from_match(m, ctx, t, player_input)
    return True


def _registry_try_instant_clear_jam(ctx: dict[str, Any], t: str, player_input: str) -> bool:
    """Weapon jam clear (W2-ish); ``instant.nl_clear_jam`` in registry."""
    m = match_registry_action_prefixed(str(player_input or ""), _INSTANT_NL_PREFIX)
    if not m or str(m.get("id", "") or "").strip() != "instant.nl_clear_jam":
        return False
    patch = m.get("ctx_patch") if isinstance(m.get("ctx_patch"), dict) else {}
    for k, v in patch.items():
        ctx[k] = v
    ctx["registry_action_id"] = str(m.get("id", "") or "").strip()
    _invoke_registry_handler_from_match(m, ctx, t, player_input)
    return True


def _registry_apply_all_instant_stop_nl(ctx: dict[str, Any], t: str, player_input: str) -> None:
    """Terapkan semua entri ``instant.nl_stop_*`` yang cocok (bukan hanya yang pertama)."""
    for m in iter_registry_matches_by_prefix(str(player_input or ""), "instant.nl_stop_"):
        patch = m.get("ctx_patch") if isinstance(m.get("ctx_patch"), dict) else {}
        for k, v in patch.items():
            ctx[k] = v
        hn = str((m or {}).get("handler") or "").strip()
        if hn:
            apply_registry_handler(hn, ctx, t, player_input)


def _registry_try_instant_trivial(ctx: dict[str, Any], t: str, player_input: str) -> bool:
    """Trivial realism via `instant.*` registry (add-only synonyms in JSON)."""
    if ctx.get("registry_action_id"):
        return False
    m = match_registry_action_prefixed(player_input, _INSTANT_NL_PREFIX)
    if not m or not str(m.get("id", "") or "").strip().startswith(_INSTANT_NL_PREFIX):
        return False
    patch = m.get("ctx_patch") if isinstance(m.get("ctx_patch"), dict) else {}
    for k, v in patch.items():
        ctx[k] = v
    ctx["registry_action_id"] = str(m.get("id", "") or "").strip()
    _invoke_registry_handler_from_match(m, ctx, t, player_input)
    return True


def _apply_smartphone_ctx_defaults(ctx: dict[str, Any]) -> None:
    ctx["action_type"] = "instant"
    ctx["domain"] = "other"
    ctx["intent_note"] = "smartphone"
    ctx["registry_action_id"] = "other.nl_smartphone_w2"
    ctx["has_stakes"] = False
    ctx["uncertain"] = False
    ctx["trivial"] = True
    ctx["risk_level"] = "low"
    ctx["stakes"] = "none"
    try:
        im = int(ctx.get("instant_minutes", 0) or 0)
    except Exception:
        im = 0
    ctx["instant_minutes"] = max(im, 2)


def _parse_smartphone_fills(ctx: dict[str, Any], raw_in: str, t: str) -> bool:
    """NL + light English patterns for W2-11 smartphone ops."""
    tnorm = str(t or "").strip().lower()
    if not tnorm:
        return False

    m = re.match(r"^(phone|smartphone|hp)\s+(on|off|status)\s*$", tnorm)
    if m:
        ctx["smartphone_op"] = {"op": "power", "value": str(m.group(2) or "").strip().lower()}
        _apply_smartphone_ctx_defaults(ctx)
        return True

    if re.search(r"\b(matikan|turn off|switch off)\s+(hp|ponsel|smartphone|phone)\b", tnorm):
        ctx["smartphone_op"] = {"op": "power", "value": "off"}
        _apply_smartphone_ctx_defaults(ctx)
        return True
    if re.search(r"\b(nyalakan|turn on|switch on|hidupkan)\s+(hp|ponsel|smartphone|phone)\b", tnorm):
        ctx["smartphone_op"] = {"op": "power", "value": "on"}
        _apply_smartphone_ctx_defaults(ctx)
        return True

    m2 = re.search(
        r"\b(telepon|panggil|call)\s+([a-zA-Z][a-zA-Z0-9_'\-]{0,40})\b",
        str(raw_in or "").strip(),
        flags=re.I,
    )
    if m2:
        ctx["smartphone_op"] = {"op": "call", "target": str(m2.group(2) or "").strip()}
        _apply_smartphone_ctx_defaults(ctx)
        ctx["instant_minutes"] = max(int(ctx.get("instant_minutes", 0) or 0), 4)
        return True

    m3 = re.search(
        r"\b(sms|pesan ke|message to|wa ke|chat ke)\s+([a-zA-Z][a-zA-Z0-9_'\-]{1,40})\s+(.{1,220})$",
        tnorm,
    )
    if m3:
        ctx["smartphone_op"] = {
            "op": "message",
            "target": str(m3.group(2) or "").strip(),
            "body": str(m3.group(3) or "").strip(),
        }
        _apply_smartphone_ctx_defaults(ctx)
        ctx["instant_minutes"] = max(int(ctx.get("instant_minutes", 0) or 0), 3)
        return True
    m3b = re.search(
        r"^(sms|pesan|message|wa|chat)\s+([a-zA-Z][a-zA-Z0-9_'\-]{1,40})\s+(.{1,220})$",
        tnorm,
    )
    if m3b:
        ctx["smartphone_op"] = {
            "op": "message",
            "target": str(m3b.group(2) or "").strip(),
            "body": str(m3b.group(3) or "").strip(),
        }
        _apply_smartphone_ctx_defaults(ctx)
        ctx["instant_minutes"] = max(int(ctx.get("instant_minutes", 0) or 0), 3)
        return True

    if re.search(r"\b(dark\s*web|darkweb|deep\s*web|darknet)\b", tnorm):
        ctx["smartphone_op"] = {"op": "dark_web"}
        _apply_smartphone_ctx_defaults(ctx)
        ctx["instant_minutes"] = max(int(ctx.get("instant_minutes", 0) or 0), 12)
        return True

    return False


def parse_action_intent(player_input: str) -> dict[str, Any]:
    t = player_input.strip().lower()
    ctx: dict[str, Any] = {
        "normalized_input": t,
        "action_type": "instant",
        "domain": "evasion",
        "trained": True,
        "uncertain": True,
        "has_stakes": True,
        "risk_level": "medium",
        "trivial": False,
        "impossible": False,
        "stop_triggers": [],
    }

    # Domain/action inference
    combat_terms = (
        "attack",
        "serang",
        "stab",
        "pukul",
        # Indo firearm verbs (note: 'menembak' does NOT contain 'tembak')
        "menembak",
        "menembakan",
        "nembak",
        "tembak",
        "tembakin",
        "shoot",
    )
    if _parse_smartphone_fills(ctx, player_input, t):
        pass
    elif _registry_try_combat(ctx, t, player_input):
        pass
    elif any(k in t for k in combat_terms):
        ctx["action_type"] = "combat"
        ctx["domain"] = "combat"
        # Ranged (peluru) vs melee — untuk aturan jam & amunisi
        ranged_hints = (
            "menembak",
            "menembakan",
            "nembak",
            "tembak",
            "tembakin",
            "shoot",
            "shooting",
            "pistol",
            "pistolku",
            "pistol ku",
            "my pistol",
            "my gun",
            "senjata api",
            "rifle",
            "shotgun",
        )
        if any(k in t for k in ranged_hints):
            ctx["combat_style"] = "ranged"
        else:
            ctx["combat_style"] = "melee"
        if any(x in t for x in _NL_ATTEMPT_MARKERS):
            ctx["intent_note"] = "nl_attempt"
    elif (_acc := _parse_accommodation_intent(t)) is not None:
        ctx["domain"] = "economy"
        ctx["intent_note"] = "accommodation_stay"
        ctx["action_type"] = "instant"
        ctx["accommodation_intent"] = _acc
        ctx["instant_minutes"] = 15
        ctx["registry_action_id"] = "economy.nl_accommodation_stay"
    elif _registry_try_travel(ctx, t, player_input):
        pass
    elif any(k in t for k in _TRAVEL_LEGACY_KEYWORDS):
        _apply_travel_heuristics(ctx, t, player_input)
    elif _registry_try_sleep(ctx, t, player_input):
        # Data-driven sleep templates (registry) — only if not a hotel/stay booking intent.
        pass
    elif (sleep_h := _parse_sleep_hours(t)) is not None:
        ctx["action_type"] = "sleep"
        ctx["rested_minutes"] = int(sleep_h) * 60
        ctx["sleep_duration_h"] = int(sleep_h)
        ctx["domain"] = "other"
        ctx["stakes"] = "none"
        ctx["risk_level"] = "low"
        ctx["has_stakes"] = False
        ctx["uncertain"] = False
        tl = str(player_input or "").strip().lower()
        explicit_hours = bool(re.search(r"\b\d{1,2}\s*(?:jam|hours?|h)\b", tl)) or bool(
            re.search(r"\b(?:tidur|sleep)\s+\d{1,2}\b", tl)
        )
        ctx["registry_action_id"] = "sleep.nl_duration_hours" if explicit_hours else "sleep.nl_default_8h"
    elif _registry_try_rest_short_nl(ctx, t, player_input):
        pass
    elif _registry_try_social_inquiry_nl(ctx, t, player_input):
        pass
    elif _is_social_inquiry(t):
        ctx["domain"] = "social"
        ctx["social_context"] = "standard"
        ctx["intent_note"] = "social_inquiry"
        ctx["social_mode"] = "non_conflict"
    elif _registry_try_intimacy_private_nl(ctx, t, player_input):
        pass
    elif _registry_try_social_nl(ctx, t, player_input):
        pass
    elif _is_social_dialogue(t):
        ctx["domain"] = "social"
        ctx["social_context"] = "standard"
        ctx["intent_note"] = "social_dialogue"
        ctx["social_mode"] = "non_conflict"
    elif _is_social_scan(t):
        ctx["domain"] = "social"
        ctx["social_context"] = "standard"
        ctx["intent_note"] = "social_scan_crowd"
        ctx["social_mode"] = "non_conflict"
    elif _registry_try_social_negotiation_nl(ctx, t, player_input):
        pass
    elif _registry_try_skill_domain(ctx, t, player_input):
        pass
    elif any(k in t for k in _HACKING_LEGACY_KEYWORDS):
        ctx["domain"] = "hacking"
    elif any(k in t for k in _MEDICAL_LEGACY_KEYWORDS):
        ctx["domain"] = "medical"
    elif any(k in t for k in _DRIVING_LEGACY_KEYWORDS):
        ctx["domain"] = "driving"
    elif any(k in t for k in _STEALTH_LEGACY_KEYWORDS):
        ctx["domain"] = "stealth"
    elif _registry_try_social_conflict_nl(ctx, t, player_input):
        pass

    # STOP sequence heuristics (multi-hit: beberapa ``instant.nl_stop_*`` boleh sekaligus)
    _registry_apply_all_instant_stop_nl(ctx, t, player_input)
    if _registry_try_instant_clear_jam(ctx, t, player_input):
        pass

    # Realism gate
    if _registry_try_instant_trivial(ctx, t, player_input):
        pass
    elif any(k in t for k in _TRIVIAL_LEGACY_KEYWORDS):
        _apply_trivial_realism_flags(ctx)
    if _registry_try_instant_physically_impossible(ctx, t, player_input):
        pass

    if any(k in t for k in ["mungkin", "coba", "nekat", "risiko", "diam-diam"]):
        ctx["uncertain"] = True
        ctx["has_stakes"] = True
        ctx["risk_level"] = "high"

    # Kontak sosial santai: jangan paksa "high risk" cuma karena kata "coba"
    if ctx.get("domain") == "social" and ctx.get("intent_note") in (
        "social_dialogue",
        "social_scan_crowd",
        "social_inquiry",
    ):
        if not any(k in t for k in ["nekat", "risiko", "bohong", "negosiasi", "diam-diam"]):
            ctx["risk_level"] = "medium"
        ctx["uncertain"] = True
        ctx["has_stakes"] = True

    # Sosial konflik jika ada kata kunci konflik (ancam/tipu/paksa/dll)
    if ctx.get("domain") == "social" and any(k in t for k in _SOCIAL_CONFLICT_WORDS):
        ctx["social_mode"] = "conflict"
        ctx["has_stakes"] = True
        ctx["uncertain"] = True
        ctx["risk_level"] = "high"

    # Default sosial bila belum ter-set
    if ctx.get("domain") == "social" and ctx.get("social_mode") not in ("non_conflict", "conflict"):
        ctx["social_mode"] = "non_conflict"

    try:
        ctx["suggested_dc"] = max(1, min(100, int(ctx.get("suggested_dc", 50) or 50)))
    except (TypeError, ValueError):
        ctx["suggested_dc"] = 50

    return ctx


def _squish_cmd(s: str) -> str:
    return " ".join(str(s or "").strip().upper().split())


def command_allowed_for_active_scene(state: dict[str, Any], raw_cmd: str) -> bool:
    """True if input is allowed while ``active_scene`` is set (scene UX + matching ``next_options``)."""
    u = _squish_cmd(raw_cmd)
    if u in ("HELP", "QUIT", "EXIT", "UI FULL", "UI COMPACT"):
        return True
    parts = u.split()
    if len(parts) >= 2 and parts[0] == "SCENE" and parts[1] in ("STATUS", "INFO", "OPTIONS", "OPTS"):
        return True
    sc = state.get("active_scene")
    if not isinstance(sc, dict) or not sc:
        return True
    stype = str(sc.get("scene_type", "") or "").strip().lower()
    if u == "EAT" or u.startswith("EAT "):
        # Keep command lock in sync with main scene gate.
        return stype in {"drop_pickup"}
    opts = sc.get("next_options") or []
    if not isinstance(opts, list) or not opts:
        return False
    for opt in opts:
        if not isinstance(opt, str):
            continue
        if _squish_cmd(opt) == u:
            return True
    return False


def apply_active_scene_intent_lock(state: dict[str, Any], action_ctx: dict[str, Any], raw_cmd: str) -> None:
    """If an active scene lists ``next_options``, block non-scene responses (``scene_locked`` / ``combat_blocked``)."""
    sc = state.get("active_scene")
    if not isinstance(sc, dict) or not sc:
        return
    if command_allowed_for_active_scene(state, raw_cmd):
        return
    action_ctx["scene_locked"] = True
    action_ctx["combat_blocked"] = "scene_locked"


def is_intent_v2(intent: Any) -> bool:
    try:
        return isinstance(intent, dict) and int(intent.get("version", 1) or 1) == 2 and isinstance(intent.get("plan"), dict)
    except Exception:
        return False


def flatten_intent_v2(intent: dict[str, Any]) -> dict[str, Any]:
    """Return a v1-like dict derived from Intent v2 (steps[0] as step_now by default).

    This keeps the current pipeline working while we progressively move execution to plan steps.
    """
    if not is_intent_v2(intent):
        return dict(intent) if isinstance(intent, dict) else {}
    plan = intent.get("plan") if isinstance(intent.get("plan"), dict) else {}
    steps = plan.get("steps") if isinstance(plan.get("steps"), list) else []
    step0 = steps[0] if steps and isinstance(steps[0], dict) else {}
    out = dict(intent)
    for k in (
        "action_type",
        "domain",
        "combat_style",
        "social_mode",
        "social_context",
        "intent_note",
        "suggested_dc",
        "targets",
        "stakes",
        "risk_level",
        "time_cost_min",
        "travel_destination",
        "inventory_ops",
        "accommodation_intent",
        "smartphone_op",
    ):
        if k in step0 and step0.get(k) is not None:
            out[k] = step0.get(k)
    if "step_now_id" not in out and isinstance(step0.get("step_id"), str):
        out["step_now_id"] = step0.get("step_id")
    return out


def apply_parser_registry_anchor_after_llm(
    action_ctx: dict[str, Any], meta: dict[str, Any], parser_registry_id: str
) -> None:
    """Keep audit trail: parser registry id wins in meta after FFCI merge; restore ctx field."""
    rid = str(parser_registry_id or "").strip()
    if not rid:
        return
    action_ctx["registry_action_id"] = rid
    meta["resolved_action_id"] = rid
    meta["intent_resolution"] = "registry+llm"


# Fields merged from FFCI intent into action_ctx (also used to snapshot parser state before merge).
INTENT_MERGE_FIELD_KEYS: tuple[str, ...] = (
    "action_type",
    "domain",
    "combat_style",
    "social_mode",
    "social_context",
    "intent_note",
    "suggested_dc",
    "targets",
    "stakes",
    "risk_level",
    "time_cost_min",
    "travel_destination",
    "inventory_ops",
    "accommodation_intent",
    "smartphone_op",
)


def strip_llm_intent_overlay_on_registry_hint_mismatch(action_ctx: dict[str, Any]) -> None:
    """Drop FFCI v2 plan / goal overlay so execution matches parser-restored mechanical fields."""
    if not isinstance(action_ctx, dict):
        return
    action_ctx.pop("intent_plan", None)
    action_ctx.pop("step_now_id", None)
    action_ctx.pop("intent_plan_blocked", None)
    action_ctx.pop("player_goal", None)
    action_ctx.pop("intent_schema_version", None)
    action_ctx["intent_version"] = 1


def merge_intent_into_action_ctx(action_ctx: dict[str, Any], intent: dict[str, Any]) -> dict[str, Any]:
    """Merge either v1 or v2 intent output into an action_ctx (in-place).

    v2 is flattened deterministically for now (default step_now = steps[0]).
    """
    if not isinstance(action_ctx, dict):
        return action_ctx
    if not isinstance(intent, dict):
        return action_ctx
    src = flatten_intent_v2(intent) if is_intent_v2(intent) else intent
    for key in INTENT_MERGE_FIELD_KEYS:
        if key in src and src[key] is not None:
            action_ctx[key] = src[key]
    try:

        rh = sanitize_registry_action_id_hint(src.get("registry_action_id_hint"))
        if rh:
            action_ctx["llm_registry_action_id_hint"] = rh
        else:
            action_ctx.pop("llm_registry_action_id_hint", None)
    except Exception:
        action_ctx.pop("llm_registry_action_id_hint", None)
    try:
        action_ctx["intent_confidence"] = float(src.get("confidence", 0.0))
    except Exception:
        action_ctx["intent_confidence"] = 0.0
    if is_intent_v2(intent):
        action_ctx["intent_version"] = 2
        action_ctx["intent_plan"] = intent.get("plan")
        if "step_now_id" in src:
            action_ctx["step_now_id"] = src.get("step_now_id")
        pg = str(intent.get("player_goal", "") or "").strip()
        if pg:
            action_ctx["player_goal"] = pg[:400]
        try:
            isv = int(intent.get("intent_schema_version", 0) or 0)
            if isv:
                action_ctx["intent_schema_version"] = isv
        except Exception:
            pass
    else:
        pg1 = str((intent or {}).get("player_goal", "") or "").strip()
        if pg1:
            action_ctx["player_goal"] = pg1[:400]
        try:
            isv1 = int((intent or {}).get("intent_schema_version", 0) or 0)
            if isv1:
                action_ctx["intent_schema_version"] = isv1
        except Exception:
            pass
    return action_ctx


def _norm_s(s: Any) -> str:
    return str(s or "").strip().lower()


def _inv_tokens(state: dict[str, Any]) -> list[str]:
    inv = state.get("inventory", {}) or {}
    if not isinstance(inv, dict):
        return []
    toks: list[str] = []
    for k in ("r_hand", "l_hand", "worn"):
        v = inv.get(k)
        if isinstance(v, str) and v.strip() and v.strip() != "-":
            toks.append(v.strip().lower())
    for k in ("pocket_contents", "bag_contents"):
        arr = inv.get(k) or []
        if not isinstance(arr, list):
            continue
        for x in arr[:80]:
            if isinstance(x, str):
                if x.strip():
                    toks.append(x.strip().lower())
            elif isinstance(x, dict):
                iid = str(x.get("id") or x.get("item_id") or x.get("name") or "").strip()
                if iid:
                    toks.append(iid.lower())
    return toks


def _cmp(op: str, left: Any, right: Any) -> bool:
    op2 = str(op or "eq").strip().lower()
    if op2 in ("eq", "=="):
        return left == right
    if op2 in ("neq", "!="):
        return left != right
    if op2 == "in":
        if isinstance(right, (list, tuple, set)):
            return left in right
        # allow string containment as a convenience
        if isinstance(left, str) and isinstance(right, str):
            return left in right
        return False
    # numeric-ish comparisons
    try:
        lnum = float(left)
        rnum = float(right)
    except Exception:
        return False
    if op2 == "gte":
        return lnum >= rnum
    if op2 == "lte":
        return lnum <= rnum
    return False


def evaluate_precondition(state: dict[str, Any], action_ctx: dict[str, Any], cond: Any) -> bool:
    """Evaluate a single precondition dict against current state.

    Fail-safe & logged: unknown/invalid shapes return False and record_error().
    """
    if not isinstance(cond, dict):
        try:

            record_error(state, "intent.precondition", Exception("Invalid precondition shape (not dict)"))
        except Exception:
            pass
        return False
    kind = _norm_s(cond.get("kind", ""))
    op = str(cond.get("op", "eq") or "eq").strip().lower()
    value = cond.get("value")

    try:
        if kind in ("location_is", "district_is"):
            p = state.get("player", {}) or {}
            cur = _norm_s(p.get("location" if kind == "location_is" else "district", ""))
            want = _norm_s(value) if not isinstance(value, (list, tuple, set)) else [_norm_s(x) for x in value]
            return _cmp(op, cur, want)

        if kind == "scene_phase":
            sc = state.get("active_scene")
            phase = _norm_s(sc.get("phase")) if isinstance(sc, dict) else ""
            want = _norm_s(value) if not isinstance(value, (list, tuple, set)) else [_norm_s(x) for x in value]
            return _cmp(op, phase, want)

        if kind == "hands_free":
            inv = state.get("inventory", {}) or {}
            if not isinstance(inv, dict):
                return False
            rh = inv.get("r_hand", "-")
            lh = inv.get("l_hand", "-")
            free = (rh in ("-", "", None)) or (lh in ("-", "", None))
            # value may specify how many hands; for now accept truthy/falsy checks
            if value is None:
                return bool(free)
            return _cmp(op, int(free), int(bool(value)))

        if kind == "has_item":
            toks = _inv_tokens(state)
            if not toks:
                return False
            want = _norm_s(value)
            if not want:
                return False
            present = want in toks or any(want in t for t in toks)
            return _cmp(op, bool(present), True)

        if kind == "npc_alive":
            npcs = state.get("npcs", {}) or {}
            if not isinstance(npcs, dict):
                return False
            npc_id = str(value or "").strip()
            if not npc_id:
                return False
            row = npcs.get(npc_id)
            if not isinstance(row, dict):
                # If NPC doesn't exist, treat as not alive for safety.
                return False
            alive = row.get("alive")
            if alive is False:
                return False
            return True

        if kind == "money_gte":
            eco = state.get("economy", {}) or {}
            cash = int(eco.get("cash", 0) or 0) if isinstance(eco, dict) else 0
            try:
                need = int(value or 0)
            except Exception:
                need = 0
            return cash >= need

        if kind == "has_cash":
            eco = state.get("economy", {}) or {}
            cash = int(eco.get("cash", 0) or 0) if isinstance(eco, dict) else 0
            try:
                need = int(value or 0)
            except Exception:
                need = 0
            return cash >= need

        if kind == "has_funds":
            eco = state.get("economy", {}) or {}
            if not isinstance(eco, dict):
                return False
            try:
                cash = int(eco.get("cash", 0) or 0)
                bank = int(eco.get("bank", 0) or 0)
            except Exception:
                cash, bank = 0, 0
            total = cash + bank
            try:
                need = int(value or 0)
            except Exception:
                need = 0
            return total >= need

        if kind in ("time_is", "day_phase"):
            meta = state.get("meta", {}) or {}
            try:
                tm = int(meta.get("time_min", 0) or 0) % (24 * 60)
            except Exception:
                tm = 0
            h = tm // 60
            want = _norm_s(value)
            if want in ("night", "malam"):
                cur_ok = h >= 22 or h < 6
            elif want in ("day", "siang", "daytime"):
                cur_ok = 6 <= h < 18
            elif want in ("morning", "pagi"):
                cur_ok = 6 <= h < 12
            elif want in ("evening", "sore"):
                cur_ok = 17 <= h < 22
            else:
                return False
            return _cmp(op, cur_ok, True)

        if kind == "has_ammo":
            inv = state.get("inventory", {}) or {}
            if not isinstance(inv, dict):
                return False
            w = get_active_weapon(inv)
            if not isinstance(w, dict):
                return False
            try:
                n = int(w.get("ammo", 0) or 0)
            except Exception:
                n = 0
            try:
                need = max(1, int(value or 1))
            except Exception:
                need = 1
            return n >= need

        if kind == "weapon_drawn":
            inv = state.get("inventory", {}) or {}
            if not isinstance(inv, dict):
                return False
            aid = str(inv.get("active_weapon_id", "") or "").strip()
            rh = str(inv.get("r_hand", "-") or "-").strip()
            drawn = bool(aid) or (rh not in ("-", "", None) and rh.lower() not in ("unarmed", "none", "-"))
            if isinstance(value, bool):
                want = value
            else:
                want = str(value).strip().lower() in ("1", "true", "yes", "on")
            return drawn == want

        if kind == "skill_gte":
            skills = state.get("skills", {}) or {}
            if not isinstance(skills, dict):
                return False
            sk = ""
            need_lvl = 1
            if isinstance(value, dict):
                sk = str(value.get("skill", "") or "").strip()
                try:
                    need_lvl = int(value.get("level", 1) or 1)
                except Exception:
                    need_lvl = 1
            elif isinstance(value, str):
                # allow "hacking:3"
                parts = value.split(":", 1)
                sk = parts[0].strip()
                if len(parts) == 2:
                    try:
                        need_lvl = int(parts[1].strip() or 1)
                    except Exception:
                        need_lvl = 1
            sk = str(sk or "").strip()
            if not sk:
                return False
            row = skills.get(sk)
            lvl = 1
            if isinstance(row, dict):
                try:
                    lvl = int(row.get("level", 1) or 1)
                except Exception:
                    lvl = 1
            return lvl >= int(need_lvl)

        # Unknown kind
        try:

            record_error(state, "intent.precondition", Exception(f"Unknown precondition kind: {kind}"))
        except Exception:
            pass
        return False
    except Exception as e:
        try:

            record_error(state, "intent.precondition", e)
        except Exception:
            pass
        return False


def apply_intent_plan_precondition_failure(
    state: dict[str, Any], action_ctx: dict[str, Any], *, reason: str = "NO_VALID_STEP"
) -> None:
    """When intent v2 has steps but none satisfy preconditions: hard-fail with small time cost."""
    steps = _get_plan_steps(action_ctx)
    if not steps:
        return
    action_ctx["intent_plan_blocked"] = True
    action_ctx["intent_plan_block_reason"] = str(reason or "NO_VALID_STEP")[:80]
    action_ctx["action_type"] = "instant"
    action_ctx["domain"] = "other"
    action_ctx["roll_domain"] = "evasion"
    action_ctx["stakes"] = "none"
    action_ctx["risk_level"] = "low"
    action_ctx["has_stakes"] = False
    action_ctx["intent_note"] = "intent_plan_precondition_fail"
    action_ctx.pop("smartphone_op", None)
    meta = state.setdefault("meta", {})
    try:
        tm = int(meta.get("time_min", 0) or 0)
    except (TypeError, ValueError):
        tm = 0
    meta["time_min"] = min(24 * 60 - 1, tm + 1)
    state.setdefault("world_notes", []).append(
        f"[IntentPlan] Preconditions not met ({action_ctx['intent_plan_block_reason']}); you lose a minute re-planning."
    )


def _get_plan_steps(action_ctx: dict[str, Any]) -> list[dict[str, Any]]:
    plan = action_ctx.get("intent_plan") if isinstance(action_ctx.get("intent_plan"), dict) else {}
    steps = plan.get("steps") if isinstance(plan.get("steps"), list) else []
    return [s for s in steps if isinstance(s, dict)]


def apply_step_to_action_ctx(action_ctx: dict[str, Any], step: dict[str, Any]) -> None:
    """Overlay v1-compatible fields from a selected plan step into action_ctx."""
    if not isinstance(action_ctx, dict) or not isinstance(step, dict):
        return
    for k in (
        "action_type",
        "domain",
        "combat_style",
        "social_mode",
        "social_context",
        "intent_note",
        "suggested_dc",
        "targets",
        "stakes",
        "risk_level",
        "time_cost_min",
        "travel_destination",
        "inventory_ops",
        "accommodation_intent",
        "smartphone_op",
        "params",
    ):
        if k in step and step.get(k) is not None:
            action_ctx[k] = step.get(k)


def select_best_step(action_ctx: dict[str, Any], state: dict[str, Any]) -> str | None:
    steps = _get_plan_steps(action_ctx)
    if not steps:
        return None
    for st in steps:
        sid = str(st.get("step_id", "") or "").strip()
        if not sid:
            continue
        pre = st.get("preconditions", [])
        if pre is None:
            pre = []
        if not isinstance(pre, list):
            pre = []
        ok = True
        for cond in pre[:12]:
            if not evaluate_precondition(state, action_ctx, cond):
                ok = False
                break
        if ok:
            return sid
    # None valid: log clearly for debugging.
    try:

        plan = action_ctx.get("intent_plan") if isinstance(action_ctx.get("intent_plan"), dict) else {}
        pid = str(plan.get("plan_id", "") or "").strip()
        step_ids = [str(s.get("step_id", "") or "") for s in steps[:8]]
        record_error(state, "intent.select_best_step", Exception(f"No valid step found plan_id={pid} steps={step_ids}"))
    except Exception:
        pass
    return None


def normalize_action_ctx(action_ctx: dict[str, Any]) -> dict[str, Any]:
    """Pure normalizer for action_ctx, additive-only for compatibility."""
    src = dict(action_ctx) if isinstance(action_ctx, dict) else {}
    out = dict(src)
    domain = str(out.get("domain", "evasion") or "evasion").strip().lower() or "evasion"
    action_type = str(out.get("action_type", "instant") or "instant").strip().lower() or "instant"
    if domain == "combat" and action_type != "combat":
        action_type = "combat"

    out["domain"] = domain
    out["action_type"] = action_type
    out["roll_domain"] = str(out.get("roll_domain", domain) or domain).strip().lower() or domain

    try:
        tcm = int(out.get("time_cost_min", 0) or 0)
    except Exception:
        tcm = 0
    if tcm > 0:
        if action_type == "travel":
            out["travel_minutes"] = max(5, min(240, tcm))
        elif action_type == "sleep":
            mins = max(60, min(12 * 60, tcm))
            out["rested_minutes"] = mins
            out["sleep_duration_h"] = round(mins / 60.0, 2)
        else:
            out["instant_minutes"] = max(1, min(60, tcm))
    return out

