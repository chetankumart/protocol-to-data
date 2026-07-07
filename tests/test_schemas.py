"""Smoke tests for schemas + deterministic generation/validation (no API key needed)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from protocol_to_data.generate import generate_dataset  # noqa: E402
from protocol_to_data.schemas import (  # noqa: E402
    Arm, DomainPlan, Endpoint, Population, ProtocolDesign, Visit,
)
from protocol_to_data.validate import validate_dataset  # noqa: E402


def _demo_design() -> ProtocolDesign:
    return ProtocolDesign(
        study_id="TEST-HF",
        phase="3",
        therapeutic_area="cardiovascular",
        arms=[Arm(name="DRUG-X", n_planned=20), Arm(name="PLACEBO", n_planned=20, is_placebo=True)],
        visits=[Visit(name="SCREEN", day=-14, is_screening=True, is_treatment=False),
                Visit(name="BASELINE", day=1), Visit(name="WEEK4", day=28)],
        endpoints=[Endpoint(name="SBP", type="secondary", domain="VS", measure="mmHg")],
        population=Population(n_subjects=20, sex="all"),
        domains=[DomainPlan(domain="DM"), DomainPlan(domain="VS"),
                 DomainPlan(domain="AE"), DomainPlan(domain="EX")],
    )


def test_design_roundtrip():
    d = _demo_design()
    assert ProtocolDesign.model_validate_json(d.model_dump_json()) == d
    assert set(d.domain_names()) == {"DM", "VS", "AE", "EX"}


def test_generate_and_validate_clean(tmp_path):
    design = _demo_design()
    out_dir = generate_dataset(design, subjects=20, seed=42, out_root=tmp_path, backend="builtin")
    assert (out_dir / "dm.csv").exists()
    report = validate_dataset(design, out_dir)
    assert report.passed, [f.message for f in report.findings]
    assert report.error_count == 0


def test_generation_is_deterministic(tmp_path):
    design = _demo_design()
    a = generate_dataset(design, subjects=15, seed=7, out_root=tmp_path / "a", backend="builtin")
    b = generate_dataset(design, subjects=15, seed=7, out_root=tmp_path / "b", backend="builtin")
    assert (a / "dm.csv").read_text() == (b / "dm.csv").read_text()


def test_validate_catches_predose_ae(tmp_path):
    import pandas as pd
    design = _demo_design()
    out_dir = generate_dataset(design, subjects=10, seed=1, out_root=tmp_path, backend="builtin")
    ae = pd.read_csv(out_dir / "ae.csv")
    if not ae.empty:
        ae.loc[0, "AESTDTC"] = "2000-01-01"
        ae.to_csv(out_dir / "ae.csv", index=False)
        report = validate_dataset(design, out_dir)
        assert not report.passed
        assert any("pre-dose" in f.message for f in report.findings)
