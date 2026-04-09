from __future__ import annotations

import json
from typing import Generator

from ai.llm_http import OPENROUTER_URL, GROQ_URL, default_narration_max_tokens, post_chat_completion

# Re-export for callers that imported URLs from ai.client
__all__ = ["stream_response", "OPENROUTER_URL", "GROQ_URL"]


def stream_response(system_prompt: str, turn_package: str) -> Generator[str, None, None]:
    max_tokens = default_narration_max_tokens()
    response = post_chat_completion(
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": turn_package},
        ],
        max_tokens=max_tokens,
        stream=True,
        timeout=120,
    )
    for line in response.iter_lines():
        if line and line.startswith(b"data: "):
            data = line[6:]
            if data == b"[DONE]":
                break
            try:
                chunk = json.loads(data)
                delta = chunk["choices"][0]["delta"].get("content", "")
                if delta:
                    yield delta
            except Exception:
                continue
