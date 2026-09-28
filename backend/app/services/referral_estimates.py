"""Publish and query the backend-owned per-referral estimate read model.

This is the only place in the product that serves a model number attached to a single referral, and it serves it
next to the measured queue row without ever mixing the two: each half of a row carries its own publication id and
identity, so a screenshot of the table is still attributable months later.

Read-time safety: the estimates only join onto the queue when both active publications stand at the same origin.
A mismatch is not an error — the measured queue still answers — but the estimate column goes empty rather than
lining up one day's model output against another day's queue.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import ValidationError as PydanticValidationError
from sqlalchemy import update
from sqlalchemy.orm import Session

from app.db.models import ReferralEstimate, ReferralEstimateSnapshot, WaitingListReferral
from app.repositories import referral_estimates as repository
from app.repositories import waiting_list as waiting_repository
from app.schemas.common import Page
from app.schemas.referral_estimates import (
    HINDSIGHT_DISCLOSURE,
    AttentionRule,
    Calibration,
    DegeneracyRule,
    ModelSelection,
    QueueReferralResponse,
    ReferralEstimateResponse,
    ReferralEstimateRow,
    ReferralEstimatesBundle,
    ReferralEstimatesPublicationResponse,
    SourceRun,
)
from app.schemas.waiting_list import ObservedAfterOrigin
from app.services.common import ConflictError, NotFoundError, ValidationError


@dataclass(frozen=True)
class ParsedReferralEstimatesBundle:
    bundle: ReferralEstimatesBundle
    bundle_sha256: str


@dataclass(frozen=True)
class PublicationResult:
    snapshot_id: int
    publication_id: str
    publication_identity_sha256: str
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


def _identity_projection(bundle: ReferralEstimatesBundle) -> dict[str, Any]:
    payload = bundle.model_dump(mode="json")
    payload.pop("publication_identity_sha256", None)
    payload.pop("generated_at", None)
    return payload


def identity_of(bundle: ReferralEstimatesBundle) -> str:
    """The canonical identity of a bundle's content, independent of when it was generated."""
    return hashlib.sha256(_canonical_bytes(_identity_projection(bundle))).hexdigest()


def parse_bundle(raw: bytes) -> ParsedReferralEstimatesBundle:
    try:
        value = json.loads(raw, object_pairs_hook=_reject_duplicate_json_keys)
        bundle = ReferralEstimatesBundle.model_validate(value)
        computed_identity = identity_of(bundle)
    except (UnicodeDecodeError, json.JSONDecodeError, PydanticValidationError, TypeError, ValueError) as exc:
        raise ValidationError(f"invalid referral-estimates bundle: {exc}") from exc
    if computed_identity != bundle.publication_identity_sha256:
        raise ValidationError(
            "invalid referral-estimates bundle: publication_identity_sha256 does not match canonical content"
        )
    return ParsedReferralEstimatesBundle(bundle=bundle, bundle_sha256=hashlib.sha256(raw).hexdigest())


def load_bundle(path: Path) -> ParsedReferralEstimatesBundle:
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise ValidationError(f"cannot read referral-estimates bundle {path}: {exc}") from exc
    return parse_bundle(raw)


def _estimate_row(snapshot_id: int, source: ReferralEstimateRow) -> ReferralEstimate:
    return ReferralEstimate(
        snapshot_id=snapshot_id,
        referral_id=source.referral_id,
        org_code=source.org_code,
        profile_code=source.profile_code,
        estimate_tier=source.estimate_tier,
        similar_training_rows=source.similar_training_rows,
        admitted_7d=source.admitted_7d,
        admitted_14d=source.admitted_14d,
        admitted_30d=source.admitted_30d,
        refused_30d=source.refused_30d,
        window_lower_days=source.window_lower_days,
        window_upper_days=source.window_upper_days,
        abstention_reason=source.abstention_reason,
        refusal_attention=source.refusal_attention,
        degenerate_30d=source.degenerate_30d,
    )


def publish(session: Session, parsed: ParsedReferralEstimatesBundle) -> PublicationResult:
    """Atomically publish one validated estimate set and switch the current snapshot."""
    bundle = parsed.bundle
    with session.begin():
        repository.current_snapshot(session, for_update=True)
        by_id = repository.snapshot_by_publication_id(session, bundle.publication_id)
        by_identity = repository.snapshot_by_identity(session, bundle.publication_identity_sha256)
        if by_id is not None:
            if by_id.publication_identity_sha256 != bundle.publication_identity_sha256:
                raise ConflictError(
                    f"publication_id {bundle.publication_id!r} is already published with a different identity"
                )
            if by_identity is not None and by_identity.id != by_id.id:
                raise ConflictError("publication identity is already attached to a different publication_id")
            session.execute(update(ReferralEstimateSnapshot).values(is_active=False))
            by_id.is_active = True
            return PublicationResult(
                snapshot_id=by_id.id,
                publication_id=by_id.publication_id,
                publication_identity_sha256=by_id.publication_identity_sha256,
                created=False,
            )
        if by_identity is not None:
            raise ConflictError("publication identity is already attached to a different publication_id")

        session.execute(update(ReferralEstimateSnapshot).values(is_active=False))
        snapshot = ReferralEstimateSnapshot(
            publication_id=bundle.publication_id,
            schema_version=bundle.schema_version,
            contract_version=bundle.contract_version,
            publication_identity_sha256=bundle.publication_identity_sha256,
            bundle_sha256=parsed.bundle_sha256,
            source_code_commit=bundle.source_code_commit,
            origin=bundle.origin,
            outcome_cutoff=bundle.outcome_cutoff,
            generated_at=bundle.generated_at,
            is_active=True,
            referral_count=len(bundle.referrals),
            horizons=list(bundle.horizons),
            admission_window_coverage=bundle.admission_window_coverage,
            source_run=bundle.source_run.model_dump(mode="json"),
            selection=bundle.selection.model_dump(mode="json"),
            calibration=bundle.calibration.model_dump(mode="json"),
            estimate_tiers=dict(bundle.estimate_tiers),
            abstention_counts=dict(bundle.abstention_counts),
            degeneracy=bundle.degeneracy.model_dump(mode="json"),
            attention=bundle.attention.model_dump(mode="json"),
            limitations=bundle.limitations,
        )
        session.add(snapshot)
        session.flush()
        session.add_all(_estimate_row(snapshot.id, row) for row in bundle.referrals)
        snapshot_id = snapshot.id
    return PublicationResult(
        snapshot_id=snapshot_id,
        publication_id=bundle.publication_id,
        publication_identity_sha256=bundle.publication_identity_sha256,
        created=True,
    )


# ---------------------------------------------------------------------------------------------- reads


def _require_snapshot(session: Session) -> ReferralEstimateSnapshot:
    snapshot = repository.current_snapshot(session)
    if snapshot is None:
        raise NotFoundError("no referral-estimates publication is active")
    return snapshot


def _joinable_snapshot(session: Session, waiting_origin: object) -> ReferralEstimateSnapshot | None:
    """The active estimate publication, but only when it stands at the queue's origin (see the module docstring)."""
    snapshot = repository.current_snapshot(session)
    if snapshot is None or snapshot.origin != waiting_origin:
        return None
    return snapshot


def publication_response(session: Session) -> ReferralEstimatesPublicationResponse:
    row = _require_snapshot(session)
    waiting = waiting_repository.current_snapshot(session)
    return ReferralEstimatesPublicationResponse(
        publication_id=row.publication_id,
        schema_version=row.schema_version,
        contract_version=row.contract_version,
        publication_identity_sha256=row.publication_identity_sha256,
        bundle_sha256=row.bundle_sha256,
        source_code_commit=row.source_code_commit,
        origin=row.origin,
        outcome_cutoff=row.outcome_cutoff,
        published_at=row.published_at,
        generated_at=row.generated_at,
        referral_count=row.referral_count,
        horizons=list(row.horizons),
        admission_window_coverage=row.admission_window_coverage,
        source_run=SourceRun.model_validate(row.source_run),
        selection=ModelSelection.model_validate(row.selection),
        calibration=Calibration.model_validate(row.calibration),
        estimate_tiers=dict(row.estimate_tiers),
        abstention_counts=dict(row.abstention_counts),
        degeneracy=DegeneracyRule.model_validate(row.degeneracy),
        attention=AttentionRule.model_validate(row.attention),
        limitations=list(row.limitations),
        matches_waiting_list=waiting is not None and waiting.origin == row.origin,
    )


def _estimate_response(
    snapshot: ReferralEstimateSnapshot, row: ReferralEstimate | None
) -> ReferralEstimateResponse | None:
    if row is None:
        return None
    return ReferralEstimateResponse(
        publication_id=snapshot.publication_id,
        publication_identity_sha256=snapshot.publication_identity_sha256,
        origin=snapshot.origin,
        selected_model=snapshot.selection["selected_model"],
        estimate_tier=row.estimate_tier,
        similar_training_rows=row.similar_training_rows,
        admitted_7d=row.admitted_7d,
        admitted_14d=row.admitted_14d,
        admitted_30d=row.admitted_30d,
        refused_30d=row.refused_30d,
        still_waiting_30d=max(0.0, 1.0 - row.admitted_30d - row.refused_30d),
        window_lower_days=row.window_lower_days,
        window_upper_days=row.window_upper_days,
        window_coverage=snapshot.admission_window_coverage,
        abstention_reason=row.abstention_reason,
        refusal_attention=row.refusal_attention,
        degenerate_30d=row.degenerate_30d,
    )


def _queue_response(
    waiting: object,
    estimates: ReferralEstimateSnapshot | None,
    row: WaitingListReferral,
    profile_name: str | None,
    estimate: ReferralEstimate | None,
) -> QueueReferralResponse:
    return QueueReferralResponse(
        publication_id=waiting.publication_id,
        publication_identity_sha256=waiting.publication_identity_sha256,
        origin=waiting.origin,
        referral_id=row.referral_id,
        hospitalization_code=row.hospitalization_code,
        is_duplicate_code=row.is_duplicate_code,
        org_code=row.org_code,
        region_code=row.region_code,
        patient_region_code=row.patient_region_code,
        profile_code=row.profile_code,
        profile_name=profile_name or row.profile_code,
        registration_date=row.registration_date,
        days_waited_at_origin=row.days_waited_at_origin,
        observed_after_origin=ObservedAfterOrigin(
            disclosure=HINDSIGHT_DISCLOSURE,
            status=row.observed_status,
            event_date=row.observed_event_date,
            days_from_origin=row.observed_days_from_origin,
        ),
        estimate=None if estimates is None else _estimate_response(estimates, estimate),
    )


def list_queue(
    session: Session,
    org_code: str,
    *,
    profile_code: str | None = None,
    order: str = "longest_wait",
    attention_only: bool = False,
    limit: int,
    offset: int,
) -> Page[QueueReferralResponse]:
    """One hospital's measured queue with the origin-time estimate of each referral beside it."""
    waiting = waiting_repository.current_snapshot(session)
    if waiting is None:
        raise NotFoundError("no waiting-list publication is active")
    if waiting_repository.hospital(session, waiting.id, org_code) is None:
        raise NotFoundError(f"hospital {org_code!r} has no waiting referrals in the current publication")
    estimates = _joinable_snapshot(session, waiting.origin)
    if estimates is None and (attention_only or order == "highest_refusal_risk"):
        raise NotFoundError("no referral-estimates publication stands at the origin of the current waiting list")
    estimate_snapshot_id = None if estimates is None else estimates.id

    total = repository.count_queue(
        session,
        waiting.id,
        estimate_snapshot_id,
        org_code,
        profile_code=profile_code,
        attention_only=attention_only,
    )
    rows = repository.queue(
        session,
        waiting.id,
        estimate_snapshot_id,
        org_code,
        profile_code=profile_code,
        attention_only=attention_only,
        order=order,
        limit=limit,
        offset=offset,
    )
    items = [_queue_response(waiting, estimates, row, profile_name, estimate) for row, profile_name, estimate in rows]
    return Page(items=items, total=total, limit=limit, offset=offset)
