#!/usr/bin/env bash
# Run a command on ChetanNode using the passphrase-protected id_ed25519 key.
#
# The passphrase is read from the project .env (`SSH_KEY=...`, under "# Chetan Node") — never
# printed, never stored. A decrypted copy of the key is written to a private 600-mode temp file for
# the single SSH call and shredded on exit (the ssh-agent path is flaky on macOS). Usage:
#   bash deploy/chetanode-ssh.sh 'uname -a; free -h'
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="${PTD_ENV:-$REPO_ROOT/.env}"
KEY="$HOME/.ssh/id_ed25519"

PW="$(grep -E '^SSH_KEY=' "$ENV_FILE" | head -1 | cut -d= -f2- | sed -E 's/^"//; s/"$//')"
[ -n "$PW" ] || { echo "SSH_KEY not set under '# Chetan Node' in $ENV_FILE" >&2; exit 1; }

tmp="$(mktemp)"; chmod 600 "$tmp"
trap 'command -v shred >/dev/null && shred -u "$tmp" 2>/dev/null || rm -f "$tmp"' EXIT
cp "$KEY" "$tmp"
ssh-keygen -p -P "$PW" -N "" -f "$tmp" >/dev/null 2>&1   # decrypt the temp copy in place
unset PW

ssh -o BatchMode=yes -o IdentitiesOnly=yes -o ConnectTimeout=10 -i "$tmp" ChetanNode "$@"
