"""Stage 5 — VALIDATE: schema + clinical-rule checks over the generated dataset.

Deterministic. Produces a ValidationReport that the loop feeds back to Claude on repair.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from .schemas import ProtocolDesign, ValidationFinding, ValidationReport

REQUIRED_COLUMNS = {
    "dm": {"STUDYID", "USUBJID", "ARM", "AGE", "SEX", "RFSTDTC"},
    "vs": {"USUBJID", "VSTESTCD", "VSORRES", "VSDTC"},
    "ae": {"USUBJID", "AETERM", "AESTDTC"},
    "ex": {"USUBJID", "EXTRT", "EXSTDTC"},
}

VITAL_BOUNDS = {"SYSBP": (60, 260), "DIABP": (30, 160), "PULSE": (30, 200)}


def validate_dataset(design: ProtocolDesign, data_dir: str | Path) -> ValidationReport:
    data_dir = Path(data_dir)
    findings: list[ValidationFinding] = []

    csvs = {p.stem: p for p in data_dir.glob("*.csv")}
    frames = {name: pd.read_csv(p) for name, p in csvs.items()}

    # non-empty + schema
    for name, df in frames.items():
        if df.empty:
            findings.append(ValidationFinding(check="non-empty", domain=name.upper(),
                                              message=f"{name}.csv has no rows"))
        req = REQUIRED_COLUMNS.get(name)
        if req and not req.issubset(df.columns):
            missing = req - set(df.columns)
            findings.append(ValidationFinding(check="schema", domain=name.upper(),
                                              message=f"missing columns: {sorted(missing)}"))

    dm = frames.get("dm")
    if dm is None or dm.empty:
        findings.append(ValidationFinding(check="non-empty", domain="DM",
                                          message="DM is required and missing/empty"))
        return ValidationReport(study_id=design.study_id, passed=False, findings=findings)

    dm_ids = set(dm["USUBJID"])
    rfst = dict(zip(dm["USUBJID"], pd.to_datetime(dm["RFSTDTC"], errors="coerce")))

    # referential integrity
    for name, df in frames.items():
        if name == "dm" or "USUBJID" not in df.columns:
            continue
        orphans = set(df["USUBJID"]) - dm_ids
        if orphans:
            findings.append(ValidationFinding(check="referential", domain=name.upper(),
                                              message=f"{len(orphans)} USUBJID not in DM",
                                              count=len(orphans)))

    # temporal: no pre-dose AEs
    ae = frames.get("ae")
    if ae is not None and not ae.empty and "AESTDTC" in ae.columns:
        onset = pd.to_datetime(ae["AESTDTC"], errors="coerce")
        predose = sum(1 for uid, d in zip(ae["USUBJID"], onset)
                      if uid in rfst and pd.notna(d) and d < rfst[uid])
        if predose:
            findings.append(ValidationFinding(check="dates", domain="AE",
                                              message=f"{predose} pre-dose adverse events (AESTDTC < RFSTDTC)",
                                              count=predose))

    # physiologic ranges
    vs = frames.get("vs")
    if vs is not None and not vs.empty and {"VSTESTCD", "VSORRES"}.issubset(vs.columns):
        oob = 0
        for tc, (lo, hi) in VITAL_BOUNDS.items():
            sub = pd.to_numeric(vs.loc[vs["VSTESTCD"] == tc, "VSORRES"], errors="coerce")
            oob += int(((sub < lo) | (sub > hi)).sum())
        if oob:
            findings.append(ValidationFinding(check="ranges", domain="VS",
                                              message=f"{oob} out-of-range vital signs", count=oob))

    # sex consistency (pregnancy-style female-only forms)
    for name, df in frames.items():
        if "PREG" in name.upper() and "USUBJID" in df.columns:
            male = dm[dm["SEX"] == "M"]["USUBJID"]
            bad = set(df["USUBJID"]) & set(male)
            if bad:
                findings.append(ValidationFinding(check="sex-consistency", domain=name.upper(),
                                                  message=f"{len(bad)} male subjects in female-only form",
                                                  count=len(bad)))

    passed = not any(f.severity == "high" for f in findings)
    return ValidationReport(study_id=design.study_id, passed=passed, findings=findings)
