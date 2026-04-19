from __future__ import annotations

from engine.core.error_taxonomy import log_swallowed_exception
from typing import Any


def normalize_item_quantities(state: dict[str, Any], *, max_qty: int = 99999, drop_zeros: bool = True) -> None:
    inv = state.setdefault("inventory", {})
    if not isinstance(inv, dict):
        inv = {}
        state["inventory"] = inv
    iq = inv.setdefault("item_quantities", {})
    if not isinstance(iq, dict):
        iq = {}
        inv["item_quantities"] = iq

    out: dict[str, int] = {}
    for k, v in list(iq.items())[:400]:
        key = str(k or "").strip()
        if not key:
            continue
        try:
            n = int(v)
        except Exception as _omni_sw_23:
            log_swallowed_exception('engine/player/inventory_norm.py:23', _omni_sw_23)
            # Try string-to-int-ish; otherwise treat as 0.
            try:
                n = int(str(v).strip())
            except Exception as _omni_sw_27:
                log_swallowed_exception('engine/player/inventory_norm.py:27', _omni_sw_27)
                n = 0
        if n < 0:
            n = 0
        if n > int(max_qty):
            n = int(max_qty)
        if drop_zeros and n == 0:
            continue
        out[key] = n

    inv["item_quantities"] = out

