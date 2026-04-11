"""Stub evolution pipeline step: read feature_gap_export shape, emit placeholder proposal JSON."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    save = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else ROOT / "save" / "current.json"
    r = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "feature_gap_export.py"), str(save)],
        capture_output=True,
        text=True,
        cwd=str(ROOT),
    )
    if r.returncode != 0:
        print(r.stderr, file=sys.stderr)
        return r.returncode
    gap = json.loads(r.stdout)
    gaps = gap.get("suggested_gaps") or []
    proposal = {
        "title": "auto_gap_batch",
        "priority": sum(3 for g in gaps if isinstance(g, dict)),
        "gaps": gaps,
        "next_human_steps": ["review", "branch", "implement", "python scripts/verify.py"],
    }
    print(json.dumps(proposal, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
