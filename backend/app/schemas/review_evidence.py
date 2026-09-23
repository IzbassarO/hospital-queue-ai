"""Candidate-independent publication input and API DTOs for review evidence.

Review evidence is the explicit product projection of two accepted, EVALUATION_ONLY capabilities:
the Forecast Stress-Test Engine (deterministic non-causal registration stress tests) and the
Constrained Decision Alternatives Engine (retrospective mathematical alternatives for human review).
Neither is an operational signal, a recommendation, a routing decision, a capacity check or a causal
claim. Rows are published only for the accepted baseline they were verified against.
"""

from __future__ import annotations

import datetime as dt
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.schemas.operational_intelligence import (
    SHA256,
    ForecastTarget,
    FreshnessState,
    Severity,
    SourceProvenance,
    SupportStatus,
)

REQUIRED_REVIEW_PROVENANCE = {"flow_scenario", "decision_alternatives"}

ScenarioType = Literal["identity", "demand_multiplier"]
ScenarioClassification = Literal["SAFE_NON_CAUSAL_STRESS_TEST", "MECHANISTIC_ACCOUNTING_SCENARIO"]
ScenarioUncertaintyStatus = Literal[
    "TRANSFORMED_BASELINE_UNCERTAINTY_RANGE",
    "UNAVAILABLE",
    "NOT_SCENARIO_ADJUSTED",
]
VerificationState = Literal["VERIFIED_FULL_ENGINE", "FAST_PATH_ONLY", "VERIFICATION_FAILED"]
RangeEvidence = Literal["COMPLETE", "RANGE_LIMITED"]
SensitivityRangeResult = Literal[
    "ROBUST_TO_TRANSFORMED_RANGE",
    "NOT_ROBUST_TO_TRANSFORMED_RANGE",
    "RANGE_EVIDENCE_INCOMPLETE",
]
ReviewPublicationStatus = Literal["AVAILABLE", "EMPTY"]


class ScenarioNetworkSummary(BaseModel):
    """Population-level counts copied from the accepted scenario summary; never recomputed."""

    model_config = ConfigDict(extra="forbid")

    daily_cells_total: int = Field(ge=0)
    severity_changed_count: int = Field(ge=0)
    severity_changed_share: float = Field(ge=0, le=1)
    severity_counts: dict[str, int]
    entity_count: int = Field(ge=0)
    entity_severity_changed_count: int = Field(ge=0)


class ScenarioCatalogRow(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scenario_id: str = Field(min_length=1, max_length=128)
    scenario_type: ScenarioType
    classification: ScenarioClassification
    lever_type: str = Field(min_length=1, max_length=64)
    multiplier: float | None = Field(default=None, gt=0)
    scope_type: str = Field(min_length=1, max_length=64)
    horizon_start: int = Field(ge=1, le=366)
    horizon_end: int = Field(ge=1, le=366)
    target: ForecastTarget
    uncertainty_method: str = Field(min_length=1, max_length=64)
    uncertainty_label: str = Field(min_length=1, max_length=64)
    coverage_guarantee: Literal[False]
    causal_effect_claimed: Literal[False]
    serving_claim: Literal[False]
    baseline_reproduction: Literal["PASS"] | None = None
    network_summary: ScenarioNetworkSummary
    evidence_facts: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_lever(self) -> ScenarioCatalogRow:
        if self.scenario_type == "identity" and self.multiplier is not None:
            raise ValueError("identity scenario cannot carry a multiplier")
        if self.scenario_type == "demand_multiplier" and self.multiplier is None:
            raise ValueError("demand_multiplier scenario requires a multiplier")
        if self.horizon_end < self.horizon_start:
            raise ValueError("scenario horizon range is inverted")
        return self


class ScenarioEntityRow(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scenario_id: str = Field(min_length=1, max_length=128)
    series_id: str = Field(min_length=1, max_length=64)
    origin: dt.date
    target: ForecastTarget
    org_code: str = Field(max_length=8)
    region_code: str = Field(max_length=4)
    profile_code: str = Field(max_length=8)
    signal_id: str = Field(min_length=1, max_length=128)
    baseline_severity: Severity
    scenario_severity: Severity
    baseline_inbox_rank: int | None = Field(default=None, ge=1)
    scenario_inbox_rank: int | None = Field(default=None, ge=1)
    baseline_central: float = Field(ge=0)
    scenario_central: float = Field(ge=0)
    threshold_value: float | None = Field(default=None, ge=0)
    absolute_delta: float
    relative_delta: float | None = None
    severity_changed: bool
    entered_primary_inbox: bool
    left_primary_inbox: bool
    first_crossing_date: dt.date | None = None
    lead_time_days: int | None = Field(default=None, ge=0)
    materiality_status: str | None = None
    scenario_headline: str | None = None
    scenario_reason: str | None = None
    scenario_range_available: bool
    limitations: list[str] = Field(default_factory=list)


class ScenarioCellRow(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scenario_id: str = Field(min_length=1, max_length=128)
    series_id: str = Field(min_length=1, max_length=64)
    origin: dt.date
    target: ForecastTarget
    target_date: dt.date
    horizon: int = Field(ge=1, le=366)
    baseline_central: float = Field(ge=0)
    baseline_lower: float | None = Field(default=None, ge=0)
    baseline_upper: float | None = Field(default=None, ge=0)
    baseline_severity: Severity
    scenario_central: float = Field(ge=0)
    scenario_lower: float | None = Field(default=None, ge=0)
    scenario_upper: float | None = Field(default=None, ge=0)
    scenario_severity: Severity
    threshold_value: float | None = Field(default=None, ge=0)
    threshold_status: str | None = None
    scenario_uncertainty_status: ScenarioUncertaintyStatus
    severity_changed: bool
    source_reason_code: str | None = None

    @model_validator(mode="after")
    def validate_ranges(self) -> ScenarioCellRow:
        if (self.target_date - self.origin).days != self.horizon:
            raise ValueError("scenario cell horizon must match target_date - origin")
        for lower, upper, name in (
            (self.baseline_lower, self.baseline_upper, "baseline"),
            (self.scenario_lower, self.scenario_upper, "scenario"),
        ):
            if (lower is None) != (upper is None):
                raise ValueError(f"{name} bounds must be supplied together")
            if lower is not None and lower > upper:
                raise ValueError(f"{name} lower bound exceeds upper bound")
        if self.scenario_uncertainty_status == "TRANSFORMED_BASELINE_UNCERTAINTY_RANGE" and self.scenario_lower is None:
            raise ValueError("transformed sensitivity range requires bounds")
        if self.scenario_uncertainty_status != "TRANSFORMED_BASELINE_UNCERTAINTY_RANGE" and (
            self.scenario_lower is not None
        ):
            raise ValueError("a scenario without a derived range must not carry bounds")
        return self


class SeriesRef(BaseModel):
    model_config = ConfigDict(extra="forbid")

    org_code: str = Field(max_length=8)
    profile_code: str = Field(max_length=8)
    region_code: str = Field(max_length=4)
    series_id: str = Field(min_length=1, max_length=64)


class StateCell(BaseModel):
    model_config = ConfigDict(extra="forbid")

    horizon: int = Field(ge=1, le=366)
    target_date: dt.date
    central: float = Field(ge=0)
    lower: float | None = Field(default=None, ge=0)
    upper: float | None = Field(default=None, ge=0)
    severity: Severity
    threshold_value: float | None = Field(default=None, ge=0)
    threshold_status: str | None = None


class SeriesState(BaseModel):
    model_config = ConfigDict(extra="forbid")

    displayed_severity: Severity
    max_severity_7d: Severity
    max_severity_14d: Severity
    severity_evidence_horizon: int | None = Field(default=None, ge=1)
    severity_evidence_date: dt.date | None = None
    cells: list[StateCell] = Field(min_length=1)


class TransferByHorizon(BaseModel):
    model_config = ConfigDict(extra="forbid")

    horizon: int = Field(ge=1, le=366)
    target_date: dt.date
    moved: float = Field(ge=0)


class InboxOutcome(BaseModel):
    model_config = ConfigDict(extra="forbid")

    baseline_inbox_rank: int | None = Field(default=None, ge=1)
    scenario_inbox_rank: int | None = Field(default=None, ge=1)
    baseline_severity: Severity
    scenario_severity: Severity
    entered_primary_inbox: bool
    left_primary_inbox: bool


class AlternativeRow(BaseModel):
    model_config = ConfigDict(extra="forbid")

    alternative_id: str = Field(min_length=1, max_length=128)
    donor: SeriesRef
    receiver: SeriesRef
    transfer_fraction: float = Field(gt=0, le=1)
    transfer_fraction_certification: str = Field(min_length=1)
    transferred_total: float = Field(ge=0)
    transferred_by_horizon: list[TransferByHorizon] = Field(min_length=1)
    donor_severity_before: Severity
    donor_severity_after: Severity
    receiver_severity_before: Severity
    receiver_severity_after: Severity
    donor_binding_horizons: list[int]
    donor_binding_cell: dict[str, Any] | None = None
    receiver_binding_cell: dict[str, Any] | None = None
    receiver_min_central_headroom: float
    receiver_no_worse_constraint_satisfied: Literal[True]
    conservation_satisfied: Literal[True]
    budget_constraint_satisfied: Literal[True]
    source_central_goal_satisfied: Literal[True]
    verification_state: VerificationState
    forecast_support_tier: SupportStatus
    donor_support_class: SupportStatus
    receiver_support_class: SupportStatus
    receiver_range_evidence: RangeEvidence
    sensitivity_range_result: SensitivityRangeResult
    feasibility_status: Literal["NOT_PHYSICAL_CAPACITY_VALIDATED"]
    capacity_checked: Literal[False]
    causal_effect_claimed: Literal[False]
    human_review_required: Literal[True]
    hierarchy_coherent: bool
    donor_inbox: InboxOutcome
    receiver_inbox: InboxOutcome
    explanation_text: str = Field(min_length=1)
    non_claims: list[str] = Field(min_length=1)
    limitations: list[str] = Field(min_length=1)
    baseline_donor_state: SeriesState
    scenario_donor_state: SeriesState
    baseline_receiver_state: SeriesState
    scenario_receiver_state: SeriesState

    @model_validator(mode="after")
    def validate_alternative(self) -> AlternativeRow:
        if self.donor.profile_code != self.receiver.profile_code:
            raise ValueError("alternatives are same-profile by contract")
        if self.donor.region_code != self.receiver.region_code:
            raise ValueError("alternatives are same-region by contract")
        if self.donor.series_id == self.receiver.series_id:
            raise ValueError("donor and receiver must differ")
        if "NOT_PHYSICAL_CAPACITY_VALIDATED" not in self.limitations:
            raise ValueError("alternative must carry NOT_PHYSICAL_CAPACITY_VALIDATED")
        if "THRESHOLD_COMPARATOR_ASSUMPTION" not in self.limitations:
            raise ValueError("alternative must carry THRESHOLD_COMPARATOR_ASSUMPTION")
        return self


class DonorRef(BaseModel):
    model_config = ConfigDict(extra="forbid")

    signal_id: str = Field(min_length=1, max_length=128)
    org_code: str = Field(max_length=8)
    profile_code: str = Field(max_length=8)
    region_code: str = Field(max_length=4)
    series_id: str = Field(min_length=1, max_length=64)
    displayed_severity: Severity
    priority_support_class: str = Field(min_length=1)
    materiality_status: str | None = None
    binding_horizons: list[int]
    inbox_rank: int | None = Field(default=None, ge=1)


class AlternativeSetRow(BaseModel):
    model_config = ConfigDict(extra="forbid")

    set_id: str = Field(min_length=1, max_length=128)
    canonical_unit_id: str = Field(min_length=1, max_length=128)
    origin: dt.date
    target: ForecastTarget
    donor: DonorRef
    budget: float = Field(gt=0, le=1)
    abstained: bool
    abstention_codes: list[str]
    rejected_receiver_counts: dict[str, int]
    receiver_candidates_considered: int = Field(ge=0)
    receiver_candidates_eligible: int = Field(ge=0)
    donor_minimum_transfer_fraction: float | None = Field(default=None, ge=0)
    shortlist_bound: int = Field(ge=1)
    alternatives: list[AlternativeRow]
    verification_failure_count: int = Field(ge=0)
    scientific_output_sha256: str = Field(pattern=SHA256)
    execution_mode: Literal["EVALUATION"]
    human_review_required: Literal[True]
    serving_claim: Literal[False]
    limitations: list[str] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_set(self) -> AlternativeSetRow:
        if self.abstained and self.alternatives:
            raise ValueError("an abstained set cannot publish alternatives")
        if not self.abstained and not self.alternatives:
            raise ValueError("a non-abstained set must publish alternatives")
        if self.verification_failure_count:
            raise ValueError("sets with verification failures are not publishable review evidence")
        for alternative in self.alternatives:
            if alternative.donor.series_id != self.donor.series_id:
                raise ValueError("alternative donor differs from the set donor")
            if alternative.transfer_fraction > self.budget + 1e-12:
                raise ValueError("alternative exceeds its policy budget")
        return self


class AlternativesSummary(BaseModel):
    """Accepted population metrics copied from Model Assurance evidence; not recomputed here."""

    model_config = ConfigDict(extra="forbid")

    set_count: int = Field(ge=0)
    unit_count: int = Field(ge=0)
    sets_with_alternatives: int = Field(ge=0)
    alternative_count: int = Field(ge=0)
    receiver_worsening_count: int = Field(ge=0)
    verification_failure_count: int = Field(ge=0)
    full_verification_success_rate: float = Field(ge=0, le=1)
    transfer_budget_ladder: list[float]
    origins: list[dt.date]
    evaluation_population: str = Field(min_length=1)


class ReviewEvidenceBundle(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["review_evidence_v1"]
    contract_version: Literal["1.0.0"]
    publication_id: str = Field(min_length=1, max_length=128)
    publication_identity_sha256: str = Field(pattern=SHA256)
    assurance_identity_sha256: str = Field(pattern=SHA256)
    operational_publication_identity_sha256: str = Field(pattern=SHA256)
    source_code_commit: str = Field(pattern=r"^[0-9a-f]{40}$")
    current_origin: dt.date
    freshness_state: FreshnessState
    publication_status: ReviewPublicationStatus
    generated_at: dt.datetime | None = None
    source_provenance: dict[str, SourceProvenance]
    limitations: list[str] = Field(min_length=1)
    scenarios: list[ScenarioCatalogRow]
    scenario_entities: list[ScenarioEntityRow]
    scenario_cells: list[ScenarioCellRow]
    alternative_sets: list[AlternativeSetRow]
    alternatives_summary: AlternativesSummary

    @model_validator(mode="after")
    def validate_bundle(self) -> ReviewEvidenceBundle:
        missing = REQUIRED_REVIEW_PROVENANCE - set(self.source_provenance)
        if missing:
            raise ValueError(f"missing source provenance: {', '.join(sorted(missing))}")
        scenario_ids = [row.scenario_id for row in self.scenarios]
        if len(scenario_ids) != len(set(scenario_ids)):
            raise ValueError("duplicate scenario_id")
        known = set(scenario_ids)
        entity_keys = [(r.scenario_id, r.series_id, r.target, r.origin) for r in self.scenario_entities]
        if len(entity_keys) != len(set(entity_keys)):
            raise ValueError("duplicate scenario entity")
        cell_keys = [(r.scenario_id, r.series_id, r.target, r.origin, r.target_date) for r in self.scenario_cells]
        if len(cell_keys) != len(set(cell_keys)):
            raise ValueError("duplicate scenario cell")
        entity_set = set(entity_keys)
        for key in cell_keys:
            if key[0] not in known:
                raise ValueError(f"scenario cell references unknown scenario {key[0]!r}")
            if key[:4] not in entity_set:
                raise ValueError("scenario cell without a published entity row")
        for row in self.scenario_entities:
            if row.scenario_id not in known:
                raise ValueError(f"scenario entity references unknown scenario {row.scenario_id!r}")
        set_ids = [row.set_id for row in self.alternative_sets]
        if len(set_ids) != len(set(set_ids)):
            raise ValueError("duplicate alternative set_id")
        if self.publication_status == "EMPTY" and (self.scenarios or self.alternative_sets):
            raise ValueError("EMPTY publication cannot contain scenarios or alternative sets")
        if self.publication_status == "AVAILABLE" and not (self.scenarios and self.scenario_cells):
            raise ValueError("AVAILABLE publication requires scenario evidence")
        if self.publication_status == "AVAILABLE" and self.current_origin not in {
            r.origin for r in [*self.scenario_entities, *self.alternative_sets]
        }:
            raise ValueError("current_origin is absent from all published rows")
        return self


# ------------------------------------------------------------------------------ API responses
class ReviewSnapshotResponse(BaseModel):
    publication_id: str
    schema_version: str
    contract_version: str
    publication_identity_sha256: str
    bundle_sha256: str
    assurance_identity_sha256: str
    operational_publication_identity_sha256: str
    source_code_commit: str
    current_origin: dt.date
    freshness_state: FreshnessState
    publication_status: ReviewPublicationStatus
    generated_at: dt.datetime | None
    published_at: dt.datetime
    scenario_count: int
    scenario_entity_count: int
    scenario_cell_count: int
    alternative_set_count: int
    alternative_count: int
    source_provenance: dict[str, SourceProvenance]
    limitations: list[str]


class ScenarioCatalogResponse(ScenarioCatalogRow):
    pass


class ReviewOverviewResponse(BaseModel):
    snapshot: ReviewSnapshotResponse
    scenarios: list[ScenarioCatalogResponse]
    alternatives_summary: AlternativesSummary


class ScenarioCellResponse(BaseModel):
    target_date: dt.date
    horizon: int
    baseline_central: float
    baseline_lower: float | None
    baseline_upper: float | None
    baseline_severity: Severity
    scenario_central: float
    scenario_lower: float | None
    scenario_upper: float | None
    scenario_severity: Severity
    threshold_value: float | None
    threshold_status: str | None
    scenario_uncertainty_status: ScenarioUncertaintyStatus
    severity_changed: bool
    source_reason_code: str | None


class ScenarioOutcomeResponse(BaseModel):
    scenario: ScenarioCatalogResponse
    baseline_severity: Severity
    scenario_severity: Severity
    baseline_inbox_rank: int | None
    scenario_inbox_rank: int | None
    baseline_central: float
    scenario_central: float
    threshold_value: float | None
    absolute_delta: float
    relative_delta: float | None
    severity_changed: bool
    entered_primary_inbox: bool
    left_primary_inbox: bool
    first_crossing_date: dt.date | None
    lead_time_days: int | None
    materiality_status: str | None
    scenario_headline: str | None
    scenario_reason: str | None
    scenario_range_available: bool
    limitations: list[str]
    cells: list[ScenarioCellResponse]


class SignalStressTestResponse(BaseModel):
    snapshot: ReviewSnapshotResponse
    signal_id: str
    series_id: str
    origin: dt.date
    target: ForecastTarget
    org_code: str
    region_code: str
    profile_code: str
    outcomes: list[ScenarioOutcomeResponse]


class AlternativeSetSummaryResponse(BaseModel):
    set_id: str
    canonical_unit_id: str
    origin: dt.date
    target: ForecastTarget
    donor: DonorRef
    budget: float
    abstained: bool
    abstention_codes: list[str]
    receiver_candidates_considered: int
    receiver_candidates_eligible: int
    donor_minimum_transfer_fraction: float | None
    alternative_count: int
    publication_identity_sha256: str


class AlternativeSetResponse(AlternativeSetRow):
    publication_identity_sha256: str
    source_provenance: dict[str, SourceProvenance]


class SignalDecisionAlternativesResponse(BaseModel):
    snapshot: ReviewSnapshotResponse
    signal_id: str
    sets: list[AlternativeSetResponse]
