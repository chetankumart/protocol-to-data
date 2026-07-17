# protocol-to-data — Submission

**Event:** Built with Claude: Life Sciences (Cerebral Valley × Anthropic × Gladstone Institutes)
**Track:** Build (Development) — built with Claude Code
**Repo:** https://github.com/chetankumart/protocol-to-data
**🔗 Live demo:** **https://protocol-to-data.onrender.com** _(Render free tier — first load may take ~30–60 s to wake, then it's snappy)_
**🎥 Demo video:** https://youtu.be/JJXIagmZX3Q
**Run it:** CLI — `ptd run examples/sample_protocol.md --subjects 40 --seed 42 --anomalies 3` · Web UI — `python app.py` · MCP — `python mcp_server.py` (Claude Desktop / any MCP client) · API — `gradio_client` → `generate_synthetic_data` (JSON) or `download_synthetic_data` (ZIP)

> **Note:** The live demo is hosted on a free Render tier (512MB RAM). It perfectly runs the bundled CARDIO-HF sample for evaluation. If you wish to test the full PDF extraction engine with massive protocols, please run the provided Docker container locally to avoid cloud out-of-memory limits.

---

## Tagline

**From a clinical trial protocol to a Databricks-ready synthetic SDTM dataset — in one agentic
loop, driven by Claude. Build your analytics pipelines before the EDC even exists.**

## The problem

Before a trial goes live — and long before any real patient enrolls — teams need realistic
data they can actually use: data managers to configure and validate EDC systems and edit
checks, statisticians to prototype analyses and SAP logic, biotech/CRO engineers to load
pipelines end-to-end without touching PHI. Today that's slow and manual: someone reads a
100–200 page protocol, hand-maps it to SDTM/CDASH domains, hand-writes generators, and
hand-checks the output. It takes days-to-weeks and drifts out of sync with the protocol.

A protocol *already contains* the full data-generation spec — arms, visit schedule,
endpoints, populations, assessments. It's just locked in prose. **Claude is very good at
reading that prose and emitting a structured design.** Once the design is structured,
generation and validation can be automated and self-correcting.

## Business value / GTM

### 🚀 From Protocol to Lakehouse (Day-One Analytics)

A critical bottleneck in clinical trials is the "data desert"—the months-long delay where downstream analytics teams wait for operational EDC systems (e.g., Medidata Rave, Veeva Vault) to be designed, deployed, and populated.

**`protocol-to-data`** solves this by outputting strictly typed **SDTM Parquet files**. Instead of waiting for the EDC, clinical data engineering teams can drop our synthetic datasets directly into a **Databricks** or Apache Spark environment on day one. This allows biostatisticians to write, test, and validate their Statistical Analysis Plan (SAP) pipelines concurrently with site activation, accelerating time-to-insight.

> **Positioning:** a *downstream pipeline accelerator*, not an EDC replacement. It complements
> Rave/Veeva — teams build against realistic synthetic data now, then swap in real extracts at
> database lock with zero pipeline rework (the ODM-XML export targets are on the v2 roadmap).
> This is why **"SDTM (Parquet) – Databricks Analytics Ready"** is the default export in the UI.

## What it does

`protocol-to-data` is a Claude-driven agentic loop, usable from the CLI or a thin Gradio web
UI (`app.py`). Drop in a protocol (PDF/HTML/text) and:

1. **Ingest** — normalize the document to text.
2. **Extract** *(Claude)* — read the prose and emit a typed `ProtocolDesign`: arms, visits
   (days relative to first dose, with windows), endpoints mapped to SDTM domains, population,
   inclusion/exclusion, and an explicit list of assumptions it had to make.
3. **Generate** — produce statistically plausible, full-breadth SDTM CSVs across up to 12
   domains (DM/VS/LB/QS/AE/EX/CM/EG/PC/RS/TU/TR), deterministic with `--seed`.
4. **Validate** — schema, referential integrity, temporal rules (no pre-dose AEs),
   physiologic ranges, and **planned-domain coverage**.
5. **Repair** *(Claude)* — on any validation failure, Claude reads the report and adjusts the
   design (e.g. remaps or drops a domain the generator can't produce, noting it in
   assumptions), then regenerates. Bounded retries; it surfaces the report rather than fake success.
6. **Anomaly loop** *(Claude)* — optionally inject controlled, **schema-valid but clinically
   implausible** defects (a severe drug-class AE on the placebo arm, an all-severe severity
   profile, a reversed dose-response) — defects deterministic validation passes, so only
   pharmacological reasoning can catch them — and have the detector find and explain each one,
   scored against ground truth.

100% synthetic, zero PHI, reproducible with a seed.

## Claude is the orchestrator, not a bolt-on

Three distinct agentic roles, all on `claude-opus-4-8`:

- **Extraction is reasoning, not regex.** Claude turns messy prose into a typed design and
  maps endpoints to the correct SDTM domains (KCCQ→QS, NT-proBNP→LB, QTcF→EG, RECIST→RS…).
- **The loop self-repairs.** Validation failures feed back to Claude, which fixes the design
  and regenerates — the move that makes this an agent, not a pipeline.
- **Detection is a second agent** that reasons about clinical plausibility, not just schema.

The whole tool was **built with Claude Code** during the hackathon week.

## Proof it works (live runs)

**Sample HFrEF protocol** — `examples/sample_protocol.md` (all planned domains are producible,
so it validates clean without a repair pass):
```
🧩 Extract ............ CARDIO-HF-P3: 2 arms, 6 visits, 6 endpoints, 7 domains (incl. EG/ECG)
🔎 Validate ........... PASS — 0 errors across 7 domains (DM/VS/LB/QS/AE/EX/EG)
🎯 Anomalies .......... Validation Engine caught 3/3 injected defects
```

**Real 179-page oncology protocol** — Amgen AMG 510 vs Docetaxel, NSCLC KRAS G12C
(CodeBreak 200), fed as a PDF (this is where the repair loop earns its keep):
```
🧩 Extract ............ 2 arms (correctly identified open-label active-control, no placebo),
                        13 cycle-based visits (C1D1/C1D8/C2D1… derived from 21-day cycles),
                        19 endpoints, ~14 domains
🔎 Validate ........... FAIL: planned domains the builtin can't emit (e.g. SU/MH/SS/IS)
🔧 Repair (Engine) .... remapped/dropped in one pass → PASS across 11 producible domains
                        (DM/VS/LB/QS/AE/EX/EG/PC/RS/TU/TR)
🎯 Anomalies .......... 3/3 caught — and the detector additionally flagged a grade-4 neutrophil
                        count in the docetaxel arm as a real, treatment-emergent finding,
                        reasoning about clinical plausibility beyond the planted defects.
```
The loop generalizes from a toy protocol to a real, messy, 179-page oncology PDF without changes.

## Built this week vs. reused

I maintain a separate, pre-existing production system for clinical synthetic data. **This
submission is the new agentic loop built during the hackathon**, not that platform.

| Built during the hackathon (this repo) | Reused / bridgeable |
|---|---|
| The agentic protocol→data loop (`loop.py`) | Clinical-realism breadth (optional `engine-bridge` backend) |
| Claude extraction agent + prompt (`extract.py`) | SDTM/CDASH domain conventions |
| Typed `ProtocolDesign` contract (`schemas.py`) | — |
| Self-validation + Claude repair edge | — |
| Anomaly inject/detect loop + scorecard (`anomalies.py`) | — |
| Builtin standalone generator (`generate.py`) | — |
| Thin Gradio web UI (`app.py`) | — |

The production engine can be *bridged in* as an optional `--backend engine-bridge`, but the
agentic orchestration — extraction, repair, detection — is what's new.

## Tech & reproducibility

- Python 3.11+, `anthropic` SDK (`claude-opus-4-8`), pydantic v2, pandas, pdfplumber.
- Robustness: JSON-mode extraction with a one-shot repair on schema-invalid output;
  head+tail dataset sampling so the detector sees appended defects.
- Deterministic: `(protocol, seed, subjects)` → identical output; `run_manifest.json` records
  protocol hash, design, seed, model id, and backend.
- Runs standalone with just `pip install -r requirements.txt` + an API key — no private deps.
- A comprehensive offline test suite (no API key needed) covers schemas, generation/
  trajectories, referential + temporal integrity, dictionary coding, validation, the repair
  loop, anomaly injection/scoring, caching, run history, and cost accounting.

## Enterprise readiness

Beyond the core loop, the app carries the systems-thinking a real deployment needs — built
lean, but showing the shape of production:

- **Ephemeral (compliance) mode.** `PTD_EPHEMERAL=1` (on by default for the hosted deployments)
  stores **nothing protocol-derived on the server** — no extraction cache, no `runs/` archive
  (the shared history dropdown is hidden, closing a cross-session exposure), per-session temp
  output swept after a few hours. Only the download ZIP survives the session. A public protocol
  the user uploads is processed as-is; the guarantee is server-side *retention*, not masking.
- **Semantic caching (cost efficiency).** In local/dev mode, extraction is content-addressed by
  the document's SHA-256 (`.cache/{hash}_extracted_design.json`) so an identical protocol never
  pays for extraction twice — a cold 25 s / one-API-call run becomes a warm **0.4 s / $0** run
  (`--no-cache` forces fresh; the cache is disabled under ephemeral mode).
- **Durable run history (state management).** In local/dev mode, every run snapshots into
  `runs/<timestamp>/` (SDTM CSVs + design + scorecard + meta); the UI's **"Load a previous run"**
  dropdown restores the whole dashboard from any saved state (skipped under ephemeral mode).
- **RBAC-aware architecture.** `rbac.py` delineates a **Clinical Data Manager** (write:
  run/generate/snapshot) from a **Statistician** (read-only: browse/restore), with the
  authorization injection points wired into the data-access and UI layers. Stubbed for the
  hackathon, not enforced — but the seams are where they belong.
- **Dictionary-coded SDTM (clinical fidelity).** AE carries `AEDECOD` (MedDRA) beside the
  verbatim `AETERM` ("bad headache" → "Headache"); the CM domain carries `CMDECOD`
  (WHODrug, "lasix" → "Furosemide"). Coding is a **deterministic dictionary coder**
  (`code_term(verbatim, dictionary)`) — an offline, reproducible stand-in that production
  replaces with an official MedDRA/WHODrug auto-encoder API. It is not a zero-shot LLM call.
- **Relational integrity (SDTM traceability).** Generation enforces both foreign keys before
  writing: every child-domain `USUBJID` must exist in DM (orphan rows dropped + asserted),
  and `VISIT ↔ VISITNUM` is asserted as a single consistent 1:1 mapping across VS/LB/QS/RS
  (the same timepoint carries the same VISITNUM everywhere) — zero dangling keys on either axis.
- **EDC-target awareness + Databricks-first export.** The UI's **Target Export Format**
  selector defaults to **"SDTM (Parquet) – Databricks Analytics Ready"** (the value delivered
  today) plus CDASH ODM-XML targets for Medidata Rave and Veeva Vault EDC — which surface a
  v2-roadmap notice and fall back to SDTM, showing awareness of the downstream EDC ecosystem
  without over-building it.
- **MCP server (Anthropic ecosystem).** The clean hybrid-AI boundary means each capability is
  an MCP tool: `mcp_server.py` exposes `extract_protocol_design`, `generate_sdtm_dataset`, and
  `validate_sdtm_dataset` to Claude Desktop / any MCP client — built for where the ecosystem
  is going, not just a standalone app.
- **PHI/PII sanitization (privacy).** A real de-identification tier (`sanitize.py`): deterministic
  regex for structured identifiers + optional Microsoft Presidio NER for names/locations/dates,
  scrubbing text **before** it reaches the LLM (opt-in via `PTD_SANITIZE_PHI=1`).
- **Containerized + cloud-deployed (portability).** Ships a non-root `Dockerfile` +
  `docker-compose.yml`, and a `render.yaml` blueprint that hosts the same image on Render's free
  tier — **live at https://protocol-to-data.onrender.com** (verified end-to-end in the cloud:
  self-repair + 3/3 anomalies + $-cost). `app.py` honors a platform-assigned `$PORT`
  (`PORT > GRADIO_SERVER_PORT > 7860`), so Railway / Fly / Cloud Run run it unchanged. A
  **CI-gated deploy** (`.github/workflows/ci.yml`) ships only green builds via a Render deploy hook,
  and the UI footer shows the live build SHA for verifiable deploys.
- **Data Copilot (natural-language analytics).** A 💬 chat tab over the generated dataset: Claude
  writes a **DuckDB** query that runs *directly on the on-disk CSVs* (streamed, `memory_limit=256MB`
  — no full-file pandas loads), so it's safe on the 512 MB tier; ask for a chart and it renders an
  interactive **Plotly** figure in-chat. Sandboxed for the demo (≤150 chars, 3 queries/run, SQL
  safety net). `copilot.py` — read-only over the produced data; it never touches generation.
- **Registry Cross-Check (verify-before-trust).** An NCT id is **auto-detected** from the protocol
  text and the extracted design (phase / arms / enrollment) is compared, **read-only**, against
  **ClinicalTrials.gov** — anchoring the LLM extraction to public government ground truth without
  ever feeding the registry into generation (`ctg_validator.py`).
- **Ingest by file *or* URL + clean API.** Mobile-friendly URL ingestion (`download.py`, precedence
  sample → URL → file, temp files auto-cleaned), and two typed HTTP endpoints (`gr.api`; UI
  internals hidden) callable via `gradio_client`: **`generate_synthetic_data`** (design + file
  paths as JSON) and **`download_synthetic_data`** (the SDTM CSVs as a downloadable ZIP). `file_path`
  is an uploadable input, so a remote caller can **upload their own protocol** (`handle_file`),
  generate, and download the result — the full loop over the API, not just server-side paths.

## Honest limitations & what's next

- The **builtin generator is therapeutic-area-aware** — a cardiology profile (NT-proBNP,
  KCCQ, NYHA) and an oncology/NSCLC profile (hematology/chemistry/coagulation/thyroid + PK
  labs, QLQ-C30/LC13 + EQ-5D-5L, arm-exact dosing like AMG 510 960 mg QD vs Docetaxel
  75 mg/m² Q3W, and RECIST response in the RS domain). Additional therapeutic areas and full
  32-domain breadth come via the `engine-bridge` backend.
- Extraction currently reads the first ~120K characters of very large protocols (the synopsis
  + schedule of activities); chunked full-document extraction is a natural extension.

## Why it fits Built with Claude: Life Sciences

A practical tool for researchers, clinics, and biotech that outlasts the week; Claude is the
orchestrator across extraction, repair, and clinical-plausibility reasoning; safe and
shareable (100% synthetic, PHI-free, seed-reproducible); and it demonstrably generalizes
across therapeutic areas — from a cardiology sample to a real 179-page oncology protocol. And
it has a clear GTM: **it collapses the critical path to analytics by producing
Databricks-ready SDTM data before a Medidata/Veeva EDC is ever stood up** — turning months of
sequential setup into parallel work.
