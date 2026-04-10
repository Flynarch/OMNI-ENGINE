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
        # Vehicle hints (best-effort): "pakai mobil", "naik motor", "drive ... car_standard", etc.
        # This does not validate ownership; engine will ignore if not owned/active.
        try:
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
            # Explicit engine ids if typed.
            for vid in ("bicycle", "motorcycle", "car_standard", "car_sports", "car_van"):
                if vid in t:
                    ctx["vehicle_id"] = vid
                    break
            if "vehicle_id" not in ctx:
                for k, vid in veh_map.items():
                    if k in t:
                        ctx["vehicle_id"] = vid
                        break
            if "vehicle_id" in ctx:
                ctx.setdefault("intent_note", "travel_by_vehicle")
        except Exception:
            pass
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
    elif _is_intimacy_private(t):
        ctx["domain"] = "social"
        ctx["social_context"] = "standard"
        ctx["intent_note"] = "intimacy_private"
        ctx["social_mode"] = "non_conflict"
        ctx["visibility"] = "private"
        ctx["stakes"] = "medium"
        ctx["has_stakes"] = True
        ctx["uncertain"] = True
        im = int(ctx.get("instant_minutes", 0) or 0)
        ctx["instant_minutes"] = max(im, 75)
        raw_in = (player_input or "").strip()
        for pat in (
            r"\bwith\s+([A-Za-z][A-Za-z0-9_'\-]{1,32})\b",
            r"\bdengan\s+([A-Za-z][A-Za-z0-9_'\-]{1,32})\b",
            r"\bbersama\s+([A-Za-z][A-Za-z0-9_'\-]{1,32})\b",
        ):
            m = re.search(pat, raw_in, flags=re.I)
            if not m:
                continue
            name = m.group(1).strip()
            if name.lower() in ("the", "a", "an", "itu", "dia", "mereka"):
                continue
            tl = ctx.setdefault("targets", [])
            if isinstance(tl, list) and name not in tl:
                tl.insert(0, name)
            break
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
        "targets",
        "stakes",
        "risk_level",
        "time_cost_min",
        "travel_destination",
        "inventory_ops",
        "accommodation_intent",
    ):
        if k in step0 and step0.get(k) is not None:
            out[k] = step0.get(k)
    if "step_now_id" not in out and isinstance(step0.get("step_id"), str):
        out["step_now_id"] = step0.get("step_id")
    return out


def merge_intent_into_action_ctx(action_ctx: dict[str, Any], intent: dict[str, Any]) -> dict[str, Any]:
    """Merge either v1 or v2 intent output into an action_ctx (in-place).

    v2 is flattened deterministically for now (default step_now = steps[0]).
    """
    if not isinstance(action_ctx, dict):
        return action_ctx
    if not isinstance(intent, dict):
        return action_ctx
    src = flatten_intent_v2(intent) if is_intent_v2(intent) else intent
    for key in (
        "action_type",
        "domain",
        "combat_style",
        "social_mode",
        "social_context",
        "intent_note",
        "targets",
        "stakes",
        "risk_level",
        "time_cost_min",
        "travel_destination",
        "inventory_ops",
        "accommodation_intent",
    ):
        if key in src and src[key] is not None:
            action_ctx[key] = src[key]
    try:
        action_ctx["intent_confidence"] = float(src.get("confidence", 0.0))
    except Exception:
        action_ctx["intent_confidence"] = 0.0
    if is_intent_v2(intent):
        action_ctx["intent_version"] = 2
        action_ctx["intent_plan"] = intent.get("plan")
        if "step_now_id" in src:
            action_ctx["step_now_id"] = src.get("step_now_id")
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
            from engine.core.errors import record_error

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
            from engine.core.errors import record_error

            record_error(state, "intent.precondition", Exception(f"Unknown precondition kind: {kind}"))
        except Exception:
            pass
        return False
    except Exception as e:
        try:
            from engine.core.errors import record_error

            record_error(state, "intent.precondition", e)
        except Exception:
            pass
        return False


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
        "targets",
        "stakes",
        "risk_level",
        "time_cost_min",
        "travel_destination",
        "inventory_ops",
        "accommodation_intent",
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
        from engine.core.errors import record_error

        plan = action_ctx.get("intent_plan") if isinstance(action_ctx.get("intent_plan"), dict) else {}
        pid = str(plan.get("plan_id", "") or "").strip()
        step_ids = [str(s.get("step_id", "") or "") for s in steps[:8]]
        record_error(state, "intent.select_best_step", Exception(f"No valid step found plan_id={pid} steps={step_ids}"))
    except Exception:
        pass
    return None

