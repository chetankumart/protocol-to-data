"""End-to-end EDGE-CASE coverage — boundary inputs, empty/oversized, malformed, degenerate.

All offline (LLM mocked where needed). Complements the feature suites with the awkward
inputs a judge or a real user will inevitably throw at the tool.
"""

import sys
from pathlib import Path

import pandas as pd
import pytest

_REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO / "src"))
sys.path.insert(0, str(_REPO))

import app  # noqa: E402
from protocol_to_data import extract as extract_mod  # noqa: E402
from protocol_to_data.anomalies import inject_anomalies, score_detections  # noqa: E402
from protocol_to_data.extract import extract_design  # noqa: E402
from protocol_to_data.generate import (  # noqa: E402
    _enforce_referential_integrity, code_term, generate_dataset,
)
from protocol_to_data.ingest import load_protocol_text  # noqa: E402
from protocol_to_data.llm import estimate_cost  # noqa: E402
from protocol_to_data.schemas import (  # noqa: E402
    AnomalyFinding, Arm, DomainPlan, Population, ProtocolDesign, Visit,
)
from protocol_to_data.validate import validate_dataset  # noqa: E402


def _design(domains=("DM", "VS", "LB", "AE", "EX"), **kw):
    base = dict(
        study_id="EDGE", phase="3",
        arms=[Arm(name="DRUG-X"), Arm(name="PLACEBO", is_placebo=True)],
        visits=[Visit(name="BASELINE", day=1), Visit(name="WEEK4", day=28)],
        population=Population(n_subjects=10),
        domains=[DomainPlan(domain=d) for d in domains],
    )
    base.update(kw)
    return ProtocolDesign(**base)


# ---------------------------------------------------------------- ingest edge cases

def test_ingest_rejects_unsupported_format(tmp_path):
    p = tmp_path / "protocol.docx"
    p.write_bytes(b"not really a docx")
    with pytest.raises(ValueError):
        load_protocol_text(p)


# ---------------------------------------------------------------- generation boundaries

def test_single_subject(tmp_path):
    out = generate_dataset(_design(), subjects=1, seed=42, out_root=tmp_path)
    assert len(pd.read_csv(out / "dm.csv")) == 1


def test_large_cohort(tmp_path):
    out = generate_dataset(_design(), subjects=100, seed=42, out_root=tmp_path)
    assert len(pd.read_csv(out / "dm.csv")) == 100
    assert validate_dataset(_design(), out).passed


def test_no_arms_falls_back(tmp_path):
    d = _design()
    d.arms = []
    out = generate_dataset(d, subjects=6, seed=1, out_root=tmp_path)
    assert set(pd.read_csv(out / "dm.csv")["ARM"]) == {"TREATMENT"}


def test_female_only_population(tmp_path):
    out = generate_dataset(_design(population=Population(n_subjects=10, sex="female")),
                           subjects=10, seed=1, out_root=tmp_path)
    assert set(pd.read_csv(out / "dm.csv")["SEX"]) == {"F"}


def test_no_visits_falls_back(tmp_path):
    d = _design(domains=("DM", "VS"))
    d.visits = []
    out = generate_dataset(d, subjects=5, seed=1, out_root=tmp_path)
    assert not pd.read_csv(out / "vs.csv").empty  # single fallback visit still produces rows


def test_only_unproducible_domain_fails_coverage(tmp_path):
    d = _design(domains=("DM", "MH"))  # MH can't be produced by the builtin backend
    out = generate_dataset(d, subjects=8, seed=1, out_root=tmp_path)
    assert (out / "dm.csv").exists() and not (out / "mh.csv").exists()
    report = validate_dataset(d, out)
    assert not report.passed
    assert any(f.check == "coverage" and f.domain == "MH" for f in report.findings)


# ---------------------------------------------------------------- anomaly edge cases

def test_anomalies_count_zero(tmp_path):
    out = generate_dataset(_design(), subjects=10, seed=42, out_root=tmp_path)
    assert inject_anomalies(out, count=0, seed=42) == []


def test_anomalies_count_exceeds_injectors(tmp_path):
    out = generate_dataset(_design(), subjects=10, seed=42, out_root=tmp_path)
    truth = inject_anomalies(out, count=99, seed=42)
    assert 0 < len(truth) <= 5  # capped at the number of available injectors


def test_anomalies_on_dm_only_dataset_no_crash(tmp_path):
    out = generate_dataset(_design(domains=("DM",)), subjects=10, seed=42, out_root=tmp_path)
    # injectors target VS/LB/AE which don't exist here → all skip, no crash
    assert inject_anomalies(out, count=5, seed=42) == []


def test_score_more_findings_than_truth():
    truth = [{"type": "pharmacologic", "domain": "AE", "usubjid": "S1"}]
    findings = [AnomalyFinding(domain="AE", anomaly_type="pharmacologic", description="x"),
                AnomalyFinding(domain="QS", anomaly_type="severity", description="extra")]
    s = score_detections(truth, findings)
    assert s["caught"] == 1 and len(s["extra"]) == 1


# ---------------------------------------------------------------- dictionary / cost / export edges

def test_code_term_edge_inputs():
    assert code_term("", {}) == ""
    assert code_term("SEVERE migraine", {}) == "Migraine"   # qualifier stripped + title-cased
    assert code_term("already coded", {"already coded": "Coded"}) == "Coded"


def test_estimate_cost_zero_tokens():
    assert estimate_cost("claude-opus-4-8", 0, 0) == 0.0


def test_export_warning_none_and_empty():
    assert app._export_warning(None) == ""
    assert app._export_warning("") == ""


# ---------------------------------------------------------------- integrity / validation edges

def test_enforce_all_orphans_drops_to_empty():
    dm = pd.DataFrame({"USUBJID": ["S1"]})
    child = pd.DataFrame({"USUBJID": ["GHOST-1", "GHOST-2"], "X": [1, 2]})
    frames = {"dm": dm, "lb": child}
    _enforce_referential_integrity(frames)  # must not raise
    assert frames["lb"].empty


def test_validate_empty_dir_fails(tmp_path):
    report = validate_dataset(_design(), tmp_path)  # no CSVs at all
    assert not report.passed


# ---------------------------------------------------------------- cache: content-addressed dedup

def test_cache_same_content_shares_entry(tmp_path, monkeypatch):
    monkeypatch.setattr(extract_mod, "_CACHE_DIR", tmp_path / ".cache")
    calls = {"n": 0}

    def fake_json(*a, **k):
        calls["n"] += 1
        return {"study_id": "DUP", "phase": "3", "domains": [{"domain": "DM"}]}

    monkeypatch.setattr(extract_mod, "complete_json", fake_json)
    (tmp_path / "a.md").write_text("identical protocol content")
    (tmp_path / "b.md").write_text("identical protocol content")  # same bytes → same SHA-256

    extract_design(tmp_path / "a.md")   # miss → extracts + caches
    extract_design(tmp_path / "b.md")   # same content hash → cache hit, no 2nd call
    assert calls["n"] == 1
