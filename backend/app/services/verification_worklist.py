"""Publish and query the backend-owned verification worklist read model.

Every response this module builds carries `decision_owner` and `not_a_decision`, because the framing is the part
most easily lost: a list of records to check is one screenshot away from being read as a list of people to strike
off. The parser refuses a bundle that drops either, the DTOs repeat them on every row, and the service never
serves a worklist row without them.

The measured queue is never modified or filtered by anything here. It is only read, to attach the registration
date and the operational code a bureau needs to find the paper record.
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

from app.db.models import (
    VerificationWorklistArea,
    VerificationWorklistItem,
    VerificationWorklistSnapshot,
)
from app.repositories import verification_worklist as repository
from app.repositories import waiting_list as waiting_repository
from app.schemas.verification_worklist import (
    AreaRow,
    HistoryQuality,
    LegacyRule,
    LocalisedText,
    RankingRule,
    SourcePublication,
    VerificationWorklistBundle,
    VerificationWorklistPublicationResponse,
    WorklistAreaResponse,
    WorklistCounts,
    WorklistHospitalResponse,
    WorklistItem,
    WorklistItemResponse,
    YieldCurve,
)
from app.services.common import ConflictError, NotFoundError, ValidationError


@dataclass(frozen=True)
class ParsedVerificationWorklistBundle:
    bundle: VerificationWorklistBundle
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


def _identity_projection(bundle: VerificationWorklistBundle) -> dict[str, Any]:
    payload = bundle.model_dump(mode="json")
    payload.pop("publication_identity_sha256", None)
    payload.pop("generated_at", None)
    return payload


def identity_of(bundle: VerificationWorklistBundle) -> str:
    """The canonical identity of a bundle's content, independent of when it was generated."""
    return hashlib.sha256(_canonical_bytes(_identity_projection(bundle))).hexdigest()


def parse_bundle(raw: bytes) -> ParsedVerificationWorklistBundle:
    try:
        value = json.loads(raw, object_pairs_hook=_reject_duplicate_json_keys)
        bundle = VerificationWorklistBundle.model_validate(value)
        computed_identity = identity_of(bundle)
    except (UnicodeDecodeError, json.JSONDecodeError, PydanticValidationError, TypeError, ValueError) as exc:
        raise ValidationError(f"invalid verification-worklist bundle: {exc}") from exc
    if computed_identity != bundle.publication_identity_sha256:
        raise ValidationError(
            "invalid verification-worklist bundle: publication_identity_sha256 does not match canonical content"
        )
    return ParsedVerificationWorklistBundle(bundle=bundle, bundle_sha256=hashlib.sha256(raw).hexdigest())


def load_bundle(path: Path) -> ParsedVerificationWorklistBundle:
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise ValidationError(f"cannot read verification-worklist bundle {path}: {exc}") from exc
    return parse_bundle(raw)


def _area_row(snapshot_id: int, source: AreaRow) -> VerificationWorklistArea:
    return VerificationWorklistArea(
        snapshot_id=snapshot_id,
        level=source.level,
        code=source.code,
        region_code=source.region_code,
        formal_queue_count=source.formal_queue_count,
        history_quality_warning_count=source.history_quality_warning_count,
        history_quality_warning_share=source.history_quality_warning_share,
    )


def _item_row(snapshot_id: int, source: WorklistItem) -> VerificationWorklistItem:
    return VerificationWorklistItem(
        snapshot_id=snapshot_id,
        referral_id=source.referral_id,
        rank=source.rank,
        org_code=source.org_code,
        region_code=source.region_code,
        profile_code=source.profile_code,
        days_waited_at_origin=source.days_waited_at_origin,
        probability_admitted_30d=source.probability_admitted_30d,
        probability_admitted_horizon=source.probability_admitted_horizon,
        probability_ever_admitted=source.probability_ever_admitted,
        observable_curve_end_day=source.observable_curve_end_day,
        estimate_tier=source.estimate_tier,
        verification_priority_score=source.verification_priority_score,
        comparable_training_at_risk_rows=source.comparable_training_at_risk_rows,
        history_quality_warning=source.history_quality_warning,
        history_quality_reason_code=source.history_quality_reason_code,
    )


def publish(session: Session, parsed: ParsedVerificationWorklistBundle) -> PublicationResult:
    """Atomically publish one validated worklist and switch the current snapshot."""
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
            session.execute(update(VerificationWorklistSnapshot).values(is_active=False))
            by_id.is_active = True
            return PublicationResult(
                snapshot_id=by_id.id,
                publication_id=by_id.publication_id,
                publication_identity_sha256=by_id.publication_identity_sha256,
                created=False,
            )
        if by_identity is not None:
            raise ConflictError("publication identity is already attached to a different publication_id")

        session.execute(update(VerificationWorklistSnapshot).values(is_active=False))
        snapshot = VerificationWorklistSnapshot(
            publication_id=bundle.publication_id,
            schema_version=bundle.schema_version,
            contract_version=bundle.contract_version,
            publication_identity_sha256=bundle.publication_identity_sha256,
            bundle_sha256=parsed.bundle_sha256,
            source_code_commit=bundle.source_code_commit,
            origin=bundle.origin,
            generated_at=bundle.generated_at,
            is_active=True,
            decision_owner=bundle.decision_owner,
            not_a_decision=bundle.not_a_decision.model_dump(mode="json"),
            source_publication=bundle.source_publication.model_dump(mode="json"),
            ranking=bundle.ranking.model_dump(mode="json"),
            legacy_rule=bundle.legacy_rule.model_dump(mode="json"),
            history_quality=bundle.history_quality.model_dump(mode="json"),
            estimands=dict(bundle.estimands),
            counts=bundle.counts.model_dump(mode="json"),
            yield_curve=bundle.yield_curve.model_dump(mode="json"),
            limitations=bundle.limitations,
        )
        session.add(snapshot)
        session.flush()
        session.add_all(_area_row(snapshot.id, row) for row in bundle.areas)
        session.add_all(_item_row(snapshot.id, row) for row in bundle.items)
        snapshot_id = snapshot.id
    return PublicationResult(
        snapshot_id=snapshot_id,
        publication_id=bundle.publication_id,
        publication_identity_sha256=bundle.publication_identity_sha256,
        created=True,
    )


# ---------------------------------------------------------------------------------------------- reads


def _require_snapshot(session: Session) -> VerificationWorklistSnapshot:
    snapshot = repository.current_snapshot(session)
    if snapshot is None:
        raise NotFoundError("no verification-worklist publication is active")
    return snapshot


def _framing(snapshot: VerificationWorklistSnapshot) -> dict[str, Any]:
    """The four fields every response repeats. Dropping any of them turns a review list into something else."""
    return {
        "publication_id": snapshot.publication_id,
        "publication_identity_sha256": snapshot.publication_identity_sha256,
        "origin": snapshot.origin,
        "decision_owner": snapshot.decision_owner,
        "not_a_decision": LocalisedText.model_validate(snapshot.not_a_decision),
    }


def publication_response(session: Session) -> VerificationWorklistPublicationResponse:
    row = _require_snapshot(session)
    return VerificationWorklistPublicationResponse(
        publication_id=row.publication_id,
        schema_version=row.schema_version,
        contract_version=row.contract_version,
        publication_identity_sha256=row.publication_identity_sha256,
        bundle_sha256=row.bundle_sha256,
        source_code_commit=row.source_code_commit,
        origin=row.origin,
        published_at=row.published_at,
        generated_at=row.generated_at,
        decision_owner=row.decision_owner,
        not_a_decision=LocalisedText.model_validate(row.not_a_decision),
        source_publication=SourcePublication.model_validate(row.source_publication),
        ranking=RankingRule.model_validate(row.ranking),
        legacy_rule=LegacyRule.model_validate(row.legacy_rule),
        history_quality=HistoryQuality.model_validate(row.history_quality),
        estimands=dict(row.estimands),
        counts=WorklistCounts.model_validate(row.counts),
        yield_curve=YieldCurve.model_validate(row.yield_curve),
        limitations=list(row.limitations),
    )


def _area_response(row: VerificationWorklistArea, name: str | None) -> WorklistAreaResponse:
    return WorklistAreaResponse(
        level=row.level,
        code=row.code,
        name=name or row.code,
        region_code=row.region_code,
        formal_queue_count=row.formal_queue_count,
        history_quality_warning_count=row.history_quality_warning_count,
        history_quality_warning_share=row.history_quality_warning_share,
    )


def list_regions(session: Session) -> list[WorklistAreaResponse]:
    """The region view: each region's formal queue and how much of it rests on thin comparable history."""
    snapshot = _require_snapshot(session)
    return [_area_response(row, name) for row, name in repository.areas(session, snapshot.id, "region")]


def hospital_worklist(
    session: Session,
    org_code: str,
    *,
    warning: bool | None = None,
    order: str = "rank",
    limit: int,
    offset: int,
) -> WorklistHospitalResponse:
    """One hospital's part of the verification order, ranked, with its own and its region's counts beside it."""
    snapshot = _require_snapshot(session)
    hospital = repository.area(session, snapshot.id, "hospital", org_code)
    if hospital is None:
        raise NotFoundError(f"hospital {org_code!r} is not in the current verification worklist publication")
    registry = repository.organization_name(session, org_code)
    org_name = registry[0] if registry else org_code
    region_code = hospital.region_code or (registry[1] if registry else "")
    region_name = registry[2] if registry and registry[2] else region_code
    region = repository.area(session, snapshot.id, "region", region_code)

    # the queue is read, never filtered: it only supplies the registration date and the operational code
    waiting = waiting_repository.current_snapshot(session)
    waiting_id = waiting.id if waiting is not None and waiting.origin == snapshot.origin else None

    total = repository.count_items(session, snapshot.id, org_code, waiting_id, warning=warning)
    rows = repository.items(
        session,
        snapshot.id,
        org_code,
        waiting_id,
        warning=warning,
        order=order,
        limit=limit,
        offset=offset,
    )
    framing = _framing(snapshot)
    horizon = int(snapshot.legacy_rule["horizon_days"])
    items = [
        WorklistItemResponse(
            **framing,
            referral_id=item.referral_id,
            rank=item.rank,
            org_code=item.org_code,
            region_code=item.region_code,
            profile_code=item.profile_code,
            profile_name=profile_name or item.profile_code,
            days_waited_at_origin=item.days_waited_at_origin,
            registration_date=registration_date,
            hospitalization_code=hospitalization_code,
            probability_admitted_30d=item.probability_admitted_30d,
            probability_admitted_horizon=item.probability_admitted_horizon,
            horizon_days=horizon,
            estimate_tier=item.estimate_tier,
            verification_priority_score=item.verification_priority_score,
            comparable_training_at_risk_rows=item.comparable_training_at_risk_rows,
            history_quality_warning=item.history_quality_warning,
            history_quality_reason_code=item.history_quality_reason_code,
        )
        for item, profile_name, registration_date, hospitalization_code in rows
    ]
    return WorklistHospitalResponse(
        **framing,
        org_code=org_code,
        org_name=org_name,
        region_code=region_code,
        region_name=region_name,
        formal_queue_count=hospital.formal_queue_count,
        history_quality_warning_count=hospital.history_quality_warning_count,
        history_quality_warning_share=hospital.history_quality_warning_share,
        region=_area_response(region, region_name)
        if region is not None
        else WorklistAreaResponse(
            level="region",
            code=region_code,
            name=region_name,
            region_code=None,
            formal_queue_count=hospital.formal_queue_count,
            history_quality_warning_count=hospital.history_quality_warning_count,
            history_quality_warning_share=hospital.history_quality_warning_share,
        ),
        items=items,
        total=total,
        limit=limit,
        offset=offset,
    )
