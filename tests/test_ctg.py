"""Registry Cross-Check — CTG fetcher + read-only UI badge. Offline (transport mocked)."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

from protocol_to_data import ctg_validator

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import app  # noqa: E402  — repo-root Gradio module


_CODEBREAK = {
    "protocolSection": {
        "designModule": {"phases": ["PHASE3"], "enrollmentInfo": {"count": 345}},
        "armsInterventionsModule": {"armGroups": [{"label": "AMG 510"}, {"label": "Docetaxel"}]},
    }
}


# ---- fetch_ctg_baseline (transport = _get, mocked) --------------------------------------

def test_fetch_success(monkeypatch):
    monkeypatch.setattr(ctg_validator, "_get", lambda url: (200, _CODEBREAK))
    assert ctg_validator.fetch_ctg_baseline("NCT04303780") == {
        "nct_id": "NCT04303780", "phase": "3", "num_arms": 2, "enrollment": 345,
    }


def test_fetch_lowercases_and_trims(monkeypatch):
    monkeypatch.setattr(ctg_validator, "_get", lambda url: (200, _CODEBREAK))
    assert ctg_validator.fetch_ctg_baseline("  nct04303780 ")["nct_id"] == "NCT04303780"


def test_empty_id_no_network():
    assert "error" in ctg_validator.fetch_ctg_baseline("")


def test_non_nct_id_rejected():
    # The AMG sponsor id is not a valid registry key — reject before any network call.
    assert "error" in ctg_validator.fetch_ctg_baseline("AMG510-20190009")


def test_404_handled(monkeypatch):
    monkeypatch.setattr(ctg_validator, "_get", lambda url: (404, None))
    assert "404" in ctg_validator.fetch_ctg_baseline("NCT99999999")["error"]


def test_non_200_handled(monkeypatch):
    monkeypatch.setattr(ctg_validator, "_get", lambda url: (503, None))
    assert "503" in ctg_validator.fetch_ctg_baseline("NCT04303780")["error"]


def test_transport_failure_handled(monkeypatch):
    def boom(url):
        raise ctg_validator._Unreachable("SSLError")
    monkeypatch.setattr(ctg_validator, "_get", boom)
    assert "Could not reach" in ctg_validator.fetch_ctg_baseline("NCT04303780")["error"]


def test_phase_normalization():
    assert ctg_validator._normalize_phase(["PHASE1", "PHASE2"]) == "1/2"
    assert ctg_validator._normalize_phase([]) == "N/A"


def test_parse_baseline_missing_modules():
    # A sparse payload must not crash — arms default to 0, enrollment to None.
    assert ctg_validator._parse_baseline({}) == {"phase": "N/A", "num_arms": 0, "enrollment": None}


# ---- app._render_crosscheck (read-only badge) -------------------------------------------

def test_render_hint_when_no_nct():
    assert "NCT ID" in app._render_crosscheck({"num_arms": 2}, "")  # no network hit


def test_render_all_match(monkeypatch):
    monkeypatch.setattr(app.ctg_validator, "fetch_ctg_baseline",
                        lambda n: {"nct_id": "NCT04303780", "phase": "3", "num_arms": 2, "enrollment": 345})
    md = app._render_crosscheck({"num_arms": 2, "phase": "3", "enrollment": 345}, "NCT04303780")
    assert md.count("✅ Match") == 3 and "⚠️ Differs" not in md


def test_render_flags_differences(monkeypatch):
    monkeypatch.setattr(app.ctg_validator, "fetch_ctg_baseline",
                        lambda n: {"nct_id": "NCT04303780", "phase": "3", "num_arms": 2, "enrollment": 345})
    md = app._render_crosscheck({"num_arms": 3, "phase": "2", "enrollment": 650}, "NCT04303780")
    assert "⚠️ Differs" in md


def test_render_error_degrades(monkeypatch):
    monkeypatch.setattr(app.ctg_validator, "fetch_ctg_baseline",
                        lambda n: {"error": "NCT99999999 not found on ClinicalTrials.gov (404)."})
    assert "unavailable" in app._render_crosscheck({}, "NCT99999999")


def test_phase_digits_helper():
    assert app._phase_digits("Phase 3") == "3"
    assert app._phase_digits("PHASE3") == "3"


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
