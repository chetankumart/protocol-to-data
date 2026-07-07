"""Offline tests for extraction logic — LLM calls are mocked, no API key needed.

Covers: the structured-output primary path, the JSON fallback when structured output is
unavailable, the one-shot repair on a schema-invalid first result, and normalization
(DM guaranteed, duplicate domains collapsed).
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from protocol_to_data import extract as extract_mod  # noqa: E402
from protocol_to_data.extract import extract_design_from_text  # noqa: E402
from protocol_to_data.schemas import DomainPlan, ProtocolDesign  # noqa: E402

_TEXT = "A Phase 3 study of Drug-X in heart failure."


def _design(domains):
    return ProtocolDesign(study_id="HF-1", phase="3",
                          domains=[DomainPlan(domain=d) for d in domains])


def test_structured_primary_path(monkeypatch):
    """When parse_model succeeds, its design is used (and DM is preserved)."""
    monkeypatch.setattr(extract_mod, "parse_model",
                        lambda *a, **k: _design(["DM", "VS", "AE"]))
    design = extract_design_from_text(_TEXT)
    assert design.study_id == "HF-1"
    assert design.domain_names() == ["DM", "VS", "AE"]


def test_normalize_inserts_dm(monkeypatch):
    """A design missing DM gets it prepended — the generator requires it."""
    monkeypatch.setattr(extract_mod, "parse_model", lambda *a, **k: _design(["VS", "AE"]))
    design = extract_design_from_text(_TEXT)
    assert design.domain_names()[0] == "DM"
    assert set(design.domain_names()) == {"DM", "VS", "AE"}


def test_dedupe_domains(monkeypatch):
    """Duplicate domains (case-insensitive) collapse to one, order preserved."""
    monkeypatch.setattr(extract_mod, "parse_model",
                        lambda *a, **k: _design(["DM", "VS", "vs", "AE"]))
    design = extract_design_from_text(_TEXT)
    assert design.domain_names() == ["DM", "VS", "AE"]


def test_json_fallback_when_structured_unavailable(monkeypatch):
    """If parse_model raises, we fall back to JSON mode and still produce a design."""
    def boom(*a, **k):
        raise RuntimeError("structured outputs not supported")
    monkeypatch.setattr(extract_mod, "parse_model", boom)
    monkeypatch.setattr(extract_mod, "complete_json",
                        lambda *a, **k: {"study_id": "HF-2", "domains": [{"domain": "DM"}]})
    design = extract_design_from_text(_TEXT)
    assert design.study_id == "HF-2"


def test_json_repair_on_invalid_first_result(monkeypatch):
    """Structured path down, first JSON is schema-invalid → one repair pass fixes it."""
    def boom(*a, **k):
        raise RuntimeError("no structured outputs")
    monkeypatch.setattr(extract_mod, "parse_model", boom)

    calls = {"n": 0}

    def flaky_json(*a, **k):
        calls["n"] += 1
        if calls["n"] == 1:
            return {"phase": "3"}  # missing required study_id → ValidationError
        return {"study_id": "HF-3", "domains": [{"domain": "DM"}]}

    monkeypatch.setattr(extract_mod, "complete_json", flaky_json)
    design = extract_design_from_text(_TEXT)
    assert design.study_id == "HF-3"
    assert calls["n"] == 2  # first failed, repair succeeded


def test_json_repair_second_failure_surfaces(monkeypatch):
    """If even the repair is invalid, the error surfaces instead of faking a design."""
    monkeypatch.setattr(extract_mod, "parse_model",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("down")))
    monkeypatch.setattr(extract_mod, "complete_json", lambda *a, **k: {"phase": "3"})
    with pytest.raises(Exception):
        extract_design_from_text(_TEXT)
