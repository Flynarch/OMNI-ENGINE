from __future__ import annotations

from collections.abc import AsyncIterator, Iterator

from ai.llm_http import (
    OPENROUTER_URL,
    GROQ_URL,
    aiter_sse_narration_chunks,
    consume_local_fallback_notice,
    default_narration_max_tokens,
    is_local_fallback_active,
    iter_sse_narration_chunks_sync,
)

# Re-export for callers that imported URLs from ai.client
__all__ = [
    "stream_response",
    "stream_response_async",
    "OPENROUTER_URL",
    "GROQ_URL",
    "consume_local_fallback_notice",
    "is_local_fallback_active",
]


def stream_response(system_prompt: str, turn_package: str) -> Iterator[str]:
    """Sync iterator over narration chunks (async httpx SSE under the hood)."""
    max_tokens = default_narration_max_tokens()
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": turn_package},
    ]
    yield from iter_sse_narration_chunks_sync(messages=messages, max_tokens=max_tokens, timeout=120.0)


async def stream_response_async(system_prompt: str, turn_package: str) -> AsyncIterator[str]:
    """Async narration stream for callers that already run on an event loop."""
    max_tokens = default_narration_max_tokens()
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": turn_package},
    ]
    async for chunk in aiter_sse_narration_chunks(messages=messages, max_tokens=max_tokens, timeout=120.0):
        yield chunk
