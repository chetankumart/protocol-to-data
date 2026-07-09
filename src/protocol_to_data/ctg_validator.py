"""Read-only ClinicalTrials.gov (CTG) v2 baseline fetcher for the Registry Cross-Check panel.

STRICTLY read-only / display-only. Nothing here feeds SDTM generation — it fetches a handful of
high-level ground-truth fields (phase, arm count, target enrollment) so the UI can show that the
Claude-extracted design agrees with the public registry: a "verify before trust" badge.

Transport note: ClinicalTrials.gov sits behind a WAF that fingerprints the TLS ClientHello and
blocks plain Python (`urllib`/`httpx`) with a 403 while allowing browsers/curl. We therefore fetch
with `curl_cffi` (impersonates a browser's TLS fingerprint), falling back to stdlib `urllib` if it
isn't installed. Never raises — failures come back as {"error": "..."} so the UI degrades to a
notice.
"""
from __future__ import annotations

import json

CTG_API = "https://clinicaltrials.gov/api/v2/studies/{nct_id}"
_TIMEOUT = 15


class _Unreachable(Exception):
    """Transport-level failure (network/TLS), as opposed to an HTTP status we can read."""


def _normalize_phase(phases) -> str:
    """CTG returns e.g. ['PHASE3'] or ['PHASE1', 'PHASE2'] → '3' / '1/2'. Empty → 'N/A'."""
    if not phases:
        return "N/A"
    parts = [str(p).replace("PHASE", "").replace("_", "/").strip() or "N/A" for p in phases]
    return "/".join(parts)


def _parse_baseline(data: dict) -> dict:
    """Pull just the three ground-truth fields from a CTG study payload."""
    ps = data.get("protocolSection", {})
    design = ps.get("designModule", {})
    arms = ps.get("armsInterventionsModule", {}).get("armGroups", [])
    return {
        "phase": _normalize_phase(design.get("phases")),
        "num_arms": len(arms),
        "enrollment": design.get("enrollmentInfo", {}).get("count"),
    }


def _get(url: str) -> tuple[int, dict | None]:
    """GET ``url`` → ``(status_code, json_or_None)``. Raises ``_Unreachable`` on transport failure.

    Prefers ``curl_cffi`` (browser TLS fingerprint — the CTG WAF blocks plain Python); falls back
    to stdlib ``urllib`` (+ ``certifi`` if present) so the module still imports without the extra.
    """
    headers = {"Accept": "application/json"}
    try:
        from curl_cffi import requests as _cr  # browser-TLS transport
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
        except Exception:  # noqa: BLE001 — certifi optional; default context is fine on Linux
            pass
        req = urllib.request.Request(url, headers={**headers, "User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=_TIMEOUT, context=ctx) as resp:  # noqa: S310
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return e.code, None
    except Exception as e:  # noqa: BLE001 — URLError/timeout/SSL → transport failure
        raise _Unreachable(type(e).__name__) from e


def fetch_ctg_baseline(nct_id: str) -> dict:
    """Fetch high-level ground truth for an NCT id from ClinicalTrials.gov v2.

    Returns ``{"nct_id", "phase", "num_arms", "enrollment"}`` on success, or ``{"error": "..."}``
    on a malformed id / 404 / blocked or unreachable API. Never raises.
    """
    nct = (nct_id or "").strip().upper()
    if not nct:
        return {"error": "No NCT ID provided."}
    if not (nct.startswith("NCT") and nct[3:].isdigit()):
        return {"error": f"'{nct}' is not a valid NCT id (expected NCT followed by digits)."}

    try:
        status, data = _get(CTG_API.format(nct_id=nct))
    except _Unreachable as e:
        return {"error": f"Could not reach ClinicalTrials.gov ({e})."}
    if status == 404:
        return {"error": f"{nct} not found on ClinicalTrials.gov (404)."}
    if status != 200 or not data:
        return {"error": f"ClinicalTrials.gov returned HTTP {status}."}
    return {"nct_id": nct, **_parse_baseline(data)}
