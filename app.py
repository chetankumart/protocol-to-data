#!/usr/bin/env python
"""Thin Gradio UI for protocol-to-data.

Upload a protocol → watch the extract → generate → validate → repair loop stream live →
browse the generated SDTM CSVs and the anomaly scorecard. Reuses the agent unchanged:
`execute()` just drives `run_loop` and the anomaly loop, forwarding their narration.

    python app.py            # then open the printed local URL
"""

from __future__ import annotations

import json
import os
import queue
import sys
import threading
from pathlib import Path

import pandas as pd

_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(_ROOT / "src"))

import cli  # noqa: E402  — reuse its .env loader
from protocol_to_data.anomalies import (  # noqa: E402
    detect_anomalies, inject_anomalies, score_detections, scorecard_markdown,
)
from protocol_to_data import ctg_validator  # noqa: E402  — read-only registry cross-check (display only)
from protocol_to_data import rbac  # noqa: E402  — RBAC stubs (not enforced; see rbac.py)
from protocol_to_data.history import list_runs, load_run, run_label, save_run  # noqa: E402
from protocol_to_data.llm import reset_usage, usage_summary  # noqa: E402  — cost tracking
from protocol_to_data.loop import run_loop  # noqa: E402

cli._load_dotenv()

SAMPLE = _ROOT / "examples" / "sample_protocol.md"

# Target export formats. Only SDTM is implemented; the EDC ODM-XML targets are demo stubs
# that surface a roadmap notice and fall back to SDTM (no XML generation is built).
EXPORT_SDTM = "SDTM (Parquet) - Databricks Analytics Ready"
EXPORT_FORMATS = [
    EXPORT_SDTM,
    "CDASH (ODM XML) - Medidata Rave",
    "CDASH (ODM XML) - Veeva Vault EDC",
]


def _export_warning(fmt: str) -> str:
    """Non-SDTM targets are not built — return the roadmap notice to prepend to the run."""
    if fmt and fmt != EXPORT_SDTM:
        return ("⚠️  EDC ODM-XML integration is slated for the v2 roadmap. "
                "Proceeding with SDTM analytics export.\n\n")
    return ""


def execute(protocol_path: str, subjects: int, seed: int, anomalies: int):
    """Generator: yield (narration_text, final, extras).

    Streams narration lines as the agent emits them; the last yield (final=True) carries
    the extracted design, the produced domains, the output dir, and the anomaly scorecard.
    Pure of Gradio — directly testable.
    """
    q: "queue.Queue" = queue.Queue()
    holder: dict = {}

    def narrate(msg: str) -> None:
        q.put(msg)

    def worker() -> None:
        try:
            reset_usage()  # start this run's token/cost tally from zero
            res = run_loop(protocol_path, subjects=int(subjects), seed=int(seed),
                           out_root=str(_ROOT / "data" / "output"), narrate=narrate)
            holder["result"] = res
            if int(anomalies) > 0:
                narrate(f"\n🕵️  Injecting {int(anomalies)} anomalies (seed {seed}) ...")
                truth = inject_anomalies(res.output_dir, count=int(anomalies), seed=int(seed))
                for t in truth:
                    narrate(f"    • injected {t['type']} in {t['domain']} ({t.get('usubjid')})")
                narrate("🔎  Claude detecting ...")
                findings = detect_anomalies(res.design, res.output_dir)
                for f in findings:
                    narrate(f"    • [{f.anomaly_type}] {f.domain}: {f.description}")
                holder["score"] = score_detections(truth, findings)
            holder["usage"] = usage_summary()  # tokens + $ across extraction/repair/detection
            # snapshot the completed run into runs/<timestamp>/ for the history dropdown
            try:
                score = holder.get("score")
                run_dir = save_run(
                    res.design, res.output_dir, subjects=int(subjects), seed=int(seed),
                    scorecard_md=scorecard_markdown(score),
                    caught=(score["caught"] if score else None),
                    total=(score["total"] if score else None),
                )
                narrate(f"\n💾  Saved run → runs/{run_dir.name}")
            except Exception:  # noqa: BLE001 — history is best-effort, never fail the run
                pass
        except Exception as e:  # noqa: BLE001 — surface any failure in the narration pane
            narrate(f"\n❌  Error: {type(e).__name__}: {e}")
        finally:
            q.put(None)  # sentinel

    threading.Thread(target=worker, daemon=True).start()

    lines: list[str] = []
    while True:
        msg = q.get()
        if msg is None:
            break
        lines.append(msg)
        yield "\n".join(lines), False, None

    yield "\n".join(lines), True, _final_payload(holder)


def _fmt_tokens(n: int) -> str:
    return f"{n / 1000:.0f}k" if n >= 1000 else str(int(n))


def _usage_badge(usage: dict | None) -> str:
    if not usage:
        return "🪙 Run Cost: —"
    return (f"🪙 **Run Cost: ${usage['cost']:.2f}** · "
            f"{_fmt_tokens(usage['input_tokens'])} in / {_fmt_tokens(usage['output_tokens'])} out")


def _final_payload(holder: dict) -> dict:
    res = holder.get("result")
    if res is None:
        return {"design_json": "{}", "domains": [], "output_dir": "", "scorecard": "",
                "usage_badge": _usage_badge(holder.get("usage")), "skeleton": {}}
    out_dir = Path(res.output_dir)
    domains = sorted(p.stem.upper() for p in out_dir.glob("*.csv"))
    return {
        "design_json": res.design.model_dump_json(indent=2),
        "domains": domains,
        "output_dir": str(out_dir),
        "scorecard": scorecard_markdown(holder.get("score")),
        "usage_badge": _usage_badge(holder.get("usage")),
        # High-level skeleton for the (read-only) registry cross-check — NOT used for generation.
        "skeleton": {
            "num_arms": len(res.design.arms),
            "phase": res.design.phase,
            "enrollment": res.design.population.n_subjects,
        },
    }


def _load_domain_csv(output_dir: str, domain: str):
    if not output_dir or not domain:
        return pd.DataFrame()
    p = Path(output_dir) / f"{domain.lower()}.csv"
    return pd.read_csv(p).head(200) if p.exists() else pd.DataFrame()


def _run_choices() -> list[tuple[str, str]]:
    """(label, run_dir) pairs for the history dropdown, newest first."""
    return [(run_label(m), m["dir"]) for m in list_runs()]


def _resolve_host(env: dict | None = None) -> str:
    """Bind address: local dev stays on 127.0.0.1 (safe); containers / hosted platforms need
    0.0.0.0. Hugging Face Spaces sets SPACE_ID (auto-bind); GRADIO_SERVER_NAME overrides."""
    env = os.environ if env is None else env
    default_host = "0.0.0.0" if env.get("SPACE_ID") else "127.0.0.1"
    return env.get("GRADIO_SERVER_NAME", default_host)


def _resolve_port(env: dict | None = None) -> int:
    """Listen port. Precedence: platform-assigned PORT (Render / Railway / Fly / Cloud Run)
    → explicit GRADIO_SERVER_PORT → 7860."""
    env = os.environ if env is None else env
    return int(env.get("PORT") or env.get("GRADIO_SERVER_PORT") or "7860")


def _crosscheck_hint() -> str:
    return ("_Enter an NCT ID above and run to cross-check the extracted design against "
            "ClinicalTrials.gov — **read-only**, never used to generate data._")


def _phase_digits(p) -> str:
    """Reduce a phase label to comparable digits/slashes: 'Phase 3' / 'PHASE3' / '3' → '3'."""
    return "".join(ch for ch in str(p) if ch.isdigit() or ch == "/")


def _render_crosscheck(extracted: dict, nct_id: str) -> str:
    """READ-ONLY registry badge: compare the extracted skeleton to ClinicalTrials.gov.

    Purely for display — the CTG data is NEVER fed into SDTM generation. Returns Markdown.
    """
    if not nct_id or not nct_id.strip():
        return _crosscheck_hint()
    reg = ctg_validator.fetch_ctg_baseline(nct_id)
    if "error" in reg:
        return f"⚠️ **Registry cross-check unavailable** — {reg['error']}"

    def row(label, ext, regv, match):
        return f"| {label} | `{ext}` | `{regv}` | {'✅ Match' if match else '⚠️ Differs'} |"

    ph_e, ph_r = extracted.get("phase"), reg.get("phase")
    ar_e, ar_r = extracted.get("num_arms"), reg.get("num_arms")
    en_e, en_r = extracted.get("enrollment"), reg.get("enrollment")
    return "\n".join([
        f"**Extracted design vs. [ClinicalTrials.gov {reg['nct_id']}]"
        f"(https://clinicaltrials.gov/study/{reg['nct_id']}) — read-only**",
        "",
        "| Field | Extracted (Claude) | Registry (CTG) | |",
        "|---|---|---|---|",
        row("Phase", ph_e, ph_r, _phase_digits(ph_e) == _phase_digits(ph_r)),
        row("Number of arms", ar_e, ar_r, ar_e == ar_r),
        row("Target enrollment", en_e, en_r, en_e == en_r),
        "",
        "<sub>🔒 Registry data is display-only — it does **not** feed SDTM generation. "
        "Enrollment can legitimately differ (protocol *planned* vs registry *actual*).</sub>",
    ])


def _build_marker(env: dict | None = None) -> str:
    """Short commit SHA of the running build, so any deploy is verifiable by loading the page.
    Render auto-sets RENDER_GIT_COMMIT; other hosts set SOURCE_COMMIT / GIT_COMMIT. Falls back
    to 'local' for a dev run."""
    env = os.environ if env is None else env
    sha = env.get("RENDER_GIT_COMMIT") or env.get("SOURCE_COMMIT") or env.get("GIT_COMMIT")
    return sha[:7] if sha else "local"


def api_run(file_path: str, use_sample: bool = True, subjects: int = 40, seed: int = 42,
            anomalies: int = 0, export_format: str = EXPORT_SDTM, nct_id: str = "") -> dict:
    """Clean programmatic entry point (Gradio/MCP endpoint ``generate_synthetic_data``).

    Runs the protocol-to-data pipeline and returns ONLY the final artifacts as a JSON-serializable
    dict — the extracted ProtocolDesign and the paths to the generated SDTM files. No Gradio UI
    objects (Markdown / Dataframe / component updates) are returned.

    Set ``use_sample=True`` to run the bundled CARDIO-HF sample; otherwise ``file_path`` must be a
    server-readable protocol (PDF / HTML / txt). ``nct_id`` optionally attaches a read-only
    ClinicalTrials.gov cross-check (it never influences generation).
    """
    path = str(SAMPLE) if (use_sample or not file_path) else file_path
    final_extras = None
    for _narration, is_final, extras in execute(path, subjects, seed, anomalies):
        if is_final:
            final_extras = extras
    if not final_extras or not final_extras.get("output_dir"):
        return {"status": "error", "message": "Generation did not complete; check server logs."}

    out_dir = Path(final_extras["output_dir"])
    design = json.loads(final_extras["design_json"])
    resp = {
        "status": "ok",
        "study_id": design.get("study_id"),
        "output_dir": str(out_dir),
        "domains": final_extras.get("domains", []),
        "files": [str(p) for p in sorted(out_dir.glob("*.csv"))],
        "design": design,
    }
    if nct_id and nct_id.strip():
        resp["registry_crosscheck"] = ctg_validator.fetch_ctg_baseline(nct_id)  # read-only
    return resp


def build_ui():
    import gradio as gr

    with gr.Blocks(title="protocol-to-data") as demo:
        gr.Markdown(
            "# 🧬 protocol-to-data\n"
            "**From a clinical trial protocol to an analyzable synthetic dataset — one agentic "
            "loop, driven by Claude.** Upload a protocol (PDF / HTML / text), or use the bundled "
            "sample, and watch Claude extract the design, generate SDTM-shaped data, validate, "
            "and self-repair."
        )
        out_dir_state = gr.State("")

        with gr.Row():
            with gr.Column(scale=1):
                file_in = gr.File(label="Protocol (PDF / HTML / .md / .txt)",
                                  file_types=[".pdf", ".html", ".htm", ".md", ".txt"])
                use_sample = gr.Checkbox(label="Use bundled CARDIO-HF sample", value=True)
                subjects = gr.Slider(4, 100, value=40, step=1, label="Subjects")
                seed = gr.Number(value=42, precision=0, label="Seed (reproducible)")
                anomalies = gr.Slider(0, 5, value=5, step=1, label="Anomalies to inject + detect")
                export_format = gr.Dropdown(label="Target Export Format", choices=EXPORT_FORMATS,
                                            value=EXPORT_SDTM, interactive=True)
                nct_input = gr.Textbox(label="NCT ID (Optional - For Registry Cross-Check)",
                                       placeholder="e.g. NCT04303780", value="")
                run_btn = gr.Button("▶  Run the loop", variant="primary")
                history_dd = gr.Dropdown(label="📁 Load a previous run", choices=_run_choices(),
                                         value=None, interactive=True)
            with gr.Column(scale=2):
                narration = gr.Textbox(label="Live agent narration", lines=17,
                                       max_lines=17, interactive=False, autoscroll=True)
                usage_badge = gr.Markdown("🪙 Run Cost: —")  # cumulative tokens + $ for this run

        with gr.Accordion("🧩 Extracted ProtocolDesign", open=False):
            design_code = gr.Code(language="json", label="design (post-repair)")
        with gr.Accordion("🏛️ Registry Cross-Check", open=True):
            crosscheck_md = gr.Markdown(_crosscheck_hint())
        with gr.Accordion("🏭 Generated SDTM data", open=True):
            domain_dd = gr.Dropdown(label="Domain", choices=[], interactive=True)
            data_df = gr.Dataframe(label="Preview (first 200 rows)", interactive=False, wrap=True)
        with gr.Accordion("🎯 Anomaly scorecard", open=True):
            scorecard = gr.Markdown()

        # Build marker — shows the deployed commit SHA so any deploy is verifiable by loading
        # the page (Render sets RENDER_GIT_COMMIT; 'local' off-platform).
        gr.Markdown(f"<sub>🧬 protocol-to-data · build `{_build_marker()}`</sub>")

        def on_run(file, use_samp, subj, sd, anom, export_fmt, nct_id):
            rbac.require_write()  # RBAC injection point: running/generating is a write op (CDM)
            warning = _export_warning(export_fmt)  # EDC targets → roadmap notice, fall back to SDTM
            path = str(SAMPLE) if (use_samp or not file) else (file.name if hasattr(file, "name") else file)
            for text, final, extras in execute(path, subj, sd, anom):
                if not final:
                    yield {narration: warning + text}
                else:
                    domains = extras["domains"]
                    yield {
                        narration: warning + text,
                        design_code: extras["design_json"],
                        # Read-only registry badge — CTG data is display-only, never fed to generation.
                        crosscheck_md: _render_crosscheck(extras.get("skeleton", {}), nct_id),
                        domain_dd: gr.update(choices=domains, value=(domains[0] if domains else None)),
                        out_dir_state: extras["output_dir"],
                        scorecard: extras["scorecard"],
                        data_df: _load_domain_csv(extras["output_dir"], domains[0] if domains else ""),
                        history_dd: gr.update(choices=_run_choices()),  # surface the just-saved run
                        usage_badge: extras["usage_badge"],
                    }

        def on_load_run(run_dir):
            rbac.require_read()  # RBAC injection point: restoring a run is read-only (Statistician-safe)
            if not run_dir:
                return {}
            data = load_run(run_dir)
            domains = data["domains"]
            return {
                narration: f"📁  Restored saved run: {Path(run_dir).name}",
                design_code: data["design_json"],
                domain_dd: gr.update(choices=domains, value=(domains[0] if domains else None)),
                out_dir_state: data["output_dir"],
                scorecard: data["scorecard"],
                data_df: _load_domain_csv(data["output_dir"], domains[0] if domains else ""),
            }

        # UI event listeners are presentation-only — hide them from the public API docs
        # (api_name=False) so consumers see just the clean endpoint below, not UI-update signatures.
        run_btn.click(on_run, [file_in, use_sample, subjects, seed, anomalies, export_format, nct_input],
                      [narration, design_code, crosscheck_md, domain_dd, out_dir_state, scorecard,
                       data_df, history_dd, usage_badge], api_name=False)
        history_dd.change(on_load_run, [history_dd],
                          [narration, design_code, domain_dd, out_dir_state, scorecard, data_df],
                          api_name=False)
        domain_dd.change(_load_domain_csv, [out_dir_state, domain_dd], data_df, api_name=False)

        # The ONLY documented API/MCP endpoint: a clean, typed function returning final artifacts.
        gr.api(api_run, api_name="generate_synthetic_data")

    return demo


if __name__ == "__main__":
    import gradio as gr

    build_ui().queue().launch(
        theme=gr.themes.Soft(),
        server_name=_resolve_host(),   # 0.0.0.0 on Spaces/containers, 127.0.0.1 locally
        server_port=_resolve_port(),   # honors a platform-assigned $PORT (Render/Fly/…)
    )
