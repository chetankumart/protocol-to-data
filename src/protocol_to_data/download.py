"""Download a remote protocol to a local temp file so the existing extractor can read it.

Backs the mobile-friendly "Ingest by URL" fallback. Fetches via curl_cffi (browser-TLS — works
where plain urllib is WAF-blocked), falling back to stdlib urllib. The **caller owns the returned
temp file's lifecycle** and must delete it (app.py does this in a finally block) so we never leak
disk on the free cloud instance.
"""
from __future__ import annotations

import contextlib
import os
import tempfile
import urllib.parse

_TIMEOUT = 30
_MAX_BYTES = 50 * 1024 * 1024  # 50 MB cap — protect the free instance from pathological downloads

_EXT_BY_CONTENT_TYPE = {
    "application/pdf": ".pdf",
    "text/html": ".html",
    "application/xhtml+xml": ".html",
    "text/plain": ".txt",
    "text/markdown": ".md",
}


def _guess_suffix(url: str, content_type: str) -> str:
    """Pick a temp-file extension so the extractor dispatches correctly (content-type, then URL)."""
    ct = (content_type or "").split(";")[0].strip().lower()
    if ct in _EXT_BY_CONTENT_TYPE:
        return _EXT_BY_CONTENT_TYPE[ct]
    path = urllib.parse.urlparse(url).path.lower()
    for ext in (".pdf", ".html", ".htm", ".txt", ".md"):
        if path.endswith(ext):
            return ".html" if ext == ".htm" else ext
    return ".pdf"  # sensible default; the ingest layer still sniffs the content


def _http_get_bytes(url: str) -> tuple[bytes, str]:
    """GET url → (body_bytes, content_type). Raises RuntimeError on any failure."""
    headers = {"Accept": "*/*"}
    try:
        from curl_cffi import requests as _cr  # browser-TLS transport
    except ImportError:
        _cr = None
    if _cr is not None:
        try:
            r = _cr.get(url, impersonate="chrome", timeout=_TIMEOUT, headers=headers)
        except Exception as e:  # noqa: BLE001 — any curl_cffi error is a fetch failure
            raise RuntimeError(f"could not fetch URL ({type(e).__name__})") from e
        if r.status_code != 200:
            raise RuntimeError(f"download failed: HTTP {r.status_code}")
        data = r.content
        if len(data) > _MAX_BYTES:
            raise RuntimeError("download too large (>50 MB)")
        return data, r.headers.get("content-type", "")

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
            data = resp.read(_MAX_BYTES + 1)
            if len(data) > _MAX_BYTES:
                raise RuntimeError("download too large (>50 MB)")
            return data, resp.headers.get("content-type", "")
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"download failed: HTTP {e.code}") from e
    except Exception as e:  # noqa: BLE001 — URLError/timeout/SSL → fetch failure
        raise RuntimeError(f"could not fetch URL ({type(e).__name__})") from e


def download_from_url(url: str) -> str:
    """Fetch ``url`` into a secure temp file and return its absolute path.

    Raises ``ValueError`` for a malformed URL and ``RuntimeError`` on a fetch failure. The caller
    must delete the returned path when done (see the ``finally`` cleanup in ``app.py``).
    """
    url = (url or "").strip()
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise ValueError(f"Invalid URL (must be http/https): {url!r}")

    content, content_type = _http_get_bytes(url)
    fd, path = tempfile.mkstemp(prefix="ptd_url_", suffix=_guess_suffix(url, content_type))
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(content)
    except Exception:
        with contextlib.suppress(OSError):
            os.remove(path)
        raise
    return os.path.abspath(path)
