"""Clean Gradio/MCP API surface — api_run wrapper + build_ui construction. Offline (mocked)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import app  # noqa: E402  — repo-root Gradio module


def _fake_extras(out_dir: Path, design: dict) -> dict:
    return {
        "design_json": json.dumps(design),
        "domains": ["DM"],
        "output_dir": str(out_dir),
        "scorecard": "", "usage_badge": "", "skeleton": {},
    }


def test_api_run_returns_clean_json_payload(tmp_path, monkeypatch):
    (tmp_path / "dm.csv").write_text("USUBJID\nS-01\n")
    design = {"study_id": "CARDIO-HF-P3", "phase": "3", "arms": [{}, {}],
              "population": {"n_subjects": 40}}
    extras = _fake_extras(tmp_path, design)

    def fake_execute(path, subj, sd, anom):
        yield ("streaming…", False, None)
        yield ("done", True, extras)
    monkeypatch.setattr(app, "execute", fake_execute)

    resp = app.api_run("ignored.pdf", use_sample=True, subjects=40, seed=42, anomalies=0,
                       export_format=app.EXPORT_SDTM, nct_id="")
    assert resp["status"] == "ok"
    assert resp["study_id"] == "CARDIO-HF-P3"
    assert resp["design"]["phase"] == "3"
    assert any(f.endswith("dm.csv") for f in resp["files"])
    # No Gradio objects — the payload must be pure JSON.
    json.dumps(resp)
    # No UI-only keys leaked through.
    assert "scorecard" not in resp and "usage_badge" not in resp


def test_api_run_attaches_readonly_crosscheck(tmp_path, monkeypatch):
    (tmp_path / "dm.csv").write_text("USUBJID\nS-01\n")
    extras = _fake_extras(tmp_path, {"study_id": "X"})
    monkeypatch.setattr(app, "execute", lambda *a: iter([("d", True, extras)]))
    monkeypatch.setattr(app.ctg_validator, "fetch_ctg_baseline",
                        lambda n: {"nct_id": "NCT04303780", "phase": "3", "num_arms": 2, "enrollment": 345})
    resp = app.api_run("x", nct_id="NCT04303780")
    assert resp["registry_crosscheck"]["num_arms"] == 2


def test_api_run_error_when_no_output(monkeypatch):
    monkeypatch.setattr(app, "execute", lambda *a: iter([("failed", True, {"output_dir": ""})]))
    resp = app.api_run("x", use_sample=True)
    assert resp["status"] == "error"


def test_build_ui_constructs_with_clean_api():
    # Exercises gr.api registration + api_name=False wiring — must not raise.
    demo = app.build_ui()
    assert demo is not None
