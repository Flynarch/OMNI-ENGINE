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

### Fase 1g — Handler + inquiry tunggal ✅ (parsial)

- Field opsional **`handler`** (string) per entri registry; hasil match menyertakan key `handler` bila ada; `action_intent` memanggil `apply_registry_handler` setelah patch (no-op jika nama belum terdaftar — lihat `engine/core/action_registry_handlers.py`).
- **`inquiry_phrases_match`**: substring inquiry disatukan dengan semua aksi `social.inquiry.*` di JSON; **`_is_social_inquiry`** memakainya (fallback minimal hanya jika load registry gagal).

### Fase 1h — Handler inquiry + audit keyword ✅ (parsial)

- Entri **`social.inquiry.nl_keywords`** memakai **`handler`: `ensure_social_inquiry_shape`** (`action_registry_handlers`): `ctx_patch` boleh tipis/kosong; field domain / inquiry diset di Python.
- **Tumpang-tindih yang disengaja / diketahui**: substring **`siapa `** di inquiry membuat frasa scan seperti `siapa di sekitar` terklasifikasi inquiry (sama seperti urutan legacy `_is_social_inquiry` sebelum `_is_social_scan`). Tidak ada overlap keyword antara `social.nl_dialogue` dan `social.inquiry.*`; `lihat sekitar` / `lihat orang` hanya di scan, bukan di trivial `lihat status`.

### Fase 1i — Allowlist intent + snapshot FFCI ✅ (parsial)

- **`allowed_registry_action_ids()`** di `action_registry.py` (alias semantik di atas `list_action_ids`) untuk permukaan allowlist / prompt.
- **`resolve_intent`** menyisipkan blok `[REGISTRY_ACTION_IDS]` ke user message; **INTENT_SYSTEM_PROMPT** menjelaskan bahwa itu hanya petunjuk silang, bukan field JSON baru.

### Fase 1j — Hint registry dari LLM ✅ (parsial)

- Intent v1/v2 boleh membawa **`registry_action_id_hint`** (top-level); `normalize_resolved_intent` memanggil `sanitize_registry_action_id_hint` — id tidak dikenal **dibuang**.
- **`merge_intent_into_action_ctx`** menyalin hint tervalidasi ke **`action_ctx["llm_registry_action_id_hint"]`** (terpisah dari `registry_action_id` parser / anchor).

### Fase 1k — Telemetri hint vs parser ✅ (parsial)

- **`registry_hint_alignment`**: label `none` | `parser_only` | `llm_only` | `match` | `mismatch` (parser `registry_action_id` vs `llm_registry_action_id_hint`).
- **`main.py`**: mirror `llm_registry_action_id_hint` ke `meta` + set `registry_hint_alignment` setelah intent merge (tiap turn).

### Fase 1l — Handler travel + flag mismatch ✅ (parsial)

- **`ensure_travel_registry_shape`**: handler untuk `travel.nl_generic` dengan `ctx_patch` kosong; heuristik `_apply_travel_heuristics` tetap mengisi menit/destinasi/kendaraan.
- **`meta["registry_hint_mismatch"]`**: `True` hanya jika `registry_hint_alignment == "mismatch"` (parser vs hint LLM).

### Fase 1m — Narration + mechanical gate (alignment) ✅ (parsial)

- **`main.py`**: `registry_hint_alignment` dan `registry_hint_mismatch` dicerminkan ke **`action_ctx`** (agar paket narasi konsisten).
- **`turn_prompt._fmt_action_ctx`**: baris ENGINE jika alignment ≠ `none`; peringatan keras jika **`registry_hint_mismatch`** (prioritas hasil parser/engine atas konflik hint LLM).
- **Gate mekanik**: jika parser punya **`registry_action_id`** dan setelah merge terjadi **`mismatch`** (parser vs `llm_registry_action_id_hint`), field yang sama dengan **`merge_intent_into_action_ctx`** dipulihkan dari snapshot pra-merge (dan field merge yang tidak ada di snapshot di-**pop** supaya tidak tertinggal overlay LLM); **`strip_llm_intent_overlay_on_registry_hint_mismatch`** menghapus overlay intent v2 (`intent_plan`, `step_now_id`, `player_goal`, …) agar tidak menabrak domain yang dipulihkan.
- **UI**: **`display/renderer`** — monitor compact `[INTENT]` dan full monitor `hint_mismatch=yes` pada baris LastIntent.

### Fase 2 — Pindahkan cabang demi cabang

- Tidur, combat, travel “polos” → data + patch.
- Cabang yang butuh heuristik panjang → `handler` Python tunggal terdaftar di map, bukan 200 `elif`.
- **Parsial**: konflik sosial eksplisit ke orang (`social.nl_conflict`) — `ctx_patch` di JSON, syarat AND (kata konflik + kata orang) tetap di Python; **`get_registry_action_by_id`** untuk load patch tanpa keyword global.
- **Parsial**: negosiasi / tipu ringkas (`social.nl_negotiation`, kata kunci di Python) — `ctx_patch` + handler **`ensure_social_negotiation_shape`** (formal vs standard).
- **Parsial**: istirahat singkat 60m — ``rest.nl_istirahat_short`` (frasa Indonesia di JSON) + ``rest.nl_prefix_60m`` (prefix ``rest …`` / kata ``istirahat`` saja lewat Python).
- **Parsial**: intimacy private konsensual — ``social.nl_intimacy_private`` (``ctx_patch`` + handler ``ensure_intimacy_private_registry_shape``); guard blokir / frasa positif tetap ``_is_intimacy_private``.
- **Parsial (data-only)**: sinonim tambahan di JSON untuk ``social.nl_dialogue`` (``dengan orang``, ``ke orang``, …) dan ``social.nl_scan_crowd`` (``mengintai``, ``people watching``, …) yang sebelumnya hanya di legacy ``_is_social_*``.
- **Parsial**: ``instant.nl_clear_jam`` (``clear jam`` / ``bersihin macet``) — menggantikan ``if`` string di ``parse_action_intent``; prioritas 49 sebelum ``instant.nl_trivial``.
- **Parsial**: ``instant.nl_physically_impossible`` (mustahil fisik) — prioritas 51; menggantikan ``if`` string realism gate.
- **Parsial**: STOP sequence — ``instant.nl_stop_irreversible`` / ``instant.nl_stop_new_zone`` / ``instant.nl_stop_critical_blood`` + ``iter_registry_matches_by_prefix`` (beberapa flag dalam satu input).

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
- `engine/core/action_registry_handlers.py` — map nama `handler` → callable (Fase 1g+).
- Integrasi bertahap di `engine/core/action_intent.py`.

## Catatan OMNI-ENGINE

Crafting, shop, travel engine, dll. sudah **data-driven** di modul masing-masing; registry ini menyatukan **lapisan “apa maksud input pemain ini?”** agar konsisten dengan pola tersebut.
