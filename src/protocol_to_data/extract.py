"""Stage 2 — EXTRACT: protocol text → ProtocolDesign (Claude-driven).

This is the reasoning step. Claude reads messy protocol prose and emits a typed design.
"""

from __future__ import annotations

from pathlib import Path

from .ingest import load_protocol_text
from .llm import MODEL_REASON, complete_json
from .schemas import ProtocolDesign

_PROMPT_PATH = Path(__file__).resolve().parents[2] / "prompts" / "extract_design.md"


def extract_design(protocol_path: str | Path, *, model: str = MODEL_REASON) -> ProtocolDesign:
    """Read a protocol file and return a validated ProtocolDesign."""
    text = load_protocol_text(protocol_path)
    template = _PROMPT_PATH.read_text(encoding="utf-8")
    prompt = template.replace("{{PROTOCOL_TEXT}}", text[:120_000])  # keep within context

    raw = complete_json(prompt, model=model, max_tokens=6000)
    return ProtocolDesign.model_validate(raw)


def extract_design_from_text(text: str, *, model: str = MODEL_REASON) -> ProtocolDesign:
    template = _PROMPT_PATH.read_text(encoding="utf-8")
    prompt = template.replace("{{PROTOCOL_TEXT}}", text[:120_000])
    raw = complete_json(prompt, model=model, max_tokens=6000)
    return ProtocolDesign.model_validate(raw)
