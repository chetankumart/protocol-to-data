#!/usr/bin/env python
"""protocol-to-data CLI (`ptd`).

    python cli.py run      <protocol> [--subjects N] [--seed S] [--backend ...] [--anomalies K]
    python cli.py extract  <protocol> [-o design.json]
    python cli.py generate <design.json> [--subjects N] [--seed S]
    python cli.py validate <output_dir>
    python cli.py anomalies <output_dir> --inject K [--seed S]
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))


def _load_dotenv() -> None:
    """Load KEY=VALUE lines from a local .env into os.environ (no external dep).

    Real environment variables take precedence; .env only fills in what's unset.
    """
    env_path = Path(__file__).resolve().parent / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip().strip("'\"")
        if key and key not in os.environ:
            os.environ[key] = value

from protocol_to_data.schemas import ProtocolDesign  # noqa: E402


def cmd_run(a: argparse.Namespace) -> int:
    from protocol_to_data.llm import reset_usage, usage_summary
    from protocol_to_data.loop import run_loop

    reset_usage()  # start this run's token/cost tally
    result = run_loop(a.protocol, subjects=a.subjects, seed=a.seed,
                      out_root=a.out_root, backend=a.backend, max_repairs=a.max_repairs,
                      use_cache=not a.no_cache, ground_ae=a.ground_ae)
    print(f"\n📁  Dataset → {result.output_dir}")
    print(f"    repairs: {result.repair_attempts} · validation passed: {result.report.passed}")

    score = _run_anomalies(result.design, result.output_dir, count=a.anomalies,
                           seed=a.seed) if a.anomalies else None
    _archive_run(result, a, score)
    u = usage_summary()
    print(f"🪙  Run cost: ${u['cost']:.2f} · {u['input_tokens']:,} in / {u['output_tokens']:,} out")
    return 0 if result.report.passed else 1


def _archive_run(result, a, score) -> None:
    """Snapshot a completed CLI run into runs/<timestamp>/ (best-effort)."""
    try:
        from protocol_to_data.anomalies import scorecard_markdown
        from protocol_to_data.history import save_run
        run_dir = save_run(result.design, result.output_dir, subjects=a.subjects, seed=a.seed,
                           scorecard_md=scorecard_markdown(score),
                           caught=(score["caught"] if score else None),
                           total=(score["total"] if score else None))
        print(f"💾  Saved run → runs/{run_dir.name}")
    except Exception:  # noqa: BLE001 — history is best-effort
        pass


def cmd_extract(a: argparse.Namespace) -> int:
    from protocol_to_data.extract import extract_design

    design = extract_design(a.protocol, narrate=print, use_cache=not a.no_cache)
    out = a.output or "design.json"
    Path(out).write_text(design.model_dump_json(indent=2))
    print(f"🧩  Design → {out}  ({design.study_id}: {len(design.domains)} domains)")
    return 0


def cmd_generate(a: argparse.Namespace) -> int:
    from protocol_to_data.generate import generate_dataset

    design = ProtocolDesign.model_validate_json(Path(a.design).read_text())
    out_dir = generate_dataset(design, subjects=a.subjects, seed=a.seed,
                               out_root=a.out_root, backend=a.backend)
    print(f"🏭  CSVs → {out_dir}")
    return 0


def cmd_validate(a: argparse.Namespace) -> int:
    from protocol_to_data.validate import validate_dataset

    # design is optional for standalone validation; use a minimal one if absent
    design_path = Path(a.output_dir).parent / "run_manifest.json"
    if design_path.exists():
        manifest = json.loads(design_path.read_text())
        design = ProtocolDesign.model_validate(manifest["design"])
    else:
        design = ProtocolDesign(study_id=Path(a.output_dir).parent.name)
    report = validate_dataset(design, a.output_dir)
    print(report.model_dump_json(indent=2))
    return 0 if report.passed else 1


def cmd_anomalies(a: argparse.Namespace) -> int:
    manifest_path = Path(a.output_dir).parent / "run_manifest.json"
    design = (ProtocolDesign.model_validate(json.loads(manifest_path.read_text())["design"])
              if manifest_path.exists()
              else ProtocolDesign(study_id=Path(a.output_dir).parent.name))
    _run_anomalies(design, Path(a.output_dir), count=a.inject, seed=a.seed)
    return 0


def _run_anomalies(design, data_dir, *, count: int, seed: int) -> dict:
    from protocol_to_data.anomalies import detect_anomalies, inject_anomalies, score_detections

    print(f"\n🕵️  Injecting {count} anomalies (seed {seed}) ...")
    truth = inject_anomalies(data_dir, count=count, seed=seed)
    for t in truth:
        print(f"    • injected {t['type']} in {t['domain']} ({t.get('usubjid')})")

    print("🔎  Claude detecting ...")
    findings = detect_anomalies(design, data_dir)
    for f in findings:
        print(f"    • [{f.anomaly_type}] {f.domain}: {f.description}")

    score = score_detections(truth, findings)
    print(f"\n🎯  Claude caught {score['caught']}/{score['total']} injected anomalies")
    for t in score["missed"]:
        print(f"    • MISSED {t['type']} in {t['domain']} ({t.get('usubjid')})")
    return score


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="ptd", description="protocol → analyzable synthetic data")
    sub = p.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("run", help="full loop")
    r.add_argument("protocol")
    r.add_argument("--subjects", type=int, default=20)
    r.add_argument("--seed", type=int, default=42)
    r.add_argument("--out-root", default="data/output")
    r.add_argument("--backend", choices=["builtin", "engine-bridge"], default="builtin")
    r.add_argument("--max-repairs", type=int, default=2)
    r.add_argument("--anomalies", type=int, default=0, help="inject+detect K anomalies after run")
    r.add_argument("--ground-ae", action="store_true",
                   help="ground adverse events in real-world OpenFDA frequencies (opt-in)")
    r.add_argument("--no-cache", action="store_true",
                   help="skip the extraction cache — force a fresh Claude call (e.g. live demos)")
    r.set_defaults(func=cmd_run)

    e = sub.add_parser("extract", help="protocol → design.json")
    e.add_argument("protocol")
    e.add_argument("-o", "--output")
    e.add_argument("--no-cache", action="store_true",
                   help="skip the extraction cache — force a fresh Claude call")
    e.set_defaults(func=cmd_extract)

    g = sub.add_parser("generate", help="design.json → CSVs")
    g.add_argument("design")
    g.add_argument("--subjects", type=int, default=20)
    g.add_argument("--seed", type=int, default=42)
    g.add_argument("--out-root", default="data/output")
    g.add_argument("--backend", choices=["builtin", "engine-bridge"], default="builtin")
    g.set_defaults(func=cmd_generate)

    v = sub.add_parser("validate", help="validate a dataset dir")
    v.add_argument("output_dir")
    v.set_defaults(func=cmd_validate)

    an = sub.add_parser("anomalies", help="inject + detect anomalies")
    an.add_argument("output_dir")
    an.add_argument("--inject", type=int, default=5)
    an.add_argument("--seed", type=int, default=42)
    an.set_defaults(func=cmd_anomalies)
    return p


def main() -> int:
    _load_dotenv()
    args = build_parser().parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
