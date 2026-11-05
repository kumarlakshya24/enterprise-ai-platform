"""LLM providers, selected by LLM_PROVIDER. Keys come only from the environment.

* anthropic     - Claude via the official `anthropic` SDK (ANTHROPIC_API_KEY or an
                  `ant auth login` profile). Opts into server-side refusal fallbacks.
* openai_compat - any OpenAI-compatible /chat/completions server (vLLM, Ollama,
                  LM Studio, OpenAI). Base URL + optional key from env.
* extractive    - no model call. The generator selects cited sentences from the
                  retrieved chunks with the cross-encoder. Deterministic, zero cost,
                  faithful by construction; used for offline/CI evaluation.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Protocol

from app.config import Settings

log = logging.getLogger(__name__)


@dataclass
class LLMResult:
    text: str
    input_tokens: int = 0
    output_tokens: int = 0
    model: str = ""


class LLM(Protocol):
    name: str
    is_external: bool  # True when text leaves our infrastructure (drives PII redaction)
    generative: bool

    def complete(self, system: str, user: str, max_tokens: int, timeout_s: float) -> LLMResult: ...


class ExtractiveLLM:
    name = "extractive"
    is_external = False
    generative = False

    def complete(self, system: str, user: str, max_tokens: int, timeout_s: float) -> LLMResult:
        raise RuntimeError("extractive provider does not generate text; the generator handles it")


class AnthropicLLM:
    is_external = True
    generative = True

    def __init__(self, model: str, effort: str):
        import anthropic

        self._anthropic = anthropic
        self.client = anthropic.Anthropic()  # resolves ANTHROPIC_API_KEY / auth profile from env
        self.model, self.effort = model, effort
        self.name = f"anthropic:{model}"

    def complete(self, system: str, user: str, max_tokens: int, timeout_s: float) -> LLMResult:
        resp = self.client.with_options(timeout=timeout_s, max_retries=1).beta.messages.create(
            model=self.model,
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": user}],
            output_config={"effort": self.effort},
            betas=["server-side-fallback-2026-07-01"],
            extra_body={"fallbacks": "default"},
        )
        if resp.stop_reason == "refusal":
            log.warning("llm_refusal", extra={"model": self.model})
            return LLMResult("NOT_FOUND", resp.usage.input_tokens, resp.usage.output_tokens, resp.model)
        text = "".join(b.text for b in resp.content if b.type == "text")
        return LLMResult(text, resp.usage.input_tokens, resp.usage.output_tokens, resp.model)


class OpenAICompatLLM:
    generative = True

    def __init__(self, base_url: str, model: str, api_key: str | None):
        import httpx

        self.client = httpx.Client(base_url=base_url, headers={"Authorization": f"Bearer {api_key}"} if api_key else {})
        self.model = model
        self.name = f"openai_compat:{model}"
        self.is_external = not any(h in base_url for h in ("localhost", "127.0.0.1", "ollama", "vllm"))

    def complete(self, system: str, user: str, max_tokens: int, timeout_s: float) -> LLMResult:
        r = self.client.post(
            "/chat/completions",
            timeout=timeout_s,
            json={
                "model": self.model,
                "max_tokens": max_tokens,
                "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            },
        )
        r.raise_for_status()
        body = r.json()
        usage = body.get("usage", {})
        return LLMResult(
            body["choices"][0]["message"]["content"],
            usage.get("prompt_tokens", 0),
            usage.get("completion_tokens", 0),
            self.model,
        )


def build_llm(s: Settings) -> LLM:
    p = s.llm_provider.lower()
    if p == "extractive":
        return ExtractiveLLM()
    if p == "anthropic":
        return AnthropicLLM(s.llm_model, s.llm_effort)
    if p == "openai_compat":
        return OpenAICompatLLM(s.openai_compat_base_url, s.llm_model, s.openai_compat_api_key)
    raise ValueError(f"unknown LLM_PROVIDER {s.llm_provider!r}")
