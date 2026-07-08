"""Offline tests for SDTM dictionary coding — AEDECOD (MedDRA) and the CM domain (CMDECOD/WHODrug)."""

import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from protocol_to_data.generate import (  # noqa: E402
    _AE_CATALOG, _CM_CATALOG, generate_dataset,
)
from protocol_to_data.schemas import (  # noqa: E402
    Arm, DomainPlan, Population, ProtocolDesign, Visit,
)
from protocol_to_data.validate import validate_dataset  # noqa: E402


def _design() -> ProtocolDesign:
    return ProtocolDesign(
        study_id="HF-DICT", phase="3",
        arms=[Arm(name="DRUG-X"), Arm(name="PLACEBO", is_placebo=True)],
        visits=[Visit(name="BASELINE", day=1), Visit(name="WEEK4", day=28)],
        population=Population(n_subjects=30),
        domains=[DomainPlan(domain=d) for d in ("DM", "VS", "AE", "CM", "EX")],
    )


def _out(tmp_path):
    return generate_dataset(_design(), subjects=30, seed=42, out_root=tmp_path, backend="builtin")


def test_ae_has_meddra_coded_term(tmp_path):
    ae = pd.read_csv(_out(tmp_path) / "ae.csv")
    assert {"AETERM", "AEDECOD"}.issubset(ae.columns)
    # every reported (verbatim) term is coded to its MedDRA preferred term
    assert set(zip(ae["AETERM"], ae["AEDECOD"])) <= set(_AE_CATALOG["cardiology"])
    # the requested example mapping exists in the catalog
    assert ("bad headache", "Headache") in set(_AE_CATALOG["cardiology"])


def test_cm_domain_has_whodrug_coded_name(tmp_path):
    out = _out(tmp_path)
    assert (out / "cm.csv").exists()
    cm = pd.read_csv(out / "cm.csv")
    assert {"CMTRT", "CMDECOD", "CMSTDTC"}.issubset(cm.columns)
    assert set(zip(cm["CMTRT"], cm["CMDECOD"])) <= set(_CM_CATALOG["cardiology"])
    assert ("lasix", "Furosemide") in set(_CM_CATALOG["cardiology"])


def test_dictionary_columns_pass_validation(tmp_path):
    report = validate_dataset(_design(), _out(tmp_path))
    assert report.passed, [f.message for f in report.findings]


def test_oncology_ae_uses_oncology_catalog(tmp_path):
    onc = ProtocolDesign(
        study_id="ONC-DICT", phase="3", therapeutic_area="Oncology", indication="NSCLC",
        arms=[Arm(name="AMG 510"), Arm(name="Docetaxel")],
        visits=[Visit(name="C1D1", day=1), Visit(name="C2D1", day=22)],
        population=Population(n_subjects=30),
        domains=[DomainPlan(domain=d) for d in ("DM", "AE", "CM")],
    )
    out = generate_dataset(onc, subjects=30, seed=7, out_root=tmp_path, backend="builtin")
    ae = pd.read_csv(out / "ae.csv")
    assert set(zip(ae["AETERM"], ae["AEDECOD"])) <= set(_AE_CATALOG["oncology"])
