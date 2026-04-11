"""Minimal scenario fingerprint harness (extend with canonical streams per release)."""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _fp(obj: object) -> str:
    raw = json.dumps(obj, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(raw.encode("utf-8", errors="ignore")).hexdigest()[:16]


def main() -> int:
    from engine.core.state import initialize_state

    ch: dict = {"name": "Bench", "location": "london"}
    s1 = initialize_state(ch, "default")
    s2 = initialize_state(dict(ch), "default")
    assert _fp(s1) == _fp(s2), "fresh init should match for same seed name"
    print(f"[scenario_benchmark] init_fp={_fp(s1)} OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
