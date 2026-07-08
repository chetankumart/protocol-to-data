"""Run history — snapshot each completed run into `runs/<timestamp>/` for later restore.

Each run directory is a self-contained, restorable state: the generated SDTM CSVs, the
extracted design, a rendered anomaly scorecard, and a small meta record for labelling.
Used by the Gradio "Load Previous Run" dropdown; the app overwrites `data/output/` on every
run, so this is the durable archive.
"""

from __future__ import annotations

import json
import shutil
from datetime import datetime
from pathlib import Path
from typing import Optional

from . import rbac
from .schemas import ProtocolDesign

_RUNS_DIR = Path(__file__).resolve().parents[2] / "runs"


def _timestamp() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def save_run(design: ProtocolDesign, csv_dir: str | Path, *, subjects: int, seed: int,
             scorecard_md: Optional[str] = None, caught: Optional[int] = None,
             total: Optional[int] = None) -> Path:
    """Copy a completed run's CSVs + design + scorecard into `runs/<timestamp>/`."""
    rbac.require_write()  # RBAC injection point: snapshotting a run is a Clinical-Data-Manager op
    csv_dir = Path(csv_dir)
    ts = _timestamp()
    run_dir = _RUNS_DIR / ts
    n = 2
    while run_dir.exists():  # avoid clobbering a run made in the same second
        run_dir = _RUNS_DIR / f"{ts}_{n}"
        n += 1
    run_dir.mkdir(parents=True, exist_ok=True)

    for csv in sorted(csv_dir.glob("*.csv")):
        shutil.copy2(csv, run_dir / csv.name)
    (run_dir / "design.json").write_text(design.model_dump_json(indent=2), encoding="utf-8")
    if scorecard_md is not None:
        (run_dir / "scorecard.md").write_text(scorecard_md, encoding="utf-8")
    (run_dir / "meta.json").write_text(json.dumps({
        "timestamp": run_dir.name, "study_id": design.study_id,
        "subjects": subjects, "seed": seed, "caught": caught, "total": total,
    }, indent=2), encoding="utf-8")
    return run_dir


def list_runs() -> list[dict]:
    """Newest-first list of saved runs, each a meta dict with a `dir` key."""
    if not _RUNS_DIR.exists():
        return []
    runs = []
    for d in sorted(_RUNS_DIR.iterdir(), reverse=True):
        if not d.is_dir():
            continue
        meta = {"timestamp": d.name}
        mp = d / "meta.json"
        if mp.exists():
            try:
                meta.update(json.loads(mp.read_text(encoding="utf-8")))
            except (OSError, json.JSONDecodeError):
                pass
        meta["dir"] = str(d)
        runs.append(meta)
    return runs


def run_label(meta: dict) -> str:
    """Human-readable dropdown label, e.g. '20260707_230500 · CARDIO-HF-P3 · 5/5 caught'."""
    parts = [meta.get("timestamp", "run")]
    if meta.get("study_id"):
        parts.append(str(meta["study_id"]))
    if meta.get("caught") is not None and meta.get("total") is not None:
        parts.append(f"{meta['caught']}/{meta['total']} caught")
    return " · ".join(parts)


def load_run(run_dir: str | Path) -> dict:
    """Restore a saved run: design JSON, produced domains, csv dir, and scorecard markdown."""
    rbac.require_read()  # RBAC injection point: restoring a run is read-only (Statistician-safe)
    run_dir = Path(run_dir)
    design_fp = run_dir / "design.json"
    score_fp = run_dir / "scorecard.md"
    return {
        "design_json": design_fp.read_text(encoding="utf-8") if design_fp.exists() else "{}",
        "domains": sorted(p.stem.upper() for p in run_dir.glob("*.csv")),
        "output_dir": str(run_dir),
        "scorecard": score_fp.read_text(encoding="utf-8") if score_fp.exists() else "",
    }
