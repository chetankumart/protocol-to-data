"""Offline tests for the free-tier retry wrapper (no network / gradio_client)."""
from __future__ import annotations

import concurrent.futures
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import ptd_api_client as api  # noqa: E402


class _FlakyClient:
    """A fake gradio_client that fails `fail_times` before succeeding."""

    def __init__(self, fail_times: int, exc: type[BaseException] = concurrent.futures.CancelledError):
        self.calls = 0
        self.fail_times = fail_times
        self.exc = exc

    def predict(self, *args, **kwargs):
        self.calls += 1
        if self.calls <= self.fail_times:
            raise self.exc()
        return "ok"


def test_retries_once_on_transient_then_succeeds():
    c = _FlakyClient(fail_times=1)
    assert api.predict_with_retry(c, backoff=0) == "ok"
    assert c.calls == 2  # failed once, retried, succeeded


def test_reraises_after_retries_exhausted():
    c = _FlakyClient(fail_times=5)
    with pytest.raises(concurrent.futures.CancelledError):
        api.predict_with_retry(c, retries=1, backoff=0)
    assert c.calls == 2  # initial + 1 retry, both failed


def test_non_transient_error_is_not_retried():
    c = _FlakyClient(fail_times=1, exc=ValueError)
    with pytest.raises(ValueError):
        api.predict_with_retry(c, backoff=0)
    assert c.calls == 1  # real error surfaces immediately, no retry
