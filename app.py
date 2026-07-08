#!/usr/bin/env python
"""Thin Gradio UI for protocol-to-data.

Upload a protocol → watch the extract → generate → validate → repair loop stream live →
browse the generated SDTM CSVs and the anomaly scorecard. Reuses the agent unchanged:
`execute()` just drives `run_loop` and the anomaly loop, forwarding their narration.

    python app.py            # then open the printed local URL
"""

from __future__ import annotations

import queue
import sys
import threading
from pathlib import Path

import pandas as pd

_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(_ROOT / "src"))

import cli  # noqa: E402  — reuse its .env loader
from protocol_to_data.anomalies import (  # noqa: E402
    detect_anomalies, inject_anomalies, score_detections,
)
from protocol_to_data.loop import run_loop  # noqa: E402

cli._load_dotenv()

SAMPLE = _ROOT / "examples" / "sample_protocol.md"


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


def _final_payload(holder: dict) -> dict:
    res = holder.get("result")
    if res is None:
        return {"design_json": "{}", "domains": [], "output_dir": "", "scorecard": ""}
    out_dir = Path(res.output_dir)
    domains = sorted(p.stem.upper() for p in out_dir.glob("*.csv"))
    return {
        "design_json": res.design.model_dump_json(indent=2),
        "domains": domains,
        "output_dir": str(out_dir),
        "scorecard": _scorecard_md(holder.get("score")),
    }


def _scorecard_md(score: dict | None) -> str:
    if not score:
        return "_No anomaly loop run (set anomalies > 0)._"
    lines = [f"### 🎯 Claude caught **{score['caught']}/{score['total']}** injected anomalies"]
    if score["missed"]:
        lines.append("\n**Missed:**")
        lines += [f"- {t['type']} in {t['domain']} ({t.get('usubjid')})" for t in score["missed"]]
    if score["extra"]:
        lines.append("\n**Extra findings** (beyond the planted defects — Claude reasoning about the data):")
        lines += [f"- [{f.anomaly_type}] {f.domain}: {f.description}" for f in score["extra"]]
    return "\n".join(lines)


def _load_domain_csv(output_dir: str, domain: str):
    if not output_dir or not domain:
        return pd.DataFrame()
    p = Path(output_dir) / f"{domain.lower()}.csv"
    return pd.read_csv(p).head(200) if p.exists() else pd.DataFrame()


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
                run_btn = gr.Button("▶  Run the loop", variant="primary")
            with gr.Column(scale=2):
                narration = gr.Textbox(label="Live agent narration", lines=18,
                                       max_lines=18, interactive=False, autoscroll=True)

        with gr.Accordion("🧩 Extracted ProtocolDesign", open=False):
            design_code = gr.Code(language="json", label="design (post-repair)")
        with gr.Accordion("🏭 Generated SDTM data", open=True):
            domain_dd = gr.Dropdown(label="Domain", choices=[], interactive=True)
            data_df = gr.Dataframe(label="Preview (first 200 rows)", interactive=False, wrap=True)
        with gr.Accordion("🎯 Anomaly scorecard", open=True):
            scorecard = gr.Markdown()

        def on_run(file, use_samp, subj, sd, anom):
            path = str(SAMPLE) if (use_samp or not file) else (file.name if hasattr(file, "name") else file)
            for text, final, extras in execute(path, subj, sd, anom):
                if not final:
                    yield {narration: text}
                else:
                    domains = extras["domains"]
                    yield {
                        narration: text,
                        design_code: extras["design_json"],
                        domain_dd: gr.update(choices=domains, value=(domains[0] if domains else None)),
                        out_dir_state: extras["output_dir"],
                        scorecard: extras["scorecard"],
                        data_df: _load_domain_csv(extras["output_dir"], domains[0] if domains else ""),
                    }

        run_btn.click(on_run, [file_in, use_sample, subjects, seed, anomalies],
                      [narration, design_code, domain_dd, out_dir_state, scorecard, data_df])
        domain_dd.change(_load_domain_csv, [out_dir_state, domain_dd], data_df)

    return demo


if __name__ == "__main__":
    import gradio as gr
    build_ui().queue().launch(theme=gr.themes.Soft(), server_name="127.0.0.1",
                              server_port=7860)
