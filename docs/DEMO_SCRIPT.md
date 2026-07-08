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
ptd run data/protocols/Prot_000-amgen.pdf --subjects 40 --seed 42 --anomalies 5
```
Or the web UI (nicer visual): `python app.py` → upload the Amgen PDF → subjects 40, seed 42,
anomalies 5 → **Run the loop**.

## ⚠️ Pre-flight (do this BEFORE recording — it protects the Flex beat)

Some of the payoff comes from Claude's **semantic** anomaly detector, which is
non-deterministic. Reliable vs. bonus:

| Beat | Guaranteed every run? |
|------|----------------------|
| Extraction (2 arms, cycle-based visits, ~12 domains) | ✅ yes |
| Self-repair (drops unproducible oncology domains → PASS) | ✅ yes |
| **5/5 injected anomalies caught** | ✅ yes (injection is seeded) |
| PK-in-LB "CDISC" catch · grade-4 neutropenia catch | ⚠️ **bonus, not guaranteed** |

**So:** do **2–3 dry-run takes first** and record the one where the two bonus findings appear.
If a take doesn't surface them, don't force it — the 5/5 + the repair loop still closes strong.
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
🧩  Extracting design (Claude) ...
    → AMG510-20190009: 2 arms, ~12 visits, 18 endpoints, ~12 domains
```
> "It's reading the prose, not a template. It pulled both arms — sotorasib and docetaxel —
> and the full cycle-based visit schedule, Cycle 1 Day 1, Day 8, the tumor-assessment weeks.
> It mapped each endpoint to the right SDTM domain: RECIST to tumor response, the labs, the
> questionnaires. That's clinical reasoning, from a PDF."

*(Read whatever visit/domain counts appear on screen — they vary slightly per run.)*

## Beat 2 — The self-repair (1:05–1:35)
**[SCREEN]** Pause on the validation → repair → re-validation lines.
```
🔎  Validating ....... ⚠️ FAIL: planned domains EG/PC/SS/TR/TU have no generated data
🔧  Repairing (Claude) → design adjusted
🔎  Re-validating .... ✅ PASS — 0 errors across N planned domains
```
> "It planned oncology domains the standalone generator can't produce, validation caught it,
> and Claude repaired its own design and regenerated — in one pass. This is an agent, not a
> pipeline. It reads its own failures and fixes them."

## Beat 3 — The Flex: clinically-intelligent data (1:35–2:20)
**[SCREEN]** Pause on the anomaly scorecard.
> "I inject five data-quality defects into a clean copy, and a second Claude agent hunts them."
```
🎯  Claude caught 5/5 injected anomalies
```
> "Five for five — the impossible blood pressure, the pre-dose adverse event, the orphan
> record, a pregnancy logged for a male subject."

**[IF your take surfaced the bonus findings — this is the money line:]**
> "But look at what it flagged *on its own*, beyond what I planted. First — it noticed the PK
> concentrations are sitting in the LB domain instead of the dedicated PC domain. It knows
> CDISC. Second, and this is the one — it flagged a grade-4 neutrophil count in the docetaxel
> arm. Docetaxel causes severe myelosuppression. My generator modeled that, and Claude
> recognized it as a real, treatment-emergent finding. This synthetic data isn't random
> distributions — it's biologically responsive to the assigned study arm."

## Beat 4 — Payoff (2:20–2:40)
**[SCREEN]** Open `ex.csv` (or the EX table in the UI).
> "And it assigned the exact protocol regimens per arm — AMG 510 960 milligrams once daily,
> docetaxel 75 per meter-squared every three weeks. Fully synthetic, reproducible with a seed,
> zero PHI — from a 179-page PDF to analyzable, clinically-coherent data, driven by Claude."

---

# Fallback: Cardiology (CARDIO-HF sample) — simpler, lower-risk

Deterministic-friendly and no large PDF. Use if the oncology take won't cooperate.

**Command:** `ptd run examples/sample_protocol.md --subjects 40 --seed 42 --anomalies 5`

- **Hook** — show `examples/sample_protocol.md` (raw prose).
- **Extract** — `CARDIO-HF-P3: 2 arms, 6 visits, ~7 domains` (KCCQ→QS, NT-proBNP→LB, ECG→EG).
- **Repair** — the protocol's ECG makes Claude plan an EG domain the builtin can't emit;
  validation flags it, Claude repairs → PASS across 6 domains.
- **Anomalies** — `Claude caught 5/5 injected anomalies`.
- **Payoff** — open a generated CSV / the NT-proBNP-falls-on-drug trajectory.

---

## Recording tips (both versions)
- Pre-run once to warm the API cache; keep the recorded run on `--seed 42`.
- Live extraction/repair on the 179-page PDF takes ~1–2 min — **cut the dead air in editing**;
  jump-cut from "Extracting…" to the results.
- Keep total under 3 min.
- Close on the repo URL + "Built with Claude: Life Sciences — Build Track".
