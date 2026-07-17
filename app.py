#!/usr/bin/env python
"""Thin Gradio UI for protocol-to-data.

Upload a protocol → watch the extract → generate → validate → repair loop stream live →
browse the generated SDTM CSVs and the anomaly scorecard. Reuses the agent unchanged:
`execute()` just drives `run_loop` and the anomaly loop, forwarding their narration.

    python app.py            # then open the printed local URL
"""

from __future__ import annotations

import contextlib
import json
import os
import queue
import re
import sys
import tempfile
import threading
import zipfile
from pathlib import Path

import pandas as pd
from gradio.data_classes import FileData  # for the downloadable-ZIP API endpoint

_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(_ROOT / "src"))

import cli  # noqa: E402  — reuse its .env loader
from protocol_to_data.anomalies import (  # noqa: E402
    detect_anomalies, inject_anomalies, score_detections, scorecard_markdown,
)
from protocol_to_data import copilot  # noqa: E402  — DuckDB-backed Data Copilot (memory-safe chat)
from protocol_to_data import ctg_validator  # noqa: E402  — read-only registry cross-check (display only)
from protocol_to_data.download import download_from_url  # noqa: E402  — "Ingest by URL" fallback
from protocol_to_data import rbac  # noqa: E402  — RBAC stubs (not enforced; see rbac.py)
from protocol_to_data.history import list_runs, load_run, run_label, save_run  # noqa: E402
from protocol_to_data.ingest import load_protocol_text  # noqa: E402  — for zero-click NCT auto-detect
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
                narrate("🔎  Running automated anomaly detection ...")
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


_NCT_RE = re.compile(r"NCT\d{8}")

# Captions are folded INTO the single dynamic markdown per accordion. A separate caption component
# stacks a second block, and the theme draws an accent border between blocks that clips the text —
# one block per accordion avoids it.
_CROSSCHECK_CAPTION = ("_Read-only comparison. Data generation is driven strictly by your uploaded "
                       "protocol document, not the registry._")
_CROSSCHECK_IDLE = (f"{_CROSSCHECK_CAPTION}\n\n"
                    "_Run a protocol — if its text contains an NCT ID, it's auto-validated "
                    "against ClinicalTrials.gov here._")
_NO_NCT_MSG = (f"{_CROSSCHECK_CAPTION}\n\n"
               "No Registry ID detected (Likely a pre-registration or private protocol).")
_SCORECARD_CAPTION = ("_An automated Data Quality (DQ) review tracking how many injected errors "
                      "were successfully caught by the system's validation logic._")


def _detect_nct(protocol_path: str) -> str | None:
    """Zero-click: scan the extracted protocol text for an NCT id (e.g. NCT04303780).

    Best-effort ingestion-layer read — never fails the run. Returns the id or None.
    """
    try:
        text = load_protocol_text(protocol_path)
    except Exception:  # noqa: BLE001 — detection must never break generation
        return None
    m = _NCT_RE.search(text or "")
    return m.group(0) if m else None


def _phase_digits(p) -> str:
    """Reduce a phase label to comparable digits/slashes: 'Phase 3' / 'PHASE3' / '3' → '3'."""
    return "".join(ch for ch in str(p) if ch.isdigit() or ch == "/")


def _render_crosscheck(extracted: dict, nct_id: str | None) -> str:
    """READ-ONLY registry badge: compare the extracted skeleton to ClinicalTrials.gov.

    Purely for display — CTG data is NEVER fed into SDTM generation. `nct_id` is auto-detected
    from the protocol text; None → a clean "no registry id" notice.
    """
    if not nct_id:
        return _NO_NCT_MSG
    reg = ctg_validator.fetch_ctg_baseline(nct_id)
    if "error" in reg:
        return f"{_CROSSCHECK_CAPTION}\n\n⚠️ **Registry cross-check unavailable** — {reg['error']}"

    def row(label, ext, regv, match):
        return f"| {label} | `{ext}` | `{regv}` | {'✅ Match' if match else '⚠️ Differs'} |"

    ph_e, ph_r = extracted.get("phase"), reg.get("phase")
    ar_e, ar_r = extracted.get("num_arms"), reg.get("num_arms")
    en_e, en_r = extracted.get("enrollment"), reg.get("enrollment")
    body = "\n".join([
        f"**Extracted design vs. [ClinicalTrials.gov {reg['nct_id']}]"
        f"(https://clinicaltrials.gov/study/{reg['nct_id']}) — read-only**",
        "",
        "| Field | Extracted (Pipeline) | Registry (CTG) | |",
        "|---|---|---|---|",
        row("Phase", ph_e, ph_r, _phase_digits(ph_e) == _phase_digits(ph_r)),
        row("Number of arms", ar_e, ar_r, ar_e == ar_r),
        row("Target enrollment", en_e, en_r, en_e == en_r),
        "",
        "<sub>🔒 Registry data is display-only — it does **not** feed SDTM generation. "
        "Enrollment can legitimately differ (protocol *planned* vs registry *actual*).</sub>",
    ])
    return f"{_CROSSCHECK_CAPTION}\n\n{body}"


def _build_marker(env: dict | None = None) -> str:
    """Short commit SHA of the running build, so any deploy is verifiable by loading the page.
    Render auto-sets RENDER_GIT_COMMIT; other hosts set SOURCE_COMMIT / GIT_COMMIT. Falls back
    to 'local' for a dev run."""
    env = os.environ if env is None else env
    sha = env.get("RENDER_GIT_COMMIT") or env.get("SOURCE_COMMIT") or env.get("GIT_COMMIT")
    return sha[:7] if sha else "local"


@contextlib.contextmanager
def _protocol_source(use_sample: bool, protocol_url: str, file_path):
    """Resolve the ingestion source by strict precedence and yield a readable local path.

    Precedence: (1) bundled sample → (2) URL (downloaded to a temp file) → (3) uploaded file →
    (4) clear error. A temp file created from a URL is deleted on exit (``finally``), so we never
    leak disk on the free cloud instance. `nct_id` is intentionally NOT a source here — it stays a
    read-only cross-check applied after extraction.
    """
    tmp_path = None
    try:
        if use_sample:
            yield str(SAMPLE)
        elif protocol_url and protocol_url.strip():
            tmp_path = download_from_url(protocol_url.strip())
            yield tmp_path
        elif file_path:
            yield file_path.name if hasattr(file_path, "name") else str(file_path)
        else:
            raise ValueError(
                "No protocol provided — upload a file, paste a URL, or tick 'Use bundled sample'."
            )
    finally:
        if tmp_path:
            with contextlib.suppress(OSError):
                os.remove(tmp_path)


def _uploaded_path(f) -> str:
    """Normalize an API file argument to a server-side path string ('' if absent).

    Via ``gradio_client``, an uploaded file (``handle_file(...)``) arrives as a dict with a
    ``path`` key pointing at the server's copy; also tolerates a bare ``FileData`` / path str.
    """
    if f is None:
        return ""
    if isinstance(f, dict):
        return f.get("path") or ""
    return getattr(f, "path", f) or ""


def api_run(file_path: FileData | None = None, use_sample: bool = True, subjects: int = 40,
            seed: int = 42, anomalies: int = 0, export_format: str = EXPORT_SDTM,
            protocol_url: str = "") -> dict:
    """Clean programmatic entry point (Gradio/MCP endpoint ``generate_synthetic_data``).

    Runs the protocol-to-data pipeline and returns ONLY the final artifacts as a JSON-serializable
    dict — the extracted ProtocolDesign and the paths to the generated SDTM files. No Gradio UI
    objects (Markdown / Dataframe / component updates) are returned.

    Ingestion precedence: ``use_sample`` (bundled CARDIO-HF) → ``protocol_url`` (downloaded) →
    ``file_path`` (server-readable protocol) → error. An NCT id is **auto-detected** from the
    protocol text; if found, a read-only ClinicalTrials.gov cross-check is attached (it never
    influences generation).
    """
    final_extras = None
    detected_nct = None
    try:
        with _protocol_source(use_sample, protocol_url, _uploaded_path(file_path)) as path:
            detected_nct = _detect_nct(path)  # zero-click, read-only (never affects generation)
            for _narration, is_final, extras in execute(path, subjects, seed, anomalies):
                if is_final:
                    final_extras = extras
    except (ValueError, RuntimeError) as e:  # no input / bad URL / download failure
        return {"status": "error", "message": str(e)}
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
        "detected_nct": detected_nct,
    }
    if detected_nct:
        resp["registry_crosscheck"] = ctg_validator.fetch_ctg_baseline(detected_nct)  # read-only
    return resp


def api_download(file_path: FileData | None = None, use_sample: bool = True, subjects: int = 40,
                 seed: int = 42, anomalies: int = 0, export_format: str = EXPORT_SDTM,
                 protocol_url: str = "") -> FileData:
    """Downloadable variant of ``generate_synthetic_data`` (endpoint ``download_synthetic_data``).

    Runs the same pipeline as ``api_run``, then returns a ZIP of the generated SDTM CSVs plus
    ``design.json`` and ``run_manifest.json``. Called via ``gradio_client``, the client downloads
    the ZIP to the caller's machine (``predict()`` returns a local path) — so remote consumers get
    the actual data, not just server-side paths. Raises on a failed run (no file to return).
    """
    result = api_run(file_path, use_sample, subjects, seed, anomalies, export_format, protocol_url)
    if result.get("status") != "ok":
        raise RuntimeError(result.get("message", "Generation failed; check server logs."))
    zip_path = _zip_synthetic_data(Path(result["output_dir"]),
                                   result.get("study_id") or "dataset", result["design"])
    return FileData(path=str(zip_path))


def _zip_synthetic_data(out_dir: Path, study: str, design: dict) -> Path:
    """Bundle a run's SDTM CSVs + design.json + run_manifest.json into a ZIP; return its path."""
    zip_path = Path(tempfile.mkdtemp(prefix="ptd_zip_")) / f"{study}_sdtm.zip"
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
        for csv in sorted(out_dir.glob("*.csv")):
            z.writestr(f"{study}/{csv.name}", csv.read_bytes())
        z.writestr(f"{study}/design.json", json.dumps(design, indent=2))
        manifest = out_dir.parent / "run_manifest.json"
        if manifest.exists():
            z.writestr(f"{study}/run_manifest.json", manifest.read_bytes())
    return zip_path


def _ui_download_zip(output_dir: str):
    """UI ⬇ Download handler: zip the current run's output dir → a filepath the browser downloads.
    Returns None (no download) if no run has produced data yet."""
    if not output_dir or not Path(output_dir).exists():
        return None
    out = Path(output_dir)
    design = {}
    manifest = out.parent / "run_manifest.json"
    if manifest.exists():
        with contextlib.suppress(Exception):
            design = json.loads(manifest.read_text()).get("design", {})
    return str(_zip_synthetic_data(out, out.parent.name, design))


# High-contrast CTA styling so the primary "Run the loop" button pops out of the input column.
_CTA_CSS = """
#main_run_btn {
    background: linear-gradient(90deg, #11998e 0%, #38ef7d 100%);
    color: white;
    border: none;
    font-weight: bold;
    font-size: 1.1em;
    transition: transform 0.2s;
}
#main_run_btn:hover { transform: scale(1.02); }
"""

# Link-preview identity. Gradio hard-codes default OG/social tags ("Gradio" + a cartoon) that a
# launch(head=...) append can't override (duplicate tags → the first, Gradio's, wins in scrapers).
# _SocialTagsMiddleware rewrites them in the ROOT html only, so WhatsApp/Slack/etc. show the project.
_OG_IMAGE = "https://raw.githubusercontent.com/chetankumart/protocol-to-data/main/docs/img/ui_demo.png"
_OG_DESC = ("Turn a clinical trial protocol into an analyzable synthetic SDTM dataset — one agentic "
            "validation loop. Then chat with the data.")
_FAVICON_SVG = ("data:image/svg+xml,<svg xmlns=%22http://www.w3.org/2000/svg%22 "
                "viewBox=%220 0 100 100%22><text y=%22.9em%22 font-size=%2290%22>🧬</text></svg>")
_OG_REPLACEMENTS = [
    (b'content="Gradio"', b'content="protocol-to-data"'),                  # og:title + twitter:title
    (b'content="Click to try out the app!"', f'content="{_OG_DESC}"'.encode()),  # descriptions
    (b'<meta property="og:image" content="" />',
     f'<meta property="og:image" content="{_OG_IMAGE}" />'.encode()),
    (b'<meta name="twitter:image" content="" />',
     f'<meta name="twitter:image" content="{_OG_IMAGE}" />'.encode()),
    # Gradio's default website header collage (the "Groot / X-ray / 3D model" image) — point it
    # at our screenshot wherever it appears (og/twitter:image:src / link image_src).
    (b"https://raw.githubusercontent.com/gradio-app/gradio/main/js/_website/src/lib/assets/"
     b"img/header-image.jpg", _OG_IMAGE.encode()),
    (b'<meta property="og:url" content="https://gradio.app/" />',
     b'<meta property="og:url" content="https://protocol-to-data.onrender.com" />'),
    (b'<meta property="og:url" content="{url}" />',
     b'<meta property="og:url" content="https://protocol-to-data.onrender.com" />'),
    (b"</head>",
     (f'<meta name="twitter:image" content="{_OG_IMAGE}" />'
      f'<link rel="icon" type="image/svg+xml" href="{_FAVICON_SVG}" /></head>').encode()),
]


class _SocialTagsMiddleware:
    """ASGI middleware — rewrite Gradio's default social/OG tags in the root ('/') HTML only.

    Every other path (including the queue's SSE streams and file routes) is passed straight through
    untouched, so live narration and chat streaming are unaffected.
    """

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope.get("type") != "http" or scope.get("path") != "/":
            await self.app(scope, receive, send)
            return
        start = {}
        chunks: list[bytes] = []

        async def _send(message):
            if message["type"] == "http.response.start":
                start["msg"] = message
            elif message["type"] == "http.response.body":
                chunks.append(message.get("body", b""))
                if message.get("more_body"):
                    return
                body = b"".join(chunks)
                headers = dict(start["msg"].get("headers", []))
                if b"text/html" in headers.get(b"content-type", b"") \
                        and b"content-encoding" not in headers:
                    for old, new in _OG_REPLACEMENTS:
                        body = body.replace(old, new)
                out = [(k, v) for k, v in start["msg"]["headers"] if k.lower() != b"content-length"]
                out.append((b"content-length", str(len(body)).encode()))
                await send({"type": "http.response.start",
                            "status": start["msg"]["status"], "headers": out})
                await send({"type": "http.response.body", "body": body})

        await self.app(scope, receive, _send)


# Demo guardrails on the Data Copilot — protect the 512MB instance + API budget.
_COPILOT_MAX_CHARS = 150
_COPILOT_MAX_QUERIES = 3


def _user_turn_count(history) -> int:
    """Completed user turns so far (robust to messages-dict or [user, bot] tuple history)."""
    if not history:
        return 0
    if isinstance(history[0], dict):  # Gradio messages format: {"role", "content"}
        return sum(1 for m in history if m.get("role") == "user")
    return len(history)  # legacy tuples format


def copilot_respond(message: str, history, output_dir: str) -> str:
    """gr.ChatInterface handler → route the message to the DuckDB-backed Data Copilot.

    Enforces demo guardrails BEFORE any LLM call: a 150-char complexity cap and a 3-query/session
    turn limit. ``output_dir`` arrives from the shared ``out_dir_state`` (additional_inputs).
    """
    if len(message) > _COPILOT_MAX_CHARS:
        return ("⚠️ Demo Guardrail: Query is too complex or long. Please keep questions under "
                "150 characters for this cloud demo.")
    if _user_turn_count(history) >= _COPILOT_MAX_QUERIES:
        return ("🛑 Demo Limit Reached: You have used your 3 queries for this session. Please run "
                "a new protocol extraction to reset the Copilot.")
    result = copilot.answer(message, output_dir or "")
    if isinstance(result, str):
        return result
    import gradio as gr
    return gr.Plot(result)  # a Plotly figure → interactive chart rendered in the chat bubble


def build_ui():
    import gradio as gr

    with gr.Blocks(title="protocol-to-data", css=_CTA_CSS) as demo:
        gr.Markdown(
            "# 🧬 protocol-to-data\n"
            "**From a clinical trial protocol to an analyzable synthetic dataset — one agentic "
            "validation loop.** Upload a protocol (PDF / HTML / text), or use the bundled "
            "sample, and watch the Validation Engine extract the design, generate SDTM-shaped "
            "data, validate, and self-repair.\n\n"
            "**3 steps: Extract → Generate → Self-Validate.**"
        )
        out_dir_state = gr.State("")

        with gr.Tabs():
            with gr.Tab("⚙️ Pipeline"):
                with gr.Row():
                    with gr.Column(scale=1):
                        file_in = gr.File(label="Protocol (PDF / HTML / .md / .txt)",
                                          file_types=[".pdf", ".html", ".htm", ".md", ".txt"])
                        url_in = gr.Textbox(label="Or paste a Protocol URL (PDF/HTML/Text)",
                                            placeholder="https://...")
                        use_sample = gr.Checkbox(label="Use bundled CARDIO-HF sample", value=True)
                        gr.Markdown("<sub>Priority: Sample → URL → File upload.</sub>")
                        subjects = gr.Slider(4, 100, value=40, step=1, label="Subjects")
                        seed = gr.Number(value=42, precision=0, label="Seed (reproducible)",
                                         info="Same protocol + seed → identical data (reproducible).")
                        anomalies = gr.Slider(
                            0, 5, value=5, step=1,
                            label="Inject Noise for Pipeline Testing (Anomalies)",
                            info="Intentionally inject protocol deviations/data errors to test your "
                                 "downstream validation scripts.")
                        export_format = gr.Dropdown(
                            label="Target Export Format", choices=EXPORT_FORMATS, value=EXPORT_SDTM,
                            interactive=True,
                            info="SDTM delivered today; EDC ODM-XML on the v2 roadmap.")
                        run_btn = gr.Button("▶  Run the loop", variant="primary",
                                            elem_id="main_run_btn")
                        history_dd = gr.Dropdown(label="📁 Load a previous run",
                                                 choices=_run_choices(), value=None,
                                                 interactive=True)
                    with gr.Column(scale=2):
                        narration = gr.Textbox(label="Live agent narration", lines=10,
                                               max_lines=25, interactive=False, autoscroll=True)
                        usage_badge = gr.Markdown("🪙 Run Cost: —")  # tokens + $ for this run

                with gr.Accordion("🧩 Extracted ProtocolDesign", open=False):
                    design_code = gr.Code(language="json", label="design (post-repair)")
                with gr.Accordion("🏛️ Registry Cross-Check", open=True):
                    crosscheck_md = gr.Markdown(_CROSSCHECK_IDLE)  # caption folded in (one block)
                with gr.Accordion("🏭 Generated SDTM data", open=True):
                    domain_dd = gr.Dropdown(label="Domain", choices=[], interactive=True)
                    data_df = gr.Dataframe(label="Preview (first 200 rows)", interactive=False,
                                           wrap=True)
                    download_btn = gr.DownloadButton("⬇ Download SDTM dataset (ZIP)", size="sm")
                with gr.Accordion("🎯 Anomaly scorecard", open=True):
                    scorecard = gr.Markdown(_SCORECARD_CAPTION)  # caption folded in (one block)

            with gr.Tab("💬 Data Copilot"):
                gr.Markdown(
                    "**Chat with your generated SDTM datasets.** Ask in plain English — a DuckDB "
                    "query runs directly against the on-disk data (memory-safe, no full-file "
                    "loads), then the Data Copilot explains the result. Or **ask for a chart** — e.g. "
                    "_'bar chart of subjects per arm'_, _'pie chart of sex'_ — to see it plotted. "
                    "_Run a protocol in the ⚙️ Pipeline tab first._\n\n"
                    "> **Demo Mode: Limited to 3 queries per run. Max 150 characters.**"
                )
                chat = gr.ChatInterface(
                    copilot_respond,
                    additional_inputs=[out_dir_state],
                    api_name=False,  # keep the public API surface to just generate_synthetic_data
                )

        # Build marker — shows the deployed commit SHA so any deploy is verifiable by loading
        # the page (Render sets RENDER_GIT_COMMIT; 'local' off-platform).
        gr.Markdown(f"<sub>🧬 protocol-to-data · build `{_build_marker()}`</sub>")

        def on_run(file, use_samp, subj, sd, anom, export_fmt, protocol_url):
            rbac.require_write()  # RBAC injection point: running/generating is a write op (CDM)
            warning = _export_warning(export_fmt)  # EDC targets → roadmap notice, fall back to SDTM
            # Ingestion precedence + temp-file cleanup handled by _protocol_source (sample → URL → file).
            try:
                with _protocol_source(use_samp, protocol_url, file) as path:
                    nct = _detect_nct(path)  # zero-click, read-only (never affects generation)
                    for text, final, extras in execute(path, subj, sd, anom):
                        if not final:
                            yield {narration: warning + text}
                        else:
                            domains = extras["domains"]
                            yield {
                                narration: warning + text,
                                design_code: extras["design_json"],
                                # Read-only registry badge — auto-detected NCT, display-only, never fed to generation.
                                crosscheck_md: _render_crosscheck(extras.get("skeleton", {}), nct),
                                domain_dd: gr.update(choices=domains, value=(domains[0] if domains else None)),
                                out_dir_state: extras["output_dir"],
                                scorecard: f"{_SCORECARD_CAPTION}\n\n{extras['scorecard']}",
                                data_df: _load_domain_csv(extras["output_dir"], domains[0] if domains else ""),
                                history_dd: gr.update(choices=_run_choices()),  # surface the just-saved run
                                usage_badge: extras["usage_badge"],
                            }
            except (ValueError, RuntimeError) as e:  # no input / bad URL / download failure
                yield {narration: warning + f"❌  {e}"}

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
                scorecard: f"{_SCORECARD_CAPTION}\n\n{data['scorecard']}",
                data_df: _load_domain_csv(data["output_dir"], domains[0] if domains else ""),
            }

        # UI event listeners are presentation-only — hide them from the public API docs
        # (api_name=False) so consumers see just the clean endpoint below, not UI-update signatures.
        run_btn.click(on_run,
                      [file_in, use_sample, subjects, seed, anomalies, export_format, url_in],
                      [narration, design_code, crosscheck_md, domain_dd, out_dir_state, scorecard,
                       data_df, history_dd, usage_badge], api_name=False)
        # A new run resets the Copilot session: clear BOTH the visible chatbot and ChatInterface's
        # internal chatbot_state (the history the 3-query counter is derived from) so
        # "run a new protocol to reset the Copilot" is literally true.
        run_btn.click(lambda: ([], []), None, [chat.chatbot, chat.chatbot_state], api_name=False)
        history_dd.change(on_load_run, [history_dd],
                          [narration, design_code, domain_dd, out_dir_state, scorecard, data_df],
                          api_name=False)
        domain_dd.change(_load_domain_csv, [out_dir_state, domain_dd], data_df, api_name=False)
        download_btn.click(_ui_download_zip, [out_dir_state], download_btn, api_name=False)

        # The ONLY documented API/MCP endpoints: clean, typed functions returning final artifacts.
        gr.api(api_run, api_name="generate_synthetic_data")
        gr.api(api_download, api_name="download_synthetic_data")  # returns a downloadable ZIP

    return demo


if __name__ == "__main__":
    import gradio as gr

    from starlette.middleware import Middleware

    build_ui().queue().launch(
        theme=gr.themes.Soft(),
        server_name=_resolve_host(),   # 0.0.0.0 on Spaces/containers, 127.0.0.1 locally
        server_port=_resolve_port(),   # honors a platform-assigned $PORT (Render/Fly/…)
        # Rewrite Gradio's default link-preview tags → project title/description/image + 🧬 favicon.
        app_kwargs={"middleware": [Middleware(_SocialTagsMiddleware)]},
    )
