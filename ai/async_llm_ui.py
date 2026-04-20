"""Async LLM streaming helpers: heartbeat while waiting on the network (same event loop)."""

from __future__ import annotations

import asyncio
import contextlib
import os

from ai.client import stream_response_async
from ai.parser import filter_narration_for_player_display


def _heartbeat_enabled() -> bool:
    return os.getenv("OMNI_LLM_HEARTBEAT", "1").strip().lower() not in ("0", "false", "no", "off")


async def run_narration_stream_with_heartbeat(
    system_prompt: str,
    package: str,
    *,
    console,
    stream_render,
    label: str = "Menghubungkan",
) -> str:
    """Stream narration chunks; show a spinner on the same line until the first token arrives."""
    parts: list[str] = []
    stop = asyncio.Event()

    async def _spin() -> None:
        chars = "|/-\\"
        i = 0
        while not stop.is_set():
            console.print(f"[dim]{chars[i % 4]} {label}…[/dim]", end="\r")
            i += 1
            await asyncio.sleep(0.12)
        console.print(" " * 56, end="\r")

    hb: asyncio.Task[None] | None = None
    if _heartbeat_enabled():
        hb = asyncio.create_task(_spin())
    _ = stream_render  # Kept for API compat; output is one filtered print (no incremental XML leak).
    try:
        async for chunk in stream_response_async(system_prompt, package):
            if hb is not None and not stop.is_set():
                stop.set()
                hb.cancel()
                with contextlib.suppress(asyncio.CancelledError, Exception):
                    await hb
                hb = None
            parts.append(chunk)
        full = "".join(parts)
        # Do not stream raw chunks: internal XML sections must not leak to the player console.
        display = filter_narration_for_player_display(full)
        if display:
            console.print(display)
        console.print()
    finally:
        stop.set()
        if hb is not None:
            hb.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await hb
    return "".join(parts)


async def await_with_heartbeat(coro, *, label: str = "Intent"):
    """Await a coroutine while showing a spinner (same event loop)."""
    from display.renderer import console

    stop = asyncio.Event()

    async def _spin() -> None:
        if not _heartbeat_enabled():
            return
        chars = "|/-\\"
        i = 0
        while not stop.is_set():
            console.print(f"[dim]{chars[i % 4]} {label}…[/dim]", end="\r")
            i += 1
            await asyncio.sleep(0.12)
        console.print(" " * 44, end="\r")

    t = asyncio.create_task(_spin())
    try:
        return await coro
    finally:
        stop.set()
        t.cancel()
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await t
