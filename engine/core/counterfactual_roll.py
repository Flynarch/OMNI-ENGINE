"""Internal counterfactual threshold sampling (debug / balancing evidence only)."""

from __future__ import annotations

from typing import Any, Dict, List, Tuple


def sample_threshold_outcomes(
    roll_value: int,
    thresholds: Tuple[int, ...],
) -> List[Dict[str, Any]]:
    """Given a fixed roll, report pass/fail vs alternate DC thresholds (no RNG)."""
    try:
        r = int(roll_value)
    except (TypeError, ValueError):
        return []
    out: List[Dict[str, Any]] = []
    for th in thresholds:
        try:
            t = int(th)
        except (TypeError, ValueError):
            continue
        out.append({"threshold": t, "would_pass": r >= t})
    return out
