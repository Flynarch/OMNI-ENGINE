"""Export lightweight feature-gap hints from save JSON (roadmap: evolution pipeline stub).

Reads meta.telemetry_turn_last and recent world_notes markers. No network; no LLM.
Usage: python scripts/feature_gap_export.py [path/to/save.json]
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def main() -> int:
    from engine.core.state import CURRENT

    p = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else CURRENT
    if not p.exists():
        print(f"[gap] missing file: {p}", file=sys.stderr)
        return 1
    st = json.loads(p.read_text(encoding="utf-8"))
    meta = st.get("meta", {}) or {}
    tel = meta.get("telemetry_turn_last") if isinstance(meta.get("telemetry_turn_last"), dict) else {}
    notes = st.get("world_notes", []) or []
    tail = [str(x) for x in notes[-12:]] if isinstance(notes, list) else []
    out = {
        "source_file": str(p),
        "telemetry_turn_last": tel,
        "recent_notes": tail,
        "suggested_gaps": [],
    }
    if str(tel.get("fallback_reason", "") or "").strip():
        out["suggested_gaps"].append({"kind": "high_fallback", "detail": tel.get("fallback_reason")})
    if "[FFCI]" in " ".join(tail):
        out["suggested_gaps"].append({"kind": "ffci_markers", "detail": "review world_notes"})
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
