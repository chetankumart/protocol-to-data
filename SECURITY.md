# Security Policy

Thanks for helping keep **protocol-to-data** and its users safe.

## Supported versions

This is an actively developed project; security fixes land on `main`. Always run the latest
`main` (or the most recent release). Older commits are not separately patched.

| Version | Supported |
|---------|-----------|
| `main` (latest) | ✅ |
| older commits / forks | ❌ |

## Reporting a vulnerability

**Please do not open a public GitHub Issue for security vulnerabilities.** Public disclosure
before a fix puts users at risk.

Instead, report privately via **either**:

1. **GitHub Private Vulnerability Reporting** (preferred) — go to the repo's **Security** tab →
   **Report a vulnerability**. This opens a private advisory visible only to maintainers.
2. **Email** — **chetankumart@gmail.com** with subject `SECURITY: protocol-to-data`.

Please include:

- A description of the issue and its impact.
- Steps to reproduce (a minimal proof-of-concept if possible).
- Affected commit / version and environment.
- Any suggested remediation.

**Response targets** (best-effort for a solo-maintained OSS project):

- Acknowledgement within **72 hours**.
- An initial assessment and severity within **7 days**.
- Coordinated disclosure once a fix is available — we'll credit you unless you prefer to remain
  anonymous.

## Scope & what to keep in mind

`protocol-to-data` generates **100% synthetic** clinical data and is designed to be PHI-free.
Security-relevant areas include:

- **API-key handling.** The `ANTHROPIC_API_KEY` is read from the environment / a host secret and
  must **never** be committed, logged, or baked into the Docker image. If you find a path that
  leaks or persists the key, report it.
- **Untrusted protocol input.** The app ingests user-supplied PDF/HTML/text. Report parsing paths
  that could enable code execution, SSRF, path traversal on write, or resource exhaustion (zip
  bombs, pathological PDFs).
- **PHI handling.** Although inputs are expected to be design documents, report any path where
  user-supplied text is persisted or transmitted in a way that would leak sensitive data —
  especially any bypass of the opt-in sanitizer (`PTD_SANITIZE_PHI`, see `sanitize.py`).
- **Dependency vulnerabilities.** If a pinned dependency has a known CVE that's exploitable in
  this project's usage, let us know (a PR bumping it, with the CVE cited, is welcome).

### Out of scope

- Findings that require committing your own real PHI or secrets to reproduce (don't do this —
  the tool is synthetic-only by design).
- Vulnerabilities in third-party hosting platforms (Hugging Face, Render, Databricks) themselves —
  report those to the respective vendor.
- Missing hardening that has no concrete exploit (report as a regular enhancement Issue instead).

## Handling secrets

If you accidentally commit a secret (e.g. an API key) to a fork or PR: **rotate it immediately**
in the [Anthropic console](https://console.anthropic.com/), then rewrite history to remove it.
Never paste real keys into Issues, PRs, or discussions.
