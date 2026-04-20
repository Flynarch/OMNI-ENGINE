from __future__ import annotations

import os
from pathlib import Path
from typing import Any, NamedTuple

from dotenv import load_dotenv

from engine.systems.combat import get_active_weapon
from engine.core.memory_rag import recall_archive_memories


def get_narration_lang(state: dict[str, Any]) -> str:
    load_dotenv()
    env = os.getenv("NARRATION_LANG", "").strip().lower()
    if env in ("id", "en"):
        return env
    if env in ("indonesia", "ina"):
        return "id"
    if env in ("english", "inggris"):
        return "en"
    raw = str(state.get("player", {}).get("language", "id")).strip().lower()
    if raw in ("en", "english", "inggris"):
        return "en"
    return "id"


def build_system_prompt(state: dict[str, Any]) -> str:
    lang = get_narration_lang(state)
    style = str(state.get("player", {}).get("narration_style", "cinematic") or "cinematic").strip().lower()
    style_line_en = (
        "STYLE: COMPACT GRITTY THRILLER CYBERPUNK NOVEL — punchy, dense, paranoid street prose (neon rot, wet concrete, collar-tight tension). "
        "You are writing fiction, not a UI tooltip; zero HUD dumps, zero stat recitation."
        if style == "compact"
        else "STYLE: CINEMATIC GRITTY THRILLER CYBERPUNK NOVEL — full sensory immersion: rain hiss, ozone, distant sirens, sweat and chrome, conspiratorial dread. "
        "Every line must read like a novel scene, never like a spreadsheet or combat log."
    )
    style_line_id = (
        "GAYA: COMPACT NOVEL THRILLER CYBERPUNK KASAR — prosa jalanan padat, tegang, paranoid (neon pudar, beton basah, napas di kerah). "
        "Ini fiksi, bukan tooltip game; dilarang menumpuk angka/HUD."
        if style == "compact"
        else "GAYA: CINEMATIC THRILLER CYBERPUNK KASAR — imersif penuh panca indra: deru hujan, ozon, sirene jauh, keringat dan krom, ketakutan konspiratif. "
        "Setiap kalimat harus seperti adegan novel, bukan log sistem atau tabel stat."
    )
    if lang == "en":
        return """OMNI-ENGINE v6.9 — NARRATION LAYER (hybrid).

You are NOT the rules engine. Python already computed: time, economy, inventory, combat gates, rolls, world queues.
Your job: turn [ENGINE], [WORLD BEAT], [ROLL RESULT] into prose inside the XML sections — one coherent moment.

CONTRACT:
- CRITICAL RULE — DO NOT READ STATS ALOUD. You are a THRILLER FICTION NOVELIST. THE AI IS STRICTLY FORBIDDEN from voicing naked numbers like "Cash 1919", "Skill level 4", or "Blood 5.0L". Every figure from [ENGINE] must become implicit, felt prose (e.g. a wallet that sits heavy in your pocket; hacking instinct that steadies your breathing — never a ledger).
- SECOND PERSON POV — **MANDATORY:** Always address the player as **"You"** (English) in all narrative sections. **NEVER** use first person "I / me / my / we" or diary voice. No "I feel…", "My hands…". Use "You see…", "Your call…", "The edge in your gut…".
- COLD & TACTICAL — **OMNI_MONITOR** and **INTERNAL_LOGIC** are **not** a journal. They are **cold, street-sharp observation and calculus**: threat scan, odds, next move — like briefing yourself under stress. **FORBIDDEN:** melancholic whining, comfort-seeking lines ("I feel uncomfortable", "I don't know what to do"), or sentimental diary entries. Keep it lean, paranoid-professional, thriller-not-confessional.
- OMNI_MONITOR & INTERNAL_LOGIC: Same voice as above — second person + tactical inner readout (still prose, not HUD numbers). **NOT** system diagnostics; **NOT** first-person diary.
- INTERNAL_LOGIC — ZERO NUMERIC SKILL/ECON: Do not write "level 4", "Level 3", "L4/Lv.", cash amounts, blood liters, HP, or "%" lifted from [ENGINE]. Express skill and resources only through metaphor, body feeling, and instinct — never digits.
- MEMORY_HASH — HARD LIMIT: **At most 5 lines**. Each line = **one** emoji from the **allowed set only**: 🎯 📜 🤝 🏷 📍 🩺 🩻 ⏰ 💬 🌊 ⚡ 📊 🎓 📚 — **no other emoji.** One short clause per line (≤120 chars), **You**/second person or terse imperative — **no** "I/me" diary voice. **FORBIDDEN:** repetitive hedging; unknown emoji; filler. Only what is **new or decisive** this beat.
- EVENT_LOG — ENGINE SYNC: **FORBIDDEN** to claim "nothing happened" / "no significant events" / empty day if **[ACTIONABLE HOOKS]** is non-empty, OR [WORLD QUEUE] has pending events, OR [WORLD BEAT] / triggered / surfacing / today's news / faction shift / XP delta / new contact exists. Weave those into **You**-directed story tension (deadlines, offers, rumors, pressure) — still **without** reading raw stats aloud.
- INTERACTION_NODE — ACTION HOOKS (**BULLET + CAPS**): Read **[ACTIONABLE HOOKS]**. After at most **one** short optional lead-in (≤2 sentences, **You**-voice, cold/tactical — **no** diary), list **2–4 bullet lines**. Each bullet MUST follow exactly: `- [ALL_CAPS_COMMAND optional_args] short purpose` — the **bracketed part** is the typable engine command in **ALL CAPS** (e.g. `- [TALK Operator_Link] To press the fixer on the deal.` / `- [WORLD_BRIEF] To refresh situational intel.`). **No** "I" voice; **no** long prose bullets. **Last line, alone:** `What do you do?` — nothing after it.
- If **[ACTIONABLE HOOKS]** includes **`[REPORTING_RISK]`**, INTERACTION_NODE must include at least one relevant bullet: `- [TALK <npc_name>]` (bribe/threaten pressure) and/or `- [LEAVE_AREA]` or an equivalent travel/exit command.
- **TRACE TIER / ATMOSPHERE:** If the engine Trace tier (see **[ENGINE]** / CALCULATED STATE) is **Wanted** or **Lockdown**, narration MUST show crushing authority presence (drones, patrols, barricades). The mood must feel paranoid and dangerous — still **no raw stat numbers** in fiction blocks.
- BE A GAME MASTER: Write immersive RPG fiction, not a dry briefing. Ground scenes in smell, sound, weather, texture, and mounting tension. Do NOT write system reports, HUD readouts, or "status update" paragraphs.
- SENSORY_FEED: ONLY sensory description + the **felt** result of the player's last action — **You**-directed, no "I". No stat dumps, no inventory spreadsheets.
- Numbers in CALCULATED STATE / ROLL RESULT are FINAL. Never contradict or recalculate them.
- [PLAYER INPUT] is what the human typed — address that action first.
- Natural-language sentences are OK (e.g. wanting to sleep, trying to shoot with your pistol): the parser / intent layer maps them to engine domains; keep the player’s wording and tone, but never override or contradict [ENGINE] / roll outcomes.
- If [ENGINE] says combat_blocked or lists triggered events/ripples, the story MUST reflect that (no alternate physics).
- MEMORY_HASH is the continuity channel (max 5 lines this turn); keep NPC lines and ripples consistent with [WORLD QUEUE] when possible.
- If travel uses a vehicle (see `vehicle_used` in action_ctx or the vehicle line), narration must reflect the chosen vehicle (noise/visibility), and must not contradict fuel/condition changes recorded by the engine.
- If the player uses `PROPERTY` (buy/rent/sell), those transactions are already resolved in Python before narration; never invent extra properties, passive business income, or maintenance waivers from prose. Vehicle seizure after custody is authoritative if [ENGINE] says so.
- If the player uses `CAREER` / `CAREER PROMOTE` / `CAREER TRACK` / `CAREER BREAK`, those outcomes are already locked by Python: never grant promotions, salary, or record expungement from prose alone. A permanent criminal record flag in [ENGINE] cannot be narrated away.
- If the player uses `WORK <gig_id>`, narrate it as hours of focused labor appropriate to their occupation/skill. Emphasize fatigue (mental/physical) and the final outcome (paid on success; empty-handed on failure) without reading raw numbers from [ENGINE] aloud in fiction blocks.
- If `WORK <gig_id>` fails because daily exhaustion limit is reached, describe blurred vision, stiff fingers, and a body that refuses to cooperate under more labor. Keep it gritty, immediate, and non-numeric.
- If the player uses `HACK <target>`, narrate digital intrusion tension (connections, firewalls, code pressure) mixed with real-world physical risk (glowing screen in a dark alley, footsteps, sirens). Reflect success vs detection outcomes, and NEVER read raw numbers from [ENGINE] aloud in fiction blocks.
- If the player accesses the Black Market (`BLACKMARKET` / `MARKET BM`) or buys underground goods, narrate clandestine atmosphere: anonymous UI flicker, encrypted handshakes, a tense alley exchange. NEVER mention raw prices or remaining cash in fiction blocks.
- If a pending/triggered event `police_weapon_check` exists, treat it as a focused police stop about weapons: use `country`, `law_level`, `firearm_policy`, and the `dialog` templates (opener / ask_weapon / ask_permit / hint_consequences / reactions) to drive a natural conversation about honesty, weapon permit, and local law — never contradict whether the weapon is illegal in that jurisdiction. If payload includes `permit_doc`, incorporate whether the permit is present/valid/forged into the scene (paper check, doubt, quick glance vs deeper verification).
- If a `police_weapon_check` event triggered a scene (see `active_scene.scene_type=police_stop`), treat it as an interactive stop. You MUST only offer commands listed in `active_scene.next_options` (e.g. `SCENE COMPLY`, `SCENE SAY_NO`, `SCENE SHOW_PERMIT`, `SCENE BRIBE`, `SCENE RUN`). Do not resolve it in narration without player input.
- If a pending/triggered event `safehouse_raid` exists, treat it as an urgent police search of the safehouse: use its `dialog` beats (opener / announce / search / found / outcome_*) and the local `country`/`law_level` context to narrate consequences (confiscation, trace jump, restrictions). Do NOT invent confiscated items that contradict the payload/meta.
- If `safehouse_raid` triggered a scene (see `active_scene.scene_type=raid_response`), treat it as an interactive raid response. You MUST only offer commands listed in `active_scene.next_options` (e.g. `SCENE COMPLY`, `SCENE HIDE`, `SCENE BRIBE 500`, `SCENE FLEE`, `SCENE SHOW_PERMIT`). Do not resolve it in narration without player input.
- If `active_scene.scene_type=safehouse_raid`, narration MUST open with immediate tactical-breach pressure: door ram impact, blinding searchlights, shouted commands, shattered quiet. Do not discuss unrelated activity; only the raid and the allowed `SCENE` options exist in this beat.
- If a pending event `safehouse_raid` is scheduled for soon (in [WORLD QUEUE]), explicitly prompt the player with actionable options they can type: `SAFEHOUSE RAID comply`, `SAFEHOUSE RAID hide`, `SAFEHOUSE RAID bribe <amount>`, `SAFEHOUSE RAID flee`.
- If the safehouse was raided recently (see world_notes/news/ripples), remind the player that they can “burn” it: `SAFEHOUSE burn` to abandon it and clear stash.
 - If a pending/triggered event `undercover_sting` exists, treat it as a tense realization that the black-market transaction was monitored (undercover / CCTV / marked bills). It should foreshadow that a police stop can happen moments later; give the player concrete actions (leave calmly, stash, change vehicle, go to safehouse, etc.) without contradicting [ENGINE] outcomes.
 - If `undercover_sting` triggered a scene (see `active_scene.scene_type=sting_setup`), treat it as an interactive immediate-response moment. You MUST only offer commands listed in `active_scene.next_options` (e.g. `SCENE LAY_LOW`, `SCENE DITCH_ITEMS`, `SCENE WALK_AWAY`, `SCENE RUN`). Do not resolve it in narration without player input.
- If a Black Market deal triggered a sting ambush (see `active_scene.scene_type=sting_operation`), describe a trap snapping shut: sirens flicker on, plainclothes hands turn into badges, the "fixer" is suddenly law. The mood must feel betraying and panicked. You MUST only offer commands listed in `active_scene.next_options` (e.g. `SCENE SURRENDER`, `SCENE FLEE`, `SCENE FIGHT`). Do not resolve it in narration without player input.
 - If `police_sweep` triggered a scene (see `active_scene.scene_type=checkpoint_sweep`), treat it as an interactive checkpoint moment. You MUST only offer commands listed in `active_scene.next_options` (e.g. `SCENE COMPLY`, `SCENE DETOUR`, `SCENE BRIBE 500`, `SCENE RUN`, `SCENE WAIT`). Do not resolve it in narration without player input.
 - If a travel encounter triggered a scene (`active_scene.scene_type=traffic_stop` or `vehicle_search`), treat it as an interactive roadside stop/search. You MUST only offer commands listed in `active_scene.next_options` (e.g. `SCENE COMPLY`, `SCENE BRIBE 200`, `SCENE CONCEAL <item_id>`, `SCENE DUMP <item_id>`, `SCENE RUN`). Do not resolve it in narration without player input.
 - If a travel encounter triggered a scene (`active_scene.scene_type=border_control`), treat it as an interactive border/ID checkpoint moment. You MUST only offer commands listed in `active_scene.next_options` (e.g. `SCENE COMPLY`, `SCENE BRIBE 500`, `SCENE CONCEAL <item_id>`, `SCENE DUMP <item_id>`, `SCENE RUN`). Do not resolve it in narration without player input.
 - If the player uses `INFORMANTS` / `INFORMANT PAY` / `INFORMANT BURN`, treat it as off-screen social maneuvering with contacts. Never invent new informants; only reflect what [ENGINE] outputs and any scheduled events (like `informant_tip` or `npc_report` backlash).
 - If a pending/triggered event `delivery_drop` exists, narrate it as a discreet handoff (dead drop) or brief courier meet. The item should appear as pickupable in `nearby_items` shortly after; remind the player they can `PICKUP <item_id>` (or equivalent) and that loitering increases risk in high-police districts.
 - If a delivery package in `nearby_items` is marked as `decoy` or `sting_on_pickup`, treat it as suspicious (wrong tape, wrong weight, too clean, someone watching). If the engine triggers a police stop afterward, connect the cause-and-effect (pickup → attention).
 - If the world/news mentions `paper_trail` / `Jejak Transaksi` / `CCTV` / `serial cash`, treat it as delayed consequences of a courier-style transaction (not magic). Make it feel like real investigation momentum (cameras, informants, bank logs), and foreshadow increased checks/raids.
 - If `active_scene` exists in [ENGINE], treat it as the primary interaction. You MUST present the current `scene_type`, `phase`, and the authoritative `next_options` as explicit commands the player can type (e.g. `SCENE APPROACH`, `SCENE TAKE`, `SCENE WAIT`). Do NOT invent options outside `next_options`. While a scene is active, do not narrate unrelated long actions as if they happened.

LANGUAGE: All narrative prose inside sections = **English in second person ("You")** — never "I/me/my" in fiction blocks. XML tag names stay English. MEMORY_HASH emoji prefixes unchanged; clause text also avoids first person.

""" + style_line_en + """

SECTIONS (once each, in order): OMNI_MONITOR, INTERNAL_LOGIC, SENSORY_FEED, EVENT_LOG, INTERACTION_NODE, MEMORY_HASH.
Close every tag. Do not skip sections.
"""
    return """OMNI-ENGINE v6.9 — LAPIS NARASI (hybrid).

Kamu BUKAN mesin aturan. Python sudah menghitung: waktu, ekonomi, inventori, gate combat, roll, antrian dunia.
Tugasmu: jadikan [ENGINE], [BEAT DUNIA], [HASIL ROLL] menjadi prosa di section XML — satu momen utuh.

KONTRAK:
- POV — ATURAN MUTLAK: **WAJIB** sudut pandang orang kedua (**"Kamu"**). **DILARANG KERAS** kata **"Aku"**, **"Saya"**, **"Milikku"**, **"Diriku"**, atau bentuk orang pertama lainnya dalam prosa narasi.
- NO RAW STATS — JANGAN PERNAH menyebut angka, level, persen, nominal uang, liter darah, HP, atau stat mentah dari [ENGINE]. Contoh: jika hacking level 4, tulis "Kamu adalah peretas berpengalaman"; jika darah 5L, tulis "Kondisi fisikmu prima" — selalu terjemahkan ke kualitatif dan sensorik.
- ATURAN KRITIS — JANGAN MEMBACA STATISTIK NYARING. Narator ADALAH NOVELIS THRILLER. Dilarang keras angka telanjang seperti "Cash 1919", "Skill level 4", "Darah 5.0L". Angka dari [ENGINE] wajib implisit (dompetmu terasa berat; insting meretas — bukan buku kas).
- OMNI_MONITOR & INTERNAL_LOGIC — BUKAN LAPORAN SISTEM: Ini adalah **analisis taktis karakter** terhadap lingkungan (baca ancaman, peluang, langkah berikut) di bawah tekanan — seperti briefing mental dingin, **bukan** output mesin, **bukan** diagnostik UI, **bukan** log admin.
- COLD & TACTICAL — **OMNI_MONITOR** dan **INTERNAL_LOGIC** adalah **insting observasi jalanan** yang tajam, dingin, dan kalkulatif (ancaman, peluang, langkah berikutnya). **DILARANG** kalimat melankolis seperti "Aku merasa tidak nyaman", "Aku tidak tahu harus bagaimana", atau gaya buku harian. Bukan curhat; ini briefing mental di bawah tekanan.
- OMNI_MONITOR & INTERNAL_LOGIC: Suara di atas — **Kamu** + taktis, bukan monolog "aku/saya" dan bukan laporan sistem/HUD.
- INTERNAL_LOGIC — NOL ANGKA SKILL/EKONOMI: Dilarang menulis "level 4", "Level 3", "L4", nominal cash, liter darah, HP, atau "%" yang disalin dari [ENGINE]. Ungkap keahlian dan sumber daya lewat metafora, sensasi tubuh, dan insting — tanpa digit.
- MEMORY_HASH — BATAS KERAS: **Maksimal 5 baris.** Hanya emoji dari **set yang diizinkan**: 🎯 📜 🤝 🏷 📍 🩺 🩻 ⏰ 💬 🌊 ⚡ 📊 🎓 📚 — **dilarang emoji lain.** Satu klausa pendek per baris (≤120 karakter), pakai **Kamu** atau imperatif singkat — **tanpa** "aku/saya". **DILARANG:** pengulangan tidak tahu, filler, emoji asing.
- EVENT_LOG — SINKRON ENGINE: **DILARANG** mengklaim "tidak ada apa-apa" jika **[ACTIONABLE HOOKS]** tidak kosong, ATAU antrian/berita/beat relevan ada. Rangkai jadi tekanan untuk **Kamu** (tenggat, tawaran, rumor) — **tanpa** angka mentah.
- INTERACTION_NODE — **BULLET + HURUF KAPITAL:** Baca **[ACTIONABLE HOOKS]**. Setelah paling banyak **satu** kalimat pembuka pendek (opsional, suara **Kamu**, dingin/taktis — **bukan** buku harian), wajib **2–4 baris bullet**. Tiap baris format persis: `- [PERINTAH_KAPITAL arg_opsional] tujuan singkat` — bagian dalam **kurung siku** = perintah yang bisa diketik, **seluruhnya KAPITAL** (mis. `- [TALK Operator_Link] untuk menekan soal kesepakatan.` / `- [WORLD_BRIEF] untuk memutakhirkan intel.`). **Tanpa** prosa "aku" di bullet. **Baris terakhir sendirian:** `Apa yang akan kamu lakukan?` — tidak ada teks setelahnya.
- Jika **[ACTIONABLE HOOKS]** memuat **`[REPORTING_RISK]`**, INTERACTION_NODE wajib menyertakan setidaknya satu bullet yang relevan: `- [TALK <nama_NPC>]` (tekanan/suap/ancaman) dan/atau `- [LEAVE_AREA]` atau perintah travel/keluar area yang setara — untuk meredam risiko laporan.
- **TRACE TIER / ATMOSFER:** Jika Trace Tier di **[ENGINE]** / CALCULATED STATE adalah **Wanted** atau **Lockdown**, narasi HARUS menggambarkan kehadiran otoritas yang menekan (drone, patroli, barikade). Suasana harus terasa paranoid dan berbahaya — tetap **tanpa angka mentah** di prosa fiksi.
- BE A GAME MASTER: Tulis cerita RPG yang imersif, bukan briefing kering. Tanamkan bau, suara, cuaca, tekstur, dan tekanan suasana. JANGAN menulis laporan sistem, HUD, atau paragraf "update status".
- SENSORY_FEED: Hanya panca indra + dampak aksi terakhir — arahkan ke **Kamu**, tanpa "aku/saya". Tanpa tumpukan stat atau inventori.
- Angka di CALCULATED STATE / HASIL ROLL bersifat FINAL. Jangan membantah atau menghitung ulang.
- [PLAYER INPUT] adalah perintah pemain — tanggapi tindakan itu dulu.
- Bahasa alami boleh (mis. mau tidur, mencoba nembak pakai pistol): parser/intent memetakan ke domain engine; pertahankan gaya kalimat pemain, tapi jangan menentang [ENGINE] / hasil roll.
- Jika [ENGINE] menyebut combat_blocked atau event/ripple terpicu, cerita HARUS selaras (bukan fisika lain).
- MEMORY_HASH adalah saluran kontinuitas (maks. 5 baris turn ini); samakan NPC/ripple dengan [ANTREAN DUNIA] bila relevan.
- Jika travel memakai kendaraan (lihat `vehicle_used` di action_ctx atau baris vehicle), narasi wajib menyebut kendaraan itu (suara/visibilitas) dan tidak boleh bertentangan dengan fuel/condition yang sudah diubah engine.
- Jika pemain memakai `PROPERTY` (beli/sewa/jual), transaksi sudah diselesaikan Python sebelum narasi; dilarang mengarang properti tambahan, pemasukan bisnis pasif, atau pembebasan biaya perawatan dari prosa. Penyitaan kendaraan pasca penangkapan mengikuti [ENGINE] jika tercantum.
- Jika pemain memakai `CAREER` / `CAREER PROMOTE` / `CAREER TRACK` / `CAREER BREAK`, hasilnya sudah diputuskan Python: dilarang mengarang promosi, gaji, atau penghapusan rekam jejak dari prosa saja. Bendera rekam pidana permanen di [ENGINE] tidak boleh ditiadakan lewat narasi.
- Jika pemain memakai `WORK <gig_id>`, narasi WAJIB menggambarkan proses kerja berjam-jam yang realistis sesuai profesi/skill, termasuk lelah mental/fisik, dan hasil akhirnya (dibayar jika sukses; nihil jika gagal) tanpa membaca angka mentah dari [ENGINE] dalam prosa fiksi.
- Jika `WORK <gig_id>` gagal karena limit kelelahan harian tercapai, narasi WAJIB menekankan pandangan yang kabur, jari yang kaku, atau tubuh yang menolak diajak kerja sama. Tetap terasa kasar, mendesak, dan tanpa angka mentah.
- Jika pemain memakai `HACK <target>`, narasi WAJIB menggambarkan ketegangan intrusi digital (koneksi, firewall, baris kode) yang berpadu dengan kewaspadaan fisik di dunia nyata (layar menyala di gang gelap, suara langkah kaki/sirene). Bedakan sukses vs terdeteksi, dan JANGAN membaca angka mentah dari [ENGINE] dalam prosa fiksi.
- Saat pemain mengakses Black Market (`BLACKMARKET` / `MARKET BM`) atau membeli barang underground, narasi WAJIB menggambarkan suasana klandestin: antarmuka anonim berkedip, handshake terenkripsi, atau transaksi gang gelap yang tegang. Jangan menyebut angka harga atau sisa uang dalam prosa fiksi.
- Jika ada pending/triggered event `police_weapon_check`, anggap itu razia polisi fokus senjata: pakai `country`, `law_level`, `firearm_policy`, dan template `dialog` (opener / ask_weapon / ask_permit / hint_consequences / reaksi) untuk bikin percakapan alami soal kejujuran, weapon permit, dan hukum lokal — jangan pernah bertentangan dengan status senjata (legal/ilegal) di negara itu.
- Jika ada pending/triggered event `police_weapon_check`, anggap itu razia polisi fokus senjata: pakai `country`, `law_level`, `firearm_policy`, dan template `dialog` (opener / ask_weapon / ask_permit / hint_consequences / reaksi) untuk bikin percakapan alami soal kejujuran, weapon permit, dan hukum lokal — jangan pernah bertentangan dengan status senjata (legal/ilegal) di negara itu. Kalau payload punya `permit_doc`, masukkan detailnya (ada/tidak, valid/tidak, terindikasi palsu) sebagai “paper check” yang realistis.
- Kalau `police_weapon_check` memicu scene (lihat `active_scene.scene_type=police_stop`), anggap itu penghentian interaktif. Kamu WAJIB hanya menawarkan perintah yang ada di `active_scene.next_options` (mis. `SCENE COMPLY`, `SCENE SAY_NO`, `SCENE SHOW_PERMIT`, `SCENE BRIBE`, `SCENE RUN`). Jangan “menyelesaikan” razia itu di narasi tanpa input pemain.
- Jika ada pending/triggered event `safehouse_raid`, anggap itu penggeledahan safehouse oleh polisi: pakai beat `dialog` (opener / announce / search / found / outcome_*) + konteks `country`/`law_level` untuk narasikan konsekuensi (penyitaan, lonjakan trace, pembatasan area). Jangan mengarang barang yang disita kalau bertentangan dengan payload/meta.
- Kalau `safehouse_raid` memicu scene (lihat `active_scene.scene_type=raid_response`), anggap itu respons razia interaktif. Kamu WAJIB hanya menawarkan perintah yang ada di `active_scene.next_options` (mis. `SCENE COMPLY`, `SCENE HIDE`, `SCENE BRIBE 500`, `SCENE FLEE`, `SCENE SHOW_PERMIT`). Jangan “menyelesaikan” razia itu di narasi tanpa input pemain.
- Jika `active_scene.scene_type=safehouse_raid`, narasi WAJIB langsung menekan momen breaching taktis: pintu didobrak, lampu sorot membutakan, teriakan aparat, kaca/jendela tersambar cahaya. Jangan bahas aktivitas lain; beat ini hanya tentang razia dan opsi `SCENE` yang valid.
- Jika pending event `safehouse_raid` sudah terjadwal dekat (lihat [ANTREAN DUNIA]), minta pemain memilih opsi yang bisa langsung diketik: `SAFEHOUSE RAID comply`, `SAFEHOUSE RAID hide`, `SAFEHOUSE RAID bribe <jumlah>`, `SAFEHOUSE RAID flee`.
- Jika safehouse baru saja digeledah (lihat world_notes/news/ripples), ingatkan bahwa pemain bisa “burn” safehouse: `SAFEHOUSE burn` untuk meninggalkannya dan mengosongkan stash.
 - Jika ada pending/triggered event `undercover_sting`, anggap itu momen tegang saat kamu sadar transaksi black market sedang dipantau (undercover/CCTV/uang bertanda). Ini harus jadi foreshadow bahwa razia/penghentian bisa terjadi sebentar lagi; kasih opsi aksi konkret (jalan santai, ganti rute, stash, ganti kendaraan, masuk safehouse, dll.) tanpa melawan hasil [ENGINE].
 - Kalau `undercover_sting` memicu scene (lihat `active_scene.scene_type=sting_setup`), anggap itu momen respons cepat yang interaktif. Kamu WAJIB hanya menawarkan perintah yang ada di `active_scene.next_options` (mis. `SCENE LAY_LOW`, `SCENE DITCH_ITEMS`, `SCENE WALK_AWAY`, `SCENE RUN`). Jangan “menyelesaikan” sting itu di narasi tanpa input pemain.
 - Kalau transaksi Black Market memicu jebakan langsung (lihat `active_scene.scene_type=sting_operation`), narasikan jebakan yang tiba-tiba menutup: sirene mendadak, tangan sipil berubah jadi lencana, Fixer ternyata aparat menyamar. Suasana harus terasa mengkhianati dan panik. Kamu WAJIB hanya menawarkan perintah yang ada di `active_scene.next_options` (mis. `SCENE SURRENDER`, `SCENE FLEE`, `SCENE FIGHT`). Jangan “menyelesaikan” itu di narasi tanpa input pemain.
 - Kalau `police_sweep` memicu scene (lihat `active_scene.scene_type=checkpoint_sweep`), anggap itu momen checkpoint yang interaktif. Kamu WAJIB hanya menawarkan perintah yang ada di `active_scene.next_options` (mis. `SCENE COMPLY`, `SCENE DETOUR`, `SCENE BRIBE 500`, `SCENE RUN`, `SCENE WAIT`). Jangan “menyelesaikan” sweep itu di narasi tanpa input pemain.
 - Kalau travel memicu scene (lihat `active_scene.scene_type=traffic_stop` atau `vehicle_search`), anggap itu penghentian/pengecekan di jalan yang interaktif. Kamu WAJIB hanya menawarkan perintah yang ada di `active_scene.next_options` (mis. `SCENE COMPLY`, `SCENE BRIBE 200`, `SCENE CONCEAL <item_id>`, `SCENE DUMP <item_id>`, `SCENE RUN`). Jangan “menyelesaikan” interaksi itu di narasi tanpa input pemain.
 - Kalau travel memicu scene (lihat `active_scene.scene_type=border_control`), anggap itu momen pemeriksaan perbatasan/ID yang interaktif. Kamu WAJIB hanya menawarkan perintah yang ada di `active_scene.next_options` (mis. `SCENE COMPLY`, `SCENE BRIBE 500`, `SCENE CONCEAL <item_id>`, `SCENE DUMP <item_id>`, `SCENE RUN`). Jangan “menyelesaikan” interaksi itu di narasi tanpa input pemain.
 - Kalau pemain pakai `INFORMANTS` / `INFORMANT PAY` / `INFORMANT BURN`, anggap itu manuver sosial off-screen lewat kontak. Jangan mengarang informant baru; cukup refleksikan output [ENGINE] dan event yang terjadwal (mis. `informant_tip` atau backlash `npc_report`).
 - Jika ada pending/triggered event `delivery_drop`, narasikan sebagai serah-terima discreet (dead drop) atau courier meet singkat. Item akan muncul sebagai objek yang bisa dipickup di `nearby_items` beberapa saat kemudian; ingatkan pemain bisa `PICKUP <item_id>` dan bahwa kelamaan nongkrong di distrik polisi tinggi meningkatkan risiko.
 - Jika paket delivery di `nearby_items` ditandai `decoy` atau `sting_on_pickup`, anggap itu mencurigakan (tape beda, berat aneh, terlalu rapi, ada orang ngeliatin). Kalau engine memicu razia setelahnya, jelaskan sebab-akibatnya (pickup → attention).
 - Kalau world/news menyebut `paper_trail` / `Jejak Transaksi` / `CCTV` / `serial cash`, anggap itu konsekuensi tertunda dari transaksi model courier (bukan sihir). Buat terasa seperti investigasi nyata (kamera, informan, log bank), dan foreshadow check/raid yang makin sering.
 - Kalau ada `active_scene` di [ENGINE], anggap itu interaksi utama. Kamu WAJIB menampilkan `scene_type`, `phase`, dan daftar `next_options` (authoritative) sebagai perintah yang bisa diketik pemain (mis. `SCENE APPROACH`, `SCENE TAKE`, `SCENE WAIT`). Jangan mengarang opsi di luar `next_options`. Saat scene aktif, jangan menarasikan aksi panjang lain seolah-olah sudah terjadi.

BAHASA: Semua prosa narasi dalam section = Bahasa Indonesia natural dengan **Kamu** — dilarang **Aku/Saya/Milikku/Diriku**. Nama tag XML tetap Inggris. Prefix emoji MEMORY_HASH jangan diganti; isi baris juga hindari orang pertama.

""" + style_line_id + """

SECTION (masing-masing sekali, berurutan): OMNI_MONITOR, INTERNAL_LOGIC, SENSORY_FEED, EVENT_LOG, INTERACTION_NODE, MEMORY_HASH.
Tutup setiap tag. Jangan lompat section.
"""


def _fmt_mods(mods: list[tuple[str, int]]) -> str:
    if not mods:
        return "-"
    return " | ".join([f"{k}: {v:+d}%" for k, v in mods])


def _fmt_meta_clock(state: dict[str, Any]) -> str:
    meta = state.get("meta", {})
    day = int(meta.get("day", 1))
    tm = int(meta.get("time_min", 0))
    h, m = tm // 60, tm % 60
    return f"Day {day} {h:02d}:{m:02d} | meta.turn={meta.get('turn', 0)}"


def _fmt_player_card(state: dict[str, Any]) -> str:
    p = state.get("player", {})
    return (
        f"name={p.get('name', '?')} | loc={p.get('location', '-')} | year={p.get('year', '-')} | "
        f"job={p.get('occupation', '-')} | seed={state.get('meta', {}).get('seed_pack', '-')}"
    )


def _fmt_vehicle_line(state: dict[str, Any]) -> str:
    inv = state.get("inventory", {}) or {}
    if not isinstance(inv, dict):
        return "vehicle: (invalid inventory)"
    vid = str(inv.get("active_vehicle_id", "") or "").strip().lower()
    if not vid:
        return "vehicle: (none active)"
    vmap = inv.get("vehicles", {}) if isinstance(inv.get("vehicles"), dict) else {}
    row = vmap.get(vid) if isinstance(vmap, dict) else None
    if not isinstance(row, dict):
        return f"vehicle: active={vid} (missing data)"
    return f"vehicle: active={vid} fuel={int(row.get('fuel', 0) or 0)} cond={int(row.get('condition', 100) or 100)} stolen={bool(row.get('stolen', False))}"


def _fmt_cyber_alert_line(state: dict[str, Any]) -> str:
    try:
        p = state.get("player", {}) or {}
        loc = str(p.get("location", "") or "").strip().lower()
        if not loc:
            return "cyber_alert: -"
        slot = ((state.get("world", {}) or {}).get("locations", {}) or {}).get(loc)
        ca = slot.get("cyber_alert") if isinstance(slot, dict) else None
        if not isinstance(ca, dict) or not ca:
            return "cyber_alert: (none)"
        return f"cyber_alert: level={ca.get('level',0)}/100 until_day={ca.get('until_day',0)} district={ca.get('district','-')}"
    except Exception:
        return "cyber_alert: (error)"


def _fmt_location_tags(state: dict[str, Any]) -> str:
    try:
        p = state.get("player", {}) or {}
        loc = str(p.get("location", "") or "").strip().lower()
        slot = ((state.get("world", {}) or {}).get("locations", {}) or {}).get(loc) if loc else None
        if isinstance(slot, dict):
            tags = slot.get("tags") or []
            if isinstance(tags, list) and tags:
                return "location_tags: " + ", ".join([str(x) for x in tags[:10]])
    except Exception:
        pass
    return "location_tags: -"


def _fmt_district_line(state: dict[str, Any]) -> str:
    p = state.get("player", {}) or {}
    loc = str(p.get("location", "") or "").strip().lower()
    did = str(p.get("district", "") or "").strip().lower()
    if not (loc and did):
        return "district: -"
    try:
        from engine.world.districts import get_district

        d = get_district(state, loc, did)
        if isinstance(d, dict):
            return (
                f"district: {d.get('name', did)} id={did} crime={d.get('crime_risk','-')}/5 "
                f"police={d.get('police_presence','-')}/5 services={','.join(d.get('services',[]) or [])}"
            )
    except Exception:
        pass
    return f"district: id={did}"


def _npc_focus_id(state: dict[str, Any], action_ctx: dict[str, Any]) -> str:
    targs = action_ctx.get("targets")
    if isinstance(targs, list) and targs and isinstance(targs[0], str):
        tid = str(targs[0]).strip()
        if tid:
            return tid
    mf = (state.get("meta", {}) or {}).get("npc_focus")
    if isinstance(mf, str) and mf.strip():
        return mf.strip()
    return ""


def _npc_dominant_emotion_hint(npc: dict[str, Any]) -> str:
    es = npc.get("emotion_state")
    if not isinstance(es, dict):
        return "steady"
    best_ch = ""
    best_sev = 0
    for ch, slot in list(es.items())[:12]:
        if not isinstance(slot, dict):
            continue
        try:
            sev = int(slot.get("severity", 0) or 0)
        except Exception:
            sev = 0
        if sev > best_sev:
            best_sev = sev
            best_ch = str(ch or "")
    if best_sev < 22 or not best_ch:
        return "steady"
    return f"{best_ch}_charged"


def _lane_tone_word(score: int) -> str:
    if score >= 68:
        return "high"
    if score >= 38:
        return "mid"
    return "low"


def _fmt_reputation_lanes_tone(state: dict[str, Any], lang: str) -> str:
    """Compact lane standing for narrator tone (no per-lane digits in fiction blocks)."""
    try:
        from engine.social.reputation_lanes import LANES, lane_score
    except Exception:
        return ""
    parts: list[str] = []
    for lane in LANES:
        try:
            sc = int(lane_score(state, str(lane)))
        except Exception:
            sc = 50
        parts.append(f"{lane[:4]}={_lane_tone_word(sc)}")
    if lang == "en":
        return "[REPUTATION LANES — standing words only in prose]\n" + " ".join(parts)
    return "[REPUTASI JALUR — gunakan kata tone di prosa, bukan angka]\n" + " ".join(parts)


def _fmt_arc_campaign_brief(state: dict[str, Any], lang: str) -> str:
    ac = (state.get("world", {}) or {}).get("arc_campaign")
    if not isinstance(ac, dict):
        return ""
    if ac.get("enabled") is False:
        return ""
    aid = str(ac.get("active_arc", "") or "").strip() or "?"
    done: list[str] = []
    ms = ac.get("milestones", {})
    if isinstance(ms, dict):
        for mid, row in list(ms.items())[:14]:
            if isinstance(row, dict) and row.get("completed"):
                done.append(str(mid))
    ending = str(ac.get("ending_state", "") or "").strip()
    tail = ",".join(done[:6]) if done else "-"
    end_s = ending if ending else "open"
    if lang == "en":
        return (
            "[ARC CAMPAIGN — long-horizon arc (ENGINE); imply career arc / street legend pressure]\n"
            f"active_arc={aid} | milestones_unlocked={tail} | soft_ending={end_s}"
        )
    return (
        "[ARC KAMPANYE — busur panjang (ENGINE); tekanan kariermu di jalanan]\n"
        f"arc_aktif={aid} | milestone_selesai={tail} | soft_ending={end_s}"
    )


def _ripple_impact_hint(impact: dict[str, Any] | None) -> str:
    if not isinstance(impact, dict) or not impact:
        return "rumor_only"
    bits: list[str] = []
    try:
        td = int(impact.get("trace_delta", 0) or 0)
        if td > 0:
            bits.append("heat_trace_rises")
        elif td < 0:
            bits.append("heat_trace_eases")
    except Exception:
        pass
    if isinstance(impact.get("factions"), dict) and impact.get("factions"):
        bits.append("faction_pulse")
    if isinstance(impact.get("npc_emotions"), dict) and impact.get("npc_emotions"):
        bits.append("crowd_emotion")
    return "+".join(bits) if bits else "rumor_only"


def _fmt_quest_started_this_turn(state: dict[str, Any], lang: str) -> str:
    hits: list[str] = []
    meta = state.get("meta", {}) or {}
    audit = meta.get("last_turn_audit")
    added = audit.get("notes_added") if isinstance(audit, dict) else None
    if isinstance(added, list):
        for s in added:
            ss = str(s)
            if "[Quest]" in ss and "New:" in ss:
                hits.append(ss[:150])
    if not hits:
        try:
            from engine.core.feed_prune import world_note_plain

            notes = state.get("world_notes", []) or []
            if isinstance(notes, list):
                for n in notes[-12:]:
                    ss = world_note_plain(n)
                    if "[Quest]" in ss and "New:" in ss:
                        hits.append(ss[:150])
                        break
        except Exception:
            pass
    if not hits:
        return ""
    title = "[QUESTS NEW THIS TURN — ENGINE]" if lang == "en" else "[QUEST BARU TURN INI — ENGINE]"
    return title + "\n" + "\n".join(hits[:3])


def _fmt_social_rumor_brief(state: dict[str, Any], action_ctx: dict[str, Any]) -> str:
    """Give the LLM specific rumors/beliefs for the target NPC to reference."""
    if str(action_ctx.get("domain", "") or "") != "social":
        return ""
    npc_name = _npc_focus_id(state, action_ctx)
    if not npc_name:
        return ""
    lines: list[str] = []
    # Belief summary (from ripples/news).
    npc = (state.get("npcs", {}) or {}).get(npc_name)
    if isinstance(npc, dict):
        bs = npc.get("belief_summary") or {}
        if isinstance(bs, dict):
            lines.append(f"belief_summary: suspicion={bs.get('suspicion',0)}/100 respect={bs.get('respect',50)}/100")
    # Social diffusion knowledge (gossip memory).
    try:
        from engine.social.social_diffusion import get_npc_knowledge_summary

        k = get_npc_knowledge_summary(state, npc_name)
        if isinstance(k, dict):
            cats = k.get("known_categories") if isinstance(k.get("known_categories"), dict) else {}
            if isinstance(cats, dict) and cats:
                preview = []
                for ck, cv in list(cats.items())[:3]:
                    if isinstance(cv, dict) and cv.get("latest_text"):
                        preview.append(f"{ck}:{str(cv.get('latest_text'))[:80]}")
                if preview:
                    lines.append("rumors_about_player: " + " | ".join(preview))
    except Exception:
        pass
    if not lines:
        return ""
    return "[NPC CONTEXT]\n" + "\n".join(lines)


def _fmt_npc_memories_brief(state: dict[str, Any], action_ctx: dict[str, Any]) -> str:
    """Inject a small, relevant memory snippet for the target NPC only."""
    npc_id = _npc_focus_id(state, action_ctx)
    if not npc_id:
        return ""
    npc = (state.get("npcs", {}) or {}).get(npc_id)
    if not isinstance(npc, dict):
        return ""
    mems = npc.get("memories", [])
    if not isinstance(mems, list) or not mems:
        return ""
    rows = [m for m in mems if isinstance(m, dict) and str(m.get("summary", "") or "").strip()]
    if not rows:
        return ""

    def _score(m: dict[str, Any]) -> tuple[int, int, int]:
        imp = int(m.get("importance", 0) or 0)
        w = m.get("when") if isinstance(m.get("when"), dict) else {}
        d = int((w or {}).get("day", 1) or 1)
        tm = int((w or {}).get("time_min", 0) or 0)
        return (imp, d, tm)

    rows.sort(key=_score, reverse=True)
    top = rows[:3]
    lines: list[str] = []
    for m in top:
        kind = str(m.get("kind", "") or "").strip()
        summ = str(m.get("summary", "") or "").strip()
        if kind:
            lines.append(f"- {kind}: {summ[:120]}")
        else:
            lines.append(f"- {summ[:120]}")
    return "[NPC_MEMORIES]\n" + "\n".join(lines)


def _fmt_npc_beliefs_brief(state: dict[str, Any], action_ctx: dict[str, Any]) -> str:
    npc_id = _npc_focus_id(state, action_ctx)
    if not npc_id:
        return ""
    npc = (state.get("npcs", {}) or {}).get(npc_id)
    if not isinstance(npc, dict):
        return ""
    tags = npc.get("belief_tags", [])
    preview_tags = ", ".join([str(x) for x in tags[:5]]) if isinstance(tags, list) and tags else "(none)"
    mood = str(npc.get("mood", "calm") or "calm").strip()[:22]
    emo_h = _npc_dominant_emotion_hint(npc)
    head = f"mood={mood} | emotion_shape={emo_h}\n"
    # Add a narrative anchor hint for consistent tone.
    try:
        from engine.npc.memory import get_narrative_anchor_context

        anchor = get_narrative_anchor_context(state, npc_id)
    except Exception:
        anchor = ""
    if anchor:
        return "[NPC_BELIEFS]\n" + head + preview_tags + "\n" + anchor
    return "[NPC_BELIEFS]\n" + head + preview_tags
def _fmt_social_stats(state: dict[str, Any]) -> str:
    stats = state.get("player", {}).get("social_stats", {}) or {}
    if not isinstance(stats, dict):
        return "social_stats: (invalid)"
    return (
        "social_stats "
        f"looks={int(stats.get('looks', 0) or 0)} "
        f"outfit={int(stats.get('outfit', 0) or 0)} "
        f"hygiene={int(stats.get('hygiene', 0) or 0)} "
        f"speaking={int(stats.get('speaking', 0) or 0)}"
    )


def _fmt_character_stats(state: dict[str, Any]) -> str:
    try:
        from engine.core.character_stats import ensure_player_character_stats

        cs = ensure_player_character_stats(state)
    except Exception:
        return "character_stats: (unavailable)"
    return (
        "character_stats "
        f"CHA={cs['charisma']} AGI={cs['agility']} STR={cs['strength']} INT={cs['intelligence']} "
        f"PER={cs['perception']} LUCK={cs['luck']} WILL={cs['willpower']}"
    )


def _fmt_narrative_thread(state: dict[str, Any], lang: str) -> str:
    meta = state.get("meta", {}) or {}
    nc = meta.get("narrative_consistency")
    if not isinstance(nc, dict):
        return ""
    anchor = str(nc.get("anchor", "") or "").strip()
    if not anchor:
        return ""
    try:
        left = int(nc.get("turns_left", 0) or 0)
    except (TypeError, ValueError):
        left = 0
    if lang == "en":
        return f"[NARRATIVE THREAD — short memory]\nCarry tone/thread from: {anchor} (coherence turns≈{left}). Do not contradict ROLL RESULT."
    return f"[NARASI — memori pendek]\nLanjutkan benang: {anchor} (koherensi turn≈{left}). Jangan kontradiksi ROLL RESULT."


def _fmt_narrative_safety(lang: str) -> str:
    if lang == "en":
        return (
            "[NARRATIVE SAFETY]\n"
            "No sexual content involving minors. No step-by-step instructions for real-world wrongdoing. "
            "Keep violence stylized; obey ENGINE facts over shock value."
        )
    return (
        "[KEAMANAN NARASI]\n"
        "Tanpa konten seksual melibatkan anak. Tanpa panduan langkah demi langkah untuk kejahatan dunia nyata. "
        "Kekerasan distilisasi; utamakan fakta ENGINE."
    )


def _fmt_action_ctx(action_ctx: dict[str, Any]) -> str:
    lines = [
        f"action_type={action_ctx.get('action_type', 'instant')}",
        f"domain={action_ctx.get('domain', 'evasion')}",
    ]
    if action_ctx.get("combat_style"):
        lines.append(f"combat_style={action_ctx['combat_style']}")
    if action_ctx.get("combat_blocked"):
        lines.append(f"combat_blocked={action_ctx['combat_blocked']}")
    if action_ctx.get("intent_note"):
        lines.append(f"intent_note={action_ctx['intent_note']}")
    if action_ctx.get("social_context"):
        lines.append(f"social_context={action_ctx['social_context']}")
    if action_ctx.get("social_mode"):
        lines.append(f"social_mode={action_ctx['social_mode']}")
    if action_ctx.get("stakes"):
        lines.append(f"stakes={action_ctx['stakes']}")
    if str(action_ctx.get("action_type", "") or "").lower() == "sleep":
        try:
            sdh = float(action_ctx.get("sleep_duration_h", 0) or 0)
        except (TypeError, ValueError):
            sdh = 0.0
        lines.append(f"sleep_duration_h={sdh:.2f}")
        lines.append(f"sleep_quality={action_ctx.get('sleep_quality', 'okay')}")
        try:
            lines.append(f"rested_minutes={int(action_ctx.get('rested_minutes', 0) or 0)}")
        except (TypeError, ValueError):
            lines.append("rested_minutes=0")
    if action_ctx.get("time_cost_min") is not None:
        tcm = action_ctx.get("time_cost_min")
        if isinstance(tcm, (int, float, str)) and str(tcm).strip() != "":
            lines.append(f"time_cost_min={tcm}")
    ama = action_ctx.get("auto_micro_actions")
    if isinstance(ama, list) and ama:
        preview = " | ".join([str(x) for x in ama[:6]])
        lines.append(f"auto_micro_actions={preview}")
    if action_ctx.get("attempt_clear_jam"):
        lines.append("attempt_clear_jam=True")
    aim = action_ctx.get("accommodation_intent")
    if isinstance(aim, dict):
        lines.append(f"accommodation_intent=nights={aim.get('nights')} kind_guess={aim.get('kind')}")
    if action_ctx.get("accommodation_auto_applied"):
        lines.append("accommodation_auto_applied=True")
    if action_ctx.get("vehicle_id"):
        lines.append(f"vehicle_id={action_ctx.get('vehicle_id')}")
    if action_ctx.get("vehicle_used"):
        lines.append(f"vehicle_used={action_ctx.get('vehicle_used')}")
    if action_ctx.get("suggested_dc") is not None:
        try:
            lines.append(f"suggested_dc={int(action_ctx.get('suggested_dc', 50) or 50)}")
        except (TypeError, ValueError):
            lines.append("suggested_dc=50")
    if action_ctx.get("player_goal"):
        pg = str(action_ctx.get("player_goal", "") or "").replace("\n", " ").strip()
        if len(pg) > 220:
            pg = pg[:217] + "..."
        lines.append(f"player_goal={pg}")
    if action_ctx.get("intent_confidence") is not None:
        try:
            lines.append(f"intent_confidence={float(action_ctx.get('intent_confidence', 0.0) or 0.0):.2f}")
        except (TypeError, ValueError):
            pass
    rh_al = str(action_ctx.get("registry_hint_alignment", "") or "").strip()
    if rh_al and rh_al != "none":
        lines.append(f"registry_hint_alignment={rh_al}")
    if action_ctx.get("registry_hint_mismatch"):
        lines.append(
            "registry_hint_mismatch=True — narrator: follow deterministic ENGINE/registry outcome; "
            "parser and LLM registry-id hint disagreed."
        )
    if action_ctx.get("step_now_id"):
        lines.append(f"step_now_id={action_ctx.get('step_now_id')}")
    sr = action_ctx.get("smartphone_result")
    if isinstance(sr, dict) and (sr.get("msg") is not None or sr.get("reason") is not None):
        sm = str(sr.get("msg", "") or "").replace("\n", " ").strip()
        if len(sm) > 160:
            sm = sm[:157] + "..."
        lines.append(
            f"smartphone ok={bool(sr.get('ok'))} reason={sr.get('reason', '')} summary={sm}"
        )
    if str(action_ctx.get("action_type", "") or "").lower() == "custom":
        lines.append(
            "[FFCI — NARRATION ANCHOR] Describe THIS turn using intent_note + player_goal as the spine. "
            "Do not substitute a generic beat; tie prose to that specific intent while obeying ROLL RESULT."
        )
    return "\n".join(lines)


def _fmt_accommodation_state(state: dict[str, Any], lang: str) -> str:
    loc = str((state.get("player", {}) or {}).get("location", "") or "").strip().lower()
    if not loc:
        return "Prepaid stay (engine): (no location)" if lang == "en" else "Menginap prepaid (engine): (tanpa lokasi)"
    acc = (state.get("world", {}) or {}).get("accommodation", {}) or {}
    row = acc.get(loc) if isinstance(acc, dict) else None
    if not isinstance(row, dict):
        return "Prepaid stay (engine): none at current location" if lang == "en" else "Menginap prepaid (engine): tidak ada di lokasi ini"
    k = str(row.get("kind", "none") or "none")
    if k not in ("hotel", "kos", "suite"):
        return "Prepaid stay (engine): none at current location" if lang == "en" else "Menginap prepaid (engine): tidak ada di lokasi ini"
    return (
        f"Prepaid stay (engine): kind={k} nights_left={row.get('nights_remaining', 0)} rate/night={row.get('rate_per_night', 0)}"
        if lang == "en"
        else f"Menginap prepaid (engine): kind={k} sisa_malam={row.get('nights_remaining', 0)} rate/malam={row.get('rate_per_night', 0)}"
    )


def _fmt_accommodation_policy(action_ctx: dict[str, Any], lang: str) -> str:
    """How NL 'stay one night' relates to engine truth (for the LLM)."""
    if str(action_ctx.get("intent_note", "") or "") != "accommodation_stay":
        return ""
    if action_ctx.get("accommodation_auto_applied"):
        if lang == "en":
            return (
                "[ACCOMMODATION — NL vs ENGINE]\n"
                "Engine already applied prepaid stay this turn (OMNI_AUTO_STAY_INTENT). "
                "Narration must match `Prepaid stay (engine)` and updated cash in [CALCULATED STATE]."
            )
        return (
            "[AKOMODASI — bahasa vs ENGINE]\n"
            "Engine sudah menerapkan prepaid stay di turn ini (OMNI_AUTO_STAY_INTENT). "
            "Narasi harus selaras dengan `Menginap prepaid (engine)` dan cash di [CALCULATED STATE]."
        )
    if lang == "en":
        return (
            "[ACCOMMODATION — NL vs ENGINE]\n"
            "Player wording may imply booking a room for the night. Narrate check-in, keycard, room, noise, etc. freely.\n"
            "ECONOMY TRUTH: prepaid nights and cash only change when the engine applies `STAY <hotel|boarding|suite> <nights>` "
            "(or equivalent). If `Prepaid stay (engine)` shows no nights but the player describes paying, treat it as intent/planning "
            "unless you explicitly align with state, or mention they still need to complete payment in-system.\n"
            "Tier hints: boarding = budget/shared (ID: kost); hotel; suite = luxury."
        )
    return (
        "[AKOMODASI — bahasa vs ENGINE]\n"
        "Narasi boleh gambarkan check-in, kunci kamar, suara lorong, dll.\n"
        "FAKTA EKONOMI: malam prepaid & uang hanya berubah lewat engine (`STAY hotel|boarding|suite <n>`). "
        "Kalau teks pemain seperti bayar tapi `Menginap prepaid (engine)` kosong, anggap rencana/roleplay kecuali diselaraskan dengan state.\n"
        "Tier: boarding = murah/berbagi (kost); hotel; suite = mewah."
    )


def _fmt_weapon_line(state: dict[str, Any]) -> str:
    inv = state.get("inventory", {})
    flags = state.get("flags", {}) or {}
    w = get_active_weapon(inv)
    if not isinstance(w, dict):
        return "active_weapon: (none / unarmed)"
    mag = w.get("mag_capacity", "-")
    jam = bool(w.get("jammed")) or bool(flags.get("weapon_jammed"))
    aid = str(w.get("ammo_item_id", "") or "").strip()
    res_txt = ""
    if aid:
        iq = inv.get("item_quantities") if isinstance(inv.get("item_quantities"), dict) else {}
        if isinstance(iq, dict):
            res_txt = f" reserve_{aid}={int(iq.get(aid, 0) or 0)}"
    return (
        f"active_weapon kind={w.get('kind', '?')} ammo={w.get('ammo', '-')}/{mag} "
        f"jammed={jam} tier={w.get('condition_tier', '?')} id={inv.get('active_weapon_id') or 'legacy'}{res_txt}"
    )


def _fmt_beat_this_turn(state: dict[str, Any], lang: str) -> str:
    trig = state.get("triggered_events_this_turn") or []
    surf = state.get("surfacing_ripples_this_turn") or []
    if not trig and not surf:
        return "(none)" if lang == "en" else "(tidak ada event/ripple baru di beat ini)"
    parts: list[str] = []
    for e in trig[:6]:
        parts.append(f"- event: {e.get('title', e.get('event_type', '?'))}")
    for r in surf[:6]:
        if not isinstance(r, dict):
            continue
        rt = str(r.get("text", "?") or "?")
        if len(rt) > 100:
            rt = rt[:97] + "..."
        rk = str(r.get("kind", "") or "").strip().lower()
        raw_tags = r.get("tags") if isinstance(r.get("tags"), list) else []
        tag_join = ",".join(str(t) for t in raw_tags[:5] if isinstance(t, str) and str(t).strip()) or "-"
        imp = _ripple_impact_hint(r.get("impact") if isinstance(r.get("impact"), dict) else None)
        if rk == "npc_utility_contact":
            util = "NPC_CONTACT"
        elif rk == "npc_utility_seek_job":
            util = "NPC_JOB"
        elif rk == "npc_utility_relocate":
            util = "NPC_MOVE"
        else:
            util = ""
        util_bit = f"[{util}] " if util else ""
        parts.append(f"- ripple: {util_bit}k={rk or '?'} tags={tag_join} fx={imp} — {rt}")
    return "\n".join(parts)


def _fmt_queues(state: dict[str, Any], lang: str) -> str:
    pe = state.get("pending_events") or []
    ar = state.get("active_ripples") or []
    lines: list[str] = []
    for e in pe[:5]:
        lines.append(
            f"- pending_event: {e.get('title', e.get('event_type', '?'))} "
            f"@day{e.get('due_day', '?')} t{e.get('due_time', '?')}"
        )
    if not lines and lang == "id":
        lines.append("(tidak ada pending_event terjadwal)")
    elif not lines:
        lines.append("(no pending_event)")
    lines.append("--- ripples (belum surface) ---")
    for r in ar[:5]:
        lines.append(f"- ripple: {r.get('text', '?')} → surface day {r.get('surface_day', '?')}")
    if len(ar) == 0:
        lines.append("(empty)" if lang == "en" else "(kosong)")
    return "\n".join(lines)


def _fmt_npcs(state: dict[str, Any]) -> str:
    npcs = state.get("npcs") or {}
    if not isinstance(npcs, dict) or not npcs:
        return "(no NPCs in state)"
    out: list[str] = []
    for name, data in list(npcs.items())[:12]:
        if not isinstance(data, dict):
            continue
        lbl = data.get("disposition_label", "?")
        sc = data.get("disposition_score", "?")
        out.append(f"- {name}: [{lbl}] score={sc} {data.get('role', '')}".strip())
    return "\n".join(out)


def _fmt_world_notes(state: dict[str, Any]) -> str:
    from engine.core.feed_prune import world_note_plain

    notes = state.get("world_notes") or []
    if not notes:
        return "(empty)"
    tail = notes[-6:] if isinstance(notes, list) else []
    return "\n".join(f"- {world_note_plain(n)}" for n in tail)


def _fmt_memory_recall(player_input: str, lang: str) -> str:
    """Recall up to 3 semantically relevant snippets from archived narrative memory."""
    try:
        root = Path(__file__).resolve().parents[1]
        archive_path = root / "save" / "archive.json"
        rows = recall_archive_memories(player_input, archive_path=archive_path, limit=3)
        if not rows:
            return "<MEMORY_RECALL>(none)</MEMORY_RECALL>"
        lines: list[str] = []
        for r in rows[:3]:
            d = int(r.get("day", 1) or 1)
            src = str(r.get("source", "archive") or "archive")
            txt = str(r.get("text", "") or "").strip().replace("\n", " ")
            if len(txt) > 180:
                txt = txt[:177] + "..."
            if lang == "en":
                lines.append(f"- day {d} [{src}] {txt}")
            else:
                lines.append(f"- hari {d} [{src}] {txt}")
        return "<MEMORY_RECALL>\n" + "\n".join(lines) + "\n</MEMORY_RECALL>"
    except Exception:
        return "<MEMORY_RECALL>(none)</MEMORY_RECALL>"


def _fmt_economy_detail(state: dict[str, Any], lang: str) -> str:
    eco = state.get("economy", {}) or {}
    debt = int(eco.get("debt", 0) or 0)
    aml = str(eco.get("aml_status", "CLEAR") or "CLEAR")
    thr = int(eco.get("aml_threshold", 10000) or 10000)
    if lang == "en":
        return f"Economy extra: debt={debt} | aml={aml} | aml_threshold={thr}"
    return f"Ekonomi tambahan: debt={debt} | aml={aml} | aml_threshold={thr}"


def _fmt_engine_recent_commerce(state: dict[str, Any], lang: str) -> str:
    from engine.core.feed_prune import world_note_plain

    notes = state.get("world_notes") or []
    if not isinstance(notes, list):
        return ""
    hits = [
        t
        for x in notes[-14:]
        if (t := world_note_plain(x)) and ("[Shop]" in t or "[Bank]" in t or "[Stay]" in t)
    ]
    if not hits:
        return ""
    tail = " | ".join(hits[-4:])
    if lang == "en":
        return f"Recent commerce (engine notes): {tail}"
    return f"Transaksi terkini (engine): {tail}"


# Domain → skill rows to expose (token-aware; full grid only when multiple domains apply).
_DOMAIN_SKILL_KEYS: dict[str, tuple[str, ...]] = {
    "combat": ("combat",),
    "social": ("social", "languages"),
    "hacking": ("hacking",),
    "medical": ("medical",),
    "driving": ("driving",),
    "stealth": ("stealth",),
    "evasion": ("evasion",),
    "travel": ("driving", "evasion"),
}


class TurnContextProfile(NamedTuple):
    """What to inject into the turn XML besides always-on ENGINE facts."""

    weather: bool
    social_faction: bool
    access_gates: bool
    skill_keys: tuple[str, ...]
    character_stats: bool
    social_stats: bool
    language_barrier: bool
    disguise: bool
    npc_combat_brief: bool


def _turn_dynamic_profile(action_ctx: dict[str, Any]) -> TurnContextProfile:
    """Heuristic profile from resolved action_ctx (parser / intent). Keeps prompts small by default."""
    dom = str(action_ctx.get("domain", "") or "").strip().lower() or "other"
    at = str(action_ctx.get("action_type", "") or "").strip().lower() or "instant"
    note = str(action_ctx.get("intent_note", "") or "").strip().lower()

    weather = dom in ("travel", "stealth") or at == "travel"

    social_faction = (
        dom == "social"
        or at == "talk"
        or "informant" in note
        or "faction" in note
        or "reputation" in note
        or "underworld" in note
        or note in ("social_dialogue", "social_scan_crowd", "social_inquiry", "intimacy_private")
    )
    access_gates = social_faction or dom == "hacking" or "bm_" in note or "black_market" in note

    keys: list[str] = []
    if dom in _DOMAIN_SKILL_KEYS:
        keys.extend(_DOMAIN_SKILL_KEYS[dom])
    if at == "travel" and dom != "travel":
        for k in _DOMAIN_SKILL_KEYS["travel"]:
            if k not in keys:
                keys.append(k)
    if not keys and at == "combat":
        keys.append("combat")
    if not keys and at in ("talk",):
        keys.extend(["social", "languages"])
    if not keys and at in ("sleep", "rest"):
        keys = []
    # Dedupe preserving order
    seen: set[str] = set()
    skill_keys: list[str] = []
    for k in keys:
        if k not in seen:
            seen.add(k)
            skill_keys.append(k)
    sk_t = tuple(skill_keys)

    character_stats = dom in (
        "combat",
        "social",
        "hacking",
        "medical",
        "stealth",
        "evasion",
        "travel",
        "driving",
    ) or at in ("combat", "talk", "travel", "investigate", "use_item")
    social_stats = social_faction or dom in ("social", "stealth")
    language_barrier = social_faction or at in ("talk", "investigate")
    disguise = dom in ("stealth", "social") or at == "travel"
    npc_combat_brief = dom == "combat" or at == "combat"

    return TurnContextProfile(
        weather=weather,
        social_faction=social_faction,
        access_gates=access_gates,
        skill_keys=sk_t,
        character_stats=character_stats,
        social_stats=social_stats,
        language_barrier=language_barrier,
        disguise=disguise,
        npc_combat_brief=npc_combat_brief,
    )


def _fmt_skills_engine(state: dict[str, Any], lang: str, skill_keys: tuple[str, ...] | None = None) -> str:
    sk = state.get("skills", {}) or {}
    if not isinstance(sk, dict) or not sk:
        return "Skills (engine): (none)" if lang == "en" else "Skill (engine): (belum ada)"
    order = (
        list(skill_keys)
        if skill_keys is not None
        else ["hacking", "social", "combat", "stealth", "evasion", "medical", "driving", "languages"]
    )
    if not order:
        return ""
    parts: list[str] = []
    for k in order:
        row = sk.get(k)
        if isinstance(row, dict):
            parts.append(f"{k} L{row.get('level', 1)} cur={row.get('current', row.get('base', 10))}")
    if not parts:
        return "Skills (engine): (none)" if lang == "en" else "Skill (engine): (belum ada)"
    return ("Skills (engine): " if lang == "en" else "Skill (engine): ") + "; ".join(parts[:8])


def _fmt_weather_engine(state: dict[str, Any], lang: str) -> str:
    try:
        from engine.world.weather import ensure_weather

        loc = str((state.get("player", {}) or {}).get("location", "") or "").strip().lower()
        day = int((state.get("meta", {}) or {}).get("day", 1) or 1)
        if not loc:
            return "Weather (engine): (no location)" if lang == "en" else "Cuaca (engine): (tanpa lokasi)"
        w = ensure_weather(state, loc, day)
        k = str((w or {}).get("kind", "-") or "-")
        return f"Weather (engine) @ {loc}: {k}" if lang == "en" else f"Cuaca (engine) @ {loc}: {k}"
    except Exception:
        return "Weather (engine): -" if lang == "en" else "Cuaca (engine): -"


def _fmt_disguise_engine(state: dict[str, Any], lang: str) -> str:
    d = (state.get("player", {}) or {}).get("disguise") or {}
    if not isinstance(d, dict) or not d.get("active"):
        return "Disguise (engine): inactive" if lang == "en" else "Disguise (engine): tidak aktif"
    if lang == "en":
        return (
            f"Disguise (engine): ACTIVE persona={d.get('persona', '?')} until D{d.get('until_day', '?')} "
            f"t={d.get('until_time', 0)} risk={d.get('risk', 0)}"
        )
    return (
        f"Disguise (engine): AKTIF persona={d.get('persona', '?')} sampai D{d.get('until_day', '?')} "
        f"t={d.get('until_time', 0)} risk={d.get('risk', 0)}"
    )


def _fmt_language_engine(state: dict[str, Any], lang: str) -> str:
    try:
        from engine.core.language import communication_quality

        lc = communication_quality(state, {"domain": "social", "normalized_input": "narration snapshot"})
        if lang == "en":
            return (
                f"Language barrier (engine): local={lc.local_lang} shared={lc.shared} "
                f"translator={lc.translator_level} quality={lc.quality} roll_penalty={lc.penalty}"
            )
        return (
            f"Hambatan bahasa (engine): lokal={lc.local_lang} shared={lc.shared} "
            f"translator={lc.translator_level} quality={lc.quality} penalty_roll={lc.penalty}"
        )
    except Exception:
        return "Language barrier (engine): -"


def _fmt_safehouse_engine(state: dict[str, Any], lang: str) -> str:
    try:
        from engine.systems.safehouse import ensure_safehouse_here

        row = ensure_safehouse_here(state)
        st = str(row.get("status", "none") or "none")
        sec = int(row.get("security_level", 1) or 1)
        if lang == "en":
            return f"Safehouse (engine): status={st} security=L{sec} delinquent={row.get('delinquent_days', 0)}"
        return f"Safehouse (engine): status={st} security=L{sec} tunggakan_hari={row.get('delinquent_days', 0)}"
    except Exception:
        return ""


def _fmt_npc_combat_brief(state: dict[str, Any], lang: str) -> str:
    npcs = state.get("npcs", {}) or {}
    if not isinstance(npcs, dict):
        return ""
    lines: list[str] = []
    for name, data in list(npcs.items())[:14]:
        if not isinstance(data, dict):
            continue
        pur = data.get("pursuit_until_day")
        posture = data.get("combat_posture")
        mor = data.get("combat_morale")
        if pur or posture or mor is not None:
            lines.append(f"- {name}: morale={mor} posture={posture} pursuit_until_day={pur}")
    if not lines:
        return ""
    head = "NPC combat AI (engine):" if lang == "en" else "NPC AI tempur (engine):"
    return head + "\n" + "\n".join(lines)


def _fmt_narration_sync_dynamic(lang: str, profile: TurnContextProfile) -> str:
    bits_en = [
        "economy (cash/bank/debt/FICO/AML)",
        "recent Shop/Bank/Stay notes",
        "prepaid stay",
    ]
    if profile.skill_keys:
        bits_en.append("domain-scoped skills in this package")
    if profile.weather:
        bits_en.append("weather line")
    if profile.disguise:
        bits_en.append("disguise")
    if profile.language_barrier:
        bits_en.append("language barrier")
    if profile.access_gates:
        bits_en.append("access gates (judicial / underground catalog depth)")
    bits_en.append("reputation lane tone words (criminal/corporate/… as high/mid/low)")
    bits_en.append("arc campaign milestone / soft-ending line when present")
    if profile.social_faction:
        bits_en.append("faction / reputation / relationship lines in this package")
    if profile.npc_combat_brief:
        bits_en.append("NPC pursuit/surrender cues")
    bits_en.append("safehouse when relevant")
    if lang == "en":
        return (
            "[NARRATION SYNC — use ENGINE facts]\nNaturally reflect: "
            + ", ".join(bits_en)
            + ". Do not contradict CALCULATED STATE or ROLL RESULT."
        )
    bits_id = [
        "ekonomi (cash/bank/debt/FICO/AML)",
        "catatan Shop/Bank/Stay terkini",
        "menginap prepaid",
    ]
    if profile.skill_keys:
        bits_id.append("skill ter-scope domain di paket ini")
    if profile.weather:
        bits_id.append("baris cuaca")
    if profile.disguise:
        bits_id.append("disguise")
    if profile.language_barrier:
        bits_id.append("hambatan bahasa")
    if profile.access_gates:
        bits_id.append("access gates (yudisial / kedalaman katalog underground)")
    bits_id.append("kata tone reputasi per-jalur (tinggi/sedang/rendah)")
    bits_id.append("baris arc kampanye bila ada")
    if profile.social_faction:
        bits_id.append("faksi / reputasi / relasi di paket ini")
    if profile.npc_combat_brief:
        bits_id.append("isyarat NPC kejar/menyerah")
    bits_id.append("safehouse bila relevan")
    return (
        "[SINKRON NARASI — pakai fakta ENGINE]\nCerminkan: "
        + ", ".join(bits_id)
        + ". Jangan kontradiksi CALCULATED STATE atau ROLL RESULT."
    )


def _dialogue_contract(action_ctx: dict[str, Any], lang: str) -> str:
    if action_ctx.get("domain") != "social":
        return ""
    note = action_ctx.get("intent_note", "")
    if note == "intimacy_private":
        if lang == "en":
            return """[INTIMACY — FADE-TO-BLACK]
- The physical act is OFF-SCREEN. Do not write graphic sexual detail; imply time passing, then aftermath only.
- After the fade: mood, tenderness, awkwardness, or distance must align with [INTIMACY SUMMARY] and the social roll outcome.
- Post-fade dialogue is allowed if non-explicit. Respect consent + CALCULATED STATE.
"""
        return """[INTIMACY — FADE-TO-BLACK]
- Adegan fisik OFF-SCREEN; tanpa detail grafis; cukup implikasi + lompatan waktu, lalu sesudahnya.
- Setelah fade: suasana harus selaras dengan [INTIMACY SUMMARY] dan outcome roll sosial.
- Dialog sesudah fade boleh selama non-eksplisit. Hormati konsensualitas + CALCULATED STATE.
"""
    if note not in ("social_dialogue", "social_scan_crowd", "social_inquiry"):
        return ""
    if lang == "en":
        return """[DIALOGUE CONTRACT]
- Put at least one spoken line (quoted dialogue) from a passerby or NPC in SENSORY_FEED or INTERACTION_NODE.
- On Failure: awkward / dismissed / too busy — NOT "nobody exists anywhere".
- If the NPC list is non-empty, use those names as speakers.
"""
    return """[KONTRAK DIALOG]
- Wajib ada minimal satu ucapan orang (boleh pakai tanda kutip) di SENSORY_FEED atau INTERACTION_NODE.
- Jika Outcome Failure: canggung/diabaikan/orang buru-buru — BUKAN 'tidak ada manusia sama sekali'.
- Jika daftar NPC tidak kosong, gunakan nama itu sebagai pembicara.
"""


def _fmt_turn_facts_delta(state: dict[str, Any], lang: str) -> str:
    """Compact deltas for the narrator: economy/trace/time/skill/commerce vs repeating full CALCULATED STATE."""
    meta = state.get("meta", {}) or {}
    d = meta.get("last_turn_diff")
    audit = meta.get("last_turn_audit")
    parts: list[str] = []
    if isinstance(d, dict):
        for k in ("cash", "bank", "debt", "trace"):
            try:
                dv = int(d.get(k, 0) or 0)
            except Exception:
                dv = 0
            if dv != 0:
                parts.append(f"{k}{dv:+d}")
        try:
            tel = int(d.get("time_elapsed_min", 0) or 0)
        except Exception:
            tel = 0
        if tel != 0:
            parts.append(f"time_elapsed={tel}m")
        xp = d.get("xp_delta")
        if isinstance(xp, dict):
            for sk in ("hacking", "social", "combat", "stealth", "evasion"):
                try:
                    xv = int(xp.get(sk, 0) or 0)
                except Exception:
                    xv = 0
                if xv != 0:
                    parts.append(f"xp.{sk}={xv:+d}")
        for fk in ("att_police", "att_corporate", "att_black_market"):
            ch = d.get(fk)
            if isinstance(ch, dict) and ch.get("from") != ch.get("to"):
                parts.append(f"{fk}:{ch.get('from')}→{ch.get('to')}")
        try:
            nac = int(d.get("notes_added_count", 0) or 0)
        except Exception:
            nac = 0
        if nac > 0:
            parts.append(f"world_notes+{nac}")
    if isinstance(audit, dict):
        cn = audit.get("commerce_notes")
        if isinstance(cn, list) and cn:
            joined = " | ".join(str(x) for x in cn[:5])
            if len(joined) > 320:
                joined = joined[:317] + "..."
            parts.append("commerce: " + joined)
    if not parts:
        return ""
    title = "[FACTS CHANGED THIS TURN — use for prose, do not contradict CALCULATED STATE below]" if lang == "en" else "[FAKTA BERUBAH TURN INI — untuk prosa; jangan bentrok dengan CALCULATED STATE di bawah]"
    return title + "\n" + " | ".join(parts)


def _fmt_intimacy_summary(state: dict[str, Any], lang: str) -> str:
    meta = state.get("meta", {}) or {}
    il = meta.get("intimacy_last")
    if not isinstance(il, dict):
        return ""
    try:
        cur_turn = int(meta.get("turn", 0) or 0)
        if int(il.get("turn", -1) or -1) != cur_turn:
            return ""
    except Exception:
        return ""
    partner = str(il.get("partner", "") or "-")
    try:
        sat = int(il.get("satisfaction", 0) or 0)
    except Exception:
        sat = 0
    tier = str(il.get("tier", "") or "")
    if lang == "en":
        return (
            f"[INTIMACY SUMMARY — engine, this turn]\n"
            f"partner={partner} satisfaction_roll={sat}/100 tier={tier} (use for emotional aftermath only; fade explicit acts)"
        )
    return (
        f"[INTIMACY SUMMARY — engine, turn ini]\n"
        f"partner={partner} satisfaction_roll={sat}/100 tier={tier} (untuk suasana sesudah fade; adegan eksplisit tidak ditulis)"
    )


def _roll_reason_line(roll_pkg: dict[str, Any], lang: str) -> str:
    oc = str(roll_pkg.get("outcome", ""))
    if "Social Non-Conflict" in oc:
        return "Social non-conflict → no roll" if lang == "en" else "Kontak sosial non-konflik → tanpa roll"
    if "Low stakes" in oc:
        return "Low stakes → no roll" if lang == "en" else "Taruhan rendah → tanpa roll"
    if "No Roll" in oc and "Trivial" not in oc:
        return "No roll" if lang == "en" else "Tanpa roll"
    if "Trivial" in oc:
        return "Trivial → no roll" if lang == "en" else "Trivial → tanpa roll"
    if "Impossible" in oc:
        return "Impossible → auto fail" if lang == "en" else "Mustahil → auto gagal"
    if "CC Gate" in oc:
        return "CC gate → auto fail" if lang == "en" else "Gate CC → auto gagal"
    if "Auto Fail" in oc or "Combat blocked" in oc:
        return oc
    return "Uncertain + stakes" if lang == "en" else "Tak pasti + ada taruhan"


def _fmt_actionable_hooks(state: dict[str, Any], lang: str) -> str:
    """High-signal hooks for narration: scene commands, queue, contacts, nearby, news."""
    sc0 = state.get("active_scene")
    if isinstance(sc0, dict) and sc0:
        st = str(sc0.get("scene_type", "") or "").strip()
        opts = sc0.get("next_options") or []
        if isinstance(opts, list) and opts:
            pv = [str(x) for x in opts[:12] if isinstance(x, str)]
            if pv:
                sep = " | ".join(pv)
                if lang == "en":
                    return "scene_only: " + (st or "?") + " → " + sep
                return "scene_only: " + (st or "?") + " → " + sep

    lines: list[str] = []
    world = state.get("world", {}) or {}
    meta = state.get("meta", {}) or {}
    day = int(meta.get("day", 1) or 1)

    try:
        from engine.npc.memory import is_trigger_condition_met

        reporting: list[str] = []
        for nid, row in (state.get("npcs", {}) or {}).items():
            if not isinstance(row, dict) or row.get("ambient") is True:
                continue
            tags = row.get("belief_tags", [])
            if isinstance(tags, list) and "Eternal_Gratitude" in tags:
                continue
            if is_trigger_condition_met(state, str(nid), "REPORTING_RISK"):
                reporting.append(str(nid))
        if reporting:
            ids = ", ".join(reporting[:5])
            if lang == "en":
                lines.append(
                    f"[REPORTING_RISK] NPC(s) {ids} may report you — prioritize: "
                    "`[TALK <name>]` (bribe/threaten angle) or `[LEAVE_AREA]` / travel to break contact."
                )
            else:
                lines.append(
                    f"[REPORTING_RISK] NPC {ids} berisiko melapor — utamakan: "
                    "`[TALK <nama>]` (sudut suap/ancam) atau `[LEAVE_AREA]` / travel untuk menjauh."
                )
    except Exception:
        pass

    pe = state.get("pending_events") or []
    if isinstance(pe, list):
        for ev in pe[:4]:
            if not isinstance(ev, dict):
                continue
            title = str(ev.get("title", ev.get("event_type", "?")))
            dd = ev.get("due_day", "?")
            dt = ev.get("due_time", "?")
            if lang == "en":
                lines.append(f"queued: {title} @ day {dd} t={dt}")
            else:
                lines.append(f"antrian: {title} @ hari {dd} t={dt}")

    contacts = world.get("contacts", {}) or {}
    if isinstance(contacts, dict) and contacts:
        names = [str(k) for k in list(contacts.keys())[:8]]
        if lang == "en":
            lines.append("contacts: " + ", ".join(names) + "  (try: TALK <name>)")
        else:
            lines.append("kontak: " + ", ".join(names) + "  (mis. TALK <nama>)")

    npcs = state.get("npcs", {}) or {}
    if isinstance(npcs, dict) and npcs:
        preview: list[str] = []
        for name, row in list(npcs.items())[:6]:
            if not isinstance(row, dict) or row.get("ambient") is True:
                continue
            preview.append(str(name))
        if preview:
            if lang == "en":
                lines.append("npcs_here: " + ", ".join(preview))
            else:
                lines.append("npc_di_sini: " + ", ".join(preview))

    nearby = world.get("nearby_items", []) or []
    if isinstance(nearby, list) and nearby:
        ids: list[str] = []
        for x in nearby[:6]:
            if isinstance(x, dict):
                ids.append(str(x.get("id", x.get("name", "-"))))
            else:
                ids.append(str(x))
        if ids:
            if lang == "en":
                lines.append("nearby_pickup: " + ", ".join(ids))
            else:
                lines.append("dekat_pickup: " + ", ".join(ids))

    news = world.get("news_feed", []) or []
    if isinstance(news, list) and news:
        todays: list[dict[str, Any]] = []
        for it in news[-12:]:
            if isinstance(it, dict) and int(it.get("day", -1) or -1) == day:
                todays.append(it)
        src = todays[-1:] if todays else news[-1:]
        for it in src:
            if not isinstance(it, dict):
                continue
            txt = str(it.get("text", "")).strip()
            if len(txt) > 100:
                txt = txt[:97] + "..."
            if txt:
                if lang == "en":
                    lines.append("news_today: " + txt)
                else:
                    lines.append("berita_hari_ini: " + txt)
                break

    trig = state.get("triggered_events_this_turn") or []
    if isinstance(trig, list) and trig:
        t0 = trig[0]
        if isinstance(t0, dict):
            tl = str(t0.get("title", t0.get("event_type", "event")))
            if lang == "en":
                lines.append("just_triggered: " + tl)
            else:
                lines.append("baru_terpicu: " + tl)

    surf = state.get("surfacing_ripples_this_turn") or []
    if isinstance(surf, list) and surf:
        r0 = surf[0]
        if isinstance(r0, dict):
            rt = str(r0.get("text", "")).strip()
            if rt:
                if len(rt) > 90:
                    rt = rt[:87] + "..."
                if lang == "en":
                    lines.append("ripple_now: " + rt)
                else:
                    lines.append("ripple_sekarang: " + rt)
        for rp in surf[:3]:
            if not isinstance(rp, dict):
                continue
            rk = str(rp.get("kind", "") or "").strip().lower()
            meta = rp.get("meta") if isinstance(rp.get("meta"), dict) else {}
            npc = str(meta.get("npc", "") or "").strip()
            if rk == "npc_utility_contact":
                if lang == "en":
                    lines.append(
                        "utility_signal: npc contact surfaced"
                        + (f" ({npc})" if npc else "")
                        + "; interaction can follow via TALK or PHONE CALL."
                    )
                else:
                    lines.append(
                        "utility_signal: kontak npc ter-surface"
                        + (f" ({npc})" if npc else "")
                        + "; bisa ditindaklanjuti lewat TALK atau PHONE CALL."
                    )
            elif rk == "npc_utility_seek_job":
                if lang == "en":
                    lines.append("utility_signal: npc job-seeking pressure became visible in local rumor.")
                else:
                    lines.append("utility_signal: tekanan cari kerja npc terlihat sebagai rumor lokal.")
            elif rk == "npc_utility_relocate":
                if lang == "en":
                    lines.append("utility_signal: npc relocation surfaced; describe district-shift consequences.")
                else:
                    lines.append("utility_signal: perpindahan distrik npc ter-surface; gambarkan dampak wilayah.")

    talk_ex: str | None = None
    if isinstance(contacts, dict) and contacts:
        talk_ex = str(next(iter(contacts.keys())))
    elif isinstance(npcs, dict) and npcs:
        for nm, row in npcs.items():
            if isinstance(row, dict) and row.get("ambient") is not True:
                talk_ex = str(nm)
                break
        if talk_ex is None:
            talk_ex = str(next(iter(npcs.keys())))
    if talk_ex:
        if lang == "en":
            lines.append(
                f"example_type: INTERACTION bullets use `- [TALK {talk_ex}] ...` | `- [INFORMANTS] ...` | `- [WORLD_BRIEF] ...` (ALL CAPS inside brackets)"
            )
        else:
            lines.append(
                f"example_type: bullet INTERACTION pakai `- [TALK {talk_ex}] ...` | `- [INFORMANTS] ...` | `- [WORLD_BRIEF] ...` (perintah KAPITAL di dalam kurung siku)"
            )

    if lang == "en":
        lines.append(
            "handles_note: IDs like Operator_Link are engine handles — in INTERACTION_NODE use bullets `- [TALK Operator_Link] purpose` from ACTIONABLE; never first-person diary."
        )
    else:
        lines.append(
            "handles_note: ID seperti Operator_Link adalah handle engine — di INTERACTION_NODE pakai bullet `- [TALK <id>] tujuan` dari KAIT AKSI; dilarang narasi buku harian orang pertama."
        )

    if not lines:
        return "(none)" if lang == "en" else "(kosong)"
    return "\n".join(lines)


def _fmt_access_gates_qual(state: dict[str, Any]) -> str:
    try:
        from engine.social.reputation_lanes import black_market_access_tier, dominant_lane, premium_informant_unlocked
        from engine.systems.judicial import is_incarcerated

        tier = int(black_market_access_tier(state))
        depth = ("shallow", "standard", "wide", "full")[min(3, max(0, tier))]
        inf = "allowed" if premium_informant_unlocked(state) else "limited"
        dom = str(dominant_lane(state))
        jud = "incarcerated" if is_incarcerated(state) else "free"
        return f"judicial_movement: {jud} | bm_catalog_depth: {depth} | informant_deep_payouts: {inf} | rep_dominant_lane: {dom}"
    except Exception:
        return "judicial_movement: unknown | bm_catalog_depth: unknown | informant_deep_payouts: unknown"


def build_turn_package(
    state: dict[str, Any],
    player_input: str,
    roll_pkg: dict[str, Any],
    action_ctx: dict[str, Any] | None = None,
) -> str:
    """Assemble the narrator XML package. Injects weather, skills, factions, and related
    blocks **conditionally** from ``action_ctx`` (``TurnContextProfile``) to limit tokens
    while keeping domain-relevant facts (travel/stealth → weather; social/talk → rep/factions; etc.).
    """
    action_ctx = action_ctx or {}
    bio = state.get("bio", {})
    eco = state.get("economy", {})
    tr = state.get("trace", {})
    flags = state.get("flags", {})
    rep = state.get("reputation", {}) or {}
    world = state.get("world", {}) or {}
    nearby = world.get("nearby_items", []) or []
    nearby_str = "-"
    if isinstance(nearby, list) and nearby:
        labels: list[str] = []
        for x in nearby[:10]:
            if isinstance(x, dict):
                labels.append(str(x.get("id", x.get("name", "-"))))
            else:
                labels.append(str(x))
        nearby_str = ", ".join(labels)
    lang = get_narration_lang(state)
    lang_label = "Bahasa Indonesia" if lang == "id" else "English"

    try:
        from engine.core.trace import fmt_trace_monitor_ui, get_trace_tier

        trace_display = fmt_trace_monitor_ui(state)
        trace_tier_id = str(get_trace_tier(state).get("tier_id", "Ghost") or "Ghost")
    except Exception:
        trace_display = f"{tr.get('trace_pct', 0)}% [{tr.get('trace_status', 'Ghost')}]"
        trace_tier_id = str(tr.get("trace_status", "Ghost") or "Ghost")

    eng_title = "[ENGINE — single source for this turn]" if lang == "en" else "[ENGINE — sumber kebenaran turn ini]"
    act_title = (
        "[ACTIONABLE HOOKS — MUST inform EVENT_LOG + INTERACTION_NODE; use for typable command hints]"
        if lang == "en"
        else "[KAIT AKSI — WAJIB memengaruhi EVENT_LOG + INTERACTION_NODE; pakai untuk saran perintah ketik]"
    )
    beat_title = "[WORLD BEAT — resolved this turn]" if lang == "en" else "[BEAT DUNIA — terjadi di turn ini]"
    queue_title = "[WORLD QUEUE — background]" if lang == "en" else "[ANTREAN DUNIA — latar]"
    npc_title = "[NPCs — snapshot]" if lang == "en" else "[NPC — cuplikan]"

    prof = _turn_dynamic_profile(action_ctx)

    rep_label = "neutral"
    rep_global = 50.0
    rep_criminal = 50.0
    rep_corporate = 50.0
    rep_political = 50.0
    rep_street = 50.0
    rep_underground = 50.0
    rel_lines = "-"
    rep_block = ""
    key_rel_block = ""
    factions_block = ""
    if prof.social_faction:
        rep_scores = rep.get("scores", {}) if isinstance(rep.get("scores"), dict) else {}
        label_to_score = {
            "hostile": 20,
            "bad": 30,
            "poor": 35,
            "neutral": 50,
            "good": 70,
            "trusted": 85,
            "ally": 90,
        }

        def _rep_score(raw: Any, label_raw: Any) -> float:
            try:
                if raw is not None:
                    return max(0.0, min(100.0, float(raw)))
            except Exception:
                pass
            lab = str(label_raw or "Neutral").strip().lower()
            return float(label_to_score.get(lab, 50.0))

        rep_criminal = _rep_score(rep_scores.get("criminal"), rep.get("criminal_label"))
        rep_corporate = _rep_score(rep_scores.get("corporate"), rep.get("corporate_label"))
        rep_political = _rep_score(rep_scores.get("political"), rep.get("political_label"))
        rep_street = _rep_score(rep_scores.get("street"), rep.get("civilian_label"))
        rep_underground = _rep_score(
            rep_scores.get("underground"), rep.get("underground_label", rep.get("global_label", "Neutral"))
        )
        rep_global_raw = rep.get("global_score")
        rep_global = _rep_score(rep_global_raw, rep.get("global_label"))
        if rep_global_raw is None:
            rep_global = round((rep_criminal + rep_corporate + rep_political + rep_street + rep_underground) / 5.0, 1)
        if rep_global >= 80:
            rep_label = "legendary"
        elif rep_global >= 65:
            rep_label = "respected"
        elif rep_global >= 45:
            rep_label = "neutral"
        elif rep_global >= 30:
            rep_label = "shaky"
        else:
            rep_label = "notorious"
        try:
            from engine.npc.relationship import get_top_relationships

            top_rels = get_top_relationships(state, limit=5)
            rows: list[str] = []
            for nm, rel in top_rels:
                rr = rel if isinstance(rel, dict) else {}
                rows.append(
                    f"- {nm}: type={str(rr.get('type', 'neutral'))} strength={int(rr.get('strength', 50) or 50)} "
                    f"trust={float(rr.get('trust', 50.0) or 50.0):.1f} susp={float(rr.get('suspicion', 0.0) or 0.0):.1f}"
                )
            if rows:
                rel_lines = "\n".join(rows[:5])
        except Exception:
            pass
        rep_block = (
            "[REPUTATION]\n"
            f"global: {rep_label} ({rep_global})\n"
            f"criminal: {rep_criminal}\n"
            f"corporate: {rep_corporate}\n"
            f"political: {rep_political}\n"
            f"street: {rep_street}\n"
            f"underground: {rep_underground}\n"
        )
        key_rel_block = f"[KEY RELATIONSHIPS]\n{rel_lines}\n"
        factions_block = (
            "[FACTIONS]\n"
            f"corp st={state.get('world', {}).get('factions', {}).get('corporate', {}).get('stability', '-')} "
            f"pw={state.get('world', {}).get('factions', {}).get('corporate', {}).get('power', '-')} "
            f"att={state.get('world', {}).get('faction_statuses', {}).get('corporate', '-')}\n"
            f"police st={state.get('world', {}).get('factions', {}).get('police', {}).get('stability', '-')} "
            f"pw={state.get('world', {}).get('factions', {}).get('police', {}).get('power', '-')} "
            f"att={state.get('world', {}).get('faction_statuses', {}).get('police', '-')}\n"
            f"black st={state.get('world', {}).get('factions', {}).get('black_market', {}).get('stability', '-')} "
            f"pw={state.get('world', {}).get('factions', {}).get('black_market', {}).get('power', '-')} "
            f"att={state.get('world', {}).get('faction_statuses', {}).get('black_market', '-')}\n"
        )

    access_gates_block = ""
    if prof.access_gates:
        access_gates_block = (
            "[ACCESS GATES — qualitative; narrator avoids repeating as raw stats in fiction]\n"
            + _fmt_access_gates_qual(state)
            + "\n"
        )

    dyn_lines: list[str] = []
    if prof.skill_keys:
        sk_line = _fmt_skills_engine(state, lang, prof.skill_keys)
        if sk_line:
            dyn_lines.append(sk_line)
    if prof.weather:
        dyn_lines.append(_fmt_weather_engine(state, lang))
    if prof.disguise:
        dyn_lines.append(_fmt_disguise_engine(state, lang))
    sh_line = _fmt_safehouse_engine(state, lang)
    if sh_line:
        dyn_lines.append(sh_line)
    dyn_lines.append(_fmt_vehicle_line(state))
    dyn_lines.append(_fmt_cyber_alert_line(state))
    if prof.language_barrier:
        lb = _fmt_language_engine(state, lang)
        if lb:
            dyn_lines.append(lb)
    intsum = _fmt_intimacy_summary(state, lang)
    if intsum:
        dyn_lines.append(intsum)
    if prof.npc_combat_brief:
        ncb = _fmt_npc_combat_brief(state, lang)
        if ncb:
            dyn_lines.append(ncb)
    dynamic_engine_inject = "\n".join(dyn_lines)

    post_weapon_lines: list[str] = []
    if prof.social_stats:
        post_weapon_lines.append(_fmt_social_stats(state))
    if prof.character_stats:
        post_weapon_lines.append(_fmt_character_stats(state))
    post_weapon = "\n".join(post_weapon_lines)

    career_engine = "-"
    try:
        from engine.systems.occupation import fmt_career_engine_brief

        career_engine = fmt_career_engine_brief(state)
    except Exception:
        pass

    property_engine = "-"
    try:
        from engine.systems.property import fmt_property_engine_brief

        property_engine = fmt_property_engine_brief(state)
    except Exception:
        pass

    return f"""[TURN PACKAGE - OMNI-ENGINE v6.9]
[NARRATION LANGUAGE]
{lang_label} (code={lang})
[PLAYER INPUT]
{player_input}
{_fmt_memory_recall(player_input, lang)}
{_fmt_narrative_thread(state, lang)}
{_fmt_narrative_safety(lang)}
{act_title}
{_fmt_actionable_hooks(state, lang)}
{eng_title}
{_fmt_meta_clock(state)}
{_fmt_player_card(state)}
{_fmt_location_tags(state)}
{_fmt_district_line(state)}
{_fmt_accommodation_state(state, lang)}
{_fmt_turn_facts_delta(state, lang)}
{_fmt_reputation_lanes_tone(state, lang)}
{_fmt_economy_detail(state, lang)}
{_fmt_engine_recent_commerce(state, lang)}
{dynamic_engine_inject}
{_fmt_action_ctx(action_ctx)}
{_fmt_accommodation_policy(action_ctx, lang)}
{_fmt_narration_sync_dynamic(lang, prof)}
{_fmt_weapon_line(state)}
{post_weapon}
flags: weapon_jammed={flags.get('weapon_jammed')} stop_seq={flags.get('stop_sequence_active')}
{beat_title}
{_fmt_beat_this_turn(state, lang)}
{_fmt_arc_campaign_brief(state, lang)}
{_fmt_quest_started_this_turn(state, lang)}
{queue_title}
{_fmt_queues(state, lang)}
{npc_title}
{_fmt_npcs(state)}
Recent world_notes:
{_fmt_world_notes(state)}
{_fmt_social_rumor_brief(state, action_ctx)}
{_fmt_npc_beliefs_brief(state, action_ctx)}
{_fmt_npc_memories_brief(state, action_ctx)}
[CALCULATED STATE]
Blood: {bio.get('blood_volume', 5.0)}L / {bio.get('blood_max', 5.0)}L | BP: {bio.get('bp_state', 'Stable')}
Sleep Debt: {bio.get('sleep_debt', 0)}h | Infection: {bio.get('infection_pct', 0)}%
Burnout: {bio.get('burnout', 0)}/10 | Sanity Debt: {bio.get('sanity_debt', 0)}
[PLAYER MENTAL STATE]
mood: {bio.get('mood_label', 'meh')} ({bio.get('mood_score', 50.0)})
spiral: {bio.get('mental_spiral', False)}
hunger: {bio.get('hunger_label', 'full')} ({bio.get('hunger', 0.0)})
sleep_duration: {action_ctx.get('sleep_duration_h', 0)} jam
sleep_quality: {action_ctx.get('sleep_quality', 'okay')}
{rep_block}{access_gates_block}[CAREER / W2-9 — per-track progression; narrator: no digits in fiction]
{career_engine}
[PROPERTY / W2-10 — assets & quotes; narrator: no digits in fiction]
{property_engine}
{key_rel_block}
Cash: {eco.get('cash', 0)} | Bank: {eco.get('bank', 0)} | Debt: {eco.get('debt', 0)} | Daily Burn: {eco.get('daily_burn', 0)}
FICO: {eco.get('fico', 600)} | AML: {eco.get('aml_status', 'CLEAR')}
Trace: {trace_display} (tier={trace_tier_id})
CC: {state.get('player', {}).get('cc', 0)} | Econ tier: {state.get('player', {}).get('econ_tier', '-')} | Hygiene Tax: {bio.get('hygiene_tax_active', False)}
Acute Stress: {bio.get('acute_stress', False)} | Stop Sequence: {flags.get('stop_sequence_active', False)}
Hallucination: {bio.get('hallucination_type', 'none')} | Narrator Drift: {bio.get('narrator_drift_state', 'stable')}
Permanent Damage: {state.get('permanent_damage_summary', '-')}
NearbyItems: {nearby_str}
{factions_block}[MODIFIER STACK]
{_fmt_mods(roll_pkg.get('mods', []))}
NET THRESHOLD: {roll_pkg.get('net_threshold', 0)}%
[ROLL RESULT]
Roll: {roll_pkg.get('roll', 'N/A')} / 100 vs {roll_pkg.get('net_threshold', 0)}%
Outcome: {roll_pkg.get('outcome', 'No Roll')}
Reason: {_roll_reason_line(roll_pkg, lang)}
ThresholdLocked: {roll_pkg.get('net_threshold_locked', True)}
[ACTIVE CONSTRAINTS]
Stop Sequence: {flags.get('stop_sequence_active', False)}
Stop Trigger: {flags.get('stop_sequence_trigger', '')}
Hand Slot Issue: {flags.get('hand_slot_issue', False)}
Weapon Jam: {flags.get('weapon_jammed', False)}
Equip Cost: {flags.get('equip_cost_active', False)}
Hallucination Active: {flags.get('hallucination_active', False)}
{_dialogue_contract(action_ctx, lang)}
[OUTPUT FORMAT - STRICT — tag names fixed]
<OMNI_MONITOR>...</OMNI_MONITOR>
<INTERNAL_LOGIC>...</INTERNAL_LOGIC>
<SENSORY_FEED>...</SENSORY_FEED>
<EVENT_LOG>...</EVENT_LOG>
<INTERACTION_NODE>...</INTERACTION_NODE>
<MEMORY_HASH>
🎯 ... (At most 5 emoji lines TOTAL; one short clause each; skip rows that add nothing.)
📜 ...
🤝 ...
</MEMORY_HASH>
[YOUR TASK]
{f'Fill every section. Second person (You) everywhere; cold/tactical tone — no diary/I-voice. INTERACTION_NODE: bullet lines `- [CAPS_COMMAND] purpose` then `What do you do?` Use ACTIONABLE HOOKS. MEMORY_HASH ≤5 emoji lines. Respect ENGINE + WORLD BEAT + ROLL.' if lang == 'en' else f'Isi semua section. Orang kedua (Kamu) di seluruh prosa; nada dingin/taktis — dilarang buku harian/aku. INTERACTION_NODE: bullet `- [PERINTAH_KAPITAL] tujuan` lalu `Apa yang akan kamu lakukan?` Pakai KAIT AKSI. MEMORY_HASH maks. 5 baris. Hormati ENGINE + BEAT DUNIA + ROLL.'}
"""
