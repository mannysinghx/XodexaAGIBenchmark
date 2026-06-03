"""
apps.server.providers
========================
The provider registry — the only place that talks to external model APIs. It does
three things, and nothing else gets to touch a raw key:

  * ``validate_key(provider, key, base_url)`` — a cheap authenticated call to prove the
    key is real (so the platform never runs on a bogus credential).
  * ``list_models(provider, key, base_url)`` — discover/validate model names.
  * ``connector(provider, key, model, base_url)`` — build a ``xodexa`` ModelConnector
    used by the worker to actually run the benchmark.

Supported: ``openai``, ``anthropic``, and ``openai-compatible`` (vLLM / TGI / Ollama /
LM Studio / llama.cpp / OpenRouter — anything exposing /v1/chat/completions).
"""

from __future__ import annotations

import httpx

from xodexa import OpenAICompatibleConnector, AnthropicConnector
from xodexa.runner import ModelConnector

PROVIDERS = {
    "openai": {"label": "OpenAI", "needs_base_url": False},
    "anthropic": {"label": "Anthropic", "needs_base_url": False},
    "openai-compatible": {"label": "OpenAI-compatible (vLLM/TGI/Ollama/LM Studio/…)",
                          "needs_base_url": True},
}

_TIMEOUT = 20.0


class ProviderError(Exception):
    pass


def _openai_base(base_url: str | None) -> str:
    return (base_url or "https://api.openai.com/v1").rstrip("/")


def validate_key(provider: str, key: str, base_url: str | None = None) -> dict:
    """Return {ok, detail, models?}. Raises ProviderError on a hard failure."""
    if provider not in PROVIDERS:
        raise ProviderError(f"unknown provider: {provider}")
    try:
        if provider == "openai" or provider == "openai-compatible":
            url = _openai_base(base_url) + "/models"
            r = httpx.get(url, headers={"Authorization": f"Bearer {key}"}, timeout=_TIMEOUT)
            if r.status_code == 401:
                return {"ok": False, "detail": "invalid API key (401)"}
            r.raise_for_status()
            data = r.json()
            models = [m.get("id") for m in data.get("data", []) if m.get("id")]
            return {"ok": True, "detail": "key validated", "models": sorted(models)[:200]}
        if provider == "anthropic":
            # /v1/models requires a valid key; cheap and side-effect-free.
            r = httpx.get("https://api.anthropic.com/v1/models",
                          headers={"x-api-key": key, "anthropic-version": "2023-06-01"},
                          timeout=_TIMEOUT)
            if r.status_code in (401, 403):
                return {"ok": False, "detail": "invalid API key"}
            r.raise_for_status()
            data = r.json()
            models = [m.get("id") for m in data.get("data", []) if m.get("id")]
            return {"ok": True, "detail": "key validated", "models": sorted(models)[:200]}
    except httpx.HTTPStatusError as e:
        return {"ok": False, "detail": f"provider error {e.response.status_code}"}
    except httpx.HTTPError as e:
        raise ProviderError(f"could not reach provider: {e}") from e
    return {"ok": False, "detail": "unsupported"}


def list_models(provider: str, key: str, base_url: str | None = None) -> list[str]:
    res = validate_key(provider, key, base_url)
    if not res.get("ok"):
        raise ProviderError(res.get("detail", "validation failed"))
    return res.get("models", [])


def validate_model(provider: str, key: str, model: str, base_url: str | None = None) -> bool:
    """A model name is legitimate if the provider lists it (best-effort: if the list
    is unavailable we accept, since some OpenAI-compatible servers don't expose /models)."""
    try:
        models = list_models(provider, key, base_url)
    except ProviderError:
        return True  # endpoint may not support discovery; allow, run will surface errors
    return (not models) or (model in models)


def connector(provider: str, key: str, model: str,
              base_url: str | None = None) -> ModelConnector:
    if provider == "anthropic":
        return AnthropicConnector(api_key=key, model=model)
    if provider == "openai":
        return OpenAICompatibleConnector(_openai_base(base_url), model, api_key=key)
    if provider == "openai-compatible":
        if not base_url:
            raise ProviderError("openai-compatible requires a base_url")
        return OpenAICompatibleConnector(base_url.rstrip("/"), model, api_key=key or "x")
    raise ProviderError(f"unknown provider: {provider}")
