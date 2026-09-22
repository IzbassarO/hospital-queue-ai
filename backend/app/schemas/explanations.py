"""DTOs for evidence-grounded explanations of published operational signals."""

from __future__ import annotations

import datetime as dt
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.operational_intelligence import (
    FallbackStatus,
    ForecastTarget,
    RawQuantiles,
    Severity,
    SignalType,
    SourceProvenance,
    SupportStatus,
    UncertaintyStatus,
)

ExplanationGenerationMode = Literal["DETERMINISTIC", "NARRATED", "DETERMINISTIC_FALLBACK"]


class ExplanationSubject(BaseModel):
    signal_id: str
    signal_type: SignalType
    series_id: str
    target: ForecastTarget
    origin: dt.date
    org_code: str | None
    region_code: str | None
    profile_code: str | None
    severity: Severity
    inbox_rank: int | None


class ExplanationEvidenceItem(BaseModel):
    code: str
    statement: str
    value: str | float | int | bool | None = None


class ExplanationUncertainty(BaseModel):
    status: UncertaintyStatus
    narrative: str
    central_value: float | None
    central_semantics: str | None
    target_date: dt.date | None
    horizon_days: int | None
    raw_quantiles: RawQuantiles | None
    calibrated_lower: float | None
    calibrated_upper: float | None
    nominal_coverage: float | None
    calibration_status: str | None


class ExplanationSupport(BaseModel):
    status: SupportStatus
    fallback_status: FallbackStatus
    prediction_source: str | None
    narrative: str


class ExplanationCapabilityFact(BaseModel):
    capability_id: str
    evidence_status: str
    acceptance_verdict: str
    product_consumption_status: str
    human_review_required: bool
    autonomous_action: bool
    capacity_checked: bool
    causal_effect_claimed: bool


class ExplanationProvenance(BaseModel):
    publication_id: str
    publication_identity_sha256: str
    assurance_identity_sha256: str
    source_provenance: dict[str, SourceProvenance]
    model_assurance_capabilities: list[ExplanationCapabilityFact]


class SignalExplanationResponse(BaseModel):
    subject: ExplanationSubject
    summary: str
    why_flagged: list[str]
    key_evidence: list[ExplanationEvidenceItem]
    uncertainty: ExplanationUncertainty
    support: ExplanationSupport
    limitations: list[str]
    suggested_review_questions: list[str]
    provenance: ExplanationProvenance
    generation_mode: ExplanationGenerationMode


class SignalExplanationContext(BaseModel):
    """Bounded, published facts that may be passed to an optional narrator."""

    model_config = ConfigDict(extra="forbid")

    subject: ExplanationSubject
    headline: str
    concise_reason: str
    materiality_status: str | None
    pressure_basis: Literal["historical_flow_proxy_v1"] | None
    threshold_value: float | None
    threshold_status: str | None
    forecast_value: float | None
    first_crossing_date: dt.date | None
    lead_time_days: int | None
    reason_codes: list[str]
    evidence_facts: list[str]
    anomaly_evidence: dict[str, Any] | None
    uncertainty: ExplanationUncertainty
    support: ExplanationSupport
    limitations: list[str]
    provenance: ExplanationProvenance


class NarratedSections(BaseModel):
    """The only fields an optional narrator may rewrite."""

    model_config = ConfigDict(extra="forbid")

    summary: str = Field(min_length=1, max_length=1000)
    why_flagged: list[str] = Field(min_length=1, max_length=8)
