"""Operational governance constants (SLO targets, non-goals, privacy, QA checklist).

Readable by tooling; not player-facing. Plan Fase 7–9 operationalization.
"""

from __future__ import annotations

# Target SLOs (monitor via telemetry_turn_last + meta counters; not auto-enforced).
SLO_INTENT_VALID_RATE_MIN = 0.85
SLO_PARSER_FALLBACK_MAX_STAGE_B = 0.20
SLO_PARSER_FALLBACK_MAX_STAGE_C = 0.10
SLO_DETERMINISTIC_MISMATCH_MAX = 0.01

# Telemetry retention (in-game turns kept in rolling buffers where applicable).
TELEMETRY_ROLLING_TURNS = 120
INTENT_RAW_MAX_CHARS = 2000

NON_GOALS = (
    "No runtime self-modifying Python loaded from LLM output.",
    "No LLM-authored state patches applied without human review and verify gates.",
    "No bypass of compute_roll_package / pipeline for player actions.",
)

QA_HUMAN_STAGE_CHECKLIST = (
    "Intent: free-text command resolves or clean parser fallback with visible reason.",
    "Mechanics: roll outcome matches HUD / world_notes; no silent success on hard-fail gates.",
    "Narration: second person; no invented inventory/cash/trace changes.",
    "Flags: shadow-only mode logs LLM intent without changing mechanics.",
)

DEPENDENCY_FREEZE_POLICY = (
    "During critical release window: avoid cross-module interface changes in "
    "pipeline.py, action_intent.py, modifiers.py without integration regression run.",
)
