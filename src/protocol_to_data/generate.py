"""Stage 4 — GENERATE: ProtocolDesign → per-domain synthetic CSVs.

Two backends:
  - "builtin"       : lean, dependency-light generator (default). Enough to demo the loop.
  - "engine-bridge" : shell out to the author's production engine for full clinical breadth.

The builtin backend is **therapeutic-area aware**: it picks a clinical profile from the
design's indication/therapeutic area and generates domain values appropriate to that cohort
(oncology vs. the cardiology default). It is NOT the production generator — it exists so the
repo runs standalone for judges.
"""

from __future__ import annotations

import random
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

from .schemas import ProtocolDesign

ENROLLMENT_START = date(2026, 1, 15)

# SDTM domains the builtin backend can emit. A planned domain outside this set can't be
# generated standalone — the loop's repair step remaps or drops it (see validate coverage check).
# EG/PC/TU/TR added in v2 so the oncology repair stops *deleting* clinically-meaningful domains:
# EG = ECG, PC = PK concentrations (moved out of LB), TU/TR = RECIST tumor identification/results.
BUILTIN_DOMAINS = {"DM", "VS", "LB", "QS", "AE", "EX", "RS", "CM", "EG", "PC", "TU", "TR"}

# ---------------------------------------------------------------- therapeutic-area profile

# Authoritative therapeutic-area signals (checked on the `therapeutic_area` field first).
_ONCOLOGY_TA = ("oncolog", "cancer")
# Specific indication/title keywords — deliberately NOT bare "tumor"/"tumour", which appear
# in non-oncology contexts (e.g. "tumor necrosis factor" in cardiology/immunology).
_ONCOLOGY_KEYWORDS = (
    "oncolog", "cancer", "nsclc", "carcinoma", "metasta", "neoplasm", "malignan",
    "lymphoma", "leukemia", "leukaemia", "melanoma", "sarcoma", "adenocarcinoma",
    "kras p.g12c", "solid tumor", "solid tumour", "tumor response", "recist",
)


def _profile_for(design: ProtocolDesign) -> str:
    """Pick a clinical profile from the design. Defaults to cardiology (the CARDIO-HF demo).

    The `therapeutic_area` field is authoritative; otherwise we require a *specific* oncology
    keyword in the indication/title so a stray generic term can't falsely trigger oncology.
    """
    ta = (design.therapeutic_area or "").lower()
    if any(k in ta for k in _ONCOLOGY_TA):
        return "oncology"
    text = f"{design.indication} {design.title}".lower()
    return "oncology" if any(k in text for k in _ONCOLOGY_KEYWORDS) else "cardiology"


def _ordered_visits(design: ProtocolDesign) -> list:
    """Visits in chronological order (by day). Falls back to a single day-1 visit."""
    visits = list(design.visits) or [type("V", (), {"name": "VISIT1", "day": 1,
                                                    "is_screening": False})()]
    return sorted(visits, key=lambda v: getattr(v, "day", 1))


def _visit_date(rfst: date, day: int) -> date:
    """Anchor a visit to first-dose day 1: day -14 (screening) lands before RFSTDTC."""
    return rfst + timedelta(days=day - 1)


def _clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def _visitnum(v, design: ProtocolDesign) -> float:
    """Stable VISITNUM from the visit's position in the full chronological schedule.

    Derived from the full ordered visit list (not per-domain iteration), so a given clinical
    timepoint carries the *same* VISITNUM in every longitudinal domain — e.g. VISITNUM 2.0
    means the same visit in VS, LB, QS, and RS.
    """
    name = getattr(v, "name", "VISIT")
    for i, ov in enumerate(_ordered_visits(design)):
        if getattr(ov, "name", "VISIT") == name:
            return float(i + 1)
    return 0.0


def generate_dataset(design: ProtocolDesign, *, subjects: int, seed: int,
                     out_root: str | Path, backend: str = "builtin") -> Path:
    """Generate CSVs and return the synthetic_data directory."""
    if backend == "engine-bridge":
        return _generate_via_engine_bridge(design, subjects=subjects, seed=seed, out_root=out_root)
    return _generate_builtin(design, subjects=subjects, seed=seed, out_root=out_root)


# --------------------------------------------------------------------------- builtin

def _generate_builtin(design: ProtocolDesign, *, subjects: int, seed: int,
                      out_root: str | Path) -> Path:
    rng = random.Random(seed)
    profile = _profile_for(design)
    out_dir = Path(out_root) / design.study_id / "synthetic_data"
    out_dir.mkdir(parents=True, exist_ok=True)

    # DM is generated first — USUBJID is the primary key every other domain references.
    subs = _make_subjects(design, subjects, rng)
    frames: dict[str, pd.DataFrame] = {"dm": _gen_dm(design, subs)}

    planned = set(design.domain_names())
    if "VS" in planned:
        frames["vs"] = _gen_vs(design, subs, rng)
    if "LB" in planned:
        lb = _gen_lb_oncology if profile == "oncology" else _gen_lb_cardiology
        frames["lb"] = lb(design, subs, rng)
    if "QS" in planned:
        qs = _gen_qs_oncology if profile == "oncology" else _gen_qs_cardiology
        frames["qs"] = qs(design, subs, rng)
    if "RS" in planned:
        frames["rs"] = _gen_rs(design, subs, rng)
    if "AE" in planned:
        frames["ae"] = _gen_ae(design, subs, rng, profile)
    if "CM" in planned:
        frames["cm"] = _gen_cm(design, subs, rng, profile)
    if "EX" in planned:
        frames["ex"] = _gen_ex(design, subs, profile)
    # v2 depth — domains the repair loop used to delete. Placed last so they only consume the RNG
    # (and only exist) when actually planned; existing domains' output is unchanged otherwise.
    if "EG" in planned:
        frames["eg"] = _gen_eg(design, subs, rng)
    if "PC" in planned:
        frames["pc"] = _gen_pc(design, subs, rng)
    if "TU" in planned or "TR" in planned:
        tu_rows, tr_rows = _gen_tumor(design, subs, rng)
        if "TU" in planned:
            frames["tu"] = pd.DataFrame(tu_rows)
        if "TR" in planned:
            frames["tr"] = pd.DataFrame(tr_rows)

    _enforce_referential_integrity(frames)  # drop orphans + assert before writing

    for name, df in frames.items():
        df.to_csv(out_dir / f"{name}.csv", index=False)
    return out_dir


def _enforce_referential_integrity(frames: dict[str, pd.DataFrame]) -> None:
    """SDTM traceability guard for both keys — subject (USUBJID) and timepoint (VISITNUM).

    1. Subject FK: every child-domain USUBJID must exist in DM. Orphan rows are dropped to
       auto-repair, then a zero-orphan assertion runs before anything is written.
    2. Timepoint FK: VISIT ↔ VISITNUM must be a single consistent 1:1 mapping across every
       longitudinal domain — the same clinical timepoint carries the same VISITNUM in VS, LB,
       QS and RS, and no VISITNUM maps to more than one visit (no orphan timepoints).

    The result is always a valid relational set (no dangling foreign keys on either axis).
    """
    # 1. subject referential integrity
    dm_ids = set(frames["dm"]["USUBJID"])
    for name in list(frames):
        if name == "dm":
            continue
        df = frames[name]
        if df.empty or "USUBJID" not in df.columns:
            continue
        keep = df["USUBJID"].isin(dm_ids)
        if not keep.all():
            frames[name] = df[keep].reset_index(drop=True)  # drop orphan rows to repair
        assert set(frames[name]["USUBJID"]) <= dm_ids, f"orphan USUBJID remains in {name}"

    # 2. temporal referential integrity — VISIT ↔ VISITNUM bijection across all domains
    visit_to_num: dict = {}
    num_to_visit: dict = {}
    for name, df in frames.items():
        if df.empty or not {"VISIT", "VISITNUM"}.issubset(df.columns):
            continue
        for visit, num in df[["VISIT", "VISITNUM"]].drop_duplicates().itertuples(index=False):
            assert visit_to_num.setdefault(visit, num) == num, \
                f"VISIT {visit!r} has an inconsistent VISITNUM in {name}"
            assert num_to_visit.setdefault(num, visit) == visit, \
                f"VISITNUM {num} maps to more than one visit (orphan timepoint in {name})"


def _make_subjects(design: ProtocolDesign, n: int, rng: random.Random) -> list[dict]:
    arms = design.arms or [type("A", (), {"name": "TREATMENT", "is_placebo": False})()]
    lo, hi = design.population.age_range
    sex_pool = {"all": ["M", "F"], "female": ["F"], "male": ["M"]}[design.population.sex]
    subs = []
    for i in range(n):
        arm = arms[i % len(arms)]
        rfst = ENROLLMENT_START + timedelta(days=rng.randint(0, 120))
        subs.append({
            "USUBJID": f"{design.study_id}-{1001 + i}",
            "ARM": getattr(arm, "name", "TREATMENT"),
            "IS_PLACEBO": getattr(arm, "is_placebo", False),
            "AGE": rng.randint(lo, hi),
            "SEX": rng.choice(sex_pool),
            "RFSTDTC": rfst,
        })
    return subs


def _gen_dm(design: ProtocolDesign, subs: list[dict]) -> pd.DataFrame:
    return pd.DataFrame([{
        "STUDYID": design.study_id,
        "USUBJID": s["USUBJID"],
        "ARM": s["ARM"],
        "AGE": s["AGE"],
        "SEX": s["SEX"],
        "RFSTDTC": s["RFSTDTC"].isoformat(),
    } for s in subs])


def _gen_vs(design: ProtocolDesign, subs: list[dict], rng: random.Random) -> pd.DataFrame:
    visits = _ordered_visits(design)
    rows = []
    seq = {}
    for s in subs:
        for v in visits:
            vdate = _visit_date(s["RFSTDTC"], getattr(v, "day", 1))
            for test, mean, sd in [("SYSBP", 128, 12), ("DIABP", 78, 8), ("PULSE", 72, 9)]:
                seq[s["USUBJID"]] = seq.get(s["USUBJID"], 0) + 1
                rows.append({
                    "STUDYID": design.study_id,
                    "USUBJID": s["USUBJID"],
                    "VSSEQ": seq[s["USUBJID"]],
                    "VISIT": getattr(v, "name", "VISIT"), "VISITNUM": _visitnum(v, design),
                    "VSTESTCD": test,
                    "VSORRES": round(rng.gauss(mean, sd), 1),
                    "VSDTC": vdate.isoformat(),
                })
    return pd.DataFrame(rows)


# ------------------------------------------------------------------ LB (labs) by profile

def _gen_lb_cardiology(design: ProtocolDesign, subs: list[dict], rng: random.Random) -> pd.DataFrame:
    """HFrEF labs with a light trajectory: NT-proBNP falls over time, more on active drug."""
    visits = _ordered_visits(design)
    rows = []
    seq = {}
    for s in subs:
        drug = not s["IS_PLACEBO"]
        bnp_base = rng.gauss(1500, 350)
        for i, v in enumerate(visits):
            vdate = _visit_date(s["RFSTDTC"], getattr(v, "day", 1))
            bnp = max(bnp_base * ((0.86 if drug else 0.97) ** i), 50)
            panel = [
                ("NTPROBNP", round(bnp, 0), "pg/mL"),
                ("CREAT", round(rng.gauss(1.0, 0.18), 2), "mg/dL"),
                ("HGB", round(rng.gauss(13.5, 1.1), 1), "g/dL"),
                ("K", round(rng.gauss(4.2, 0.35), 1), "mmol/L"),
            ]
            for test, val, unit in panel:
                seq[s["USUBJID"]] = seq.get(s["USUBJID"], 0) + 1
                rows.append({
                    "STUDYID": design.study_id, "USUBJID": s["USUBJID"],
                    "LBSEQ": seq[s["USUBJID"]], "VISIT": getattr(v, "name", "VISIT"),
                    "VISITNUM": _visitnum(v, design),
                    "LBTESTCD": test, "LBORRES": val, "LBORRESU": unit,
                    "LBDTC": vdate.isoformat(),
                })
    return pd.DataFrame(rows)


# Oncology (NSCLC) lab panel: (testcd, unit, mean, sd, decimals). Hematology, chemistry,
# coagulation, thyroid — PK concentrations are added per treatment visit below.
_ONC_LB_PANEL = [
    # hematology
    ("HGB", "g/dL", 11.5, 1.3, 1), ("WBC", "10^9/L", 6.5, 2.0, 1),
    ("NEUT", "10^9/L", 4.0, 1.2, 1), ("LYM", "10^9/L", 1.5, 0.5, 1),
    ("PLT", "10^9/L", 250, 60, 0),
    # chemistry
    ("CREAT", "mg/dL", 0.9, 0.2, 2), ("ALT", "U/L", 22, 9, 0), ("AST", "U/L", 24, 9, 0),
    ("BILI", "mg/dL", 0.6, 0.25, 2), ("ALP", "U/L", 85, 25, 0), ("ALB", "g/dL", 3.8, 0.45, 1),
    ("SODIUM", "mmol/L", 139, 2.5, 0), ("K", "mmol/L", 4.2, 0.4, 1),
    ("CALCIUM", "mg/dL", 9.4, 0.5, 1),
    # coagulation
    ("INR", "ratio", 1.05, 0.08, 2), ("PT", "s", 12.5, 1.1, 1), ("APTT", "s", 30, 3, 0),
    # thyroid
    ("TSH", "mIU/L", 2.0, 0.9, 2), ("FT4", "ng/dL", 1.2, 0.22, 2),
]


def _drug_effect(tc: str, i: int, *, docetaxel: bool, sotorasib: bool) -> float:
    """Deterministic biological-context rule: multiplier on a lab value at visit index `i`.

    The therapeutic-area clinical rules are declared here — cleanly separated from row
    assembly and injected per-arm — so the biology is explicit and standardized, not left to
    chance. Each effect is documented to its known pharmacology:
      • docetaxel → myelosuppression: neutrophils fall to a nadir (grade-4 possible); platelets fall.
      • sotorasib (AMG 510) → transaminitis: ALT/AST rise over exposure.
    Returns 1.0 (no effect) for any (analyte, arm) pair without a defined rule.
    """
    if docetaxel and tc == "NEUT":
        return max(1 - 0.15 * min(i, 3), 0.30)   # neutropenia nadir (grade-4 preserved)
    if docetaxel and tc == "PLT":
        return max(1 - 0.10 * min(i, 3), 0.40)   # thrombocytopenia
    if sotorasib and tc in ("ALT", "AST"):
        return min(1 + 0.18 * min(i, 4), 2.5)    # hepatotoxicity signal
    return 1.0


def _gen_lb_oncology(design: ProtocolDesign, subs: list[dict], rng: random.Random) -> pd.DataFrame:
    """NSCLC labs: full panel + arm-specific drug effects (docetaxel myelosuppression,
    sotorasib transaminitis) + a plasma PK concentration at each treatment visit."""
    visits = _ordered_visits(design)
    rows = []
    seq = {}
    for s in subs:
        name = s["ARM"].lower()
        docetaxel = "docetaxel" in name
        sotorasib = ("amg" in name) or ("sotorasib" in name)
        for i, v in enumerate(visits):
            vdate = _visit_date(s["RFSTDTC"], getattr(v, "day", 1))
            for tc, unit, mean, sd, dec in _ONC_LB_PANEL:
                # draw, then apply the declared biological-context rule for this (analyte, arm)
                val = rng.gauss(mean, sd) * _drug_effect(tc, i, docetaxel=docetaxel, sotorasib=sotorasib)
                seq[s["USUBJID"]] = seq.get(s["USUBJID"], 0) + 1
                rows.append({
                    "STUDYID": design.study_id, "USUBJID": s["USUBJID"],
                    "LBSEQ": seq[s["USUBJID"]], "LBCAT": "CHEMISTRY/HEMATOLOGY",
                    "VISIT": getattr(v, "name", "VISIT"), "VISITNUM": _visitnum(v, design),
                    "LBTESTCD": tc, "LBORRES": round(max(val, 0.0), dec), "LBORRESU": unit,
                    "LBDTC": vdate.isoformat(),
                })
            # (PK concentrations moved to the dedicated PC domain — see _gen_pc — which is the
            # CDISC-correct home; they no longer pollute LB.)
    return pd.DataFrame(rows)


# ------------------------------------------------------------- QS (questionnaires) by profile

def _gen_qs_cardiology(design: ProtocolDesign, subs: list[dict], rng: random.Random) -> pd.DataFrame:
    """HFrEF PROs from baseline onward: KCCQ improves, NYHA may downgrade."""
    visits = [v for v in _ordered_visits(design) if not getattr(v, "is_screening", False)]
    rows = []
    seq = {}
    for s in subs:
        drug = not s["IS_PLACEBO"]
        kccq_base = rng.gauss(52, 9)
        nyha_base = rng.choice([2, 3])
        for i, v in enumerate(visits):
            vdate = _visit_date(s["RFSTDTC"], getattr(v, "day", 1))
            kccq = min(max(kccq_base + (6.5 if drug else 1.8) * i + rng.gauss(0, 3), 0), 100)
            nyha = max(1, nyha_base - (1 if (drug and i >= 2) else 0))
            for test, val in [("KCCQ12", round(kccq, 1)), ("NYHA", nyha)]:
                seq[s["USUBJID"]] = seq.get(s["USUBJID"], 0) + 1
                rows.append({
                    "STUDYID": design.study_id, "USUBJID": s["USUBJID"],
                    "QSSEQ": seq[s["USUBJID"]], "VISIT": getattr(v, "name", "VISIT"),
                    "VISITNUM": _visitnum(v, design),
                    "QSTESTCD": test, "QSORRES": val, "QSDTC": vdate.isoformat(),
                })
    return pd.DataFrame(rows)


def _gen_qs_oncology(design: ProtocolDesign, subs: list[dict], rng: random.Random) -> pd.DataFrame:
    """NSCLC PROs from baseline onward: EORTC QLQ-C30 / QLQ-LC13 and EQ-5D-5L.

    QLQ-C30 global health (0-100, higher better); QLQ-LC13 symptom scales (0-100, higher
    worse); EQ-5D-5L index (-0.594..1) and VAS (0-100).
    """
    visits = [v for v in _ordered_visits(design) if not getattr(v, "is_screening", False)]
    rows = []
    seq = {}
    for s in subs:
        for v in visits:
            vdate = _visit_date(s["RFSTDTC"], getattr(v, "day", 1))
            items = [
                ("QLQC30GH", round(_clamp(rng.gauss(60, 14), 0, 100), 1)),          # global QoL
                ("QLQLC13DYSP", round(_clamp(rng.gauss(30, 17), 0, 100), 1)),       # dyspnea
                ("QLQLC13COUGH", round(_clamp(rng.gauss(33, 18), 0, 100), 1)),      # cough
                ("EQ5D5LVAS", round(_clamp(rng.gauss(68, 14), 0, 100), 0)),          # EQ VAS
                ("EQ5D5LIDX", round(_clamp(rng.gauss(0.75, 0.14), -0.594, 1.0), 3)),  # EQ index
            ]
            for test, val in items:
                seq[s["USUBJID"]] = seq.get(s["USUBJID"], 0) + 1
                rows.append({
                    "STUDYID": design.study_id, "USUBJID": s["USUBJID"],
                    "QSSEQ": seq[s["USUBJID"]], "VISIT": getattr(v, "name", "VISIT"),
                    "VISITNUM": _visitnum(v, design),
                    "QSTESTCD": test, "QSORRES": val, "QSDTC": vdate.isoformat(),
                })
    return pd.DataFrame(rows)


# ------------------------------------------------------------------ RS (RECIST response)

_RECIST = ["CR", "PR", "SD", "PD", "NE"]
# Best-overall-response weights by arm (CodeBreak-200-flavored: sotorasib higher ORR).
_RECIST_WEIGHTS = {
    "sotorasib": [0.02, 0.28, 0.45, 0.22, 0.03],
    "docetaxel": [0.01, 0.13, 0.47, 0.32, 0.07],
    "default":   [0.02, 0.20, 0.45, 0.28, 0.05],
}


def _gen_rs(design: ProtocolDesign, subs: list[dict], rng: random.Random) -> pd.DataFrame:
    """Overall tumor response (RECIST 1.1) at tumor-assessment visits."""
    visits = [v for v in _ordered_visits(design)
              if "tumor" in getattr(v, "name", "").lower()
              or "assess" in getattr(v, "name", "").lower()]
    if not visits:  # no explicit tumor visits — use on-treatment visits after baseline
        visits = [v for v in _ordered_visits(design)
                  if not getattr(v, "is_screening", False) and getattr(v, "day", 1) > 1]
    rows = []
    seq = {}
    for s in subs:
        name = s["ARM"].lower()
        key = "sotorasib" if ("amg" in name or "sotorasib" in name) else \
              ("docetaxel" if "docetaxel" in name else "default")
        resp = rng.choices(_RECIST, weights=_RECIST_WEIGHTS[key], k=1)[0]
        for v in visits:
            vdate = _visit_date(s["RFSTDTC"], getattr(v, "day", 1))
            seq[s["USUBJID"]] = seq.get(s["USUBJID"], 0) + 1
            rows.append({
                "STUDYID": design.study_id, "USUBJID": s["USUBJID"],
                "RSSEQ": seq[s["USUBJID"]], "RSCAT": "RECIST 1.1",
                "VISIT": getattr(v, "name", "VISIT"), "VISITNUM": _visitnum(v, design),
                "RSTESTCD": "OVRLRESP", "RSORRES": resp, "RSDTC": vdate.isoformat(),
            })
    return pd.DataFrame(rows)


# ------------------------------------------------------------------ EG (ECG) · universal

_EG_PANEL = [("QT", 400, 25, "msec"), ("QTCF", 415, 18, "msec"), ("HR", 72, 10, "beats/min"),
             ("PR", 158, 20, "msec"), ("QRS", 95, 12, "msec")]


def _gen_eg(design: ProtocolDesign, subs: list[dict], rng: random.Random) -> pd.DataFrame:
    """12-lead ECG parameters (QT/QTcF/HR/PR/QRS) at each visit — applicable to any area."""
    visits = _ordered_visits(design)
    rows, seq = [], {}
    for s in subs:
        for v in visits:
            vdate = _visit_date(s["RFSTDTC"], getattr(v, "day", 1))
            for tc, mean, sd, unit in _EG_PANEL:
                seq[s["USUBJID"]] = seq.get(s["USUBJID"], 0) + 1
                rows.append({
                    "STUDYID": design.study_id, "USUBJID": s["USUBJID"], "EGSEQ": seq[s["USUBJID"]],
                    "VISIT": getattr(v, "name", "VISIT"), "VISITNUM": _visitnum(v, design),
                    "EGTESTCD": tc, "EGORRES": round(rng.gauss(mean, sd), 0), "EGORRESU": unit,
                    "EGDTC": vdate.isoformat(),
                })
    return pd.DataFrame(rows)


# ----------------------------------------------------------- PC (PK concentrations) · oncology

def _gen_pc(design: ProtocolDesign, subs: list[dict], rng: random.Random) -> pd.DataFrame:
    """Plasma PK concentrations at treatment visits — the CDISC-correct home for PK (was in LB)."""
    visits = _ordered_visits(design)
    rows, seq = [], {}
    for s in subs:
        name = s["ARM"].lower()
        docetaxel = "docetaxel" in name
        sotorasib = ("amg" in name) or ("sotorasib" in name)
        if not (docetaxel or sotorasib):
            continue
        analyte, mean, sd = ("SOTORASIB", 900, 350) if sotorasib else ("DOCETAXEL", 2200, 800)
        for v in visits:
            if getattr(v, "is_screening", False):
                continue
            vdate = _visit_date(s["RFSTDTC"], getattr(v, "day", 1))
            seq[s["USUBJID"]] = seq.get(s["USUBJID"], 0) + 1
            rows.append({
                "STUDYID": design.study_id, "USUBJID": s["USUBJID"], "PCSEQ": seq[s["USUBJID"]],
                "VISIT": getattr(v, "name", "VISIT"), "VISITNUM": _visitnum(v, design),
                "PCTESTCD": analyte, "PCORRES": round(max(rng.gauss(mean, sd), 0.0), 0),
                "PCORRESU": "ng/mL", "PCDTC": vdate.isoformat(),
            })
    return pd.DataFrame(rows)


# --------------------------------------------------------- TU / TR (RECIST tumor) · oncology

_TU_LOCATIONS = ["LUNG", "LIVER", "LYMPH NODE", "BONE", "ADRENAL GLAND"]


def _gen_tumor(design: ProtocolDesign, subs: list[dict],
               rng: random.Random) -> tuple[list[dict], list[dict]]:
    """RECIST target lesions: TU (identification at baseline) + TR (longest diameter over time).

    Returns (tu_rows, tr_rows). Lesions shrink faster on active treatment; TU and TR share a
    per-lesion ``LNKID`` so the two domains are relationally linked (SDTM `--LNKID`).
    """
    ordered = _ordered_visits(design)
    baseline = next((v for v in ordered if not getattr(v, "is_screening", False)), ordered[0])
    assess = [v for v in ordered if not getattr(v, "is_screening", False)
              and getattr(v, "day", 1) >= getattr(baseline, "day", 1)]
    tu_rows, tr_rows = [], []
    for s in subs:
        drug = not s["IS_PLACEBO"]
        tu_seq = tr_seq = 0
        bdate = _visit_date(s["RFSTDTC"], getattr(baseline, "day", 1))
        lesions = []
        for i in range(rng.randint(1, 3)):
            lnk = f"T{i + 1}"
            base = _clamp(rng.gauss(35, 12), 10, 90)
            lesions.append((lnk, base))
            tu_seq += 1
            tu_rows.append({
                "STUDYID": design.study_id, "USUBJID": s["USUBJID"], "TUSEQ": tu_seq,
                "TULNKID": lnk, "TUTESTCD": "TUMIDENT", "TUORRES": "TARGET",
                "TULOC": rng.choice(_TU_LOCATIONS),
                "VISIT": getattr(baseline, "name", "VISIT"), "VISITNUM": _visitnum(baseline, design),
                "TUDTC": bdate.isoformat(),
            })
        for j, v in enumerate(assess):
            vdate = _visit_date(s["RFSTDTC"], getattr(v, "day", 1))
            for lnk, base in lesions:
                diam = _clamp(base * ((0.85 if drug else 0.98) ** j) + rng.gauss(0, 2), 0, 120)
                tr_seq += 1
                tr_rows.append({
                    "STUDYID": design.study_id, "USUBJID": s["USUBJID"], "TRSEQ": tr_seq,
                    "TRLNKID": lnk, "TRTESTCD": "LDIAM", "TRORRES": round(diam, 0), "TRORRESU": "mm",
                    "VISIT": getattr(v, "name", "VISIT"), "VISITNUM": _visitnum(v, design),
                    "TRDTC": vdate.isoformat(),
                })
    return tu_rows, tr_rows


# --------------------------------------------------------------------------- AE (by profile)

# Dictionary coding — a DETERMINISTIC DICTIONARY STAND-IN (not a zero-shot LLM call).
# `code_term` maps a verbatim reported term to its standardized dictionary term: a MedDRA
# Preferred Term for AE (AETERM "bad headache" → AEDECOD "Headache"), a WHODrug preferred
# name for CM. In production this call routes each verbatim through an official
# MedDRA / WHODrug auto-encoder API; the offline dictionaries below stand in so the demo has
# no external dependency and stays fully reproducible.
_AE_DICTIONARY = {
    "cardiology": {
        "bad headache": "Headache", "feeling sick": "Nausea", "very tired": "Fatigue",
        "dizzy spells": "Dizziness", "low blood pressure": "Hypotension",
    },
    "oncology": {
        "very tired": "Fatigue", "feeling sick": "Nausea", "loose stools": "Diarrhoea",
        "hair loss": "Alopecia", "low white cell count": "Neutropenia",
        "low blood count": "Anaemia", "no appetite": "Decreased appetite",
        "raised liver enzymes": "Alanine aminotransferase increased",
        "throwing up": "Vomiting", "numb hands and feet": "Peripheral sensory neuropathy",
    },
}

# Severity/qualifier prefixes stripped when normalizing a term not found in the dictionary.
_QUALIFIERS = ("bad ", "very ", "mild ", "moderate ", "severe ", "low ", "high ", "raised ")


def code_term(verbatim: str, dictionary: dict[str, str]) -> str:
    """Deterministic dictionary coder: verbatim reported term → standardized term.

    Exact dictionary hit wins; an unknown term falls back to a normalized Title Case (with
    common severity qualifiers stripped) so *any* reported term still codes to something
    stable. Production replaces this with an official MedDRA/WHODrug mapping API.
    """
    if verbatim in dictionary:
        return dictionary[verbatim]
    cleaned = verbatim.strip().lower()
    for q in _QUALIFIERS:
        if cleaned.startswith(q):
            cleaned = cleaned[len(q):]
            break
    return cleaned.capitalize()


def _gen_ae(design: ProtocolDesign, subs: list[dict], rng: random.Random, profile: str) -> pd.DataFrame:
    dictionary = _AE_DICTIONARY[profile]
    verbatims = list(dictionary)
    # OpenFDA-grounded path (opt-in; attached to the design at DESIGN time, never fetched here):
    # sample real-world MedDRA PTs weighted by report frequency. Strict AETERM == AEDECOD == PT
    # (the OpenFDA term is already a Preferred Term). Deterministic given (seed, grounded weights) —
    # the generator stays network-free. Empty grounding ⇒ the built-in dictionary path below.
    grounded_terms = [g.term for g in design.grounded_ae]
    grounded_weights = [g.count for g in design.grounded_ae]
    rows = []
    for s in subs:
        seq = 0
        for _ in range(rng.randint(0, 3)):
            seq += 1
            if grounded_terms:
                term = rng.choices(grounded_terms, weights=grounded_weights, k=1)[0]
                verbatim, decod = term, term
            else:
                verbatim = rng.choice(verbatims)
                decod = code_term(verbatim, dictionary)  # reported term → MedDRA-coded term
            # Onset on/after first dose — the loop's repair step depends on this invariant.
            onset = s["RFSTDTC"] + timedelta(days=rng.randint(1, 90))
            rows.append({
                "STUDYID": design.study_id, "USUBJID": s["USUBJID"], "AESEQ": seq,
                "AETERM": verbatim, "AEDECOD": decod, "AESTDTC": onset.isoformat(),
                "AESEV": rng.choice(["MILD", "MODERATE", "SEVERE"]),
            })
    return pd.DataFrame(rows)


# --------------------------------------------------------------------------- CM (con-meds)

# Concomitant medications: CMTRT is the reported drug name; CMDECOD is the WHODrug-coded
# preferred name — coded by the same deterministic `code_term` stand-in as AE (production
# routes each verbatim drug through an official WHODrug mapping API).
_CM_DICTIONARY = {
    "cardiology": {
        "lisinopril 10mg": "Lisinopril", "metoprolol": "Metoprolol",
        "lasix": "Furosemide", "spironolactone": "Spironolactone",
        "aspirin 81mg": "Acetylsalicylic acid",
    },
    "oncology": {
        "ondansetron": "Ondansetron", "dexamethasone": "Dexamethasone",
        "tylenol": "Paracetamol", "omeprazole": "Omeprazole", "filgrastim": "Filgrastim",
    },
}


def _gen_cm(design: ProtocolDesign, subs: list[dict], rng: random.Random, profile: str) -> pd.DataFrame:
    dictionary = _CM_DICTIONARY[profile]
    verbatims = list(dictionary)
    rows = []
    for s in subs:
        seq = 0
        for _ in range(rng.randint(0, 3)):
            seq += 1
            verbatim = rng.choice(verbatims)
            decod = code_term(verbatim, dictionary)  # reported drug → WHODrug-coded name
            start = s["RFSTDTC"] + timedelta(days=rng.randint(-30, 30))
            rows.append({
                "STUDYID": design.study_id, "USUBJID": s["USUBJID"], "CMSEQ": seq,
                "CMTRT": verbatim, "CMDECOD": decod, "CMSTDTC": start.isoformat(),
            })
    return pd.DataFrame(rows)


# --------------------------------------------------------------------------- EX (dosing)

# Known regimens matched on arm/drug name — placeholder for design-carried dosing.
# (name substrings, EXTRT, dose, unit, frequency, route)
_REGIMENS = [
    (("sotorasib", "amg 510", "amg510"), "AMG 510", 960.0, "mg", "QD", "ORAL"),
    (("docetaxel",), "Docetaxel", 75.0, "mg/m2", "Q3W", "INTRAVENOUS"),
]
# Profile fallback when the drug isn't a known regimen: (dose, unit, freq, route).
_EX_DEFAULT = {"cardiology": (40.0, "mg", "QD", "ORAL"), "oncology": (0.0, "mg", "QD", "ORAL")}


def _resolve_regimen(arm_name: str, is_placebo: bool, profile: str):
    if is_placebo:
        return ("Placebo", 0.0, "", "QD", "ORAL")
    name = (arm_name or "").lower()
    for keys, trt, dose, unit, freq, route in _REGIMENS:
        if any(k in name for k in keys):
            return (trt, dose, unit, freq, route)
    dose, unit, freq, route = _EX_DEFAULT[profile]
    return (arm_name or "Study Drug", dose, unit, freq, route)


def _gen_ex(design: ProtocolDesign, subs: list[dict], profile: str) -> pd.DataFrame:
    rows = []
    for s in subs:
        trt, dose, unit, freq, route = _resolve_regimen(s["ARM"], s["IS_PLACEBO"], profile)
        rows.append({
            "STUDYID": design.study_id, "USUBJID": s["USUBJID"], "EXSEQ": 1,
            "EXTRT": trt, "EXDOSE": dose, "EXDOSU": unit, "EXDOSFRQ": freq,
            "EXROUTE": route, "EXSTDTC": s["RFSTDTC"].isoformat(),
        })
    return pd.DataFrame(rows)


# --------------------------------------------------------------------------- engine bridge

def _generate_via_engine_bridge(design, *, subjects, seed, out_root):  # pragma: no cover
    """ENGINE BRIDGE (optional, stretch).

    Shell out to the production engine for full 32-domain clinical output:

        protocol-synthetic-data-generation/scripts/engine.py \
          --study-name <id> --protocol-html <path> --num-subjects N --seed S --confirm

    Then copy its synthetic_data/*.csv into out_root/<study_id>/synthetic_data/.
    Not required for the demo — builtin backend is the default.
    """
    raise NotImplementedError(
        "engine-bridge backend is a stretch goal — see docs/ARCHITECTURE.md 'Generation backends'."
    )
