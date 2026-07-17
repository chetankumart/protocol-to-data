"""Stage 1 — INGEST: load a protocol file into normalized plain text.

Supports .txt/.md directly; .pdf via pdfplumber; .html via BeautifulSoup.
Deterministic, no Claude.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from . import sanitize


def sha256_of(path: str | Path) -> str:
    data = Path(path).read_bytes()
    return hashlib.sha256(data).hexdigest()


# The extractor only consumes the first ~120K chars (extract.py `_MAX_CHARS`), so we stop parsing
# a PDF once we have comfortably more than that. This bounds memory on constrained hosts (e.g. the
# Render 512MB free tier), where pdfplumber holding a whole 100+ page PDF is what triggers the OOM.
_PDF_TEXT_CAP = 160_000


def _pdf_text_bounded(pages, cap: int = _PDF_TEXT_CAP) -> str:
    """Accumulate page text up to ``cap`` chars, releasing each page's parse cache as we go.

    pdfplumber caches parsed objects per page; on a large PDF that accumulation is the memory
    spike. We flush each page and stop early once we have more than the extractor will use, so
    peak memory stays bounded regardless of the PDF's size.
    """
    parts: list[str] = []
    total = 0
    for page in pages:
        parts.append(page.extract_text() or "")
        total += len(parts[-1])
        flush = getattr(page, "flush_cache", None)  # release pdfplumber's per-page object cache
        if callable(flush):
            flush()
        if total >= cap:
            break
    return "\n\n".join(parts)


def load_protocol_text(path: str | Path) -> str:
    """Return normalized plain text for a protocol file.

    PRIVACY GUARDRAIL: this is the trust boundary before text reaches the LLM. When
    `PTD_SANITIZE_PHI=1`, the extracted text is routed through the PHI/PII sanitizer
    (`sanitize.py` — deterministic regex + optional Presidio NER) *before* it is sent to
    Claude. Off by default, since trial protocols are design docs and usually PHI-free.
    """
    path = Path(path)
    suffix = path.suffix.lower()

    if suffix in {".txt", ".md"}:
        text = path.read_text(encoding="utf-8", errors="ignore")
    elif suffix == ".pdf":
        try:
            import pdfplumber  # type: ignore
        except ImportError as e:  # pragma: no cover
            raise RuntimeError("pdfplumber required for PDF ingest: pip install pdfplumber") from e
        with pdfplumber.open(str(path)) as pdf:
            text = _pdf_text_bounded(pdf.pages)
    elif suffix in {".html", ".htm"}:
        try:
            from bs4 import BeautifulSoup  # type: ignore
        except ImportError as e:  # pragma: no cover
            raise RuntimeError("beautifulsoup4 required for HTML ingest: pip install beautifulsoup4") from e
        soup = BeautifulSoup(path.read_text(encoding="utf-8", errors="ignore"), "html.parser")
        text = soup.get_text("\n")
    else:
        raise ValueError(f"Unsupported protocol format: {suffix}")

    return sanitize.sanitize_text(text) if sanitize.enabled() else text
