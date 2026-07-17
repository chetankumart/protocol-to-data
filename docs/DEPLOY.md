# Deploy — public demo, MCP server, PHI sanitization

Ways to run beyond a local `python app.py`. The app is already deploy-ready: `app.py`
auto-binds `0.0.0.0` on Hugging Face Spaces / containers (via `SPACE_ID` / `GRADIO_SERVER_NAME`)
and honors a platform-assigned `$PORT` (Render / Railway / Fly / Cloud Run).

---

## 1. Public demo — judge-accessible URL

Gives you a public URL to put at the top of `docs/SUBMISSION.md` — no clone, no local key
required for a judge. Two paths; pick one.

### 1a. Render (free) — recommended

Hugging Face now requires a **PRO** subscription to host Gradio/Docker Spaces on the free
CPU tier (`402 Payment Required` on Space create). Render's free tier hosts the **same
Docker image** for $0 (it spins down when idle — expect a ~30 s cold start on the first hit,
which is fine for a demo). The repo ships a [`render.yaml`](../render.yaml) blueprint:

1. **render.com → New → Blueprint** → connect this GitHub repo. Render reads `render.yaml`
   and provisions a free Docker web service from the existing `Dockerfile`.
2. **Set the secret** → in the service's *Environment*, add `ANTHROPIC_API_KEY = sk-ant-…`
   (the blueprint marks it `sync: false`, so Render prompts for it; never committed).
3. Render builds the image and serves at `https://protocol-to-data-*.onrender.com`. The app
   binds `0.0.0.0` and listens on Render's `$PORT` automatically.
4. Paste the public URL into `docs/SUBMISSION.md` (top) and `docs/SOCIAL_POST.md`.

### 1c. CI-gated auto-deploy (GitHub Actions → Render) — recommended once live

By default Render redeploys on every push to `main` — **including red builds**. To deploy only
**green** commits, gate it behind CI: the `deploy` job in
[`.github/workflows/ci.yml`](../.github/workflows/ci.yml) runs **only after `Lint & Test` passes**
and **only on a push to `main`** (never on PRs), then POSTs a Render **deploy hook**.

One-time setup:

1. **Turn off Render's native auto-deploy** → Render service → *Settings → Build & Deploy →
   Auto-Deploy → **No*** (so CI is the only trigger; avoids double deploys).
2. **Create a deploy hook** → same *Settings* page → *Deploy Hook* → copy the secret URL
   (`https://api.render.com/deploy/srv-…?key=…`).
3. **Add it to GitHub** → repo *Settings → Secrets and variables → Actions → New repository
   secret* → name **`RENDER_DEPLOY_HOOK`**, value = the hook URL.

After that, every merge to `main` that passes lint + tests automatically ships to the live URL;
a failing build never reaches production. The job hard-fails with a clear message if the secret
is missing.

### 1b. Hugging Face Space (needs HF PRO)

If you have (or take) **HF PRO**, deployment is fully scripted — the repo's deploy helper
creates the Gradio Space, uploads `app.py`/`cli.py`/`src/`/`requirements.txt`/sample, and
sets `ANTHROPIC_API_KEY` as a Space secret via the API. The Space's own `README.md` carries
the Gradio SDK header (`sdk: gradio`, `app_file: app.py`); `app.py` sees `SPACE_ID` and binds
`0.0.0.0:7860` automatically. Requires a **write-scoped** HF token in `.env` as `HF_TOKEN`.

> Cost note: on the hosted deployments the extraction cache is disabled (ephemeral mode — see §4),
> so each run pays for a fresh extraction. The $200 API credits cover judge traffic comfortably
> (a full run ≈ $0.2–0.3).

---

## 2. Run as an MCP server (Anthropic ecosystem)

`mcp_server.py` exposes the loop as Model Context Protocol tools so **any MCP client**
(Claude Desktop, Claude Code) can call them:

- `extract_protocol_design(protocol_text)` — Claude → typed design (needs API key)
- `generate_sdtm_dataset(design_json, subjects, seed)` — deterministic SDTM generation (no key)
- `validate_sdtm_dataset(data_dir)` — schema + integrity + clinical checks (no key)

```bash
pip install ".[mcp]"
python mcp_server.py            # stdio transport
```

Register in **Claude Desktop** (`claude_desktop_config.json`), then ask Claude to "generate an
SDTM dataset from this design" and watch it call your tool:
```json
{
  "mcpServers": {
    "protocol-to-data": {
      "command": "python",
      "args": ["/absolute/path/to/protocol-to-data/mcp_server.py"],
      "env": { "ANTHROPIC_API_KEY": "sk-ant-..." }
    }
  }
}
```

---

## 3. PHI / PII sanitization (enterprise privacy)

Off by default (trial protocols are design docs, usually PHI-free). Turn it on to scrub
identifiers **before** any text reaches Claude:

```bash
export PTD_SANITIZE_PHI=1        # deterministic regex: emails, phones, SSNs, MRNs, URLs
pip install ".[phi]"            # optional: adds Presidio NER for names / locations / dates
```

With the `[phi]` extra installed, Microsoft Presidio's recognizers additionally redact
free-text PERSON / LOCATION / DATE_TIME entities; the regex tier always runs as a backstop.
See `src/protocol_to_data/sanitize.py`.

## 4. Ephemeral (compliance) mode

```bash
export PTD_EPHEMERAL=1     # store nothing protocol-derived on the server
```

**On by default for the hosted deployments** — the `Dockerfile` sets `PTD_EPHEMERAL=1`, so every
container run (Render + self-hosted) is ephemeral; a local `python app.py` leaves it unset and
keeps the convenient dev persistence (cache + `runs/` history). When on, a run:

- writes generated data to a **per-session OS-temp dir** (swept after ~3h), never under the app dir
- **disables the extraction cache** (`.cache`) — no protocol design metadata persists
- **skips the `runs/` history archive** and **hides the shared "Load a previous run" dropdown**
  (which would otherwise expose one user's uploaded-protocol run to the next visitor)

Only the session download ZIP survives. A public protocol the user uploads is processed as-is —
the guarantee is about server-side *retention*, not masking. See `app.py` `_ephemeral`.
