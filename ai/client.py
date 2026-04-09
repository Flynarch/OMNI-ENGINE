from __future__ import annotations

import json
import os
import random
import time
from typing import Generator

import requests
from dotenv import load_dotenv
from requests.exceptions import ChunkedEncodingError, ConnectionError, Timeout

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"


def stream_response(system_prompt: str, turn_package: str) -> Generator[str, None, None]:
    load_dotenv()
    provider = os.getenv("LLM_PROVIDER", "openrouter").strip().lower()
    if provider in ("groq", "grok"):
        # "grok" typo → Groq (Llama 3.3 70B ada di Groq, bukan xAI Grok).
        api_key = os.getenv("GROQ_API_KEY", "").strip()
        if not api_key:
            raise RuntimeError("GROQ_API_KEY missing in .env (set LLM_PROVIDER=groq)")
        url = GROQ_URL
        model = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile").strip() or "llama-3.3-70b-versatile"
    else:
        api_key = os.getenv("OPENROUTER_API_KEY", "").strip()
        if not api_key:
            raise RuntimeError("OPENROUTER_API_KEY missing in .env")
        url = OPENROUTER_URL
        model = os.getenv("OPENROUTER_MODEL", "deepseek/deepseek-chat").strip() or "deepseek/deepseek-chat"

    _mt = os.getenv("LLM_MAX_TOKENS", "").strip()
    if _mt.isdigit():
        max_tokens = int(_mt)
    else:
        max_tokens = 4096 if provider in ("groq", "grok") else 2000

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": model,
        "max_tokens": max_tokens,
        "stream": True,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": turn_package},
        ],
    }
    _nr = os.getenv("LLM_HTTP_RETRIES", "").strip()
    max_retries = int(_nr) if _nr.isdigit() else 4
    max_retries = max(1, min(12, max_retries))
    response = None
    last_exc: Exception | None = None
    for attempt in range(max_retries):
        try:
            response = requests.post(
                url,
                headers=headers,
                json=payload,
                stream=True,
                timeout=120,
            )
            response.raise_for_status()
            last_exc = None
            break
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
    if response is None:
        raise RuntimeError(f"LLM request failed: {last_exc!r}")
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

