# Future feature — Shared Protocol Extraction Library

**Status:** design / planning only — **no code written.** Documented at the end of the
post-hackathon hardening session (2026-07-17) for a future implementer.

## Idea (as requested)

When a user uploads a protocol, the app runs the full LLM extraction from scratch every time.
Instead, **store the JSON extraction** (the `ProtocolDesign`) keyed by the document, together with
identifying metadata (study id, title, NCT, …). Then, if **any** user later submits the *same*
protocol, the app serves the stored extraction from a **shared library** instead of calling the
LLM — so repeat protocols cost **$0** in extraction tokens.

**Is it a good feature?** Yes — extraction is the single largest LLM cost in a run (a full
extraction is ~20–25k input / ~6k output tokens ≈ most of the ~$0.2–0.3/run). A shared cache turns
every repeat of a common public protocol (the bundled sample, well-known trials like CodeBreak-200,
anything a second user re-uploads) into a near-free run. **But** it has a governance/privacy catch
that must be designed for up front — see §2.

---

## 1. What already exists (this feature extends it)

There is already a **per-instance semantic cache** — `src/protocol_to_data/extract.py`:

- `extract_design()` keys the design by **SHA-256 of the document bytes** and writes
  `.cache/{sha}_extracted_design.json`. A hit **skips the LLM call entirely** (25 s → 0.4 s, $0).
- `use_cache=False` / `--no-cache` forces a fresh extraction.

So the "store the JSON and reuse it" mechanism is **built and working** — for a single instance's
own repeats. This feature is the promotion of that cache from **local & private** to **shared,
persistent, and browsable across users**. Most of the work is *not* the caching logic (it exists);
it's the **storage backend, the keying, the governance, and the invalidation**.

---

## 2. ⚠️ The catch: this reopens what ephemeral (compliance) mode just closed

In the same session this doc was written, we shipped **ephemeral (compliance) mode**
(`PTD_EPHEMERAL=1`, default-on for the hosted deployments — see `docs/DEPLOY.md` §4). It
deliberately **stores nothing protocol-derived on the server**: no `.cache`, no `runs/` archive,
and it hid the "Load a previous run" dropdown *specifically because it was a cross-session
exposure* — one user's uploaded-protocol run must not be visible to the next user.

A **shared extraction library is the opposite of that** by construction: it stores one user's
extracted design (study id, arms, endpoints, indication, assumptions) and serves it to other
users. An uploaded protocol may be a **confidential, unpublished trial design** (sponsor IP /
pre-registration). Sharing that across tenants would be a **data-leak / IP-disclosure risk**, not
just a cache.

**Therefore the library must be governance-first.** Do not cache-and-share arbitrary uploads. The
eligibility gate (which protocols are allowed into the shared library) is the core design
decision, not an afterthought. Options, roughly in order of safety:

1. **Public-only allowlist (recommended default).** Only admit protocols that are provably public:
   - the **bundled sample**, and
   - documents whose auto-detected **NCT id** (already extracted, `_detect_nct`) resolves on
     **ClinicalTrials.gov** *and* whose content matches the registered study — i.e. it's a
     published, registry-backed trial, not private IP.
   Everything else falls through to a normal (private, per-session) extraction.
2. **Explicit opt-in.** A checkbox — *"Contribute this extraction to the shared library"* —
   default **off**, with clear copy that it will be reused by others. Only opted-in docs are stored.
3. **Per-tenant library.** Share within an org/workspace but never across tenants. (Needs auth /
   tenancy, which the app doesn't have yet.)

A safe v1 is **(1) + (2)**: public registry-backed protocols, or an explicit opt-in, only.

---

## 3. Cache key — get this right or it serves stale/wrong data

Key the library entry on a **composite**, not just the byte hash:

```
library_key = hash( normalized_text  ||  extract_prompt_version  ||  model_id )
```

- **`normalized_text`** — hashing raw bytes (today's `sha256_of`) misses that the *same* public
  protocol arrives as different files (re-exported PDF, different whitespace, added cover page). A
  normalized-text hash (lowercased, whitespace-collapsed, header/footer-stripped) makes trivially
  different copies of the same document hit the same entry. Keep the raw-byte SHA too, as a fast
  exact-match tier.
- **`extract_prompt_version`** — **critical.** The extraction prompt changes (e.g. this session's
  `study_id`-verbatim fix in `prompts/extract_design.md`). A cached extraction from an old prompt
  must **not** be served after the prompt improves. Bump a version constant whenever
  `extract_design.md` changes; include it in the key.
- **`model_id`** — a design extracted by `claude-opus-4-8` shouldn't be silently served to a run
  that requested a different model. Include it (or at least the model family).

Add a **TTL / max-age** and a manual **invalidate** path so a bad entry can be evicted.

---

## 4. What to store (the "library" record)

Per entry — enough to reuse the extraction *and* to browse the library:

| Field | Source | Purpose |
|---|---|---|
| `library_key`, `raw_sha256` | computed | lookup |
| `design` (the `ProtocolDesign` JSON) | `extract_design` output | the payload reused instead of the LLM |
| `study_id`, `title`, `phase`, `therapeutic_area`, `indication` | `design` | human-readable library listing |
| `nct_id` + registry-verified flag | `_detect_nct` + CTG cross-check | eligibility + trust |
| `n_arms`, `n_visits`, `n_endpoints`, `domains` | `design` | at-a-glance metadata |
| `extract_prompt_version`, `model_id` | build/config | invalidation |
| `source` (`bundled` / `public-nct` / `opt-in`), `contributed_at`, `hit_count` | runtime | governance + analytics |

The filename the user mentioned can be derived deterministically, e.g.
`{study_id}__{raw_sha256[:12]}.json`, but the **canonical index** should be a small manifest/DB
(see §5), not the filesystem layout — filenames alone don't scale to "browse the library".

---

## 5. Storage backend

`.cache/` is a local dir on the instance's **ephemeral** disk (wiped on Render restart/redeploy),
so it can't be the shared store. Options:

- **Object storage** (S3 / R2 / GCS) — a `library/{library_key}.json` blob + a small index object
  (or a manifest file) listing entries. Cheapest, stateless-friendly, works across instances.
- **A tiny database** (SQLite on a mounted volume, or a managed KV/Postgres) — better for the
  browse/search UX and `hit_count` bookkeeping.

Note: on ChetanNode (self-hosted, persistent disk) a shared volume is trivial; on Render free tier
you need an **external** store (the local disk won't persist). The backend should be behind a small
interface (`get(key) / put(key, record) / list()`), so the store is swappable and testable.

---

## 6. Lookup flow (where it plugs in)

Extend `extract_design()` precedence — **local session cache → shared library → LLM**:

```
1. (existing) per-session/.cache exact hit?           → return it
2. shared library: raw_sha256 exact hit?              → return it (record hit_count++)
3. shared library: normalized_text hit (same prompt+model version)? → return it
4. miss → run the LLM extraction (as today)
5. if the doc is ELIGIBLE (public-NCT-verified or opt-in) → contribute to the library
```

The lookup should be fast and **fail-open**: a library outage or a miss must never block a run —
fall straight through to normal extraction (mirror the existing cache's best-effort behavior).
The "background" the user described is really *"check the library before spending tokens"*; it's a
pre-extraction lookup, not an async job.

**Interaction with ephemeral mode:** ephemeral disables the *private* `.cache` and `runs/`. The
shared library is a *separate*, governed store and can remain available even under ephemeral mode —
but **only for library-eligible (public) protocols**. A private upload under ephemeral mode still
extracts fresh and stores nothing. Keep the two systems explicitly separate.

---

## 7. UX

- On a library hit, narrate it honestly: *"Loaded a verified extraction from the shared library —
  no LLM extraction needed."* (white-labeled; consistent with the current narration).
- Optional **"📚 Protocol library"** browser (only lists eligible/public entries) — pick a known
  protocol and run it straight from the library. This is the "pick it from the library" the user
  described, and it doubles as a great demo surface.
- If opt-in contribution is offered, the copy must be unambiguous that the extraction will be
  reused by others.

---

## 8. Cost model (why it's worth it)

- Extraction ≈ the bulk of a run's LLM spend (~$0.2–0.3). A library hit makes extraction **$0**;
  only the anomaly-detection call (if enabled) remains.
- Highest ROI on **repeatedly-run public protocols**: the bundled sample, demo/QA runs, and any
  trial multiple users try. For a public demo, most traffic is the same handful of documents — so
  the hit rate (and savings) can be high.
- Storage cost is negligible (a `ProtocolDesign` is a few KB).

---

## 9. Rollout phases

1. **P0 — Contracts & key.** Define `library_key` (normalized-text + prompt-version + model),
   the record schema, and the store interface. Add `extract_prompt_version` to the codebase.
2. **P1 — Store + lookup (public-only).** Object-store backend; wire the §6 precedence; admit
   **only** the bundled sample + NCT-verified public protocols. Fail-open. Metrics: hit rate, $ saved.
3. **P2 — Opt-in contribution.** The checkbox + consent copy for non-registry docs.
4. **P3 — Library browser UI** (§7) + invalidation/TTL controls.

## 10. Open decisions (need a human call)

- **Eligibility policy** — public-only vs opt-in vs per-tenant? (Recommend public-only + opt-in for v1.)
- **Where does the shared store live** for the Render deployment (S3/R2 vs a managed DB)?
- **Governance** — who can evict entries; retention period; is any PHI/PII scrub (`sanitize.py`)
  required before an extraction is admitted?
- **Cross-deployment sharing** — one global library for both onrender + ChetanNode, or per-deploy?

---

### TL;DR for the next implementer
The caching mechanism already exists (`extract.py`); this feature is **(a)** a shared/persistent
store, **(b)** a smarter composite key (normalized text + prompt-version + model), and **(c)** an
**eligibility gate** so it never shares private/confidential protocol IP — reconciling it with the
ephemeral compliance mode shipped in the same session. Build P0–P1 public-only first; it captures
most of the cost savings at the lowest risk.
