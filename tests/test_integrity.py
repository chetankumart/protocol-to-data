"""Offline tests for SDTM relational integrity: USUBJID FK, consistent VISITNUM, orphan repair."""

import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from protocol_to_data.generate import (  # noqa: E402
    _enforce_referential_integrity, _profile_for, generate_dataset,
)
from protocol_to_data.schemas import (  # noqa: E402
    Arm, DomainPlan, Population, ProtocolDesign, Visit,
)


def _design() -> ProtocolDesign:
    return ProtocolDesign(
        study_id="ONC-RI", phase="3", therapeutic_area="Oncology", indication="NSCLC",
        arms=[Arm(name="AMG 510"), Arm(name="Docetaxel")],
        visits=[Visit(name="Screening", day=-28, is_screening=True, is_treatment=False),
                Visit(name="C1D1", day=1), Visit(name="C1D8", day=8), Visit(name="C2D1", day=22),
                Visit(name="Tumor Wk7", day=49), Visit(name="Tumor Wk13", day=91)],
        population=Population(n_subjects=20),
        domains=[DomainPlan(domain=d) for d in ("DM", "VS", "LB", "QS", "AE", "EX", "CM", "RS")],
    )


def _out(tmp_path):
    return generate_dataset(_design(), subjects=20, seed=42, out_root=tmp_path, backend="builtin")


def test_all_child_usubjids_exist_in_dm(tmp_path):
    out = _out(tmp_path)
    dm_ids = set(pd.read_csv(out / "dm.csv")["USUBJID"])
    for child in ("vs", "lb", "qs", "ae", "ex", "cm", "rs"):
        df = pd.read_csv(out / f"{child}.csv")
        assert set(df["USUBJID"]) <= dm_ids, f"orphan USUBJID in {child}"


def test_visitnum_consistent_across_longitudinal_domains(tmp_path):
    out = _out(tmp_path)
    ref = None
    for dom in ("vs", "lb", "qs", "rs"):
        df = pd.read_csv(out / f"{dom}.csv")
        assert "VISITNUM" in df.columns
        mapping = dict(df[["VISIT", "VISITNUM"]].drop_duplicates().itertuples(index=False))
        if ref is None:
            ref = mapping
        else:
            shared = set(ref) & set(mapping)
            for visit in shared:
                assert ref[visit] == mapping[visit], f"VISITNUM mismatch for {visit} in {dom}"


def test_enforce_drops_orphan_rows(tmp_path):
    dm = pd.DataFrame({"USUBJID": ["S1", "S2"]})
    child = pd.DataFrame({"USUBJID": ["S1", "GHOST-9999", "S2"], "LBORRES": [1, 2, 3]})
    frames = {"dm": dm, "lb": child}
    _enforce_referential_integrity(frames)  # must not raise; drops the orphan
    assert set(frames["lb"]["USUBJID"]) == {"S1", "S2"}
    assert len(frames["lb"]) == 2


def test_enforce_rejects_inconsistent_visitnum():
    """Same VISIT mapped to different VISITNUMs across domains must fail the guard."""
    dm = pd.DataFrame({"USUBJID": ["S1"]})
    vs = pd.DataFrame({"USUBJID": ["S1"], "VISIT": ["Baseline"], "VISITNUM": [2.0]})
    lb = pd.DataFrame({"USUBJID": ["S1"], "VISIT": ["Baseline"], "VISITNUM": [3.0]})  # drift!
    with pytest.raises(AssertionError):
        _enforce_referential_integrity({"dm": dm, "vs": vs, "lb": lb})


def test_profile_dispatch_does_not_misfire_on_generic_terms():
    # "tumor necrosis factor" must NOT trigger oncology on a cardiology protocol
    cardio = ProtocolDesign(
        study_id="HF-TNF", therapeutic_area="Cardiovascular",
        indication="Heart failure; elevated tumor necrosis factor alpha",
        domains=[DomainPlan(domain="DM")])
    assert _profile_for(cardio) == "cardiology"
    # a real oncology study still resolves to oncology (via therapeutic_area)
    onc = ProtocolDesign(study_id="ONC", therapeutic_area="Oncology", indication="NSCLC",
                         domains=[DomainPlan(domain="DM")])
    assert _profile_for(onc) == "oncology"
