"""Publish and query the backend-owned waiting-list read model.

The publication is measured data: the queue as it stood at the end of one origin day, and — in a separate field
marked on every row — the outcome the source data recorded afterwards. Nothing here scores, ranks or predicts, and
`carries_model_output` is a literal false the parser enforces, so a bundle that ever grew a model column would be
rejected rather than served quietly.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import ValidationError as PydanticValidationError
from sqlalchemy import update
from sqlalchemy.orm import Session

from app.db.models import WaitingListHospital, WaitingListReferral, WaitingListSnapshot
from app.repositories import waiting_list as repository
from app.schemas.common import Page
from app.schemas.waiting_list import (
    HINDSIGHT_DISCLOSURE,
    CohortDefinition,
    ObservedAfterOrigin,
    ObservedAfterOriginCounts,
    SupportThresholds,
    WaitingDaysBucket,
    WaitingHospitalDetailResponse,
    WaitingHospitalResponse,
    WaitingHospitalRow,
    WaitingListBundle,
    WaitingListSnapshotResponse,
    WaitingProfileBreakdown,
    WaitingReferralResponse,
    WaitingReferralRow,
)
from app.services import transparency
from app.services.common import ConflictError, NotFoundError, ValidationError


@dataclass(frozen=True)
class ParsedWaitingListBundle:
    bundle: WaitingListBundle
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


def _identity_projection(bundle: WaitingListBundle) -> dict[str, Any]:
    payload = bundle.model_dump(mode="json")
    payload.pop("publication_identity_sha256", None)
    payload.pop("generated_at", None)
    return payload


def identity_of(bundle: WaitingListBundle) -> str:
    """The canonical identity of a bundle's content, independent of when it was generated."""
    return hashlib.sha256(_canonical_bytes(_identity_projection(bundle))).hexdigest()


def parse_bundle(raw: bytes) -> ParsedWaitingListBundle:
    try:
        value = json.loads(raw, object_pairs_hook=_reject_duplicate_json_keys)
        bundle = WaitingListBundle.model_validate(value)
        computed_identity = identity_of(bundle)
    except (UnicodeDecodeError, json.JSONDecodeError, PydanticValidationError, TypeError, ValueError) as exc:
        raise ValidationError(f"invalid waiting-list bundle: {exc}") from exc
    if computed_identity != bundle.publication_identity_sha256:
        raise ValidationError(
            "invalid waiting-list bundle: publication_identity_sha256 does not match canonical content"
        )
    return ParsedWaitingListBundle(bundle=bundle, bundle_sha256=hashlib.sha256(raw).hexdigest())


def load_bundle(path: Path) -> ParsedWaitingListBundle:
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise ValidationError(f"cannot read waiting-list bundle {path}: {exc}") from exc
    return parse_bundle(raw)


def _hospital_row(snapshot_id: int, source: WaitingHospitalRow) -> WaitingListHospital:
    return WaitingListHospital(
        snapshot_id=snapshot_id,
        org_code=source.org_code,
        region_code=source.region_code,
        waiting_count=source.waiting_count,
        profile_count=source.profile_count,
        median_days_waited=source.median_days_waited,
        max_days_waited=source.max_days_waited,
        support_class=source.support_class,
    )


def _referral_row(snapshot_id: int, source: WaitingReferralRow) -> WaitingListReferral:
    observed = source.observed_after_origin
    return WaitingListReferral(
        snapshot_id=snapshot_id,
        referral_id=source.referral_id,
        hospitalization_code=source.hospitalization_code,
        is_duplicate_code=source.is_duplicate_code,
        org_code=source.org_code,
        region_code=source.region_code,
        patient_region_code=source.patient_region_code,
        profile_code=source.profile_code,
        registration_date=source.registration_date,
        days_waited_at_origin=source.days_waited_at_origin,
        observed_status=observed.status,
        observed_event_date=observed.event_date,
        observed_days_from_origin=observed.days_from_origin,
    )


def publish(session: Session, parsed: ParsedWaitingListBundle) -> PublicationResult:
    """Atomically publish one validated waiting list and switch the current snapshot."""
    bundle = parsed.bundle
    with session.begin():
        previous = repository.current_snapshot(session, for_update=True)
        by_id = repository.snapshot_by_publication_id(session, bundle.publication_id)
        by_identity = repository.snapshot_by_identity(session, bundle.publication_identity_sha256)
        if by_id is not None:
            if by_id.publication_identity_sha256 != bundle.publication_identity_sha256:
                raise ConflictError(
                    f"publication_id {bundle.publication_id!r} is already published with a different identity"
                )
            if by_identity is not None and by_identity.id != by_id.id:
                raise ConflictError("publication identity is already attached to a different publication_id")
            session.execute(update(WaitingListSnapshot).values(is_active=False))
            by_id.is_active = True
            transparency.record_activation(session, "waiting_list", previous, by_id)
            return PublicationResult(
                snapshot_id=by_id.id,
                publication_id=by_id.publication_id,
                publication_identity_sha256=by_id.publication_identity_sha256,
                created=False,
            )
        if by_identity is not None:
            raise ConflictError("publication identity is already attached to a different publication_id")

        session.execute(update(WaitingListSnapshot).values(is_active=False))
        snapshot = WaitingListSnapshot(
            publication_id=bundle.publication_id,
            schema_version=bundle.schema_version,
            contract_version=bundle.contract_version,
            publication_identity_sha256=bundle.publication_identity_sha256,
            bundle_sha256=parsed.bundle_sha256,
            source_code_commit=bundle.source_code_commit,
            origin=bundle.origin,
            outcome_cutoff=bundle.outcome_cutoff,
            observed_through=bundle.observed_through,
            generated_at=bundle.generated_at,
            is_active=True,
            hospital_count=len(bundle.hospitals),
            waiting_count=len(bundle.referrals),
            cohort=bundle.cohort.model_dump(mode="json"),
            support_thresholds=bundle.support_thresholds.model_dump(mode="json"),
            limitations=bundle.limitations,
        )
        session.add(snapshot)
        session.flush()
        session.add_all(_hospital_row(snapshot.id, row) for row in bundle.hospitals)
        session.add_all(_referral_row(snapshot.id, row) for row in bundle.referrals)
        session.flush()
        # last, so the ledger lock is held only until this commit (docs/transparency-ledger.md §6)
        transparency.record_publication(session, "waiting_list", previous, snapshot)
        snapshot_id = snapshot.id
    return PublicationResult(
        snapshot_id=snapshot_id,
        publication_id=bundle.publication_id,
        publication_identity_sha256=bundle.publication_identity_sha256,
        created=True,
    )


# ---------------------------------------------------------------------------------------------- reads


def _require_snapshot(session: Session) -> WaitingListSnapshot:
    snapshot = repository.current_snapshot(session)
    if snapshot is None:
        raise NotFoundError("no waiting-list publication is active")
    return snapshot


def snapshot_response(session: Session) -> WaitingListSnapshotResponse:
    row = _require_snapshot(session)
    return WaitingListSnapshotResponse(
        publication_id=row.publication_id,
        schema_version=row.schema_version,
        contract_version=row.contract_version,
        publication_identity_sha256=row.publication_identity_sha256,
        bundle_sha256=row.bundle_sha256,
        source_code_commit=row.source_code_commit,
        origin=row.origin,
        outcome_cutoff=row.outcome_cutoff,
        observed_through=row.observed_through,
        published_at=row.published_at,
        generated_at=row.generated_at,
        carries_model_output=False,
        hospital_count=row.hospital_count,
        waiting_count=row.waiting_count,
        cohort=CohortDefinition.model_validate(row.cohort),
        support_thresholds=SupportThresholds.model_validate(row.support_thresholds),
        limitations=list(row.limitations),
    )


def list_hospitals(
    session: Session,
    *,
    region_code: str | None = None,
    support_class: str | None = None,
    min_waiting: int | None = None,
    limit: int,
    offset: int,
) -> Page[WaitingHospitalResponse]:
    snapshot = _require_snapshot(session)
    total = repository.count_hospitals(
        session, snapshot.id, region_code=region_code, support_class=support_class, min_waiting=min_waiting
    )
    rows = repository.hospitals(
        session,
        snapshot.id,
        region_code=region_code,
        support_class=support_class,
        min_waiting=min_waiting,
        limit=limit,
        offset=offset,
    )
    items = [
        WaitingHospitalResponse(
            publication_id=snapshot.publication_id,
            publication_identity_sha256=snapshot.publication_identity_sha256,
            origin=snapshot.origin,
            org_code=row.org_code,
            org_name=org_name,
            region_code=row.region_code,
            region_name=region_name,
            waiting_count=row.waiting_count,
            profile_count=row.profile_count,
            median_days_waited=row.median_days_waited,
            max_days_waited=row.max_days_waited,
            support_class=row.support_class,
        )
        for row, org_name, region_name in rows
    ]
    return Page(items=items, total=total, limit=limit, offset=offset)


def hospital_detail(session: Session, org_code: str) -> WaitingHospitalDetailResponse:
    """One hospital's queue at the origin: totals, profile breakdown, days-waited histogram and hindsight totals."""
    snapshot = _require_snapshot(session)
    found = repository.hospital(session, snapshot.id, org_code)
    if found is None:
        raise NotFoundError(f"hospital {org_code!r} has no waiting referrals in the current publication")
    row, org_name, region_name = found
    counts = repository.observed_counts(session, snapshot.id, org_code)
    return WaitingHospitalDetailResponse(
        publication_id=snapshot.publication_id,
        publication_identity_sha256=snapshot.publication_identity_sha256,
        origin=snapshot.origin,
        org_code=row.org_code,
        org_name=org_name,
        region_code=row.region_code,
        region_name=region_name,
        waiting_count=row.waiting_count,
        profile_count=row.profile_count,
        median_days_waited=row.median_days_waited,
        max_days_waited=row.max_days_waited,
        support_class=row.support_class,
        profiles=[
            WaitingProfileBreakdown(
                profile_code=code,
                profile_name=name or code,
                waiting_count=waiting,
                median_days_waited=float(median),
                max_days_waited=int(largest),
            )
            for code, name, waiting, median, largest in repository.profile_breakdown(session, snapshot.id, org_code)
        ],
        days_waited_histogram=[
            WaitingDaysBucket(from_days=low, to_days=high, count=count)
            for (low, high), count in zip(
                repository.DAYS_BUCKETS,
                repository.days_waited_histogram(session, snapshot.id, org_code),
                strict=True,
            )
        ],
        observed_after_origin=ObservedAfterOriginCounts(
            disclosure=HINDSIGHT_DISCLOSURE,
            admitted=counts.get("ADMITTED", 0),
            refused=counts.get("REFUSED", 0),
            still_waiting_at_cutoff=counts.get("STILL_WAITING_AT_CUTOFF", 0),
        ),
    )


def list_referrals(
    session: Session,
    org_code: str,
    *,
    profile_code: str | None = None,
    order: str = "longest_wait",
    limit: int,
    offset: int,
) -> Page[WaitingReferralResponse]:
    snapshot = _require_snapshot(session)
    if repository.hospital(session, snapshot.id, org_code) is None:
        raise NotFoundError(f"hospital {org_code!r} has no waiting referrals in the current publication")
    total = repository.count_referrals(session, snapshot.id, org_code, profile_code=profile_code)
    rows = repository.referrals(
        session,
        snapshot.id,
        org_code,
        profile_code=profile_code,
        ascending=order == "shortest_wait",
        limit=limit,
        offset=offset,
    )
    items = [
        WaitingReferralResponse(
            publication_id=snapshot.publication_id,
            publication_identity_sha256=snapshot.publication_identity_sha256,
            origin=snapshot.origin,
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
        )
        for row, profile_name in rows
    ]
    return Page(items=items, total=total, limit=limit, offset=offset)


def build_observation(origin: dt.date, resolution_date: dt.date | None, outcome: str) -> ObservedAfterOrigin:
    """Map one source row's terminal event to the published hindsight field. Shared by the offline builder."""
    if resolution_date is None:
        return ObservedAfterOrigin(disclosure=HINDSIGHT_DISCLOSURE, status="STILL_WAITING_AT_CUTOFF")
    status = "ADMITTED" if outcome == "hospitalized" else "REFUSED"
    return ObservedAfterOrigin(
        disclosure=HINDSIGHT_DISCLOSURE,
        status=status,
        event_date=resolution_date,
        days_from_origin=(resolution_date - origin).days,
    )
