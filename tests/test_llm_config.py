"""Offline test for deterministic LLM config — temperature=0.0 only where the API accepts it.

Adaptive-thinking models (opus-4-8, sonnet-5, fable-5) removed sampling params and 400 on
`temperature`; legacy models still accept it. The API client is faked so no key is needed.
"""

import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from protocol_to_data import llm  # noqa: E402


def _fake_client(captured: dict):
    class _Messages:
        def create(self, **kwargs):
            captured.clear()
            captured.update(kwargs)
            return SimpleNamespace(content=[SimpleNamespace(type="text", text="ok")], usage=None)
    return SimpleNamespace(messages=_Messages())


def test_temperature_omitted_on_opus_48(monkeypatch):
    captured: dict = {}
    monkeypatch.setattr(llm, "_client", lambda: _fake_client(captured))
    llm.complete("hi", model="claude-opus-4-8")
    assert "temperature" not in captured  # would 400 on this model — must be absent


def test_temperature_set_on_legacy_model(monkeypatch):
    captured: dict = {}
    monkeypatch.setattr(llm, "_client", lambda: _fake_client(captured))
    llm.complete("hi", model="claude-3-5-sonnet-20241022")  # legacy: accepts sampling
    assert captured.get("temperature") == 0.0
