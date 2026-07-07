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
🧬  Reading protocol .......... CARDIO-HF Phase 3
🧩  Extracting design ......... 2 arms, 8 visits, 3 endpoints, 12 domains
```

## Beat 2 — Extraction is reasoning (0:35–1:05)
Pause on the extracted `ProtocolDesign`. Point out Claude inferred the visit schedule,
arms, and which SDTM domains the endpoints map to — from prose, no templates.

## Beat 3 — Generate + self-repair (1:05–1:45)
Show generation, then a deliberate validation failure and the repair edge:
```
🔎  Validating ............... FAIL: 2 pre-dose adverse events
🔧  Repairing ................ Claude: "AE onset window precedes RFSTDTC; shifting."
🔎  Re-validating ............ PASS: 0 errors
```
> "This is the key move — Claude reads its own validation failures and fixes the
> design, the way a data manager would, in seconds."

## Beat 4 — Anomaly detection (1:45–2:20)
```
🕵️  Injecting 5 anomalies into a clean copy...
🔎  Claude detects: 5/5
    • SBP=400 in VS → physiologically implausible
    • LB row USUBJID-9999 → orphan (no matching DM)
    • pregnancy form, subject SEX=M → logical inconsistency
    ...
```

## Beat 5 — Payoff (2:20–2:45)
Open a generated CSV in the terminal / a quick plot.
> "Fully synthetic, reproducible with a seed, zero PHI — and it generalizes across
> therapeutic areas. From protocol to analyzable data, driven by Claude."

## Recording tips
- Pre-run once to warm the API cache; keep the recorded run on the frozen seed.
- Keep total under 3 min. Cut dead air during API calls in edit.
- Show the repo URL and "Built with Claude: Life Sciences — Development Track" at the end.
