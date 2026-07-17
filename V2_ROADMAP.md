# V2 Roadmap — protocol-to-data

**Status:** v1.0.0 **submitted & locked** — the hackathon submission deadline is **today, 2026-07-13**.
**Extended access:** the **Fable** environment (`claude-fable-5`) is available to us through
**2026-07-19** — this is *model access only*, **not** a submission extension.
**This ticket:** V2.0 — **OpenFDA Adverse-Event grounding** (V2 Ticket #1). **Paused before any code.**

**Next session — two objectives (in order):**
1. **Fable assessment** — a rigorous **architectural & security review of v1.0.0** using `claude-fable-5`.
2. **V2 Phase 0** — Contracts & Flag (start of this sprint, below).

> Planning doc only — **no Python written yet.** Contracts below are descriptions, not implementations.

---

## Goal & the sacred invariant

Make synthetic **Adverse Events pharmacologically grounded** in real-world OpenFDA frequencies —
**without** breaking `generate.py`'s core invariant: **deterministic, zero-LLM, zero-network,
seed-reproducible.** Grounding is fetched **once at design time** and stored as **data on the
design**; the generator only *reads* that data and samples deterministically.

Why this shape (and why the naive version was rejected): `generate.py:_gen_ae` is pure
deterministic Python (`rng.choice` over a fixed dict) — no LLM, no prompt. Injecting a live
API/LLM call there would have destroyed 0-LLM coupling, seed reproducibility, and the offline test
suite. The OpenFDA `count` endpoint returns **frequencies = sampling weights**, so a
deterministic-data path achieves the clinical goal *better* than an LLM prompt would.

---

## 🔒 Locked decisions (agreed 2026-07-13)

| # | Decision | Locked choice |
|---|----------|---------------|
| 1 | Grounding field shape | A typed **`AEGrounding` Pydantic submodel** — `{ term: str, count: int }` — carried as `ProtocolDesign.grounded_ae: list[AEGrounding]` (optional, default empty). **Not** a bare `dict`. |
| 2 | HTTP client | **Reuse `curl_cffi`** (already a dependency; mirrors `ctg_validator.py` / `download.py`). No new `requests` dependency. |
| 3 | AE term mapping | **Strict `AETERM == AEDECOD == the OpenFDA MedDRA PT`** for grounded rows (OpenFDA `reactionmeddrapt` is already a Preferred Term). The verbatim `code_term` dictionary remains only on the fallback path. |
| 4 | Result cap | **`top_n = 15`** most-frequent reactions, to bound design/manifest size. |
| 5 | Drug-name resolution | **3-step fallback cascade** (try each until OpenFDA returns data): **(a)** non-placebo `arm.name` → **(b)** drug token parsed from `arm.description` → **(c)** EX-regimen `EXTRT` / indication-derived generic. Placebo arms always skipped. *(Exact per-step parsing finalized in Phase 1.)* |

**Defaults:** feature is **OFF by default** (`PTD_GROUND_AE=1` env **or** `ptd run … --ground-ae`).
Flag-off, or OpenFDA empty/unreachable, ⇒ **byte-identical to v1** (graceful fallback).

---

## 🗓️ 5-Phase Sprint Plan

### Phase 0 — Contracts & flag (½ day)  ← **START HERE next session**
| Integration point | Change | Contract |
|---|---|---|
| `src/protocol_to_data/schemas.py` → `ProtocolDesign` | Add `AEGrounding` submodel + optional `grounded_ae: list[AEGrounding] = []` | Optional + default empty → every existing design / cached `.json` / test stays valid. |
| Opt-in flag | `PTD_GROUND_AE=1` env **and** `ptd run … --ground-ae` | Thread `ground_ae: bool = False` through `cli.py → run_loop`. Off ⇒ v1 behavior. |
| `requirements.txt` | (none — reuse `curl_cffi`) | No new dependency. |

### Phase 1 — `grounding.py`, standalone (1 day)
- New `src/protocol_to_data/grounding.py`, mirroring `ctg_validator.py`'s **never-raises** style.
  - `fetch_ae_grounding(drug_name, *, top_n=15) -> list[AEGrounding]` — GET OpenFDA
    `count` endpoint (`.../drug/event.json?search=patient.drug.medicinalproduct:{drug}&count=patient.reaction.reactionmeddrapt.exact`),
    **5s timeout**, parse top-15 `{term, count}`, `[]` on any error/empty.
  - `_drug_query_names(design) -> list[str]` — the **3-step cascade** (decision #5), placebo skipped.
- **Tests (offline, mock HTTP):** parsing · empty-on-error · timeout · placebo-skip. No live OpenFDA in CI.
- Integration: **none yet** — pure, decoupled module.

### Phase 2 — Wire into `loop.py` at design time (½ day)
- In `run_loop`, **after `extract_design` (loop.py:48), before generation (loop.py:57)**: if
  `ground_ae` → derive drug names → `fetch_ae_grounding` → set `design.grounded_ae`.
  Narrate `🌐 Grounded N AE terms from OpenFDA (<drug>)`.
- **Provenance is automatic:** `RunManifest.design` already embeds the design (schemas.py:113) →
  grounded terms land in `run_manifest.json`. No manifest change.
- **Fallback:** empty fetch ⇒ `grounded_ae` stays `[]` ⇒ generator uses the v1 path.
- 🚫 Fetch lives **here, never in `generate.py`** — keeps the generator network-free.

### Phase 3 — Weighted sampling in `generate.py:_gen_ae` (1 day)
- `_gen_ae` (generate.py:462) gains **one branch**: `grounded_ae` non-empty →
  `rng.choices(terms, weights=counts, k=1)[0]`; else current `rng.choice(verbatims)`.
- **AETERM/AEDECOD:** strict PT mapping (decision #3). Fallback path keeps `code_term`.
- **Invariant preserved:** `rng.choices` is deterministic given `(seed, terms, weights)`, and those
  come from the design → **same `(design, seed)` → byte-identical output.** Onset-≥-RFSTDTC logic
  untouched (repair loop depends on it).
- **Tests:** grounded design → generate twice/same seed → identical · AETERM ∈ grounded set ·
  RNG-sequence assertion for weighting.

### Phase 4 — Surface, docs, suite (½ day)
- Finalize CLI/env flag (optional UI checkbox deferred to V2.1).
- Docs: README bullet (opt-in) · SPEC feature section · ARCHITECTURE (`grounding.py` row +
  "design-time; generator stays deterministic") · TEST_PLAN rows + bump count.

### Phase 5 — Verify & roll out (½ day)
- Live smoke: real drug (e.g. `docetaxel`) → sane terms; AE distribution reflects real frequencies.
- Reproducibility: `ptd generate design.json --seed 42` ×2 → identical.
- Guardrail: OpenFDA unreachable → graceful v1 fallback.
- CI + deploy with the flag **OFF** → live app unchanged until explicitly enabled.

---

## 🔎 Integration points (full surface to review)
1. `schemas.py` — `AEGrounding` submodel + optional `grounded_ae`.
2. `loop.py` — fetch call site (post-extract / pre-generate) + drug-name cascade.
3. `generate.py:_gen_ae` — the **only** generator change (`rng.choices` branch).
4. `cli.py` / env — opt-in flag threading.
5. `run_manifest.json` — provenance (automatic via design embedding).
6. `requirements.txt` — no change (reuse `curl_cffi`).

## ⏭️ Next-session kickoff
1. **Fable assessment first** — architectural & security review of v1.0.0 with `claude-fable-5`
   (findings may feed back into this sprint before we cut code).
2. Then **Phase 0 (Contracts & Flag)**. All five decisions above are locked; the only items still
   open are per-step parsing details inside the drug-name cascade (finalize during Phase 1).

_Related: `docs/SUBMISSION.md` (v1 scope), persistent memory `protocol-to-data-v2-openfda-grounding`._

---

## Backlog / other future tickets

- **Shared Protocol Extraction Library** — reuse a stored `ProtocolDesign` across users so a repeat
  protocol skips the LLM extraction ($0). Design doc: `docs/FUTURE_SHARED_EXTRACTION_LIBRARY.md`.
  **Governance-first** — it reopens the cross-user exposure that ephemeral compliance mode closed,
  so v1 must be public-only (registry-verified) + opt-in. Build P0–P1 first.
