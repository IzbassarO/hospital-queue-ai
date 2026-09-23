"""Publish and query the backend-owned review-evidence read model.

Review evidence projects two accepted EVALUATION_ONLY capabilities (forecast stress tests and
constrained decision alternatives) for human review. Publication verifies both against the referenced
Model Assurance snapshot and checks that the identity scenario reproduces the referenced operational
publication exactly. Request-time code never reads ML artifacts.
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

from app.db.models import (
    ReviewAlternative,
    ReviewAlternativeSet,
    ReviewEvidenceSnapshot,
    ReviewScenario,
    ReviewScenarioCell,
    ReviewScenarioEntity,
)
from app.repositories import model_assurance as assurance_repository
from app.repositories import review_evidence as repository
from app.schemas.common import Page
from app.schemas.review_evidence import (
    AlternativeRow,
    AlternativeSetResponse,
    AlternativeSetRow,
    AlternativeSetSummaryResponse,
    ReviewEvidenceBundle,
    ReviewOverviewResponse,
    ReviewSnapshotResponse,
    ScenarioCatalogResponse,
    ScenarioCatalogRow,
    ScenarioCellResponse,
    ScenarioCellRow,
    ScenarioEntityRow,
    ScenarioOutcomeResponse,
    SignalDecisionAlternativesResponse,
    SignalStressTestResponse,
)
from app.services.common import ConflictError, NotFoundError, ValidationError

BASELINE_TOLERANCE = 1e-9
ASSURANCE_CAPABILITY_BY_SOURCE = {
    "flow_scenario": "forecast_stress_test",
    "decision_alternatives": "decision_alternatives",
}
IDENTITY_SCENARIO_TYPE = "identity"


@dataclass(frozen=True)
class ParsedReviewBundle:
    bundle: ReviewEvidenceBundle
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


def _identity_projection(bundle: ReviewEvidenceBundle) -> dict[str, Any]:
    payload = bundle.model_dump(mode="json")
    payload.pop("publication_identity_sha256", None)
    payload.pop("generated_at", None)
    return payload


def parse_bundle(raw: bytes) -> ParsedReviewBundle:
    try:
        value = json.loads(raw, object_pairs_hook=_reject_duplicate_json_keys)
        bundle = ReviewEvidenceBundle.model_validate(value)
        computed_identity = hashlib.sha256(_canonical_bytes(_identity_projection(bundle))).hexdigest()
    except (UnicodeDecodeError, json.JSONDecodeError, PydanticValidationError, TypeError, ValueError) as exc:
        raise ValidationError(f"invalid review-evidence bundle: {exc}") from exc
    if computed_identity != bundle.publication_identity_sha256:
        raise ValidationError(
            "invalid review-evidence bundle: publication_identity_sha256 does not match canonical content"
        )
    return ParsedReviewBundle(bundle=bundle, bundle_sha256=hashlib.sha256(raw).hexdigest())


def load_bundle(path: Path) -> ParsedReviewBundle:
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise ValidationError(f"cannot read review-evidence bundle {path}: {exc}") from exc
    return parse_bundle(raw)


# ------------------------------------------------------------------------------- publication
def _verify_assured_provenance(session: Session, bundle: ReviewEvidenceBundle) -> None:
    assurance = assurance_repository.snapshot_by_identity(session, bundle.assurance_identity_sha256)
    if assurance is None:
        raise ValidationError("review-evidence bundle references an unpublished Model Assurance identity")
    if assurance.ml_freeze_status != "ML_CORE_CLOSED_FROZEN":
        raise ValidationError("referenced Model Assurance snapshot is not frozen")
    if assurance.source_code_commit != bundle.source_code_commit:
        raise ValidationError("review-evidence source commit does not match Model Assurance")
    capabilities = {row.capability_id: row for row in assurance_repository.capabilities(session, assurance.id)}
    for source_key, capability_id in ASSURANCE_CAPABILITY_BY_SOURCE.items():
        capability = capabilities.get(capability_id)
        if capability is None:
            raise ValidationError(f"Model Assurance lacks required capability {capability_id!r}")
        if (
            capability.evidence_status != "ACCEPTED"
            or capability.acceptance_verdict not in {"ACCEPT", "ACCEPT_WITH_P2"}
            or capability.product_consumption_status != "EVALUATION_ONLY"
        ):
            raise ValidationError(f"Model Assurance capability {capability_id!r} is not review-only accepted evidence")
        if (
            not capability.human_review_required
            or capability.autonomous_action
            or capability.capacity_checked
            or capability.causal_effect_claimed
            or capability.serving_claim
            or capability.promotion_status != "NO_PROMOTION"
        ):
            raise ValidationError(f"Model Assurance capability {capability_id!r} violates governance boundaries")
        source = bundle.source_provenance[source_key]
        comparisons = {
            "run_id": (source.run_id, capability.run_id),
            "scientific_identity_sha256": (source.scientific_identity_sha256, capability.scientific_identity_sha256),
            "artifact_sha256": (source.artifact_sha256, capability.artifact_identity),
            "dataset_identity_sha256": (source.dataset_identity_sha256, capability.dataset_identity_sha256),
            "config_identity_sha256": (source.config_identity_sha256, capability.config_identity_sha256),
            "code_identity_sha256": (source.code_identity_sha256, capability.code_identity_sha256),
        }
        mismatched = [name for name, values in comparisons.items() if values[0] != values[1]]
        if mismatched:
            raise ValidationError(
                f"review source {source_key!r} does not match assured capability {capability_id!r}: "
                f"{', '.join(mismatched)}"
            )
    operational = repository.operational_snapshot_by_identity(session, bundle.operational_publication_identity_sha256)
    if operational is None:
        raise ValidationError("review-evidence bundle references an unpublished operational publication identity")
    if operational.assurance_identity_sha256 != bundle.assurance_identity_sha256:
        raise ValidationError("operational publication and review evidence reference different Model Assurance")
    if bundle.publication_status == "AVAILABLE" and operational.current_origin != bundle.current_origin:
        raise ValidationError("review-evidence origin differs from the referenced operational publication")


def _scenario_row(snapshot_id: int, source: ScenarioCatalogRow) -> ReviewScenario:
    return ReviewScenario(
        snapshot_id=snapshot_id,
        scenario_id=source.scenario_id,
        scenario_type=source.scenario_type,
        classification=source.classification,
        lever_type=source.lever_type,
        multiplier=source.multiplier,
        scope_type=source.scope_type,
        horizon_start=source.horizon_start,
        horizon_end=source.horizon_end,
        target=source.target,
        uncertainty_method=source.uncertainty_method,
        uncertainty_label=source.uncertainty_label,
        coverage_guarantee=source.coverage_guarantee,
        causal_effect_claimed=source.causal_effect_claimed,
        serving_claim=source.serving_claim,
        baseline_reproduction=source.baseline_reproduction,
        details={
            "network_summary": source.network_summary.model_dump(mode="json"),
            "evidence_facts": source.evidence_facts,
            "limitations": source.limitations,
        },
    )


def _entity_row(snapshot_id: int, source: ScenarioEntityRow) -> ReviewScenarioEntity:
    data = source.model_dump(mode="json")
    limitations = data.pop("limitations")
    return ReviewScenarioEntity(snapshot_id=snapshot_id, details={"limitations": limitations}, **data)


def _cell_row(snapshot_id: int, source: ScenarioCellRow) -> ReviewScenarioCell:
    return ReviewScenarioCell(snapshot_id=snapshot_id, **source.model_dump(mode="json"))


def _set_row(snapshot_id: int, source: AlternativeSetRow) -> ReviewAlternativeSet:
    donor = source.donor
    return ReviewAlternativeSet(
        snapshot_id=snapshot_id,
        set_id=source.set_id,
        canonical_unit_id=source.canonical_unit_id,
        origin=source.origin,
        target=source.target,
        signal_id=donor.signal_id,
        org_code=donor.org_code,
        profile_code=donor.profile_code,
        region_code=donor.region_code,
        series_id=donor.series_id,
        donor_severity=donor.displayed_severity,
        priority_support_class=donor.priority_support_class,
        materiality_status=donor.materiality_status,
        budget=source.budget,
        abstained=source.abstained,
        abstention_codes=source.abstention_codes,
        receiver_candidates_considered=source.receiver_candidates_considered,
        receiver_candidates_eligible=source.receiver_candidates_eligible,
        donor_minimum_transfer_fraction=source.donor_minimum_transfer_fraction,
        shortlist_bound=source.shortlist_bound,
        alternative_count=len(source.alternatives),
        verification_failure_count=source.verification_failure_count,
        scientific_output_sha256=source.scientific_output_sha256,
        details={
            "donor": donor.model_dump(mode="json"),
            "rejected_receiver_counts": source.rejected_receiver_counts,
            "limitations": source.limitations,
            "execution_mode": source.execution_mode,
        },
    )


def _alternative_row(snapshot_id: int, set_id: str, position: int, source: AlternativeRow) -> ReviewAlternative:
    return ReviewAlternative(
        snapshot_id=snapshot_id,
        set_id=set_id,
        alternative_id=source.alternative_id,
        position=position,
        donor_org_code=source.donor.org_code,
        receiver_org_code=source.receiver.org_code,
        profile_code=source.donor.profile_code,
        region_code=source.donor.region_code,
        transfer_fraction=source.transfer_fraction,
        transferred_total=source.transferred_total,
        donor_severity_before=source.donor_severity_before,
        donor_severity_after=source.donor_severity_after,
        receiver_severity_before=source.receiver_severity_before,
        receiver_severity_after=source.receiver_severity_after,
        verification_state=source.verification_state,
        forecast_support_tier=source.forecast_support_tier,
        receiver_range_evidence=source.receiver_range_evidence,
        sensitivity_range_result=source.sensitivity_range_result,
        feasibility_status=source.feasibility_status,
        receiver_no_worse_constraint_satisfied=source.receiver_no_worse_constraint_satisfied,
        conservation_satisfied=source.conservation_satisfied,
        details=source.model_dump(mode="json"),
    )


def publish(session: Session, parsed: ParsedReviewBundle) -> PublicationResult:
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
            session.execute(update(ReviewEvidenceSnapshot).values(is_active=False))
            by_id.is_active = True
            return PublicationResult(
                snapshot_id=by_id.id,
                publication_id=by_id.publication_id,
                publication_identity_sha256=by_id.publication_identity_sha256,
                created=False,
            )
        if by_identity is not None:
            raise ConflictError("publication identity is already attached to a different publication_id")

        session.execute(update(ReviewEvidenceSnapshot).values(is_active=False))
        alternative_count = sum(len(row.alternatives) for row in bundle.alternative_sets)
        snapshot = ReviewEvidenceSnapshot(
            publication_id=bundle.publication_id,
            schema_version=bundle.schema_version,
            contract_version=bundle.contract_version,
            publication_identity_sha256=bundle.publication_identity_sha256,
            bundle_sha256=parsed.bundle_sha256,
            assurance_identity_sha256=bundle.assurance_identity_sha256,
            operational_publication_identity_sha256=bundle.operational_publication_identity_sha256,
            source_code_commit=bundle.source_code_commit,
            current_origin=bundle.current_origin,
            freshness_state=bundle.freshness_state,
            publication_status=bundle.publication_status,
            generated_at=bundle.generated_at,
            is_active=True,
            scenario_count=len(bundle.scenarios),
            scenario_entity_count=len(bundle.scenario_entities),
            scenario_cell_count=len(bundle.scenario_cells),
            alternative_set_count=len(bundle.alternative_sets),
            alternative_count=alternative_count,
            source_provenance={key: value.model_dump(mode="json") for key, value in bundle.source_provenance.items()},
            limitations=bundle.limitations,
            alternatives_summary=bundle.alternatives_summary.model_dump(mode="json"),
        )
        session.add(snapshot)
        session.flush()
        session.add_all(_scenario_row(snapshot.id, row) for row in bundle.scenarios)
        session.add_all(_entity_row(snapshot.id, row) for row in bundle.scenario_entities)
        session.add_all(_cell_row(snapshot.id, row) for row in bundle.scenario_cells)
        session.add_all(_set_row(snapshot.id, row) for row in bundle.alternative_sets)
        session.add_all(
            _alternative_row(snapshot.id, row.set_id, position, alternative)
            for row in bundle.alternative_sets
            for position, alternative in enumerate(row.alternatives)
        )
        session.flush()
        operational = repository.operational_snapshot_by_identity(
            session, bundle.operational_publication_identity_sha256
        )
        assert operational is not None  # verified above inside the same transaction
        for scenario in bundle.scenarios:
            if scenario.scenario_type != IDENTITY_SCENARIO_TYPE:
                continue
            mismatches = repository.baseline_mismatch_count(
                session, snapshot.id, scenario.scenario_id, operational.id, BASELINE_TOLERANCE
            )
            if mismatches:
                raise ValidationError(
                    f"identity scenario {scenario.scenario_id!r} does not reproduce the referenced operational "
                    f"publication: {mismatches} cell(s) differ or are unpublished"
                )
        snapshot_id = snapshot.id
    return PublicationResult(
        snapshot_id=snapshot_id,
        publication_id=bundle.publication_id,
        publication_identity_sha256=bundle.publication_identity_sha256,
        created=True,
    )


# ----------------------------------------------------------------------------------- queries
def _snapshot_response(row: ReviewEvidenceSnapshot) -> ReviewSnapshotResponse:
    return ReviewSnapshotResponse(
        publication_id=row.publication_id,
        schema_version=row.schema_version,
        contract_version=row.contract_version,
        publication_identity_sha256=row.publication_identity_sha256,
        bundle_sha256=row.bundle_sha256,
        assurance_identity_sha256=row.assurance_identity_sha256,
        operational_publication_identity_sha256=row.operational_publication_identity_sha256,
        source_code_commit=row.source_code_commit,
        current_origin=row.current_origin,
        freshness_state=row.freshness_state,
        publication_status=row.publication_status,
        generated_at=row.generated_at,
        published_at=row.published_at,
        scenario_count=row.scenario_count,
        scenario_entity_count=row.scenario_entity_count,
        scenario_cell_count=row.scenario_cell_count,
        alternative_set_count=row.alternative_set_count,
        alternative_count=row.alternative_count,
        source_provenance=row.source_provenance,
        limitations=row.limitations,
    )


def _scenario_response(row: ReviewScenario) -> ScenarioCatalogResponse:
    return ScenarioCatalogResponse(
        scenario_id=row.scenario_id,
        scenario_type=row.scenario_type,
        classification=row.classification,
        lever_type=row.lever_type,
        multiplier=row.multiplier,
        scope_type=row.scope_type,
        horizon_start=row.horizon_start,
        horizon_end=row.horizon_end,
        target=row.target,
        uncertainty_method=row.uncertainty_method,
        uncertainty_label=row.uncertainty_label,
        coverage_guarantee=row.coverage_guarantee,
        causal_effect_claimed=row.causal_effect_claimed,
        serving_claim=row.serving_claim,
        baseline_reproduction=row.baseline_reproduction,
        network_summary=row.details["network_summary"],
        evidence_facts=row.details["evidence_facts"],
        limitations=row.details["limitations"],
    )


def _cell_response(row: ReviewScenarioCell) -> ScenarioCellResponse:
    return ScenarioCellResponse(
        target_date=row.target_date,
        horizon=row.horizon,
        baseline_central=row.baseline_central,
        baseline_lower=row.baseline_lower,
        baseline_upper=row.baseline_upper,
        baseline_severity=row.baseline_severity,
        scenario_central=row.scenario_central,
        scenario_lower=row.scenario_lower,
        scenario_upper=row.scenario_upper,
        scenario_severity=row.scenario_severity,
        threshold_value=row.threshold_value,
        threshold_status=row.threshold_status,
        scenario_uncertainty_status=row.scenario_uncertainty_status,
        severity_changed=row.severity_changed,
        source_reason_code=row.source_reason_code,
    )


def _current(session: Session) -> ReviewEvidenceSnapshot:
    snapshot = repository.current_snapshot(session)
    if snapshot is None:
        raise NotFoundError("no current review-evidence snapshot is published")
    return snapshot


def overview(session: Session) -> ReviewOverviewResponse:
    snapshot = _current(session)
    return ReviewOverviewResponse(
        snapshot=_snapshot_response(snapshot),
        scenarios=[_scenario_response(row) for row in repository.scenarios(session, snapshot.id)],
        alternatives_summary=snapshot.alternatives_summary,
    )


def signal_stress_test(session: Session, signal_id: str) -> SignalStressTestResponse:
    snapshot = _current(session)
    entities = repository.entities_for_signal(session, snapshot.id, signal_id)
    if not entities:
        raise NotFoundError(f"no current stress-test evidence for signal {signal_id!r}")
    catalog = {row.scenario_id: row for row in repository.scenarios(session, snapshot.id)}
    first = entities[0]
    cells = repository.cells_for_series(session, snapshot.id, first.series_id, first.target, first.origin)
    by_scenario: dict[str, list[ReviewScenarioCell]] = {}
    for cell in cells:
        by_scenario.setdefault(cell.scenario_id, []).append(cell)
    order = [row.scenario_id for row in catalog.values()]
    outcomes = []
    for entity in sorted(entities, key=lambda row: order.index(row.scenario_id)):
        outcomes.append(
            ScenarioOutcomeResponse(
                scenario=_scenario_response(catalog[entity.scenario_id]),
                baseline_severity=entity.baseline_severity,
                scenario_severity=entity.scenario_severity,
                baseline_inbox_rank=entity.baseline_inbox_rank,
                scenario_inbox_rank=entity.scenario_inbox_rank,
                baseline_central=entity.baseline_central,
                scenario_central=entity.scenario_central,
                threshold_value=entity.threshold_value,
                absolute_delta=entity.absolute_delta,
                relative_delta=entity.relative_delta,
                severity_changed=entity.severity_changed,
                entered_primary_inbox=entity.entered_primary_inbox,
                left_primary_inbox=entity.left_primary_inbox,
                first_crossing_date=entity.first_crossing_date,
                lead_time_days=entity.lead_time_days,
                materiality_status=entity.materiality_status,
                scenario_headline=entity.scenario_headline,
                scenario_reason=entity.scenario_reason,
                scenario_range_available=entity.scenario_range_available,
                limitations=entity.details["limitations"],
                cells=[_cell_response(cell) for cell in by_scenario.get(entity.scenario_id, [])],
            )
        )
    return SignalStressTestResponse(
        snapshot=_snapshot_response(snapshot),
        signal_id=signal_id,
        series_id=first.series_id,
        origin=first.origin,
        target=first.target,
        org_code=first.org_code,
        region_code=first.region_code,
        profile_code=first.profile_code,
        outcomes=outcomes,
    )


def _set_summary(snapshot: ReviewEvidenceSnapshot, row: ReviewAlternativeSet) -> AlternativeSetSummaryResponse:
    return AlternativeSetSummaryResponse(
        set_id=row.set_id,
        canonical_unit_id=row.canonical_unit_id,
        origin=row.origin,
        target=row.target,
        donor=row.details["donor"],
        budget=row.budget,
        abstained=row.abstained,
        abstention_codes=row.abstention_codes,
        receiver_candidates_considered=row.receiver_candidates_considered,
        receiver_candidates_eligible=row.receiver_candidates_eligible,
        donor_minimum_transfer_fraction=row.donor_minimum_transfer_fraction,
        alternative_count=row.alternative_count,
        publication_identity_sha256=snapshot.publication_identity_sha256,
    )


def _set_response(
    snapshot: ReviewEvidenceSnapshot, row: ReviewAlternativeSet, alternatives: list[ReviewAlternative]
) -> AlternativeSetResponse:
    return AlternativeSetResponse(
        set_id=row.set_id,
        canonical_unit_id=row.canonical_unit_id,
        origin=row.origin,
        target=row.target,
        donor=row.details["donor"],
        budget=row.budget,
        abstained=row.abstained,
        abstention_codes=row.abstention_codes,
        rejected_receiver_counts=row.details["rejected_receiver_counts"],
        receiver_candidates_considered=row.receiver_candidates_considered,
        receiver_candidates_eligible=row.receiver_candidates_eligible,
        donor_minimum_transfer_fraction=row.donor_minimum_transfer_fraction,
        shortlist_bound=row.shortlist_bound,
        alternatives=[alternative.details for alternative in alternatives],
        verification_failure_count=row.verification_failure_count,
        scientific_output_sha256=row.scientific_output_sha256,
        execution_mode=row.details["execution_mode"],
        human_review_required=True,
        serving_claim=False,
        limitations=row.details["limitations"],
        publication_identity_sha256=snapshot.publication_identity_sha256,
        source_provenance=snapshot.source_provenance,
    )


def signal_decision_alternatives(session: Session, signal_id: str) -> SignalDecisionAlternativesResponse:
    snapshot = _current(session)
    rows, _ = repository.alternative_sets(session, snapshot.id, signal_id=signal_id, limit=500, offset=0)
    if not rows:
        raise NotFoundError(f"no current decision-alternative evidence for signal {signal_id!r}")
    alternatives = repository.alternatives(session, snapshot.id, [row.set_id for row in rows])
    grouped: dict[str, list[ReviewAlternative]] = {}
    for alternative in alternatives:
        grouped.setdefault(alternative.set_id, []).append(alternative)
    return SignalDecisionAlternativesResponse(
        snapshot=_snapshot_response(snapshot),
        signal_id=signal_id,
        sets=[_set_response(snapshot, row, grouped.get(row.set_id, [])) for row in rows],
    )


def list_alternative_sets(
    session: Session,
    *,
    origin: dt.date | None,
    region_code: str | None,
    org_code: str | None,
    profile_code: str | None,
    with_alternatives: bool | None,
    limit: int,
    offset: int,
) -> Page[AlternativeSetSummaryResponse]:
    snapshot = _current(session)
    rows, total = repository.alternative_sets(
        session,
        snapshot.id,
        origin=origin,
        region_code=region_code,
        org_code=org_code,
        profile_code=profile_code,
        with_alternatives=with_alternatives,
        limit=limit,
        offset=offset,
    )
    return Page[AlternativeSetSummaryResponse](
        items=[_set_summary(snapshot, row) for row in rows], total=total, limit=limit, offset=offset
    )


def get_alternative_set(session: Session, set_id: str) -> AlternativeSetResponse:
    snapshot = _current(session)
    row = repository.alternative_set(session, snapshot.id, set_id)
    if row is None:
        raise NotFoundError(f"unknown current decision-alternative set {set_id!r}")
    return _set_response(snapshot, row, repository.alternatives(session, snapshot.id, [set_id]))
