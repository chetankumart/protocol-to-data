#!/usr/bin/env python
"""MCP server for protocol-to-data — exposes the agentic loop as Model Context Protocol tools.

Because the core is a clean hybrid-AI boundary (Claude reasons, deterministic Python
generates), each capability maps 1:1 to an MCP tool. Any MCP client — Claude Desktop, Claude
Code, or another agent — can extract a design, generate an SDTM dataset, and validate it.

Run (stdio transport):   python mcp_server.py
Requires the MCP SDK:    pip install ".[mcp]"   (optional extra; the app/CLI don't need it)

Register in Claude Desktop (`claude_desktop_config.json`):
    {
      "mcpServers": {
        "protocol-to-data": {
          "command": "python",
          "args": ["/absolute/path/to/protocol-to-data/mcp_server.py"],
          "env": { "ANTHROPIC_API_KEY": "sk-ant-..." }
        }
      }
    }
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(_ROOT / "src"))

import cli  # noqa: E402  — reuse its .env loader
from mcp.server.fastmcp import FastMCP  # noqa: E402
from protocol_to_data.extract import extract_design_from_text  # noqa: E402
from protocol_to_data.generate import generate_dataset  # noqa: E402
from protocol_to_data.schemas import ProtocolDesign  # noqa: E402
from protocol_to_data.validate import validate_dataset  # noqa: E402

cli._load_dotenv()
mcp = FastMCP("protocol-to-data")


@mcp.tool()
def extract_protocol_design(protocol_text: str) -> str:
    """Extract a typed clinical-trial design from raw protocol prose using Claude.

    Returns a ProtocolDesign as JSON — arms, visit schedule, endpoints mapped to SDTM
    domains, population, and the assumptions Claude had to make. Requires ANTHROPIC_API_KEY.
    """
    return extract_design_from_text(protocol_text).model_dump_json(indent=2)


@mcp.tool()
def generate_sdtm_dataset(design_json: str, subjects: int = 20, seed: int = 42) -> str:
    """Generate a deterministic, referentially-sound SDTM synthetic dataset from a design.

    Input is a ProtocolDesign JSON (e.g. from `extract_protocol_design`). No LLM / API key
    needed — this is 100% deterministic Python. Returns the output directory, the produced
    domains with row counts, and whether validation passed.
    """
    import pandas as pd
    design = ProtocolDesign.model_validate_json(design_json)
    out = generate_dataset(design, subjects=subjects, seed=seed,
                           out_root=str(_ROOT / "data" / "output"))
    report = validate_dataset(design, out)
    domains = {p.stem.upper(): int(len(pd.read_csv(p))) for p in sorted(out.glob("*.csv"))}
    return json.dumps({
        "output_dir": str(out),
        "domains": domains,
        "validation_passed": report.passed,
        "findings": [f.message for f in report.findings],
    }, indent=2)


@mcp.tool()
def validate_sdtm_dataset(data_dir: str) -> str:
    """Validate an SDTM dataset directory (schema · referential integrity · clinical rules).

    Returns the ValidationReport JSON. No API key needed.
    """
    design = ProtocolDesign(study_id=Path(data_dir).parent.name)
    return validate_dataset(design, data_dir).model_dump_json(indent=2)


if __name__ == "__main__":
    mcp.run()
