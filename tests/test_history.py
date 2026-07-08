"""Offline tests for run history — save / list / label / load / collision handling."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from protocol_to_data import history  # noqa: E402
from protocol_to_data.history import list_runs, load_run, run_label, save_run  # noqa: E402
from protocol_to_data.schemas import DomainPlan, ProtocolDesign  # noqa: E402


def _csv_dir(tmp_path) -> Path:
    d = tmp_path / "src_csvs"
    d.mkdir(exist_ok=True)
    (d / "dm.csv").write_text("USUBJID\nS1\nS2\n")
    (d / "vs.csv").write_text("USUBJID,VSTESTCD\nS1,SYSBP\n")
    return d


def _design() -> ProtocolDesign:
    return ProtocolDesign(study_id="HF-1", phase="3",
                          domains=[DomainPlan(domain="DM"), DomainPlan(domain="VS")])


def test_save_creates_restorable_snapshot(tmp_path, monkeypatch):
    monkeypatch.setattr(history, "_RUNS_DIR", tmp_path / "runs")
    run_dir = save_run(_design(), _csv_dir(tmp_path), subjects=20, seed=42,
                       scorecard_md="### 🎯 5/5", caught=5, total=5)
    for f in ("dm.csv", "vs.csv", "design.json", "scorecard.md", "meta.json"):
        assert (run_dir / f).exists(), f"missing {f}"


def test_list_and_label(tmp_path, monkeypatch):
    monkeypatch.setattr(history, "_RUNS_DIR", tmp_path / "runs")
    save_run(_design(), _csv_dir(tmp_path), subjects=20, seed=42,
             scorecard_md="x", caught=5, total=5)
    runs = list_runs()
    assert len(runs) == 1
    meta = runs[0]
    assert meta["study_id"] == "HF-1" and meta["caught"] == 5
    label = run_label(meta)
    assert "HF-1" in label and "5/5 caught" in label


def test_load_restores_state(tmp_path, monkeypatch):
    monkeypatch.setattr(history, "_RUNS_DIR", tmp_path / "runs")
    run_dir = save_run(_design(), _csv_dir(tmp_path), subjects=20, seed=42,
                       scorecard_md="### restored", caught=5, total=5)
    data = load_run(run_dir)
    assert "HF-1" in data["design_json"]
    assert data["domains"] == ["DM", "VS"]
    assert data["scorecard"] == "### restored"
    assert Path(data["output_dir"]) == run_dir


def test_same_second_runs_do_not_collide(tmp_path, monkeypatch):
    monkeypatch.setattr(history, "_RUNS_DIR", tmp_path / "runs")
    monkeypatch.setattr(history, "_timestamp", lambda: "20260707_230500")
    d1 = save_run(_design(), _csv_dir(tmp_path), subjects=20, seed=42)
    d2 = save_run(_design(), _csv_dir(tmp_path), subjects=20, seed=42)
    assert d1 != d2 and d1.exists() and d2.exists()
    assert len(list_runs()) == 2
