# Functional & Technical Spec

## Goals

1. Accept any clinical protocol (pdf/html/md/txt) and produce a valid synthetic dataset.
2. Keep Claude in the driver's seat for extraction, repair, and anomaly detection.
3. Run standalone (no private dependencies) with just an API key.
4. Be reproducible and PHI-free.

## Non-goals (for the hackathon)

- Full regulatory-grade SDTM conformance (SEND/define.xml). We target *shape*, not certification.
- Every SDTM domain. Start with the demo-critical set; bridge to the engine for breadth.
- A web UI. CLI + narrated output is enough for the demo (stretch goal: thin Gradio/Streamlit front-end).

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
| referential | Every USUBJID in child domains exists in DM |
| dates | AESTDTC ≥ RFSTDTC (no pre-dose AEs); visit dates within window |
| ranges | Vitals/labs within plausible physiological bounds |
| sex-consistency | Female-only forms (e.g. pregnancy) have no male subjects |

Failures produce a `ValidationReport` that the loop feeds back to Claude for repair.

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
- `typer` or argparse (CLI)
- `pytest` (tests)

## Model usage guidance

- **Extraction / repair**: `claude-opus-4-8` (reasoning-heavy, worth the tokens).
- **Anomaly explanation**: `claude-opus-4-8` or `claude-sonnet-5`.
- **Cheap structural steps**: `claude-haiku-4-5-20251001`.
- Load the `claude-api` skill / SDK reference before wiring API calls.

## Acceptance criteria (demo-ready)

- [ ] `ptd run examples/sample_protocol.md --seed 42` completes with 0 validation errors.
- [ ] Extraction produces a sensible `ProtocolDesign` for the example.
- [ ] At least DM, VS, AE domains generated with plausible values.
- [ ] Anomaly loop injects ≥3 anomalies and Claude identifies all of them.
- [ ] Output is reproducible across two runs with the same seed.
