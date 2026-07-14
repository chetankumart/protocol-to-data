"""Offline tests for anomaly injection + scoring (detection needs a key and is mocked away).

v2 pivot: injectors plant schema-VALID but pharmacologically implausible defects — so deterministic
validation still PASSES (that's the point; only clinical reasoning catches them).
"""

import random
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from protocol_to_data.anomalies import (  # noqa: E402
    _inject_dose_response_reversal, _inject_placebo_severe_ae, inject_anomalies, score_detections,
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


def test_inject_returns_ground_truth_and_stays_schema_valid(tmp_path):
    out = _dataset(tmp_path)
    truth = inject_anomalies(out, count=5, seed=42)
    assert len(truth) == 3  # three clinical-plausibility injectors available
    assert all({"type", "domain", "usubjid"} <= set(t) for t in truth)
    assert {t["type"] for t in truth} <= {"pharmacologic", "dose_response", "severity"}
    # The whole point of the pivot: these are pharmacological defects, NOT schema/integrity errors,
    # so deterministic validation STILL PASSES — only clinical reasoning can catch them.
    assert validate_dataset(_design(), out).passed


def test_inject_deterministic(tmp_path):
    a, b = _dataset(tmp_path / "a"), _dataset(tmp_path / "b")
    assert inject_anomalies(a, count=5, seed=7) == inject_anomalies(b, count=5, seed=7)


def test_placebo_severe_ae_lands_on_placebo_arm(tmp_path):
    out = _dataset(tmp_path)
    rec = _inject_placebo_severe_ae(out, random.Random(0))
    assert rec is not None and rec["type"] == "pharmacologic" and rec["domain"] == "AE"
    dm, ae = pd.read_csv(out / "dm.csv"), pd.read_csv(out / "ae.csv")
    fn = ae[ae["AETERM"] == "Febrile neutropenia"]
    assert not fn.empty and (fn["AESEV"] == "SEVERE").all()
    uid = fn["USUBJID"].iloc[0]
    assert "PLACEBO" in dm.loc[dm["USUBJID"] == uid, "ARM"].iloc[0].upper()   # planted on placebo


def test_dose_response_reversal_hits_drug_arm_marker(tmp_path):
    out = _dataset(tmp_path)
    rec = _inject_dose_response_reversal(out, random.Random(0))
    assert rec is not None and rec["type"] == "dose_response" and rec["domain"] == "LB"
    dm, lb = pd.read_csv(out / "dm.csv"), pd.read_csv(out / "lb.csv")
    placebo = set(dm[dm["ARM"].str.contains("PLACEBO", case=False)]["USUBJID"])
    assert rec["usubjid"] not in placebo                                     # only active-drug arm
    drug_bnp = lb[(lb["LBTESTCD"] == "NTPROBNP") & (~lb["USUBJID"].isin(placebo))]
    assert not drug_bnp.empty and (drug_bnp["LBORRES"] == 3000.0).all()      # flattened to reversed value


def test_score_detections_matches_by_type_and_domain():
    truth = [
        {"type": "pharmacologic", "domain": "AE", "usubjid": "S1"},
        {"type": "dose_response", "domain": "LB", "usubjid": "S2"},
        {"type": "severity", "domain": "AE", "usubjid": "S3"},
    ]
    findings = [
        AnomalyFinding(domain="AE", anomaly_type="pharmacologic", description="severe AE on placebo"),
        AnomalyFinding(domain="lb", anomaly_type="dose_response", description="NT-proBNP flat on drug"),
        AnomalyFinding(domain="QS", anomaly_type="severity", description="spurious extra"),
    ]
    score = score_detections(truth, findings)
    assert score["caught"] == 2 and score["total"] == 3
    assert [m["domain"] for m in score["missed"]] == ["AE"]   # the (severity, AE) truth unmatched
    assert len(score["extra"]) == 1                            # the spurious QS finding
