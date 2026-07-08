# Architecture

## The loop

```mermaid
flowchart TD
    P["📄 Protocol<br/>(pdf / html / md / txt)"] --> I1["1 · INGEST<br/>read → plain text"]
    I1 --> I2["2 · EXTRACT (Claude)<br/>text → ProtocolDesign (typed)"]:::claude
    I2 --> I3["3 · PLAN<br/>which SDTM domains · n · visits"]
    I3 --> I4["4 · GENERATE<br/>synthetic CSVs per domain"]
    EB["ENGINE BRIDGE<br/>(optional backend)"] -. bridge .-> I4
    I4 --> I5{"5 · VALIDATE<br/>schema · referential + temporal<br/>integrity · clinical rules"}
    I5 -- pass --> I6["6 · EMIT<br/>dataset + validation report + run manifest"]
    I5 -- fail --> I5a["5a · REPAIR (Claude)<br/>reads failures, adjusts design / params"]:::claude
    I5a -- bounded retries --> I4
    I6 --> A1["7 · ANOMALY LOOP<br/>inject controlled errors (seeded)"]
    A1 --> A2["detect + explain (Claude)<br/>score N/N caught"]:::claude

    classDef claude fill:#5b3df5,stroke:#3a24b3,color:#ffffff;
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

1. **`builtin`** (default, in-repo): a lean, dependency-light, **therapeutic-area-aware**
   generator that produces DM/VS/LB/QS/AE/EX (+ RS for oncology) with plausible clinical
   values. It picks a clinical profile from the design's indication — a **cardiology**
   default (NT-proBNP/KCCQ/NYHA) and an **oncology** profile (NSCLC lab panel + PK,
   QLQ-C30/LC13 + EQ-5D-5L, arm-exact dosing, RECIST response) — so the same loop generates
   indication-appropriate data. Good enough to demo the loop across therapeutic areas.
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
