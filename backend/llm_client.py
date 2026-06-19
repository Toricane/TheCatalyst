"""LiteLLM wrapper routing CLOD (primary) and Gemini (fallback)."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

import litellm

from .config import CLOD_API_BASE, CLOD_API_KEY, GEMINI_API_KEY


def is_configured() -> bool:
    """Return True when the primary CLOD provider is configured."""

    return bool(CLOD_API_KEY)


def is_fallback_configured() -> bool:
    """Return True when the Gemini fallback provider is configured."""

    return bool(GEMINI_API_KEY)


def _is_gemini_model(model: str) -> bool:
    return model.startswith("gemini-")


def resolve_litellm_params(model: str) -> Dict[str, Any]:
    """Map a logical model name to LiteLLM provider parameters."""

    if _is_gemini_model(model):
        if not GEMINI_API_KEY:
            raise ValueError(
                f"GEMINI_API_KEY is required to use fallback model '{model}'"
            )
        return {"model": f"gemini/{model}", "api_key": GEMINI_API_KEY}

    if not CLOD_API_KEY:
        raise ValueError(f"CLOD_API_KEY is required to use model '{model}'")

    return {
        "model": f"openai/{model}",
        "api_base": CLOD_API_BASE,
        "api_key": CLOD_API_KEY,
    }


async def acompletion(
    *,
    model: str,
    messages: List[Dict[str, Any]],
    tools: Optional[List[Dict[str, Any]]] = None,
    temperature: float = 0.7,
    response_format: Optional[Dict[str, str]] = None,
) -> Any:
    """Run an async chat completion via LiteLLM."""

    params = resolve_litellm_params(model)
    kwargs: Dict[str, Any] = {
        "messages": messages,
        "temperature": temperature,
        **params,
    }
    if tools:
        kwargs["tools"] = tools
    if response_format:
        kwargs["response_format"] = response_format
    return await litellm.acompletion(**kwargs)
