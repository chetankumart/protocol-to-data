# protocol-to-data — Submission

**Event:** Built with Claude: Life Sciences (Cerebral Valley × Anthropic × Gladstone Institutes)
**Track:** Build (Development) — built with Claude Code
**Repo:** https://github.com/chetankumart/protocol-to-data
**Demo video:** _(link)_
**Run it:** CLI — `ptd run examples/sample_protocol.md --subjects 40 --seed 42 --anomalies 5` · Web UI — `python app.py` (upload a protocol, watch the loop stream, browse the data)

---

## Tagline

**From a clinical trial protocol to an analyzable synthetic dataset — in one agentic loop, driven by Claude.**

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

## What it does

`protocol-to-data` is a Claude-driven agentic loop, usable from the CLI or a thin Gradio web
UI (`app.py`). Drop in a protocol (PDF/HTML/text) and:

1. **Ingest** — normalize the document to text.
2. **Extract** *(Claude)* — read the prose and emit a typed `ProtocolDesign`: arms, visits
   (days relative to first dose, with windows), endpoints mapped to SDTM domains, population,
   inclusion/exclusion, and an explicit list of assumptions it had to make.
3. **Generate** — produce statistically plausible, SDTM-shaped synthetic CSVs
   (DM/VS/LB/QS/AE/EX), deterministic with `--seed`.
4. **Validate** — schema, referential integrity, temporal rules (no pre-dose AEs),
   physiologic ranges, and **planned-domain coverage**.
5. **Repair** *(Claude)* — on any validation failure, Claude reads the report and adjusts the
   design (e.g. remaps or drops a domain the generator can't produce, noting it in
   assumptions), then regenerates. Bounded retries; it surfaces the report rather than fake success.
6. **Anomaly loop** *(Claude)* — optionally inject controlled data-quality defects
   (pre-dose AE, impossible vital, orphan record, duplicate visit, pregnancy-on-male) and have
   a second Claude agent find and explain each one, scored against ground truth.

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

**Sample HFrEF protocol** — `examples/sample_protocol.md`:
```
🧩 Extract ............ CARDIO-HF-P3: 2 arms, 6 visits, 6 endpoints, 7 domains (incl. EG)
🔎 Validate ........... FAIL: planned domain EG has no generated data
🔧 Repair (Claude) .... design adjusted (EG remapped/dropped, noted in assumptions)
🔎 Re-validate ........ PASS — 0 errors across 6 domains
🎯 Anomalies .......... Claude caught 5/5 injected defects
```

**Real 179-page oncology protocol** — Amgen AMG 510 vs Docetaxel, NSCLC KRAS G12C
(CodeBreak 200), fed as a PDF:
```
🧩 Extract ............ 2 arms (correctly identified open-label active-control, no placebo),
                        13 cycle-based visits (C1D1/C1D8/C2D1… derived from 21-day cycles),
                        19 endpoints, 14 domains
🔎 Validate ........... FAIL: 8 oncology domains the builtin can't emit (RS/TU/TR/SU/PC/CM/MH/SS)
🔧 Repair (Claude) .... dropped all 8 in one pass → PASS across 6 domains
🎯 Anomalies .......... 5/5 caught — and the detector additionally flagged that the demo
                        generator's cardiac instruments (KCCQ/NT-proBNP) don't fit an
                        oncology indication (QLQ-C30/RECIST), reasoning about clinical
                        plausibility beyond the planted defects.
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
- 23 offline tests (no key needed) cover schemas, generation/trajectories, validation, the
  repair loop, and anomaly injection/scoring.

## Honest limitations & what's next

- The **builtin generator emits cardiovascular-flavored clinical values** (NT-proBNP, KCCQ,
  NYHA) regardless of indication — great for the HFrEF demo, not for oncology. The detector
  correctly flags this on the Amgen run. Next: therapeutic-area-aware panels (e.g. QLQ-C30 +
  ANC/platelets for oncology), and the `engine-bridge` backend for full 32-domain breadth.
- Extraction currently reads the first ~120K characters of very large protocols (the synopsis
  + schedule of activities); chunked full-document extraction is a natural extension.

## Why it fits Built with Claude: Life Sciences

A practical tool for researchers, clinics, and biotech that outlasts the week; Claude is the
orchestrator across extraction, repair, and clinical-plausibility reasoning; safe and
shareable (100% synthetic, PHI-free, seed-reproducible); and it demonstrably generalizes
across therapeutic areas — from a cardiology sample to a real 179-page oncology protocol.
