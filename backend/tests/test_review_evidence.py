"""Review-evidence publication, query, and API contract tests (synthetic bundles; no ML artifacts)."""

from __future__ import annotations

import copy
import datetime as dt
import hashlib
import inspect
import json
import uuid
from collections.abc import Iterator

import httpx
import pytest
from sqlalchemy import delete, select, update

from app.api import routes
from app.db.models import (
    ModelAssuranceCapability,
    ModelAssuranceSnapshot,
    OperationalForecast,
    OperationalIntelligenceSnapshot,
    ReviewEvidenceSnapshot,
)
from app.db.session import SessionLocal
from app.schemas.review_evidence import ReviewEvidenceBundle
from app.services import review_evidence
from app.services.common import ConflictError, ValidationError
from conftest import API

TEST_PREFIX = "pytest-review-"
ASSURANCE_IDENTITY = "b" * 64
OPERATIONAL_IDENTITY = "c" * 64
COMMIT = "2" * 40
SOURCES = {
    "flow_scenario": ("forecast_stress_test", 1),
    "decision_alternatives": ("decision_alternatives", 2),
}
SERIES = "hp:H001:P01"
SIGNAL = "review-signal-1"
ORIGIN = "2025-03-17"
DATES = [f"2025-03-{18 + i:02d}" for i in range(14)]
CENTRAL = [5.0 + i * 0.25 for i in range(14)]


def _canonical(value: dict) -> bytes:
    return json.dumps(value, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":")).encode()


def _provenance(index: int) -> dict:
    return {
        "run_id": f"synthetic-review-run-{index}",
        "scientific_identity_sha256": format(index, "x") * 64,
        "artifact_sha256": format(index + 6, "x") * 64,
        "dataset_identity_sha256": "d" * 64,
        "config_identity_sha256": "e" * 64,
        "code_identity_sha256": "f" * 64,
    }


def _scenario(scenario_id: str, multiplier: float | None) -> dict:
    return {
        "scenario_id": scenario_id,
        "scenario_type": "identity" if multiplier is None else "demand_multiplier",
        "classification": "SAFE_NON_CAUSAL_STRESS_TEST",
        "lever_type": "identity" if multiplier is None else "demand_multiplier",
        "multiplier": multiplier,
        "scope_type": "all_hospitals",
        "horizon_start": 1,
        "horizon_end": 14,
        "target": "registrations",
        "uncertainty_method": "additive_central_shift_v1",
        "uncertainty_label": "TRANSFORMED_BASELINE_UNCERTAINTY_RANGE",
        "coverage_guarantee": False,
        "causal_effect_claimed": False,
        "serving_claim": False,
        "baseline_reproduction": "PASS" if multiplier is None else None,
        "network_summary": {
            "daily_cells_total": 28,
            "severity_changed_count": 0 if multiplier is None else 3,
            "severity_changed_share": 0.0 if multiplier is None else 0.107,
            "severity_counts": {"HIGH": 14, "WATCH": 14},
            "entity_count": 2,
            "entity_severity_changed_count": 0 if multiplier is None else 1,
        },
        "evidence_facts": ["Synthetic accepted scenario evidence."],
        "limitations": ["No causal identification; no capacity; no coverage guarantee."],
    }


def _entity(scenario_id: str, factor: float) -> dict:
    return {
        "scenario_id": scenario_id,
        "series_id": SERIES,
        "origin": ORIGIN,
        "target": "registrations",
        "org_code": "H001",
        "region_code": "R1",
        "profile_code": "P01",
        "signal_id": SIGNAL,
        "baseline_severity": "HIGH",
        "scenario_severity": "HIGH" if factor >= 1 else "ELEVATED",
        "baseline_inbox_rank": 1,
        "scenario_inbox_rank": 1,
        "baseline_central": CENTRAL[0],
        "scenario_central": CENTRAL[0] * factor,
        "threshold_value": 1.0,
        "absolute_delta": CENTRAL[0] * (factor - 1),
        "relative_delta": factor - 1,
        "severity_changed": factor < 1,
        "entered_primary_inbox": False,
        "left_primary_inbox": False,
        "first_crossing_date": DATES[0],
        "lead_time_days": 1,
        "materiality_status": "materiality_rule_not_triggered",
        "scenario_headline": "High flow pressure expected within 1 day.",
        "scenario_reason": "Derived scenario sensitivity lower bound exceeds the historical high-flow threshold.",
        "scenario_range_available": True,
        "limitations": ["Synthetic scenario limitation."],
    }


def _cells(scenario_id: str, factor: float) -> list[dict]:
    rows = []
    for index, target_date in enumerate(DATES):
        base = CENTRAL[index]
        shift = base * (factor - 1)
        rows.append(
            {
                "scenario_id": scenario_id,
                "series_id": SERIES,
                "origin": ORIGIN,
                "target": "registrations",
                "target_date": target_date,
                "horizon": index + 1,
                "baseline_central": base,
                "baseline_lower": 1.0,
                "baseline_upper": 20.0,
                "baseline_severity": "HIGH",
                "scenario_central": base * factor,
                "scenario_lower": max(0.0, 1.0 + shift),
                "scenario_upper": 20.0 + shift,
                "scenario_severity": "HIGH" if factor >= 1 else "ELEVATED",
                "threshold_value": 1.0,
                "threshold_status": "supported",
                "scenario_uncertainty_status": "TRANSFORMED_BASELINE_UNCERTAINTY_RANGE",
                "severity_changed": factor < 1,
                "source_reason_code": "CALIBRATED_LOWER_EXCEEDS_HISTORICAL_FLOW_THRESHOLD",
            }
        )
    return rows


def _state(severity: str, scale: float) -> dict:
    return {
        "displayed_severity": severity,
        "max_severity_7d": severity,
        "max_severity_14d": severity,
        "severity_evidence_horizon": 1,
        "severity_evidence_date": DATES[0],
        "cells": [
            {
                "horizon": i + 1,
                "target_date": d,
                "central": CENTRAL[i] * scale,
                "lower": 0.5 * scale,
                "upper": 9.0 * scale,
                "severity": severity,
                "threshold_value": 4.0,
                "threshold_status": "supported",
            }
            for i, d in enumerate(DATES)
        ],
    }


def _alternative() -> dict:
    return {
        "alternative_id": "alt-1",
        "donor": {"org_code": "H001", "profile_code": "P01", "region_code": "R1", "series_id": SERIES},
        "receiver": {"org_code": "H002", "profile_code": "P01", "region_code": "R1", "series_id": "hp:H002:P01"},
        "transfer_fraction": 0.3,
        "transfer_fraction_certification": "ALGEBRAIC_MINIMUM_CERTIFIED_UPWARD_FLOAT64",
        "transferred_total": 12.5,
        "transferred_by_horizon": [{"horizon": i + 1, "target_date": d, "moved": 0.9} for i, d in enumerate(DATES)],
        "donor_severity_before": "ELEVATED",
        "donor_severity_after": "WATCH",
        "receiver_severity_before": "WATCH",
        "receiver_severity_after": "WATCH",
        "donor_binding_horizons": [12, 13],
        "donor_binding_cell": {"horizon": 12, "threshold_value": 1.0},
        "receiver_binding_cell": {"horizon": 3, "predicate": "CENTRAL"},
        "receiver_min_central_headroom": 1.18,
        "receiver_no_worse_constraint_satisfied": True,
        "conservation_satisfied": True,
        "budget_constraint_satisfied": True,
        "source_central_goal_satisfied": True,
        "verification_state": "VERIFIED_FULL_ENGINE",
        "forecast_support_tier": "DIRECT_SUPPORTED",
        "donor_support_class": "DIRECT_SUPPORTED",
        "receiver_support_class": "DIRECT_SUPPORTED",
        "receiver_range_evidence": "COMPLETE",
        "sensitivity_range_result": "NOT_ROBUST_TO_TRANSFORMED_RANGE",
        "feasibility_status": "NOT_PHYSICAL_CAPACITY_VALIDATED",
        "capacity_checked": False,
        "causal_effect_claimed": False,
        "human_review_required": True,
        "hierarchy_coherent": True,
        "donor_inbox": {
            "baseline_inbox_rank": 9,
            "scenario_inbox_rank": 2272,
            "baseline_severity": "ELEVATED",
            "scenario_severity": "WATCH",
            "entered_primary_inbox": False,
            "left_primary_inbox": False,
        },
        "receiver_inbox": {
            "baseline_inbox_rank": 695,
            "scenario_inbox_rank": 344,
            "baseline_severity": "WATCH",
            "scenario_severity": "WATCH",
            "entered_primary_inbox": False,
            "left_primary_inbox": False,
        },
        "explanation_text": "Synthetic mathematical alternative under stated constraints; requires human review.",
        "non_claims": ["No real-world improvement is claimed."],
        "limitations": [
            "NOT_PHYSICAL_CAPACITY_VALIDATED",
            "THRESHOLD_COMPARATOR_ASSUMPTION",
            "PHYSICAL_FEASIBILITY_UNKNOWN",
        ],
        "baseline_donor_state": _state("ELEVATED", 1.0),
        "scenario_donor_state": _state("WATCH", 0.7),
        "baseline_receiver_state": _state("WATCH", 1.0),
        "scenario_receiver_state": _state("WATCH", 1.3),
    }


def _set(budget: float, *, abstained: bool) -> dict:
    return {
        "set_id": f"unit-1-{budget:.2f}",
        "canonical_unit_id": "unit-1",
        "origin": ORIGIN,
        "target": "registrations",
        "donor": {
            "signal_id": SIGNAL,
            "org_code": "H001",
            "profile_code": "P01",
            "region_code": "R1",
            "series_id": SERIES,
            "displayed_severity": "HIGH",
            "priority_support_class": "direct_supported",
            "materiality_status": "materiality_rule_not_triggered",
            "binding_horizons": [1, 2],
        },
        "budget": budget,
        "abstained": abstained,
        "abstention_codes": ["RECEIVER_BLOCKED"] if abstained else [],
        "rejected_receiver_counts": {"RECEIVER_BLOCKED": 4, "RECEIVER_OUTSIDE_SAME_REGION_POLICY": 57},
        "receiver_candidates_considered": 61,
        "receiver_candidates_eligible": 4,
        "donor_minimum_transfer_fraction": 0.3,
        "shortlist_bound": 5,
        "alternatives": [] if abstained else [_alternative()],
        "verification_failure_count": 0,
        "scientific_output_sha256": "9" * 64,
        "execution_mode": "EVALUATION",
        "human_review_required": True,
        "serving_claim": False,
        "limitations": [
            "NOT_PHYSICAL_CAPACITY_VALIDATED",
            "THRESHOLD_COMPARATOR_ASSUMPTION",
            "PHYSICAL_FEASIBILITY_UNKNOWN",
        ],
    }


def _bundle(publication_id: str | None = None) -> dict:
    scenarios = [("baseline-identity", None, 1.0), ("national-registrations-x0.90", 0.9, 0.9)]
    payload = {
        "schema_version": "review_evidence_v1",
        "contract_version": "1.0.0",
        "publication_id": publication_id or f"{TEST_PREFIX}{uuid.uuid4().hex}",
        "publication_identity_sha256": "0" * 64,
        "assurance_identity_sha256": ASSURANCE_IDENTITY,
        "operational_publication_identity_sha256": OPERATIONAL_IDENTITY,
        "source_code_commit": COMMIT,
        "current_origin": ORIGIN,
        "freshness_state": "UNKNOWN",
        "publication_status": "AVAILABLE",
        "generated_at": None,
        "source_provenance": {key: _provenance(index) for key, (_, index) in SOURCES.items()},
        "limitations": ["Retrospective evaluation evidence for human review; not physical capacity."],
        "scenarios": [_scenario(sid, m) for sid, m, _ in scenarios],
        "scenario_entities": [_entity(sid, f) for sid, _, f in scenarios],
        "scenario_cells": [cell for sid, _, f in scenarios for cell in _cells(sid, f)],
        "alternative_sets": [_set(0.05, abstained=True), _set(1.0, abstained=False)],
        "alternatives_summary": {
            "set_count": 2,
            "unit_count": 1,
            "sets_with_alternatives": 1,
            "alternative_count": 1,
            "receiver_worsening_count": 0,
            "verification_failure_count": 0,
            "full_verification_success_rate": 1.0,
            "transfer_budget_ladder": [0.05, 0.1, 0.25, 1.0],
            "origins": [ORIGIN],
            "evaluation_population": "synthetic donor unit",
        },
    }
    return _set_identity(payload)


def _set_identity(payload: dict) -> dict:
    validated = ReviewEvidenceBundle.model_validate(payload)
    projection = validated.model_dump(mode="json")
    projection.pop("publication_identity_sha256")
    projection.pop("generated_at")
    payload["publication_identity_sha256"] = hashlib.sha256(_canonical(projection)).hexdigest()
    return payload


def _parsed(payload: dict) -> review_evidence.ParsedReviewBundle:
    return review_evidence.parse_bundle((json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode())


@pytest.fixture(autouse=True)
def synthetic_upstream() -> Iterator[None]:
    """Synthetic Model Assurance and operational baselines the review bundle may reference; removed afterwards."""
    with SessionLocal.begin() as session:
        previous = session.scalar(select(ReviewEvidenceSnapshot.id).where(ReviewEvidenceSnapshot.is_active.is_(True)))
        assurance = ModelAssuranceSnapshot(
            assurance_id=f"{TEST_PREFIX}assurance",
            contract_version="1.0.0",
            schema_version="model_assurance_v1",
            assurance_identity_sha256=ASSURANCE_IDENTITY,
            bundle_sha256="8" * 64,
            source_code_commit=COMMIT,
            ml_freeze_status="ML_CORE_CLOSED_FROZEN",
            product_contract_version="model-assurance-product-v1",
            generated_at=dt.datetime(2026, 9, 23, tzinfo=dt.UTC),
            is_active=False,
            capability_count=2,
            failed_evidence_history=[],
            claim_boundaries={"pressure_basis": "historical_flow_proxy_v1"},
            monitoring_expectations=[],
            freshness_policy={"sla_thresholds": None},
        )
        session.add(assurance)
        session.flush()
        for source_key, (capability_id, index) in SOURCES.items():
            provenance = _provenance(index)
            session.add(
                ModelAssuranceCapability(
                    snapshot_id=assurance.id,
                    capability_id=capability_id,
                    display_name=source_key,
                    evidence_status="ACCEPTED",
                    acceptance_verdict="ACCEPT_WITH_P2",
                    product_consumption_status="EVALUATION_ONLY",
                    run_id=provenance["run_id"],
                    scientific_identity_sha256=provenance["scientific_identity_sha256"],
                    artifact_identity=provenance["artifact_sha256"],
                    dataset_identity_sha256=provenance["dataset_identity_sha256"],
                    config_identity_sha256=provenance["config_identity_sha256"],
                    code_identity_sha256=provenance["code_identity_sha256"],
                    model_identity=None,
                    estimand_id=None,
                    calibration_identity=None,
                    hierarchy_identity=None,
                    pressure_provider_identity="historical_flow_proxy_v1",
                    prioritization_identity=None,
                    scenario_identity="forecast-stress-test-v1",
                    decision_alternative_identity=None,
                    human_review_required=True,
                    autonomous_action=False,
                    capacity_checked=False,
                    causal_effect_claimed=False,
                    serving_claim=False,
                    physical_feasibility_status="NOT_VALIDATED",
                    promotion_status="NO_PROMOTION",
                    freshness_state="UNKNOWN",
                    details={},
                )
            )
        operational = OperationalIntelligenceSnapshot(
            publication_id=f"{TEST_PREFIX}operational",
            schema_version="operational_intelligence_v1",
            contract_version="1.0.0",
            publication_identity_sha256=OPERATIONAL_IDENTITY,
            bundle_sha256="7" * 64,
            assurance_identity_sha256=ASSURANCE_IDENTITY,
            source_code_commit=COMMIT,
            current_origin=dt.date.fromisoformat(ORIGIN),
            freshness_state="UNKNOWN",
            publication_status="AVAILABLE",
            generated_at=None,
            is_active=False,
            forecast_count=14,
            signal_count=0,
            source_provenance={},
            limitations=["synthetic"],
        )
        session.add(operational)
        session.flush()
        for index, target_date in enumerate(DATES):
            session.add(
                OperationalForecast(
                    snapshot_id=operational.id,
                    series_id=SERIES,
                    level="hospital",
                    origin=dt.date.fromisoformat(ORIGIN),
                    target_date=dt.date.fromisoformat(target_date),
                    horizon=index + 1,
                    target="registrations",
                    org_code="H001",
                    region_code="R1",
                    profile_code="P01",
                    central_value=CENTRAL[index],
                    central_semantics="P50",
                    raw_p10=None,
                    raw_p50=None,
                    raw_p90=None,
                    calibrated_lower=1.0,
                    calibrated_upper=20.0,
                    calibration_nominal_coverage=0.8,
                    calibration_status="CALIBRATED",
                    calibration_support_class="direct",
                    calibration_version="v1",
                    prediction_source="DIRECT",
                    hierarchy_status="bottom_up_child_unchanged",
                    support_status="DIRECT_SUPPORTED",
                    fallback_status="NOT_APPLICABLE",
                    uncertainty_status="CALIBRATED",
                    provenance_keys=[],
                    details={"evidence_facts": [], "limitations": []},
                )
            )
    yield
    with SessionLocal.begin() as session:
        session.execute(update(ReviewEvidenceSnapshot).values(is_active=False))
        session.execute(
            delete(ReviewEvidenceSnapshot).where(ReviewEvidenceSnapshot.publication_id.startswith(TEST_PREFIX))
        )
        if previous is not None:
            session.execute(
                update(ReviewEvidenceSnapshot).where(ReviewEvidenceSnapshot.id == previous).values(is_active=True)
            )
        session.execute(
            delete(OperationalIntelligenceSnapshot).where(
                OperationalIntelligenceSnapshot.publication_identity_sha256 == OPERATIONAL_IDENTITY
            )
        )
        session.execute(
            delete(ModelAssuranceSnapshot).where(ModelAssuranceSnapshot.assurance_identity_sha256 == ASSURANCE_IDENTITY)
        )


def test_publication_preserves_scenarios_cells_sets_and_abstention() -> None:
    payload = _bundle()
    with SessionLocal() as session:
        result = review_evidence.publish(session, _parsed(payload))
        assert result.created
        overview = review_evidence.overview(session)
        assert overview.snapshot.scenario_cell_count == 28
        assert [s.scenario_id for s in overview.scenarios] == ["baseline-identity", "national-registrations-x0.90"]
        assert overview.scenarios[0].baseline_reproduction == "PASS"
        assert overview.alternatives_summary.receiver_worsening_count == 0
        stress = review_evidence.signal_stress_test(session, SIGNAL)
        assert [o.scenario.scenario_id for o in stress.outcomes] == [
            "baseline-identity",
            "national-registrations-x0.90",
        ]
        weaker = stress.outcomes[1]
        assert weaker.baseline_severity == "HIGH" and weaker.scenario_severity == "ELEVATED"
        assert len(weaker.cells) == 14
        assert weaker.cells[0].scenario_central == pytest.approx(CENTRAL[0] * 0.9)
        assert weaker.cells[0].scenario_uncertainty_status == "TRANSFORMED_BASELINE_UNCERTAINTY_RANGE"
        alternatives = review_evidence.signal_decision_alternatives(session, SIGNAL)
        assert [s.budget for s in alternatives.sets] == [0.05, 1.0]
        assert alternatives.sets[0].abstained and alternatives.sets[0].abstention_codes == ["RECEIVER_BLOCKED"]
        alternative = alternatives.sets[1].alternatives[0]
        assert alternative.receiver.org_code == "H002" and alternative.donor_severity_after == "WATCH"
        assert alternative.feasibility_status == "NOT_PHYSICAL_CAPACITY_VALIDATED"
        assert "THRESHOLD_COMPARATOR_ASSUMPTION" in alternative.limitations
        page = review_evidence.list_alternative_sets(
            session,
            origin=None,
            region_code="R1",
            org_code=None,
            profile_code=None,
            with_alternatives=True,
            limit=20,
            offset=0,
        )
        assert page.total == 1 and page.items[0].alternative_count == 1
        full = review_evidence.get_alternative_set(session, page.items[0].set_id)
        assert full.alternatives[0].alternative_id == "alt-1"


def test_identity_scenario_must_reproduce_operational_forecasts() -> None:
    payload = _bundle()
    payload["scenario_cells"][3]["baseline_central"] += 0.5
    payload["scenario_cells"][3]["scenario_central"] += 0.5
    payload = _set_identity(payload)
    with SessionLocal() as session:
        with pytest.raises(ValidationError, match="does not reproduce"):
            review_evidence.publish(session, _parsed(payload))
        session.rollback()
        # publish rolled back: nothing from this bundle was persisted
        assert (
            session.scalar(
                select(ReviewEvidenceSnapshot).where(ReviewEvidenceSnapshot.publication_id == payload["publication_id"])
            )
            is None
        )


def test_unassured_or_unpublished_upstream_fails_closed() -> None:
    with SessionLocal() as session:
        wrong_assurance = _set_identity(_bundle() | {"assurance_identity_sha256": "a" * 64})
        with pytest.raises(ValidationError, match="unpublished Model Assurance"):
            review_evidence.publish(session, _parsed(wrong_assurance))
        session.rollback()
        wrong_operational = _set_identity(_bundle() | {"operational_publication_identity_sha256": "1" * 64})
        with pytest.raises(ValidationError, match="unpublished operational publication"):
            review_evidence.publish(session, _parsed(wrong_operational))
        session.rollback()
        mismatched = _bundle()
        mismatched["source_provenance"]["flow_scenario"]["run_id"] = "another-run"
        with pytest.raises(ValidationError, match="does not match assured capability"):
            review_evidence.publish(session, _parsed(_set_identity(mismatched)))
        session.rollback()
        assert (
            session.scalar(
                select(ReviewEvidenceSnapshot).where(ReviewEvidenceSnapshot.publication_id.startswith(TEST_PREFIX))
            )
            is None
        )


def test_idempotent_replay_conflict_and_semantic_validation() -> None:
    payload = _bundle()
    with SessionLocal() as session:
        first = review_evidence.publish(session, _parsed(payload))
        replay = review_evidence.publish(session, _parsed(copy.deepcopy(payload)))
        assert replay.snapshot_id == first.snapshot_id and not replay.created
        different = _set_identity(copy.deepcopy(payload) | {"limitations": ["changed"]})
        with pytest.raises(ConflictError):
            review_evidence.publish(session, _parsed(different))
        session.rollback()
    # Semantic validation runs before the identity comparison, so the broken payloads keep their identity.
    with pytest.raises(ValidationError, match="abstained set cannot publish"):
        broken = _bundle()
        broken["alternative_sets"][1]["abstained"] = True
        _parsed(broken)
    with pytest.raises(ValidationError, match="same-region"):
        broken = _bundle()
        broken["alternative_sets"][1]["alternatives"][0]["receiver"]["region_code"] = "R2"
        _parsed(broken)
    with pytest.raises(ValidationError, match="without a derived range must not carry bounds"):
        broken = _bundle()
        broken["scenario_cells"][0]["scenario_uncertainty_status"] = "UNAVAILABLE"
        _parsed(broken)
    with pytest.raises(ValidationError, match="does not match canonical content"):
        tampered = _bundle()
        tampered["scenarios"][0]["evidence_facts"].append("tampered")
        _parsed(tampered)


@pytest.mark.anyio
async def test_review_api_requires_authentication(anon_client: httpx.AsyncClient) -> None:
    for path in (
        "/review-evidence/overview",
        f"/review-evidence/signals/{SIGNAL}/stress-test",
        f"/review-evidence/signals/{SIGNAL}/decision-alternatives",
        "/review-evidence/decision-alternatives",
        "/review-evidence/decision-alternatives/unit-1-1.00",
    ):
        response = await anon_client.get(f"{API}{path}")
        assert response.status_code == 401, path


@pytest.mark.anyio
async def test_review_api_contract(client: httpx.AsyncClient) -> None:
    with SessionLocal() as session:
        review_evidence.publish(session, _parsed(_bundle()))
    overview = await client.get(f"{API}/review-evidence/overview")
    assert overview.status_code == 200
    body = overview.json()
    assert body["snapshot"]["operational_publication_identity_sha256"] == OPERATIONAL_IDENTITY
    assert body["scenarios"][1]["multiplier"] == 0.9 and body["scenarios"][1]["coverage_guarantee"] is False
    stress = await client.get(f"{API}/review-evidence/signals/{SIGNAL}/stress-test")
    assert stress.status_code == 200
    outcome = stress.json()["outcomes"][1]
    assert outcome["scenario_severity"] == "ELEVATED" and outcome["cells"][0]["scenario_lower"] >= 0
    alternatives = await client.get(f"{API}/review-evidence/signals/{SIGNAL}/decision-alternatives")
    assert alternatives.status_code == 200
    sets = alternatives.json()["sets"]
    assert sets[0]["abstained"] is True and sets[1]["alternatives"][0]["human_review_required"] is True
    assert sets[1]["source_provenance"]["decision_alternatives"]["run_id"] == "synthetic-review-run-2"
    listing = await client.get(f"{API}/review-evidence/decision-alternatives", params={"with_alternatives": "false"})
    assert listing.status_code == 200 and listing.json()["total"] == 1 and listing.json()["items"][0]["abstained"]
    one = await client.get(f"{API}/review-evidence/decision-alternatives/unit-1-1.00")
    assert one.status_code == 200 and one.json()["alternatives"][0]["receiver"]["org_code"] == "H002"
    for path in (
        "/review-evidence/signals/unknown/stress-test",
        "/review-evidence/signals/unknown/decision-alternatives",
        "/review-evidence/decision-alternatives/unknown",
    ):
        assert (await client.get(f"{API}{path}")).status_code == 404, path


@pytest.mark.anyio
async def test_review_api_returns_404_without_current_snapshot(client: httpx.AsyncClient) -> None:
    with SessionLocal.begin() as session:
        session.execute(update(ReviewEvidenceSnapshot).values(is_active=False))
    response = await client.get(f"{API}/review-evidence/overview")
    assert response.status_code == 404


def test_api_adapter_has_no_artifact_or_ml_runtime_dependency() -> None:
    source = inspect.getsource(routes)
    assert "review_evidence" in source
    for module in (routes, review_evidence):
        text = inspect.getsource(module)
        assert "hqai_ml" not in text and "read_parquet" not in text and "artifacts/" not in text
