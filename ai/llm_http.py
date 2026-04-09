"""
Shared OpenAI-compatible chat completion HTTP layer (OpenRouter / Groq).

Narration (streaming) and intent (JSON) share the same endpoint resolution,
retries, and env knobs (LLM_HTTP_RETRIES).
"""

from __future__ import annotations

import os
import random
import time
from typing import Any

import requests
from dotenv import load_dotenv
from requests.exceptions import ChunkedEncodingError, ConnectionError, Timeout

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"


def resolve_backend() -> tuple[str, dict[str, str], str, str]:
    """Return (url, headers, model, provider_key). Raises if API key missing."""
    load_dotenv()
    provider = os.getenv("LLM_PROVIDER", "openrouter").strip().lower()
    if provider in ("groq", "grok"):
        api_key = os.getenv("GROQ_API_KEY", "").strip()
        if not api_key:
            raise RuntimeError("GROQ_API_KEY missing in .env (set LLM_PROVIDER=groq)")
        model = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile").strip() or "llama-3.3-70b-versatile"
        return GROQ_URL, {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}, model, provider
    api_key = os.getenv("OPENROUTER_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("OPENROUTER_API_KEY missing in .env")
    model = os.getenv("OPENROUTER_MODEL", "deepseek/deepseek-chat").strip() or "deepseek/deepseek-chat"
    return OPENROUTER_URL, {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}, model, provider


def _retry_count() -> int:
    _nr = os.getenv("LLM_HTTP_RETRIES", "").strip()
    n = int(_nr) if _nr.isdigit() else 4
    return max(1, min(12, n))


def default_narration_max_tokens() -> int:
    _mt = os.getenv("LLM_MAX_TOKENS", "").strip()
    if _mt.isdigit():
        return int(_mt)
    *_, provider = resolve_backend()
    return 4096 if provider in ("groq", "grok") else 2000


def post_chat_completion(
    *,
    messages: list[dict[str, Any]],
    max_tokens: int,
    stream: bool,
    timeout: float,
) -> requests.Response:
    url, headers, model, _prov = resolve_backend()
    payload: dict[str, Any] = {
        "model": model,
        "max_tokens": max_tokens,
        "stream": stream,
        "messages": messages,
    }
    max_retries = _retry_count()
    last_exc: Exception | None = None
    for attempt in range(max_retries):
        try:
            response = requests.post(url, headers=headers, json=payload, stream=stream, timeout=timeout)
            response.raise_for_status()
            return response
        except requests.HTTPError as e:
            last_exc = e
            code = e.response.status_code if e.response is not None else 0
            retryable = code in (408, 429, 500, 502, 503, 504)
            if retryable and attempt < max_retries - 1:
                delay = min(45.0, (2**attempt) * 0.35 + random.random() * 0.2)
                time.sleep(delay)
                continue
            raise RuntimeError(f"LLM HTTP {code}: {e}") from e
        except (ConnectionError, Timeout, ChunkedEncodingError) as e:
            last_exc = e
            if attempt < max_retries - 1:
                delay = min(45.0, (2**attempt) * 0.35 + random.random() * 0.2)
                time.sleep(delay)
                continue
            raise RuntimeError(f"LLM connection failed after {max_retries} attempts: {e}") from e
    raise RuntimeError(f"LLM request failed: {last_exc!r}")


def chat_completion_json(
    *,
    messages: list[dict[str, Any]],
    max_tokens: int,
    timeout: float = 60.0,
) -> dict[str, Any]:
    resp = post_chat_completion(messages=messages, max_tokens=max_tokens, stream=False, timeout=timeout)
    data = resp.json()
    if not isinstance(data, dict):
        raise RuntimeError("LLM returned non-object JSON")
    return data
