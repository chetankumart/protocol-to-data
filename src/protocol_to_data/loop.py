"""The agentic loop: ingest → extract → generate → validate → (repair) → emit.

Claude drives extraction and repair; deterministic code drives generation/validation.
This is the heart of the project — the repair edge is what makes it a Claude project,
not a pipeline.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

from .extract import extract_design
from .generate import generate_dataset
from .ingest import sha256_of
from .llm import MODEL_REASON, complete_json
from .schemas import ProtocolDesign, RunManifest, ValidationReport
from .validate import validate_dataset

Narrator = Callable[[str], None]


def _default_narrator(msg: str) -> None:
    print(msg)


@dataclass
class LoopResult:
    design: ProtocolDesign
    report: ValidationReport
    output_dir: Path
    repair_attempts: int
    manifest: RunManifest


def run_loop(protocol_path: str | Path, *, subjects: int, seed: int,
             out_root: str | Path = "data/output", backend: str = "builtin",
             max_repairs: int = 2, model: str = MODEL_REASON,
             narrate: Optional[Narrator] = None) -> LoopResult:
    say = narrate or _default_narrator

    say("🧬  Reading protocol ...")
    proto_sha = sha256_of(protocol_path)

    say("🧩  Extracting design (Claude) ...")
    design = extract_design(protocol_path, model=model, narrate=say)
    if subjects:
        design.population.n_subjects = subjects
    say(f"    → {design.study_id}: {len(design.arms)} arms, {len(design.visits)} visits, "
        f"{len(design.endpoints)} endpoints, {len(design.domains)} domains")

    repair_attempts = 0
    while True:
        say("🏭  Generating synthetic data ...")
        out_dir = generate_dataset(design, subjects=subjects, seed=seed,
                                   out_root=out_root, backend=backend)

        say("🔎  Validating ...")
        report = validate_dataset(design, out_dir)
        if report.passed:
            say(f"    ✅  PASS — 0 errors across {len(design.domain_names())} planned domains")
            break

        say(f"    ⚠️  FAIL — {report.error_count} issue(s): "
            + "; ".join(f.message for f in report.findings if f.severity == "high"))

        if repair_attempts >= max_repairs:
            say("    ⛔  Max repairs reached — surfacing report without faking success")
            break

        repair_attempts += 1
        say(f"🔧  Repairing (Claude, attempt {repair_attempts}/{max_repairs}) ...")
        design = _repair_design(design, report, model=model, say=say)

    manifest = RunManifest(
        study_id=design.study_id, protocol_path=str(protocol_path),
        protocol_sha256=proto_sha, seed=seed, subjects=subjects, backend=backend,
        model=model, design=design, validation_passed=report.passed,
        repair_attempts=repair_attempts,
    )
    manifest_path = Path(out_dir).parent / "run_manifest.json"
    manifest_path.write_text(manifest.model_dump_json(indent=2))
    (Path(out_dir).parent / "validation_report.json").write_text(report.model_dump_json(indent=2))

    return LoopResult(design=design, report=report, output_dir=Path(out_dir),
                      repair_attempts=repair_attempts, manifest=manifest)


def _repair_design(design: ProtocolDesign, report: ValidationReport, *,
                   model: str, say: Narrator) -> ProtocolDesign:
    """Ask Claude to adjust the design given validation failures.

    Note: the builtin generator maintains invariants (e.g. AE onset ≥ RFSTDTC), so real
    repairs will bite once generation grows richer (Day 3–4). The wiring lives here now.
    """
    prompt = f"""You are repairing a clinical trial synthetic-data design that failed validation.

Current design (JSON):
{design.model_dump_json(indent=2)}

Validation failures:
{json.dumps([f.model_dump() for f in report.findings], indent=2)}

Adjust the design to eliminate these failures (e.g. tighten visit windows, fix population
sex for sex-specific forms, correct domain plans). Return the FULL corrected ProtocolDesign
as JSON only — same schema, no prose."""
    raw = complete_json(prompt, model=model, max_tokens=6000)
    try:
        repaired = ProtocolDesign.model_validate(raw)
        say("    → design adjusted")
        return repaired
    except Exception as e:  # noqa: BLE001
        say(f"    → repair parse failed ({e}); keeping prior design")
        return design
