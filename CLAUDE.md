# CLAUDE.md — protocol-to-data

**Project**: protocol-to-data — protocol → analyzable synthetic clinical dataset, one agentic loop.
**Event**: Built with Claude: Life Sciences (Cerebral Valley × Anthropic × Gladstone), Jul 7–13 2026, Development Track.

## What this is
A Claude-driven loop: ingest a protocol → **extract** a typed `ProtocolDesign` (Claude) →
**generate** SDTM-shaped synthetic CSVs → **validate** → **repair** on failure (Claude) →
optionally **inject + detect anomalies** (Claude). See `docs/ARCHITECTURE.md`.

## Agent rules
1. **Skill-first**: drive everything through the `protocol-to-data` skill / `cli.py`, not ad-hoc imports.
2. **Standalone default**: `--backend builtin`. Only use `engine-bridge` when full clinical breadth is explicitly requested.
3. **Reproducible**: always pass `--seed`; it goes in `run_manifest.json`.
4. **Zero PHI**: synthetic only. Never ingest/emit real patient data.
5. **Claude does reasoning** (extract/repair/detect); Python does deterministic generation/validation. Don't hardcode what should be extracted.
6. **Bounded repair**: never fake a clean validation — surface the `ValidationReport`.
7. **Models**: extraction/repair → `claude-opus-4-8`; cheap steps → `claude-haiku-4-5-20251001`. Load the `claude-api` reference before editing `llm.py`.

## Layout
```
cli.py                     # ptd entry point (run/extract/generate/validate/anomalies)
src/protocol_to_data/      # ingest, extract, generate, validate, anomalies, loop, llm, schemas
prompts/                   # extract_design.md, detect_anomalies.md
docs/                      # IDEA, ARCHITECTURE, SPEC, BUILD_PLAN, DEMO_SCRIPT
examples/sample_protocol.md
tests/                     # offline (no API key needed)
```

## Commands
```bash
python cli.py run examples/sample_protocol.md --subjects 20 --seed 42 --anomalies 5
pytest -q                  # offline smoke tests (schemas + builtin gen + validate)
```

## Do NOT
- Import from the private `protocol-synthetic-data-generation` engine except via the
  documented ENGINE BRIDGE in `generate.py`.
- Commit `.env` or generated data (see `.gitignore`).
- Present the pre-existing production platform as the submission (see `HACKATHON.md`).
