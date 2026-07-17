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

## Prerequisites
1. **SSH access.** ChetanNode is **key-only** (password auth disabled). The authorized key is
   `~/.ssh/id_ed25519`, which is **passphrase-protected**; the passphrase lives in this repo's
   `.env` as `SSH_KEY` (under `# Chetan Node`). Run remote commands via the helper
   **`deploy/chetanode-ssh.sh 'cmd'`** — it unlocks the key from `.env` in a scoped temp file and
   never prints it.
2. An **`ANTHROPIC_API_KEY`** (in `.env`).
3. The tunnel is **dashboard-managed** (a `cloudflared` container run with `--token`; no local
   `config.yml`), so the public hostname is added in the Cloudflare Zero Trust dashboard (§2 Option B).

## 1. Run the container on ChetanNode
Driven from your Mac (the helper reads the passphrase from `.env`):
```bash
# clone (or update) on the server
bash deploy/chetanode-ssh.sh 'cd ~ && git clone https://github.com/chetankumart/protocol-to-data.git \
  || (cd protocol-to-data && git fetch -q origin main && git reset --hard -q origin/main)'
# write a minimal server .env — ONLY the API key, piped over SSH, never printed
printf 'ANTHROPIC_API_KEY=%s\n' "$(grep -E '^ANTHROPIC_API_KEY=' .env | cut -d= -f2-)" \
  | bash deploy/chetanode-ssh.sh 'umask 077; cat > ~/protocol-to-data/.env'
# build + run on the HOST network (see below)
bash deploy/chetanode-ssh.sh 'cd ~/protocol-to-data &&
  docker compose -f docker-compose.yml -f docker-compose.chetanode.yml up -d --build'
# verify
bash deploy/chetanode-ssh.sh 'curl -fsS http://localhost:7860/ >/dev/null && echo up; \
  docker inspect --format "{{.State.Health.Status}}" protocol-to-data'
```
**Host networking is required.** The ThinkCentre's Docker *bridge* has no outbound route, so a
bridged container can't reach `api.anthropic.com` (`Network is unreachable`) — the host can.
`docker-compose.chetanode.yml` runs it on the **host network** (like open-webui / cloudflared),
which restores egress *and* lets the host-network tunnel reach `localhost:7860`.
`restart: unless-stopped` + a stdlib `HEALTHCHECK` are already set.

> Optional: `echo "GIT_COMMIT=$(bash deploy/chetanode-ssh.sh 'cd ~/protocol-to-data && git rev-parse --short HEAD')"`
> appended to the server `.env` makes the footer show the build SHA (verifiable deploys).

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
