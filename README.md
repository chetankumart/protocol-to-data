# protocol-to-data

> **From a clinical trial protocol to an analyzable synthetic dataset — in one agentic loop, driven by Claude.**

A researcher, clinical data manager, or biotech engineer drops in a study protocol
(PDF / HTML / text). Claude reads it, extracts the trial design, generates a
statistically realistic **SDTM/CDASH-shaped synthetic dataset**, validates it,
and (optionally) injects controlled data-quality anomalies so a downstream agent
can find and explain them.

No real patient data. No manual schema wiring. Just: **protocol in → analyzable data out.**

Built for **[Built with Claude: Life Sciences](https://cerebralvalley.ai/e/built-with-claude-life-sciences)**
(Cerebral Valley × Anthropic × Gladstone Institutes, July 7–13, 2026) — **Development Track**.

---

## The magic moment

```
$ ptd run examples/sample_protocol.md --subjects 40 --seed 42

🧬  Reading protocol ................ CARDIO-HF Phase 3, 2 arms, 8 visits
🧩  Extracting design ............... 3 endpoints, population n≈40, 12 SDTM domains
🏭  Generating synthetic data ...... DM VS AE LB QS EX  (2,140 records)
🔎  Validating ..................... 0 schema errors, 0 pre-dose AEs
✅  Dataset ready → data/output/CARDIO-HF/synthetic_data/
```

Each step is narrated by Claude with its reasoning visible — that is the demo.

---

## Why this fits the hackathon

- **Development Track**: a practical tool for researchers/clinics/biotech, built with Claude Code.
- **Agentic**: Claude is the orchestrator, not a bolt-on — it extracts, decides domains, generates, self-validates, and repairs.
- **Life-sciences native**: SDTM/CDASH clinical domains, realistic clinical logic.
- **Safe & shareable**: 100% synthetic, no PHI, reproducible with `--seed`.

See [`docs/IDEA.md`](docs/IDEA.md) for the full pitch and [`docs/BUILD_PLAN.md`](docs/BUILD_PLAN.md) for the 7-day plan.

---

## Quickstart

```bash
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
export ANTHROPIC_API_KEY=sk-ant-...

# End-to-end loop on the bundled example
python cli.py run examples/sample_protocol.md --subjects 20 --seed 42

# Individual steps
python cli.py extract examples/sample_protocol.md          # protocol → design.json
python cli.py generate design.json --subjects 20           # design → CSVs
python cli.py validate data/output/<study>/                # schema + clinical checks
python cli.py anomalies data/output/<study>/ --inject 5    # inject + detect loop
```

## Architecture (one loop)

```
 protocol ──▶ extract ──▶ ProtocolDesign ──▶ generate ──▶ dataset ──▶ validate ──┐
 (pdf/html/txt)  (Claude)     (pydantic)      (engine)     (CSVs)     (checks)    │
                                                                                  │
                        ◀── repair / regenerate on validation failure ◀───────────┘
                                                     │
                                    optional: inject anomalies ──▶ detect (Claude)
```

Full design: [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) ·
Spec: [`docs/SPEC.md`](docs/SPEC.md) ·
Skill: [`.claude/skills/protocol-to-data/SKILL.md`](.claude/skills/protocol-to-data/SKILL.md)

## Status

🚧 **Hackathon scaffold.** Schemas, CLI, skill, and the loop skeleton are in place;
generation/validation modules have working stubs with clear `TODO(hackathon)` markers
and an optional bridge to a production engine. See [`docs/BUILD_PLAN.md`](docs/BUILD_PLAN.md).

## License

MIT — see [`LICENSE`](LICENSE).
