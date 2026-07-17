# Demo Script

Two versions below. **Record the Oncology (Amgen) version** — it's the stronger story:
a dense, unstructured 179-page protocol → a biologically-responsive, self-repairing SDTM
dataset. The CARDIO-HF version is kept as a simpler, lower-risk fallback.

---

# ★ Primary: Oncology (Amgen AMG 510 / CodeBreak 200)

**Goal:** show *unstructured 179-page oncology protocol → clinically-intelligent SDTM data*,
with Claude's reasoning visible. Target length **2:30**. Narrate in first person.

**The one command (lock this seed):**
```bash
ptd run data/protocols/Prot_000-amgen.pdf --subjects 40 --seed 42 --anomalies 3
```
Or the web UI (nicer visual): `python app.py` → upload the Amgen PDF → subjects 40, seed 42,
anomalies 3 → **Run the loop**.

> **Live cloud option:** the exact same UI is public at **https://protocol-to-data.onrender.com**
> (free Render tier). You can record straight from the cloud URL to prove it's really deployed —
> just **pre-warm it** (open it once ~1 min before recording; the free instance cold-starts in
> ~30–60 s after idle). Local `python app.py` is faster/steadier for the take; the cloud URL is
> the "and it's live, try it yourself" closer.

## ⚠️ Pre-flight (do this BEFORE recording — it protects the Flex beat)

Some of the payoff comes from Claude's **semantic** anomaly detector, which is
non-deterministic. Reliable vs. bonus:

| Beat | Guaranteed every run? |
|------|----------------------|
| Extraction (2 arms, cycle-based visits, ~12 domains) | ✅ yes |
| Self-repair (drops unproducible oncology domains → PASS) | ✅ yes |
| **3/3 injected anomalies caught** | ✅ yes (injection is seeded) |
| grade-4 neutropenia catch (extra plausibility finding) | ⚠️ **bonus, not guaranteed** |

**So:** do **2–3 dry-run takes first** and record the one where the bonus finding appears.
If a take doesn't surface it, don't force it — the 3/3 + the repair loop still closes strong.
Also: **warm the cache** with one throwaway run so the recorded run is faster, and keep
`--seed 42` (that seed produced a grade-4 ANC dip and clean detections in testing).

## Beat 0 — The Hook (0:00–0:20)
**[SCREEN]** Scroll the Amgen PDF fast — title page, then the dense schedule-of-activities table.
> "This is a real 179-page oncology protocol — AMG 510 versus docetaxel in lung cancer.
> Today, turning this into usable test data means someone reads all of it and hand-builds
> SDTM datasets by hand. Days of work. Watch Claude do it from the raw PDF."

## Beat 1 — The Magic: extraction is reasoning (0:20–1:05)
**[SCREEN]** Run the command / hit **Run**. Let the narration stream.
```
🧩  Extracting protocol design (Validation Engine) ...
    → AMG510-20190009: 2 arms, ~12 visits, 18 endpoints, ~14 domains
```
> "It's reading the prose, not a template. It pulled both arms — sotorasib and docetaxel —
> and the full cycle-based visit schedule, Cycle 1 Day 1, Day 8, the tumor-assessment weeks.
> It mapped each endpoint to the right SDTM domain: RECIST to tumor response, the labs, the
> questionnaires. That's clinical reasoning, from a PDF."

*(Read whatever visit/domain counts appear on screen — they vary slightly per run.)*

## Beat 2 — The self-repair (1:05–1:35)
**[SCREEN]** Pause on the validation → repair → re-validation lines.
```
🔎  Validating ....... ⚠️ FAIL: planned domains SU/MH/SS/IS have no generated data
🔧  Repairing design (Validation Engine) → design adjusted
🔎  Re-validating .... ✅ PASS — 0 errors across N planned domains
```
> "It planned oncology domains the standalone generator can't produce, validation caught it,
> and the engine repaired its own design and regenerated — in one pass. This is an agent, not a
> pipeline. It reads its own failures and fixes them."

## Beat 3 — The Flex: clinically-intelligent data (1:35–2:20)
**[SCREEN]** Pause on the anomaly scorecard.
> "I inject clinically-implausible defects into a clean copy — defects that are schema-valid, so
> only pharmacological reasoning can catch them — and the Validation Engine hunts them."
```
🎯  Validation Engine caught 3/3 injected anomalies
```
> "Three for three — a severe drug-class adverse event logged on the placebo arm, an
> implausibly all-severe severity profile, and a reversed dose-response (a drug-sensitive lab
> that shows no treatment effect). Deterministic validation passes all three — they're only
> wrong to someone who understands the pharmacology."

**[IF your take surfaced a bonus finding — this is the money line:]**
> "And look at what it flagged *on its own*, beyond what I planted — a grade-4 neutrophil count
> in the docetaxel arm. Docetaxel causes severe myelosuppression. My generator modeled that, and
> the engine recognized it as a real, treatment-emergent finding. This synthetic data isn't
> random distributions — it's biologically responsive to the assigned study arm."

## Beat 4 — Payoff (2:20–2:40)
**[SCREEN]** Open `ex.csv` (or the EX table in the UI).
> "And it assigned the exact protocol regimens per arm — AMG 510 960 milligrams once daily,
> docetaxel 75 per meter-squared every three weeks. Fully synthetic, reproducible with a seed,
> zero PHI — from a 179-page PDF to analyzable, clinically-coherent data, driven by Claude."

## Bonus beat — Data Copilot (optional, if you have ~20s)
**[SCREEN]** Switch to the **💬 Data Copilot** tab. Type `bar chart of subjects per arm`.
> "And you can just *talk* to the data. Claude writes a DuckDB query that runs directly on the
> generated files — memory-safe — and here it plots it. No SQL, no export. From protocol PDF to a
> chart, in one app."

*(Also show the 🏛️ Registry Cross-Check panel: "it even auto-detected the NCT id and checked our
extraction against ClinicalTrials.gov — the phase and arms match.")*

---

# Fallback: Cardiology (CARDIO-HF sample) — simpler, lower-risk

Deterministic-friendly and no large PDF. Use if the oncology take won't cooperate.

**Command:** `ptd run examples/sample_protocol.md --subjects 40 --seed 42 --anomalies 3`

- **Hook** — show `examples/sample_protocol.md` (raw prose).
- **Extract** — `CARDIO-HF-P3: 2 arms, 6 visits, ~7 domains` (KCCQ→QS, NT-proBNP→LB, ECG→EG).
- **Repair** — the protocol may plan a domain the builtin can't emit; validation flags it, the
  engine repairs → PASS across the ~7 producible domains (DM/VS/LB/QS/AE/EX/EG).
- **Anomalies** — `Validation Engine caught 3/3 injected anomalies`.
- **Payoff** — open a generated CSV / the NT-proBNP-falls-on-drug trajectory.

---

## Recording tips (both versions)
- Pre-run once to warm the API cache; keep the recorded run on `--seed 42`.
- Live extraction/repair on the 179-page PDF takes ~1–2 min — **cut the dead air in editing**;
  jump-cut from "Extracting…" to the results.
- Keep total under 3 min.
- Close on the repo URL + the **live demo (`protocol-to-data.onrender.com`)** + "Built with
  Claude: Life Sciences — Build Track". The "it's deployed, judges can run it themselves" line
  lands the enterprise-readiness story.
