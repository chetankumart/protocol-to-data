"""Stage 7 — ANOMALY LOOP: inject controlled errors, then Claude detects & explains.

Injection is deterministic (seeded). Detection is Claude-driven and scored against the
ground-truth injections so the demo can show "N/N caught". Each injector introduces one
clearly-detectable, clinically-meaningful defect from the SPEC anomaly catalog.
"""

from __future__ import annotations

import random
from pathlib import Path

import pandas as pd

from .llm import MODEL_REASON, complete_json, parse_model
from .schemas import AnomalyFinding, AnomalyReport, ProtocolDesign

_PROMPT_PATH = Path(__file__).resolve().parents[2] / "prompts" / "detect_anomalies.md"


def inject_anomalies(data_dir: str | Path, *, count: int, seed: int) -> list[dict]:
    """Mutate the CSVs in-place with up to `count` known anomalies. Returns ground truth.

    An injector that has no target file (domain absent) is skipped, so the returned list
    may be shorter than `count` — the score is always against what was actually injected.
    """
    rng = random.Random(seed)
    data_dir = Path(data_dir)
    injected: list[dict] = []

    injectors = [_inject_predose_ae, _inject_oob_vital, _inject_orphan,
                 _inject_dup_visit, _inject_pregnancy_male]
    rng.shuffle(injectors)
    for fn in injectors[:count]:
        rec = fn(data_dir, rng)
        if rec:
            injected.append(rec)
    return injected


def _inject_predose_ae(data_dir: Path, rng) -> dict | None:
    """Temporal: an adverse event onset before first dose."""
    p = data_dir / "ae.csv"
    if not p.exists():
        return None
    df = pd.read_csv(p)
    if df.empty:
        return None
    df.loc[0, "AESTDTC"] = "2020-01-01"  # clearly before any dose
    df.to_csv(p, index=False)
    return {"type": "temporal", "domain": "AE", "usubjid": str(df.loc[0, "USUBJID"])}


def _inject_oob_vital(data_dir: Path, rng) -> dict | None:
    """Physiologic: an impossible systolic blood pressure."""
    p = data_dir / "vs.csv"
    if not p.exists():
        return None
    df = pd.read_csv(p)
    idx = df.index[df["VSTESTCD"] == "SYSBP"]
    if len(idx) == 0:
        return None
    df.loc[idx[0], "VSORRES"] = 400
    df.to_csv(p, index=False)
    return {"type": "physiologic", "domain": "VS", "usubjid": str(df.loc[idx[0], "USUBJID"])}


def _inject_orphan(data_dir: Path, rng) -> dict | None:
    """Referential: a child-domain record whose subject has no DM row (prefers LB)."""
    for name in ("lb.csv", "vs.csv"):
        p = data_dir / name
        if not p.exists():
            continue
        df = pd.read_csv(p)
        if df.empty:
            continue
        row = df.iloc[0].copy()
        row["USUBJID"] = "GHOST-9999"
        pd.concat([df, pd.DataFrame([row])], ignore_index=True).to_csv(p, index=False)
        return {"type": "referential", "domain": name[:2].upper(), "usubjid": "GHOST-9999"}
    return None


def _inject_dup_visit(data_dir: Path, rng) -> dict | None:
    """Uniqueness: a duplicated vital-signs record."""
    p = data_dir / "vs.csv"
    if not p.exists():
        return None
    df = pd.read_csv(p)
    if df.empty:
        return None
    pd.concat([df, df.iloc[[0]]], ignore_index=True).to_csv(p, index=False)
    return {"type": "uniqueness", "domain": "VS", "usubjid": str(df.iloc[0]["USUBJID"])}


def _inject_pregnancy_male(data_dir: Path, rng) -> dict | None:
    """Logical: a PREGNANCY adverse event recorded for a male subject.

    Uses a valid (on/after first-dose) onset date so the *only* defect is the logical one,
    not a temporal one — keeps the ground truth unambiguous.
    """
    ae_p, dm_p = data_dir / "ae.csv", data_dir / "dm.csv"
    if not ae_p.exists() or not dm_p.exists():
        return None
    dm = pd.read_csv(dm_p)
    males = dm[dm["SEX"] == "M"]["USUBJID"].tolist()
    uid = males[0] if males else str(dm["USUBJID"].iloc[0])
    onset = dm.loc[dm["USUBJID"] == uid, "RFSTDTC"].iloc[0]

    ae = pd.read_csv(ae_p)
    row = {c: "" for c in ae.columns}
    row.update({
        "STUDYID": dm["STUDYID"].iloc[0] if "STUDYID" in dm.columns else "",
        "USUBJID": uid,
        "AESEQ": (int(ae["AESEQ"].max()) + 1) if ("AESEQ" in ae.columns and not ae.empty) else 1,
        "AETERM": "PREGNANCY",
        "AEDECOD": "Pregnancy",  # MedDRA-coded even for the injected defect
        "AESTDTC": onset,
        "AESEV": "MODERATE",
    })
    pd.concat([ae, pd.DataFrame([row])], ignore_index=True).to_csv(ae_p, index=False)
    return {"type": "logical", "domain": "AE", "usubjid": str(uid)}


def detect_anomalies(design: ProtocolDesign, data_dir: str | Path, *,
                     model: str = MODEL_REASON, sample_rows: int = 25) -> list[AnomalyFinding]:
    """Claude reads dataset samples and returns anomaly findings (structured output)."""
    data_dir = Path(data_dir)
    samples = []
    for p in sorted(data_dir.glob("*.csv")):
        df = pd.read_csv(p)
        # Sample head AND tail: injected defects (orphans, dups, added rows) land at the end,
        # so a head-only sample would hide them from the detector.
        if len(df) <= 2 * sample_rows:
            sample = df
        else:
            sample = pd.concat([df.head(sample_rows), df.tail(sample_rows)])
        samples.append(f"### {p.stem.upper()} ({len(df)} rows)\n{sample.to_csv(index=False)}")
    template = _PROMPT_PATH.read_text(encoding="utf-8")
    prompt = (template
              .replace("{{DESIGN_JSON}}", design.model_dump_json(indent=2))
              .replace("{{DATASET_SAMPLES}}", "\n\n".join(samples)[:100_000]))

    try:
        return parse_model(prompt, AnomalyReport, model=model, max_tokens=4000).findings
    except Exception:  # noqa: BLE001 — structured path failed; fall back to JSON mode
        raw = complete_json(prompt, model=model, max_tokens=4000)
        return [AnomalyFinding.model_validate(f) for f in raw.get("findings", [])]


def scorecard_markdown(score: dict | None) -> str:
    """Render a scorecard dict as markdown (shared by the UI and run-history archive)."""
    if not score:
        return "_No anomaly loop run (set anomalies > 0)._"
    lines = [f"### 🎯 Claude caught **{score['caught']}/{score['total']}** injected anomalies"]
    if score["missed"]:
        lines.append("\n**Missed:**")
        lines += [f"- {t['type']} in {t['domain']} ({t.get('usubjid')})" for t in score["missed"]]
    if score["extra"]:
        lines.append("\n**Extra findings** (beyond the planted defects — Claude reasoning about the data):")
        lines += [f"- [{f.anomaly_type}] {f.domain}: {f.description}" for f in score["extra"]]
    return "\n".join(lines)


def score_detections(truth: list[dict], findings: list[AnomalyFinding]) -> dict:
    """Match Claude's findings to ground truth by (anomaly_type, domain). Returns a scorecard.

    Matching on type+domain (not USUBJID) is deliberate: the demo metric is whether Claude
    identified each planted defect, and a model may not echo the exact subject id.
    """
    remaining = list(findings)
    matched: list[dict] = []
    missed: list[dict] = []
    for t in truth:
        hit = next((f for f in remaining
                    if f.anomaly_type == t["type"] and f.domain.upper() == t["domain"].upper()),
                   None)
        if hit is not None:
            matched.append(t)
            remaining.remove(hit)
        else:
            missed.append(t)
    return {"caught": len(matched), "total": len(truth),
            "matched": matched, "missed": missed, "extra": remaining}
