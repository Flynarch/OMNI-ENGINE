"""Where to insert ``from engine.core.error_taxonomy import log_swallowed_exception`` in a module."""

from __future__ import annotations


def compute_log_swallowed_import_insert_index(lines: list[str]) -> int:
    """Return a 0-based line index: insert the import *before* the line currently at that index."""
    if not lines:
        return 0
    i = 0
    if lines[0].startswith("#!"):
        i = 1
    if i < len(lines) and ("coding:" in lines[i] or "coding=" in lines[i]) and lines[i].lstrip().startswith("#"):
        i += 1

    future_idx: int | None = None
    for j in range(i, len(lines)):
        if lines[j].startswith("from __future__ import"):
            future_idx = j
            break
    if future_idx is not None:
        insert_at = future_idx + 1
        while insert_at < len(lines) and lines[insert_at].strip() == "":
            insert_at += 1
        return insert_at

    def _skip_module_docstring(start: int) -> int:
        if start >= len(lines):
            return start
        first = lines[start].lstrip()
        if not (first.startswith('"""') or first.startswith("'''")):
            return start
        quote = '"""' if first.startswith('"""') else "'''"
        if first.count(quote) >= 2 and first.rstrip().endswith(quote):
            return start + 1
        k = start + 1
        while k < len(lines):
            if quote in lines[k]:
                return k + 1
            k += 1
        return start

    i = _skip_module_docstring(i)
    while i < len(lines) and lines[i].strip() == "":
        i += 1
    return i
