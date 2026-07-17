"""Stage 4b — ENRICH: expand the lean per-domain frames to full CDISC SDTM breadth.

The generators in ``generate.py`` emit the *analyzable core* of each domain (identifiers, the
topic-result-unit triplet, timing). This layer adds the rest of the SDTM variable set a
reviewer expects — ``DOMAIN``; standardized results (``--STRESC/--STRESN/--STRESU``); baseline
flags (``--BLFL``); study day (``--DY``); test-name decodes (``--TEST``); LB reference ranges +
``--NRIND``; and the DM / AE / EX / CM context variables (RACE, ARMCD, AEBODSYS, EXENDTC, …).

Design contract: **enrichment derives every added value deterministically from data already on
the row** (ids, dates, results, test codes) — it never draws from the generator's shared RNG.
So the clinically-meaningful values the generators produced are unchanged and reproducible; this
step only *adds columns*. Categorical fills (RACE, AEREL, …) are chosen by a stable hash of the
row key, so they're varied but fully reproducible across processes and runs.
"""

from __future__ import annotations

import hashlib
from datetime import date

import pandas as pd

from .schemas import ProtocolDesign

# Findings-class domains carry the topic-result-unit + standardized-result pattern.
_FINDINGS = {"VS", "LB", "EG", "PC", "QS", "RS", "TR", "TU"}
# Domains where a baseline flag (--BLFL) is meaningful (repeated pre/post-dose measurements).
_BLFL_DOMAINS = {"VS", "LB", "EG", "QS"}


# --------------------------------------------------------------------------- decode tables

_TESTCD_DECODE = {
    # VS
    "SYSBP": "Systolic Blood Pressure", "DIABP": "Diastolic Blood Pressure", "PULSE": "Pulse Rate",
    # EG (ECG)
    "QT": "QT Interval", "QTCF": "QTcF Interval", "HR": "Heart Rate",
    "PR": "PR Interval", "QRS": "QRS Duration",
    # LB
    "HGB": "Hemoglobin", "WBC": "Leukocytes", "NEUT": "Neutrophils", "LYM": "Lymphocytes",
    "PLT": "Platelets", "CREAT": "Creatinine", "ALT": "Alanine Aminotransferase",
    "AST": "Aspartate Aminotransferase", "BILI": "Bilirubin", "ALP": "Alkaline Phosphatase",
    "ALB": "Albumin", "SODIUM": "Sodium", "K": "Potassium", "CALCIUM": "Calcium", "INR": "INR",
    "PT": "Prothrombin Time", "APTT": "Activated Partial Thromboplastin Time", "TSH": "Thyrotropin",
    "FT4": "Thyroxine, Free", "NTPROBNP": "Natriuretic Peptide B Prohormone N-Terminal",
    # QS
    "KCCQ12": "KCCQ-12 Summary Score", "NYHA": "NYHA Classification",
    "QLQC30GH": "QLQ-C30 Global Health Status", "QLQLC13DYSP": "QLQ-LC13 Dyspnoea",
    "QLQLC13COUGH": "QLQ-LC13 Coughing", "EQ5D5LVAS": "EQ-5D-5L VAS", "EQ5D5LIDX": "EQ-5D-5L Index",
    # RS / TU / TR
    "OVRLRESP": "Overall Response", "TUMIDENT": "Tumor Identification", "LDIAM": "Longest Diameter",
}

# VS default original units (VS generator emits no unit).
_VS_UNITS = {"SYSBP": "mmHg", "DIABP": "mmHg", "PULSE": "beats/min"}

# LB reference ranges (adult): testcd -> (low, high). Drives --ORNRLO/HI, --STNRLO/HI, --NRIND.
_LB_REF = {
    "HGB": (12.0, 17.5), "WBC": (4.0, 11.0), "NEUT": (2.0, 7.5), "LYM": (1.0, 4.0),
    "PLT": (150, 400), "CREAT": (0.6, 1.3), "ALT": (7, 56), "AST": (10, 40), "BILI": (0.1, 1.2),
    "ALP": (44, 147), "ALB": (3.5, 5.0), "SODIUM": (135, 145), "K": (3.5, 5.1),
    "CALCIUM": (8.6, 10.3), "INR": (0.8, 1.2), "PT": (11, 13.5), "APTT": (25, 35),
    "TSH": (0.4, 4.0), "FT4": (0.8, 1.8), "NTPROBNP": (0, 125),
}

# AEDECOD (MedDRA PT) -> System Organ Class, for AEBODSYS.
_AE_SOC = {
    "Febrile neutropenia": "Blood and lymphatic system disorders",
    "Neutropenia": "Blood and lymphatic system disorders",
    "Anaemia": "Blood and lymphatic system disorders",
    "Nausea": "Gastrointestinal disorders", "Vomiting": "Gastrointestinal disorders",
    "Diarrhoea": "Gastrointestinal disorders",
    "Fatigue": "General disorders and administration site conditions",
    "Headache": "Nervous system disorders", "Dizziness": "Nervous system disorders",
    "Peripheral sensory neuropathy": "Nervous system disorders",
    "Alopecia": "Skin and subcutaneous tissue disorders", "Hypotension": "Vascular disorders",
    "Decreased appetite": "Metabolism and nutrition disorders",
    "Alanine aminotransferase increased": "Investigations",
}
_AE_TOXGR = {"MILD": "1", "MODERATE": "2", "SEVERE": "3"}
_AE_ACN = ["DOSE NOT CHANGED", "DOSE REDUCED", "DRUG INTERRUPTED", "DRUG WITHDRAWN"]
_AE_REL = ["NOT RELATED", "UNLIKELY RELATED", "POSSIBLY RELATED", "RELATED"]
_AE_OUT = ["RECOVERED/RESOLVED", "RECOVERING/RESOLVING", "NOT RECOVERED/NOT RESOLVED"]

_RACES = ["WHITE", "ASIAN", "BLACK OR AFRICAN AMERICAN",
          "AMERICAN INDIAN OR ALASKA NATIVE", "NATIVE HAWAIIAN OR OTHER PACIFIC ISLANDER"]
_ETHNIC = ["HISPANIC OR LATINO", "NOT HISPANIC OR LATINO"]
_COUNTRIES = ["USA", "GBR", "DEU", "FRA", "ESP", "CHN", "JPN", "AUS", "CAN"]


# --------------------------------------------------------------------------- small helpers

def _stable_pick(key: str, options: list):
    """Deterministic, well-distributed choice from ``options`` keyed by ``key`` (hash-based, so
    it's stable across processes — unlike the salted built-in ``hash()``)."""
    h = int(hashlib.md5(key.encode("utf-8")).hexdigest(), 16)  # noqa: S324 — non-crypto, just a stable hash
    return options[h % len(options)]


def _study_day(dtc, rfst) -> object:
    """SDTM study day for a --DTC vs the subject's RFSTDTC (no day 0: day 1 == first dose)."""
    if rfst is None or not isinstance(dtc, str) or len(dtc) < 10:
        return ""
    try:
        d = date.fromisoformat(dtc[:10])
    except ValueError:
        return ""
    delta = (d - rfst).days
    return delta + 1 if delta >= 0 else delta


def _decode(code: str) -> str:
    return _TESTCD_DECODE.get(code, str(code).replace("_", " ").title())


def _reorder(df: pd.DataFrame, order: list[str]) -> pd.DataFrame:
    """Put known columns first in canonical SDTM order; append any extras in their current order."""
    front = [c for c in order if c in df.columns]
    rest = [c for c in df.columns if c not in front]
    return df[front + rest]


# --------------------------------------------------------------------------- generic enrichers

def _add_domain(df: pd.DataFrame, dom: str) -> None:
    df["DOMAIN"] = dom


def _add_test(df: pd.DataFrame, dom: str) -> None:
    tc, ts = f"{dom}TESTCD", f"{dom}TEST"
    if tc in df.columns:
        df[ts] = df[tc].map(_decode)


def _add_standardized(df: pd.DataFrame, dom: str) -> None:
    """--STRESC (char), --STRESN (numeric or blank), --STRESU (= original unit)."""
    orres, orresu = f"{dom}ORRES", f"{dom}ORRESU"
    if orres not in df.columns:
        return
    df[f"{dom}STRESC"] = df[orres].astype(str)
    num = pd.to_numeric(df[orres], errors="coerce")
    df[f"{dom}STRESN"] = num.where(num.notna(), "")     # blank for categorical results (e.g. RECIST)
    if orresu in df.columns:
        df[f"{dom}STRESU"] = df[orresu]


def _add_baseline_flag(df: pd.DataFrame, dom: str) -> None:
    """--BLFL = 'Y' on the earliest record per (USUBJID, --TESTCD) by VISITNUM; else blank."""
    tc = f"{dom}TESTCD"
    if not {"USUBJID", "VISITNUM", tc}.issubset(df.columns) or df.empty:
        return
    idx = df.groupby(["USUBJID", tc])["VISITNUM"].idxmin()
    flag = pd.Series("", index=df.index)
    flag.loc[idx] = "Y"
    df[f"{dom}BLFL"] = flag.values


def _add_study_day(df: pd.DataFrame, dom: str, rfst: dict) -> None:
    dtc = f"{dom}DTC"
    if dtc in df.columns and "USUBJID" in df.columns:
        df[f"{dom}DY"] = [_study_day(d, rfst.get(u)) for u, d in zip(df["USUBJID"], df[dtc])]


# --------------------------------------------------------------------------- domain-specific

def _enrich_dm(df: pd.DataFrame, design: ProtocolDesign, rfend: dict) -> None:
    ids = df["USUBJID"].astype(str)
    df["SUBJID"] = ids.str.rsplit("-", n=1).str[-1]
    df["AGEU"] = "YEARS"
    df["RACE"] = [_stable_pick(u + "race", _RACES) for u in ids]
    df["ETHNIC"] = [_stable_pick(u + "eth", _ETHNIC) for u in ids]
    df["COUNTRY"] = [_stable_pick(u + "ctry", _COUNTRIES) for u in ids]
    df["SITEID"] = [f"{(int(hashlib.md5((u + 'site').encode()).hexdigest(), 16) % 20) + 1:03d}"  # noqa: S324
                    for u in ids]
    df["ARMCD"] = df["ARM"].map(lambda a: _armcd(a))
    df["ACTARM"] = df["ARM"]
    df["ACTARMCD"] = df["ARMCD"]
    df["DTHFL"] = "N"
    df["RFXSTDTC"] = df["RFSTDTC"]
    df["RFENDTC"] = df["USUBJID"].map(lambda u: rfend.get(u, ""))
    df["RFXENDTC"] = df["RFENDTC"]


def _armcd(arm: str) -> str:
    """A short (<=8 char, alphanumeric) arm code from an arm name — SDTM ARMCD.

    Uses the initial of each alphanumeric word so punctuation (``+``, ``(``) never leaks into
    the code: 'Tislelizumab + Lenvatinib (RSD)' → 'TLR'.
    """
    import re
    code = "".join(w[0] for w in re.split(r"[^A-Za-z0-9]+", str(arm)) if w)[:8].upper()
    return code or "ARM"


def _enrich_ae(df: pd.DataFrame, rfst: dict) -> None:
    if df.empty or "AEDECOD" not in df.columns:
        return
    df["AEBODSYS"] = df["AEDECOD"].map(
        lambda d: _AE_SOC.get(d, "General disorders and administration site conditions"))
    sev = df["AESEV"] if "AESEV" in df.columns else pd.Series("MODERATE", index=df.index)
    df["AETOXGR"] = sev.map(lambda s: _AE_TOXGR.get(str(s).upper(), "2"))
    df["AESER"] = sev.map(lambda s: "Y" if str(s).upper() == "SEVERE" else "N")
    keys = (df["USUBJID"].astype(str) + df.get("AESEQ", pd.Series(range(len(df)))).astype(str))
    df["AEACN"] = [_stable_pick(k + "acn", _AE_ACN) for k in keys]
    df["AEREL"] = [_stable_pick(k + "rel", _AE_REL) for k in keys]
    df["AEOUT"] = [_stable_pick(k + "out", _AE_OUT) for k in keys]
    # end date = onset + a stable 1..21 day duration; study days off RFSTDTC
    if "AESTDTC" in df.columns:
        durs = [(int(hashlib.md5((k + 'dur').encode()).hexdigest(), 16) % 21) + 1 for k in keys]  # noqa: S324
        end = [_add_days(d, n) for d, n in zip(df["AESTDTC"], durs)]
        df["AEENDTC"] = end
        df["AESTDY"] = [_study_day(d, rfst.get(u)) for u, d in zip(df["USUBJID"], df["AESTDTC"])]
        df["AEENDY"] = [_study_day(d, rfst.get(u)) for u, d in zip(df["USUBJID"], end)]


def _add_days(dtc, n: int) -> str:
    if not isinstance(dtc, str) or len(dtc) < 10:
        return ""
    try:
        from datetime import timedelta
        return (date.fromisoformat(dtc[:10]) + timedelta(days=n)).isoformat()
    except ValueError:
        return ""


def _enrich_ex(df: pd.DataFrame, rfst: dict, rfend: dict) -> None:
    if df.empty:
        return
    route = df["EXROUTE"] if "EXROUTE" in df.columns else pd.Series("ORAL", index=df.index)
    df["EXDOSFRM"] = route.map(
        lambda r: "SOLUTION FOR INFUSION" if "VENOUS" in str(r).upper() else "TABLET")
    df["EXENDTC"] = df["USUBJID"].map(lambda u: rfend.get(u, ""))
    if "EXSTDTC" in df.columns:
        df["EXSTDY"] = [_study_day(d, rfst.get(u)) for u, d in zip(df["USUBJID"], df["EXSTDTC"])]
        df["EXENDY"] = [_study_day(rfend.get(u, ""), rfst.get(u)) for u in df["USUBJID"]]


def _enrich_cm(df: pd.DataFrame, rfst: dict) -> None:
    if df.empty:
        return
    df["CMCAT"] = "CONCOMITANT MEDICATION"
    df["CMINDC"] = ""  # indication not modeled
    keys = (df["USUBJID"].astype(str) + df.get("CMSEQ", pd.Series(range(len(df)))).astype(str))
    df["CMDOSE"] = [(int(hashlib.md5((k + 'd').encode()).hexdigest(), 16) % 8 + 1) * 5  # noqa: S324
                    for k in keys]
    df["CMDOSU"] = "mg"
    df["CMDOSFRQ"] = [_stable_pick(k + "frq", ["QD", "BID", "PRN", "TID"]) for k in keys]
    df["CMROUTE"] = "ORAL"
    if "CMSTDTC" in df.columns:
        df["CMENDTC"] = [_add_days(d, (int(hashlib.md5((k + 'ce').encode()).hexdigest(), 16) % 60))  # noqa: S324
                         for d, k in zip(df["CMSTDTC"], keys)]
        df["CMSTDY"] = [_study_day(d, rfst.get(u)) for u, d in zip(df["USUBJID"], df["CMSTDTC"])]


def _enrich_lb_reference(df: pd.DataFrame) -> None:
    """LB reference ranges + normal-range indicator, and a default LBCAT where absent."""
    if df.empty or "LBTESTCD" not in df.columns:
        return
    lo = df["LBTESTCD"].map(lambda c: _LB_REF.get(c, (None, None))[0])
    hi = df["LBTESTCD"].map(lambda c: _LB_REF.get(c, (None, None))[1])
    df["LBORNRLO"] = lo.where(lo.notna(), "")
    df["LBORNRHI"] = hi.where(hi.notna(), "")
    df["LBSTNRLO"] = df["LBORNRLO"]
    df["LBSTNRHI"] = df["LBORNRHI"]
    val = pd.to_numeric(df.get("LBORRES"), errors="coerce")
    ind = []
    for v, lo_i, hi_i in zip(val, lo, hi):
        if pd.isna(v) or pd.isna(lo_i) or pd.isna(hi_i):
            ind.append("")
        elif v < lo_i:
            ind.append("LOW")
        elif v > hi_i:
            ind.append("HIGH")
        else:
            ind.append("NORMAL")
    df["LBNRIND"] = ind
    if "LBCAT" not in df.columns:
        df["LBCAT"] = "CHEMISTRY"


def _enrich_pc(df: pd.DataFrame) -> None:
    if df.empty:
        return
    df["PCCAT"] = "PHARMACOKINETICS"
    df["PCSPEC"] = "PLASMA"


def _enrich_rs(df: pd.DataFrame) -> None:
    if not df.empty:
        df["RSEVAL"] = "INVESTIGATOR"


def _enrich_tu(df: pd.DataFrame) -> None:
    if not df.empty:
        df["TUMETHOD"] = "CT SCAN"
        df["TUEVAL"] = "INVESTIGATOR"


def _enrich_tr(df: pd.DataFrame) -> None:
    if not df.empty:
        df["TRMETHOD"] = "CT SCAN"
        df["TREVAL"] = "INVESTIGATOR"


# --------------------------------------------------------------------------- canonical order

_ORDER = {
    "dm": ["STUDYID", "DOMAIN", "USUBJID", "SUBJID", "RFSTDTC", "RFENDTC", "RFXSTDTC", "RFXENDTC",
           "SITEID", "AGE", "AGEU", "SEX", "RACE", "ETHNIC", "COUNTRY", "ARMCD", "ARM",
           "ACTARMCD", "ACTARM", "DTHFL"],
    "ae": ["STUDYID", "DOMAIN", "USUBJID", "AESEQ", "AETERM", "AEDECOD", "AEBODSYS", "AESEV",
           "AETOXGR", "AESER", "AEACN", "AEREL", "AEOUT", "AESTDTC", "AEENDTC", "AESTDY", "AEENDY"],
    "ex": ["STUDYID", "DOMAIN", "USUBJID", "EXSEQ", "EXTRT", "EXDOSE", "EXDOSU", "EXDOSFRM",
           "EXDOSFRQ", "EXROUTE", "EXSTDTC", "EXENDTC", "EXSTDY", "EXENDY"],
    "cm": ["STUDYID", "DOMAIN", "USUBJID", "CMSEQ", "CMTRT", "CMDECOD", "CMCAT", "CMINDC",
           "CMDOSE", "CMDOSU", "CMDOSFRQ", "CMROUTE", "CMSTDTC", "CMENDTC", "CMSTDY"],
}


def _findings_order(dom: str) -> list[str]:
    d = dom.upper()
    return ["STUDYID", "DOMAIN", "USUBJID", f"{d}SEQ", f"{d}LNKID", f"{d}CAT", f"{d}SPEC",
            f"{d}TESTCD", f"{d}TEST", f"{d}POS", f"{d}LOC", f"{d}ORRES", f"{d}ORRESU",
            f"{d}ORNRLO", f"{d}ORNRHI", f"{d}STRESC", f"{d}STRESN", f"{d}STRESU",
            f"{d}STNRLO", f"{d}STNRHI", f"{d}NRIND", f"{d}METHOD", f"{d}EVAL", f"{d}BLFL",
            "VISIT", "VISITNUM", f"{d}DTC", f"{d}DY"]


# --------------------------------------------------------------------------- entry point

def enrich_frames(frames: dict[str, pd.DataFrame], design: ProtocolDesign,
                  subs: list[dict]) -> None:
    """Expand every generated frame to full SDTM breadth, in place. Deterministic; adds columns
    only (never mutates the generators' clinical values, never consumes the shared RNG)."""
    rfst = {s["USUBJID"]: s["RFSTDTC"] for s in subs}
    # a plausible reference end date per subject (first dose + ~24 weeks) for RF*ENDTC / EX end
    rfend = {u: _add_days(d.isoformat() if isinstance(d, date) else str(d), 168)
             for u, d in rfst.items()}

    for name, df in frames.items():
        if df is None or df.empty:
            continue
        dom = name.upper()
        _add_domain(df, dom)

        if dom in _FINDINGS:
            _add_test(df, dom)
            if dom == "VS" and "VSORRESU" not in df.columns:  # VS generator emits no unit
                df["VSORRESU"] = df["VSTESTCD"].map(lambda c: _VS_UNITS.get(c, ""))
            _add_standardized(df, dom)
            _add_study_day(df, dom, rfst)
            if dom in _BLFL_DOMAINS:
                _add_baseline_flag(df, dom)

        if dom == "LB":
            _enrich_lb_reference(df)
        elif dom == "PC":
            _enrich_pc(df)
        elif dom == "RS":
            _enrich_rs(df)
        elif dom == "TU":
            _enrich_tu(df)
        elif dom == "TR":
            _enrich_tr(df)
        elif dom == "DM":
            _enrich_dm(df, design, rfend)
        elif dom == "AE":
            _enrich_ae(df, rfst)
        elif dom == "EX":
            _enrich_ex(df, rfst, rfend)
        elif dom == "CM":
            _enrich_cm(df, rfst)

        order = _ORDER.get(name) or (_findings_order(dom) if dom in _FINDINGS else None)
        if order:
            frames[name] = _reorder(df, order)
