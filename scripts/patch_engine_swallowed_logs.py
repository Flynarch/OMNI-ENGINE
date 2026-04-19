"""One-shot: inject log_swallowed_exception into ``except Exception`` handlers under engine/ and main.py.

Run from repo root:  python scripts/patch_engine_swallowed_logs.py
"""

from __future__ import annotations

import re
from pathlib import Path

from engine_import_placement import compute_log_swallowed_import_insert_index

ROOT = Path(__file__).resolve().parents[1]
IMPORT_LINE = "from engine.core.error_taxonomy import log_swallowed_exception\n"
SKIP_NAMES = frozenset({"patch_engine_swallowed_logs.py"})


def _insert_import(text: str) -> str:
    """Place the import after ``from __future__`` or after module preamble (see engine_import_placement)."""
    if "from engine.core.error_taxonomy import log_swallowed_exception" in text:
        return text
    lines = text.splitlines(keepends=True)
    if not lines:
        return IMPORT_LINE
    idx = compute_log_swallowed_import_insert_index(lines)
    lines.insert(idx, IMPORT_LINE)
    return "".join(lines)


def patch_file(path: Path) -> tuple[bool, str]:
    if path.name in SKIP_NAMES:
        return False, "skip"
    try:
        rel = path.relative_to(ROOT).as_posix()
    except ValueError:
        return False, "skip"
    if rel == "engine/core/error_taxonomy.py":
        return False, "skip self"
    text = path.read_text(encoding="utf-8")
    if "except Exception" not in text:
        return False, rel

    lines = text.splitlines(keepends=True)
    new_lines: list[str] = []
    i = 0
    changed = False
    bare = re.compile(r"^(\s*)except Exception\s*:\s*$")
    named = re.compile(r"^(\s*)except Exception\s+as\s+(\w+)\s*:\s*$")

    while i < len(lines):
        line = lines[i]
        m_b = bare.match(line)
        m_n = named.match(line)
        if not m_b and not m_n:
            new_lines.append(line)
            i += 1
            continue

        lineno = i + 1
        indent = (m_b or m_n).group(1)  # type: ignore[union-attr]
        if m_n:
            var = m_n.group(2)
            new_header = f"{indent}except Exception as {var}:\n"
        else:
            var = f"_omni_sw_{lineno}"
            new_header = f"{indent}except Exception as {var}:\n"

        if line != new_header:
            new_lines.append(new_header)
            changed = True
        else:
            new_lines.append(line)
        i += 1

        while i < len(lines) and lines[i].strip() == "":
            new_lines.append(lines[i])
            i += 1

        body_indent = len(indent) + 4
        ctx = f"{rel}:{lineno}"
        if not (i < len(lines) and "log_swallowed_exception(" in lines[i]):
            new_lines.append(" " * body_indent + f"log_swallowed_exception({ctx!r}, {var})\n")
            changed = True
        continue

    if not changed:
        return False, rel

    new_text = "".join(new_lines)
    if "log_swallowed_exception(" in new_text:
        new_text = _insert_import(new_text)
    path.write_text(new_text, encoding="utf-8")
    return True, rel


def main() -> int:
    targets = list((ROOT / "engine").rglob("*.py"))
    targets.append(ROOT / "main.py")
    n = 0
    for p in sorted(targets):
        if not p.is_file():
            continue
        ok, msg = patch_file(p)
        if ok:
            print("patched", msg)
            n += 1
    print("done, files changed:", n)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
