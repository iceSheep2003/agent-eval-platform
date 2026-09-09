"""Provider-agnostic LLM client with two backends.

Credentials are read from the environment at call time. Two protocols are supported:

* **Anthropic Messages API** — triggered by ``ANTHROPIC_AUTH_TOKEN`` / ``ANTHROPIC_API_KEY``
  with ``ANTHROPIC_BASE_URL`` and ``ANTHROPIC_MODEL`` (e.g. a grok-4.5 proxy behind an
  Anthropic-compatible endpoint).
* **OpenAI-compatible** — triggered by ``LLM_API_KEY`` / ``OPENAI_API_KEY`` / ``DASHSCOPE_API_KEY``.

If no key is present — or the call fails for any reason (network, auth, schema) — ``chat()``
returns ``None`` so the caller can degrade to a deterministic policy rather than raising.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

import httpx

OPENAI_BASE = "https://api.openai.com/v1"
ANTHROPIC_BASE = "https://api.anthropic.com"
DASHSCOPE_BASE = "https://dashscope.aliyuncs.com/compatible-mode/v1"
DEFAULT_TIMEOUT = 20.0


@dataclass(frozen=True)
class LLMConfig:
    api_key: str | None
    base_url: str
    model: str
    backend: str = "openai"  # "openai" | "anthropic"


def _first_env(*names: str) -> str | None:
    for name in names:
        if value := os.getenv(name):
            return value
    return None


def _openai_base_url(url: str) -> str:
    url = url.rstrip("/")
    return url if url.endswith("/chat/completions") else f"{url}/chat/completions"


def _anthropic_messages_url(url: str) -> str:
    url = url.rstrip("/")
    return url if url.endswith("/v1/messages") else f"{url}/v1/messages"


def llm_config_from_env() -> LLMConfig:
    anthropic_key = _first_env("ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_API_KEY")
    if anthropic_key:
        base_url = os.getenv("ANTHROPIC_BASE_URL") or ANTHROPIC_BASE
        model = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-5")
        return LLMConfig(api_key=anthropic_key, base_url=base_url, model=model, backend="anthropic")

    api_key = _first_env("LLM_API_KEY", "OPENAI_API_KEY", "DASHSCOPE_API_KEY")
    base_url = os.getenv("LLM_BASE_URL")
    dashscope = bool(os.getenv("DASHSCOPE_API_KEY"))
    if base_url:
        base_url = _openai_base_url(base_url)
    elif dashscope:
        base_url = _openai_base_url(DASHSCOPE_BASE)
    else:
        base_url = _openai_base_url(OPENAI_BASE)
    model = os.getenv("LLM_MODEL", "qwen-plus" if dashscope else "gpt-4o-mini")
    return LLMConfig(api_key=api_key, base_url=base_url, model=model, backend="openai")


class ChatClient:
    def __init__(self, config: LLMConfig | None = None) -> None:
        self.config = config or llm_config_from_env()

    @property
    def available(self) -> bool:
        return bool(self.config.api_key)

    async def chat(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float = 0.0,
        max_tokens: int = 256,
    ) -> str | None:
        if not self.config.api_key:
            return None
        try:
            if self.config.backend == "anthropic":
                return await self._chat_anthropic(messages, temperature, max_tokens)
            return await self._chat_openai(messages, temperature, max_tokens)
        except Exception:
            # Best-effort: degrade to the deterministic policy instead of raising.
            return None

    async def _chat_openai(self, messages: list[dict[str, str]], temperature: float, max_tokens: int) -> str:
        payload = {
            "model": self.config.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        headers = {"Authorization": f"Bearer {self.config.api_key}", "Content-Type": "application/json"}
        async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT) as client:
            response = await client.post(self.config.base_url, json=payload, headers=headers)
            response.raise_for_status()
            data = response.json()
        return data["choices"][0]["message"]["content"]

    async def _chat_anthropic(self, messages: list[dict[str, str]], temperature: float, max_tokens: int) -> str:
        system = next((m["content"] for m in messages if m.get("role") == "system"), None)
        turns = [{"role": m["role"], "content": m["content"]} for m in messages if m.get("role") in ("user", "assistant")]
        payload = {
            "model": self.config.model,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "messages": turns,
        }
        if system:
            payload["system"] = system
        headers = {
            "x-api-key": self.config.api_key,
            "Authorization": f"Bearer {self.config.api_key}",
            "anthropic-version": "2023-06-01",
            "Content-Type": "application/json",
        }
        async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT) as client:
            response = await client.post(_anthropic_messages_url(self.config.base_url), json=payload, headers=headers)
            response.raise_for_status()
            data = response.json()
        # Some models emit a leading ``thinking`` block (extended thinking) before the
        # final text block — collect only ``text`` blocks.
        text = "".join(block.get("text", "") for block in data.get("content", []) if block.get("type") == "text")
        return text or None