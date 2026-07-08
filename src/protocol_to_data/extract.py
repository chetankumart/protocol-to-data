"""Stage 2 — EXTRACT: protocol text → ProtocolDesign (Claude-driven).

This is the reasoning step. Claude reads messy protocol prose and emits a typed design.

Primary path uses structured outputs (`parse_model`) so the result is schema-valid by
construction. If that fails for any reason, we fall back to JSON-mode extraction with one
repair attempt that feeds the validation error back to Claude — extraction should degrade,
never crash the loop.
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable, Optional

from pydantic import ValidationError

from .ingest import load_protocol_text, sha256_of
from .llm import MODEL_REASON, complete_json
from .schemas import DomainPlan, ProtocolDesign

_ROOT = Path(__file__).resolve().parents[2]
_PROMPT_PATH = _ROOT / "prompts" / "extract_design.md"
_CACHE_DIR = _ROOT / ".cache"          # semantic (content-addressed) extraction cache
_MAX_CHARS = 120_000  # keep within context

Narrator = Callable[[str], None]


def _noop(_: str) -> None:
    pass


def extract_design(protocol_path: str | Path, *, model: str = MODEL_REASON,
                   narrate: Optional[Narrator] = None, use_cache: bool = True) -> ProtocolDesign:
    """Read a protocol file and return a validated ProtocolDesign.

    Semantic cache: the design is keyed by the SHA-256 of the document bytes. If a cached
    `{hash}_extracted_design.json` exists, it's loaded and the Claude extraction call is
    skipped entirely — identical documents never pay for extraction twice. Pass
    `use_cache=False` to force a fresh extraction.
    """
    say = narrate or _noop
    if use_cache:
        cached = _load_cached_design(protocol_path, say)
        if cached is not None:
            return cached
    design = extract_design_from_text(load_protocol_text(protocol_path), model=model, narrate=narrate)
    if use_cache:
        _save_cached_design(protocol_path, design, say)
    return design


def _cache_file(protocol_path: str | Path) -> Path:
    return _CACHE_DIR / f"{sha256_of(protocol_path)}_extracted_design.json"


def _load_cached_design(protocol_path: str | Path, say: Narrator) -> Optional[ProtocolDesign]:
    """Return the cached design for this document, or None on miss / corrupt cache."""
    fp = _cache_file(protocol_path)
    if not fp.exists():
        return None
    try:
        design = ProtocolDesign.model_validate_json(fp.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001 — a corrupt/stale cache entry is just a miss
        return None
    say(f"    → cache hit — loaded design, skipped Claude extraction ({fp.name[:19]}…)")
    return design


def _save_cached_design(protocol_path: str | Path, design: ProtocolDesign, say: Narrator) -> None:
    """Persist the extracted design; caching is best-effort and never fails the run."""
    try:
        _CACHE_DIR.mkdir(parents=True, exist_ok=True)
        _cache_file(protocol_path).write_text(design.model_dump_json(indent=2), encoding="utf-8")
        say("    → cached extracted design for future runs")
    except OSError:
        pass


def extract_design_from_text(text: str, *, model: str = MODEL_REASON,
                             narrate: Optional[Narrator] = None) -> ProtocolDesign:
    say = narrate or _noop
    design = normalize_design(design_from_prompt(_build_prompt(text), model=model, narrate=narrate))
    if design.assumptions:
        say(f"    → {len(design.assumptions)} assumption(s) noted (e.g. {design.assumptions[0]})")
    return design


def design_from_prompt(prompt: str, *, model: str = MODEL_REASON,
                       narrate: Optional[Narrator] = None) -> ProtocolDesign:
    """Get a validated ProtocolDesign from a prompt via JSON mode + one-shot repair.

    Shared by extraction and the loop's repair step. (Structured outputs reject
    ProtocolDesign with "Schema is too complex" — it's a 5-model nested schema — so we
    use JSON mode directly and repair once if the first result is schema-invalid.)
    """
    return _extract_via_json(prompt, model=model, say=narrate or _noop)


def _build_prompt(text: str) -> str:
    template = _PROMPT_PATH.read_text(encoding="utf-8")
    return template.replace("{{PROTOCOL_TEXT}}", text[:_MAX_CHARS])


def _extract_via_json(prompt: str, *, model: str, say: Narrator) -> ProtocolDesign:
    """Fallback: raw JSON mode, with one repair pass if the first result is schema-invalid."""
    raw = complete_json(prompt, model=model, max_tokens=6000)
    try:
        return ProtocolDesign.model_validate(raw)
    except ValidationError as e:
        say("    → first extraction failed validation; asking Claude to correct it")
        repair_prompt = (
            f"{prompt}\n\nYour previous JSON did not match the schema. Errors:\n{e}\n\n"
            "Return corrected JSON only."
        )
        raw = complete_json(repair_prompt, model=model, max_tokens=6000)
        return ProtocolDesign.model_validate(raw)  # let a second failure surface


def normalize_design(design: ProtocolDesign) -> ProtocolDesign:
    """Enforce invariants the generator relies on: DM present, no duplicate domains."""
    seen: set[str] = set()
    deduped: list[DomainPlan] = []
    for dp in design.domains:
        key = dp.domain.upper()
        if key not in seen:
            seen.add(key)
            deduped.append(dp)
    if "DM" not in seen:
        deduped.insert(0, DomainPlan(
            domain="DM",
            key_variables=["USUBJID", "AGE", "SEX", "ARM", "RFSTDTC"],
        ))
    design.domains = deduped
    return design
