"""Named handlers for registry entries with optional ``handler`` field.

Register callables with ``register_handler``; ``apply_registry_handler`` invokes
by name (no-op if unknown). Used when JSON alone cannot express intent logic.

Built-in: ``ensure_social_inquiry_shape`` (inquiry), ``ensure_travel_registry_shape`` (travel),
``ensure_social_negotiation_shape`` (negotiation / deception phrasing),
``ensure_intimacy_private_registry_shape`` (intimacy private NL),
``apply_sleep_duration_from_nl`` (``sleep.nl_duration_hours`` — jam tidur dari teks NL),
``apply_accommodation_nl`` (``economy.nl_accommodation_stay`` — hotel/menginap semalam dari NL),
``try_parse_smartphone_nl`` (NL + regex untuk ``smartphone_op``; id registry ``other.nl_smartphone_w2``),
``ensure_stop_irreversible`` / ``ensure_stop_new_zone`` / ``ensure_stop_critical_blood`` (STOP sequence) so ``ctx_patch`` can stay minimal,
``apply_social_post_hedge_risk_rules`` (risiko sosial setelah hedge di ``parse_action_intent``).
"""

from __future__ import annotations

from engine.core.error_taxonomy import log_swallowed_exception
import re
from collections.abc import Sequence
from typing import Any, Callable

RegistryHandler = Callable[[dict[str, Any], str, str], None]

_HANDLERS: dict[str, RegistryHandler] = {}


def ensure_social_inquiry_shape(ctx: dict[str, Any], t: str, raw: str) -> None:
    """Normalize social inquiry ctx after a thin or empty ``ctx_patch``."""
    ctx["domain"] = "social"
    ctx["social_context"] = "standard"
    ctx["social_mode"] = "non_conflict"
    ctx["intent_note"] = "social_inquiry"


def ensure_travel_registry_shape(ctx: dict[str, Any], t: str, raw: str) -> None:
    """Ensure travel NL keeps ``action_type`` after an empty/minimal ``ctx_patch`` (heuristics usually set it earlier)."""
    ctx.setdefault("action_type", "travel")


def ensure_social_negotiation_shape(ctx: dict[str, Any], t: str, raw: str) -> None:
    """Formal vs standard venue for negotiation / deception phrasing (after ``ctx_patch``)."""
    formal_cues = ("formal", "kantor", "instansi", "gala", "hotel")
    ctx["social_context"] = "formal" if any(k in t for k in formal_cues) else "standard"
    ctx["intent_note"] = "social_negotiation"


_SOCIAL_CALM_INTENT_NOTES: frozenset[str] = frozenset(
    ("social_dialogue", "social_scan_crowd", "social_inquiry")
)
_SOCIAL_CALM_RISK_EXCEPTIONS: tuple[str, ...] = (
    "nekat",
    "risiko",
    "bohong",
    "negosiasi",
    "diam-diam",
)


def apply_social_post_hedge_risk_rules(
    ctx: dict[str, Any], t: str, conflict_keywords: Sequence[str]
) -> None:
    """Calm dialogue/scan/inquiry risk, then conflict keywords, then default ``social_mode`` (after hedge)."""
    if ctx.get("domain") == "social" and ctx.get("intent_note") in _SOCIAL_CALM_INTENT_NOTES:
        if not any(k in t for k in _SOCIAL_CALM_RISK_EXCEPTIONS):
            ctx["risk_level"] = "medium"
        ctx["uncertain"] = True
        ctx["has_stakes"] = True

    if ctx.get("domain") == "social" and any(k in t for k in conflict_keywords):
        ctx["social_mode"] = "conflict"
        ctx["has_stakes"] = True
        ctx["uncertain"] = True
        ctx["risk_level"] = "high"

    if ctx.get("domain") == "social" and ctx.get("social_mode") not in ("non_conflict", "conflict"):
        ctx["social_mode"] = "non_conflict"


def ensure_stop_irreversible(ctx: dict[str, Any], t: str, raw: str) -> None:
    """STOP: irreversible / lethal phrasing."""
    ctx["irreversible_decision"] = True
    st = ctx.setdefault("stop_triggers", [])
    if isinstance(st, list) and "irreversible_decision" not in st:
        st.append("irreversible_decision")


def ensure_stop_new_zone(ctx: dict[str, Any], t: str, raw: str) -> None:
    """STOP: spatial transition cue."""
    ctx["new_zone"] = True
    st = ctx.setdefault("stop_triggers", [])
    if isinstance(st, list) and "new_zone" not in st:
        st.append("new_zone")


def ensure_stop_critical_blood(ctx: dict[str, Any], t: str, raw: str) -> None:
    """STOP: severe bleeding cue."""
    ctx["blood_loss_single_event_over_30"] = True
    st = ctx.setdefault("stop_triggers", [])
    if isinstance(st, list) and "critical_blood_loss" not in st:
        st.append("critical_blood_loss")


def apply_smartphone_ctx_defaults(ctx: dict[str, Any]) -> None:
    """Default fields for smartphone micro-ops (W2-11)."""
    ctx["action_type"] = "instant"
    ctx["domain"] = "other"
    ctx["intent_note"] = "smartphone"
    ctx["has_stakes"] = False
    ctx["uncertain"] = False
    ctx["trivial"] = True
    ctx["risk_level"] = "low"
    ctx["stakes"] = "none"
    try:
        im = int(ctx.get("instant_minutes", 0) or 0)
    except (TypeError, ValueError):
        im = 0
    ctx["instant_minutes"] = max(im, 2)


def try_parse_smartphone_nl(ctx: dict[str, Any], raw_in: str, t: str) -> bool:
    """NL + light English patterns for smartphone ops; mutates ``ctx`` on match."""
    tnorm = str(t or "").strip().lower()
    if not tnorm:
        return False

    m = re.match(r"^(phone|smartphone|hp)\s+(on|off|status)\s*$", tnorm)
    if m:
        ctx["smartphone_op"] = {"op": "power", "value": str(m.group(2) or "").strip().lower()}
        apply_smartphone_ctx_defaults(ctx)
        return True

    if re.search(r"\b(matikan|turn off|switch off)\s+(hp|ponsel|smartphone|phone)\b", tnorm):
        ctx["smartphone_op"] = {"op": "power", "value": "off"}
        apply_smartphone_ctx_defaults(ctx)
        return True
    if re.search(r"\b(nyalakan|turn on|switch on|hidupkan)\s+(hp|ponsel|smartphone|phone)\b", tnorm):
        ctx["smartphone_op"] = {"op": "power", "value": "on"}
        apply_smartphone_ctx_defaults(ctx)
        return True

    m2 = re.search(
        r"\b(telepon|panggil|call)\s+([a-zA-Z][a-zA-Z0-9_'\-]{0,40})\b",
        str(raw_in or "").strip(),
        flags=re.I,
    )
    if m2:
        ctx["smartphone_op"] = {"op": "call", "target": str(m2.group(2) or "").strip()}
        apply_smartphone_ctx_defaults(ctx)
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
        apply_smartphone_ctx_defaults(ctx)
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
        apply_smartphone_ctx_defaults(ctx)
        ctx["instant_minutes"] = max(int(ctx.get("instant_minutes", 0) or 0), 3)
        return True

    if re.search(r"\b(dark\s*web|darkweb|deep\s*web|darknet)\b", tnorm):
        ctx["smartphone_op"] = {"op": "dark_web"}
        apply_smartphone_ctx_defaults(ctx)
        ctx["instant_minutes"] = max(int(ctx.get("instant_minutes", 0) or 0), 12)
        return True

    return False


def parse_accommodation_intent_from_nl(t: str) -> dict[str, Any] | None:
    """Detect prepaid short-stay phrasing (hotel/boarding/suite night); same rules as legacy parser."""
    tnorm = str(t or "").strip().lower()
    if not tnorm:
        return None
    night_ok = (
        "semalam" in tnorm
        or "semaleman" in tnorm
        or "satu malam" in tnorm
        or "overnight" in tnorm
        or "one night" in tnorm
        or bool(re.search(r"\b1\s*(?:malam|night|nights)\b", tnorm))
        or bool(re.search(r"\b(\d+)\s*(?:malam|night|nights)\b", tnorm))
    )
    if not night_ok:
        return None
    lodging_ok = any(
        k in tnorm
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
    if not lodging_ok and ("stay" in tnorm or "menginap" in tnorm):
        lodging_ok = True
    if not lodging_ok:
        return None
    if "pergi ke" in tnorm or "menuju" in tnorm:
        if not any(
            k in tnorm
            for k in (
                "nginap",
                "menginap",
                "stay",
                "booking",
                "check in",
                "check-in",
                "hotel",
                "hostel",
                "kos",
                "kost",
                "suite",
                "kamar",
            )
        ):
            return None
    nights = 1
    m = re.search(r"\b(\d+)\s*(?:malam|night|nights)\b", tnorm)
    if m:
        nights = max(1, min(365, int(m.group(1))))
    if re.search(r"\b(?:satu|1)\s+malam\b", tnorm) or "semalam" in tnorm or "one night" in tnorm or re.search(r"\b1\s+night\b", tnorm):
        nights = 1
    kind: str | None = None
    if any(x in tnorm for x in ("suite", "penthouse")) or ("luxury" in tnorm and "hotel" in tnorm):
        kind = "suite"
    elif any(x in tnorm for x in ("hostel", "dorm", "guesthouse", "kos", "kost", "boarding")):
        kind = "kos"
    elif any(x in tnorm for x in ("hotel", "motel", "inn")):
        kind = "hotel"
    return {"nights": nights, "kind": kind, "parser": "accommodation_nl"}


def apply_accommodation_nl(ctx: dict[str, Any], t: str, raw: str) -> None:
    """Apply economy stay hint from ``parse_accommodation_intent_from_nl``."""
    acc = parse_accommodation_intent_from_nl(t)
    if not acc:
        return
    ctx["domain"] = "economy"
    ctx["intent_note"] = "accommodation_stay"
    ctx["action_type"] = "instant"
    ctx["accommodation_intent"] = acc
    ctx["instant_minutes"] = 15


def parse_sleep_hours_from_nl(t: str) -> int | None:
    """Parse explicit or default sleep duration in hours from lowercased NL (1..12 or default 8)."""
    txt = str(t or "").strip().lower()
    if not txt:
        return None
    m = re.search(r"\b(?:aku|saya)\s+mau\s+tidur\s+(\d{1,2})(?:\s*(?:jam|hours?|h))?\b", txt)
    if m:
        try:
            return max(1, min(12, int(m.group(1))))
        except Exception as _omni_sw_292:
            log_swallowed_exception('engine/core/action_registry_handlers.py:292', _omni_sw_292)
            return 8
    m = re.search(r"\b(?:sleep|tidur)\s+(\d{1,2})(?:\s*(?:jam|hours?|h))?\b", txt)
    if m:
        try:
            return max(1, min(12, int(m.group(1))))
        except Exception as _omni_sw_298:
            log_swallowed_exception('engine/core/action_registry_handlers.py:298', _omni_sw_298)
            return 8
    m = re.search(r"\b(\d{1,2})\s*(?:jam|hours?|h)\b", txt)
    if m and ("tidur" in txt or "sleep" in txt):
        try:
            return max(1, min(12, int(m.group(1))))
        except Exception as _omni_sw_304:
            log_swallowed_exception('engine/core/action_registry_handlers.py:304', _omni_sw_304)
            return 8
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


def apply_sleep_duration_from_nl(ctx: dict[str, Any], t: str, raw: str) -> None:
    """Fill sleep ctx from ``parse_sleep_hours_from_nl`` (used with ``sleep.nl_duration_hours``)."""
    h = parse_sleep_hours_from_nl(t)
    if h is None:
        return
    sleep_h = max(1, min(12, int(h)))
    ctx["action_type"] = "sleep"
    ctx["rested_minutes"] = int(sleep_h) * 60
    ctx["sleep_duration_h"] = int(sleep_h)
    ctx["domain"] = "other"
    ctx["stakes"] = "none"
    ctx["risk_level"] = "low"
    ctx["has_stakes"] = False
    ctx["uncertain"] = False


def ensure_intimacy_private_registry_shape(ctx: dict[str, Any], t: str, raw: str) -> None:
    """After ``ctx_patch``: minimum instant time + optional partner token from NL."""
    try:
        im = int(ctx.get("instant_minutes", 0) or 0)
    except (TypeError, ValueError):
        im = 0
    ctx["instant_minutes"] = max(im, 75)
    raw_in = str(raw or "").strip()
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


def register_handler(name: str, fn: RegistryHandler) -> None:
    key = str(name or "").strip()
    if key:
        _HANDLERS[key] = fn


def get_registry_handler(name: str) -> RegistryHandler | None:
    return _HANDLERS.get(str(name or "").strip())


def apply_registry_handler(name: str, ctx: dict[str, Any], t: str, raw: str) -> bool:
    fn = get_registry_handler(name)
    if not fn:
        return False
    fn(ctx, t, raw)
    return True


register_handler("ensure_social_inquiry_shape", ensure_social_inquiry_shape)
register_handler("ensure_travel_registry_shape", ensure_travel_registry_shape)
register_handler("ensure_social_negotiation_shape", ensure_social_negotiation_shape)
register_handler("ensure_intimacy_private_registry_shape", ensure_intimacy_private_registry_shape)
register_handler("ensure_stop_irreversible", ensure_stop_irreversible)
register_handler("ensure_stop_new_zone", ensure_stop_new_zone)
register_handler("ensure_stop_critical_blood", ensure_stop_critical_blood)
register_handler("apply_sleep_duration_from_nl", apply_sleep_duration_from_nl)
register_handler("apply_accommodation_nl", apply_accommodation_nl)
