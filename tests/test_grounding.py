"""Offline tests for OpenFDA AE grounding — the HTTP seam (`_get`) is mocked; no network."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from protocol_to_data import grounding  # noqa: E402
from protocol_to_data.schemas import AEGrounding, Arm, ProtocolDesign  # noqa: E402

_OPENFDA_OK = {"results": [
    {"term": "NAUSEA", "count": 900}, {"term": "FATIGUE", "count": 700},
    {"term": "DIARRHOEA", "count": 500}, {"term": "NEUTROPENIA", "count": 300},
]}


def test_fetch_parses_and_normalizes_and_caps(monkeypatch):
    monkeypatch.setattr(grounding, "_get", lambda url: (200, _OPENFDA_OK))
    out = grounding.fetch_ae_grounding("docetaxel", top_n=3)
    assert all(isinstance(x, AEGrounding) for x in out)
    assert [x.term for x in out] == ["Nausea", "Fatigue", "Diarrhoea"]   # title-cased, top_n=3
    assert [x.count for x in out] == [900, 700, 500]


def test_fetch_empty_on_404_non200_and_blank(monkeypatch):
    monkeypatch.setattr(grounding, "_get", lambda url: (404, None))       # OpenFDA: 0 hits → 404
    assert grounding.fetch_ae_grounding("nonesuch") == []
    monkeypatch.setattr(grounding, "_get", lambda url: (500, None))
    assert grounding.fetch_ae_grounding("docetaxel") == []
    assert grounding.fetch_ae_grounding("") == []                        # no drug → no call


def test_fetch_empty_on_transport_failure(monkeypatch):
    def boom(url):
        raise grounding._Unreachable("Timeout")
    monkeypatch.setattr(grounding, "_get", boom)
    assert grounding.fetch_ae_grounding("docetaxel") == []               # never raises


def test_clean_drug_strips_dose_and_route():
    assert grounding._clean_drug("Zephyrol 10 mg once daily (oral)") == "Zephyrol"
    assert grounding._clean_drug("Docetaxel 75 mg/m2 IV Q3W") == "Docetaxel"


def test_drug_candidates_skips_placebo_and_dedupes():
    d = ProtocolDesign(study_id="S", indication="hypertension", arms=[
        Arm(name="Zephyrol 10 mg", description="Zephyrol 10 mg once daily", is_placebo=False),
        Arm(name="Placebo", description="matching placebo", is_placebo=True),
    ])
    cands = grounding._drug_candidates(d)
    assert "Placebo" not in cands and "matching placebo" not in cands
    assert "Zephyrol 10 mg" in cands and "Zephyrol" in cands             # (a) raw + (b) cleaned
    assert cands[-1] == "hypertension"                                   # (c) indication last
    assert len(cands) == len(set(c.lower() for c in cands))              # order-deduped


def test_ground_design_returns_first_nonempty(monkeypatch):
    calls = []

    def fake_fetch(drug, *, top_n):
        calls.append(drug)
        return [AEGrounding(term="Nausea", count=10)] if drug == "Docetaxel" else []
    monkeypatch.setattr(grounding, "fetch_ae_grounding", fake_fetch)
    d = ProtocolDesign(study_id="S", arms=[Arm(name="Docetaxel 75 mg", is_placebo=False)])
    out = grounding.ground_design(d)
    assert len(out) == 1 and out[0].term == "Nausea"
    assert calls[0] == "Docetaxel 75 mg" and "Docetaxel" in calls        # cascade tried in order
