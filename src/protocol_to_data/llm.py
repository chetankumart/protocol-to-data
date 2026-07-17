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

# --- Usage observability (cost awareness) ---------------------------------------------
# USD per 1M tokens (input, output). Defaults to the reasoning model's rate for unknowns.
PRICING = {
    "claude-opus-4-8": (5.00, 25.00),
    "claude-haiku-4-5-20251001": (1.00, 5.00),
    "claude-haiku-4-5": (1.00, 5.00),
}
_usage: dict[str, list[int]] = {}  # model -> [input_tokens, output_tokens], accumulated per run


def estimate_cost(model: str, input_tokens: int, output_tokens: int) -> float:
    """Estimated USD cost for a call, from the model's per-1M-token pricing."""
    rate_in, rate_out = PRICING.get(model, PRICING[MODEL_REASON])
    return input_tokens / 1e6 * rate_in + output_tokens / 1e6 * rate_out


def reset_usage() -> None:
    """Clear the token tally — call at the start of a run."""
    _usage.clear()


def _record_usage(model: str, usage) -> None:
    """Accumulate input/output tokens from an API response's `usage` metadata."""
    if usage is None:
        return
    entry = _usage.setdefault(model, [0, 0])
    entry[0] += getattr(usage, "input_tokens", 0) or 0
    entry[1] += getattr(usage, "output_tokens", 0) or 0


def usage_summary() -> dict:
    """Cumulative tokens + estimated cost since the last reset (summed across models)."""
    total_in = sum(v[0] for v in _usage.values())
    total_out = sum(v[1] for v in _usage.values())
    cost = sum(estimate_cost(m, i, o) for m, (i, o) in _usage.items())
    return {"input_tokens": total_in, "output_tokens": total_out, "cost": cost}


def _client():
    try:
        from anthropic import Anthropic  # type: ignore
    except ImportError as e:  # pragma: no cover
        raise RuntimeError("anthropic SDK required: pip install anthropic") from e
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError("Set ANTHROPIC_API_KEY in the environment")
    return Anthropic(api_key=api_key)


# Adaptive-thinking models (Opus 4.8/4.7, Sonnet 5, Fable 5) REMOVED sampling params —
# sending `temperature`/`top_p` returns a 400. We only pass temperature=0.0 to models that
# still accept it; on the removed-sampling models determinism is guided by the prompt + the
# JSON-only system instruction instead (setting temperature there would break the call).
_SAMPLING_REMOVED = {
    "claude-opus-4-8", "claude-opus-4-7", "claude-sonnet-5", "claude-fable-5", "claude-mythos-5",
}


def complete(prompt: str, *, model: str = MODEL_REASON, max_tokens: int = 4096,
             system: str | None = None, think: bool = False) -> str:
    """Return Claude's text response for a single-turn prompt.

    `think=True` turns on **adaptive extended thinking** on the reasoning models (Opus 4.x /
    Sonnet 5 / Fable 5) — used for the reasoning-heavy steps (extraction, self-repair). Thinking
    blocks are dropped from the return; only the text (e.g. the JSON design) comes back.
    """
    client = _client()
    kwargs: dict[str, Any] = dict(model=model, max_tokens=max_tokens,
                                  messages=[{"role": "user", "content": prompt}])
    if system:
        kwargs["system"] = system
    if model not in _SAMPLING_REMOVED:
        kwargs["temperature"] = 0.0  # deterministic extraction on models that accept sampling
    elif think:
        # Adaptive thinking is only offered on the sampling-removed reasoning models; `budget_tokens`
        # is rejected there, so we pass the adaptive form (and never mix it with temperature).
        kwargs["thinking"] = {"type": "adaptive"}
    resp = client.messages.create(**kwargs)
    _record_usage(model, getattr(resp, "usage", None))
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
    _record_usage(model, getattr(resp, "usage", None))
    return resp.parsed_output


def complete_json(prompt: str, *, model: str = MODEL_REASON, max_tokens: int = 4096,
                  think: bool = False) -> dict:
    """Call Claude and parse the response as JSON.

    Robust to models that wrap JSON in ```json fences or add stray prose. `think=True` enables
    adaptive extended thinking for reasoning-heavy calls (extraction / repair).
    """
    text = complete(prompt, model=model, max_tokens=max_tokens, think=think,
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
