# 7-Day Build Plan (July 7–13, 2026)

Time-boxed so a demo exists by Day 5, then polish. Each day ends with something runnable.

## Day 1 (Mon Jul 7) — Skeleton runs end-to-end on stubs
- [x] Repo structure, docs, skill, schemas, CLI, loop skeleton (this scaffold)
- [ ] `pip install -r requirements.txt` clean in a fresh venv
- [ ] `ptd run examples/sample_protocol.md` runs through all stages on stubbed data
- [ ] Wire `ANTHROPIC_API_KEY` + a smoke call to Claude

## Day 2 (Tue Jul 8) — Real extraction
- [ ] Implement `ingest.py` (pdf/html/md/txt → text)
- [ ] Implement `extract.py`: Claude → `ProtocolDesign` using `prompts/extract_design.md`
- [ ] Validate extraction on `sample_protocol.md`; hand-check the design JSON
- [ ] `ptd extract` produces a correct design

## Day 3 (Wed Jul 9) — Real generation (builtin backend)
- [ ] Implement `generate.py` builtin: DM → VS → AE → LB → QS → EX
- [ ] Deterministic with `--seed`; dates anchored to visit schedule + RFSTDTC
- [ ] `ptd generate design.json` produces CSVs

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
