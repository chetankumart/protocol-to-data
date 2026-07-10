"""URL ingestion helper — download_from_url. Offline (transport mocked)."""
from __future__ import annotations

import os

import pytest

from protocol_to_data import download


def test_rejects_non_http_scheme():
    with pytest.raises(ValueError):
        download.download_from_url("ftp://host/file.pdf")
    with pytest.raises(ValueError):
        download.download_from_url("not a url")


def test_writes_tempfile_and_returns_abspath(monkeypatch):
    monkeypatch.setattr(download, "_http_get_bytes", lambda url: (b"%PDF-1.4 fake", "application/pdf"))
    path = download.download_from_url("https://host/protocol.pdf")
    try:
        assert os.path.isabs(path) and path.endswith(".pdf")
        with open(path, "rb") as fh:
            assert fh.read() == b"%PDF-1.4 fake"
    finally:
        os.remove(path)


def test_suffix_from_content_type_when_url_has_none(monkeypatch):
    monkeypatch.setattr(download, "_http_get_bytes",
                        lambda url: (b"<html></html>", "text/html; charset=utf-8"))
    path = download.download_from_url("https://host/no-extension")
    try:
        assert path.endswith(".html")
    finally:
        os.remove(path)


def test_guess_suffix():
    assert download._guess_suffix("https://x/a.PDF", "") == ".pdf"
    assert download._guess_suffix("https://x/a", "application/pdf") == ".pdf"
    assert download._guess_suffix("https://x/a.htm", "") == ".html"
    assert download._guess_suffix("https://x/unknown", "") == ".pdf"   # sensible default


def test_fetch_failure_raises_runtimeerror(monkeypatch):
    def boom(url):
        raise RuntimeError("download failed: HTTP 404")
    monkeypatch.setattr(download, "_http_get_bytes", boom)
    with pytest.raises(RuntimeError):
        download.download_from_url("https://host/missing.pdf")
