---
name: protocol-to-data
description: >
  Turn a clinical trial protocol (pdf/html/md/txt) into an analyzable, SDTM/CDASH-shaped
  synthetic dataset in one agentic loop — extract design with Claude, generate data,
  self-validate, repair on failure, and optionally inject/detect anomalies. Use whenever
  the user wants synthetic clinical trial data derived from a protocol, wants to test the
  protocol→data loop, or asks to extract a structured study design from a protocol document.
---

# protocol-to-data

The single interface for the protocol→data agentic loop. Prefer this skill over calling
the modules directly.

## When to use
- "Generate synthetic data from this protocol"
- "Extract the study design from this protocol"
- "Validate this generated dataset / find data-quality anomalies"
- Any demo of the full loop for the hackathon

## Entry point

Always drive through the CLI (keeps the loop, repair, and manifest consistent):

```bash
# Full loop: protocol → design → data → validate → (repair) → (anomalies)
python cli.py run <protocol> --subjects N --seed S [--backend builtin|engine-bridge] [--anomalies K]

# Individual stages
python cli.py extract  <protocol> [-o design.json]
python cli.py generate <design.json> --subjects N --seed S
python cli.py validate <output_dir>
python cli.py anomalies <output_dir> --inject K --seed S
```

## Operating rules

1. **Standalone by default.** Use `--backend builtin` unless the user explicitly asks for
   full clinical breadth; only then use `--backend engine-bridge` (requires the private engine).
2. **Reproducible.** Always pass `--seed`. Record it in any report you produce.
3. **Zero PHI.** All data is synthetic. Never ingest or emit real patient data.
4. **Claude does the reasoning steps** (extract, repair, detect); Python does deterministic
   generation/validation. Do not hardcode design values that should be extracted.
5. **Bounded repair.** The loop retries repair a limited number of times; if it can't reach
   a clean validation, surface the `ValidationReport`, don't fake success.
6. **Model choice.** Extraction/repair → `claude-opus-4-8`; cheap structural steps →
   `claude-haiku-4-5-20251001`. Load the `claude-api` reference before editing API calls.

## Outputs
- `data/output/<STUDY>/synthetic_data/*.csv` — one CSV per SDTM domain
- `data/output/<STUDY>/validation_report.json`
- `data/output/<STUDY>/run_manifest.json` — protocol hash, design, seed, model, backend

## Prompts
- `prompts/extract_design.md` — protocol text → `ProtocolDesign`
- `prompts/detect_anomalies.md` — dataset sample → anomaly findings

## Related
- Spec: `docs/SPEC.md` · Architecture: `docs/ARCHITECTURE.md` · Idea: `docs/IDEA.md`
