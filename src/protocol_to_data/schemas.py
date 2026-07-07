"""Typed contracts for the protocol-to-data loop.

`ProtocolDesign` is the intermediate representation between Claude's extraction step
and the deterministic generation step. Keep it JSON-serializable and stable — the
extraction prompt (`prompts/extract_design.md`) targets this exact shape.
"""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field

Phase = Literal["1", "2", "3", "4"]
EndpointType = Literal["primary", "secondary", "exploratory"]
Sex = Literal["all", "female", "male"]


class Arm(BaseModel):
    name: str
    description: str = ""
    n_planned: int = 0
    is_placebo: bool = False


class Visit(BaseModel):
    name: str
    day: int = Field(..., description="Relative to first dose (day 1). Screening is negative.")
    window_days: int = 0
    is_screening: bool = False
    is_treatment: bool = True


class Endpoint(BaseModel):
    name: str
    type: EndpointType = "secondary"
    domain: str = Field(..., description="SDTM domain that carries this endpoint, e.g. VS, LB, QS, AE")
    measure: str = ""


class Population(BaseModel):
    n_subjects: int = 0
    age_range: tuple[int, int] = (18, 85)
    sex: Sex = "all"
    key_inclusion: list[str] = Field(default_factory=list)
    key_exclusion: list[str] = Field(default_factory=list)


class DomainPlan(BaseModel):
    domain: str
    source_endpoints: list[str] = Field(default_factory=list)
    key_variables: list[str] = Field(default_factory=list)


class ProtocolDesign(BaseModel):
    study_id: str
    title: str = ""
    phase: Phase = "3"
    therapeutic_area: str = ""
    indication: str = ""
    arms: list[Arm] = Field(default_factory=list)
    visits: list[Visit] = Field(default_factory=list)
    endpoints: list[Endpoint] = Field(default_factory=list)
    population: Population = Field(default_factory=Population)
    domains: list[DomainPlan] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)

    def domain_names(self) -> list[str]:
        return [d.domain for d in self.domains]


class ValidationFinding(BaseModel):
    check: str
    domain: Optional[str] = None
    severity: Literal["high", "medium", "low"] = "high"
    message: str
    count: int = 1


class ValidationReport(BaseModel):
    study_id: str
    passed: bool
    findings: list[ValidationFinding] = Field(default_factory=list)

    @property
    def error_count(self) -> int:
        return sum(f.count for f in self.findings if f.severity == "high")


class AnomalyFinding(BaseModel):
    domain: str
    usubjid: Optional[str] = None
    anomaly_type: Literal["temporal", "physiologic", "referential", "uniqueness", "logical"]
    description: str
    evidence: str = ""
    severity: Literal["high", "medium", "low"] = "high"


class RunManifest(BaseModel):
    study_id: str
    protocol_path: str
    protocol_sha256: str
    seed: int
    subjects: int
    backend: str
    model: str
    design: ProtocolDesign
    validation_passed: bool
    repair_attempts: int = 0
    created_utc: str = ""  # stamped by caller (Date.now not available inside some harness contexts)
