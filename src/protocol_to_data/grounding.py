"""OpenFDA adverse-event grounding (opt-in) — real-world AE frequencies as sampling weights.

DESIGN-TIME ONLY. This fetches, **once**, the most-reported adverse reactions for the study drug
from OpenFDA's FAERS ``count`` endpoint and returns them as ``AEGrounding`` (MedDRA PT + report
count). The result is captured **as data on the ProtocolDesign** (and thus in ``run_manifest.json``);
the deterministic generator later samples from it with ``rng.choices(terms, weights=counts)``. The
generator stays network-free and reproducible — the network result is a design-time input, exactly
like extraction.

Transport mirrors ``ctg_validator``: ``curl_cffi`` (browser-TLS) with a stdlib ``urllib`` fallback,
a **5s timeout**, and **never raises** — any failure (drug not found, OpenFDA down, zero results)
returns ``[]`` so generation degrades gracefully to the built-in AE dictionary.
"""
from __future__ import annotations

import json
import re
from urllib.parse import quote

from .schemas import AEGrounding, ProtocolDesign

OPENFDA_EVENT = "https://api.fda.gov/drug/event.json"
_TIMEOUT = 5                       # locked decision: strict 5s timeout
_DEFAULT_TOP_N = 15                # locked decision: top-15 reactions

# dose/route/frequency noise to strip when reducing an arm label to a drug name
_DOSE_RE = re.compile(r"\b\d[\d.,]*\s*(mg/m2|mg|mcg|g|ml|iu|units?|%)\b.*", re.IGNORECASE)
_ROUTE_RE = re.compile(r"\b(once|twice|daily|weekly|oral|iv|intravenous|q\d?w|qd|bid|po)\b.*",
                       re.IGNORECASE)


class _Unreachable(Exception):
    """Transport-level failure (network/TLS) — as opposed to an HTTP status we can read."""


def _clean_drug(label: str) -> str:
    """Reduce an arm label to a queryable drug name: 'Zephyrol 10 mg once daily' -> 'Zephyrol'."""
    s = _DOSE_RE.sub("", label or "")
    s = _ROUTE_RE.sub("", s)
    return s.replace("(", " ").replace(")", " ").strip(" ,;-")


def _drug_candidates(design: ProtocolDesign) -> list[str]:
    """3-step drug-name fallback cascade (locked decision), placebo arms skipped, order-deduped:

    (a) non-placebo ``arm.name`` → (b) drug token cleaned from ``arm.name`` / ``arm.description``
    → (c) the study ``indication`` as a last resort.
    """
    cands: list[str] = []
    for arm in design.arms:
        if getattr(arm, "is_placebo", False):
            continue
        if arm.name:
            cands.append(arm.name)                    # (a)
        for src in (arm.name, getattr(arm, "description", "")):
            tok = _clean_drug(src)                     # (b)
            if tok:
                cands.append(tok)
    if design.indication:
        cands.append(design.indication)               # (c)
    seen: set[str] = set()
    out: list[str] = []
    for c in cands:
        key = c.lower()
        if c and key not in seen:
            seen.add(key)
            out.append(c)
    return out


def _normalize_term(term: str) -> str:
    """OpenFDA reactionmeddrapt is UPPERCASE; render as a MedDRA-style PT ('Title case')."""
    return (term or "").strip().title()


def _get(url: str) -> tuple[int, dict | None]:
    """GET ``url`` -> ``(status, json_or_None)``. Raises ``_Unreachable`` on transport failure.

    Prefers ``curl_cffi``; falls back to stdlib ``urllib`` so the module imports without the extra.
    """
    headers = {"Accept": "application/json"}
    try:
        from curl_cffi import requests as _cr
    except ImportError:
        _cr = None
    if _cr is not None:
        try:
            r = _cr.get(url, impersonate="chrome", timeout=_TIMEOUT, headers=headers)
            return r.status_code, (r.json() if r.status_code == 200 else None)
        except Exception as e:  # noqa: BLE001 — any curl_cffi error is a transport failure
            raise _Unreachable(type(e).__name__) from e

    import ssl
    import urllib.error
    import urllib.request
    try:
        ctx = ssl.create_default_context()
        try:
            import certifi
            ctx = ssl.create_default_context(cafile=certifi.where())
        except Exception:  # noqa: BLE001 — certifi optional
            pass
        req = urllib.request.Request(url, headers={**headers, "User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=_TIMEOUT, context=ctx) as resp:  # noqa: S310
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return e.code, None                            # OpenFDA returns 404 when a search has 0 hits
    except Exception as e:  # noqa: BLE001 — URLError/timeout/SSL → transport failure
        raise _Unreachable(type(e).__name__) from e


def fetch_ae_grounding(drug_name: str, *, top_n: int = _DEFAULT_TOP_N) -> list[AEGrounding]:
    """Top-``top_n`` real-world adverse reactions for ``drug_name`` from OpenFDA. ``[]`` on any miss.

    Queries FAERS: ``count=patient.reaction.reactionmeddrapt.exact`` filtered by
    ``patient.drug.medicinalproduct``. Never raises.
    """
    drug = (drug_name or "").strip()
    if not drug:
        return []
    search = quote(f'patient.drug.medicinalproduct:"{drug}"', safe=":")
    url = f"{OPENFDA_EVENT}?search={search}&count=patient.reaction.reactionmeddrapt.exact"
    try:
        status, data = _get(url)
    except _Unreachable:
        return []
    if status != 200 or not data:
        return []
    out: list[AEGrounding] = []
    for row in (data.get("results") or [])[:top_n]:
        term = _normalize_term(row.get("term", ""))
        count = int(row.get("count", 0) or 0)
        if term and count > 0:
            out.append(AEGrounding(term=term, count=count))
    return out


def ground_design(design: ProtocolDesign, *, top_n: int = _DEFAULT_TOP_N) -> list[AEGrounding]:
    """Run the drug-name cascade until OpenFDA returns data; return the first non-empty result.

    Pure/read-only — the caller assigns the result to ``design.grounded_ae``. Never raises.
    """
    for drug in _drug_candidates(design):
        grounded = fetch_ae_grounding(drug, top_n=top_n)
        if grounded:
            return grounded
    return []
