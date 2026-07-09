"""Offline tests for the MCP server. Skipped where the MCP SDK isn't installed (e.g. CI)."""

import asyncio
import json
import sys
from pathlib import Path

import pytest

pytest.importorskip("mcp")  # optional extra — skip cleanly when not installed

_REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO / "src"))
sys.path.insert(0, str(_REPO))

import mcp_server  # noqa: E402


def test_tools_registered():
    names = {t.name for t in asyncio.run(mcp_server.mcp.list_tools())}
    assert {"extract_protocol_design", "generate_sdtm_dataset", "validate_sdtm_dataset"} <= names


def test_generate_tool_runs_deterministically():
    design = json.dumps({
        "study_id": "MCP-T", "phase": "3",
        "arms": [{"name": "A"}, {"name": "P", "is_placebo": True}],
        "visits": [{"name": "BASE", "day": 1}, {"name": "WK4", "day": 28}],
        "population": {"n_subjects": 6},
        "domains": [{"domain": "DM"}, {"domain": "VS"}],
    })
    res = json.loads(mcp_server.generate_sdtm_dataset(design, subjects=6, seed=1))
    assert res["validation_passed"] is True
    assert res["domains"]["DM"] == 6 and "VS" in res["domains"]
