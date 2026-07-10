"""Data Copilot — DuckDB engine + NL answer + demo guardrails. LLM mocked; DuckDB runs for real."""
from __future__ import annotations

import sys
from pathlib import Path

from protocol_to_data import copilot

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import app  # noqa: E402  — repo-root module (copilot_respond wrapper lives here)


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


def test_bad_sql_returns_demo_guardrail(tmp_path, monkeypatch):
    monkeypatch.setattr(copilot.llm, "complete",
                        lambda p, *, model=None, max_tokens=4096, system=None: "SELECT * FROM ghost_table")
    out = copilot.answer("anything", _dm(tmp_path))
    assert "Demo Guardrail" in out and "safe query" in out


# ---- demo guardrails on the ChatInterface wrapper (app.copilot_respond) ------------------

def test_length_guardrail_blocks_before_llm(monkeypatch):
    def must_not_run(*a, **k):
        raise AssertionError("copilot.answer must not run when over the 150-char limit")
    monkeypatch.setattr(app.copilot, "answer", must_not_run)
    out = app.copilot_respond("x" * 200, [], "/some/dir")
    assert "Demo Guardrail" in out and "150 characters" in out


def test_turn_limit_guardrail_blocks_fourth_query(monkeypatch):
    def must_not_run(*a, **k):
        raise AssertionError("copilot.answer must not run at the turn limit")
    monkeypatch.setattr(app.copilot, "answer", must_not_run)
    history = [{"role": "user", "content": "q1"}, {"role": "assistant", "content": "a1"},
               {"role": "user", "content": "q2"}, {"role": "assistant", "content": "a2"},
               {"role": "user", "content": "q3"}, {"role": "assistant", "content": "a3"}]
    out = app.copilot_respond("q4", history, "/some/dir")
    assert "Demo Limit Reached" in out


def test_third_query_within_limits_is_allowed(monkeypatch):
    monkeypatch.setattr(app.copilot, "answer", lambda msg, od: "OK-ANSWER")
    history = [{"role": "user", "content": "q1"}, {"role": "assistant", "content": "a1"},
               {"role": "user", "content": "q2"}, {"role": "assistant", "content": "a2"}]
    assert app.copilot_respond("How many subjects?", history, "/dir") == "OK-ANSWER"


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


# ---- chart generation (wired into the Copilot) ------------------------------------------

def test_wants_chart_detection():
    assert copilot._wants_chart("show a bar chart of arms") == "bar"
    assert copilot._wants_chart("pie chart of sex") == "pie"
    assert copilot._wants_chart("scatter plot of age vs score") == "scatter"
    assert copilot._wants_chart("line chart of the trend") == "line"
    assert copilot._wants_chart("how many subjects per arm?") is None      # no chart intent
    assert copilot._wants_chart("baseline characteristics table") is None  # 'line' in 'baseline'


def test_build_chart_returns_figure_or_none():
    import plotly.graph_objects as go
    fig = copilot._build_chart("bar", ["ARM", "n"], [("A", 20), ("B", 20)], "subjects per arm")
    assert isinstance(fig, go.Figure)
    assert copilot._build_chart("bar", [], [], "x") is None  # empty result → not chartable


def test_answer_returns_figure_for_chart_query(tmp_path, monkeypatch):
    import plotly.graph_objects as go
    calls = []

    def fake_complete(p, *, model=None, max_tokens=4096, system=None):
        calls.append(1)
        return "SELECT ARM, COUNT(*) AS n FROM dm GROUP BY ARM"
    monkeypatch.setattr(copilot.llm, "complete", fake_complete)
    result = copilot.answer("show a bar chart of subjects per arm", _dm(tmp_path))
    assert isinstance(result, go.Figure)
    assert len(calls) == 1  # chart path skips the text-answer LLM call


def test_copilot_respond_wraps_figure_in_gr_plot(monkeypatch):
    import gradio as gr
    import plotly.graph_objects as go
    monkeypatch.setattr(app.copilot, "answer", lambda msg, od: go.Figure())
    out = app.copilot_respond("bar chart please", [], "/dir")
    assert isinstance(out, gr.Plot)
