"""Offline tests for LLM usage observability — cost estimate, accumulation, badge formatting."""

import sys
from pathlib import Path
from types import SimpleNamespace

_REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO / "src"))
sys.path.insert(0, str(_REPO))

import app  # noqa: E402
from protocol_to_data import llm  # noqa: E402


def test_estimate_cost_opus_rates():
    # opus-4-8: $5 / 1M input, $25 / 1M output
    assert llm.estimate_cost("claude-opus-4-8", 1_000_000, 0) == 5.0
    assert llm.estimate_cost("claude-opus-4-8", 0, 1_000_000) == 25.0
    assert abs(llm.estimate_cost("claude-opus-4-8", 40_000, 8_000) - (0.20 + 0.20)) < 1e-9


def test_usage_accumulates_and_resets():
    llm.reset_usage()
    llm._record_usage("claude-opus-4-8", SimpleNamespace(input_tokens=30_000, output_tokens=5_000))
    llm._record_usage("claude-opus-4-8", SimpleNamespace(input_tokens=10_000, output_tokens=3_000))
    s = llm.usage_summary()
    assert s["input_tokens"] == 40_000 and s["output_tokens"] == 8_000
    assert abs(s["cost"] - llm.estimate_cost("claude-opus-4-8", 40_000, 8_000)) < 1e-9
    llm.reset_usage()
    assert llm.usage_summary() == {"input_tokens": 0, "output_tokens": 0, "cost": 0.0}


def test_usage_sums_across_models():
    llm.reset_usage()
    llm._record_usage("claude-opus-4-8", SimpleNamespace(input_tokens=1_000_000, output_tokens=0))
    llm._record_usage("claude-haiku-4-5-20251001", SimpleNamespace(input_tokens=1_000_000, output_tokens=0))
    assert abs(llm.usage_summary()["cost"] - (5.0 + 1.0)) < 1e-9  # opus $5 + haiku $1


def test_badge_formatting():
    assert app._usage_badge(None) == "🪙 Run Cost: —"
    badge = app._usage_badge({"input_tokens": 42_000, "output_tokens": 8_000, "cost": 0.35})
    assert "$0.35" in badge and "42k in" in badge and "8k out" in badge
