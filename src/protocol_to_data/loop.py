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

from .extract import design_from_prompt, extract_design, normalize_design
from .generate import BUILTIN_DOMAINS, generate_dataset
from .ingest import sha256_of
from .llm import MODEL_REASON
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
             narrate: Optional[Narrator] = None, use_cache: bool = True,
             ground_ae: bool = False) -> LoopResult:
    say = narrate or _default_narrator

    say("🧬  Reading protocol ...")
    proto_sha = sha256_of(protocol_path)

    say("🧩  Extracting design (Claude) ...")
    design = extract_design(protocol_path, model=model, narrate=say, use_cache=use_cache)
    if subjects:
        design.population.n_subjects = subjects
    say(f"    → {design.study_id}: {len(design.arms)} arms, {len(design.visits)} visits, "
        f"{len(design.endpoints)} endpoints, {len(design.domains)} domains")

    # Opt-in OpenFDA AE grounding — DESIGN TIME ONLY. The fetched real-world AE frequencies are
    # stored as data on the design (and thus in the manifest); the generator samples them
    # deterministically. Never blocks the loop — an empty result falls back to the built-in profile.
    if ground_ae:
        from .grounding import ground_design
        say("🌐  Grounding adverse events in OpenFDA (real-world frequencies) ...")
        design.grounded_ae = ground_design(design)
        if design.grounded_ae:
            top = design.grounded_ae[0]
            say(f"    → grounded {len(design.grounded_ae)} AE terms "
                f"(top: {top.term} ×{top.count})")
        else:
            say("    → no OpenFDA match; using the built-in AE profile")

    repair_attempts = 0
    while True:
        say("🏭  Generating synthetic data ...")
        out_dir = generate_dataset(design, subjects=subjects, seed=seed,
                                   out_root=out_root, backend=backend)
        # generate_dataset asserts referential + temporal integrity before it writes — if we
        # got here, that verify-before-write gate passed. Surface it for transparency.
        say("    🔗  Integrity verified — no orphan USUBJID / VISITNUM before write")

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
    """Ask Claude to adjust the design given validation failures, then regenerate.

    The most common real failure is a planned domain the builtin generator can't emit
    (e.g. EG/CM/MH extracted faithfully from a protocol). Claude remaps or drops it and
    records the change in `assumptions`. Uses structured output, so the repair is
    schema-valid; on any failure we keep the prior design rather than fake success.
    """
    prompt = f"""You are repairing a clinical trial synthetic-data design that failed validation.

Current design (JSON):
{design.model_dump_json(indent=2)}

Validation failures:
{json.dumps([f.model_dump() for f in report.findings], indent=2)}

The synthetic-data generator can only produce these SDTM domains: {sorted(BUILTIN_DOMAINS)}.
For any planned domain it cannot produce, either remap the relevant endpoints to a supported
domain or remove that domain — and note the change in `assumptions`. Also correct any
population (e.g. sex for sex-specific forms) or schema issues the failures indicate.
Return the FULL corrected ProtocolDesign."""
    try:
        repaired = normalize_design(design_from_prompt(prompt, model=model, narrate=say))
        say("    → design adjusted")
        return repaired
    except Exception as e:  # noqa: BLE001 — repair failed; surface the report, don't fake success
        say(f"    → repair failed ({e}); keeping prior design")
        return design
