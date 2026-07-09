# Functional & Technical Spec

## Goals

1. Accept any clinical protocol (pdf/html/md/txt) and produce a valid synthetic dataset.
2. Keep Claude in the driver's seat for extraction, repair, and anomaly detection.
3. Run standalone (no private dependencies) with just an API key.
4. Be reproducible and PHI-free.

## Non-goals (for the hackathon)

- Full regulatory-grade SDTM conformance (SEND/define.xml). We target *shape*, not certification.
- Every SDTM domain. Start with the demo-critical set; bridge to the engine for breadth.
- Real EDC ODM-XML export (Rave/Veeva). The UI surfaces these as v2-roadmap targets that fall
  back to SDTM — the value delivered today is Databricks-ready SDTM Parquet.

> **Delivered beyond the original plan:** a thin **Gradio web UI** (`app.py`, was a stretch
> goal), an **MCP server** (`mcp_server.py`), opt-in **PHI/PII sanitization** (`sanitize.py`),
> and a free **cloud deployment** (Render, `render.yaml`) — see the sections below.

## `ProtocolDesign` (the contract)

```python
ProtocolDesign
├── study_id: str                 # e.g. "CARDIO-HF-P3"
├── title: str
├── phase: str                    # "1" | "2" | "3" | "4"
├── therapeutic_area: str         # e.g. "cardiovascular"
├── indication: str
├── arms: list[Arm]               # name, description, n_planned, is_placebo
├── visits: list[Visit]           # name, day, window_days, is_screening, is_treatment
├── endpoints: list[Endpoint]     # name, type(primary/secondary), domain, measure
├── population: Population         # n_subjects, age_range, sex, key_inclusion/exclusion
└── domains: list[DomainPlan]     # domain(DM/VS/AE/...), source_endpoints, key_variables
```

## CLI surface

| Command | Description |
|---------|-------------|
| `ptd run <protocol> [--subjects N] [--seed S] [--backend builtin\|engine-bridge] [--anomalies K]` | Full loop |
| `ptd extract <protocol> [-o design.json]` | Protocol → design only |
| `ptd generate <design.json> [--subjects N] [--seed S]` | Design → CSVs |
| `ptd validate <output_dir>` | Run validation report |
| `ptd anomalies <output_dir> --inject K [--seed S]` | Inject + detect loop |

## Validation checks (v1)

| Check | Rule |
|-------|------|
| schema | Each CSV has required columns for its domain |
| non-empty | Every planned domain has ≥1 row |
| coverage | Every *planned* domain produced data (the failure that drives repair) |
| referential | Every USUBJID in child domains exists in DM (orphans dropped + asserted pre-write) |
| VISITNUM 1:1 | `VISIT ↔ VISITNUM` is a single consistent mapping across VS/LB/QS/RS |
| dates | AESTDTC ≥ RFSTDTC (no pre-dose AEs); visit dates within window |
| ranges | Vitals/labs within plausible physiological bounds |
| sex-consistency | Female-only forms (e.g. pregnancy) have no male subjects |

Failures produce a `ValidationReport` that the loop feeds back to Claude for repair.

## New surfaces & features (delivered)

### MCP server (`mcp_server.py`)
A FastMCP server exposes the loop as Model Context Protocol tools for Claude Desktop / any MCP client:

| Tool | Does | Needs key? |
|------|------|-----------|
| `extract_protocol_design(protocol_text)` | Claude → typed `ProtocolDesign` JSON | yes |
| `generate_sdtm_dataset(design_json, subjects, seed)` | deterministic SDTM generation | no |
| `validate_sdtm_dataset(data_dir)` | schema + integrity + clinical checks | no |

`pip install ".[mcp]"` then `python mcp_server.py` (stdio transport).

### PHI/PII sanitization (`sanitize.py`)
Opt-in via `PTD_SANITIZE_PHI=1` — scrubs identifiers **before** any text reaches Claude:
deterministic regex (email, phone, SSN, MRN, URL) always runs; `pip install ".[phi]"` adds
Microsoft Presidio NER for PERSON / LOCATION / DATE_TIME. Off by default (protocols are
design docs, usually PHI-free).

### Enterprise seams
Semantic extraction cache (SHA-256 content-addressed, `--no-cache` to force fresh) · run
history snapshots (`runs/<timestamp>/`, restorable in the UI) · RBAC injection-point stubs
(CDM write / Statistician read) · dictionary coding (`AEDECOD` MedDRA, `CMDECOD` WHODrug) ·
per-run token + `$` cost accounting · Target Export Format selector (SDTM default + EDC stubs).

### Deployment
- **Local:** `python app.py` (127.0.0.1:7860).
- **Container:** `docker compose up` / `podman-compose up` (`Dockerfile`, non-root, binds 0.0.0.0).
- **Cloud (free):** `render.yaml` → Render, live at **https://protocol-to-data.onrender.com**.
  `app.py` honors platform `$PORT` (`PORT > GRADIO_SERVER_PORT > 7860`) so Railway/Fly/Cloud Run
  also work unchanged. See `docs/DEPLOY.md`.

## Anomaly catalog (v1)

| Anomaly | Injection | What Claude should catch |
|---------|-----------|--------------------------|
| pre-dose AE | shift one AESTDTC before RFSTDTC | temporal impossibility |
| out-of-range vital | set SBP to 400 | physiologic implausibility |
| orphan record | add LB row with unknown USUBJID | referential integrity |
| duplicate visit | duplicate a VS visit row | uniqueness |
| sex mismatch | male subject in pregnancy form | logical inconsistency |

## Tech stack

- Python 3.11+
- `anthropic` (Claude API — model default `claude-opus-4-8`; use `claude-haiku-4-5` for cheap steps)
- `pydantic` v2 (schemas)
- `pandas` (CSV assembly/validation)
- `pdfplumber` (pdf ingest), `beautifulsoup4` (html ingest)
- `gradio` (web UI, `app.py`)
- argparse (CLI)
- `pytest` + `ruff` (tests + lint, CI-enforced)
- Optional extras: `mcp` (`pip install ".[mcp]"` — MCP server), `presidio-analyzer`/`presidio-anonymizer` (`.[phi]` — PHI NER)
- Packaging: `Dockerfile` + `docker-compose.yml` (container), `render.yaml` (free cloud deploy)

## Model usage guidance

- **Extraction / repair**: `claude-opus-4-8` (reasoning-heavy, worth the tokens).
- **Anomaly explanation**: `claude-opus-4-8` or `claude-sonnet-5`.
- **Cheap structural steps**: `claude-haiku-4-5-20251001`.
- Load the `claude-api` skill / SDK reference before wiring API calls.

## Acceptance criteria (demo-ready) — ✅ all met

- [x] `ptd run examples/sample_protocol.md --seed 42` completes with 0 validation errors.
- [x] Extraction produces a sensible `ProtocolDesign` for the example (and for a real 179-page oncology PDF).
- [x] At least DM, VS, AE domains generated with plausible values (DM/VS/LB/QS/AE/EX + RS for oncology).
- [x] Anomaly loop injects ≥3 anomalies and Claude identifies all of them (5/5, verified locally **and** on the live cloud demo).
- [x] Output is reproducible across two runs with the same seed.
