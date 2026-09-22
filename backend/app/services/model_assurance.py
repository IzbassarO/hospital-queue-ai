"""Publish and query the backend-owned Model Assurance read model."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import ValidationError as PydanticValidationError
from sqlalchemy import update
from sqlalchemy.orm import Session

from app.db.models import ModelAssuranceCapability, ModelAssuranceSnapshot
from app.repositories import model_assurance as repository
from app.schemas.model_assurance import (
    AssuranceCapabilityBundle,
    AssuranceIdentityRecord,
    ModelAssuranceBundle,
    ModelAssuranceCapabilityResponse,
    ModelAssuranceSnapshotResponse,
)
from app.services.common import ConflictError, NotFoundError, ValidationError


@dataclass(frozen=True)
class ParsedAssuranceBundle:
    bundle: ModelAssuranceBundle
    bundle_sha256: str


@dataclass(frozen=True)
class PublicationResult:
    snapshot_id: int
    assurance_id: str
    assurance_identity_sha256: str
    created: bool


def _reject_duplicate_json_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key {key!r}")
        result[key] = value
    return result


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":")).encode()


def _identity_projection(bundle: ModelAssuranceBundle) -> dict[str, Any]:
    payload = bundle.model_dump(mode="json")
    payload.pop("assurance_identity_sha256", None)
    payload.pop("generated_at", None)
    return payload


def parse_assurance_bundle(raw: bytes) -> ParsedAssuranceBundle:
    try:
        value = json.loads(raw, object_pairs_hook=_reject_duplicate_json_keys)
        bundle = ModelAssuranceBundle.model_validate(value)
        computed_identity = hashlib.sha256(_canonical_bytes(_identity_projection(bundle))).hexdigest()
    except (UnicodeDecodeError, json.JSONDecodeError, PydanticValidationError, TypeError, ValueError) as exc:
        raise ValidationError(f"invalid Model Assurance bundle: {exc}") from exc
    if computed_identity != bundle.assurance_identity_sha256:
        raise ValidationError(
            "invalid Model Assurance bundle: assurance_identity_sha256 does not match canonical content"
        )
    return ParsedAssuranceBundle(bundle=bundle, bundle_sha256=hashlib.sha256(raw).hexdigest())


def load_assurance_bundle(path: Path) -> ParsedAssuranceBundle:
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise ValidationError(f"cannot read Model Assurance bundle {path}: {exc}") from exc
    return parse_assurance_bundle(raw)


def _available(record: AssuranceIdentityRecord) -> str | list[str] | None:
    return record.value if record.status == "AVAILABLE" else None


def _scalar(record: AssuranceIdentityRecord) -> str | None:
    value = _available(record)
    return value if isinstance(value, str) else None


def _capability_row(snapshot_id: int, source: AssuranceCapabilityBundle) -> ModelAssuranceCapability:
    identities = source.identities
    return ModelAssuranceCapability(
        snapshot_id=snapshot_id,
        capability_id=source.capability_id,
        display_name=source.display_name,
        evidence_status=source.evidence_status,
        acceptance_verdict=source.acceptance_verdict,
        product_consumption_status=source.product_consumption_status,
        run_id=_scalar(identities.run_id),
        scientific_identity_sha256=_scalar(identities.scientific_identity_sha256),
        artifact_identity=_available(identities.artifact_sha256),
        dataset_identity_sha256=_scalar(identities.dataset_identity_sha256),
        config_identity_sha256=_scalar(identities.config_identity_sha256),
        code_identity_sha256=_scalar(identities.code_identity_sha256),
        model_identity=_available(identities.model_identity),
        estimand_id=_scalar(identities.estimand_id),
        calibration_identity=_scalar(identities.calibration_identity),
        hierarchy_identity=_scalar(identities.hierarchy_identity),
        pressure_provider_identity=_scalar(identities.pressure_provider_identity),
        prioritization_identity=_scalar(identities.prioritization_identity),
        scenario_identity=_scalar(identities.scenario_identity),
        decision_alternative_identity=_scalar(identities.decision_alternative_identity),
        human_review_required=source.governance.human_review_required,
        autonomous_action=source.governance.autonomous_action,
        capacity_checked=source.governance.capacity_checked,
        causal_effect_claimed=source.governance.causal_effect_claimed,
        serving_claim=source.governance.serving_claim,
        physical_feasibility_status=source.governance.physical_feasibility_status,
        promotion_status=source.governance.promotion_status,
        freshness_state=source.freshness.state,
        details={
            "identities": source.identities.model_dump(mode="json"),
            "evidence": source.evidence,
            "source_lineage": source.source_lineage,
            "support": source.support.model_dump(mode="json"),
            "limitations": source.limitations,
            "allowed_claims": source.allowed_claims,
            "forbidden_claims": source.forbidden_claims,
            "monitoring_metadata": [],
            "freshness_reason": source.freshness.reason,
        },
    )


def publish(session: Session, parsed: ParsedAssuranceBundle) -> PublicationResult:
    """Atomically insert and activate a validated snapshot, or return an idempotent replay."""
    bundle = parsed.bundle
    with session.begin():
        repository.current_snapshot(session, for_update=True)
        by_id = repository.snapshot_by_assurance_id(session, bundle.assurance_id)
        by_identity = repository.snapshot_by_identity(session, bundle.assurance_identity_sha256)
        if by_id is not None:
            if by_id.assurance_identity_sha256 != bundle.assurance_identity_sha256:
                raise ConflictError(
                    f"assurance_id {bundle.assurance_id!r} is already published with a different identity"
                )
            if by_identity is not None and by_identity.id != by_id.id:
                raise ConflictError("assurance identity is already attached to a different assurance_id")
            session.execute(update(ModelAssuranceSnapshot).values(is_active=False))
            by_id.is_active = True
            return PublicationResult(
                snapshot_id=by_id.id,
                assurance_id=by_id.assurance_id,
                assurance_identity_sha256=by_id.assurance_identity_sha256,
                created=False,
            )
        if by_identity is not None:
            raise ConflictError("assurance identity is already attached to a different assurance_id")

        session.execute(update(ModelAssuranceSnapshot).values(is_active=False))
        snapshot = ModelAssuranceSnapshot(
            assurance_id=bundle.assurance_id,
            contract_version=bundle.contract_version,
            schema_version=bundle.schema_version,
            assurance_identity_sha256=bundle.assurance_identity_sha256,
            bundle_sha256=parsed.bundle_sha256,
            source_code_commit=bundle.source_code_commit,
            ml_freeze_status=bundle.ml_freeze_status,
            product_contract_version=bundle.product_contract_version,
            generated_at=bundle.generated_at,
            is_active=True,
            capability_count=len(bundle.capabilities),
            failed_evidence_history=bundle.failed_evidence_history,
            claim_boundaries=bundle.claim_boundaries,
            monitoring_expectations=bundle.monitoring_expectations,
            freshness_policy=bundle.freshness_policy,
        )
        session.add(snapshot)
        session.flush()
        session.add_all(_capability_row(snapshot.id, capability) for capability in bundle.capabilities)
        snapshot_id = snapshot.id
    return PublicationResult(
        snapshot_id=snapshot_id,
        assurance_id=bundle.assurance_id,
        assurance_identity_sha256=bundle.assurance_identity_sha256,
        created=True,
    )


def _snapshot_response(row: ModelAssuranceSnapshot) -> ModelAssuranceSnapshotResponse:
    return ModelAssuranceSnapshotResponse(
        assurance_id=row.assurance_id,
        contract_version=row.contract_version,
        schema_version=row.schema_version,
        assurance_identity_sha256=row.assurance_identity_sha256,
        bundle_sha256=row.bundle_sha256,
        source_code_commit=row.source_code_commit,
        ml_freeze_status=row.ml_freeze_status,
        product_contract_version=row.product_contract_version,
        generated_at=row.generated_at,
        published_at=row.published_at,
        is_active=row.is_active,
        capability_count=row.capability_count,
        failed_evidence_history=row.failed_evidence_history,
        claim_boundaries=row.claim_boundaries,
        monitoring_expectations=row.monitoring_expectations,
        freshness_policy=row.freshness_policy,
    )


def _capability_response(row: ModelAssuranceCapability) -> ModelAssuranceCapabilityResponse:
    details = row.details
    return ModelAssuranceCapabilityResponse(
        capability_id=row.capability_id,
        display_name=row.display_name,
        evidence_status=row.evidence_status,
        acceptance_verdict=row.acceptance_verdict,
        product_consumption_status=row.product_consumption_status,
        identities=details["identities"],
        support=details["support"],
        governance={
            "human_review_required": row.human_review_required,
            "autonomous_action": row.autonomous_action,
            "capacity_checked": row.capacity_checked,
            "causal_effect_claimed": row.causal_effect_claimed,
            "serving_claim": row.serving_claim,
            "physical_feasibility_status": row.physical_feasibility_status,
            "promotion_status": row.promotion_status,
        },
        freshness={"state": row.freshness_state, "reason": details["freshness_reason"]},
        evidence=details["evidence"],
        limitations=details["limitations"],
        allowed_claims=details["allowed_claims"],
        forbidden_claims=details["forbidden_claims"],
    )


def current(session: Session) -> ModelAssuranceSnapshotResponse:
    row = repository.current_snapshot(session)
    if row is None:
        raise NotFoundError("no current Model Assurance snapshot is published")
    return _snapshot_response(row)


def list_current_capabilities(session: Session) -> list[ModelAssuranceCapabilityResponse]:
    snapshot = repository.current_snapshot(session)
    if snapshot is None:
        raise NotFoundError("no current Model Assurance snapshot is published")
    return [_capability_response(row) for row in repository.capabilities(session, snapshot.id)]


def get_current_capability(session: Session, capability_id: str) -> ModelAssuranceCapabilityResponse:
    snapshot = repository.current_snapshot(session)
    if snapshot is None:
        raise NotFoundError("no current Model Assurance snapshot is published")
    row = repository.capability(session, snapshot.id, capability_id)
    if row is None:
        raise NotFoundError(f"unknown current Model Assurance capability {capability_id!r}")
    return _capability_response(row)
