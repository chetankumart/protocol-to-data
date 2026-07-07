# Built with Claude: Life Sciences — Submission Workbook

**Event**: [Built with Claude: Life Sciences](https://cerebralvalley.ai/e/built-with-claude-life-sciences)
**Organizers**: Cerebral Valley × Anthropic × Gladstone Institutes
**Format**: Global, virtual
**Dates**: July 7 – 13, 2026 (applications closed July 5)
**Prize pool**: $100K in credits · top 500 applicants get 1 month Claude Max 20x + $200 API credits

## Tracks

| Track | Tooling | Goal |
|-------|---------|------|
| Lab Track | Claude Science (research workbench) | Explore a biological question, submit reproducible analyses/models |
| **Development Track (ours)** | **Claude Code** | **Build a practical software tool for researchers, clinics, or biotech** |

## Our submission: `protocol-to-data`

A Claude-driven agent that turns an unstructured clinical trial protocol into an
analyzable, SDTM/CDASH-shaped synthetic dataset — with self-validation and an
optional anomaly-detection loop.

### Judging (typical Claude-hackathon axes — confirm on event page)

| Axis | How we win it |
|------|---------------|
| Technical implementation | Real agentic loop: extract → generate → validate → repair, Claude in the driver's seat |
| Creativity / uniqueness | Unstructured protocol → analyzable clinical data in minutes; nobody hand-wires schemas |
| Future potential | Every trial needs realistic test data before go-live; researchers need safe data to prototype analyses |
| Pitch / demo | The narrated one-command loop is the whole demo |
| Life-sciences relevance | SDTM/CDASH clinical domains, realistic clinical trajectories, zero PHI |

## ⚠️ Positioning rule (read before submitting)

The author maintains a large **pre-existing** production system (`protocol-synthetic-data-generation`).
Judges reward **what was built during the event**, not the size of a prior platform.

- ✅ Present `protocol-to-data` as the **new thing built this week**: the Claude-driven
  protocol→data loop, the extraction agent, the self-repair, the anomaly-detection loop.
- ✅ Be transparent that the heavy-duty generation engine can be *bridged in* as a backend
  (see `src/protocol_to_data/generate.py` → `ENGINE BRIDGE`), but the agentic orchestration is new.
- ❌ Do not submit the production platform itself.

## Submission checklist

- [ ] Public repo pushed to `github.com/chetankumart/protocol-to-data`
- [ ] README with quickstart + the "magic moment" (done)
- [ ] 2–3 min demo video (see `docs/DEMO_SCRIPT.md`)
- [ ] Written description emphasizing what was built during the hackathon
- [ ] One reproducible example (`examples/sample_protocol.md` + `--seed 42`)
- [ ] Note Claude Code usage in the build (skill + agentic loop)
- [ ] Submit on the Cerebral Valley project page before the deadline

## Timeline

See [`docs/BUILD_PLAN.md`](docs/BUILD_PLAN.md) for the day-by-day 7-day plan.
