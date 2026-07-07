"""Stage 4 — GENERATE: ProtocolDesign → per-domain synthetic CSVs.

Two backends:
  - "builtin"       : lean, dependency-light generator (default). Enough to demo the loop.
  - "engine-bridge" : shell out to the author's production engine for full clinical breadth.

The builtin backend is intentionally simple. It is NOT the production generator — it exists
so the repo runs standalone for judges. Wire richer logic day 3; bridge for breadth.
"""

from __future__ import annotations

import random
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

from .schemas import ProtocolDesign

ENROLLMENT_START = date(2026, 1, 15)


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
    out_dir = Path(out_root) / design.study_id / "synthetic_data"
    out_dir.mkdir(parents=True, exist_ok=True)

    subs = _make_subjects(design, subjects, rng)
    dm = _gen_dm(design, subs)
    dm.to_csv(out_dir / "dm.csv", index=False)

    planned = set(design.domain_names())
    if "VS" in planned:
        _gen_vs(design, subs, rng).to_csv(out_dir / "vs.csv", index=False)
    if "AE" in planned:
        _gen_ae(design, subs, rng).to_csv(out_dir / "ae.csv", index=False)
    if "EX" in planned:
        _gen_ex(design, subs, rng).to_csv(out_dir / "ex.csv", index=False)

    # TODO(hackathon, Day 3): LB, QS (and endpoint-driven measures) + clinical trajectories.
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
    visits = design.visits or [type("V", (), {"name": "VISIT1", "day": 1})()]
    rows = []
    seq = {}
    for s in subs:
        for v in visits:
            vday = getattr(v, "day", 1)
            vdate = s["RFSTDTC"] + timedelta(days=max(vday - 1, 0))
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


def _gen_ae(design: ProtocolDesign, subs: list[dict], rng: random.Random) -> pd.DataFrame:
    terms = ["HEADACHE", "NAUSEA", "FATIGUE", "DIZZINESS", "HYPOTENSION"]
    rows = []
    for s in subs:
        seq = 0
        for _ in range(rng.randint(0, 3)):
            seq += 1
            # Onset on/after first dose — the loop's repair step depends on this invariant.
            onset = s["RFSTDTC"] + timedelta(days=rng.randint(1, 90))
            rows.append({
                "STUDYID": design.study_id,
                "USUBJID": s["USUBJID"],
                "AESEQ": seq,
                "AETERM": rng.choice(terms),
                "AESTDTC": onset.isoformat(),
                "AESEV": rng.choice(["MILD", "MODERATE", "SEVERE"]),
            })
    return pd.DataFrame(rows)


def _gen_ex(design: ProtocolDesign, subs: list[dict], rng: random.Random) -> pd.DataFrame:
    rows = []
    for s in subs:
        dose = 0.0 if s["IS_PLACEBO"] else rng.choice([10, 20, 40])
        rows.append({
            "STUDYID": design.study_id,
            "USUBJID": s["USUBJID"],
            "EXSEQ": 1,
            "EXTRT": "PLACEBO" if s["IS_PLACEBO"] else "STUDY DRUG",
            "EXDOSE": dose,
            "EXSTDTC": s["RFSTDTC"].isoformat(),
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
