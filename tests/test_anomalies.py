"""Offline tests for anomaly injection + scoring (detection needs a key and is mocked away)."""

import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from protocol_to_data.anomalies import (  # noqa: E402
    _inject_orphan, _inject_pregnancy_male, inject_anomalies, score_detections,
)
from protocol_to_data.generate import generate_dataset  # noqa: E402
from protocol_to_data.schemas import (  # noqa: E402
    AnomalyFinding, Arm, DomainPlan, Population, ProtocolDesign, Visit,
)
from protocol_to_data.validate import validate_dataset  # noqa: E402


def _design() -> ProtocolDesign:
    return ProtocolDesign(
        study_id="HF-ANOM", phase="3",
        arms=[Arm(name="DRUG-X"), Arm(name="PLACEBO", is_placebo=True)],
        visits=[Visit(name="SCREEN", day=-14, is_screening=True, is_treatment=False),
                Visit(name="BASELINE", day=1), Visit(name="WEEK4", day=28)],
        population=Population(n_subjects=20, sex="all"),
        domains=[DomainPlan(domain=d) for d in ("DM", "VS", "LB", "QS", "AE", "EX")],
    )


def _dataset(tmp_path, seed=42):
    return generate_dataset(_design(), subjects=20, seed=seed, out_root=tmp_path, backend="builtin")


def test_inject_returns_ground_truth_and_breaks_validation(tmp_path):
    out = _dataset(tmp_path)
    truth = inject_anomalies(out, count=5, seed=42)
    assert len(truth) == 5
    assert all({"type", "domain", "usubjid"} <= set(t) for t in truth)
    # several injected defects are also deterministically catchable → validation must now fail
    assert not validate_dataset(_design(), out).passed


def test_inject_deterministic(tmp_path):
    a, b = _dataset(tmp_path / "a"), _dataset(tmp_path / "b")
    assert inject_anomalies(a, count=5, seed=7) == inject_anomalies(b, count=5, seed=7)


def test_orphan_prefers_lb(tmp_path):
    out = _dataset(tmp_path)
    import random
    rec = _inject_orphan(out, random.Random(0))
    assert rec["domain"] == "LB" and rec["usubjid"] == "GHOST-9999"
    lb = pd.read_csv(out / "lb.csv")
    assert "GHOST-9999" in set(lb["USUBJID"])


def test_pregnancy_injected_for_male(tmp_path):
    out = _dataset(tmp_path)
    import random
    rec = _inject_pregnancy_male(out, random.Random(0))
    assert rec is not None and rec["type"] == "logical" and rec["domain"] == "AE"
    dm = pd.read_csv(out / "dm.csv")
    ae = pd.read_csv(out / "ae.csv")
    preg = ae[ae["AETERM"] == "PREGNANCY"]
    assert not preg.empty
    uid = preg["USUBJID"].iloc[0]
    assert dm.loc[dm["USUBJID"] == uid, "SEX"].iloc[0] == "M"  # planted on a male subject


def test_score_detections_matches_by_type_and_domain():
    truth = [
        {"type": "temporal", "domain": "AE", "usubjid": "S1"},
        {"type": "physiologic", "domain": "VS", "usubjid": "S2"},
        {"type": "referential", "domain": "LB", "usubjid": "GHOST-9999"},
    ]
    findings = [
        AnomalyFinding(domain="AE", anomaly_type="temporal", description="pre-dose AE"),
        AnomalyFinding(domain="vs", anomaly_type="physiologic", description="SBP 400"),
        AnomalyFinding(domain="QS", anomaly_type="uniqueness", description="spurious extra"),
    ]
    score = score_detections(truth, findings)
    assert score["caught"] == 2 and score["total"] == 3
    assert [m["domain"] for m in score["missed"]] == ["LB"]
    assert len(score["extra"]) == 1  # the spurious QS finding
