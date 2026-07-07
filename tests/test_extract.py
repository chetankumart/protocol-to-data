"""Offline tests for extraction logic — the LLM call (complete_json) is mocked, no key needed.

Extraction uses JSON mode (ProtocolDesign is too complex for structured outputs) with a
one-shot repair on a schema-invalid result, then normalization (DM guaranteed, domains deduped).
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from protocol_to_data import extract as extract_mod  # noqa: E402
from protocol_to_data.extract import extract_design_from_text  # noqa: E402

_TEXT = "A Phase 3 study of Drug-X in heart failure."


def _valid(domains, study="HF-1"):
    return {"study_id": study, "phase": "3", "domains": [{"domain": d} for d in domains]}


def test_happy_path(monkeypatch):
    monkeypatch.setattr(extract_mod, "complete_json", lambda *a, **k: _valid(["DM", "VS", "AE"]))
    d = extract_design_from_text(_TEXT)
    assert d.study_id == "HF-1"
    assert d.domain_names() == ["DM", "VS", "AE"]


def test_normalize_inserts_dm(monkeypatch):
    monkeypatch.setattr(extract_mod, "complete_json", lambda *a, **k: _valid(["VS", "AE"]))
    d = extract_design_from_text(_TEXT)
    assert d.domain_names()[0] == "DM"
    assert set(d.domain_names()) == {"DM", "VS", "AE"}


def test_dedupe_domains(monkeypatch):
    monkeypatch.setattr(extract_mod, "complete_json", lambda *a, **k: _valid(["DM", "VS", "vs", "AE"]))
    d = extract_design_from_text(_TEXT)
    assert d.domain_names() == ["DM", "VS", "AE"]


def test_repair_on_invalid_first_result(monkeypatch):
    """First JSON is schema-invalid → one repair pass fixes it."""
    calls = {"n": 0}

    def flaky(*a, **k):
        calls["n"] += 1
        if calls["n"] == 1:
            return {"phase": "3"}  # missing required study_id → ValidationError
        return _valid(["DM"], study="HF-3")

    monkeypatch.setattr(extract_mod, "complete_json", flaky)
    d = extract_design_from_text(_TEXT)
    assert d.study_id == "HF-3"
    assert calls["n"] == 2  # first failed, repair succeeded


def test_second_failure_surfaces(monkeypatch):
    """If even the repair is invalid, the error surfaces instead of faking a design."""
    monkeypatch.setattr(extract_mod, "complete_json", lambda *a, **k: {"phase": "3"})
    with pytest.raises(Exception):
        extract_design_from_text(_TEXT)
