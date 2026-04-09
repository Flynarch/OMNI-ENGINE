from __future__ import annotations

import re
from typing import Any

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
    """Tanya info (bukan evasion)."""
    if "?" in t:
        return True
    return any(
        p in t
        for p in (
            "berapa ",
            "berapa ini",
            "tahun ",
            "jam berapa",
            "apa itu",
            "apa arti",
            "dimana ",
            "di mana",
            "kemana ",
            "kemana",
            "siapa ",
            "kenapa ",
            "mengapa ",
            "bagaimana ",
            "gimana ",
            "what year",
            "what time",
        )
    )


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


def _is_social_scan(t: str) -> bool:
    if any(p in t for p in _SOCIAL_SCAN_PHRASES):
        return True
    # "coba cari ... cewe" / "cari wanita di sekitar"
    if "cari" in t and any(w in t for w in _PEOPLE_WORDS):
        return True
    if any(w in t for w in ("mengintai", "mengamati", "mata-matai", "people watching", "perhatiin orang")):
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
    if any(k in t for k in combat_terms):
        ctx["action_type"] = "combat"
        ctx["domain"] = "combat"
        # Ranged (peluru) vs melee — untuk aturan jam & amunisi
        ranged_hints = ("menembak", "menembakan", "nembak", "tembak", "tembakin", "shoot", "pistol", "senjata api", "rifle", "shotgun")
        if any(k in t for k in ranged_hints):
            ctx["combat_style"] = "ranged"
        else:
            ctx["combat_style"] = "melee"
    elif (_acc := _parse_accommodation_intent(t)) is not None:
        ctx["domain"] = "economy"
        ctx["intent_note"] = "accommodation_stay"
        ctx["action_type"] = "instant"
        ctx["accommodation_intent"] = _acc
        ctx["instant_minutes"] = 15
    elif any(k in t for k in ["travel", "pergi ke", "naik", "menuju", "balik ke", "pulang ke", "kembali ke", "balik", "pulang", "kembali"]):
        ctx["action_type"] = "travel"
        # Heuristic distance estimation from text keywords.
        if any(k in t for k in ["dekat", "sekitar", "deket", "dekat sini", "sekitar sini", "dekat sana"]):
            ctx["travel_minutes"] = 10
        elif any(k in t for k in ["balik", "pulang", "kembali"]) and any(k in t for k in ["ke"]):
            ctx["travel_minutes"] = 15
        elif any(k in t for k in ["jauh", "jauhnya", "jauh banget", "antar kota", "beda kota", "lintas", "seberang", "lumayan jauh"]):
            ctx["travel_minutes"] = 90
        else:
            ctx["travel_minutes"] = 30

        # Try to extract destination after "ke"/"menuju"/"balik ke"/etc.
        # Example: "pergi ke london", "balik ke jakarta selatan".
        m = re.search(r"\b(?:ke|menuju|pulang ke|balik ke|kembali ke)\s+([a-zA-Z][a-zA-Z0-9\s\-']{2,40})", t)
        if m:
            dest_raw = m.group(1).strip()
            # Cut trailing connectors to avoid capturing "dengan/pakai/untuk".
            for cut in (" dengan ", " pakai ", " untuk ", " agar ", " lalu ", " sambil ", " sebelum ", " setelah ", " dan ", ","):
                if cut in (" " + dest_raw + " "):
                    dest_raw = dest_raw.split(cut.strip(), 1)[0].strip()
            dest_raw = dest_raw.strip(" .,!?:;\"'")
            if dest_raw:
                ctx["travel_destination"] = dest_raw
    elif t.startswith("sleep "):
        ctx["action_type"] = "sleep"
        ctx["rested_minutes"] = 8 * 60
    elif t.startswith("rest "):
        ctx["action_type"] = "rest"
        ctx["rested_minutes"] = 60
    elif _is_social_inquiry(t):
        ctx["domain"] = "social"
        ctx["social_context"] = "standard"
        ctx["intent_note"] = "social_inquiry"
        ctx["social_mode"] = "non_conflict"
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
    elif any(k in t for k in ["negosiasi", "bohong", "yakinkan"]):
        ctx["domain"] = "social"
        ctx["social_context"] = "formal" if any(k in t for k in ["formal", "kantor", "instansi", "gala", "hotel"]) else "standard"
        ctx["social_mode"] = "conflict"
    elif any(k in t for k in ["hack", "retas", "bypass", "terminal"]):
        ctx["domain"] = "hacking"
    elif any(k in t for k in ["rawat", "obati", "jahit luka"]):
        ctx["domain"] = "medical"
    elif any(k in t for k in ["nyetir", "driving", "mengemudi"]):
        ctx["domain"] = "driving"
    elif any(k in t for k in ["mengendap", "stealth", "diam-diam"]):
        ctx["domain"] = "stealth"
    elif any(k in t for k in _SOCIAL_CONFLICT_WORDS) and any(w in t for w in _PEOPLE_WORDS):
        # Konflik sosial eksplisit (ancam/paksa/tipu) ke orang: ini tetap domain social.
        ctx["domain"] = "social"
        ctx["social_context"] = "standard"
        ctx["intent_note"] = "social_conflict"
        ctx["social_mode"] = "conflict"

    # STOP sequence heuristics
    if any(k in t for k in ["eksekusi", "bunuh", "korbankan", "putusan final"]):
        ctx["irreversible_decision"] = True
        ctx["stop_triggers"].append("irreversible_decision")
    if any(k in t for k in ["masuk ruangan", "buka pintu", "masuk area baru", "new zone"]):
        ctx["new_zone"] = True
        ctx["stop_triggers"].append("new_zone")
    if "darah deras" in t or "kehilangan darah parah" in t:
        ctx["blood_loss_single_event_over_30"] = True
        ctx["stop_triggers"].append("critical_blood_loss")
    if "clear jam" in t or "bersihin macet" in t:
        ctx["attempt_clear_jam"] = True
        ctx["instant_minutes"] = 1

    # Realism gate
    if any(k in t for k in ["lihat status", "cek tas", "jalan santai", "minum air"]):
        ctx["trivial_action"] = True
        ctx["trivial"] = True
        ctx["uncertain"] = False
        ctx["has_stakes"] = False
        ctx["risk_level"] = "low"
    if any(k in t for k in ["terbang tanpa alat", "menembus dinding", "berenang di udara"]):
        ctx["physically_impossible"] = True
        ctx["impossible"] = True
        ctx["uncertain"] = False
        ctx["has_stakes"] = True
        ctx["risk_level"] = "high"

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

    return ctx

