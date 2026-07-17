"""Clean Gradio/MCP API surface — api_run routing, URL ingestion, zero-click NCT. Offline."""
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
    monkeypatch.setattr(app, "_detect_nct", lambda p: None)  # no id in this protocol

    resp = app.api_run("ignored.pdf", use_sample=True, subjects=40, seed=42, anomalies=0,
                       export_format=app.EXPORT_SDTM)
    assert resp["status"] == "ok"
    assert resp["study_id"] == "CARDIO-HF-P3"
    assert resp["design"]["phase"] == "3"
    assert resp["detected_nct"] is None
    assert any(f.endswith("dm.csv") for f in resp["files"])
    json.dumps(resp)  # pure JSON — no Gradio objects
    assert "scorecard" not in resp and "usage_badge" not in resp


def test_api_run_autodetects_nct_and_attaches_crosscheck(tmp_path, monkeypatch):
    (tmp_path / "dm.csv").write_text("USUBJID\nS-01\n")
    extras = _fake_extras(tmp_path, {"study_id": "X"})
    monkeypatch.setattr(app, "execute", lambda *a: iter([("d", True, extras)]))
    monkeypatch.setattr(app, "_detect_nct", lambda p: "NCT04303780")   # zero-click detection
    monkeypatch.setattr(app.ctg_validator, "fetch_ctg_baseline",
                        lambda n: {"nct_id": n, "phase": "3", "num_arms": 2, "enrollment": 345})
    resp = app.api_run("x", use_sample=True)
    assert resp["detected_nct"] == "NCT04303780"
    assert resp["registry_crosscheck"]["num_arms"] == 2


def test_api_run_via_url_downloads_and_cleans_up(tmp_path, monkeypatch):
    dl = tmp_path / "downloaded.pdf"
    dl.write_text("%PDF-1.4 fake")
    monkeypatch.setattr(app, "download_from_url", lambda u: str(dl))
    monkeypatch.setattr(app, "_detect_nct", lambda p: None)
    out = tmp_path / "out"
    out.mkdir()
    (out / "dm.csv").write_text("USUBJID\nS-1\n")
    captured = {}

    def fake_execute(path, subj, sd, anom):
        captured["path"] = path
        yield ("done", True, _fake_extras(out, {"study_id": "URL-STUDY"}))
    monkeypatch.setattr(app, "execute", fake_execute)

    resp = app.api_run("", use_sample=False, protocol_url="https://host/p.pdf")
    assert resp["status"] == "ok" and resp["study_id"] == "URL-STUDY"
    assert captured["path"] == str(dl)   # extracted from the downloaded file
    assert not dl.exists()               # CRITICAL: temp file cleaned up in finally


def test_sample_precedence_beats_url(tmp_path, monkeypatch):
    def no_download(u):
        raise AssertionError("download must not run when use_sample=True")
    monkeypatch.setattr(app, "download_from_url", no_download)
    monkeypatch.setattr(app, "_detect_nct", lambda p: None)
    out = tmp_path / "out"
    out.mkdir()
    (out / "dm.csv").write_text("x\n")
    monkeypatch.setattr(app, "execute", lambda *a: iter([("d", True, _fake_extras(out, {"study_id": "S"}))]))
    resp = app.api_run("", use_sample=True, protocol_url="https://host/p.pdf")
    assert resp["status"] == "ok"


def test_api_run_requires_some_input(monkeypatch):
    def boom(*a, **k):
        raise AssertionError("execute must not run without a source")
    monkeypatch.setattr(app, "execute", boom)
    resp = app.api_run("", use_sample=False, protocol_url="")
    assert resp["status"] == "error" and "protocol" in resp["message"].lower()


def test_api_run_error_when_no_output(monkeypatch):
    monkeypatch.setattr(app, "_detect_nct", lambda p: None)
    monkeypatch.setattr(app, "execute", lambda *a: iter([("failed", True, {"output_dir": ""})]))
    resp = app.api_run("x", use_sample=True)
    assert resp["status"] == "error"


def test_build_ui_constructs_with_clean_api():
    # Exercises gr.api registration + api_name=False wiring — must not raise.
    demo = app.build_ui()
    assert demo is not None


def test_zip_synthetic_data_bundles_csvs_design_manifest(tmp_path):
    # The downloadable-ZIP endpoint's packaging — offline (no pipeline / API key).
    import zipfile
    out = tmp_path / "STUDY-1" / "synthetic_data"
    out.mkdir(parents=True)
    (out / "dm.csv").write_text("USUBJID\nS-1\n")
    (out / "vs.csv").write_text("USUBJID,VSTESTCD\nS-1,SYSBP\n")
    (out.parent / "run_manifest.json").write_text('{"seed": 42}')
    zip_path = app._zip_synthetic_data(out, "STUDY-1", {"study_id": "STUDY-1"})
    assert zipfile.is_zipfile(zip_path)
    names = set(zipfile.ZipFile(zip_path).namelist())
    assert {"STUDY-1/dm.csv", "STUDY-1/vs.csv", "STUDY-1/design.json",
            "STUDY-1/run_manifest.json"} <= names


def test_uploaded_path_normalizes_api_file_arg():
    # gradio_client uploads arrive as a dict {"path": ...}; also tolerate FileData / str / None.
    assert app._uploaded_path(None) == ""
    assert app._uploaded_path("") == ""
    assert app._uploaded_path("/srv/x.pdf") == "/srv/x.pdf"
    assert app._uploaded_path({"path": "/tmp/up.pdf"}) == "/tmp/up.pdf"
    assert app._uploaded_path({"path": None}) == ""

    class _FD:
        path = "/tmp/fd.pdf"
    assert app._uploaded_path(_FD()) == "/tmp/fd.pdf"


def test_zip_run_bundles_or_none(tmp_path):
    import zipfile
    assert app._zip_run("") is None
    assert app._zip_run(str(tmp_path / "missing")) is None
    # a dir with no CSVs yields no download
    empty = tmp_path / "empty"
    empty.mkdir()
    assert app._zip_run(str(empty)) is None

    # live-run layout: data/output/<STUDY>/synthetic_data + parent run_manifest.json
    out = tmp_path / "ZZZ" / "synthetic_data"
    out.mkdir(parents=True)
    (out / "dm.csv").write_text("USUBJID\nS-1\n")
    (out.parent / "run_manifest.json").write_text('{"design": {"study_id": "ZZZ"}}')
    zp = app._zip_run(str(out))
    assert zp and zipfile.is_zipfile(zp)
    names = zipfile.ZipFile(zp).namelist()
    assert "ZZZ/dm.csv" in names and "ZZZ/design.json" in names

    # saved-run layout: runs/<ts>/ with a design.json inside (no parent manifest) → study id from it
    saved = tmp_path / "runs" / "20260101_000000"
    saved.mkdir(parents=True)
    (saved / "dm.csv").write_text("USUBJID\nS-1\n")
    (saved / "design.json").write_text('{"study_id": "SAVED-1"}')
    zp2 = app._zip_run(str(saved))
    assert zp2 and "SAVED-1/dm.csv" in zipfile.ZipFile(zp2).namelist()
