"""Black-market catalog tiers only — split from ``black_market`` to avoid import cycles with ``reputation_lanes``."""

from __future__ import annotations

# W2-2: minimum black-market standing tier (0..3) to see & buy listing.
ITEM_REPUTATION_TIER: dict[str, int] = {
    "lockpick": 0,
    "burner_phone": 0,
    "fake_id": 1,
    "police_scanner": 2,
    "cyberdeck_mk1": 2,
    "disguise_kit": 3,
}
