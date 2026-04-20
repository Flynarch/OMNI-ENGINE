"""
Shared OpenAI-compatible chat completion HTTP layer (OpenRouter / Groq).

Uses httpx AsyncClient for non-blocking I/O under asyncio. Sync helpers use
``asyncio.run`` for call sites that are still synchronous (CLI / pipeline).
"""

from __future__ import annotations

import asyncio
import json
import os
import random
from collections.abc import AsyncIterator, Iterator
from typing import Any

import httpx
from dotenv import load_dotenv

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
OLLAMA_DEFAULT_URL = "http://localhost:11434/api/generate"
GEMINI_BASE = "https://generativelanguage.googleapis.com/v1beta/models"

_LOCAL_FALLBACK_ACTIVE = False
_LOCAL_FALLBACK_NOTICE: str | None = None


def resolve_backend() -> tuple[str, dict[str, str], str, str]:
    """Return (url, headers, model, provider_key). Raises if API key missing."""
    load_dotenv()
    provider = os.getenv("LLM_PROVIDER", "openrouter").strip().lower()
    if provider == "gemini":
        api_key = os.getenv("GEMINI_API_KEY", "").strip()
        if not api_key:
            raise RuntimeError("GEMINI_API_KEY missing in .env (set LLM_PROVIDER=gemini)")
        model = os.getenv("GEMINI_MODEL", "gemini-2.0-flash").strip() or "gemini-2.0-flash"
        url = f"{GEMINI_BASE}/{model}:generateContent?key={api_key}"
        return url, {"Content-Type": "application/json"}, model, provider
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


def _httpx_timeout(*, stream: bool, timeout_sec: float) -> httpx.Timeout:
    """Bounded timeouts; read timeout covers inter-chunk gaps for SSE."""
    read = float(timeout_sec) if stream else float(timeout_sec)
    return httpx.Timeout(connect=30.0, read=read, write=60.0, pool=30.0)


async def _async_retry_delay(attempt: int) -> None:
    delay = min(45.0, (2**attempt) * 0.35 + random.random() * 0.2)
    await asyncio.sleep(delay)


def _http_retryable(code: int) -> bool:
    return code in (408, 429, 500, 502, 503, 504)


def _local_fallback_enabled() -> bool:
    v = os.getenv("LLM_LOCAL_FALLBACK_ENABLED", "1").strip().lower()
    return v not in ("0", "false", "no", "off")


def _local_fallback_after_attempts() -> int:
    # "after 2 retries" default
    raw = os.getenv("LLM_LOCAL_FALLBACK_AFTER_RETRIES", "").strip()
    n = int(raw) if raw.isdigit() else 2
    return max(1, min(6, n))


def _local_ollama_url() -> str:
    return os.getenv("LLM_LOCAL_BASE_URL", OLLAMA_DEFAULT_URL).strip() or OLLAMA_DEFAULT_URL


def _local_ollama_model() -> str:
    return os.getenv("LLM_LOCAL_MODEL", "llama3.2:3b").strip() or "llama3.2:3b"


def _gemini_model_for(purpose: str) -> str:
    purpose_key = "GEMINI_INTENT_MODEL" if purpose == "intent" else "GEMINI_NARRATOR_MODEL"
    return (
        os.getenv(purpose_key, "").strip()
        or os.getenv("GEMINI_MODEL", "gemini-2.0-flash").strip()
        or "gemini-2.0-flash"
    )


def _mark_local_fallback(reason: str) -> None:
    global _LOCAL_FALLBACK_ACTIVE, _LOCAL_FALLBACK_NOTICE
    _LOCAL_FALLBACK_ACTIVE = True
    _LOCAL_FALLBACK_NOTICE = f"Beralih ke Local AI Network ({reason})"


def _mark_primary_backend_active() -> None:
    global _LOCAL_FALLBACK_ACTIVE
    _LOCAL_FALLBACK_ACTIVE = False


def consume_local_fallback_notice() -> str:
    global _LOCAL_FALLBACK_NOTICE
    msg = str(_LOCAL_FALLBACK_NOTICE or "").strip()
    _LOCAL_FALLBACK_NOTICE = None
    return msg


def is_local_fallback_active() -> bool:
    return bool(_LOCAL_FALLBACK_ACTIVE)


def _messages_to_prompt(messages: list[dict[str, Any]]) -> str:
    parts: list[str] = []
    for m in messages[:24]:
        if not isinstance(m, dict):
            continue
        role = str(m.get("role", "user") or "user").strip().upper()
        content = str(m.get("content", "") or "")
        if content:
            parts.append(f"{role}:\n{content}")
    return "\n\n".join(parts).strip()


def _messages_to_gemini_payload(messages: list[dict[str, Any]], *, max_tokens: int) -> dict[str, Any]:
    sys_parts: list[str] = []
    contents: list[dict[str, Any]] = []
    for m in messages[:32]:
        if not isinstance(m, dict):
            continue
        role = str(m.get("role", "user") or "user").strip().lower()
        content = str(m.get("content", "") or "")
        if not content:
            continue
        if role == "system":
            sys_parts.append(content)
            continue
        gem_role = "model" if role == "assistant" else "user"
        contents.append({"role": gem_role, "parts": [{"text": content}]})
    if not contents:
        contents = [{"role": "user", "parts": [{"text": ""}]}]
    payload: dict[str, Any] = {
        "contents": contents,
        "generationConfig": {"maxOutputTokens": int(max_tokens)},
    }
    if sys_parts:
        payload["systemInstruction"] = {"parts": [{"text": "\n\n".join(sys_parts)}]}
    return payload


def _extract_gemini_text_from_obj(obj: dict[str, Any]) -> str:
    if not isinstance(obj, dict):
        return ""
    cands = obj.get("candidates")
    if not isinstance(cands, list) or not cands:
        return ""
    c0 = cands[0] if isinstance(cands[0], dict) else {}
    if not isinstance(c0, dict):
        return ""
    content = c0.get("content") if isinstance(c0.get("content"), dict) else {}
    parts = content.get("parts") if isinstance(content.get("parts"), list) else []
    out: list[str] = []
    for p in parts:
        if not isinstance(p, dict):
            continue
        txt = str(p.get("text", "") or "")
        if txt:
            out.append(txt)
    return "".join(out)


def _wrap_text_as_openai_completion(*, text: str, model: str) -> dict[str, Any]:
    return {
        "id": "gemini-bridge",
        "object": "chat.completion",
        "model": model,
        "choices": [{"index": 0, "message": {"role": "assistant", "content": str(text or "")}, "finish_reason": "stop"}],
    }


def _extract_sse_delta(line: str) -> tuple[str, bool]:
    """Parse OpenAI-compatible SSE line into (delta, done)."""
    ln = str(line or "").strip()
    if not ln.startswith("data:"):
        return "", False
    data = ln[5:].strip()
    if data == "[DONE]":
        return "", True
    try:
        chunk = json.loads(data)
        choice0 = (chunk.get("choices", [{}]) or [{}])[0] if isinstance(chunk.get("choices"), list) else {}
        if not isinstance(choice0, dict):
            choice0 = {}
        delta_obj = choice0.get("delta") if isinstance(choice0.get("delta"), dict) else {}
        delta = delta_obj.get("content", "")
        if isinstance(delta, list):
            buf: list[str] = []
            for part in delta:
                if isinstance(part, dict):
                    txt = str(part.get("text", "") or "")
                    if txt:
                        buf.append(txt)
                elif isinstance(part, str):
                    buf.append(part)
            delta = "".join(buf)
        if not delta:
            # Some providers stream under `text` or send full `message` in a non-standard SSE chunk.
            delta = choice0.get("text", "")
            if not delta and isinstance(choice0.get("message"), dict):
                delta = str((choice0.get("message") or {}).get("content", "") or "")
        return str(delta or ""), False
    except Exception:
        return "", False


def _extract_text_from_completion(data: dict[str, Any]) -> str:
    if not isinstance(data, dict):
        return ""
    ch = data.get("choices")
    if isinstance(ch, list) and ch:
        c0 = ch[0] if isinstance(ch[0], dict) else {}
        if isinstance(c0, dict):
            msg = c0.get("message")
            if isinstance(msg, dict):
                txt = str(msg.get("content", "") or "")
                if txt.strip():
                    return txt
            txt2 = str(c0.get("text", "") or "")
            if txt2.strip():
                return txt2
    return ""


async def _async_ollama_generate_nonstream(
    *,
    messages: list[dict[str, Any]],
    max_tokens: int,
    timeout: float,
) -> dict[str, Any]:
    url = _local_ollama_url()
    model = _local_ollama_model()
    payload = {
        "model": model,
        "prompt": _messages_to_prompt(messages),
        "stream": False,
        "options": {"num_predict": int(max_tokens)},
    }
    timeout_cfg = _httpx_timeout(stream=False, timeout_sec=timeout)
    async with httpx.AsyncClient(timeout=timeout_cfg) as client:
        resp = await client.post(url, json=payload)
        resp.raise_for_status()
        data = resp.json()
    txt = str(data.get("response", "") or "")
    return {
        "id": "local-ollama",
        "object": "chat.completion",
        "model": model,
        "choices": [{"index": 0, "message": {"role": "assistant", "content": txt}, "finish_reason": "stop"}],
    }


async def _aiter_ollama_stream(
    *,
    messages: list[dict[str, Any]],
    max_tokens: int,
    timeout: float,
) -> AsyncIterator[str]:
    url = _local_ollama_url()
    model = _local_ollama_model()
    payload = {
        "model": model,
        "prompt": _messages_to_prompt(messages),
        "stream": True,
        "options": {"num_predict": int(max_tokens)},
    }
    timeout_cfg = _httpx_timeout(stream=True, timeout_sec=timeout)
    yielded = False
    async with httpx.AsyncClient(timeout=timeout_cfg) as client:
        async with client.stream("POST", url, json=payload) as response:
            response.raise_for_status()
            async for line in response.aiter_lines():
                ln = str(line or "").strip()
                if not ln:
                    continue
                try:
                    obj = json.loads(ln)
                except Exception:
                    continue
                delta = str(obj.get("response", "") or "")
                if delta:
                    yielded = True
                    yield delta
                if bool(obj.get("done", False)):
                    if not yielded:
                        raise RuntimeError("Local LLM stream returned no content chunks")
                    return
    if not yielded:
        raise RuntimeError("Local LLM stream ended without content")


async def async_chat_completion_json(
    *,
    messages: list[dict[str, Any]],
    max_tokens: int,
    timeout: float = 60.0,
) -> dict[str, Any]:
    """Non-streaming JSON chat completion (intent resolver, tools)."""
    url, headers, model, _prov = resolve_backend()
    if _prov == "gemini":
        model = _gemini_model_for("intent")
        api_key = os.getenv("GEMINI_API_KEY", "").strip()
        url = f"{GEMINI_BASE}/{model}:generateContent?key={api_key}"
        payload = _messages_to_gemini_payload(messages, max_tokens=max_tokens)
    else:
        payload = {
            "model": model,
            "max_tokens": max_tokens,
            "stream": False,
            "messages": messages,
        }
    max_retries = _retry_count()
    fallback_after = _local_fallback_after_attempts()
    timeout_cfg = _httpx_timeout(stream=False, timeout_sec=timeout)
    last_exc: BaseException | None = None
    async with httpx.AsyncClient(timeout=timeout_cfg) as client:
        for attempt in range(max_retries):
            try:
                resp = await client.post(url, headers=headers, json=payload)
                resp.raise_for_status()
                data = resp.json()
                if not isinstance(data, dict):
                    raise RuntimeError("LLM returned non-object JSON")
                if _prov == "gemini":
                    txt = _extract_gemini_text_from_obj(data)
                    data = _wrap_text_as_openai_completion(text=txt, model=model)
                _mark_primary_backend_active()
                return data
            except httpx.HTTPStatusError as e:
                last_exc = e
                code = e.response.status_code if e.response is not None else 0
                if _local_fallback_enabled() and code == 503 and attempt >= fallback_after - 1:
                    _mark_local_fallback("external 503")
                    return await _async_ollama_generate_nonstream(messages=messages, max_tokens=max_tokens, timeout=timeout)
                if _http_retryable(code) and attempt < max_retries - 1:
                    await _async_retry_delay(attempt)
                    continue
                raise RuntimeError(f"LLM HTTP {code}: {e}") from e
            except (httpx.ConnectError, httpx.ReadTimeout, httpx.WriteTimeout, httpx.RemoteProtocolError) as e:
                last_exc = e
                if _local_fallback_enabled() and attempt >= fallback_after - 1:
                    _mark_local_fallback("external timeout")
                    return await _async_ollama_generate_nonstream(messages=messages, max_tokens=max_tokens, timeout=timeout)
                if attempt < max_retries - 1:
                    await _async_retry_delay(attempt)
                    continue
                raise RuntimeError(f"LLM connection failed after {max_retries} attempts: {e}") from e
    raise RuntimeError(f"LLM request failed: {last_exc!r}")


def chat_completion_json(
    *,
    messages: list[dict[str, Any]],
    max_tokens: int,
    timeout: float = 60.0,
) -> dict[str, Any]:
    """Sync wrapper for parser / pipeline code paths without an event loop."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(async_chat_completion_json(messages=messages, max_tokens=max_tokens, timeout=timeout))
    raise RuntimeError(
        "chat_completion_json() cannot be used inside a running event loop; await async_chat_completion_json() instead."
    )


async def aiter_sse_narration_chunks(
    *,
    messages: list[dict[str, Any]],
    max_tokens: int,
    timeout: float = 120.0,
) -> AsyncIterator[str]:
    """Async generator: yield text deltas from an OpenAI-compatible SSE stream."""
    url, headers, model, _prov = resolve_backend()
    payload: dict[str, Any] = {
        "model": model,
        "max_tokens": max_tokens,
        "stream": True,
        "messages": messages,
    }
    if _prov == "gemini":
        model = _gemini_model_for("narration")
        api_key = os.getenv("GEMINI_API_KEY", "").strip()
        url = f"{GEMINI_BASE}/{model}:streamGenerateContent?alt=sse&key={api_key}"
        payload = _messages_to_gemini_payload(messages, max_tokens=max_tokens)
    max_retries = _retry_count()
    fallback_after = _local_fallback_after_attempts()
    timeout_cfg = _httpx_timeout(stream=True, timeout_sec=timeout)
    last_exc: BaseException | None = None
    for attempt in range(max_retries):
        try:
            yielded = False
            async with httpx.AsyncClient(timeout=timeout_cfg) as client:
                async with client.stream("POST", url, headers=headers, json=payload) as response:
                    response.raise_for_status()
                    last_full = ""
                    async for line in response.aiter_lines():
                        if _prov == "gemini":
                            ln = str(line or "").strip()
                            if not ln.startswith("data:"):
                                continue
                            raw = ln[5:].strip()
                            if not raw:
                                continue
                            try:
                                chunk_obj = json.loads(raw)
                            except Exception:
                                continue
                            full_txt = _extract_gemini_text_from_obj(chunk_obj)
                            if full_txt and full_txt.startswith(last_full):
                                delta = full_txt[len(last_full):]
                                last_full = full_txt
                            else:
                                delta = full_txt
                                if full_txt:
                                    last_full = full_txt
                            done = False
                        else:
                            delta, done = _extract_sse_delta(str(line or ""))
                        if delta:
                            yielded = True
                            yield str(delta)
                        if done:
                            if not yielded:
                                raise RuntimeError("LLM stream completed without any content chunk")
                            _mark_primary_backend_active()
                            return
            if yielded:
                _mark_primary_backend_active()
                return
            raise RuntimeError("LLM stream ended without any content chunk")
        except httpx.HTTPStatusError as e:
            last_exc = e
            code = e.response.status_code if e.response is not None else 0
            if _local_fallback_enabled() and code == 503 and attempt >= fallback_after - 1:
                _mark_local_fallback("external 503")
                async for ch in _aiter_ollama_stream(messages=messages, max_tokens=max_tokens, timeout=timeout):
                    yield ch
                return
            if _http_retryable(code) and attempt < max_retries - 1:
                await _async_retry_delay(attempt)
                continue
            raise RuntimeError(f"LLM HTTP {code}: {e}") from e
        except RuntimeError as e:
            last_exc = e
            # SSE transport can fail while provider non-stream still works.
            try:
                data = await async_chat_completion_json(messages=messages, max_tokens=max_tokens, timeout=max(60.0, float(timeout)))
                txt = _extract_text_from_completion(data)
                if txt.strip():
                    _mark_primary_backend_active()
                    yield txt
                    return
            except Exception as _nonstream_exc:
                last_exc = _nonstream_exc
            if _local_fallback_enabled() and attempt >= fallback_after - 1:
                _mark_local_fallback("external empty-stream")
                async for ch in _aiter_ollama_stream(messages=messages, max_tokens=max_tokens, timeout=timeout):
                    yield ch
                return
            if attempt < max_retries - 1:
                await _async_retry_delay(attempt)
                continue
            raise
        except (httpx.ConnectError, httpx.ReadTimeout, httpx.WriteTimeout, httpx.RemoteProtocolError) as e:
            last_exc = e
            if _local_fallback_enabled() and attempt >= fallback_after - 1:
                _mark_local_fallback("external timeout")
                async for ch in _aiter_ollama_stream(messages=messages, max_tokens=max_tokens, timeout=timeout):
                    yield ch
                return
            if attempt < max_retries - 1:
                await _async_retry_delay(attempt)
                continue
            raise RuntimeError(f"LLM connection failed after {max_retries} attempts: {e}") from e
    raise RuntimeError(f"LLM stream failed: {last_exc!r}")


def iter_sse_narration_chunks_sync(
    *,
    messages: list[dict[str, Any]],
    max_tokens: int,
    timeout: float = 120.0,
) -> Iterator[str]:
    """
    Drive ``aiter_sse_narration_chunks`` from synchronous code (e.g. Rich CLI).

    Uses a dedicated event loop for the lifetime of this iterator so network
    waits are ``await``-based (async I/O) without blocking other coroutines on
    a shared loop; the game loop stays sequential and does not touch ``state``
    until each chunk is yielded.
    """
    try:
        asyncio.get_running_loop()
        raise RuntimeError(
            "iter_sse_narration_chunks_sync() cannot be used inside a running event loop; use aiter_sse_narration_chunks() instead."
        )
    except RuntimeError as e:
        # get_running_loop() raises RuntimeError when no loop is running: that's our normal sync case.
        if "cannot be used inside a running event loop" in str(e):
            raise

    agen = aiter_sse_narration_chunks(messages=messages, max_tokens=max_tokens, timeout=timeout)
    ait = agen.__aiter__()
    loop = asyncio.new_event_loop()
    prev_loop: asyncio.AbstractEventLoop | None = None
    had_prev = False
    try:
        try:
            prev_loop = asyncio.get_event_loop()
            had_prev = True
        except Exception:
            prev_loop = None
            had_prev = False
        asyncio.set_event_loop(loop)
        while True:
            try:
                chunk = loop.run_until_complete(ait.__anext__())
                yield chunk
            except StopAsyncIteration:
                break
    finally:
        try:
            loop.run_until_complete(agen.aclose())
        except (RuntimeError, GeneratorExit, Exception):
            pass
        try:
            loop.close()
        except Exception:
            pass
        try:
            asyncio.set_event_loop(prev_loop if had_prev else None)
        except Exception:
            pass
