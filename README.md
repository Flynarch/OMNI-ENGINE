# OMNI-ENGINE

> **Deterministic simulation** — the AI **narrates** and maps intent; Python **owns** time, rolls, economy, and consequences.  
> Terminal cyberpunk sandbox · one persistent character · systemic, replayable outcomes.

`Python 3.11+` · `MIT` · **Rich** terminal UI

---

## At a glance

OMNI-ENGINE is a **rules-first** game core: **time, economy, combat, hacking, factions, NPCs, quests, and trace** are resolved in Python with reproducible outcomes. An LLM **narrates** and **maps free-form intent** to structured actions—but it does **not** override mechanics.

| Principle           | What it means                                                                                           |
| ------------------- | ------------------------------------------------------------------------------------------------------- |
| **Determinism**     | Same save state + same player input ⇒ same simulation path (testable, replay-friendly).                 |
| **State authority** | `save/current.json` is the source of truth; narration and UI read it, they do not invent stats.         |
| **Hybrid intent**   | LLM JSON intent + regex/heuristic parser; engine picks a valid execution path with gates and fallbacks. |
| **Bounded intel**   | News and ripples are structured, deduped, and pruned so saves stay maintainable.                        |

---

## Table of contents

1. [Features](#features)
2. [Quickstart](#quickstart)
3. [Configuration](#configuration)
4. [Saves, archive & publishing](#saves-archive--publishing)
5. [In-game commands](#in-game-commands-sample)
6. [Seed packs & data](#seed-packs--data)
7. [Scripts & tooling](#scripts--tooling)
8. [Repository layout](#repository-layout)
9. [Release highlights](#release-highlights)
10. [Roadmap](#roadmap)
11. [License](#license)

---

## Features

### Time & world

- Turn-based **world clock** with automatic micro-costs for inventory actions.
- **Weather** per location (deterministic) affecting travel and stealth-related rolls.
- **Location restrictions** (`police_sweep`, `corporate_lockdown`) with real mechanical effects.

### Social & NPCs

- Plutchik-style **emotions**, decay, **beliefs**, and short **memory** with source and confidence.
- **Gossip** and rumor propagation during social play (rate-limited, channel-aware).

### Trace, economy, factions

- **Trace tiers** from low attention through serious heat.
- **Hacking heat** per target with inventory tooling hooks.
- **Layered economy**: global → country → city; geopolitical pressure and local modifiers.
- **Ripples** with propagation modes (local / contacts / broadcast) and structured impact.
- **Underworld**: black market flows, sting risk, arrest chains, faction escalation from targeted hacks.

### Lodging, commerce, progression

- **Shop / bank / prepaid stay** (hotel, boarding, suite) integrated with audit trails.
- **Disguise** personas; **safehouses** (rent, stash, trace decay).
- **Skill XP** by domain after rolls; decay when skills idle.

### Language & content

- Language learning and communication barriers; **Earth-only** city presets under `data/locations/`.
- **Content packs** under `data/packs/` (items, roles, services) with validation scripts.

### AI narration (turn package)

**Dynamic context injection** — The narrator XML from `build_turn_package` in [`ai/turn_prompt.py`](ai/turn_prompt.py) is gated by **`TurnContextProfile`**, produced by **`_turn_dynamic_profile(action_ctx)`** from the resolved **`action_ctx`** (`domain`, `action_type`, `intent_note`). **Weather** is included for travel- or stealth-shaped beats; **reputation, faction lines, and key relationships** only for social/faction-relevant turns (for example `talk`, `domain=social`, or notes touching informants, reputation, or underworld); **skills** are emitted as a **domain-scoped** subset instead of the full skill grid; **access gates** (judicial movement, BM catalog depth, informant depth) appear for social, hacking, or black-market–tinted hints. A thin or empty `action_ctx` yields a smaller package on purpose — keep the pipeline filling `domain` / `action_type` when those blocks should inform prose.

**Async CLI loop** — The main play loop runs under **`asyncio`** with **`aioconsole.ainput`** for the `>` prompt (same event loop as httpx narration / intent). While the model is thinking, a small **spinner** can show (`OMNI_LLM_HEARTBEAT`, default on); set to `0` to disable.

---

## Quickstart

```bash
# From your checkout of this repository
cd OMNI-ENGINE

python -m venv .venv
# Windows: .venv\Scripts\activate
# macOS/Linux: source .venv/bin/activate

pip install -r requirements.txt
cp .env.example .env   # Windows: copy .env.example .env
```

Edit `.env`: set **`OPENROUTER_API_KEY`** or **`GROQ_API_KEY`** (see [Configuration](#configuration)).

```bash
python main.py
```

On first launch you define a short profile and pick a **seed pack** (`default`, `minimal`, or `none`).

---

## Configuration

Commented templates for the variables below (including feed prune and engine error log) live in **`.env.example`**.

### LLM providers

**OpenRouter (default)**

```env
OPENROUTER_API_KEY=sk-or-v1-...
# OPENROUTER_MODEL=openrouter/free
```

**Groq** (example: Llama 3.3 70B)

```env
LLM_PROVIDER=groq
GROQ_API_KEY=gsk_...
GROQ_MODEL=llama-3.3-70b-versatile
```

Model directories: [OpenRouter models](https://openrouter.ai/models) · [Groq docs](https://console.groq.com/docs/models)

Optional tuning (see `.env.example`): `LLM_MAX_TOKENS`, `LLM_INTENT_MAX_TOKENS`, `LLM_HTTP_RETRIES`, `NARRATION_LANG`, `BAL_*`, bio keys, `STRICT_PACK_VALIDATION`, `OMNI_AUTO_STAY_INTENT`, `OMNI_LLM_HEARTBEAT`.

### FFCI (free-form custom intent)

| Variable                                 | Default | Meaning                                                                    |
| ---------------------------------------- | ------- | -------------------------------------------------------------------------- |
| `OMNI_FFCI_ENABLED`                      | `1`     | `0` = skip LLM intent resolver; parser-only mechanics.                     |
| `OMNI_FFCI_SHADOW_ONLY`                  | `0`     | `1` = still call resolver for logging, but mechanics use parser path only. |
| `OMNI_FFCI_CUSTOM_HIGH_RISK_CAP_PER_DAY` | `4`     | Caps high/medium-stakes **custom** LLM intents merged per in-game day.     |

### Feed archive limits (in-game prune)

Applied during **`world_tick`**, **`load_state`**, and **`save_state`**: old `world_notes` / `world.news_feed` entries move to **`save/archive.json`**, active lists stay bounded.

| Variable                     | Default | Range (clamped) | Meaning                                                                         |
| ---------------------------- | ------- | --------------- | ------------------------------------------------------------------------------- |
| `OMNI_FEED_MAX_AGE_DAYS`     | `7`     | 1–365           | Drop from active state when `meta.day - entry.day` exceeds this.                |
| `OMNI_FEED_MAX_ENTRIES`      | `100`   | 10–500          | Max active entries per list (newest tail kept).                                 |
| `OMNI_FEED_ARCHIVE_LIST_CAP` | `5000`  | 100–50000       | Max rows per list **inside** `archive.json` (oldest dropped from archive file). |

### Engine error log (non-fatal)

Swallowed exceptions in the engine can append tracebacks to a file log (never blocks gameplay).

| Variable                        | Meaning                                            |
| ------------------------------- | -------------------------------------------------- |
| `OMNI_ENGINE_ERROR_LOG_DISABLE` | `1` / `true` / `yes` / `on` disables file logging. |
| `OMNI_ENGINE_ERROR_LOG_PATH`    | Override path (default: `logs/engine_errors.log`). |

---

## Saves, archive & publishing

### Files

| Path                 | Role                                                                                       |
| -------------------- | ------------------------------------------------------------------------------------------ |
| `save/current.json`  | Active session (autosave).                                                                 |
| `save/previous.json` | Backup used for `UNDO` in Normal mode.                                                     |
| `save/archive.json`  | Long-tail **world_notes** and **news_feed** evicted from active state (append + tail cap). |

All under `save/` are **gitignored**—do not commit personal saves or archives.

### Publishing or sharing a bundle

1. Run the game as usual; pruning keeps **`current.json`** lean automatically.
2. To shrink **`archive.json`** before distribution, use the trim CLI (keeps the **newest** tail of each list):

```bash
# Preview only
python scripts/trim_feed_archive.py --dry-run

# Write a redacted copy for public share (drops engine prune timestamps)
python scripts/trim_feed_archive.py save/archive.json -o dist/archive_publish.json --keep 300 --redact-metadata

# In-place trim with backup
python scripts/trim_feed_archive.py --keep 400 --backup
```

See `python scripts/trim_feed_archive.py --help` for `--notes-keep`, `--news-keep`, and `--output`.

---

## In-game commands (sample)

| Command                                           | Purpose                                       |
| ------------------------------------------------- | --------------------------------------------- |
| `HELP`                                            | Full command list                             |
| `SHOWER` / `HYGIENE` / `MANDI`                    | Hygiene reset (engine time)                   |
| `STATUS` / `INFO`                                 | Condition: daily gigs cap, hack fatigue, etc. |
| `WHEREAMI`                                        | Location + short profile                      |
| `BANK …` / `STAY …`                               | Banking and prepaid lodging                   |
| `MARKET` / `BLACKMARKET` / `BUY_DARK …` / `QUEST` | Legal and underworld economy                  |
| `ATLAS` / `COUNTRIES` / `CITIES`                  | Atlas and cities                              |
| `WHO` / `NPC <name>`                              | NPC roster and detail                         |
| `HEAT` / `OFFERS`                                 | Hacking heat and NPC offers                   |
| `GIGS` / `WORK` / `HACK <target>`                 | Gigs and targeted hacking                     |
| `DISGUISE` / `SAFEHOUSE` / `WEATHER` / `SKILLS`   | Disguise, safehouse, weather, skills          |
| `MODE NORMAL` / `IRONMAN` · `UNDO`                | Mode and undo                                 |

---

## Seed packs & data

| Path                         | Role                                               |
| ---------------------------- | -------------------------------------------------- |
| `data/seeds/<name>.json`     | Safe merge into state at boot.                     |
| `data/locations/<city>.json` | City presets: NPCs, items, tags.                   |
| `data/packs/<id>/`           | Extensible content; validate before large changes. |
| `data/state_template.json`   | Default shape merged with boot profile.            |

For richer intra-city structure (districts + travel), a city can optionally define `data/locations/<city>_districts.json` (example: `data/locations/london_districts.json`). This bundle can declare the district list, per-district profiles (danger/police/economic tier, etc.), and a deterministic `district_graph` (weighted edges in minutes). Keeping this in a separate `*_districts.json` file avoids introducing new keys into `<city>.json`, so existing preset validation/allowlists remain unchanged.

---

## Scripts & tooling

| Command                                            | Purpose                                                                                 |
| -------------------------------------------------- | --------------------------------------------------------------------------------------- |
| `python scripts/verify.py`                         | `compileall` + smoke + regression scenarios (markets, quests, feed prune, trim CLI, …). |
| `python scripts/validate_all.py`                   | Packs + every location preset.                                                          |
| `python scripts/migrate_save.py`                   | Migrate older saves in-place (writes `.bak`).                                           |
| `python scripts/migrate_save.py path/to/save.json` | Same, explicit file.                                                                    |
| `python scripts/trim_feed_archive.py`              | Trim `save/archive.json` for smaller publish artifacts.                                 |
| `python scripts/feature_gap_export.py`             | Lightweight hints from telemetry + recent notes (no network).                           |

---

## Repository layout

| Path       | Role                                                                               |
| ---------- | ---------------------------------------------------------------------------------- |
| `main.py`  | REPL: intent, pipeline, autosave, AI streaming.                                    |
| `engine/`  | Simulation: time, world, economy, quests, trace, NPCs, bio, balance, feed prune, … |
| `ai/`      | LLM client (httpx + asyncio), intent resolver, turn package, system prompts.        |
| `display/` | Terminal UI (**Rich**).                                                            |
| `data/`    | Template, seeds, locations, packs.                                                 |
| `scripts/` | Verify, validate, migrate, trim archive, utilities.                                |
| `logs/`    | Optional `engine_errors.log` (gitignored; see env vars).                           |

---

## Release highlights

- **Intent schema v2 (plan-based)** with `plan.steps[]` and preconditions; engine picks the first valid step for the turn.
- **Shared LLM HTTP layer** with retries/backoff for streaming narration and JSON intent (`LLM_HTTP_RETRIES`).
- **FFCI** path with feasibility gates, schema discipline, and per-day caps for risky custom intents.
- **Turn audit**: `meta.last_turn_audit` includes `commerce_notes` and transparent deltas where applicable.
- **Security scenes**: police stop, safehouse raid, sting operations with deterministic resolution hooks.
- **Feed lifecycle**: automatic prune + **`save/archive.json`**; optional env limits; **`trim_feed_archive.py`** for publish.
- **Centralized swallowed-exception logging** to `logs/engine_errors.log` (optional disable/path via env).

---

## Roadmap

- Richer per-turn **time breakdown** in the UI (what consumed minutes automatically).
- Deeper **districts** and intra-city travel graphs.
- Stronger **NPC→NPC** diffusion (who hears what, with distortion).
- Stricter **pack schema** and CI gates for modding.

---

## License

[MIT](LICENSE) · Copyright (c) 2026 Flynarch

---

_Systems first; the story follows the state._
