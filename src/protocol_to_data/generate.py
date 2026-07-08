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
BUILTIN_DOMAINS = {"DM", "VS", "LB", "QS", "AE", "EX", "RS", "PC"}

# ---------------------------------------------------------------- therapeutic-area profile

_ONCOLOGY_KEYWORDS = (
    "oncolog", "cancer", "tumor", "tumour", "nsclc", "carcinoma", "metasta",
    "neoplas", "lymphoma", "leukem", "melanoma", "sarcoma", "adenocarcinoma", "kras",
)


def _profile_for(design: ProtocolDesign) -> str:
    """Pick a clinical profile from the design. Defaults to cardiology (the CARDIO-HF demo)."""
    text = f"{design.therapeutic_area} {design.indication} {design.title}".lower()
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

    subs = _make_subjects(design, subjects, rng)
    _gen_dm(design, subs).to_csv(out_dir / "dm.csv", index=False)

    planned = set(design.domain_names())
    if "VS" in planned:
        _gen_vs(design, subs, rng).to_csv(out_dir / "vs.csv", index=False)
    if "LB" in planned:
        lb = _gen_lb_oncology if profile == "oncology" else _gen_lb_cardiology
        lb(design, subs, rng).to_csv(out_dir / "lb.csv", index=False)
    if "QS" in planned:
        qs = _gen_qs_oncology if profile == "oncology" else _gen_qs_cardiology
        qs(design, subs, rng).to_csv(out_dir / "qs.csv", index=False)
    if "RS" in planned:
        _gen_rs(design, subs, rng).to_csv(out_dir / "rs.csv", index=False)
    if "PC" in planned:
        _gen_pc(design, subs, rng).to_csv(out_dir / "pc.csv", index=False)
    if "AE" in planned:
        _gen_ae(design, subs, rng, profile).to_csv(out_dir / "ae.csv", index=False)
    if "EX" in planned:
        _gen_ex(design, subs, profile).to_csv(out_dir / "ex.csv", index=False)

    return out_dir


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
                    "VISIT": getattr(v, "name", "VISIT"),
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


def _gen_lb_oncology(design: ProtocolDesign, subs: list[dict], rng: random.Random) -> pd.DataFrame:
    """NSCLC labs: full panel + arm-specific drug effects (docetaxel myelosuppression,
    sotorasib transaminitis). PK concentrations live in the PC domain (see `_gen_pc`)."""
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
                val = rng.gauss(mean, sd)
                if docetaxel and tc == "NEUT":
                    val *= max(1 - 0.15 * min(i, 3), 0.40)   # neutropenia (kept ≥ grade 3)
                elif docetaxel and tc == "PLT":
                    val *= max(1 - 0.10 * min(i, 3), 0.40)   # thrombocytopenia
                elif sotorasib and tc in ("ALT", "AST"):
                    val *= min(1 + 0.18 * min(i, 4), 2.5)    # hepatotoxicity signal
                floor = 0.5 if tc == "NEUT" else 0.0         # ANC ≥ 0.5 (avoid grade-4)
                seq[s["USUBJID"]] = seq.get(s["USUBJID"], 0) + 1
                rows.append({
                    "STUDYID": design.study_id, "USUBJID": s["USUBJID"],
                    "LBSEQ": seq[s["USUBJID"]], "LBCAT": "CHEMISTRY/HEMATOLOGY",
                    "VISIT": getattr(v, "name", "VISIT"),
                    "LBTESTCD": tc, "LBORRES": round(max(val, floor), dec), "LBORRESU": unit,
                    "LBDTC": vdate.isoformat(),
                })
    return pd.DataFrame(rows)


def _gen_pc(design: ProtocolDesign, subs: list[dict], rng: random.Random) -> pd.DataFrame:
    """PK (Pharmacokinetics Concentrations) — plasma drug concentration at treatment visits.

    Placebo subjects have no PK. Known study drugs get realistic Cmax-ish means; any other
    active drug gets a generic concentration keyed to the arm name.
    """
    visits = [v for v in _ordered_visits(design) if not getattr(v, "is_screening", False)]
    rows = []
    seq = {}
    for s in subs:
        if s["IS_PLACEBO"]:
            continue
        name = s["ARM"].lower()
        if "amg" in name or "sotorasib" in name:
            analyte, mean, sd = "SOTORASIB", 900, 350
        elif "docetaxel" in name:
            analyte, mean, sd = "DOCETAXEL", 2200, 800
        else:
            analyte, mean, sd = (s["ARM"].upper().replace(" ", "")[:8] or "DRUG"), 500, 200
        for v in visits:
            vdate = _visit_date(s["RFSTDTC"], getattr(v, "day", 1))
            seq[s["USUBJID"]] = seq.get(s["USUBJID"], 0) + 1
            rows.append({
                "STUDYID": design.study_id, "USUBJID": s["USUBJID"],
                "PCSEQ": seq[s["USUBJID"]], "PCTESTCD": analyte, "PCTEST": f"{analyte} concentration",
                "VISIT": getattr(v, "name", "VISIT"),
                "PCORRES": round(max(rng.gauss(mean, sd), 0.0), 0), "PCORRESU": "ng/mL",
                "PCDTC": vdate.isoformat(),
            })
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
                "VISIT": getattr(v, "name", "VISIT"),
                "RSTESTCD": "OVRLRESP", "RSORRES": resp, "RSDTC": vdate.isoformat(),
            })
    return pd.DataFrame(rows)


# --------------------------------------------------------------------------- AE (by profile)

_AE_TERMS = {
    "cardiology": ["HEADACHE", "NAUSEA", "FATIGUE", "DIZZINESS", "HYPOTENSION"],
    "oncology": ["FATIGUE", "NAUSEA", "DIARRHOEA", "ALOPECIA", "NEUTROPENIA", "ANAEMIA",
                 "DECREASED APPETITE", "ALT INCREASED", "VOMITING",
                 "PERIPHERAL SENSORY NEUROPATHY"],
}


def _gen_ae(design: ProtocolDesign, subs: list[dict], rng: random.Random, profile: str) -> pd.DataFrame:
    terms = _AE_TERMS[profile]
    rows = []
    for s in subs:
        seq = 0
        for _ in range(rng.randint(0, 3)):
            seq += 1
            # Onset on/after first dose — the loop's repair step depends on this invariant.
            onset = s["RFSTDTC"] + timedelta(days=rng.randint(1, 90))
            rows.append({
                "STUDYID": design.study_id, "USUBJID": s["USUBJID"], "AESEQ": seq,
                "AETERM": rng.choice(terms), "AESTDTC": onset.isoformat(),
                "AESEV": rng.choice(["MILD", "MODERATE", "SEVERE"]),
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
