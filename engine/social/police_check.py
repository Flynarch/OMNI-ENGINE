from __future__ import annotations

from typing import Any
import hashlib


def _has_illegal_weapon(state: dict[str, Any]) -> tuple[bool, list[str]]:
    """Return illegal weapons the player is currently carrying (not stashed)."""
    inv = state.get("inventory", {}) or {}
    if not isinstance(inv, dict):
        return (False, [])

    held: set[str] = set()
    for key in ("bag_contents", "pocket_contents"):
        arr = inv.get(key, [])
        if isinstance(arr, list):
            for x in arr[:80]:
                s = str(x or "").strip()
                if s:
                    held.add(s)
    for key in ("r_hand", "l_hand", "worn"):
        v = str(inv.get(key, "") or "").strip()
        if v and v != "-":
            held.add(v)

    if not held:
        return (False, [])

    world = state.get("world", {}) or {}
    idx = (world.get("content_index", {}) or {}) if isinstance(world, dict) else {}
    items = idx.get("items", {}) if isinstance(idx, dict) else {}
    out: list[str] = []
    for wid_s in sorted(list(held))[:120]:
        meta = items.get(wid_s) if isinstance(items, dict) else None
        tags = meta.get("tags", []) if isinstance(meta, dict) else []
        if not isinstance(tags, list):
            tags = []
        tags_l = [str(x).lower() for x in tags if isinstance(x, str)]
        if "weapons" not in tags_l and "weapon" not in tags_l:
            continue
        if "illegal_in_many_regions" in tags_l or "contraband" in tags_l:
            out.append(wid_s)
    return (bool(out), out)


def _inv_all_items(state: dict[str, Any]) -> list[str]:
    inv = state.get("inventory", {}) or {}
    if not isinstance(inv, dict):
        return []
    out: list[str] = []
    for key in ("bag_contents", "pocket_contents"):
        arr = inv.get(key, [])
        if isinstance(arr, list):
            for x in arr[:120]:
                s = str(x or "").strip()
                if s:
                    out.append(s)
    for key in ("r_hand", "l_hand", "worn"):
        v = str(inv.get(key, "") or "").strip()
        if v and v != "-":
            out.append(v)
    # de-dupe, preserve order
    seen: set[str] = set()
    uniq: list[str] = []
    for x in out:
        if x not in seen:
            uniq.append(x)
            seen.add(x)
    return uniq


def _item_tags(state: dict[str, Any], item_id: str) -> list[str]:
    world = state.get("world", {}) or {}
    idx = (world.get("content_index", {}) or {}) if isinstance(world, dict) else {}
    items = idx.get("items", {}) if isinstance(idx, dict) else {}
    row = items.get(str(item_id)) if isinstance(items, dict) else None
    if not isinstance(row, dict):
        return []
    t = row.get("tags", [])
    if not isinstance(t, list):
        return []
    out: list[str] = []
    for x in t[:60]:
        if isinstance(x, str) and x.strip():
            s = x.strip().lower()
            if s not in out:
                out.append(s)
    return out


def _issuer_from_tags(tags: list[str]) -> str:
    for t in tags:
        if isinstance(t, str) and t.startswith("issuer_"):
            return t.split("_", 1)[1].strip().lower()
    return ""


def _permit_doc_status(state: dict[str, Any], *, country: str) -> dict[str, Any]:
    """Check for a weapon permit document in inventory and whether it's valid for this country."""
    c = str(country or "").strip().lower()
    present = False
    forged = False
    issuer = ""
    permit_item_id = ""
    for iid in _inv_all_items(state):
        tags = _item_tags(state, iid)
        if "weapon_permit" not in tags:
            continue
        present = True
        permit_item_id = iid
        issuer = _issuer_from_tags(tags)
        forged = ("forged" in tags) or (issuer == "" and "issuer_" not in " ".join(tags))
        break

    if not present:
        return {
            "permit_present": False,
            "permit_item_id": "",
            "permit_issuer": "",
            "permit_valid": False,
            "permit_forged": False,
            "permit_forged_passed": False,
            "permit_note": "",
        }

    # Canonical issuer matching: allow aliases.
    issuer_ok = False
    if issuer:
        aliases = {"us": "usa", "united_states": "usa", "unitedstates": "usa", "id": "indonesia", "idn": "indonesia"}
        iss = aliases.get(issuer, issuer)
        cc = aliases.get(c, c)
        issuer_ok = bool(iss and cc and (iss == cc))

    # If forged, deterministically decide whether it passes a quick glance (corruption helps; strict hurts).
    forged_passed = False
    if forged:
        law = "standard"
        corruption = "medium"
        try:
            from engine.world.atlas import ensure_country_profile

            prof = ensure_country_profile(state, c)
            if isinstance(prof, dict):
                law = str(prof.get("law_level", "standard") or "standard").lower()
                corruption = str(prof.get("corruption", "medium") or "medium").lower()
        except Exception:
            pass
        base = 35
        if corruption == "high":
            base += 25
        elif corruption == "low":
            base -= 12
        if law in ("strict", "militarized"):
            base -= 12
        if not issuer_ok:
            base -= 10
        base = max(5, min(80, base))
        meta = state.get("meta", {}) or {}
        seed = str(meta.get("world_seed", "") or meta.get("seed_pack", "") or "").strip()
        day = int(meta.get("day", 1) or 1) if isinstance(meta, dict) else 1
        t = int(meta.get("time_min", 0) or 0) if isinstance(meta, dict) else 0
        h = hashlib.md5(f"{seed}|{day}|{t}|{c}|{permit_item_id}|permit_check".encode("utf-8", errors="ignore")).hexdigest()
        r = int(h[:8], 16) % 100
        forged_passed = r < base

    valid = (issuer_ok and (not forged)) or forged_passed
    note = "valid" if valid else ("forged_suspected" if forged else "issuer_mismatch")
    return {
        "permit_present": True,
        "permit_item_id": permit_item_id,
        "permit_issuer": issuer,
        "permit_valid": bool(valid),
        "permit_forged": bool(forged),
        "permit_forged_passed": bool(forged_passed),
        "permit_note": note,
    }


def _has_weapon_permit(state: dict[str, Any], *, country: str = "") -> bool:
    # Backward-compatible flag (older saves).
    p = state.get("player", {}) or {}
    if isinstance(p, dict):
        lic = p.get("licenses", {}) or {}
        if isinstance(lic, dict) and bool(lic.get("weapon_permit", False)):
            return True
    # New: real document check.
    st = _permit_doc_status(state, country=str(country or ""))
    return bool(st.get("permit_valid", False))


def schedule_weapon_check(state: dict[str, Any], *, weapon_ids: list[str], reason: str = "unspecified", extra_payload: dict[str, Any] | None = None) -> None:
    """Force-schedule a weapon check (used by stings/raids), avoiding duplicates."""
    meta = state.get("meta", {}) or {}
    day = int(meta.get("day", 1) or 1)
    t = int(meta.get("time_min", 0) or 0)
    events = state.setdefault("pending_events", [])
    if isinstance(events, list):
        for ev in events:
            if not isinstance(ev, dict):
                continue
            if str(ev.get("event_type", "") or "") == "police_weapon_check" and not bool(ev.get("triggered")):
                return

    loc = str((state.get("player", {}) or {}).get("location", "") or "").strip()
    loc_key = loc.strip().lower()
    country = ""
    firearm_ctx: dict[str, Any] = {}
    try:
        from engine.world.atlas import ensure_location_profile

        if loc:
            prof = ensure_location_profile(state, loc)
            if isinstance(prof, dict):
                country = str(prof.get("country", "") or "").strip().lower()
        firearm_ctx = _firearm_policy_for_country(state, country=country or "unknown")
    except Exception:
        firearm_ctx = _firearm_policy_for_country(state, country="unknown")

    pstat = _permit_doc_status(state, country=country or "")
    payload = {
        "weapon_ids": list(weapon_ids or [])[:20],
        "weapon_illegal": True,
        "has_weapon_permit": _has_weapon_permit(state, country=country or ""),
        "permit_doc": pstat,
        "location": loc_key,
        "trace_pct": int((state.get("trace", {}) or {}).get("trace_pct", 0) or 0),
        "country": firearm_ctx.get("country", ""),
        "law_level": firearm_ctx.get("law_level", ""),
        "firearm_policy": firearm_ctx.get("firearm_policy", ""),
        "firearm_policy_narrative": firearm_ctx.get("narrative", ""),
        "dialog": firearm_ctx.get("dialog", {}),
        "reason": str(reason or "unspecified"),
    }
    if isinstance(extra_payload, dict) and extra_payload:
        payload.update(extra_payload)
    events.append(
        {
            "event_type": "police_weapon_check",
            "title": "Pemeriksaan Polisi — Senjata",
            "due_day": day,
            "due_time": min(1439, t + 1),
            "triggered": False,
            "payload": payload,
        }
    )


def _firearm_policy_for_country(state: dict[str, Any], *, country: str) -> dict[str, str]:
    """Abstract firearm policy per country for AI to narrate consequences.

    We lean on atlas law_level + hand-crafted anchors (e.g. US vs Indonesia).
    """
    c = str(country or "").strip().lower()
    law = "standard"
    try:
        from engine.world.atlas import ensure_country_profile

        prof = ensure_country_profile(state, c)
        if isinstance(prof, dict):
            law = str(prof.get("law_level", "standard") or "standard").lower()
            c = str(prof.get("name", c) or c).lower()
    except Exception:
        pass

    policy = "standard_permit"
    narrative = "Kepemilikan senjata pribadi diatur dengan izin (permit) dan pemeriksaan ketat."
    dialog: dict[str, list[str]] = {
        "opener": [
            "Petugas menghentikanmu dan melirik ke arah tasmu.",
            "Patroli polisi memperlambat langkah saat melihatmu.",
        ],
        "ask_weapon": [
            "“Apakah kamu membawa senjata api saat ini?”",
            "“Ada senjata tajam atau senjata api di badan atau tasmu?”",
        ],
        "ask_permit": [
            "“Kalau memang ada, tunjukkan izin/weapon permit kamu.”",
            "“Legal nggak senjata itu? Ada surat izinnya?”",
        ],
        "hint_consequences": [
            "Mereka memperingatkan bahwa berbohong soal senjata bisa berakibat lebih parah daripada mengaku.",
            "Salah satu petugas mengingatkan, “Lebih baik jujur daripada kami temukan sendiri.”",
        ],
        "reaction_honest_legal": [
            "Petugas mengecek izinnya, mengembalikan senjata, dan melepasmu dengan teguran singkat.",
            "Setelah verifikasi izin, mereka hanya mencatat identitasmu dan menyuruhmu pergi.",
        ],
        "reaction_honest_illegal": [
            "Mereka langsung menyita senjatamu dan mencatat kasus pelanggaran kepemilikan senjata.",
            "Petugas saling bertukar pandang, lalu mengamankan senjata dan memintamu ikut ke pos untuk pendataan.",
        ],
        "reaction_lie_caught": [
            "Begitu mereka menemukan senjata setelah kamu mengaku tidak bawa apa-apa, nada bicara mereka langsung mengeras.",
            "Ketika penggeledahan menemukan pistol yang kamu sembunyikan, mereka menuduhmu berbohong dan menyabotase pemeriksaan.",
        ],
        "reaction_try_bribe": [
            "Saat kamu mencoba menyelipkan uang, ekspresi petugas sulit dibaca—bisa jadi ini justru memperburuk situasi.",
            "Upaya suapmu membuat suasana jadi tegang; kamu tidak tahu apakah mereka tergoda atau tersinggung.",
        ],
    }

    # Hand-tuned anchors for more grounded flavor.
    if c in ("united states", "usa", "united states of america"):
        policy = "permit_friendly"
        narrative = (
            "Di sini, kepemilikan handgun bisa legal dengan weapon permit, "
            "tapi membawa senjata tersembunyi tanpa izin jelas bermasalah."
        )
        dialog["opener"].extend(
            [
                "Mobil patroli melambat di sebelahmu; di negara ini orang bersenjata bukan hal asing, tapi tetap diawasi.",
            ]
        )
        dialog["hint_consequences"].append(
            "Mereka mengingatkan bahwa di sini, concealed carry tanpa izin bisa langsung berujung penahanan."
        )
    elif c in ("indonesia",):
        policy = "civilian_ban"
        narrative = (
            "Di sini, kepemilikan senjata api oleh warga sipil sangat dibatasi; "
            "bahkan dengan 'permit', polisi bisa menganggapmu mencurigakan."
        )
        dialog["opener"].extend(
            [
                "Pos polisi jalanan menghentikanmu; di negara ini warga sipil jarang sekali boleh membawa senjata api.",
            ]
        )
        dialog["hint_consequences"].append(
            "Petugas menegaskan bahwa kepemilikan senjata api oleh sipil hampir selalu dianggap pelanggaran berat."
        )
    elif c in ("japan", "united kingdom", "singapore"):
        policy = "civilian_ban"
        narrative = (
            "Negara ini terkenal sangat ketat soal senjata api; hampir semua kepemilikan pribadi dianggap pelanggaran."
        )
    else:
        if law == "lenient":
            policy = "lenient"
            narrative = (
                "Hukum senjata di sini relatif longgar; polisi masih bisa mewaspadai, "
                "tapi warga sipil bersenjata bukan hal yang luar biasa."
            )
        elif law in ("strict", "militarized"):
            policy = "strict"
            narrative = (
                "Hukum senjata di sini ketat; membawa pistol, apalagi ilegal, "
                "bisa memicu respon keras dari aparat."
            )

    return {
        "country": c,
        "law_level": law,
        "firearm_policy": policy,
        "narrative": narrative,
        "dialog": dialog,
    }


def maybe_schedule_weapon_check(state: dict[str, Any]) -> None:
    """Chance-based street stop when carrying illegal weapons.

    This only schedules a pending_event; narrative + choices handled by AI layer.
    """
    has_illegal, wid_list = _has_illegal_weapon(state)
    if not has_illegal:
        return

    meta = state.get("meta", {}) or {}
    day = int(meta.get("day", 1) or 1)
    t = int(meta.get("time_min", 0) or 0)
    trace = state.get("trace", {}) or {}
    tp = int(trace.get("trace_pct", 0) or 0)

    loc = str((state.get("player", {}) or {}).get("location", "") or "").strip()
    loc_key = loc.strip().lower()
    loc_tags: list[str] = []
    try:
        world = state.get("world", {}) or {}
        slot = (world.get("locations", {}) or {}).get(loc_key) if loc_key else None
        if isinstance(slot, dict):
            lt = slot.get("tags", []) or []
            if isinstance(lt, list):
                loc_tags = [str(x).lower() for x in lt if isinstance(x, str)]
    except Exception:
        loc_tags = []

    # District police presence (within city) also increases street checks.
    try:
        p = state.get("player", {}) or {}
        loc0 = str(p.get("location", "") or "").strip().lower()
        did0 = str(p.get("district", "") or "").strip().lower()
        if loc0 and did0:
            from engine.world.districts import get_district

            d0 = get_district(state, loc0, did0)
            if isinstance(d0, dict):
                pp = int(d0.get("police_presence", 0) or 0)
                if pp >= 4:
                    loc_tags.append("checkpoint_strict")
                elif pp == 3:
                    chance_boost = 4
                    # apply after base chance computed
                    loc_tags.append(f"_district_police_boost_{chance_boost}")
    except Exception:
        pass

    # Base chance per tick (0..100).
    chance = 0
    if "police_sweep" in loc_tags or "checkpoint_strict" in loc_tags:
        chance += 18
    if "surveillance_high" in loc_tags:
        chance += 8
    if tp >= 75:
        chance += 20
    elif tp >= 50:
        chance += 12
    elif tp >= 25:
        chance += 6

    # Police faction attention escalates checks.
    try:
        world = state.get("world", {}) or {}
        fs = (world.get("faction_statuses", {}) or {}) if isinstance(world, dict) else {}
        pol = str(fs.get("police", "idle") or "idle").lower()
        if pol == "aware":
            chance += 4
        elif pol == "investigated":
            chance += 10
        elif pol == "manhunt":
            chance += 20
    except Exception:
        pass

    chance = max(0, min(65, chance))
    # Apply small district boost if present.
    try:
        for t in loc_tags:
            if isinstance(t, str) and t.startswith("_district_police_boost_"):
                chance += int(t.rsplit("_", 1)[-1])
    except Exception:
        pass
    chance = max(0, min(72, chance))
    if chance <= 0:
        return

    # Deterministic "random" gate using world_seed+day+time+loc.
    seed = str(meta.get("world_seed", "") or meta.get("seed_pack", "") or "").strip()
    h = hashlib.md5(f"{seed}|{day}|{t}|{loc}|{tp}|police_weapon_check".encode("utf-8", errors="ignore")).hexdigest()
    r = int(h[:8], 16) % 100
    if r >= chance:
        return

    # Avoid spamming: if an upcoming, untriggered event of this type already exists, skip.
    events = state.setdefault("pending_events", [])
    if isinstance(events, list):
        for ev in events:
            if not isinstance(ev, dict):
                continue
            if str(ev.get("event_type", "") or "") == "police_weapon_check" and not bool(ev.get("triggered")):
                return

    # Country / firearm policy context.
    country = ""
    firearm_ctx: dict[str, str] = {}
    try:
        from engine.world.atlas import ensure_location_profile

        if loc:
            prof = ensure_location_profile(state, loc)
            if isinstance(prof, dict):
                country = str(prof.get("country", "") or "").strip().lower()
        firearm_ctx = _firearm_policy_for_country(state, country=country or "unknown")
    except Exception:
        firearm_ctx = _firearm_policy_for_country(state, country="unknown")

    permit_doc = _permit_doc_status(state, country=country or "")
    payload = {
        "weapon_ids": wid_list,
        "weapon_illegal": True,
        "has_weapon_permit": _has_weapon_permit(state, country=country or ""),
        "permit_doc": permit_doc,
        "location": loc_key,
        "trace_pct": tp,
        "country": firearm_ctx.get("country", ""),
        "law_level": firearm_ctx.get("law_level", ""),
        "firearm_policy": firearm_ctx.get("firearm_policy", ""),
        "firearm_policy_narrative": firearm_ctx.get("narrative", ""),
        "dialog": firearm_ctx.get("dialog", {}),
    }
    events.append(
        {
            "event_type": "police_weapon_check",
            "title": "Pemeriksaan Polisi — Senjata",
            "due_day": day,
            "due_time": t + 1,
            "triggered": False,
            "payload": payload,
        }
    )

