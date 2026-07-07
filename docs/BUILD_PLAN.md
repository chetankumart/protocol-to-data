# 7-Day Build Plan (July 7–13, 2026)

Time-boxed so a demo exists by Day 5, then polish. Each day ends with something runnable.

## Day 1 (Mon Jul 7) — Skeleton runs end-to-end on stubs
- [x] Repo structure, docs, skill, schemas, CLI, loop skeleton (this scaffold)
- [x] `pip install -r requirements.txt` clean in a fresh venv
- [x] Offline suite green (`pytest` — schemas + builtin gen/validate + extraction)
- [x] `.env` loading wired into `cli.py` (dependency-free loader)
- [ ] Wire `ANTHROPIC_API_KEY` + a smoke call to Claude — **needs the hackathon key**

## Day 2 (Tue Jul 8) — Real extraction
- [x] `ingest.py` (pdf/html/md/txt → text) — complete
- [x] `extract.py`: Claude → `ProtocolDesign` via structured outputs (`messages.parse`),
      with JSON-mode + one-shot repair fallback and DM/dedupe normalization
- [x] Offline tests for all extraction paths (mocked LLM, no key)
- [ ] Validate extraction on `sample_protocol.md`; hand-check the design JSON — **needs the key**
- [ ] `ptd extract` produces a correct design — **needs the key**

## Day 3 (Wed Jul 9) — Real generation (builtin backend)
- [x] `generate.py` builtin: DM → VS → LB → QS → AE → EX (all six domains)
- [x] Deterministic with `--seed`; dates anchored to visit schedule + RFSTDTC
      (screening now lands before first dose)
- [x] Light HFrEF trajectories: NT-proBNP falls / KCCQ rises / NYHA downgrades,
      stronger on active drug than placebo — visible treatment effect in the demo
- [x] Validation extended: LB/QS schema checks + lab physiologic-range check
- [x] `ptd generate design.json` produces CSVs (verified end-to-end, no key)
- [x] Offline tests for LB/QS, trajectory, determinism, date anchoring

## Day 4 (Thu Jul 10) — Validation + self-repair
- [ ] Implement `validate.py` checks (see SPEC)
- [ ] Wire repair edge in `loop.py`: failures → Claude adjusts design/params → regenerate
- [ ] Demonstrate a real repair (e.g. pre-dose AE auto-fixed)

## Day 5 (Fri Jul 11) — Anomaly loop + FREEZE demo path
- [ ] Implement `anomalies.py` inject + Claude detect/explain
- [ ] `ptd run ... --anomalies 5` works end-to-end
- [ ] 🔒 Freeze a known-good demo command + seed; stop adding features to the demo path

## Day 6 (Sat Jul 12) — Demo video + write-up
- [ ] Record 2–3 min narrated demo (see `DEMO_SCRIPT.md`)
- [ ] Write submission description (emphasize what was built this week)
- [ ] Clean README, add screenshots/gif of the narrated loop

## Day 7 (Sun Jul 13) — Buffer + submit
- [ ] Fresh-clone test on a clean machine/venv
- [ ] Push final to `github.com/chetankumart/protocol-to-data`
- [ ] Submit on Cerebral Valley project page **before deadline**
- [ ] Stretch (only if green): thin Gradio front-end, second therapeutic area

## Stretch goals (do not block submission)
- Engine-bridge backend for full 32-domain output
- Web UI (Gradio/Streamlit) showing the narrated loop
- `define.xml` / metadata emission
- Protocol-diff mode (v1 vs v2 → regenerate affected domains)

## Cut lines (if behind)
1. Drop anomaly loop from the *demo* (keep code) — extraction+generation+repair still wins.
2. Drop LB/QS/EX; demo DM+VS+AE only.
3. Drop pdf/html ingest; accept md/txt only for the demo protocol.
