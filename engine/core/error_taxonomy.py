"""Structured error / reason codes plus centralized file logging for swallowed exceptions.

Use :func:`log_swallowed_exception` from ``except Exception`` handlers so failures are recorded
with full traceback in ``logs/engine_errors.log`` without stopping the game.
"""

from __future__ import annotations

import logging
import os
import sys
import threading
import traceback
from pathlib import Path
from typing import Any

# --- String codes (integration / diagnostics) ---------------------------------
INTENT_INVALID = "INTENT_INVALID"
GATE_BLOCKED = "GATE_BLOCKED"
ROLL_ABORTED = "ROLL_ABORTED"
PARSER_FALLBACK = "PARSER_FALLBACK"
ABUSE_GUARD = "ABUSE_GUARD"
SECURITY_BLOCKED = "SECURITY_BLOCKED"
RECONCILER_WARN = "RECONCILER_WARN"

# --- File logging (swallowed exceptions) --------------------------------------
_LOCK = threading.RLock()
_LOGGER: logging.Logger | None = None
_CONFIGURED = False

_LOG_ENV_DISABLE = "OMNI_ENGINE_ERROR_LOG_DISABLE"
_LOG_ENV_PATH = "OMNI_ENGINE_ERROR_LOG_PATH"


def _default_log_file() -> Path:
    root = Path(__file__).resolve().parents[2]
    log_dir = root / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    return log_dir / "engine_errors.log"


def _ensure_swallow_logger() -> logging.Logger:
    """Configure a dedicated logger once (thread-safe)."""
    global _CONFIGURED, _LOGGER
    with _LOCK:
        if _CONFIGURED and _LOGGER is not None:
            return _LOGGER
        name = "omni_engine.swallowed_exceptions"
        log = logging.getLogger(name)
        log.handlers.clear()
        log.setLevel(logging.ERROR)
        log.propagate = False
        if os.getenv(_LOG_ENV_DISABLE, "").strip().lower() in ("1", "true", "yes", "on"):
            _CONFIGURED = True
            _LOGGER = log
            return log
        path = os.getenv(_LOG_ENV_PATH, "").strip()
        log_path = Path(path) if path else _default_log_file()
        try:
            log_path.parent.mkdir(parents=True, exist_ok=True)
            fh = logging.FileHandler(log_path, encoding="utf-8", delay=True)
            fh.setLevel(logging.ERROR)
            fh.setFormatter(
                logging.Formatter(
                    fmt="%(asctime)s | %(levelname)s | %(message)s",
                    datefmt="%Y-%m-%d %H:%M:%S",
                )
            )
            log.addHandler(fh)
        except OSError:
            # Fallback: still avoid crashing callers.
            sh = logging.StreamHandler(sys.stderr)
            sh.setLevel(logging.ERROR)
            sh.setFormatter(logging.Formatter("%(levelname)s | %(message)s"))
            log.addHandler(sh)
        _CONFIGURED = True
        _LOGGER = log
        return log


def log_swallowed_exception(context: str, exc: BaseException | None = None) -> None:
    """Append a full traceback for a non-fatal path to ``logs/engine_errors.log``.

    * ``context``: stable label, e.g. ``"engine/core/state.py:215"`` or ``"main.handle_special"``.
    * ``exc``: exception instance from ``except Exception as exc`` (preferred). If omitted,
      uses :func:`traceback.format_exc` (only valid inside an active ``except`` block).

    Never raises to callers.
    """
    ctx = str(context or "unknown").strip() or "unknown"
    try:
        log = _ensure_swallow_logger()
        if not log.handlers:
            return
        if exc is not None:
            tb = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
            log.error("%s\n%s", ctx, tb.rstrip())
        else:
            tb = traceback.format_exc()
            if tb and tb.strip() != "NoneType: None\n":
                log.error("%s\n%s", ctx, tb.rstrip())
            else:
                log.error("%s\n(no active exception traceback)", ctx)
    except Exception:
        try:
            sys.stderr.write(f"[omni_engine] log_swallowed_exception failed: {ctx!r}\n")
        except Exception:
            pass


def log_swallowed_exception_extra(context: str, exc: BaseException | None, **fields: Any) -> None:
    """Like :func:`log_swallowed_exception` with a short extra field line (values stringified, truncated)."""
    bits = [f"{k}={repr(v)[:200]}" for k, v in sorted(fields.items())]
    suffix = (" | " + " ".join(bits)) if bits else ""
    log_swallowed_exception(str(context) + suffix, exc)
