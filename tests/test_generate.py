"""Offline tests for Day-3 generation: LB + QS domains, trajectories, date anchoring."""

import sys
from datetime import date
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from protocol_to_data.generate import _visit_date, generate_dataset  # noqa: E402
from protocol_to_data.schemas import (  # noqa: E402
    Arm, DomainPlan, Endpoint, Population, ProtocolDesign, Visit,
)
from protocol_to_data.validate import validate_dataset  # noqa: E402


def _full_design() -> ProtocolDesign:
    return ProtocolDesign(
        study_id="HF-FULL",
        phase="3",
        arms=[Arm(name="DRUG-X", n_planned=20), Arm(name="PLACEBO", n_planned=20, is_placebo=True)],
        visits=[Visit(name="SCREEN", day=-14, is_screening=True, is_treatment=False),
                Visit(name="BASELINE", day=1),
                Visit(name="WEEK4", day=28),
                Visit(name="WEEK12", day=84),
                Visit(name="WEEK24", day=168)],
        endpoints=[Endpoint(name="KCCQ", type="primary", domain="QS", measure="score"),
                   Endpoint(name="NTproBNP", type="secondary", domain="LB", measure="pg/mL")],
        population=Population(n_subjects=20, sex="all"),
        domains=[DomainPlan(domain="DM"), DomainPlan(domain="VS"), DomainPlan(domain="LB"),
                 DomainPlan(domain="QS"), DomainPlan(domain="AE"), DomainPlan(domain="EX")],
    )


def test_lb_qs_generated_and_valid(tmp_path):
    out = generate_dataset(_full_design(), subjects=20, seed=42, out_root=tmp_path, backend="builtin")
    assert (out / "lb.csv").exists() and (out / "qs.csv").exists()

    lb = pd.read_csv(out / "lb.csv")
    qs = pd.read_csv(out / "qs.csv")
    assert {"USUBJID", "LBTESTCD", "LBORRES", "LBDTC"}.issubset(lb.columns)
    assert {"USUBJID", "QSTESTCD", "QSORRES", "QSDTC"}.issubset(qs.columns)
    assert set(lb["LBTESTCD"]) == {"NTPROBNP", "CREAT", "HGB", "K"}
    assert set(qs["QSTESTCD"]) == {"KCCQ12", "NYHA"}

    report = validate_dataset(_full_design(), out)
    assert report.passed, [f.message for f in report.findings]


def test_qs_excludes_screening(tmp_path):
    out = generate_dataset(_full_design(), subjects=10, seed=1, out_root=tmp_path, backend="builtin")
    qs = pd.read_csv(out / "qs.csv")
    assert "SCREEN" not in set(qs["VISIT"])  # PROs collected from baseline onward


def test_lb_trajectory_declines_on_drug(tmp_path):
    """NT-proBNP should fall across visits for an active-drug subject."""
    out = generate_dataset(_full_design(), subjects=20, seed=42, out_root=tmp_path, backend="builtin")
    dm = pd.read_csv(out / "dm.csv")
    lb = pd.read_csv(out / "lb.csv")
    drug_id = dm[dm["ARM"] == "DRUG-X"]["USUBJID"].iloc[0]

    bnp = lb[(lb["USUBJID"] == drug_id) & (lb["LBTESTCD"] == "NTPROBNP")]
    bnp = bnp.sort_values("LBDTC")["LBORRES"].tolist()
    assert bnp[-1] < bnp[0], f"expected decline, got {bnp}"


def test_kccq_improves_more_on_drug(tmp_path):
    """Mean KCCQ at the final visit should exceed baseline (aggregate over subjects)."""
    out = generate_dataset(_full_design(), subjects=20, seed=42, out_root=tmp_path, backend="builtin")
    qs = pd.read_csv(out / "qs.csv")
    kccq = qs[qs["QSTESTCD"] == "KCCQ12"].copy()
    first_visit = sorted(kccq["QSDTC"].unique())[0]
    last_visit = sorted(kccq["QSDTC"].unique())[-1]
    assert kccq[kccq["QSDTC"] == last_visit]["QSORRES"].mean() > \
        kccq[kccq["QSDTC"] == first_visit]["QSORRES"].mean()


def test_lb_qs_deterministic(tmp_path):
    a = generate_dataset(_full_design(), subjects=12, seed=7, out_root=tmp_path / "a", backend="builtin")
    b = generate_dataset(_full_design(), subjects=12, seed=7, out_root=tmp_path / "b", backend="builtin")
    assert (a / "lb.csv").read_text() == (b / "lb.csv").read_text()
    assert (a / "qs.csv").read_text() == (b / "qs.csv").read_text()


def test_screening_date_anchored_before_first_dose():
    rfst = date(2026, 3, 1)
    assert _visit_date(rfst, 1) == rfst                    # first dose = RFSTDTC
    assert _visit_date(rfst, -14) < rfst                   # screening precedes dosing
    assert _visit_date(rfst, 28) == date(2026, 3, 28)      # week 4 = +27d
