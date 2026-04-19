"""Named handlers for registry entries with optional ``handler`` field.

Register callables with ``register_handler``; ``apply_registry_handler`` invokes
by name (no-op if unknown). Used when JSON alone cannot express intent logic.

Built-in: ``ensure_social_inquiry_shape`` (inquiry), ``ensure_travel_registry_shape`` (travel),
``ensure_social_negotiation_shape`` (negotiation / deception phrasing),
``ensure_intimacy_private_registry_shape`` (intimacy private NL),
``ensure_stop_irreversible`` / ``ensure_stop_new_zone`` / ``ensure_stop_critical_blood`` (STOP sequence) so ``ctx_patch`` can stay minimal.
"""

from __future__ import annotations

import re
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
