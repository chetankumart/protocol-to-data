"""Stage 7 — ANOMALY LOOP: inject controlled *clinical-plausibility* defects, then Claude detects.

v2 pivot: this deliberately does NOT re-check schema/integrity errors (orphans, out-of-range
values, pre-dose dates, wrong-sex forms) — those are caught deterministically by `validate.py`, so
having an LLM re-find them was redundant. Instead the injectors plant defects that are **schema-
valid but pharmacologically implausible** (a severe drug-class AE on placebo, an all-severe
severity profile, a reversed dose-response) — things only clinical/pharmacological reasoning can
flag. Injection is deterministic (seeded); detection is Claude-driven and scored against the
ground-truth injections so the demo can still show "N/N caught".
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

    injectors = [_inject_placebo_severe_ae, _inject_severity_implausible,
                 _inject_dose_response_reversal]
    rng.shuffle(injectors)
    for fn in injectors[:count]:
        rec = fn(data_dir, rng)
        if rec:
            injected.append(rec)
    return injected


def _placebo_ids(dm: pd.DataFrame) -> pd.Series:
    return dm[dm["ARM"].astype(str).str.contains("placebo", case=False, na=False)]["USUBJID"]


def _inject_placebo_severe_ae(data_dir: Path, rng) -> dict | None:
    """Pharmacologic: a SEVERE, serious drug-class adverse event on a PLACEBO-arm subject.

    Schema-VALID by construction (real subject, on/after-dose onset, valid severity) — so
    deterministic validation PASSES. The defect is purely pharmacological: placebo shouldn't
    produce severe febrile neutropenia. Only Claude, reasoning about the assigned arm, can flag it.
    """
    ae_p, dm_p = data_dir / "ae.csv", data_dir / "dm.csv"
    if not ae_p.exists() or not dm_p.exists():
        return None
    dm = pd.read_csv(dm_p)
    placebo = _placebo_ids(dm)
    if placebo.empty:
        return None
    uid = str(placebo.iloc[0])
    onset = dm.loc[dm["USUBJID"] == uid, "RFSTDTC"].iloc[0]  # valid (== first dose), not pre-dose
    ae = pd.read_csv(ae_p)
    row = {c: "" for c in ae.columns}
    row.update({
        "STUDYID": dm["STUDYID"].iloc[0] if "STUDYID" in dm.columns else "",
        "USUBJID": uid,
        "AESEQ": (int(ae["AESEQ"].max()) + 1) if ("AESEQ" in ae.columns and not ae.empty) else 1,
        "AETERM": "Febrile neutropenia", "AEDECOD": "Febrile neutropenia",
        "AESTDTC": onset, "AESEV": "SEVERE",
    })
    pd.concat([ae, pd.DataFrame([row])], ignore_index=True).to_csv(ae_p, index=False)
    return {"type": "pharmacologic", "domain": "AE", "usubjid": uid}


def _inject_severity_implausible(data_dir: Path, rng) -> dict | None:
    """Severity: escalate ALL of one subject's adverse events to SEVERE — an implausible severity
    distribution (real trials skew mild/moderate). Schema-valid AESEV values; validation passes."""
    p = data_dir / "ae.csv"
    if not p.exists():
        return None
    ae = pd.read_csv(p)
    if ae.empty or not {"AESEV", "USUBJID"}.issubset(ae.columns):
        return None
    uid = str(ae["USUBJID"].iloc[0])
    ae.loc[ae["USUBJID"] == uid, "AESEV"] = "SEVERE"
    ae.to_csv(p, index=False)
    return {"type": "severity", "domain": "AE", "usubjid": uid}


# drug-sensitive labs and the reversed (no-treatment-effect) value to plant, in preference order
_REVERSAL_MARKERS = [("NTPROBNP", 3000.0), ("NEUT", 8.5)]


def _inject_dose_response_reversal(data_dir: Path, rng) -> dict | None:
    """Dose-response: flatten an active-drug arm's drug-sensitive lab so it shows NO treatment
    effect (NT-proBNP stays high on an effective HF drug; neutrophils stay normal on a
    myelosuppressive agent). Values remain in physiologic range → validation passes; only
    pharmacological reasoning flags the missing dose-response."""
    lb_p, dm_p = data_dir / "lb.csv", data_dir / "dm.csv"
    if not lb_p.exists() or not dm_p.exists():
        return None
    lb, dm = pd.read_csv(lb_p), pd.read_csv(dm_p)
    if not {"LBTESTCD", "LBORRES", "USUBJID"}.issubset(lb.columns):
        return None
    drug = set(dm["USUBJID"]) - set(_placebo_ids(dm))
    codes = set(lb["LBTESTCD"])
    marker = next(((c, v) for c, v in _REVERSAL_MARKERS if c in codes), None)
    if marker is None or not drug:
        return None
    code, val = marker
    mask = (lb["LBTESTCD"] == code) & (lb["USUBJID"].isin(drug))
    if not mask.any():
        return None
    lb.loc[mask, "LBORRES"] = val
    lb.to_csv(lb_p, index=False)
    return {"type": "dose_response", "domain": "LB", "usubjid": str(lb.loc[mask, "USUBJID"].iloc[0])}


def detect_anomalies(design: ProtocolDesign, data_dir: str | Path, *,
                     model: str = MODEL_REASON, sample_rows: int = 25) -> list[AnomalyFinding]:
    """The Validation Engine reads dataset samples and returns anomaly findings (structured output)."""
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
    lines = [f"### 🎯 Validation Engine caught **{score['caught']}/{score['total']}** injected anomalies"]
    if score["missed"]:
        lines.append("\n**Missed:**")
        lines += [f"- {t['type']} in {t['domain']} ({t.get('usubjid')})" for t in score["missed"]]
    if score["extra"]:
        lines.append("\n**Extra findings** (beyond the planted defects — autonomous plausibility "
                     "review by the Validation Engine):")
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
