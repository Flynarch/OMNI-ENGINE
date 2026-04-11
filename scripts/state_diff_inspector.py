"""Compare two save JSON files on bounded high-churn keys (internal tooling)."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

KEYS = ("trace", "economy", "meta", "world_notes", "reputation", "player")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("before")
    ap.add_argument("after")
    args = ap.parse_args()
    a = Path(args.before)
    b = Path(args.after)
    if not a.exists() or not b.exists():
        print("missing file", file=sys.stderr)
        return 1
    sa = json.loads(a.read_text(encoding="utf-8"))
    sb = json.loads(b.read_text(encoding="utf-8"))
    out: dict[str, object] = {}
    for k in KEYS:
        if sa.get(k) != sb.get(k):
            out[k] = {"before": sa.get(k), "after": sb.get(k)}
    print(json.dumps({"diff_keys": list(out.keys()), "detail": out}, ensure_ascii=False, indent=2)[:12000])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
