"""LLM access. Provider-agnostic through LangChain's ``init_chat_model``.

If no provider/API key is configured (or OFFLINE=1) every LLM-backed step falls back to
deterministic rules/templates, so the whole system runs and can be evaluated without a key.
"""
from __future__ import annotations

import json
import os
from typing import Any, TypeVar

from pydantic import BaseModel

from .settings import Settings

DEFAULT_MODELS = {
    "openai": "gpt-4o-mini",
    "anthropic": "claude-opus-5-5",
    "groq": "llama-3.3-70b-versatile",
    "ollama": "llama3.1",
}
KEY_ENV = {"openai": "OPENAI_API_KEY", "anthropic": "ANTHROPIC_API_KEY", "groq": "GROQ_API_KEY"}

M = TypeVar("M", bound=BaseModel)


def get_llm(settings: Settings) -> Any | None:
    """Return a chat model, or None when running offline."""
    if settings.force_offline:
        return None
    provider = settings.llm_provider
    if not provider:  # auto-detect from whichever key is present
        provider = next((p for p, env in KEY_ENV.items() if os.getenv(env)), "")
    if not provider:
        return None
    if provider in KEY_ENV and not os.getenv(KEY_ENV[provider]):
        return None
    from langchain.chat_models import init_chat_model

    model = settings.llm_model or DEFAULT_MODELS.get(provider)
    if not model:
        raise ValueError(f"set LLM_MODEL for provider {provider!r}")
    kwargs = {}
    # current Claude models reject non-default sampling params; leave temperature to the provider default
    if provider != "anthropic":
        kwargs["temperature"] = settings.llm_temperature
    return init_chat_model(model, model_provider=provider, **kwargs)


def structured(llm: Any, schema: type[M]) -> Any:
    """Bind a Pydantic schema so the model must return it.

    OpenAI-style providers use function/tool calling. Current Claude models don't accept a
    forced tool choice, so for Anthropic we use native structured outputs (json_schema).
    """
    if type(llm).__name__ == "ChatAnthropic":
        return llm.with_structured_output(schema, method="json_schema")
    return llm.with_structured_output(schema)


def describe(llm: Any | None) -> str:
    if llm is None:
        return "offline (deterministic rules and templates)"
    name = getattr(llm, "model_name", None) or getattr(llm, "model", None) or type(llm).__name__
    return f"LLM: {name}"


def ask_text(llm: Any, system: str, user: str) -> str:
    resp = llm.invoke([("system", system), ("human", user)])
    content = resp.content
    if isinstance(content, list):  # some providers return content blocks
        content = "".join(b.get("text", "") if isinstance(b, dict) else str(b) for b in content)
    return str(content).strip()


def ask_structured(llm: Any, schema: type[M], system: str, user: str) -> M:
    """Structured output via the provider's tool-calling interface."""
    return structured(llm, schema).invoke([("system", system), ("human", user)])


def as_json(data: Any) -> str:
    return json.dumps(data, indent=2, default=str, ensure_ascii=False)
