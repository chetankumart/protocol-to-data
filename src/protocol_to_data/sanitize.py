"""PHI / PII sanitization — scrub identifiers from protocol text before it reaches the LLM.

Trial protocols are design documents and are normally PHI-free, but this is the trust
boundary if real-world documents are ingested. Two tiers:

  1. **Deterministic regex** (always available, no dependency) — emails, phones, SSNs,
     MRN-style ids, and URLs.
  2. **Presidio NER** (optional: `pip install ".[phi]"`) — additionally redacts names,
     locations, and dates via Microsoft Presidio's recognizers.

Enabled per-run via env `PTD_SANITIZE_PHI=1` (default off, so demo output is unchanged and
protocol design terms aren't over-scrubbed). `load_protocol_text` calls `sanitize_text` when
enabled, before the text is sent to Claude.
"""

from __future__ import annotations

import os
import re

_PATTERNS = {
    "EMAIL": re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b"),
    "SSN": re.compile(r"\b\d{3}-\d{2}-\d{4}\b"),
    "MRN": re.compile(r"\bMRN[:\s#]*\d{5,}\b", re.IGNORECASE),
    "PHONE": re.compile(r"\b(?:\+?\d{1,2}[\s.-]?)?\(?\d{3}\)?[\s.-]?\d{3}[\s.-]?\d{4}\b"),
    "URL": re.compile(r"\bhttps?://\S+"),
}
# NER entities Presidio redacts when it is installed.
_PRESIDIO_ENTITIES = ["PERSON", "LOCATION", "DATE_TIME", "EMAIL_ADDRESS", "PHONE_NUMBER", "US_SSN"]


def enabled() -> bool:
    """True when PHI sanitization is switched on (env `PTD_SANITIZE_PHI` in 1/true/yes)."""
    return os.environ.get("PTD_SANITIZE_PHI", "").strip().lower() in ("1", "true", "yes")


def regex_scrub(text: str) -> tuple[str, int]:
    """Deterministic pattern-based redaction. Returns (scrubbed_text, num_redactions)."""
    total = 0
    for label, pattern in _PATTERNS.items():
        text, n = pattern.subn(f"[{label}_REDACTED]", text)
        total += n
    return text, total


def _presidio_scrub(text: str):
    """Presidio NER redaction if installed, else None (caller falls back to regex)."""
    try:
        from presidio_analyzer import AnalyzerEngine
        from presidio_anonymizer import AnonymizerEngine
    except ImportError:
        return None
    results = AnalyzerEngine().analyze(text=text, language="en", entities=_PRESIDIO_ENTITIES)
    return AnonymizerEngine().anonymize(text=text, analyzer_results=results).text


def sanitize_text(text: str) -> str:
    """Scrub PHI/PII from `text`. Uses Presidio (NER) when available, else deterministic regex.

    Regex always runs, so structured identifiers (emails/SSNs/MRNs) are caught even without
    Presidio; Presidio adds free-text names/locations/dates on top.
    """
    scrubbed = _presidio_scrub(text)
    if scrubbed is None:
        scrubbed = regex_scrub(text)[0]
    else:
        scrubbed = regex_scrub(scrubbed)[0]  # belt-and-suspenders on structured ids
    return scrubbed
