"""Emit integration health / capability snapshot JSON from a save (offline)."""

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
        print(f"missing {p}", file=sys.stderr)
        return 1
    st = json.loads(p.read_text(encoding="utf-8"))
    meta = st.get("meta", {}) or {}
    tel = meta.get("telemetry_turn_last") if isinstance(meta.get("telemetry_turn_last"), dict) else {}
    cap = meta.get("system_capability_index") if isinstance(meta.get("system_capability_index"), dict) else {}
    score = 1.0
    if str(tel.get("fallback_reason", "") or "").strip():
        score -= 0.05
    out = {
        "integration_health_score": round(max(0.0, min(1.0, score)), 3),
        "telemetry_turn_last": tel,
        "system_capability_index": cap,
        "journal_len": len(meta.get("state_change_journal", []) or []) if isinstance(meta.get("state_change_journal"), list) else 0,
    }
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
