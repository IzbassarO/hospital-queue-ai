"""Publish and query backend-owned operational-intelligence read models."""

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

from app.db.models import OperationalForecast, OperationalIntelligenceSnapshot, OperationalSignal
from app.repositories import model_assurance as assurance_repository
from app.repositories import operational_intelligence as repository
from app.schemas.common import Page
from app.schemas.operational_intelligence import (
    ForecastPublicationRow,
    OperationalCounts,
    OperationalForecastResponse,
    OperationalHospitalProfileResponse,
    OperationalIntelligenceBundle,
    OperationalOverviewResponse,
    OperationalRegionResponse,
    OperationalRegionSummary,
    OperationalSignalResponse,
    OperationalSnapshotResponse,
    SignalPublicationRow,
)
from app.services.common import ConflictError, NotFoundError, ValidationError


@dataclass(frozen=True)
class ParsedOperationalBundle:
    bundle: OperationalIntelligenceBundle
    bundle_sha256: str


@dataclass(frozen=True)
class PublicationResult:
    snapshot_id: int
    publication_id: str
    publication_identity_sha256: str
    created: bool


ASSURANCE_CAPABILITY_BY_SOURCE = {
    "flow_forecast": "flow_point_forecast",
    "flow_quantile": "flow_quantile_forecast",
    "flow_calibration": "flow_temporal_calibration",
    "flow_hierarchy": "flow_hierarchical_coherence",
    "flow_pressure": "preventive_flow_pressure",
    "signal_prioritization": "signal_prioritization",
}


def _reject_duplicate_json_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key {key!r}")
        result[key] = value
    return result


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":")).encode()


def _identity_projection(bundle: OperationalIntelligenceBundle) -> dict[str, Any]:
    payload = bundle.model_dump(mode="json")
    payload.pop("publication_identity_sha256", None)
    payload.pop("generated_at", None)
    return payload


def parse_bundle(raw: bytes) -> ParsedOperationalBundle:
    try:
        value = json.loads(raw, object_pairs_hook=_reject_duplicate_json_keys)
        bundle = OperationalIntelligenceBundle.model_validate(value)
        computed_identity = hashlib.sha256(_canonical_bytes(_identity_projection(bundle))).hexdigest()
    except (UnicodeDecodeError, json.JSONDecodeError, PydanticValidationError, TypeError, ValueError) as exc:
        raise ValidationError(f"invalid operational-intelligence bundle: {exc}") from exc
    if computed_identity != bundle.publication_identity_sha256:
        raise ValidationError(
            "invalid operational-intelligence bundle: publication_identity_sha256 does not match canonical content"
        )
    return ParsedOperationalBundle(bundle=bundle, bundle_sha256=hashlib.sha256(raw).hexdigest())


def load_bundle(path: Path) -> ParsedOperationalBundle:
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise ValidationError(f"cannot read operational-intelligence bundle {path}: {exc}") from exc
    return parse_bundle(raw)


def _forecast_row(snapshot_id: int, source: ForecastPublicationRow) -> OperationalForecast:
    raw = source.raw_quantiles
    calibrated = source.calibrated_uncertainty
    return OperationalForecast(
        snapshot_id=snapshot_id,
        series_id=source.series_id,
        level=source.level,
        origin=source.origin,
        target_date=source.target_date,
        horizon=source.horizon,
        target=source.target,
        org_code=source.org_code,
        region_code=source.region_code,
        profile_code=source.profile_code,
        central_value=source.central_value,
        central_semantics=source.central_semantics,
        raw_p10=raw.p10 if raw else None,
        raw_p50=raw.p50 if raw else None,
        raw_p90=raw.p90 if raw else None,
        calibrated_lower=calibrated.lower if calibrated else None,
        calibrated_upper=calibrated.upper if calibrated else None,
        calibration_nominal_coverage=calibrated.nominal_coverage if calibrated else None,
        calibration_status=source.calibration_status,
        calibration_support_class=calibrated.support_class if calibrated else None,
        calibration_version=calibrated.calibration_version if calibrated else None,
        prediction_source=source.prediction_source,
        hierarchy_status=source.hierarchy_status,
        support_status=source.support_status,
        fallback_status=source.fallback_status,
        uncertainty_status=source.uncertainty_status,
        provenance_keys=source.provenance_keys,
        details={"evidence_facts": source.evidence_facts, "limitations": source.limitations},
    )


def _signal_row(snapshot_id: int, source: SignalPublicationRow) -> OperationalSignal:
    return OperationalSignal(
        snapshot_id=snapshot_id,
        signal_id=source.signal_id,
        signal_type=source.signal_type,
        series_id=source.series_id,
        origin=source.origin,
        target=source.target,
        org_code=source.org_code,
        region_code=source.region_code,
        profile_code=source.profile_code,
        inbox_rank=source.inbox_rank,
        severity=source.severity,
        headline=source.headline,
        concise_reason=source.concise_reason,
        materiality_status=source.materiality_status,
        support_status=source.support_status,
        fallback_status=source.fallback_status,
        uncertainty_status=source.uncertainty_status,
        pressure_basis=source.pressure_basis,
        threshold_value=source.threshold_value,
        threshold_status=source.threshold_status,
        forecast_value=source.forecast_value,
        uncertainty_lower=source.uncertainty_lower,
        uncertainty_upper=source.uncertainty_upper,
        first_crossing_date=source.first_crossing_date,
        lead_time_days=source.lead_time_days,
        observed_anomaly_status=source.observed_anomaly_status,
        observed_anomaly_present=source.observed_anomaly_present,
        data_freshness=source.data_freshness,
        reason_codes=source.reason_codes,
        evidence_facts=source.evidence_facts,
        provenance_keys=source.provenance_keys,
        details={
            "anomaly_evidence": source.anomaly_evidence.model_dump(mode="json") if source.anomaly_evidence else None,
            "limitations": source.limitations,
        },
    )


def _verify_assured_provenance(session: Session, bundle: OperationalIntelligenceBundle) -> None:
    assurance = assurance_repository.snapshot_by_identity(session, bundle.assurance_identity_sha256)
    if assurance is None:
        raise ValidationError("operational-intelligence bundle references an unpublished Model Assurance identity")
    if assurance.ml_freeze_status != "ML_CORE_CLOSED_FROZEN":
        raise ValidationError("referenced Model Assurance snapshot is not frozen")
    if assurance.claim_boundaries.get("pressure_basis") != "historical_flow_proxy_v1":
        raise ValidationError("referenced Model Assurance pressure basis is not historical_flow_proxy_v1")
    if assurance.source_code_commit != bundle.source_code_commit:
        raise ValidationError("operational-intelligence source commit does not match Model Assurance")
    capabilities = {row.capability_id: row for row in assurance_repository.capabilities(session, assurance.id)}
    for source_key, capability_id in ASSURANCE_CAPABILITY_BY_SOURCE.items():
        capability = capabilities.get(capability_id)
        if capability is None:
            raise ValidationError(f"Model Assurance lacks required capability {capability_id!r}")
        if (
            capability.evidence_status != "ACCEPTED"
            or capability.acceptance_verdict not in {"ACCEPT", "ACCEPT_WITH_P2"}
            or capability.product_consumption_status != "ELIGIBLE_AFTER_INGESTION"
        ):
            raise ValidationError(f"Model Assurance capability {capability_id!r} is not eligible for publication")
        if (
            not capability.human_review_required
            or capability.autonomous_action
            or capability.capacity_checked
            or capability.causal_effect_claimed
            or capability.serving_claim
        ):
            raise ValidationError(f"Model Assurance capability {capability_id!r} violates governance boundaries")
        source = bundle.source_provenance[source_key]
        comparisons = {
            "run_id": (source.run_id, capability.run_id),
            "scientific_identity_sha256": (
                source.scientific_identity_sha256,
                capability.scientific_identity_sha256,
            ),
            "artifact_sha256": (source.artifact_sha256, capability.artifact_identity),
            "dataset_identity_sha256": (
                source.dataset_identity_sha256,
                capability.dataset_identity_sha256,
            ),
            "config_identity_sha256": (
                source.config_identity_sha256,
                capability.config_identity_sha256,
            ),
            "code_identity_sha256": (
                source.code_identity_sha256,
                capability.code_identity_sha256,
            ),
        }
        mismatched = [name for name, values in comparisons.items() if values[0] != values[1]]
        if mismatched:
            raise ValidationError(
                f"operational source {source_key!r} does not match assured capability {capability_id!r}: "
                f"{', '.join(mismatched)}"
            )


def publish(session: Session, parsed: ParsedOperationalBundle) -> PublicationResult:
    """Atomically publish one validated projection and switch the current snapshot."""
    bundle = parsed.bundle
    with session.begin():
        _verify_assured_provenance(session, bundle)
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
            session.execute(update(OperationalIntelligenceSnapshot).values(is_active=False))
            by_id.is_active = True
            return PublicationResult(
                snapshot_id=by_id.id,
                publication_id=by_id.publication_id,
                publication_identity_sha256=by_id.publication_identity_sha256,
                created=False,
            )
        if by_identity is not None:
            raise ConflictError("publication identity is already attached to a different publication_id")

        session.execute(update(OperationalIntelligenceSnapshot).values(is_active=False))
        snapshot = OperationalIntelligenceSnapshot(
            publication_id=bundle.publication_id,
            schema_version=bundle.schema_version,
            contract_version=bundle.contract_version,
            publication_identity_sha256=bundle.publication_identity_sha256,
            bundle_sha256=parsed.bundle_sha256,
            assurance_identity_sha256=bundle.assurance_identity_sha256,
            source_code_commit=bundle.source_code_commit,
            current_origin=bundle.current_origin,
            freshness_state=bundle.freshness_state,
            publication_status=bundle.publication_status,
            generated_at=bundle.generated_at,
            is_active=True,
            forecast_count=len(bundle.forecasts),
            signal_count=len(bundle.signals),
            source_provenance={key: value.model_dump(mode="json") for key, value in bundle.source_provenance.items()},
            limitations=bundle.limitations,
        )
        session.add(snapshot)
        session.flush()
        session.add_all(_forecast_row(snapshot.id, row) for row in bundle.forecasts)
        session.add_all(_signal_row(snapshot.id, row) for row in bundle.signals)
        snapshot_id = snapshot.id
    return PublicationResult(
        snapshot_id=snapshot_id,
        publication_id=bundle.publication_id,
        publication_identity_sha256=bundle.publication_identity_sha256,
        created=True,
    )


def _snapshot_response(row: OperationalIntelligenceSnapshot) -> OperationalSnapshotResponse:
    return OperationalSnapshotResponse(
        publication_id=row.publication_id,
        schema_version=row.schema_version,
        contract_version=row.contract_version,
        publication_identity_sha256=row.publication_identity_sha256,
        bundle_sha256=row.bundle_sha256,
        assurance_identity_sha256=row.assurance_identity_sha256,
        source_code_commit=row.source_code_commit,
        current_origin=row.current_origin,
        freshness_state=row.freshness_state,
        publication_status=row.publication_status,
        generated_at=row.generated_at,
        published_at=row.published_at,
        forecast_count=row.forecast_count,
        signal_count=row.signal_count,
        source_provenance=row.source_provenance,
        limitations=row.limitations,
    )


def _provenance(snapshot: OperationalIntelligenceSnapshot, keys: list[str]) -> dict[str, Any]:
    return {key: snapshot.source_provenance[key] for key in keys}


def _forecast_response(
    snapshot: OperationalIntelligenceSnapshot, row: OperationalForecast
) -> OperationalForecastResponse:
    raw = None
    if row.raw_p10 is not None:
        raw = {
            "p10": row.raw_p10,
            "p50": row.raw_p50,
            "p90": row.raw_p90,
            "semantics": "UNCHANGED_MODEL_EVIDENCE",
        }
    calibrated = None
    if row.calibrated_lower is not None:
        calibrated = {
            "lower": row.calibrated_lower,
            "upper": row.calibrated_upper,
            "nominal_coverage": row.calibration_nominal_coverage,
            "calibration_status": "CALIBRATED",
            "support_class": row.calibration_support_class,
            "calibration_version": row.calibration_version,
        }
    return OperationalForecastResponse(
        series_id=row.series_id,
        level=row.level,
        origin=row.origin,
        target_date=row.target_date,
        horizon=row.horizon,
        target=row.target,
        org_code=row.org_code,
        region_code=row.region_code,
        profile_code=row.profile_code,
        central_value=row.central_value,
        central_semantics=row.central_semantics,
        raw_quantiles=raw,
        calibrated_uncertainty=calibrated,
        calibration_status=row.calibration_status,
        prediction_source=row.prediction_source,
        hierarchy_status=row.hierarchy_status,
        support_status=row.support_status,
        fallback_status=row.fallback_status,
        uncertainty_status=row.uncertainty_status,
        provenance_keys=row.provenance_keys,
        evidence_facts=row.details["evidence_facts"],
        limitations=row.details["limitations"],
        publication_identity_sha256=snapshot.publication_identity_sha256,
        source_provenance=_provenance(snapshot, row.provenance_keys),
    )


def _signal_response(snapshot: OperationalIntelligenceSnapshot, row: OperationalSignal) -> OperationalSignalResponse:
    return OperationalSignalResponse(
        signal_id=row.signal_id,
        signal_type=row.signal_type,
        series_id=row.series_id,
        origin=row.origin,
        target=row.target,
        org_code=row.org_code,
        region_code=row.region_code,
        profile_code=row.profile_code,
        inbox_rank=row.inbox_rank,
        severity=row.severity,
        headline=row.headline,
        concise_reason=row.concise_reason,
        materiality_status=row.materiality_status,
        support_status=row.support_status,
        fallback_status=row.fallback_status,
        uncertainty_status=row.uncertainty_status,
        pressure_basis=row.pressure_basis,
        threshold_value=row.threshold_value,
        threshold_status=row.threshold_status,
        forecast_value=row.forecast_value,
        uncertainty_lower=row.uncertainty_lower,
        uncertainty_upper=row.uncertainty_upper,
        first_crossing_date=row.first_crossing_date,
        lead_time_days=row.lead_time_days,
        observed_anomaly_status=row.observed_anomaly_status,
        observed_anomaly_present=row.observed_anomaly_present,
        data_freshness=row.data_freshness,
        reason_codes=row.reason_codes,
        evidence_facts=row.evidence_facts,
        provenance_keys=row.provenance_keys,
        anomaly_evidence=row.details["anomaly_evidence"],
        limitations=row.details["limitations"],
        publication_identity_sha256=snapshot.publication_identity_sha256,
        source_provenance=_provenance(snapshot, row.provenance_keys),
    )


def _current(session: Session) -> OperationalIntelligenceSnapshot:
    snapshot = repository.current_snapshot(session)
    if snapshot is None:
        raise NotFoundError("no current operational-intelligence snapshot is published")
    return snapshot


def _add_count(counts: OperationalCounts, row, count: int) -> None:
    counts.total_signals += count
    severity_field = {
        "HIGH": "high",
        "ELEVATED": "elevated",
        "WATCH": "watch",
        "NORMAL": "normal",
        "UNSUPPORTED": "unsupported_severity",
    }[row.severity]
    setattr(counts, severity_field, getattr(counts, severity_field) + count)
    if row.signal_type == "preventive_flow_pressure":
        counts.preventive_pressure += count
    else:
        counts.observed_unusual_flow += count
    support_field = {
        "DIRECT_SUPPORTED": "direct_supported",
        "FALLBACK_LIMITED": "fallback_limited",
        "UNSUPPORTED": "unsupported_support",
    }[row.support_status]
    setattr(counts, support_field, getattr(counts, support_field) + count)
    if row.uncertainty_status == "CALIBRATED":
        counts.calibrated += count
    else:
        counts.uncertainty_limited_or_unavailable += count


def _counts(rows, *, grouped: bool = True) -> OperationalCounts:
    counts = OperationalCounts()
    for row in rows:
        count = row.count if grouped else 1
        _add_count(counts, row, count)
    return counts


def overview(session: Session) -> OperationalOverviewResponse:
    snapshot = _current(session)
    rows = repository.signal_summary_rows(session, snapshot.id)
    by_region: dict[str, list] = {}
    for row in rows:
        if row.region_code is not None:
            by_region.setdefault(row.region_code, []).append(row)
    regions = set(by_region) | set(repository.forecast_regions(session, snapshot.id))
    return OperationalOverviewResponse(
        snapshot=_snapshot_response(snapshot),
        national=_counts(rows),
        regions=[
            OperationalRegionSummary(region_code=region, counts=_counts(by_region.get(region, [])))
            for region in sorted(regions)
        ],
    )


def list_signals(
    session: Session,
    *,
    region_code: str | None,
    org_code: str | None,
    profile_code: str | None,
    target: str | None,
    severity: str | None,
    signal_type: str | None,
    support_status: str | None,
    limit: int,
    offset: int,
) -> Page[OperationalSignalResponse]:
    snapshot = _current(session)
    rows, total = repository.signals(
        session,
        snapshot.id,
        region_code=region_code,
        org_code=org_code,
        profile_code=profile_code,
        target=target,
        severity=severity,
        signal_type=signal_type,
        support_status=support_status,
        limit=limit,
        offset=offset,
    )
    return Page[OperationalSignalResponse](
        items=[_signal_response(snapshot, row) for row in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


def get_signal(session: Session, signal_id: str) -> OperationalSignalResponse:
    snapshot = _current(session)
    row = repository.signal(session, snapshot.id, signal_id)
    if row is None:
        raise NotFoundError(f"unknown current operational signal {signal_id!r}")
    return _signal_response(snapshot, row)


def region(session: Session, region_code: str) -> OperationalRegionResponse:
    snapshot = _current(session)
    summary_rows = repository.signal_summary_rows(session, snapshot.id, region_code)
    top, total = repository.signals(session, snapshot.id, region_code=region_code, limit=20, offset=0)
    point_count, origins, targets = repository.region_forecast_facets(session, snapshot.id, region_code)
    if not total and not point_count:
        raise NotFoundError(f"no current operational intelligence for region {region_code!r}")
    return OperationalRegionResponse(
        snapshot=_snapshot_response(snapshot),
        region_code=region_code,
        counts=_counts(summary_rows),
        top_signals=[_signal_response(snapshot, row) for row in top],
        forecast_point_count=point_count,
        available_origins=origins,
        available_targets=targets,
    )


def hospital_profile(session: Session, org_code: str, profile_code: str) -> OperationalHospitalProfileResponse:
    snapshot = _current(session)
    rows, total = repository.signals(
        session,
        snapshot.id,
        org_code=org_code,
        profile_code=profile_code,
        limit=500,
        offset=0,
    )
    point_count, origins, targets, forecast_region = repository.hospital_forecast_facets(
        session, snapshot.id, org_code, profile_code
    )
    if not total and not point_count:
        raise NotFoundError(
            f"no current operational intelligence for hospital {org_code!r} and profile {profile_code!r}"
        )
    region_code = next((row.region_code for row in rows if row.region_code), forecast_region)
    return OperationalHospitalProfileResponse(
        snapshot=_snapshot_response(snapshot),
        org_code=org_code,
        region_code=region_code,
        profile_code=profile_code,
        counts=_counts(rows, grouped=False),
        signals=[_signal_response(snapshot, row) for row in rows],
        forecast_point_count=point_count,
        available_origins=origins,
        available_targets=targets,
    )


def list_forecasts(
    session: Session,
    *,
    origin: dt.date | None,
    target_date_from: dt.date | None,
    target_date_to: dt.date | None,
    level: str | None,
    region_code: str | None,
    org_code: str | None,
    profile_code: str | None,
    target: str | None,
    limit: int,
    offset: int,
) -> Page[OperationalForecastResponse]:
    snapshot = _current(session)
    rows, total = repository.forecasts(
        session,
        snapshot.id,
        origin=origin,
        target_date_from=target_date_from,
        target_date_to=target_date_to,
        level=level,
        region_code=region_code,
        org_code=org_code,
        profile_code=profile_code,
        target=target,
        limit=limit,
        offset=offset,
    )
    return Page[OperationalForecastResponse](
        items=[_forecast_response(snapshot, row) for row in rows],
        total=total,
        limit=limit,
        offset=offset,
    )
