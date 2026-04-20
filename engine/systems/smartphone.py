"""W2-11: player smartphone — deterministic comms, dark-web gate, police tracking risk."""

from __future__ import annotations

import hashlib
from typing import Any

from engine.core.error_taxonomy import log_swallowed_exception
from engine.core.trace import get_trace_tier


def _h32(*parts: Any) -> int:
    s = "|".join(str(p) for p in parts)
    h = hashlib.md5(s.encode("utf-8", errors="ignore")).hexdigest()
    return int(h[:8], 16)


def ensure_smartphone(state: dict[str, Any]) -> dict[str, Any]:
    """Ensure player.smartphone exists with safe defaults."""
    pl = state.setdefault("player", {})
    if not isinstance(pl, dict):
        pl = {}
        state["player"] = pl
    sp = pl.get("smartphone")
    if not isinstance(sp, dict):
        sp = {}
        pl["smartphone"] = sp
    meta = state.get("meta", {}) or {}
    seed = str(meta.get("world_seed", "") or meta.get("seed_pack", "") or meta.get("seed", "") or "0")
    pname = str(pl.get("name", "player") or "player")
    if not str(sp.get("number", "") or "").strip():
        h = _h32(seed, pname) % 900_000_000
        sp["number"] = f"+{1_000_000_000 + abs(h)}"
    sp.setdefault("phone_on", True)
    msgs = sp.get("messages")
    if not isinstance(msgs, list):
        msgs = []
        sp["messages"] = msgs
    apps = sp.get("apps_installed")
    if not isinstance(apps, list):
        apps = ["dialer", "messages", "wallet", "browser"]
        sp["apps_installed"] = apps
    contacts = sp.get("contacts")
    if not isinstance(contacts, list):
        contacts = []
        sp["contacts"] = contacts
    # Light sync: NPC first names -> contact labels (bounded, deterministic order).
    try:
        npcs = state.get("npcs", {}) or {}
        if isinstance(npcs, dict) and len(contacts) < 24:
            seen = {str(c).strip().lower() for c in contacts if isinstance(c, str)}
            keys = sorted(npcs.keys(), key=lambda x: str(x).lower())[:40]
            for k in keys:
                n = npcs.get(k)
                if not isinstance(n, dict):
                    continue
                nm = str(n.get("name", k) or k).strip()
                if nm and nm.lower() not in seen:
                    contacts.append(nm[:48])
                    seen.add(nm.lower())
                if len(contacts) >= 24:
                    break
    except Exception as _omni_sw_60:
        log_swallowed_exception('engine/systems/smartphone.py:60', _omni_sw_60)
    return sp


def _skill_level(state: dict[str, Any], key: str) -> int:
    skills = state.get("skills", {}) or {}
    if not isinstance(skills, dict):
        return 1
    row = skills.get(key)
    if not isinstance(row, dict):
        return 1
    try:
        return max(1, min(20, int(row.get("level", 1) or 1)))
    except Exception as _omni_sw_74:
        log_swallowed_exception('engine/systems/smartphone.py:74', _omni_sw_74)
        return 1


def resolve_phone_target(state: dict[str, Any], needle: str) -> tuple[str | None, str]:
    """Match NPC id + display name from free text (substring, deterministic first match)."""
    raw = str(needle or "").strip()
    if not raw:
        return None, ""
    nl = raw.lower()
    npcs = state.get("npcs", {}) or {}
    if isinstance(npcs, dict):
        # Exact key
        if raw in npcs and isinstance(npcs.get(raw), dict):
            n = npcs[raw]
            name = str(n.get("name", raw) or raw).strip()
            return str(raw), name
        for k in sorted(npcs.keys(), key=lambda x: str(x).lower()):
            n = npcs.get(k)
            if not isinstance(n, dict):
                continue
            name = str(n.get("name", k) or k).strip()
            kl = str(k).lower()
            if nl == kl or nl in name.lower():
                return str(k), name
    contacts = (state.get("world", {}) or {}).get("contacts", {}) or {}
    if isinstance(contacts, dict):
        for ck in sorted(contacts.keys(), key=lambda x: str(x).lower()):
            if nl in str(ck).lower():
                return None, str(ck).strip()
    return None, raw


def _append_message(
    state: dict[str, Any],
    sp: dict[str, Any],
    *,
    direction: str,
    peer: str,
    text: str,
    kind: str,
) -> None:
    meta = state.get("meta", {}) or {}
    day = int(meta.get("day", 1) or 1)
    tmin = int(meta.get("time_min", 0) or 0)
    msgs: list[Any] = sp.setdefault("messages", [])
    if not isinstance(msgs, list):
        msgs = []
        sp["messages"] = msgs
    msgs.append(
        {
            "day": day,
            "time_min": tmin,
            "dir": direction,
            "peer": peer[:64],
            "text": text[:500],
            "kind": kind,
        }
    )
    del msgs[: max(0, len(msgs) - 48)]


def _smartphone_status_summary(sp: dict[str, Any]) -> str:
    """Compact phone status summary shared by HUD and PHONE STATUS."""
    on = bool(sp.get("phone_on", True))
    num = str(sp.get("number", "") or "").strip()
    tail = num[-4:] if len(num) >= 4 else num
    bits = [f"{'ON' if on else 'OFF'}" + (f" ···{tail}" if tail else "")]
    msgs = sp.get("messages")
    if isinstance(msgs, list) and msgs:
        recent = [m for m in msgs[-8:] if isinstance(m, dict)]
        incoming = [m for m in recent if str(m.get("dir", "") or "") == "in"]
        utility_in = [m for m in incoming if str(m.get("kind", "") or "").strip().lower() == "npc_utility_contact"]
        if utility_in:
            last_peer = str(utility_in[-1].get("peer", "NPC") or "NPC").strip()[:16]
            bits.append(f"contact:{last_peer}")
        elif incoming:
            bits.append(f"inbox:{len(incoming)}")
    return " | ".join([b for b in bits if b])


def notify_npc_utility_contact_surfaced(state: dict[str, Any], rp: dict[str, Any]) -> None:
    """Mirror surfaced utility-AI contact ripples into the smartphone inbox (deterministic)."""
    if not isinstance(rp, dict):
        return
    if rp.get("dropped_by_propagation"):
        return
    kind = str(rp.get("kind", "") or "").strip().lower()
    if kind != "npc_utility_contact":
        return
    flags = state.get("flags", {}) or {}
    if not bool(flags.get("npc_utility_contact_notify_enabled", True)):
        return
    meta = rp.get("meta") if isinstance(rp.get("meta"), dict) else {}
    npc_id = str(meta.get("npc", "") or "").strip()
    display = npc_id
    npcs = state.get("npcs", {}) or {}
    if npc_id and isinstance(npcs, dict):
        row = npcs.get(npc_id)
        if isinstance(row, dict):
            display = str(row.get("name", npc_id) or npc_id).strip() or npc_id
    meta_d = state.get("meta", {}) or {}
    try:
        day = int(meta_d.get("day", 1) or 1)
    except Exception:
        day = 1
    sp = ensure_smartphone(state)
    msgs = sp.get("messages")
    if isinstance(msgs, list):
        for m in reversed(msgs[-16:]):
            if not isinstance(m, dict):
                continue
            if (
                str(m.get("kind", "") or "") == "npc_utility_contact"
                and str(m.get("peer", "") or "") == display
                and int(m.get("day", 0) or 0) == day
            ):
                return
    txt = "Menyisakan pesan: butuh kontak. Balas atau TALK jika bisa."
    _append_message(state, sp, direction="in", peer=display[:64], text=txt, kind="npc_utility_contact")


def apply_smartphone_pipeline(state: dict[str, Any], action_ctx: dict[str, Any]) -> None:
    """Run deterministic smartphone mechanics once per turn (pre-roll). Mutates state; sets roll hints."""
    op = action_ctx.get("smartphone_op")
    if not isinstance(op, dict):
        return
    sp = ensure_smartphone(state)
    kind = str(op.get("op", "") or "").strip().lower()
    result: dict[str, Any] = {"ok": True, "msg": "", "reason": ""}

    im = int(action_ctx.get("instant_minutes", 0) or 0)

    if kind == "power":
        v = str(op.get("value", "") or "").strip().lower()
        if v == "on":
            sp["phone_on"] = True
            result["msg"] = "Phone is on."
            im = max(im, 1)
        elif v == "off":
            sp["phone_on"] = False
            result["msg"] = "Phone is off."
            im = max(im, 1)
        elif v == "status":
            result["msg"] = "Phone " + _smartphone_status_summary(sp)
            im = max(im, 0)
        else:
            result = {"ok": False, "reason": "BAD_POWER", "msg": "Unknown power action."}
            im = max(im, 0)
    elif kind == "call":
        if not bool(sp.get("phone_on", True)):
            result = {"ok": False, "reason": "PHONE_OFF", "msg": "Phone is off; cannot place a call."}
        else:
            tgt = str(op.get("target", "") or "").strip()
            npc_id, name = resolve_phone_target(state, tgt)
            peer = name or tgt
            result["msg"] = f"Outgoing call to {peer}…"
            if npc_id:
                try:
                    npcs = state.get("npcs", {}) or {}
                    n = npcs.get(npc_id) if isinstance(npcs, dict) else None
                    if isinstance(n, dict):
                        tr = int(n.get("trust", 50) or 50)
                        n["trust"] = min(100, tr + 1)
                except Exception as _omni_sw_179:
                    log_swallowed_exception('engine/systems/smartphone.py:179', _omni_sw_179)
            _append_message(state, sp, direction="out", peer=peer, text="[voice call]", kind="call")
            im = max(im, 4)
    elif kind == "message":
        if not bool(sp.get("phone_on", True)):
            result = {"ok": False, "reason": "PHONE_OFF", "msg": "Phone is off; cannot send messages."}
        else:
            tgt = str(op.get("target", "") or "").strip()
            body = str(op.get("body", "") or "").strip() or "(no text)"
            npc_id, name = resolve_phone_target(state, tgt)
            peer = name or tgt
            result["msg"] = f"Message sent to {peer}."
            _append_message(state, sp, direction="out", peer=peer, text=body, kind="sms")
            if npc_id:
                try:
                    npcs = state.get("npcs", {}) or {}
                    n = npcs.get(npc_id) if isinstance(npcs, dict) else None
                    if isinstance(n, dict):
                        tr = int(n.get("trust", 50) or 50)
                        n["trust"] = min(100, tr + 1)
                except Exception as _omni_sw_200:
                    log_swallowed_exception('engine/systems/smartphone.py:200', _omni_sw_200)
            im = max(im, 3)
    elif kind == "dark_web":
        if not bool(sp.get("phone_on", True)):
            result = {"ok": False, "reason": "PHONE_OFF", "msg": "Phone is off; no network session."}
        else:
            hack_lv = _skill_level(state, "hacking")
            if hack_lv < 4:
                result = {
                    "ok": False,
                    "reason": "SKILL_LOW",
                    "msg": "Dark web access refused — need stronger hacking fundamentals.",
                }
            else:
                result["msg"] = "Dark web session connected (high risk)."
                _append_message(state, sp, direction="out", peer="dark_web", text="[session start]", kind="dark_web")
                try:
                    tier = str(get_trace_tier(state).get("tier_id", "") or "")
                    if tier in ("Wanted", "Lockdown"):
                        tr = state.setdefault("trace", {})
                        cur = int(tr.get("trace_pct", 0) or 0)
                        tr["trace_pct"] = min(100, cur + 1)
                except Exception as _omni_sw_225:
                    log_swallowed_exception('engine/systems/smartphone.py:225', _omni_sw_225)
                im = max(im, 12)
    else:
        result = {"ok": False, "reason": "UNKNOWN_OP", "msg": "Unknown smartphone operation."}

    action_ctx["instant_minutes"] = max(im, int(action_ctx.get("instant_minutes", 0) or 0))
    action_ctx["smartphone_result"] = result
    action_ctx["smartphone_handled"] = True
    action_ctx.pop("smartphone_op", None)


def maybe_police_track_phone_daily(state: dict[str, Any]) -> None:
    """Once per sim day: powered phone + high trace tier → small trace bump (deterministic)."""
    sp = ensure_smartphone(state)
    if not bool(sp.get("phone_on", True)):
        return
    try:
        tier = str(get_trace_tier(state).get("tier_id", "") or "")
        if tier not in ("Wanted", "Lockdown"):
            return
        tr = state.setdefault("trace", {})
        cur = int(tr.get("trace_pct", 0) or 0)
        tr["trace_pct"] = min(100, cur + 2)
        state.setdefault("world_notes", []).append(
            "[PhoneTrack] Carrier metadata + tower logs increased pressure while your phone stayed on."
        )
    except Exception as _omni_sw_254:
        log_swallowed_exception('engine/systems/smartphone.py:254', _omni_sw_254)
def parse_phone_command(cmd: str) -> dict[str, Any] | None:
    """Parse PHONE / SMARTPHONE CLI into smartphone_op + action_ctx fields, or None."""
    raw = str(cmd or "").strip()
    if not raw:
        return None
    up = raw.upper().strip()
    if not (up.startswith("PHONE ") or up.startswith("SMARTPHONE ") or up in ("PHONE", "SMARTPHONE")):
        return None
    parts = raw.split()
    if parts and parts[0].upper() == "SMARTPHONE":
        rest = parts[1:]
    else:
        rest = parts[1:] if len(parts) > 1 else []

    ctx: dict[str, Any] = {
        "normalized_input": raw.lower(),
        "action_type": "instant",
        "domain": "other",
        "intent_note": "smartphone",
        "trained": True,
        "uncertain": False,
        "has_stakes": False,
        "stakes": "none",
        "risk_level": "low",
        "trivial": True,
    }

    if not rest or rest[0].upper() == "HELP":
        ctx["smartphone_cli_help"] = True
        return ctx

    sub0 = rest[0].upper()
    if sub0 == "STATUS":
        ctx["smartphone_op"] = {"op": "power", "value": "status"}
        ctx["instant_minutes"] = 0
        return ctx
    if sub0 == "ON":
        ctx["smartphone_op"] = {"op": "power", "value": "on"}
        return ctx
    if sub0 == "OFF":
        ctx["smartphone_op"] = {"op": "power", "value": "off"}
        return ctx
    if sub0 == "CALL" and len(rest) >= 2:
        ctx["smartphone_op"] = {"op": "call", "target": " ".join(rest[1:]).strip()}
        return ctx
    if sub0 in ("MSG", "MESSAGE", "SMS", "WA") and len(rest) >= 3:
        target = rest[1].strip()
        body = " ".join(rest[2:]).strip()
        ctx["smartphone_op"] = {"op": "message", "target": target, "body": body}
        return ctx
    if sub0 in ("DARKWEB", "DARK", "DARK_WEB"):
        ctx["smartphone_op"] = {"op": "dark_web"}
        return ctx

    ctx["smartphone_cli_error"] = True
    return ctx
