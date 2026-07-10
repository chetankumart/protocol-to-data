"""Data Copilot — DuckDB-on-disk query engine + NL answer. LLM mocked; DuckDB runs for real."""
from __future__ import annotations

from protocol_to_data import copilot


def _dm(tmp_path):
    (tmp_path / "dm.csv").write_text("USUBJID,ARM\nS-1,A\nS-2,A\nS-3,B\n")
    return str(tmp_path)


def test_requires_data_when_no_output_dir():
    assert "generate a dataset first" in copilot.answer("hi", "").lower()


def test_requires_data_when_dir_has_no_csvs(tmp_path):
    (tmp_path / "notes.txt").write_text("nothing here")
    assert "generate a dataset first" in copilot.answer("hi", str(tmp_path)).lower()


def test_empty_query_prompts_user(tmp_path):
    assert "Ask me something" in copilot.answer("   ", _dm(tmp_path))


def test_end_to_end_two_llm_calls(tmp_path, monkeypatch):
    calls = []

    def fake_complete(prompt, *, model=None, max_tokens=4096, system=None):
        calls.append(system or "")
        if "DuckDB SQL" in (system or ""):
            return "```sql\nSELECT ARM, COUNT(*) AS n FROM dm GROUP BY ARM ORDER BY ARM;\n```"
        return "Arm A has 2 subjects and arm B has 1."

    monkeypatch.setattr(copilot.llm, "complete", fake_complete)
    out = copilot.answer("How many subjects per arm?", _dm(tmp_path))
    assert "Arm A has 2" in out
    assert len(calls) == 2  # NL→SQL, then result→answer


def test_bad_sql_is_surfaced_not_raised(tmp_path, monkeypatch):
    monkeypatch.setattr(copilot.llm, "complete",
                        lambda p, *, model=None, max_tokens=4096, system=None: "SELECT * FROM ghost_table")
    out = copilot.answer("anything", _dm(tmp_path))
    assert "couldn't run that query" in out.lower()


def test_connect_pins_memory_limit(tmp_path):
    tables = copilot._domain_tables(_dm(tmp_path))
    con = copilot._connect(tables)
    try:
        val = con.execute("SELECT current_setting('memory_limit')").fetchone()[0]
        num, unit = str(val).split()  # e.g. "244.1 MiB" (DuckDB shows 256 MB as MiB)
        assert unit == "MiB" and float(num) <= 256  # capped, not DuckDB's RAM-derived default
        # the view queries from disk and returns the rows
        assert con.execute("SELECT COUNT(*) FROM dm").fetchone()[0] == 3
    finally:
        con.close()


def test_sql_only_strips_fences_and_semicolons():
    assert copilot._sql_only("```sql\nSELECT 1;\n```") == "SELECT 1"
    assert copilot._sql_only("SELECT 1") == "SELECT 1"
