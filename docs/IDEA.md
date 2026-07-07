# The Idea

## One line

**Turn a clinical trial protocol into an analyzable synthetic dataset in one agentic loop, driven by Claude.**

## The problem

Before a clinical trial goes live — and long before any real patient enrolls — teams
need realistic data:

- **Data managers** need test data to configure and validate EDC systems, edit checks, and dashboards.
- **Statisticians / researchers** need representative data to prototype analyses and SAP logic.
- **Biotech / CRO engineers** need to load pipelines end-to-end without touching PHI.

Today this is slow and manual: someone reads a 100-page protocol, hand-maps it to
SDTM/CDASH domains, hand-writes generators, and hand-checks the output. It takes
days-to-weeks and drifts out of sync with the protocol.

## The insight

A protocol *already contains* the full data-generation spec — arms, visit schedule,
endpoints, populations, assessments. It's just locked in prose. **Claude is very good
at reading that prose and emitting structured design.** Once the design is structured,
generation and validation can be automated and self-correcting.

So the whole thing becomes one loop with Claude as the orchestrator:

```
protocol ─▶ (Claude extracts design) ─▶ (generate data) ─▶ (validate)
                       ▲                                        │
                       └──────── repair / regenerate ◀──────────┘
```

## What makes it a *Claude* project (not just a script)

1. **Extraction is reasoning, not regex.** Claude reads messy protocol text and
   produces a typed `ProtocolDesign` (arms, visits, endpoints, domains, populations).
2. **The loop self-repairs.** When validation fails (e.g. pre-dose adverse events,
   schema drift), Claude reads the failures and adjusts the design or generation params.
3. **Anomaly detection is a second agent.** Inject controlled errors, then have Claude
   find and explain them — a live demo of clinical data quality reasoning.

## Why it can win Built with Claude: Life Sciences

- **Development Track fit**: a real tool for researchers/clinics/biotech.
- **Demo-able in 3 minutes**: one command, narrated reasoning, real CSV output.
- **Safe**: 100% synthetic, reproducible with a seed, no PHI — ideal for a public demo.
- **Extensible story**: the same loop generalizes across therapeutic areas
  (the author's production engine already covers CV + oncology + vaccines), so
  "future potential" is concrete, not hand-wavy.

## Scope for the week (what's actually new)

| Built during hackathon | Reused / bridged |
|------------------------|------------------|
| The agentic protocol→data loop (`loop.py`) | Clinical-realism generation logic (bridge) |
| Claude extraction agent (`extract.py`) | SDTM/CDASH domain conventions |
| Typed `ProtocolDesign` schema | — |
| Self-validation + repair | — |
| Anomaly inject/detect loop | Anomaly catalog concepts |
| The `protocol-to-data` skill | — |

See [`BUILD_PLAN.md`](BUILD_PLAN.md).
