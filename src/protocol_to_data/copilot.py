"""Clinical Data Copilot — chat over the generated SDTM datasets, memory-safely via DuckDB.

Queries the generated per-domain CSVs directly from disk with DuckDB (columnar, streaming) — it
NEVER loads full files into pandas — so it stays well within the 512MB cloud instance. Flow:
NL question + schema → DuckDB SQL (one LLM call) → execute on disk → result snippet → concise
human answer (second LLM call). generate.py/loop.py/extract.py are untouched.
"""
from __future__ import annotations

import re
from pathlib import Path

from . import llm

# Hard cap so DuckDB can't misdetect a constrained container's RAM and over-allocate.
_MEMORY_LIMIT = "256MB"
_THREADS = 2
_RESULT_ROW_CAP = 50  # bound the result snippet handed back to the LLM

_SQL_SYSTEM = (
    "You are a clinical data copilot. Write a single valid DuckDB SQL query to answer the user's "
    "question using the provided table schemas (SDTM domains). Return ONLY the SQL string — no "
    "prose, no markdown fences, no explanation. Use only the listed tables and columns."
)
_ANSWER_SYSTEM = "You are a clinical data copilot. Answer concisely and accurately."

_NEED_DATA_MSG = (
    "Please generate a dataset first — run a protocol in the **⚙️ Pipeline** tab, then come back "
    "to chat with the results."
)


def _domain_tables(output_dir: str) -> list[tuple[str, Path]]:
    """(table_name, csv_path) per generated domain CSV. No data is read here."""
    return [(p.stem.lower(), p) for p in sorted(Path(output_dir).glob("*.csv"))]


def _connect(tables: list[tuple[str, Path]]):
    """DuckDB connection with a hard memory cap + one VIEW per domain CSV (streamed from disk)."""
    import duckdb
    con = duckdb.connect(database=":memory:")
    con.execute(f"SET memory_limit='{_MEMORY_LIMIT}'")
    con.execute(f"SET threads={_THREADS}")
    for name, path in tables:
        safe = str(path).replace("'", "''")
        # A VIEW does NOT load the CSV — rows are read from disk only when the view is queried.
        con.execute(
            f'CREATE OR REPLACE VIEW "{name}" AS '
            f"SELECT * FROM read_csv_auto('{safe}', header=true)"
        )
    return con


def _schema_text(con, tables) -> str:
    """Schema string (table + typed columns) via DESCRIBE — metadata only, no rows read."""
    parts = []
    for name, _ in tables:
        cols = con.execute(f'DESCRIBE "{name}"').fetchall()  # (name, type, ...)
        parts.append(f"- {name}(" + ", ".join(f"{c[0]} {c[1]}" for c in cols) + ")")
    return "\n".join(parts)


def _sql_only(text: str) -> str:
    """Strip markdown fences / trailing semicolons so we execute just the SQL string."""
    t = re.sub(r"```(?:sql)?", "", text, flags=re.IGNORECASE).replace("```", "").strip()
    return t.rstrip(";").strip()


def _rows_to_markdown(cols, rows, max_rows: int = 20) -> str:
    if not rows:
        return "(no rows)"
    out = ["| " + " | ".join(map(str, cols)) + " |",
           "| " + " | ".join(["---"] * len(cols)) + " |"]
    for r in rows[:max_rows]:
        out.append("| " + " | ".join(str(v) for v in r) + " |")
    if len(rows) > max_rows:
        out.append(f"_({len(rows)} rows, showing {max_rows})_")
    return "\n".join(out)


def answer(query: str, output_dir: str) -> str:
    """Answer a natural-language question over the generated SDTM data. Never raises to the UI."""
    if not query or not query.strip():
        return "Ask me something about the data (e.g. 'How many subjects are in each arm?')."
    if not output_dir or not Path(output_dir).exists():
        return _NEED_DATA_MSG
    tables = _domain_tables(output_dir)
    if not tables:
        return _NEED_DATA_MSG

    con = _connect(tables)
    try:
        schema = _schema_text(con, tables)
        sql = _sql_only(llm.complete(
            f"Table schemas:\n{schema}\n\nUser question: {query}",
            system=_SQL_SYSTEM, model=llm.MODEL_CHEAP, max_tokens=500,
        ))
        try:
            cur = con.execute(f"SELECT * FROM ({sql}) AS _q LIMIT {_RESULT_ROW_CAP}")
            rows = cur.fetchall()
            cols = [d[0] for d in cur.description]
        except Exception as e:  # noqa: BLE001 — bad SQL/columns → surface, never crash the chat
            return f"I couldn't run that query.\n\n**SQL:** `{sql}`\n\n**Error:** {e}"
        snippet = _rows_to_markdown(cols, rows)
        return llm.complete(
            f"Question: {query}\n\nSQL:\n{sql}\n\nResult (first {_RESULT_ROW_CAP} rows):\n{snippet}"
            "\n\nAnswer the question in 1-3 sentences using ONLY this result. If it's empty, say "
            "no matching records were found.",
            system=_ANSWER_SYSTEM, model=llm.MODEL_CHEAP, max_tokens=400,
        )
    finally:
        con.close()
