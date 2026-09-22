"""Candidate-independent publication input and API DTOs for operational intelligence."""

from __future__ import annotations

import datetime as dt
import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

SHA256 = r"^[0-9a-f]{64}$"
REQUIRED_PROVENANCE = {
    "flow_forecast",
    "flow_quantile",
    "flow_calibration",
    "flow_hierarchy",
    "flow_pressure",
    "signal_prioritization",
}

FreshnessState = Literal["FRESH", "STALE", "DEGRADED", "UNKNOWN"]
PublicationStatus = Literal["AVAILABLE", "DEGRADED", "EMPTY"]
ForecastLevel = Literal["hospital", "region", "national"]
ForecastTarget = Literal["registrations", "cohort_hospitalizations"]
CentralSemantics = Literal["P50", "POINT_FORECAST", "BOTTOM_UP_CENTRAL"]
PredictionSource = Literal["DIRECT", "REGION_PROFILE_FALLBACK", "BOTTOM_UP_AGGREGATE", "UNSUPPORTED"]
SupportStatus = Literal["DIRECT_SUPPORTED", "FALLBACK_LIMITED", "UNSUPPORTED"]
FallbackStatus = Literal["NOT_APPLICABLE", "REGION_PROFILE_FALLBACK", "OTHER_FALLBACK", "UNSUPPORTED"]
UncertaintyStatus = Literal["CALIBRATED", "INSUFFICIENT_CALIBRATION_SUPPORT", "UNAVAILABLE"]
CalibrationStatus = Literal["CALIBRATED", "INSUFFICIENT_SUPPORT", "NOT_APPLICABLE"]
SignalType = Literal["preventive_flow_pressure", "observed_unusual_flow"]
Severity = Literal["HIGH", "ELEVATED", "WATCH", "NORMAL", "UNSUPPORTED"]


class SourceProvenance(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: str = Field(min_length=1, max_length=128)
    scientific_identity_sha256: str = Field(pattern=SHA256)
    artifact_sha256: str | list[str] = Field()
    dataset_identity_sha256: str | None = Field(default=None, pattern=SHA256)
    config_identity_sha256: str | None = Field(default=None, pattern=SHA256)
    code_identity_sha256: str | None = Field(default=None, pattern=SHA256)

    @model_validator(mode="after")
    def validate_artifact_identity(self) -> SourceProvenance:
        values = self.artifact_sha256 if isinstance(self.artifact_sha256, list) else [self.artifact_sha256]
        if not values or any(re.fullmatch(SHA256, value) is None for value in values):
            raise ValueError("artifact_sha256 must contain lowercase SHA256 values")
        return self


class RawQuantiles(BaseModel):
    model_config = ConfigDict(extra="forbid")

    p10: float = Field(ge=0)
    p50: float = Field(ge=0)
    p90: float = Field(ge=0)
    semantics: Literal["UNCHANGED_MODEL_EVIDENCE"]

    @model_validator(mode="after")
    def ordered(self) -> RawQuantiles:
        if not self.p10 <= self.p50 <= self.p90:
            raise ValueError("raw quantiles must satisfy p10 <= p50 <= p90")
        return self


class CalibratedUncertainty(BaseModel):
    model_config = ConfigDict(extra="forbid")

    lower: float = Field(ge=0)
    upper: float = Field(ge=0)
    nominal_coverage: float = Field(gt=0, lt=1)
    calibration_status: Literal["CALIBRATED"]
    support_class: str = Field(min_length=1)
    calibration_version: str = Field(min_length=1, max_length=128)

    @model_validator(mode="after")
    def ordered(self) -> CalibratedUncertainty:
        if self.lower > self.upper:
            raise ValueError("calibrated uncertainty lower bound exceeds upper bound")
        return self


class ForecastPublicationRow(BaseModel):
    model_config = ConfigDict(extra="forbid")

    series_id: str = Field(min_length=1, max_length=64)
    level: ForecastLevel
    origin: dt.date
    target_date: dt.date
    horizon: int = Field(ge=1, le=366)
    target: ForecastTarget
    org_code: str | None = Field(default=None, max_length=8)
    region_code: str | None = Field(default=None, max_length=4)
    profile_code: str | None = Field(default=None, max_length=8)
    central_value: float = Field(ge=0)
    central_semantics: CentralSemantics
    raw_quantiles: RawQuantiles | None = None
    calibrated_uncertainty: CalibratedUncertainty | None = None
    calibration_status: CalibrationStatus
    prediction_source: PredictionSource
    hierarchy_status: str = Field(min_length=1, max_length=64)
    support_status: SupportStatus
    fallback_status: FallbackStatus
    uncertainty_status: UncertaintyStatus
    provenance_keys: list[str] = Field(min_length=1)
    evidence_facts: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_semantics(self) -> ForecastPublicationRow:
        if (self.target_date - self.origin).days != self.horizon:
            raise ValueError("forecast horizon must match target_date - origin")
        if self.level == "hospital" and not all((self.org_code, self.region_code, self.profile_code)):
            raise ValueError("hospital forecast requires org_code, region_code, and profile_code")
        if self.level == "region" and not all((self.region_code, self.profile_code)):
            raise ValueError("region forecast requires region_code and profile_code")
        if self.central_semantics == "P50" and (
            self.raw_quantiles is None or abs(self.central_value - self.raw_quantiles.p50) > 1e-9
        ):
            raise ValueError("P50 central value must equal the separately retained raw p50")
        if self.uncertainty_status == "CALIBRATED":
            if self.calibrated_uncertainty is None or self.calibration_status != "CALIBRATED":
                raise ValueError("calibrated uncertainty status requires calibrated bounds")
            if not self.calibrated_uncertainty.lower <= self.central_value <= self.calibrated_uncertainty.upper:
                raise ValueError("central forecast must fall within calibrated uncertainty bounds")
        elif self.calibrated_uncertainty is not None:
            raise ValueError("non-calibrated forecast must not carry calibrated bounds")
        if self.support_status == "DIRECT_SUPPORTED" and self.fallback_status != "NOT_APPLICABLE":
            raise ValueError("direct support cannot carry fallback status")
        return self


class AnomalyEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    observed_value: float = Field(ge=0)
    weekly_residual: float
    reference_median_residual: float
    reference_mad: float = Field(ge=0)
    robust_z: float | None
    reference_sample_count: int = Field(ge=0)
    reference_max_date: dt.date
    causal_claim: Literal[False]


class SignalPublicationRow(BaseModel):
    model_config = ConfigDict(extra="forbid")

    signal_id: str = Field(min_length=1, max_length=128)
    signal_type: SignalType
    series_id: str = Field(min_length=1, max_length=64)
    origin: dt.date
    target: ForecastTarget
    org_code: str | None = Field(default=None, max_length=8)
    region_code: str | None = Field(default=None, max_length=4)
    profile_code: str | None = Field(default=None, max_length=8)
    inbox_rank: int | None = Field(default=None, ge=1)
    severity: Severity
    headline: str = Field(min_length=1)
    concise_reason: str = Field(min_length=1)
    materiality_status: str | None = None
    support_status: SupportStatus
    fallback_status: FallbackStatus
    uncertainty_status: UncertaintyStatus
    pressure_basis: Literal["historical_flow_proxy_v1"] | None = None
    threshold_value: float | None = Field(default=None, ge=0)
    threshold_status: str | None = None
    forecast_value: float | None = Field(default=None, ge=0)
    uncertainty_lower: float | None = Field(default=None, ge=0)
    uncertainty_upper: float | None = Field(default=None, ge=0)
    first_crossing_date: dt.date | None = None
    lead_time_days: int | None = Field(default=None, ge=0)
    observed_anomaly_status: str | None = None
    observed_anomaly_present: bool = False
    data_freshness: dt.date | None = None
    reason_codes: list[str] = Field(min_length=1)
    evidence_facts: list[str] = Field(default_factory=list)
    provenance_keys: list[str] = Field(min_length=1)
    anomaly_evidence: AnomalyEvidence | None = None
    limitations: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_signal_semantics(self) -> SignalPublicationRow:
        bounds = (self.uncertainty_lower, self.uncertainty_upper)
        if (bounds[0] is None) != (bounds[1] is None):
            raise ValueError("signal uncertainty bounds must be supplied together")
        if bounds[0] is not None and bounds[0] > bounds[1]:
            raise ValueError("signal uncertainty lower bound exceeds upper bound")
        if self.uncertainty_status == "CALIBRATED" and bounds[0] is None:
            raise ValueError("calibrated signal requires uncertainty bounds")
        if self.uncertainty_status != "CALIBRATED" and bounds[0] is not None:
            raise ValueError("non-calibrated signal must not carry calibrated bounds")
        if self.signal_type == "preventive_flow_pressure":
            if self.pressure_basis != "historical_flow_proxy_v1":
                raise ValueError("preventive pressure must use historical_flow_proxy_v1")
            if self.anomaly_evidence is not None:
                raise ValueError("preventive pressure cannot embed observed anomaly evidence")
        else:
            if any(
                value is not None
                for value in (
                    self.pressure_basis,
                    self.threshold_value,
                    self.threshold_status,
                    self.forecast_value,
                    self.first_crossing_date,
                    self.lead_time_days,
                )
            ):
                raise ValueError("observed unusual flow must remain distinct from preventive pressure")
            if self.anomaly_evidence is None:
                raise ValueError("observed unusual flow requires anomaly_evidence")
            if not self.observed_anomaly_present:
                raise ValueError("observed unusual flow must declare observed_anomaly_present")
        if self.support_status == "DIRECT_SUPPORTED" and self.fallback_status != "NOT_APPLICABLE":
            raise ValueError("direct support cannot carry fallback status")
        return self


class OperationalIntelligenceBundle(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["operational_intelligence_v1"]
    contract_version: Literal["1.0.0"]
    publication_id: str = Field(min_length=1, max_length=128)
    publication_identity_sha256: str = Field(pattern=SHA256)
    assurance_identity_sha256: str = Field(pattern=SHA256)
    source_code_commit: str = Field(pattern=r"^[0-9a-f]{40}$")
    current_origin: dt.date
    freshness_state: FreshnessState
    publication_status: PublicationStatus
    generated_at: dt.datetime | None = None
    source_provenance: dict[str, SourceProvenance]
    limitations: list[str] = Field(min_length=1)
    forecasts: list[ForecastPublicationRow]
    signals: list[SignalPublicationRow]

    @model_validator(mode="after")
    def validate_bundle(self) -> OperationalIntelligenceBundle:
        missing = REQUIRED_PROVENANCE - set(self.source_provenance)
        if missing:
            raise ValueError(f"missing source provenance: {', '.join(sorted(missing))}")
        forecast_keys = [(row.series_id, row.target, row.origin, row.target_date) for row in self.forecasts]
        if len(forecast_keys) != len(set(forecast_keys)):
            raise ValueError("duplicate forecast point")
        signal_ids = [row.signal_id for row in self.signals]
        if len(signal_ids) != len(set(signal_ids)):
            raise ValueError("duplicate signal_id")
        ranks = [(row.origin, row.inbox_rank) for row in self.signals if row.inbox_rank is not None]
        if len(ranks) != len(set(ranks)):
            raise ValueError("duplicate inbox_rank within origin")
        for row in [*self.forecasts, *self.signals]:
            unknown = set(row.provenance_keys) - set(self.source_provenance)
            if unknown:
                raise ValueError(f"unknown provenance keys: {', '.join(sorted(unknown))}")
        if (self.forecasts or self.signals) and self.current_origin not in {
            row.origin for row in [*self.forecasts, *self.signals]
        }:
            raise ValueError("current_origin is absent from all published rows")
        if self.publication_status == "EMPTY" and (self.forecasts or self.signals):
            raise ValueError("EMPTY publication cannot contain forecasts or signals")
        return self


class OperationalSnapshotResponse(BaseModel):
    publication_id: str
    schema_version: str
    contract_version: str
    publication_identity_sha256: str
    bundle_sha256: str
    assurance_identity_sha256: str
    source_code_commit: str
    current_origin: dt.date
    freshness_state: FreshnessState
    publication_status: PublicationStatus
    generated_at: dt.datetime | None
    published_at: dt.datetime
    forecast_count: int
    signal_count: int
    source_provenance: dict[str, SourceProvenance]
    limitations: list[str]


class OperationalForecastResponse(ForecastPublicationRow):
    publication_identity_sha256: str
    source_provenance: dict[str, SourceProvenance]


class OperationalSignalResponse(SignalPublicationRow):
    publication_identity_sha256: str
    source_provenance: dict[str, SourceProvenance]


class OperationalCounts(BaseModel):
    total_signals: int = 0
    high: int = 0
    elevated: int = 0
    watch: int = 0
    normal: int = 0
    unsupported_severity: int = 0
    preventive_pressure: int = 0
    observed_unusual_flow: int = 0
    direct_supported: int = 0
    fallback_limited: int = 0
    unsupported_support: int = 0
    calibrated: int = 0
    uncertainty_limited_or_unavailable: int = 0


class OperationalRegionSummary(BaseModel):
    region_code: str
    counts: OperationalCounts


class OperationalOverviewResponse(BaseModel):
    snapshot: OperationalSnapshotResponse
    national: OperationalCounts
    regions: list[OperationalRegionSummary]


class OperationalRegionResponse(BaseModel):
    snapshot: OperationalSnapshotResponse
    region_code: str
    counts: OperationalCounts
    top_signals: list[OperationalSignalResponse]
    forecast_point_count: int
    available_origins: list[dt.date]
    available_targets: list[ForecastTarget]


class OperationalHospitalProfileResponse(BaseModel):
    snapshot: OperationalSnapshotResponse
    org_code: str
    region_code: str | None
    profile_code: str
    counts: OperationalCounts
    signals: list[OperationalSignalResponse]
    forecast_point_count: int
    available_origins: list[dt.date]
    available_targets: list[ForecastTarget]
