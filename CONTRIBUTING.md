# Contributing to protocol-to-data

Thanks for your interest in improving **protocol-to-data**. This project favors a **small,
sharp, well-tested codebase** over breadth. To keep it that way, contributions follow a strict
policy. Please read this document in full **before** opening a Pull Request — PRs that ignore it
will be closed with a pointer back here.

By contributing, you agree your work is licensed under the repository's [MIT License](LICENSE).

---

## 1. The Fork & Pull model (required)

There is **no direct push access** to this repository, and none will be granted. Every change —
from a typo to a feature — goes through the same path:

1. **Fork** the repository to your own account.
2. **Branch from `main`** in your fork: `git checkout -b fix/short-description`.
3. Make your change (see the rules below).
4. **Open a Pull Request** against `main` of this repository.

The `main` branch is protected: it requires a passing PR and cannot be pushed to directly. Do not
ask for collaborator access — the fork-and-PR flow is the only supported route.

### Discuss before you build

For anything beyond a trivial fix (a bug fix touching one file, a doc correction), **open an
Issue first** and get agreement on the approach. Unsolicited large PRs are the #1 thing we close
unreviewed — an Issue costs you five minutes and saves you an afternoon of wasted work.

---

## 2. The "AI vibe coding" rule

AI coding assistants (including Claude — this project was itself built with Claude Code) are
**welcome**. Good engineers use good tools. But the bar for what lands in `main` is the same
whether a human or a model typed it, and **you are the author** — you are accountable for every
line you submit.

**PRs must be:**

- **Atomic** — one logical change per PR. One bug, one feature, one refactor. Not three.
- **Focused** — the diff touches only what the change requires. No drive-by reformatting,
  no renaming unrelated variables, no "while I was in here" edits.
- **Human-reviewed by you** — you have read, understood, and can explain and defend every line.
  If a reviewer asks "why is this here?" and the honest answer is "the AI added it," that's a
  close.
- **Explained** — the PR description says *what* changed, *why*, and how you verified it.

**These will be closed without review:**

- ❌ Massive multi-file AI-generated refactors or feature dumps with no prior Issue/discussion.
- ❌ PRs that regenerate, reformat, or "clean up" large swaths of the codebase.
- ❌ Sprawling diffs that mix unrelated changes.
- ❌ Generated code the author clearly hasn't read (dead code, hallucinated APIs, contradictory
  comments, tests that don't actually assert anything).
- ❌ Auto-generated dependency bumps or "AI suggestions" opened in bulk.

Quality and reviewability win. A 15-line PR you fully understand is worth more here than a
1,500-line one you generated and skimmed.

---

## 3. Mandatory CI checks

Both checks below **must pass locally before you open a PR**. GitHub Actions runs the exact same
two commands on every push and PR ([`.github/workflows/ci.yml`](.github/workflows/ci.yml)), and a
red check **blocks the merge** — there are no exceptions and no overrides for contributors.

```bash
pip install -r requirements.txt ruff pytest

ruff check .        # lint / code quality — must report: All checks passed!
pytest -q           # full offline suite — must report: <N> passed (no API key needed)
```

- The test suite is **fully offline** — all Claude API calls are mocked, so no `ANTHROPIC_API_KEY`
  is required to run it. There is no excuse for submitting with failing or skipped tests.
- **New behavior needs a test.** If you add or change functionality, add or update a test in
  `tests/` that would fail without your change. PRs that add logic but no coverage will be asked
  to add it before review.
- **Don't weaken tests to make them pass.** Deleting assertions or loosening a check to get green
  is an automatic close.
- Keep the diff `ruff`-clean; don't disable lint rules to sidestep a warning without justifying it
  in the PR.

---

## 4. Project conventions (quick reference)

- **Hybrid-AI boundary is sacred.** Claude does *reasoning* (extract, repair, detect); Python does
  *deterministic* generation and validation. `generate.py` has **zero LLM coupling** — keep it
  that way. Don't move data-row generation into a model call, and don't hardcode what should be
  extracted from the protocol.
- **Reproducibility.** Generation is seeded; the same `(protocol, seed, subjects)` must produce
  identical output. Don't introduce unseeded randomness.
- **Zero PHI.** Synthetic data only. Never add real patient data, keys, or protocol PDFs to the
  repo (see `.gitignore`).
- **Model routing.** Extraction/repair → `claude-opus-4-8`; cheap steps → `claude-haiku-4-5`.
  Read the architecture docs before touching `llm.py`.
- **Docs travel with code.** If your change alters behavior, update the relevant docs
  (`README.md`, `docs/ARCHITECTURE.md`, `docs/SPEC.md`, `docs/TEST_PLAN.md`) in the same PR.

Architecture: [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) ·
Spec: [`docs/SPEC.md`](docs/SPEC.md) ·
Test plan: [`docs/TEST_PLAN.md`](docs/TEST_PLAN.md).

---

## 5. Opening the PR

- Give it a clear, imperative title (`fix: drop orphan USUBJID before VISITNUM assert`).
- Link the Issue it resolves (`Closes #123`).
- Describe what changed, why, and how you verified it (commands run, output).
- Confirm in the description that **`ruff check .` and `pytest` pass locally**.
- Keep it small. If it's growing, split it.

Maintainers review on a best-effort basis. A tight, tested, well-described PR that follows this
guide gets reviewed fastest. Thank you for helping keep this project sharp.
