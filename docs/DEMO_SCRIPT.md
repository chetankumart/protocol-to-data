# Demo Script (2–3 minutes)

Goal: show *unstructured protocol → analyzable data* with Claude reasoning visible.
Record terminal + brief slides. Narrate in first person.

## Beat 0 — Hook (0:00–0:20)
> "Every clinical trial needs realistic test data before it goes live — to configure
> systems, validate dashboards, prototype analyses. Today that's days of manual work
> and it can't touch real patient data. Watch Claude do it from just the protocol."

Show `examples/sample_protocol.md` scrolling briefly — emphasize it's raw prose.

## Beat 1 — One command (0:20–0:35)
```bash
ptd run examples/sample_protocol.md --subjects 40 --seed 42 --anomalies 5
```
Let the narrated loop print live:
```
🧬  Reading protocol .......... CARDIO-HF-P3 Phase 3
🧩  Extracting design (Claude)  2 arms, 6 visits, 4 endpoints, ~7 domains
```

## Beat 2 — Extraction is reasoning (0:35–1:05)
Pause on the extracted `ProtocolDesign`. Point out Claude inferred the visit schedule,
arms, and which SDTM domains the endpoints map to (KCCQ→QS, NT-proBNP→LB, ECG→EG…) —
from prose, no templates.

## Beat 3 — Generate + self-repair (1:05–1:45)
The protocol mentions a 12-lead ECG, so Claude plans an **EG** domain. The standalone
generator doesn't produce EG — validation flags it, and Claude repairs the design:
```
🏭  Generating synthetic data ...
🔎  Validating ............... ⚠️  FAIL: planned domain EG has no generated data
🔧  Repairing (Claude) ....... design adjusted (EG dropped / remapped, noted in assumptions)
🏭  Generating synthetic data ...
🔎  Validating ............... ✅  PASS — 0 errors across 6 planned domains
```
> "This is the key move — Claude reads its own validation failures and fixes the
> design, the way a data manager would, in seconds. It's an agent, not a pipeline."

## Beat 4 — Anomaly detection (1:45–2:20)
```
🕵️  Injecting 5 anomalies (seed 42) ...
🔎  Claude detecting ...
🎯  Claude caught 5/5 injected anomalies
    • SBP=400 in VS → physiologically implausible
    • GHOST-9999 in LB → orphan (no matching DM)
    • PREGNANCY on a male subject → logical inconsistency
    • AE onset in 2020 → pre-dose (temporal)
    • duplicated VS record → uniqueness
```

## Beat 5 — Payoff (2:20–2:45)
Open a generated CSV / show the NT-proBNP-falls-on-drug trajectory.
> "Fully synthetic, reproducible with a seed, zero PHI — and it generalizes across
> therapeutic areas. From protocol to analyzable data, driven by Claude."

## 🔒 Frozen demo path (locked Day 5 — do not change)
- **Command:** `ptd run examples/sample_protocol.md --subjects 40 --seed 42 --anomalies 5`
- **Input:** `examples/sample_protocol.md` (includes the ECG line that triggers the repair beat)
- **Deterministic offline** (no key): generation, anomaly injection, and the scorecard.
- **Model-dependent** (needs the key): extraction, the repair edit, anomaly detection.
  If a live extraction happens to be clean (no unproducible domain), the repair beat is
  simply skipped — the happy-path "PASS, 0 errors" is still a strong demo. To guarantee the
  repair beat, keep the ECG assessment in the frozen protocol.
- After the first green live run on this command, **stop changing the demo path** — only
  fix bugs, and re-record if a beat's wording drifts.

## Recording tips
- Pre-run once to warm the API cache; keep the recorded run on the frozen seed.
- Keep total under 3 min. Cut dead air during API calls in edit.
- Show the repo URL and "Built with Claude: Life Sciences — Development Track" at the end.
