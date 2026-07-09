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

### 1b. Hugging Face Space (needs HF PRO)

If you have (or take) **HF PRO**, deployment is fully scripted — the repo's deploy helper
creates the Gradio Space, uploads `app.py`/`cli.py`/`src/`/`requirements.txt`/sample, and
sets `ANTHROPIC_API_KEY` as a Space secret via the API. The Space's own `README.md` carries
the Gradio SDK header (`sdk: gradio`, `app_file: app.py`); `app.py` sees `SPACE_ID` and binds
`0.0.0.0:7860` automatically. Requires a **write-scoped** HF token in `.env` as `HF_TOKEN`.

> Cost note: the semantic cache lives on the host's ephemeral disk; a fresh rebuild clears it.
> The $200 API credits cover judge traffic comfortably (a full run ≈ $0.2–0.3).

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
