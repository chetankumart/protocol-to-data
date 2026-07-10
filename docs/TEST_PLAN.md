# End-to-End Test Plan — protocol-to-data

Full E2E coverage for CLI, Web UI, generation, the agentic loop, and enterprise features —
including edge, boundary, malformed, and error cases.

- **Automated:** `134` offline tests (no API key — LLM calls mocked). Run: `pytest -q`.
- **Lint:** `ruff check .` (enforced in CI on every push/PR).
- **Legend:** ✅ automated · 👤 manual · 🔑 needs a live `ANTHROPIC_API_KEY`.

Run the automated suite anywhere:
```bash
pip install -r requirements.txt ruff
ruff check . && pytest -q      # expect: All checks passed! · 134 passed
```

---

## 1. Environment & packaging

| ID | Case | Steps | Expected | Cov |
|----|------|-------|----------|-----|
| ENV-01 | Fresh-clone install | `git clone` → `python -m venv venv` → `pip install -r requirements.txt` | exit 0, no build-from-source | 👤 (verified) |
| ENV-02 | No secrets in repo | `git ls-files \| grep -E '\.env\|\.key\|\.pdf'` | no matches | 👤 |
| ENV-03 | Docker image builds | `docker build -t protocol-to-data .` (or `podman build`) | image builds, runs as non-root (uid 10001) | 👤 (verified w/ podman) |
| ENV-04 | One-command spin-up | `docker compose up` (or `podman-compose up`) | serves on `localhost:7860` | 👤 |
| ENV-05 | CI on push/PR | push to `main` / open PR | GitHub Actions runs `ruff` + `pytest`, goes green | 👤 (verified) |
| ENV-06 | `render.yaml` blueprint | inspect blueprint config | Docker runtime, free plan, `ANTHROPIC_API_KEY` `sync:false` secret | ✅ (`test_deploy`) |
| ENV-07 | Host/port resolution | `_resolve_host` / `_resolve_port` under various env | 0.0.0.0 on SPACE_ID; platform `$PORT` wins over 7860 | ✅ (`test_deploy`) |
| ENV-08 | Dockerfile cloud-ready | inspect Dockerfile | slim base, non-root, `GRADIO_SERVER_NAME=0.0.0.0`, reqs cached | ✅ (`test_deploy`) |
| ENV-09 | Live cloud deploy | open `protocol-to-data.onrender.com` → run sample | full loop runs; 5/5 anomalies; $-cost logged | 👤 (verified: $0.18, 5/5) |

## 2. CLI (`ptd`)

| ID | Case | Command | Expected | Cov |
|----|------|---------|----------|-----|
| CLI-01 | Full loop | `ptd run examples/sample_protocol.md --seed 42 --anomalies 5` | extract → repair → PASS → 5/5 → cost line | 🔑👤 |
| CLI-02 | Extract only | `ptd extract examples/sample_protocol.md -o design.json` | valid `ProtocolDesign` JSON | 🔑👤 |
| CLI-03 | Generate from design | `ptd generate design.json --subjects 20 --seed 42` | CSVs written | ✅ (`test_edge_cases`, `test_generate`) |
| CLI-04 | Validate a dataset | `ptd validate data/output/<study>/synthetic_data/` | `"passed": true` on clean data | ✅ (`test_schemas`) |
| CLI-05 | Anomalies standalone | `ptd anomalies <dir> --inject 5` | injects + detects + scores | 🔑👤 |
| CLI-06 | Determinism | run generate twice, same `--seed` | byte-identical CSVs | ✅ (`test_generate`, `test_oncology`) |
| CLI-07 | `--no-cache` | `ptd run … --no-cache` | forces fresh extraction (no cache hit) | ✅ (`test_cache`) |

## 3. Web UI (`app.py`)

| ID | Case | Steps | Expected | Cov |
|----|------|-------|----------|-----|
| UI-01 | Launch | `python app.py` → open `:7860` | UI renders (controls, narration, accordions) | ✅ build (`test_*`) 👤 |
| UI-02 | Run bundled sample | check "Use sample" → Run | narration streams; PASS; data + scorecard populate | 🔑👤 |
| UI-03 | Upload a PDF | upload `Prot_000-amgen.pdf` → Run | extracts real oncology protocol → repair → data | 🔑👤 |
| UI-04 | Live cost badge | after a run | `🪙 Run Cost: $X · Nk in / Nk out` | ✅ (`test_usage`) 👤 |
| UI-05 | Load previous run | pick from "Load a previous run" | dashboard restores design + data + scorecard | ✅ (`test_history`) 👤 |
| UI-06 | Export = SDTM/Databricks | default option → Run | runs normally, no warning | ✅ (`test_enterprise`) |
| UI-07 | Export = EDC target | choose Rave/Veeva → Run | roadmap notice prepended, still exports SDTM | ✅ (`test_enterprise`) |
| UI-08 | Domain browser | switch the Domain dropdown | table reloads for the selected domain | 👤 |

## 4. Generation — clinical fidelity

| ID | Case | Expected | Cov |
|----|------|----------|-----|
| GEN-01 | Cardiology profile | NT-proBNP/CREAT/HGB/K labs, KCCQ/NYHA PROs | ✅ (`test_generate`) |
| GEN-02 | Oncology profile (NSCLC) | heme/chem/coag/thyroid + PK labs, QLQ-C30/LC13 + EQ-5D, RECIST (RS) | ✅ (`test_oncology`) |
| GEN-03 | Therapeutic-area dispatch | indication drives profile; `therapeutic_area` authoritative | ✅ (`test_dictionary`, `test_integrity`) |
| GEN-04 | Profile misfire guard | "tumor necrosis factor" on cardio ≠ oncology | ✅ (`test_integrity`) |
| GEN-05 | AE MedDRA coding | `AEDECOD` = coded PT ("bad headache" → "Headache") | ✅ (`test_dictionary`) |
| GEN-06 | CM WHODrug coding | `CMDECOD` ("lasix" → "Furosemide") | ✅ (`test_dictionary`) |
| GEN-07 | Drug-effect realism | docetaxel neutropenia (grade-4 possible); sotorasib transaminitis | ✅ (`test_oncology`, `test_generate`) |
| GEN-08 | Arm-exact dosing | AMG 510 960 mg QD / Docetaxel 75 mg/m² Q3W | ✅ (`test_oncology`) |

## 5. Integrity — verify-before-write

| ID | Case | Expected | Cov |
|----|------|----------|-----|
| INT-01 | USUBJID referential | every child USUBJID exists in DM (orphans dropped + asserted) | ✅ (`test_integrity`, `test_edge_cases`) |
| INT-02 | VISITNUM ↔ VISIT 1:1 | same timepoint = same VISITNUM across VS/LB/QS/RS | ✅ (`test_integrity`) |
| INT-03 | VISITNUM drift rejected | inconsistent VISITNUM raises | ✅ (`test_integrity`) |
| INT-04 | All-orphan child | drops to empty, no crash | ✅ (`test_edge_cases`) |
| INT-05 | Validation checks | schema · non-empty · referential · dates · ranges · sex · coverage | ✅ (`test_schemas`) |

## 6. Agentic loop & anomalies

| ID | Case | Expected | Cov |
|----|------|----------|-----|
| LOOP-01 | Self-repair converges | unproducible domain → repair drops it → PASS | ✅ (`test_loop`) |
| LOOP-02 | Bounded repair | never fakes success; stops at `--max-repairs` | ✅ (`test_loop`) |
| LOOP-03 | Manifest persisted | `run_manifest.json` + `validation_report.json` written | ✅ (`test_loop`) |
| ANOM-01 | 5 defects injected + detected | scorecard "N/N caught" | ✅ inject/score (`test_anomalies`), 🔑 detect |
| ANOM-02 | Scorecard matching | type+domain match; missed/extra tracked | ✅ (`test_anomalies`) |

## 7. Enterprise / efficiency

| ID | Case | Expected | Cov |
|----|------|----------|-----|
| ENT-01 | Semantic cache hit | identical protocol skips extraction ($0) | ✅ (`test_cache`) |
| ENT-02 | Cache content-addressed | same content, different filename → one entry | ✅ (`test_edge_cases`) |
| ENT-03 | Corrupt cache → miss | falls back to fresh extraction | ✅ (`test_cache`) |
| ENT-04 | Cost accounting | tokens accumulate; `$` per model pricing | ✅ (`test_usage`) |
| ENT-05 | Deterministic config | `temperature=0.0` only on models that accept it (opus-4-8 omits → no 400) | ✅ (`test_llm_config`) |
| ENT-06 | RBAC stubs | write/read no-ops at CDM/Statistician injection points | ✅ (`test_enterprise`) |
| ENT-07 | Run history | snapshot → list → restore; same-second collision safe | ✅ (`test_history`) |
| ENT-08 | PHI regex scrub | emails/phones/SSN/MRN/URL redacted when `PTD_SANITIZE_PHI=1` | ✅ (`test_sanitize`) |
| ENT-09 | PHI off by default | text passes through untouched with the flag unset | ✅ (`test_sanitize`) |

## 7a. MCP server (`mcp_server.py`)

| ID | Case | Expected | Cov |
|----|------|----------|-----|
| MCP-01 | Tools importable / registered | `extract_protocol_design` / `generate_sdtm_dataset` / `validate_sdtm_dataset` exposed | ✅ (`test_mcp`, importorskip) |
| MCP-02 | Generate + validate via MCP | deterministic generation + validation callable without a key | ✅ (`test_mcp`) |
| MCP-03 | Register in Claude Desktop | tool calls succeed from an MCP client | 👤 (`docs/DEPLOY.md` §2) |

## 7b. Data Copilot · Registry Cross-Check · URL ingestion · API

| ID | Case | Expected | Cov |
|----|------|----------|-----|
| COP-01 | NL → text answer | schema-only SQL, on-disk DuckDB, result → concise answer | ✅ (`test_copilot`) |
| COP-02 | NL → chart | "bar chart of subjects per arm" → a Plotly `go.Figure` (bar/pie/line/scatter/histogram) | ✅ (`test_copilot`) |
| COP-03 | Memory cap | DuckDB `memory_limit` pinned to 256 MiB; no full-file pandas load | ✅ (`test_copilot`) |
| COP-04 | Invalid SQL safety net | bad/unsafe SQL → graceful demo message, never a crash | ✅ (`test_copilot`) |
| COP-05 | Demo guardrails | >150 chars blocked; ≥3 user turns blocked; both before any LLM call | ✅ (`test_copilot`) |
| COP-06 | Needs data | chat before a run → "generate a dataset first" | ✅ (`test_copilot`) |
| CTG-01 | Zero-click NCT detect | `NCT\d{8}` regex-detected from extracted text | ✅ (`test_ctg`) |
| CTG-02 | Registry cross-check render | Extracted vs CTG (phase/arms/enrollment) with Match/Differs; read-only | ✅ (`test_ctg`) |
| CTG-03 | Fetch failure / 404 / bad id | graceful `{"error": …}` / "unavailable", never raises | ✅ (`test_ctg`) |
| URL-01 | Download to temp file | `download_from_url` → abs temp path; suffix from content-type/URL | ✅ (`test_download`) |
| URL-02 | Ingestion precedence + cleanup | sample → URL → file → error; URL temp file removed in `finally` | ✅ (`test_api`, `test_download`) |
| URL-03 | Bad scheme / fetch error | `ValueError` / `RuntimeError`, surfaced not crashed | ✅ (`test_download`) |
| API-01 | Clean endpoint surface | only `generate_synthetic_data` documented (UI events `api_name=False`) | ✅ (`test_api`) 👤 (`view_api`) |
| API-02 | Clean payload | returns `study_id`/`design`/file paths as pure JSON; no Gradio objects | ✅ (`test_api`) |
| API-03 | `build_ui()` constructs | tabs + ChatInterface + `gr.api` + CTA CSS build without error | ✅ (`test_api`) |

## 8. Edge / boundary / error cases

| ID | Case | Expected | Cov |
|----|------|----------|-----|
| EDGE-01 | Unsupported file (`.docx`) | `ValueError` | ✅ (`test_edge_cases`) |
| EDGE-02 | Single subject (`n=1`) | generates, DM = 1 row | ✅ |
| EDGE-03 | Large cohort (`n=100`) | generates + validates clean | ✅ |
| EDGE-04 | No arms | falls back to `TREATMENT` | ✅ |
| EDGE-05 | Female-only population | all subjects `SEX=F` | ✅ |
| EDGE-06 | No visits | single fallback visit, rows still produced | ✅ |
| EDGE-07 | Only unproducible domain | DM written; coverage flags the missing domain | ✅ |
| EDGE-08 | Anomalies `count=0` | returns `[]` | ✅ |
| EDGE-09 | Anomalies `count>injectors` | capped at available injectors | ✅ |
| EDGE-10 | Anomalies on DM-only data | all injectors skip, no crash | ✅ |
| EDGE-11 | More findings than truth | extras tracked, no over-count | ✅ |
| EDGE-12 | `code_term` empty / unknown | `""` / normalized Title Case | ✅ |
| EDGE-13 | `estimate_cost` zero tokens | `0.0` | ✅ |
| EDGE-14 | Export format `None`/`""` | no warning (treated as default) | ✅ |
| EDGE-15 | Empty data dir | validation fails (missing DM) | ✅ |
| EDGE-16 | Extraction unparseable/invalid JSON | one repair pass, else surfaces error | ✅ (`test_extract`) |

## 9. Manual pre-submission smoke (do once before submitting)

1. 👤 Fresh clone → `pip install -r requirements.txt` → `ruff check . && pytest -q` → **All green, 134 passed**.
2. 🔑 `ptd run examples/sample_protocol.md --seed 42 --anomalies 5` → PASS + 5/5 + cost line.
3. 🔑 `python app.py` → run sample in the browser → narration + data + scorecard + cost badge.
4. 👤 `docker compose up` (or `podman-compose up`) → `localhost:7860` serves.
5. 👤 Open **https://protocol-to-data.onrender.com** → run the sample end-to-end in the cloud.
6. 🔑 In the **💬 Data Copilot** tab after a run: ask a text question ("subjects per arm?") and a
   chart request ("bar chart of subjects per arm") → concise answer + an interactive Plotly chart.
7. 👤 Paste a protocol **URL** (uncheck the sample) → extracts; the **🏛️ Registry Cross-Check**
   auto-populates if the protocol contains an NCT id.
8. 👤 Confirm README screenshot + Mermaid diagrams render on the GitHub page, and the link-preview
   card (share the URL) shows the project title + screenshot.

---

### Coverage summary
`134/134` automated tests green · `ruff` clean · CI enforced. Every edge/boundary/error case
above is either covered by an automated test or listed as a one-time manual check.
