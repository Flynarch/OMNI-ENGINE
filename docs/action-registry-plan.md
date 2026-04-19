# Action Registry — rencana arsitektur (data-driven intent)

## Tujuan

Menggantikan rantai `if / elif` tanpa akhir di `parse_action_intent` dengan model:

**Input pemain (NL)** → **satu `action_id` terdaftar** + **parameter** → **engine Python** mengeksekusi mekanik → **AI** hanya menarasikan.

Yang *tidak* berubah: **Python memegang kebenaran** (RNG, state, roll); AI tidak memutuskan hasil.

## Konsep inti

| Elemen | Fungsi |
|--------|--------|
| **Registry** (JSON / DB) | Daftar `action_id` yang valid: kata kunci, prioritas, patch ke `action_ctx`, atau rujukan *handler* kode. |
| **Resolver** | Memilih **satu** `action_id` (urutan prioritas + match pertama / skor). |
| **Dispatcher / handler** | Memetakan `action_id` → fungsi Python yang mengisi `action_ctx` dan memicu pipeline yang sudah ada (`update_timers`, combat gates, dll.). |
| **LLM (opsional, FFCI)** | Hanya mengembalikan **`action_id` + `params`** dari **himpunan terbatas** (constrained intent), bukan aturan baru. |

## Skema registry (v1)

Minimal per entri:

- `id` (string stabil, mis. `sleep.default`, `combat.ranged_attempt`)
- `version` / `priority` (integer, lebih kecil = dievaluasi lebih dulu jika perlu)
- `match`: salah satu atau kombinasi
  - `keywords_any`: list substring / kata
  - `regex` (opsional, hati-hati performa)
- `ctx_patch`: objek parsial yang di-merge ke `action_ctx` (hanya field yang sudah dipakai engine)
- `handler` (opsional): nama simbol di Python, mis. `"apply_travel_from_text"` — untuk logika yang tidak bisa diekspresikan statis (estimasi menit travel, ekstraksi destinasi).

Versi berikutnya bisa menambah: `preconditions`, `requires_scene`, `mutually_exclusive_group`.

## Fase migrasi (disarankan)

### Fase 0 — Kontrak ✅

- Dokumen ini + modul loader + `data/action_registry/registry_v1.json` + tes load.

### Fase 1 — Dual path (aman) ✅

- **Tidur NL** dari registry: `parse_action_intent` memanggil `_registry_try_sleep` **setelah** cabang akomodasi (supaya “hotel semalam” tidak tertimpa), **sebelum** `_parse_sleep_hours` legacy.
- `meta["resolved_action_id"]` + `meta["intent_resolution"] = "registry"` diset di `main.py` bila `action_ctx["registry_action_id"]` ada.

### Fase 1b — Combat NL (registry-first) ✅ (parsial)

- `_registry_try_combat` dipanggil **sebelum** cabang combat legacy (`combat_terms`): jika match `combat.*` di JSON, `ctx_patch` diterapkan + `registry_action_id`.
- Entri: `combat.nl_ranged_attempt` (tembak/nembak/shoot, …), `combat.nl_melee` (serang/attack/pukul, …). `intent_note: nl_attempt` **bukan** dari JSON; diset di Python bila substring sama seperti legacy (`mencoba`, `try to`, …).
- Input yang tidak match registry tetap jatuh ke **legacy** `elif combat_terms` (perilaku lama).

### Fase 1c — Travel NL (registry-first) ✅ (parsial)

- `_registry_try_travel` sebelum cabang `_TRAVEL_LEGACY_KEYWORDS`; heuristik menit / destinasi / kendaraan dipusatkan di `_apply_travel_heuristics` (dipakai registry + legacy).
- Entri `travel.nl_generic` (prioritas 40): kata kunci perjalanan yang sudah ada + sinonim aman (`head to`, `heading to`, `commute to`); ekstraksi destinasi Inggris ditambah di Python untuk frasa tersebut.

### Fase 1d — Domain skill (registry-first) ✅ (parsial)

- `_registry_try_skill_domain` sebelum cabang legacy `hacking` / `medical` / `driving` / `stealth` (hanya set `domain` seperti sebelumnya).
- Entri: `hacking.nl_keywords`, `medical.nl_keywords`, `driving.nl_keywords`, `stealth.nl_keywords` (prioritas 42–45, setelah travel). Sinonim tambahan hanya di JSON (mis. `piratear`, `first aid`, `take the wheel`, `stay hidden`) tetap memakai jalur registry; kata kunci lama tetap lewat legacy jika tidak ada di data.

### Fase 1e — Sosial & trivial (registry-first, parsial) ✅

- `match_registry_action_prefixed(text, id_prefix)` memilih aksi hanya dalam prefiks (`social.*`, `instant.*`) agar tidak berebut prioritas global dengan tidur/combat/travel.
- `_registry_try_social_nl` sebelum `_is_social_dialogue` / `_is_social_scan`: entri `social.nl_dialogue`, `social.nl_scan_crowd` (prioritas 46–47).
- `_registry_try_instant_trivial` di gate realism: `instant.nl_trivial` (50); tidak menimpa `registry_action_id` yang sudah diisi cabang `elif` lebih kuat; sinonim baru contoh `check inventory`.

### Fase 1f — Inquiry sosial + anchor LLM ✅ (parsial)

- `_registry_try_social_inquiry_nl` memakai `match_registry_action_prefixed(..., "social.inquiry.")` **sebelum** `_is_social_inquiry` (subset frasa + `?` + sinonim data-only seperti `what time is it`).
- **Policy merge FFCI**: setelah `merge_intent_into_action_ctx`, `apply_parser_registry_anchor_after_llm` mengembalikan `action_ctx["registry_action_id"]` dan men-set `meta["intent_resolution"] = "registry+llm"` sambil mempertahankan `meta["resolved_action_id"]` ke id parser (jejak audit; field mekanik lain tetap boleh di-overlay LLM).
- Jalur abuse re-parse: `resolved_action_id` / `intent_resolution` diselaraskan ulang dari hasil parse kedua (atau dihapus jika tidak ada registry).

### Fase 1g — Lanjutan

- Handler bernama di registry untuk cabang kompleks; penyatuan sumber keyword inquiry vs `_is_social_inquiry`.

### Fase 2 — Pindahkan cabang demi cabang

- Tidur, combat, travel “polos” → data + patch.
- Cabang yang butuh heuristik panjang → `handler` Python tunggal terdaftar di map, bukan 200 `elif`.

### Fase 3 — LLM terikat registry

- Prompt intent resolver: output JSON **hanya** `action_id` ∈ `allowed_action_ids` + `params` sesuai skema entri.
- Parser teks menjadi fallback ketika LLM tidak dipanggil atau gagal.

### Fase 4 — Penyederhanaan

- Kurangi duplikasi antara `action_intent.py` dan registry; satu sumber kebenaran untuk sinonim NL.

## Risiko & mitigasi

| Risiko | Mitigasi |
|--------|----------|
| Regresi perilaku | Fase 1 selalu punya fallback legacy; `verify.py` untuk setiap cabang yang dipindah. |
| JSON tidak cukup untuk logika kompleks | Field `handler` + fungsi Python kecil, tetap deterministik. |
| LLM “kreatif” di luar registry | Validasi keras: tolak `action_id` tidak dikenal; clamp params. |
| Performa | Match keyword dulu; regex terbatas; cache registry di memori setelah load. |

## Kriteria selesai (definisi “seperti database”)

- Menambah perilaku baru yang **murni data** (sinonim + `ctx_patch`) **tanpa** menyentuh `if` baru di `action_intent.py`.
- LLM (jika dipakai) **tidak** bisa mengusulkan aksi di luar `allowed_action_ids`.

## File yang direncanakan (repo)

- `data/action_registry/registry_v1.json` — isi entri bertambah seiring migrasi.
- `engine/core/action_registry.py` — load, validasi, resolve, merge patch.
- (Fase 1+) `engine/core/action_registry_handlers.py` — fungsi bernama untuk cabang kompleks.
- Integrasi bertahap di `engine/core/action_intent.py`.

## Catatan OMNI-ENGINE

Crafting, shop, travel engine, dll. sudah **data-driven** di modul masing-masing; registry ini menyatukan **lapisan “apa maksud input pemain ini?”** agar konsisten dengan pola tersebut.
