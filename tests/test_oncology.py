"""Offline tests for the oncology (NSCLC) generation profile — AMG510-style protocol.

Verifies the three requested domain fixes: oncology LB panel (no cardiac markers),
oncology QS instruments (QLQ-C30/LC13, EQ-5D-5L), arm-exact EX dosing, plus RECIST in RS.
"""

import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from protocol_to_data.generate import _profile_for, generate_dataset  # noqa: E402
from protocol_to_data.schemas import (  # noqa: E402
    Arm, DomainPlan, Population, ProtocolDesign, Visit,
)
from protocol_to_data.validate import validate_dataset  # noqa: E402


def _amg510_design() -> ProtocolDesign:
    return ProtocolDesign(
        study_id="AMG510-20190009",
        title="A Phase 3 Study of AMG 510 vs Docetaxel in NSCLC KRAS p.G12C",
        phase="3",
        therapeutic_area="Oncology",
        indication="Previously treated locally advanced/metastatic NSCLC with KRAS G12C",
        arms=[Arm(name="AMG 510"), Arm(name="Docetaxel")],
        visits=[Visit(name="Screening", day=-28, is_screening=True, is_treatment=False),
                Visit(name="Cycle 1 Day 1", day=1),
                Visit(name="Cycle 1 Day 8", day=8),
                Visit(name="Cycle 2 Day 1", day=22),
                Visit(name="Tumor Assessment Week 7", day=49),
                Visit(name="Tumor Assessment Week 13", day=91)],
        population=Population(n_subjects=20, sex="all"),
        domains=[DomainPlan(domain=d)
                 for d in ("DM", "VS", "LB", "QS", "AE", "EX", "RS", "EG", "PC", "TU", "TR")],
    )


def _dataset(tmp_path, seed=42):
    return generate_dataset(_amg510_design(), subjects=20, seed=seed, out_root=tmp_path, backend="builtin")


def test_profile_detected_as_oncology():
    assert _profile_for(_amg510_design()) == "oncology"


def test_generates_all_domains_and_validates(tmp_path):
    out = _dataset(tmp_path)
    for f in ("dm", "vs", "lb", "qs", "ae", "ex", "rs", "eg", "pc", "tu", "tr"):
        assert (out / f"{f}.csv").exists(), f"missing {f}.csv"
    report = validate_dataset(_amg510_design(), out)
    assert report.passed, [f.message for f in report.findings]


def test_lb_is_oncology_panel_not_cardiac(tmp_path):
    lb = pd.read_csv(_dataset(tmp_path) / "lb.csv")
    tests = set(lb["LBTESTCD"])
    assert "NTPROBNP" not in tests  # cardiac marker removed
    # hematology + chemistry + coagulation + thyroid all represented
    for expected in ("HGB", "NEUT", "PLT", "ALT", "AST", "INR", "APTT", "TSH", "FT4"):
        assert expected in tests, f"missing lab {expected}"
    # PK concentrations moved OUT of LB into the dedicated PC domain (CDISC-correct home)
    assert "SOTORASIB" not in tests and "DOCETAXEL" not in tests


def test_qs_is_oncology_instruments(tmp_path):
    qs = pd.read_csv(_dataset(tmp_path) / "qs.csv")
    tests = set(qs["QSTESTCD"])
    assert not ({"KCCQ12", "NYHA"} & tests)  # cardiac PROs removed
    assert {"QLQC30GH", "QLQLC13DYSP", "QLQLC13COUGH", "EQ5D5LVAS", "EQ5D5LIDX"} <= tests


def test_ex_assigns_exact_protocol_doses(tmp_path):
    out = _dataset(tmp_path)
    dm = pd.read_csv(out / "dm.csv")
    ex = pd.read_csv(out / "ex.csv").merge(dm[["USUBJID", "ARM"]], on="USUBJID")

    amg = ex[ex["ARM"] == "AMG 510"].iloc[0]
    assert amg["EXTRT"] == "AMG 510" and amg["EXDOSE"] == 960.0
    assert amg["EXDOSU"] == "mg" and amg["EXDOSFRQ"] == "QD" and amg["EXROUTE"] == "ORAL"

    doc = ex[ex["ARM"] == "Docetaxel"].iloc[0]
    assert doc["EXTRT"] == "Docetaxel" and doc["EXDOSE"] == 75.0
    assert doc["EXDOSU"] == "mg/m2" and doc["EXDOSFRQ"] == "Q3W" and doc["EXROUTE"] == "INTRAVENOUS"
    assert "STUDY DRUG" not in set(ex["EXTRT"])  # generic label gone


def test_rs_has_recist_responses(tmp_path):
    rs = pd.read_csv(_dataset(tmp_path) / "rs.csv")
    assert set(rs["RSTESTCD"]) == {"OVRLRESP"}
    assert set(rs["RSORRES"]) <= {"CR", "PR", "SD", "PD", "NE"}
    assert (rs["RSCAT"] == "RECIST 1.1").all()


def test_oncology_deterministic(tmp_path):
    a = _dataset(tmp_path / "a")
    b = _dataset(tmp_path / "b")
    for f in ("lb", "qs", "rs", "ex"):
        assert (a / f"{f}.csv").read_text() == (b / f"{f}.csv").read_text()


def test_pc_holds_pk_concentrations(tmp_path):
    pc = pd.read_csv(_dataset(tmp_path) / "pc.csv")
    assert not pc.empty
    assert set(pc["PCTESTCD"]) <= {"SOTORASIB", "DOCETAXEL"}   # PK now lives in PC, not LB
    assert (pc["PCORRESU"] == "ng/mL").all()


def test_eg_has_ecg_parameters(tmp_path):
    eg = pd.read_csv(_dataset(tmp_path) / "eg.csv")
    assert {"QT", "QTCF", "HR", "PR", "QRS"} <= set(eg["EGTESTCD"])


def test_tu_tr_recist_lesions_linked(tmp_path):
    out = _dataset(tmp_path)
    tu, tr = pd.read_csv(out / "tu.csv"), pd.read_csv(out / "tr.csv")
    assert (tu["TUTESTCD"] == "TUMIDENT").all() and (tu["TUORRES"] == "TARGET").all()
    assert (tr["TRTESTCD"] == "LDIAM").all()
    assert set(tr["TRLNKID"]) <= set(tu["TULNKID"])           # RECIST TR→TU link integrity
