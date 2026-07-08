"""Offline tests for SDTM relational integrity: USUBJID FK, consistent VISITNUM, orphan repair."""

import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from protocol_to_data.generate import (  # noqa: E402
    _enforce_referential_integrity, generate_dataset,
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
