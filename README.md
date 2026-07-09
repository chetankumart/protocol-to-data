# protocol-to-data

> **From a clinical trial protocol to an analyzable synthetic dataset — in one agentic loop, driven by Claude.**

**🔗 Live demo → [protocol-to-data.onrender.com](https://protocol-to-data.onrender.com)** &nbsp;·&nbsp; _free tier — first load takes ~30–60 s to wake, then it's instant._

A researcher, clinical data manager, or biotech engineer drops in a study protocol
(PDF / HTML / text). Claude reads it, extracts the trial design, and a deterministic engine
generates a **therapeutic-area-aware, dictionary-coded, referentially-sound SDTM dataset** —
validated, self-repaired on failure, and (optionally) stress-tested by a second agent that
injects and detects data-quality defects.

No real patient data. No manual schema wiring. Just: **protocol in → analyzable data out** —
as **Databricks-ready Parquet, before an EDC is ever stood up.**

Built for **[Built with Claude: Life Sciences](https://cerebralvalley.ai/e/built-with-claude-life-sciences)**
(Cerebral Valley × Anthropic × Gladstone Institutes, July 7–13, 2026) — **Build Track**.

---

## The magic moment

```
$ ptd run examples/sample_protocol.md --subjects 40 --seed 42 --anomalies 5

🧬  Reading protocol ...
🧩  Extracting design (Claude) ...       → CARDIO-HF-P3: 2 arms, 6 visits, 6 endpoints, 7 domains
🏭  Generating synthetic data ...
    🔗  Integrity verified — no orphan USUBJID / VISITNUM before write
🔎  Validating ...                       ⚠️  FAIL — planned domain EG has no generated data
🔧  Repairing (Claude, attempt 1/2) ...  → design adjusted
🔎  Validating ...                       ✅  PASS — 0 errors across 6 planned domains
🎯  Claude caught 5/5 injected anomalies
🪙  Run cost: $0.29 · 23,870 in / 6,458 out
```

Every step is narrated by Claude with its reasoning visible — the **self-repair** loop (Claude
reads its own validation failure and fixes the design) is what makes it an agent, not a pipeline.

---

## What's under the hood

Hybrid AI by design — **Claude reasons, deterministic Python generates**:

- 🧠 **Claude for reasoning only** — extraction, self-repair, and anomaly detection. It never
  writes a data row, so it can't hallucinate structural data. (`generate.py` has zero LLM coupling.)
- 🏭 **Therapeutic-area-aware generation** — a cardiology profile (NT-proBNP/KCCQ/NYHA) and an
  oncology/NSCLC profile (hematology/chem/coag/thyroid + PK, QLQ-C30/LC13 + EQ-5D-5L, arm-exact
  dosing, RECIST) selected deterministically from the protocol's indication.
- 🔤 **Dictionary-coded SDTM** — `AEDECOD` (MedDRA) and `CMDECOD` (WHODrug) via a deterministic
  `code_term` mapper ("bad headache" → "Headache", "lasix" → "Furosemide").
- 🔗 **Referential + temporal integrity** — orphan `USUBJID` dropped and asserted; `VISIT↔VISITNUM`
  asserted 1:1 across VS/LB/QS/RS — a verify-before-write gate.
- 🕵️ **Anomaly loop** — a second Claude agent finds and explains injected defects, scored N/N.
- ⚡ **Semantic caching** — SHA-256-keyed extraction cache; an identical protocol never pays for
  extraction twice ($0 on a cache hit).
- 🪙 **Cost observability** — live per-run token + `$` tracking in the UI and CLI.
- 🔌 **MCP server** — `mcp_server.py` exposes extract / generate / validate as Model Context
  Protocol tools for Claude Desktop or any MCP client (`pip install ".[mcp]"`).
- 🔒 **PHI/PII sanitization** — opt-in (`PTD_SANITIZE_PHI=1`): deterministic regex + optional
  Presidio NER scrub the text **before** it reaches the LLM.
- 🗂️ **Run history · RBAC-aware · EDC-target-aware · Dockerized · CI-guarded · cloud-deployed** —
  enterprise seams without over-building. Runs unchanged on any `$PORT`-driven host and is
  **live on Render's free tier**. See [`docs/SUBMISSION.md`](docs/SUBMISSION.md) and
  [`docs/DEPLOY.md`](docs/DEPLOY.md) for the full story.

Safe & shareable: 100% synthetic, no PHI, reproducible with `--seed`.

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

## Web UI

Prefer a browser? A thin Gradio front-end wraps the same loop:

```bash
python app.py           # then open http://127.0.0.1:7860
```

Upload a protocol (or use the bundled sample), set subjects/seed/anomalies, and watch the
extract → generate → validate → **repair** loop stream live, then browse the generated SDTM
CSVs and the anomaly scorecard. The UI reuses `run_loop` unchanged — it's presentation only.

![protocol-to-data web UI — the narrated loop shows Claude extracting the design, hitting a
validation failure (planned domain EG has no data) and self-repairing to PASS, with the live
🪙 run-cost badge, the Databricks-ready export format, and the generated AE table showing
MedDRA dictionary coding (AETERM "bad headache" → AEDECOD "Headache")](docs/img/ui_demo.png)

## 🚀 Quickstart (Docker)

Run the whole app — web UI included — with one command, no local Python setup:

```bash
cp .env.example .env      # then add your ANTHROPIC_API_KEY
docker compose up         # or:  podman-compose up
```

Then open **http://localhost:7860**. The image installs dependencies, runs as a non-root
user, and reads your API key from `.env` at runtime (it is never baked into the image). The
compose file is engine-agnostic, so Podman users can substitute `podman-compose up`. Rebuild
after code changes with `docker compose up --build`.

## System & deployment architecture

How the whole thing is wired — from a `git push` to the live public URL, and how a request
flows through the app at runtime:

```mermaid
flowchart TB
    dev["👩‍💻 Developer<br/>(Claude Code)"] -->|"git push · fork & PR"| repo

    subgraph GH["GitHub — source & CI/CD"]
        direction TB
        repo["📦 repo · main<br/>branch-protected · CODEOWNERS"]
        repo --> ci["⚙️ Actions CI<br/>Lint + Test (ruff · pytest)"]
        ci -->|"green + push to main"| deployjob["🚀 Deploy job<br/>POST deploy hook"]
    end

    deployjob -->|"RENDER_DEPLOY_HOOK (secret)"| RENDER

    subgraph RENDER["Render — cloud host (free tier)"]
        direction TB
        build["🐳 Build Docker image<br/>from Dockerfile · non-root"]
        build --> live["🖥️ Gradio app · app.py<br/>binds 0.0.0.0 : $PORT"]
        key["🔑 ANTHROPIC_API_KEY<br/>(Render secret)"] -.-> live
    end

    live --> url(["🌐 protocol-to-data.onrender.com"])
    judge["🧑‍🔬 User / Judge"] --> url

    url --> loop
    cli["⌨️ CLI · ptd"] --> loop
    mcp["🔌 MCP server"] --> loop

    subgraph APP["The agentic loop (run_loop)"]
        loop["🧩 extract → 🏭 generate → 🔎 validate<br/>→ 🔧 repair → 🎯 anomalies"]
    end

    loop -->|"reasoning: extract · repair · detect"| claude["✨ Claude API<br/>claude-opus-4-8"]:::claude
    loop --> out["📦 SDTM CSVs · report · manifest"]

    classDef claude fill:#5b3df5,stroke:#3a24b3,color:#ffffff;
```

- **CI/CD:** every push to `main` runs `Lint + Test`; **only a green build** triggers the deploy
  job, which POSTs a Render deploy hook — a failing build never ships. `main` is branch-protected
  (PR + passing CI required).
- **Cloud host:** Render builds the same non-root `Dockerfile` and runs the Gradio app, injecting
  `ANTHROPIC_API_KEY` as a secret (never in the image). The app honors Render's `$PORT`.
- **Runtime:** the UI, CLI, and MCP server all drive the identical `run_loop`; Claude does the
  reasoning (extract · repair · detect) while deterministic Python generates the SDTM data.

## Architecture (one loop)

```mermaid
flowchart TD
    A["📄 Protocol<br/>(PDF / HTML / text)"] --> B["Ingest → text"]
    B --> C["🧩 Extract<br/>ProtocolDesign (typed)"]:::claude
    C --> D["🏭 Generate<br/>SDTM CSVs (deterministic)"]
    D --> E{"🔎 Validate<br/>schema · referential + temporal<br/>integrity · clinical rules"}
    E -- pass --> F["✅ Emit dataset<br/>+ run manifest + report"]
    E -- fail --> G["🔧 Repair design<br/>(reads failures, adjusts)"]:::claude
    G -- regenerate --> D
    F --> H["🕵️ Inject controlled<br/>anomalies (seeded)"]
    H --> I["🎯 Detect + explain<br/>score N/N caught"]:::claude

    classDef claude fill:#5b3df5,stroke:#3a24b3,color:#ffffff;
```

> Purple = Claude-driven reasoning (extract · repair · detect); the rest is deterministic
> Python. The **repair edge** is what makes it an agent, not a pipeline.

Full design: [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) ·
Spec: [`docs/SPEC.md`](docs/SPEC.md) ·
Skill: [`.claude/skills/protocol-to-data/SKILL.md`](.claude/skills/protocol-to-data/SKILL.md)

## Status

✅ **Complete and demo-ready.** Extraction, generation (therapeutic-area-aware,
dictionary-coded, referentially-sound), self-repair, and anomaly detection all work
end-to-end, with a full offline test suite and CI. See
[`docs/SUBMISSION.md`](docs/SUBMISSION.md) and [`docs/BUILD_PLAN.md`](docs/BUILD_PLAN.md).

## 🤝 Contributing

PRs welcome — but this project runs a **strict, fork-and-PR contribution policy** to keep the
codebase small and sharp. **Please read [`CONTRIBUTING.md`](CONTRIBUTING.md) in full before
opening a Pull Request.** It's a hard requirement, not a suggestion — PRs that ignore it are
closed with a pointer back to it.

In short:

- **Fork & PR only.** No direct push access; branch from `main` in your fork and open a PR.
  Discuss anything non-trivial in an **Issue first**.
- **Atomic, human-reviewed changes.** AI assistants are welcome, but large unsolicited
  AI-generated refactors or feature dumps are closed without review. One logical change per PR,
  and you own every line.
- **Green CI is mandatory.** `ruff check .` and `pytest` must pass locally before you submit —
  [GitHub Actions](.github/workflows/ci.yml) blocks any failing PR.

```bash
pip install -r requirements.txt ruff pytest
ruff check .          # → All checks passed!
pytest -q             # → 88 passed  (offline; no API key needed)
```

See **[`CONTRIBUTING.md`](CONTRIBUTING.md)** for the full guidelines.

## License

MIT — see [`LICENSE`](LICENSE).
