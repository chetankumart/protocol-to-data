# Deploy — public demo, MCP server, PHI sanitization

Three ways to run beyond a local `python app.py`. The app is already deploy-ready
(`app.py` auto-binds `0.0.0.0` on Hugging Face Spaces / containers via `SPACE_ID` / env).

---

## 1. Public demo on Hugging Face Spaces (judge-accessible URL)

Gives you a public URL (e.g. `https://huggingface.co/spaces/<you>/protocol-to-data`) to put
at the top of `docs/SUBMISSION.md` — no clone, no local key required for a judge.

1. **Create the Space** → huggingface.co/new-space → SDK **Gradio**, hardware **CPU basic** (free).
2. **Add the code.** Easiest: in the Space's *Files* tab, upload the repo (or `git push` this
   repo to the Space remote). Ensure `app.py`, `requirements.txt`, and `src/` are present.
3. **Point the Space at `app.py`.** In the Space's own `README.md`, put this header (this is
   the Space config — separate from the project README):
   ```yaml
   ---
   title: protocol-to-data
   emoji: 🧬
   colorFrom: indigo
   colorTo: purple
   sdk: gradio
   app_file: app.py
   pinned: false
   ---
   ```
4. **Add your key as a secret** → Space *Settings → Variables and secrets → New secret*:
   `ANTHROPIC_API_KEY = sk-ant-…`. (Never commit it.) The app reads it at runtime.
5. The Space builds and serves. `app.py` sees `SPACE_ID` and binds `0.0.0.0:7860` automatically.
6. Paste the public URL into `docs/SUBMISSION.md` (top) and `docs/SOCIAL_POST.md`.

> Cost note: the semantic cache lives in the Space's ephemeral disk; a fresh Space rebuild
> clears it. The $200 API credits cover judge traffic comfortably (a full run ≈ $0.2–0.3).

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
