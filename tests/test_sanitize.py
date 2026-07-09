"""Offline tests for the PHI/PII sanitizer + its ingest integration."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from protocol_to_data import sanitize  # noqa: E402
from protocol_to_data.ingest import load_protocol_text  # noqa: E402


def test_regex_scrub_redacts_structured_pii():
    text = "Contact jane.doe@hospital.org or 415-555-0199; SSN 123-45-6789; MRN: 0099887."
    out, n = sanitize.regex_scrub(text)
    assert n >= 4
    for tok in ("EMAIL_REDACTED", "PHONE_REDACTED", "SSN_REDACTED", "MRN_REDACTED"):
        assert tok in out
    assert "jane.doe@hospital.org" not in out and "123-45-6789" not in out


def test_sanitize_text_falls_back_to_regex_without_presidio():
    out = sanitize.sanitize_text("reach a@b.com, ssn 111-22-3333")
    assert "EMAIL_REDACTED" in out and "SSN_REDACTED" in out


def test_enabled_flag(monkeypatch):
    monkeypatch.delenv("PTD_SANITIZE_PHI", raising=False)
    assert sanitize.enabled() is False
    monkeypatch.setenv("PTD_SANITIZE_PHI", "1")
    assert sanitize.enabled() is True


def test_ingest_sanitizes_only_when_enabled(tmp_path, monkeypatch):
    p = tmp_path / "proto.txt"
    p.write_text("PI email dr.smith@clinic.com — a Phase 3 study of Drug-X.")

    monkeypatch.delenv("PTD_SANITIZE_PHI", raising=False)  # default off → unchanged
    assert "dr.smith@clinic.com" in load_protocol_text(p)

    monkeypatch.setenv("PTD_SANITIZE_PHI", "1")             # on → redacted before the LLM
    out = load_protocol_text(p)
    assert "dr.smith@clinic.com" not in out and "EMAIL_REDACTED" in out
    assert "Phase 3 study of Drug-X" in out                 # design terms preserved
