# Self-host on ChetanNode → `protocol-to-data.chetanlab.com`

Deploy protocol-to-data on the **Ubuntu ThinkCentre** (`ai-server` / ChetanNode) behind the
existing **Cloudflare Zero Trust Tunnel**, alongside Open WebUI + Portainer.

## Architecture (as deployed here)
```
Internet ──HTTPS──▶ Cloudflare edge ──tunnel──▶ ThinkCentre cloudflared
                                                   └─▶ protocol-to-data container :7860
reasoning (extract / repair / detect) ─▶ Claude API (ANTHROPIC_API_KEY)
generation (SDTM synthetic data) ──────▶ deterministic Python, on the ThinkCentre CPU (no LLM)
```
> The Mac Mini's Ollama (`llama3.1:8b`) is **not** used — generation is deterministic Python, and
> the reasoning steps use Claude (chosen for extraction fidelity). No GPU / Ollama dependency.
> RAM: comfortable on the ThinkCentre; the 512 MB Render OOM does not apply here.

## Prerequisites (yours)
1. **SSH key authorized** on ChetanNode: `ssh-copy-id -p 2222 -i ~/.ssh/id_ed25519.pub chetankumart@192.168.1.172`
2. An **`ANTHROPIC_API_KEY`**.
3. Know your **tunnel management model** — locally-managed (`~/.cloudflared/config.yml`) or
   dashboard-managed (Cloudflare Zero Trust → Networks → Tunnels). Both are covered below.

## 1. Run the container on ChetanNode
```bash
ssh -p 2222 chetankumart@192.168.1.172
git clone https://github.com/chetankumart/protocol-to-data.git && cd protocol-to-data
printf 'ANTHROPIC_API_KEY=sk-ant-...\n' > .env          # runtime secret, never committed
docker compose up -d --build                            # builds + runs on 127.0.0.1:7860
curl -fsS http://localhost:7860/ >/dev/null && echo "app up on :7860"
docker compose ps                                       # STATUS should show (healthy)
```
`docker-compose.yml` already publishes `7860:7860`, loads `.env`, and `restart: unless-stopped`;
the image now ships a `HEALTHCHECK`.

## 2. Expose it via the Cloudflare Tunnel

**Option A — locally-managed tunnel (`config.yml`):** add an ingress rule *above* the catch-all:
```yaml
# ~/.cloudflared/config.yml  (on ChetanNode)
ingress:
  - hostname: protocol-to-data.chetanlab.com
    service: http://localhost:7860
  # … existing rules (open-webui, etc.) …
  - service: http_status:404          # keep this catch-all last
```
```bash
cloudflared tunnel route dns <your-tunnel-name> protocol-to-data.chetanlab.com   # creates the CNAME
sudo systemctl restart cloudflared                                               # reload ingress
```

**Option B — dashboard-managed tunnel (Cloudflare Zero Trust):**
Networks → Tunnels → *your tunnel* → **Public Hostnames → Add**:
`subdomain = protocol-to-data`, `domain = chetanlab.com`, `service = HTTP → localhost:7860`. Save.
(DNS + routing are handled automatically; no `config.yml` edit.)

## 3. Verify
```bash
dig +short protocol-to-data.chetanlab.com          # resolves to Cloudflare (proxied)
curl -fsSI https://protocol-to-data.chetanlab.com  # 200 from the edge
```
Open **https://protocol-to-data.chetanlab.com** — footer shows the build; run the bundled sample.

## Ops
- **Update:** `git pull && docker compose up -d --build`
- **Logs:** `docker compose logs -f` (or Portainer)
- **Secret rotation:** edit `.env` → `docker compose up -d`
- **Zero-downtime-ish:** Compose recreates the container; the tunnel reconnects automatically.
