"""Swappable LLM backends for the unified extract harness.

Primary adapter: ``OpenAICompatibleClient`` — any OpenAI Chat Completions
endpoint (Ollama on AGX Orin, vLLM, OpenRouter, LM Studio, …).

Factory: ``make_backend(name)`` picks a preset from env:
  orin / ollama / openai  → OLLAMA_HOST (default http://127.0.0.1:11434)
  openrouter / free       → OpenRouter + OPENROUTER_API_KEY
"""

from __future__ import annotations

import os
import re
import time
from pathlib import Path
from typing import Any, Protocol


def load_dotenv(path: Path | None = None) -> None:
    """Lightweight .env loader (no dependency). Does not override existing env."""
    p = path or Path(__file__).resolve().parents[2] / ".env"
    if not p.exists():
        return
    for line in p.read_text(encoding="utf-8").splitlines():
        s = line.strip()
        if not s or s.startswith("#") or "=" not in s:
            continue
        k, v = s.split("=", 1)
        k = k.strip().removeprefix("export ").strip()
        v = v.strip().strip("\"'").strip()
        os.environ.setdefault(k, v)


def _normalize_v1_base(url: str) -> str:
    host = (url or "").strip().rstrip("/")
    if not host:
        host = "http://127.0.0.1:11434"
    return host if host.endswith("/v1") else f"{host}/v1"


def _message_content(msg: dict[str, Any]) -> str:
    """Assistant ``content`` only (do not fall back to reasoning)."""
    return str(msg.get("content") or "").strip()


def _extract_json_blob(text: str) -> str:
    """Return raw text, or the first {...} object if buried in prose/reasoning."""
    s = (text or "").strip()
    if not s:
        return ""
    # Strip ```json ... ``` fences (Gemma often wraps even when asked not to)
    fence = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", s, flags=re.I)
    if fence:
        s = fence.group(1).strip()
    if s.startswith("{") and s.endswith("}"):
        return s
    m = re.search(r"\{[\s\S]*\}", s)
    return m.group(0) if m else s


class ChatBackend(Protocol):
    def chat_json(self, *, system: str, user: str, model: str) -> str: ...


class OpenAICompatibleClient:
    """Reusable OpenAI-compatible Chat Completions client.

    Swap models by changing ``model=`` at call time; swap hosts by
    constructing with a different ``base_url`` / env ``OLLAMA_HOST`` /
    ``OPENAI_BASE_URL``.
    """

    def __init__(
        self,
        base_url: str | None = None,
        *,
        api_key: str | None = None,
        timeout: float = 300.0,
        max_retries: int = 3,
        max_tokens: int = 800,
        default_headers: dict[str, str] | None = None,
        json_response_format: bool = True,
        disable_thinking: bool = False,
    ) -> None:
        load_dotenv()
        raw = (
            base_url
            or os.environ.get("OPENAI_BASE_URL")
            or os.environ.get("OLLAMA_HOST")
            or "http://127.0.0.1:11434"
        )
        self.base_url = _normalize_v1_base(raw)
        self.api_key = (
            api_key
            or os.environ.get("OPENAI_API_KEY")
            or os.environ.get("OLLAMA_API_KEY")
            or "ollama"
        )
        self.timeout = timeout
        self.max_retries = max_retries
        self.max_tokens = max_tokens
        self.default_headers = default_headers or {}
        self.json_response_format = json_response_format
        self.disable_thinking = disable_thinking

    def chat(
        self,
        *,
        model: str,
        messages: list[dict[str, str]],
        temperature: float = 0.0,
        max_tokens: int | None = None,
        extra_body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Raw chat.completions POST; returns parsed JSON response body."""
        import requests

        url = f"{self.base_url}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            **self.default_headers,
        }
        body: dict[str, Any] = {
            "model": model,
            "temperature": temperature,
            "max_tokens": max_tokens if max_tokens is not None else self.max_tokens,
            "messages": messages,
        }
        if extra_body:
            body.update(extra_body)
        # 1 attempt + up to max_retries retries on transport / 5xx / 429
        attempts = max(1, int(self.max_retries) + 1)
        last_err: Exception | None = None
        for attempt in range(attempts):
            try:
                r = requests.post(url, headers=headers, json=body, timeout=self.timeout)
                if r.status_code == 429 or r.status_code >= 500:
                    wait = min(30.0, 1.0 * (2.0**attempt))
                    last_err = RuntimeError(f"HTTP {r.status_code}: {r.text[:240]}")
                    time.sleep(wait)
                    continue
                if r.status_code >= 400:
                    # Non-retryable client errors (except transient 429 handled above)
                    raise RuntimeError(f"HTTP {r.status_code}: {r.text[:400]}")
                return r.json()
            except (requests.exceptions.Timeout, requests.exceptions.ConnectionError) as e:
                last_err = e
                time.sleep(min(30.0, 1.0 * (2.0**attempt)))
            except RuntimeError as e:
                if str(e).startswith("HTTP 4") and "HTTP 429" not in str(e):
                    raise
                last_err = e
                time.sleep(min(30.0, 1.0 * (2.0**attempt)))
            except Exception as e:  # noqa: BLE001
                last_err = e
                time.sleep(min(30.0, 1.0 * (2.0**attempt)))
        raise RuntimeError(f"OpenAI-compatible chat failed after retries: {last_err}")

    def chat_json(self, *, system: str, user: str, model: str) -> str:
        """Chat and return assistant text suitable for JSON parsing."""
        sys = system
        extra: dict[str, Any] = {}
        mlow = model.lower()
        # Ollama /v1 ignores ``think``; use OpenAI-style reasoning_effort.
        if "gemma" in mlow or "qwen3" in mlow or self.disable_thinking:
            extra["reasoning_effort"] = "none"
        if "gemma" in mlow:
            sys = (
                system
                + " Reply with a single JSON object in the message content only — "
                "no markdown fences, no preamble."
            )
        elif self.json_response_format:
            extra["response_format"] = {"type": "json_object"}

        last_empty: str | None = None
        # Empty content: one extra attempt (thinking models sometimes dump into reasoning)
        for empty_try in range(2):
            data = self.chat(
                model=model,
                messages=[
                    {"role": "system", "content": sys},
                    {"role": "user", "content": user},
                ],
                extra_body=extra or None,
            )
            choice = (data.get("choices") or [{}])[0]
            msg = choice.get("message") or {}
            if not isinstance(msg, dict):
                msg = {}
            content = _message_content(msg)
            if content:
                return _extract_json_blob(content)
            last_empty = (
                f"empty content (reasoning_len="
                f"{len(str(msg.get('reasoning') or msg.get('reasoning_content') or ''))})"
            )
            if empty_try == 0:
                time.sleep(0.5)
                continue
        raise RuntimeError(f"OpenAI-compatible chat returned {last_empty}")


# Back-compat aliases
OpenAICompatBackend = OpenAICompatibleClient


def OpenRouterBackend(**kwargs: Any) -> OpenAICompatibleClient:
    load_dotenv()
    key = kwargs.pop("api_key", None) or os.environ.get("OPENROUTER_API_KEY") or ""
    if not key:
        raise RuntimeError(
            "OPENROUTER_API_KEY missing. Create a key at https://openrouter.ai/keys"
        )
    return OpenAICompatibleClient(
        base_url=kwargs.pop("base_url", "https://openrouter.ai/api/v1"),
        api_key=key,
        timeout=kwargs.pop("timeout", 120.0),
        max_retries=kwargs.pop("max_retries", 12),
        max_tokens=kwargs.pop("max_tokens", 512),
        default_headers={
            "HTTP-Referer": "https://github.com/Kedar-V/BNY-Capstone-Project",
            "X-Title": "BNY Capstone Unified Extract",
        },
        **kwargs,
    )


def OrinBackend(**kwargs: Any) -> OpenAICompatibleClient:
    """AGX Orin / LAN Ollama hub via OpenAI-compatible /v1 (reads OLLAMA_HOST)."""
    load_dotenv()
    return OpenAICompatibleClient(
        base_url=kwargs.pop("base_url", None),
        api_key=kwargs.pop("api_key", "ollama"),
        timeout=kwargs.pop("timeout", 300.0),
        max_retries=kwargs.pop("max_retries", 3),
        max_tokens=kwargs.pop("max_tokens", 800),
        json_response_format=False,  # gemma-friendly default
        disable_thinking=kwargs.pop("disable_thinking", True),
        **kwargs,
    )


class NativeOllamaBackend:
    """Local Ollama native API — same path as tender hybrid (think=False, format=json).

    OpenAI /v1 ``reasoning_effort`` does not reliably disable Qwen3 thinking on
    desktop Ollama; the native client does.
    """

    def __init__(
        self,
        host: str | None = None,
        *,
        num_ctx: int | None = None,
        num_predict: int = 800,
        timeout: float = 300.0,
    ) -> None:
        import threading

        load_dotenv()
        import ollama

        raw = (host or os.environ.get("OLLAMA_HOST") or "http://127.0.0.1:11434").strip()
        # Native client wants host without /v1
        self.host = raw.rstrip("/").removesuffix("/v1")
        self.num_ctx = int(
            num_ctx
            if num_ctx is not None
            else os.environ.get("OLLAMA_NUM_CTX")
            or os.environ.get("OLLAMA_CONTEXT_LENGTH")
            or 16384
        )
        self.num_predict = num_predict
        # Thread-local clients so c>1 can hit OLLAMA_NUM_PARALLEL (shared Client+lock serializes)
        self._local = threading.local()
        self._timeout = timeout

    def _client(self):
        import ollama

        c = getattr(self._local, "client", None)
        if c is None:
            c = ollama.Client(host=self.host, timeout=self._timeout)
            self._local.client = c
        return c

    def chat_json(self, *, system: str, user: str, model: str) -> str:
        last_err: Exception | None = None
        for attempt in range(3):
            try:
                resp = self._client().chat(
                    model=model,
                    messages=[
                        {"role": "system", "content": system},
                        {"role": "user", "content": user},
                    ],
                    options={
                        "temperature": 0.0,
                        "num_predict": self.num_predict,
                        "num_ctx": self.num_ctx,
                        "repeat_penalty": 1.2,
                    },
                    format="json",
                    think=False,
                )
                if isinstance(resp, dict):
                    raw = (resp.get("message") or {}).get("content") or ""
                else:
                    raw = getattr(getattr(resp, "message", None), "content", "") or ""
                blob = _extract_json_blob(str(raw))
                if not blob:
                    raise RuntimeError("empty ollama content")
                return blob
            except Exception as e:  # noqa: BLE001
                last_err = e
                time.sleep(0.4 * (attempt + 1))
        raise RuntimeError(f"native ollama chat_json failed: {last_err}")


def make_backend(name: str) -> ChatBackend:
    key = (name or "orin").strip().lower()
    if key in {"openrouter", "or", "free"}:
        return OpenRouterBackend()
    if key in {"ollama", "native", "ollama_native"}:
        return NativeOllamaBackend()
    if key in {"orin", "openai", "openai_compat", "ollama_v1"}:
        return OrinBackend()
    raise KeyError(f"unknown backend {name!r}; use orin|ollama|openrouter")
