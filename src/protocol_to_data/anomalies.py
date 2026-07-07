"""Stage 7 — ANOMALY LOOP: inject controlled errors, then Claude detects & explains.

Injection is deterministic (seeded). Detection is Claude-driven and scored against
the ground-truth injections so the demo can show "5/5 caught".
"""

from __future__ import annotations

import random
from pathlib import Path

import pandas as pd

from .llm import MODEL_REASON, complete_json
from .schemas import AnomalyFinding, ProtocolDesign

_PROMPT_PATH = Path(__file__).resolve().parents[2] / "prompts" / "detect_anomalies.md"


def inject_anomalies(data_dir: str | Path, *, count: int, seed: int) -> list[dict]:
    """Mutate copies of the CSVs in-place with `count` known anomalies. Returns ground truth."""
    rng = random.Random(seed)
    data_dir = Path(data_dir)
    injected: list[dict] = []

    injectors = [_inject_predose_ae, _inject_oob_vital, _inject_orphan_lb,
                 _inject_dup_visit, _inject_sex_mismatch]
    rng.shuffle(injectors)
    for fn in injectors[:count]:
        rec = fn(data_dir, rng)
        if rec:
            injected.append(rec)
    return injected


def _inject_predose_ae(data_dir: Path, rng) -> dict | None:
    p = data_dir / "ae.csv"
    if not p.exists():
        return None
    df = pd.read_csv(p)
    if df.empty:
        return None
    df.loc[0, "AESTDTC"] = "2020-01-01"  # clearly before any dose
    df.to_csv(p, index=False)
    return {"type": "temporal", "domain": "AE", "usubjid": df.loc[0, "USUBJID"]}


def _inject_oob_vital(data_dir: Path, rng) -> dict | None:
    p = data_dir / "vs.csv"
    if not p.exists():
        return None
    df = pd.read_csv(p)
    idx = df.index[df["VSTESTCD"] == "SYSBP"]
    if len(idx) == 0:
        return None
    df.loc[idx[0], "VSORRES"] = 400
    df.to_csv(p, index=False)
    return {"type": "physiologic", "domain": "VS", "usubjid": df.loc[idx[0], "USUBJID"]}


def _inject_orphan_lb(data_dir: Path, rng) -> dict | None:
    p = data_dir / "vs.csv"  # reuse VS as a stand-in child domain if LB absent
    if not p.exists():
        return None
    df = pd.read_csv(p)
    row = df.iloc[0].copy()
    row["USUBJID"] = "GHOST-9999"
    df = pd.concat([df, pd.DataFrame([row])], ignore_index=True)
    df.to_csv(p, index=False)
    return {"type": "referential", "domain": "VS", "usubjid": "GHOST-9999"}


def _inject_dup_visit(data_dir: Path, rng) -> dict | None:
    p = data_dir / "vs.csv"
    if not p.exists():
        return None
    df = pd.read_csv(p)
    df = pd.concat([df, df.iloc[[0]]], ignore_index=True)
    df.to_csv(p, index=False)
    return {"type": "uniqueness", "domain": "VS", "usubjid": df.iloc[0]["USUBJID"]}


def _inject_sex_mismatch(data_dir: Path, rng) -> dict | None:
    p = data_dir / "dm.csv"
    if not p.exists():
        return None
    df = pd.read_csv(p)
    # flip one subject's SEX to create downstream logical inconsistencies
    df.loc[0, "SEX"] = "M" if df.loc[0, "SEX"] == "F" else "F"
    df.to_csv(p, index=False)
    return {"type": "logical", "domain": "DM", "usubjid": df.loc[0, "USUBJID"]}


def detect_anomalies(design: ProtocolDesign, data_dir: str | Path, *,
                     model: str = MODEL_REASON, sample_rows: int = 25) -> list[AnomalyFinding]:
    """Claude reads dataset samples and returns anomaly findings."""
    data_dir = Path(data_dir)
    samples = []
    for p in sorted(data_dir.glob("*.csv")):
        df = pd.read_csv(p)
        samples.append(f"### {p.stem.upper()}\n{df.head(sample_rows).to_csv(index=False)}")
    template = _PROMPT_PATH.read_text(encoding="utf-8")
    prompt = (template
              .replace("{{DESIGN_JSON}}", design.model_dump_json(indent=2))
              .replace("{{DATASET_SAMPLES}}", "\n\n".join(samples)[:100_000]))
    raw = complete_json(prompt, model=model, max_tokens=4000)
    return [AnomalyFinding.model_validate(f) for f in raw.get("findings", [])]
