"""Offline tests for SDTM dictionary coding — code_term mapper + AEDECOD/CMDECOD population."""

import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from protocol_to_data.generate import (  # noqa: E402
    _AE_DICTIONARY, _CM_DICTIONARY, code_term, generate_dataset,
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


def test_code_term_maps_known_and_falls_back():
    d = _AE_DICTIONARY["cardiology"]
    assert code_term("bad headache", d) == "Headache"        # requested example mapping
    assert code_term("dizzy spells", d) == "Dizziness"
    # a term not in the dictionary → normalized fallback (strip qualifier, Title Case)
    assert code_term("bad sunburn", d) == "Sunburn"
    assert code_term("PREGNANCY", {}) == "Pregnancy"


def test_ae_aedecod_matches_dictionary(tmp_path):
    ae = pd.read_csv(_out(tmp_path) / "ae.csv")
    assert {"AETERM", "AEDECOD"}.issubset(ae.columns)
    d = _AE_DICTIONARY["cardiology"]
    for term, decod in zip(ae["AETERM"], ae["AEDECOD"]):
        assert d[term] == decod  # every reported term is coded to its MedDRA PT


def test_cm_cmdecod_matches_dictionary(tmp_path):
    out = _out(tmp_path)
    assert (out / "cm.csv").exists()
    cm = pd.read_csv(out / "cm.csv")
    assert {"CMTRT", "CMDECOD", "CMSTDTC"}.issubset(cm.columns)
    d = _CM_DICTIONARY["cardiology"]
    for trt, decod in zip(cm["CMTRT"], cm["CMDECOD"]):
        assert d[trt] == decod
    assert d["lasix"] == "Furosemide"


def test_dictionary_columns_pass_validation(tmp_path):
    report = validate_dataset(_design(), _out(tmp_path))
    assert report.passed, [f.message for f in report.findings]


def test_oncology_ae_uses_oncology_dictionary(tmp_path):
    onc = ProtocolDesign(
        study_id="ONC-DICT", phase="3", therapeutic_area="Oncology", indication="NSCLC",
        arms=[Arm(name="AMG 510"), Arm(name="Docetaxel")],
        visits=[Visit(name="C1D1", day=1), Visit(name="C2D1", day=22)],
        population=Population(n_subjects=30),
        domains=[DomainPlan(domain=d) for d in ("DM", "AE", "CM")],
    )
    ae = pd.read_csv(generate_dataset(onc, subjects=30, seed=7, out_root=tmp_path) / "ae.csv")
    d = _AE_DICTIONARY["oncology"]
    for term, decod in zip(ae["AETERM"], ae["AEDECOD"]):
        assert d[term] == decod
