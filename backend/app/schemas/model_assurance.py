"""Backend-owned publication input and candidate-independent Model Assurance API DTOs."""

from __future__ import annotations

import datetime as dt
import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

IdentityStatus = Literal["AVAILABLE", "UNKNOWN", "NOT_APPLICABLE"]
EvidenceStatus = Literal["ACCEPTED", "REJECTED", "EXPERIMENTAL"]
AcceptanceVerdict = Literal["ACCEPT", "ACCEPT_WITH_P2", "DO_NOT_PROMOTE", "NOT_APPLICABLE"]
ProductConsumptionStatus = Literal["ELIGIBLE_AFTER_INGESTION", "EVALUATION_ONLY", "REFERENCE_ONLY", "NOT_FOR_PRODUCT"]
FreshnessState = Literal["FRESH", "STALE", "DEGRADED", "UNKNOWN"]

SHA256_IDENTITY_FIELDS = {
    "scientific_identity_sha256",
    "artifact_sha256",
    "dataset_identity_sha256",
    "config_identity_sha256",
    "code_identity_sha256",
}
SCALAR_IDENTITY_FIELDS = {
    "run_id",
    "scientific_identity_sha256",
    "dataset_identity_sha256",
    "config_identity_sha256",
    "code_identity_sha256",
    "estimand_id",
    "calibration_identity",
    "hierarchy_identity",
    "pressure_provider_identity",
    "prioritization_identity",
    "scenario_identity",
    "decision_alternative_identity",
}


class AssuranceIdentityRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: IdentityStatus
    value: str | list[str] | None
    reason: str = Field(min_length=1)

    @model_validator(mode="after")
    def validate_status_value(self) -> AssuranceIdentityRecord:
        if self.status == "AVAILABLE" and self.value in (None, "", []):
            raise ValueError("AVAILABLE identity requires a value")
        if self.status != "AVAILABLE" and self.value is not None:
            raise ValueError("UNKNOWN and NOT_APPLICABLE identity values must be null")
        return self


class AssuranceIdentities(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: AssuranceIdentityRecord
    scientific_identity_sha256: AssuranceIdentityRecord
    artifact_sha256: AssuranceIdentityRecord
    dataset_identity_sha256: AssuranceIdentityRecord
    config_identity_sha256: AssuranceIdentityRecord
    code_identity_sha256: AssuranceIdentityRecord
    model_identity: AssuranceIdentityRecord
    estimand_id: AssuranceIdentityRecord
    calibration_identity: AssuranceIdentityRecord
    hierarchy_identity: AssuranceIdentityRecord
    pressure_provider_identity: AssuranceIdentityRecord
    prioritization_identity: AssuranceIdentityRecord
    scenario_identity: AssuranceIdentityRecord
    decision_alternative_identity: AssuranceIdentityRecord

    @model_validator(mode="after")
    def validate_identity_shapes(self) -> AssuranceIdentities:
        for field in SCALAR_IDENTITY_FIELDS:
            record = getattr(self, field)
            if record.status == "AVAILABLE" and not isinstance(record.value, str):
                raise ValueError(f"{field} must be scalar when available")
        for field in SHA256_IDENTITY_FIELDS:
            record = getattr(self, field)
            if record.status != "AVAILABLE":
                continue
            values = record.value if isinstance(record.value, list) else [record.value]
            if any(not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{64}", value) is None for value in values):
                raise ValueError(f"{field} contains malformed SHA256")
        return self


class AssuranceSupport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    support_semantics: list[Literal["DIRECT_SUPPORTED", "FALLBACK_LIMITED", "UNSUPPORTED"]]
    range_semantics: list[Literal["COMPLETE", "RANGE_LIMITED"]]


class AssuranceGovernance(BaseModel):
    model_config = ConfigDict(extra="forbid")

    human_review_required: bool
    autonomous_action: bool
    capacity_checked: bool
    causal_effect_claimed: bool
    serving_claim: bool
    physical_feasibility_status: Literal["VALIDATED", "NOT_VALIDATED", "UNKNOWN", "NOT_APPLICABLE"]
    promotion_status: Literal["PROMOTED", "HUMAN_REVIEW_ONLY", "NO_PROMOTION", "NOT_APPLICABLE"]


class AssuranceFreshness(BaseModel):
    model_config = ConfigDict(extra="forbid")

    state: FreshnessState
    reason: str = Field(min_length=1)


class AssuranceCapabilityBundle(BaseModel):
    model_config = ConfigDict(extra="forbid")

    capability_id: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    display_name: str = Field(min_length=1)
    evidence_status: EvidenceStatus
    acceptance_verdict: AcceptanceVerdict
    product_consumption_status: ProductConsumptionStatus
    run_manifest: str | None = None
    identities: AssuranceIdentities
    evidence: dict[str, Any]
    support: AssuranceSupport
    governance: AssuranceGovernance
    freshness: AssuranceFreshness
    source_lineage: list[str]
    limitations: list[str]
    allowed_claims: list[str]
    forbidden_claims: list[str]


class ModelAssuranceBundle(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["model_assurance_v1"]
    contract_version: str = Field(min_length=1)
    assurance_id: str = Field(min_length=1, max_length=128)
    assurance_identity_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_code_commit: str = Field(pattern=r"^[0-9a-f]{40}$")
    ml_freeze_status: Literal["ML_CORE_CLOSED_FROZEN"]
    capabilities: list[AssuranceCapabilityBundle] = Field(min_length=1)
    failed_evidence_history: list[dict[str, Any]]
    claim_boundaries: dict[str, Any]
    monitoring_expectations: list[dict[str, Any]]
    freshness_policy: dict[str, Any]
    product_contract_version: str = Field(min_length=1)
    generated_at: dt.datetime | None = None

    @model_validator(mode="after")
    def unique_capabilities(self) -> ModelAssuranceBundle:
        ids = [capability.capability_id for capability in self.capabilities]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate capability_id")
        return self


class ModelAssuranceCapabilityResponse(BaseModel):
    capability_id: str
    display_name: str
    evidence_status: EvidenceStatus
    acceptance_verdict: AcceptanceVerdict
    product_consumption_status: ProductConsumptionStatus
    identities: AssuranceIdentities
    support: AssuranceSupport
    governance: AssuranceGovernance
    freshness: AssuranceFreshness
    evidence: dict[str, Any]
    limitations: list[str]
    allowed_claims: list[str]
    forbidden_claims: list[str]


class ModelAssuranceSnapshotResponse(BaseModel):
    assurance_id: str
    contract_version: str
    schema_version: str
    assurance_identity_sha256: str
    bundle_sha256: str
    source_code_commit: str
    ml_freeze_status: str
    product_contract_version: str
    generated_at: dt.datetime | None
    published_at: dt.datetime
    is_active: bool
    capability_count: int
    failed_evidence_history: list[dict[str, Any]]
    claim_boundaries: dict[str, Any]
    monitoring_expectations: list[dict[str, Any]]
    freshness_policy: dict[str, Any]
