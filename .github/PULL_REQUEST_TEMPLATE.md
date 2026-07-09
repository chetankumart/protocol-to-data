<!--
Read CONTRIBUTING.md before opening this PR. PRs that ignore it are closed with a pointer back.
Keep this ATOMIC: one logical change. Large unsolicited AI-generated refactors are closed unreviewed.
-->

## What & why

<!-- What does this change, and why? Keep it to one logical change. -->

Closes #<!-- issue number — non-trivial changes must have a prior agreed issue -->

## How I verified

```bash
ruff check .        # → All checks passed!
pytest -q           # → N passed  (offline; no API key needed)
```

<!-- Paste anything else you ran (a live `ptd run`, the UI, Docker) and its outcome. -->

## Checklist

- [ ] This PR is **atomic** — one logical change, no drive-by or unrelated edits.
- [ ] I linked an **Issue**, and for non-trivial changes the approach was **agreed there first**.
- [ ] `ruff check .` passes locally.
- [ ] `pytest -q` passes locally (offline suite, no API key).
- [ ] I **added/updated tests** for any changed behavior.
- [ ] I updated relevant **docs** (README / ARCHITECTURE / SPEC / TEST_PLAN) if behavior changed.
- [ ] I have **read and understood every line** and can explain it (AI-assisted is fine — I'm the author).
- [ ] No real patient data (PHI), keys, or protocol PDFs are included.
- [ ] I respected the **hybrid-AI boundary** (Claude reasons; `generate.py` stays deterministic / LLM-free).
