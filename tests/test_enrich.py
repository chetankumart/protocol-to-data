"""Offline tests for the SDTM enrichment layer (full CDISC IG breadth).

Asserts the added variables are present, correct, and deterministic — DOMAIN, standardized
results (--STRESC/--STRESN/--STRESU), baseline flags, study day, LB reference ranges + --NRIND,
and the DM / AE / EX / CM context variables — without breaking validation or reproducibility.
"""

import filecmp
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from protocol_to_data.generate import generate_dataset  # noqa: E402
from protocol_to_data.schemas import (  # noqa: E402
    Arm, DomainPlan, Population, ProtocolDesign, Visit,
)
from protocol_to_data.validate import validate_dataset  # noqa: E402


def _design() -> ProtocolDesign:
    return ProtocolDesign(
        study_id="ONC-101",
        title="A Phase 3 Study of Drug X vs Docetaxel in NSCLC",
        phase="3",
        therapeutic_area="Oncology",
        indication="Metastatic NSCLC",
        arms=[Arm(name="Drug X + Chemo"), Arm(name="Docetaxel")],
        visits=[Visit(name="Screening", day=-28, is_screening=True, is_treatment=False),
                Visit(name="Cycle 1 Day 1", day=1),
                Visit(name="Cycle 2 Day 1", day=22),
                Visit(name="Tumor Assessment Week 7", day=49)],
        population=Population(n_subjects=12, sex="all"),
        domains=[DomainPlan(domain=d)
                 for d in ("DM", "VS", "LB", "QS", "AE", "EX", "CM", "RS", "EG", "PC", "TU", "TR")],
    )


def _gen(tmp_path, seed=7):
    out = generate_dataset(_design(), subjects=12, seed=seed, out_root=tmp_path)
    return {p.stem: pd.read_csv(p) for p in out.glob("*.csv")}, out


def test_domain_column_on_every_frame(tmp_path):
    frames, _ = _gen(tmp_path)
    for name, df in frames.items():
        assert "DOMAIN" in df.columns, f"{name} missing DOMAIN"
        assert (df["DOMAIN"] == name.upper()).all(), f"{name} DOMAIN mislabeled"


def test_full_breadth_column_counts(tmp_path):
    """Every domain expanded well beyond the lean core (was 6-10 cols)."""
    frames, _ = _gen(tmp_path)
    mins = {"dm": 18, "ae": 15, "lb": 20, "vs": 14, "ex": 12, "eg": 14,
            "pc": 15, "qs": 12, "tu": 13, "tr": 16, "rs": 12, "cm": 13}
    for name, floor in mins.items():
        assert len(frames[name].columns) >= floor, \
            f"{name} has only {len(frames[name].columns)} cols (< {floor})"


def test_dm_context_variables(tmp_path):
    frames, _ = _gen(tmp_path)
    dm = frames["dm"]
    for col in ("SUBJID", "AGEU", "RACE", "ETHNIC", "COUNTRY", "SITEID",
                "ARMCD", "ACTARM", "ACTARMCD", "RFENDTC", "DTHFL"):
        assert col in dm.columns, f"DM missing {col}"
    assert dm["ARMCD"].str.fullmatch(r"[A-Z0-9]+").all()   # alphanumeric, no punctuation leak
    assert dm["AGEU"].eq("YEARS").all()


def test_lb_reference_ranges_and_nrind(tmp_path):
    frames, _ = _gen(tmp_path)
    lb = frames["lb"]
    for col in ("LBTEST", "LBSTRESC", "LBSTRESN", "LBSTRESU",
                "LBORNRLO", "LBORNRHI", "LBNRIND", "LBBLFL", "LBDY"):
        assert col in lb.columns, f"LB missing {col}"
    # --NRIND agrees with the standardized value vs the standardized range, wherever all present
    graded = lb[(lb["LBNRIND"] != "") & lb["LBSTRESN"].apply(lambda x: str(x) != "")]
    for r in graded.itertuples():
        v, lo, hi = float(r.LBSTRESN), float(r.LBORNRLO), float(r.LBORNRHI)
        expect = "LOW" if v < lo else "HIGH" if v > hi else "NORMAL"
        assert r.LBNRIND == expect


def test_baseline_flag_exactly_one_per_subject_test(tmp_path):
    frames, _ = _gen(tmp_path)
    lb = frames["lb"]
    ys = lb[lb["LBBLFL"] == "Y"].groupby(["USUBJID", "LBTESTCD"]).size()
    assert (ys == 1).all() and len(ys) > 0


def test_standardized_numeric_blank_for_categorical(tmp_path):
    frames, _ = _gen(tmp_path)
    rs = frames["rs"]
    assert set(rs["RSSTRESC"]) <= {"CR", "PR", "SD", "PD", "NE"}
    # categorical result → no numeric standardized value (blank field reads back as NaN)
    assert pd.to_numeric(rs["RSSTRESN"], errors="coerce").isna().all()


def test_study_day_no_day_zero_and_onset_positive(tmp_path):
    frames, _ = _gen(tmp_path)
    ae = frames["ae"]
    for col in ("AEBODSYS", "AETOXGR", "AESER", "AEACN", "AEREL", "AEOUT",
                "AEENDTC", "AESTDY", "AEENDY"):
        assert col in ae.columns, f"AE missing {col}"
    dy = pd.to_numeric(ae["AESTDY"], errors="coerce").dropna()
    assert (dy != 0).all() and (dy >= 1).all()   # onset is on/after first dose; no day 0


def test_ex_and_cm_context(tmp_path):
    frames, _ = _gen(tmp_path)
    for col in ("EXDOSFRM", "EXENDTC", "EXSTDY", "EXENDY"):
        assert col in frames["ex"].columns
    for col in ("CMCAT", "CMDOSE", "CMDOSU", "CMDOSFRQ", "CMROUTE", "CMENDTC"):
        assert col in frames["cm"].columns


def test_enriched_dataset_still_validates(tmp_path):
    _, out = _gen(tmp_path)
    report = validate_dataset(_design(), out)
    assert report.passed, [f.message for f in report.findings]


def test_enrichment_is_deterministic(tmp_path):
    a = generate_dataset(_design(), subjects=12, seed=7, out_root=tmp_path / "a")
    b = generate_dataset(_design(), subjects=12, seed=7, out_root=tmp_path / "b")
    files = sorted(p.name for p in a.glob("*.csv"))
    assert files and all(filecmp.cmp(a / f, b / f, shallow=False) for f in files)
