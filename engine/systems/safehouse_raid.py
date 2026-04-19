from __future__ import annotations

import hashlib
from typing import Any

from engine.core.error_taxonomy import log_swallowed_exception
from engine.world.atlas import ensure_location_profile
from engine.world.districts import get_district


def _here_key(state: dict[str, Any]) -> str:
    return str((state.get("player", {}) or {}).get("location", "") or "").strip().lower()

def _has_weapon_permit(state: dict[str, Any]) -> bool:
    p = state.get("player", {}) or {}
    if not isinstance(p, dict):
        return False
    lic = p.get("licenses", {}) or {}
    if not isinstance(lic, dict):
        return False
    return bool(lic.get("weapon_permit", False))


def _firearm_policy(country: str, law_level: str) -> str:
    c = str(country or "").strip().lower()
    law = str(law_level or "standard").strip().lower()
    if c in ("united states", "usa", "united states of america"):
        return "permit_friendly"
    if c in ("indonesia", "japan", "united kingdom", "singapore"):
        return "civilian_ban"
    if law == "lenient":
        return "lenient"
    if law in ("strict", "militarized"):
        return "strict"
    return "standard_permit"


def _stash_hot_items(state: dict[str, Any], *, loc: str) -> list[str]:
    """Return list of contraband item_ids currently stashed at loc."""
    world = state.get("world", {}) or {}
    sh = (world.get("safehouses", {}) or {}) if isinstance(world, dict) else {}
    row = sh.get(loc) if isinstance(sh, dict) else None
    if not isinstance(row, dict):
        return []
    stash = row.get("stash") or []
    if not isinstance(stash, list) or not stash:
        stash = []

    stash_ammo = row.get("stash_ammo") or {}
    if not isinstance(stash_ammo, dict):
        stash_ammo = {}

    idx = (world.get("content_index", {}) or {}) if isinstance(world, dict) else {}
    items = idx.get("items", {}) if isinstance(idx, dict) else {}

    out: list[str] = []
    for ent in stash[:200]:
        iid = ""
        if isinstance(ent, dict):
            iid = str(ent.get("item_id", "") or "").strip()
        elif isinstance(ent, str):
            iid = ent.strip()
        if not iid:
            continue
        meta = items.get(iid) if isinstance(items, dict) else None
        tags = meta.get("tags", []) if isinstance(meta, dict) else []
        if not isinstance(tags, list):
            tags = []
        tags_l = [str(x).lower() for x in tags if isinstance(x, str)]
        if "illegal_in_many_regions" in tags_l or "contraband" in tags_l or ("ammo" in tags_l and "restricted" in tags_l):
            out.append(iid)
    # Any restricted ammo stored counts as hot (even without physical ammo boxes).
    for aid, n in list(stash_ammo.items())[:200]:
        try:
            nn = int(n or 0)
        except Exception as _omni_sw_72:
            log_swallowed_exception('engine/systems/safehouse_raid.py:72', _omni_sw_72)
            nn = 0
        if nn <= 0:
            continue
        meta = items.get(str(aid)) if isinstance(items, dict) else None
        tags = meta.get("tags", []) if isinstance(meta, dict) else []
        if not isinstance(tags, list):
            tags = []
        tags_l = [str(x).lower() for x in tags if isinstance(x, str)]
        if "ammo" in tags_l and "restricted" in tags_l:
            out.append(str(aid))
    return out


def set_pending_raid_response(
    state: dict[str, Any],
    *,
    action: str,
    bribe_amount: int = 0,
) -> dict[str, Any]:
    """Set response for the nearest pending safehouse_raid at current location."""
    loc = _here_key(state)
    if not loc:
        return {"ok": False, "reason": "no_location"}
    pe = state.get("pending_events", []) or []
    if not isinstance(pe, list):
        return {"ok": False, "reason": "no_pending_events"}

    target = None
    for ev in pe:
        if not isinstance(ev, dict) or ev.get("triggered"):
            continue
        if str(ev.get("event_type", "") or "") != "safehouse_raid":
            continue
        payload = ev.get("payload") or {}
        if isinstance(payload, dict) and str(payload.get("location", "") or "").strip().lower() == loc:
            target = ev
            break
    if target is None:
        return {"ok": False, "reason": "no_pending_safehouse_raid_here"}

    a = str(action or "").strip().lower()
    if a in ("none", "-", ""):
        a = "none"
    if a in ("cooperate", "comply", "open", "ok"):
        a = "comply"
    if a in ("hide", "stash", "conceal", "clean"):
        a = "hide"
    if a in ("bribe", "pay", "suap"):
        a = "bribe"
    if a in ("flee", "run", "escape", "kabur"):
        a = "flee"
    if a in ("talk", "negotiate", "nego", "reason", "argue"):
        a = "negotiate"
    if a in ("permit", "show_permit", "showpermit", "show", "tunjuk_izin", "izin"):
        a = "show_permit"
    if a not in ("none", "comply", "hide", "bribe", "flee", "negotiate", "show_permit"):
        return {"ok": False, "reason": "invalid_action", "allowed": ["comply", "hide", "bribe <amt>", "flee", "negotiate", "show_permit"]}

    payload = target.get("payload") or {}
    if not isinstance(payload, dict):
        payload = {}
    payload["response"] = a
    payload["bribe_amount"] = int(max(0, min(1_000_000_000, int(bribe_amount or 0))))
    payload.setdefault("response_notes", [])
    if isinstance(payload.get("response_notes"), list):
        payload["response_notes"].append(f"player_response={a} bribe={payload['bribe_amount']}")
    target["payload"] = payload
    return {"ok": True, "action": a, "bribe_amount": int(payload["bribe_amount"]), "location": loc}


def maybe_schedule_safehouse_raid(state: dict[str, Any]) -> None:
    """Chance-based police raid on the CURRENT location safehouse if stash contains contraband.

    Security level reduces chance; strict countries increase it.
    """
    loc = _here_key(state)
    if not loc:
        return
    world = state.get("world", {}) or {}
    sh = world.get("safehouses", {}) or {}
    row = sh.get(loc) if isinstance(sh, dict) else None
    if not isinstance(row, dict):
        return
    if str(row.get("status", "none") or "none") == "none":
        return
    # Cooldown after a raid / burnout window.
    meta = state.get("meta", {}) or {}
    day = int(meta.get("day", 1) or 1)
    try:
        cd = int(row.get("raid_cooldown_until_day", 0) or 0)
    except Exception as _omni_sw_163:
        log_swallowed_exception('engine/systems/safehouse_raid.py:163', _omni_sw_163)
        cd = 0
    if cd and day <= cd:
        return

    hot = _stash_hot_items(state, loc=loc)
    if not hot:
        return

    meta = state.get("meta", {}) or {}
    day = int(meta.get("day", 1) or 1)
    t = int(meta.get("time_min", 0) or 0)
    tr = state.get("trace", {}) or {}
    tp = int(tr.get("trace_pct", 0) or 0)

    # Country law affects raid intensity.
    country = ""
    law = "standard"
    corruption = "medium"
    try:
        prof = ensure_location_profile(state, loc)
        if isinstance(prof, dict):
            country = str(prof.get("country", "") or "").strip().lower()
            law = str(prof.get("law_level", law) or law).lower()
            corruption = str(prof.get("corruption", corruption) or corruption).lower()
    except Exception as _omni_sw_190:
        log_swallowed_exception('engine/systems/safehouse_raid.py:190', _omni_sw_190)
    sec = int(row.get("security_level", 1) or 1)
    delin = int(row.get("delinquent_days", 0) or 0)
    has_permit = _has_weapon_permit(state)
    fp = _firearm_policy(country, law)
    disguise_active = bool(((state.get("disguise", {}) or {}).get("active", False))) or bool(((state.get("player", {}) or {}).get("disguise", {}) or {}).get("active", False))

    # Base chance per tick: scaled by trace and strictness.
    chance = 0
    if tp >= 80:
        chance += 16
    elif tp >= 60:
        chance += 10
    elif tp >= 40:
        chance += 6
    elif tp >= 25:
        chance += 3

    # More contraband = bigger footprint.
    chance += min(10, len(hot))

    # District police presence affects raid likelihood (downtown/financial are hotter).
    try:
        p = state.get("player", {}) or {}
        did0 = str(p.get("district", "") or "").strip().lower()
        if did0:
            d0 = get_district(state, loc, did0)
            if isinstance(d0, dict):
                pp = int(d0.get("police_presence", 0) or 0)
                chance += 3 if pp == 3 else 6 if pp >= 4 else 0
    except Exception as _omni_sw_224:
        log_swallowed_exception('engine/systems/safehouse_raid.py:224', _omni_sw_224)
    # Law & delinquency.
    if law in ("strict", "militarized"):
        chance += 6
    if delin >= 2:
        chance += 6
    # If you're actively disguised, reduce raid likelihood slightly (harder to link you).
    if disguise_active:
        chance -= 2

    # Security reduces.
    chance -= max(0, min(10, sec * 2))

    # Bound.
    chance = max(0, min(45, chance))
    if chance <= 0:
        return

    # Deduplicate: only one pending raid ahead.
    pe = state.get("pending_events", []) or []
    if isinstance(pe, list):
        for ev in pe:
            if isinstance(ev, dict) and str(ev.get("event_type", "") or "") == "safehouse_raid" and not bool(ev.get("triggered")):
                return

    seed = str(meta.get("world_seed", "") or meta.get("seed_pack", "") or "").strip()
    h = hashlib.md5(f"{seed}|{day}|{t}|{loc}|{tp}|{sec}|safehouse_raid".encode("utf-8", errors="ignore")).hexdigest()
    r = int(h[:8], 16) % 100
    if r >= chance:
        return

    payload = {
        "location": loc,
        "country": country,
        "law_level": law,
        "corruption": corruption,
        "firearm_policy": fp,
        "has_weapon_permit": has_permit,
        "disguise_active": disguise_active,
        "security_level": sec,
        "delinquent_days": delin,
        "trace_snapshot": tp,
        "hot_item_ids": hot[:20],
        "response": "none",  # none|comply|hide|bribe|flee
        "bribe_amount": 0,
        "response_notes": [],
        "dialog": {
            "opener": [
                "Pagi itu, gedoran keras mengguncang pintu safehouse.",
                "Ketukan cepat di pintu berubah jadi teriakan perintah untuk membuka.",
                "Suara sepatu bot di koridor berhenti tepat di depan unitmu.",
            ],
            "announce": [
                "“POLISI. Pemeriksaan. Buka pintu.”",
                "“Kami menerima laporan. Buka sekarang.”",
                "“Penggeledahan. Jangan buat ini sulit.”",
            ],
            "search": [
                "Mereka menyisir ruangan dengan gerakan hafal, mencari sesuatu yang spesifik.",
                "Petugas memeriksa sudut-sudut, laci, dan bagian belakang lemari.",
                "Senter menelusuri tiap celah—terlalu teliti untuk sekadar ‘cek rutin’.",
            ],
            "found": [
                "Salah satu petugas mengangkat barang bukti dan memberi kode pada rekan-rekannya.",
                "Mereka menemukan sesuatu. Wajahmu bisa menyembunyikan panik, tapi ruangan tidak bisa.",
            ],
            "outcome_soft": [
                "Mereka menyita barang dan meninggalkan surat panggilan. Untuk saat ini, kamu tidak diborgol—tapi kamu dicatat.",
                "Mereka menyita dan memperingatkan: satu langkah lagi, dan ini naik jadi kasus besar.",
            ],
            "outcome_hard": [
                "Mereka mengamankan lokasi dan membawamu untuk pemeriksaan lebih lanjut.",
                "Situasi memburuk cepat—diborgol, digeledah, dan dibawa keluar tanpa banyak bicara.",
            ],
            "negotiate": [
                "Kamu mencoba bicara tenang—minta prosedur yang jelas, nama petugas, dan alasan penggeledahan.",
                "Kamu menahan napas dan berusaha mengontrol percakapan, berharap celah hukum bisa memperlambat mereka.",
            ],
            "show_permit": [
                "Kamu mengeluarkan dokumen/permit dan menunjukkannya dengan tangan yang stabil.",
                "Kamu menawarkan permit lebih dulu, mencoba membingkai situasi sebagai 'misunderstanding'.",
            ],
        },
    }
    state.setdefault("pending_events", []).append(
        {
            "event_type": "safehouse_raid",
            "title": "Police Raid — Safehouse",
            "due_day": day,
            # Give the player a short window to react with SAFEHOUSE RAID <action>.
            "due_time": min(1439, t + 12),
            "triggered": False,
            "payload": payload,
        }
    )

