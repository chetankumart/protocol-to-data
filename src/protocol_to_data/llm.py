"""Thin Claude API wrapper.

Centralizes model selection and JSON-mode calls so the rest of the code stays clean.
Load the `claude-api` skill / SDK reference before changing model ids or params.
"""

from __future__ import annotations

import json
import os
from typing import Any, TypeVar

from pydantic import BaseModel

# Model tiers — see docs/SPEC.md "Model usage guidance"
MODEL_REASON = "claude-opus-4-8"            # extraction, repair
MODEL_CHEAP = "claude-haiku-4-5-20251001"   # cheap structural steps

T = TypeVar("T", bound=BaseModel)


def _client():
    try:
        from anthropic import Anthropic  # type: ignore
    except ImportError as e:  # pragma: no cover
        raise RuntimeError("anthropic SDK required: pip install anthropic") from e
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError("Set ANTHROPIC_API_KEY in the environment")
    return Anthropic(api_key=api_key)


def complete(prompt: str, *, model: str = MODEL_REASON, max_tokens: int = 4096,
             system: str | None = None) -> str:
    """Return Claude's text response for a single-turn prompt."""
    client = _client()
    kwargs: dict[str, Any] = dict(model=model, max_tokens=max_tokens,
                                  messages=[{"role": "user", "content": prompt}])
    if system:
        kwargs["system"] = system
    resp = client.messages.create(**kwargs)
    return "".join(block.text for block in resp.content if getattr(block, "type", None) == "text")


def parse_model(prompt: str, schema: type[T], *, model: str = MODEL_REASON,
                max_tokens: int = 8000, system: str | None = None,
                thinking: bool = True) -> T:
    """Return a schema-valid pydantic instance using structured outputs.

    Uses `messages.parse`, which constrains the response to `schema` server-side and
    validates it — so the result is guaranteed to satisfy the model, not just be JSON.
    Extraction is reasoning-heavy, so adaptive thinking is on by default.
    """
    client = _client()
    kwargs: dict[str, Any] = dict(model=model, max_tokens=max_tokens,
                                  output_format=schema,
                                  messages=[{"role": "user", "content": prompt}])
    if system:
        kwargs["system"] = system
    if thinking:
        kwargs["thinking"] = {"type": "adaptive"}
    resp = client.messages.parse(**kwargs)
    return resp.parsed_output


def complete_json(prompt: str, *, model: str = MODEL_REASON, max_tokens: int = 4096) -> dict:
    """Call Claude and parse the response as JSON.

    Robust to models that wrap JSON in ```json fences or add stray prose.
    """
    text = complete(prompt, model=model, max_tokens=max_tokens,
                    system="You output only valid JSON. No markdown, no prose.")
    return _extract_json(text)


def _extract_json(text: str) -> dict:
    text = text.strip()
    if text.startswith("```"):
        text = text.split("```", 2)[1]
        if text.startswith("json"):
            text = text[4:]
        text = text.strip("` \n")
    # Fallback: grab the outermost {...}
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start != -1 and end != -1:
            return json.loads(text[start:end + 1])
        raise
