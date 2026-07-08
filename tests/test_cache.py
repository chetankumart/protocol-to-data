"""Offline tests for the semantic (content-addressed) extraction cache.

The Claude call is mocked and counted so we can prove a cache hit skips it entirely.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from protocol_to_data import extract as extract_mod  # noqa: E402
from protocol_to_data.extract import extract_design  # noqa: E402


def _protocol(tmp_path, text="A Phase 3 HFrEF study of Drug-X.", name="protocol.md"):
    p = tmp_path / name
    p.write_text(text)
    return p


def _mock_extraction(monkeypatch, cache_dir, study="HF-CACHE"):
    """Point the cache at a temp dir and count Claude extraction calls."""
    monkeypatch.setattr(extract_mod, "_CACHE_DIR", cache_dir)
    calls = {"n": 0}

    def fake_complete_json(*a, **k):
        calls["n"] += 1
        return {"study_id": study, "phase": "3", "domains": [{"domain": "DM"}]}

    monkeypatch.setattr(extract_mod, "complete_json", fake_complete_json)
    return calls


def test_miss_then_hit_skips_api(tmp_path, monkeypatch):
    proto = _protocol(tmp_path)
    calls = _mock_extraction(monkeypatch, tmp_path / ".cache")

    d1 = extract_design(proto)                     # miss → extracts + caches
    assert d1.study_id == "HF-CACHE" and calls["n"] == 1
    cached = list((tmp_path / ".cache").glob("*_extracted_design.json"))
    assert len(cached) == 1                        # cache file written, hash-named

    d2 = extract_design(proto)                     # hit → API skipped
    assert d2.study_id == "HF-CACHE"
    assert calls["n"] == 1                          # no additional extraction call


def test_use_cache_false_forces_extraction(tmp_path, monkeypatch):
    proto = _protocol(tmp_path)
    calls = _mock_extraction(monkeypatch, tmp_path / ".cache")

    extract_design(proto)                           # miss → 1 call
    extract_design(proto, use_cache=False)          # forced → 2 calls (ignores cache)
    assert calls["n"] == 2


def test_different_documents_get_separate_entries(tmp_path, monkeypatch):
    calls = _mock_extraction(monkeypatch, tmp_path / ".cache")
    extract_design(_protocol(tmp_path, text="Study A oncology NSCLC.", name="a.md"))
    extract_design(_protocol(tmp_path, text="Study B heart failure.", name="b.md"))
    assert calls["n"] == 2                          # distinct hashes → both extracted
    assert len(list((tmp_path / ".cache").glob("*_extracted_design.json"))) == 2


def test_corrupt_cache_is_treated_as_miss(tmp_path, monkeypatch):
    proto = _protocol(tmp_path)
    cache_dir = tmp_path / ".cache"
    calls = _mock_extraction(monkeypatch, cache_dir)

    extract_design(proto)                           # writes a valid cache entry
    # corrupt it
    entry = next((cache_dir).glob("*_extracted_design.json"))
    entry.write_text("{ this is not valid json")
    extract_design(proto)                           # corrupt → miss → re-extracts
    assert calls["n"] == 2
