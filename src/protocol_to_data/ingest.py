"""Stage 1 — INGEST: load a protocol file into normalized plain text.

Supports .txt/.md directly; .pdf via pdfplumber; .html via BeautifulSoup.
Deterministic, no Claude.
"""

from __future__ import annotations

import hashlib
from pathlib import Path


def sha256_of(path: str | Path) -> str:
    data = Path(path).read_bytes()
    return hashlib.sha256(data).hexdigest()


def load_protocol_text(path: str | Path) -> str:
    """Return normalized plain text for a protocol file."""
    path = Path(path)
    suffix = path.suffix.lower()

    if suffix in {".txt", ".md"}:
        return path.read_text(encoding="utf-8", errors="ignore")

    if suffix == ".pdf":
        # TODO(hackathon, Day 2): pip install pdfplumber
        try:
            import pdfplumber  # type: ignore
        except ImportError as e:  # pragma: no cover
            raise RuntimeError("pdfplumber required for PDF ingest: pip install pdfplumber") from e
        pages = []
        with pdfplumber.open(str(path)) as pdf:
            for page in pdf.pages:
                pages.append(page.extract_text() or "")
        return "\n\n".join(pages)

    if suffix in {".html", ".htm"}:
        try:
            from bs4 import BeautifulSoup  # type: ignore
        except ImportError as e:  # pragma: no cover
            raise RuntimeError("beautifulsoup4 required for HTML ingest: pip install beautifulsoup4") from e
        soup = BeautifulSoup(path.read_text(encoding="utf-8", errors="ignore"), "html.parser")
        return soup.get_text("\n")

    raise ValueError(f"Unsupported protocol format: {suffix}")
