# Architecture

## The loop

```
                            ┌──────────────────────────────────────────────┐
                            │                  ptd loop                     │
                            │                                               │
  protocol file ──────────▶│  1. INGEST   read pdf/html/txt → plain text    │
  (pdf/html/md/txt)        │       │                                        │
                           │       ▼                                        │
                           │  2. EXTRACT  Claude → ProtocolDesign (typed)   │◀── prompts/extract_design.md
                           │       │                                        │
                           │       ▼                                        │
                           │  3. PLAN     design → domain generation plan   │
                           │       │        (which SDTM domains, n, visits) │
                           │       ▼                                        │
                           │  4. GENERATE synthetic CSVs per domain         │◀── ENGINE BRIDGE (optional)
                           │       │                                        │
                           │       ▼                                        │
                           │  5. VALIDATE schema + clinical rule checks     │
                           │       │                                        │
                           │       ├── pass ─▶ 6. EMIT dataset + report     │
                           │       │                                        │
                           │       └── fail ─▶ 5a. REPAIR (Claude adjusts   │
                           │                        design/params) ─┐       │
                           │                                        │       │
                           │                    ◀───────────────────┘       │
                           │                    (bounded retries)           │
                           └──────────────────────────────────────────────┘
                                              │
                                              ▼
                          optional: 7. ANOMALY LOOP
                              inject controlled errors ─▶ Claude detects & explains
```

## Components

| Module | Responsibility | Claude? |
|--------|----------------|---------|
| `src/protocol_to_data/ingest.py` | Load pdf/html/md/txt → normalized text | no |
| `src/protocol_to_data/extract.py` | Text → `ProtocolDesign` | **yes** |
| `src/protocol_to_data/schemas.py` | Typed models (`ProtocolDesign`, `Arm`, `Visit`, `Endpoint`, `DomainPlan`) | no |
| `src/protocol_to_data/generate.py` | `ProtocolDesign` → per-domain CSVs | optional |
| `src/protocol_to_data/validate.py` | Schema + clinical-rule checks → `ValidationReport` | no (Claude reads report on repair) |
| `src/protocol_to_data/anomalies.py` | Inject controlled errors; Claude detects | **yes (detect)** |
| `src/protocol_to_data/loop.py` | Orchestrates 1–7, handles repair retries | **yes (repair)** |
| `cli.py` | `ptd run/extract/generate/validate/anomalies` | no |

## Data contracts

- **Input**: any protocol as pdf/html/md/txt.
- **Intermediate**: `ProtocolDesign` (JSON-serializable, see `schemas.py`).
- **Output**: `data/output/<STUDY>/synthetic_data/*.csv` (one CSV per SDTM domain)
  + `validation_report.json` + `run_manifest.json`.

## Generation backends

`generate.py` supports two backends selected by config/flag:

1. **`builtin`** (default, in-repo): a lean, dependency-light generator that produces
   DM/VS/AE/LB/QS/EX with plausible clinical values. Good enough to demo the loop.
2. **`engine-bridge`** (optional): shells out to the author's production engine
   (`protocol-synthetic-data-generation/scripts/engine.py`) for full 32-domain,
   clinically-rich output. Marked `ENGINE BRIDGE` in code; **not required** for the demo.

> Keeping `builtin` as default means the repo runs standalone for judges with just
> `pip install -r requirements.txt` + an API key — no access to the private engine needed.

## Reproducibility

- Every run takes `--seed`; the same (protocol, seed, subjects) → identical output.
- `run_manifest.json` records: protocol hash, design, seed, model id, timestamps, backend.

## Why the loop, not a pipeline

A straight pipeline breaks on the first messy protocol. The **repair edge** is what
makes it robust and what makes it a *Claude* project: validation failures feed back
into Claude, which adjusts the design (e.g. "AEs generated before first dose → move
AE onset window after RFSTDTC") and regenerates. This mirrors how a data manager
iterates, compressed into seconds.
