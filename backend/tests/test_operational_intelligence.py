"""Operational-intelligence publication, query, and API contract tests."""

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
    OperationalSignal,
)
from app.db.session import SessionLocal
from app.schemas.operational_intelligence import OperationalIntelligenceBundle
from app.services import operational_intelligence
from app.services.common import ConflictError, ValidationError
from conftest import API

TEST_PREFIX = "pytest-operational-"
ASSURANCE_IDENTITY = "a" * 64
SOURCE_KEYS = (
    "flow_forecast",
    "flow_quantile",
    "flow_calibration",
    "flow_hierarchy",
    "flow_pressure",
    "signal_prioritization",
)
CAPABILITY_BY_SOURCE = {
    "flow_forecast": "flow_point_forecast",
    "flow_quantile": "flow_quantile_forecast",
    "flow_calibration": "flow_temporal_calibration",
    "flow_hierarchy": "flow_hierarchical_coherence",
    "flow_pressure": "preventive_flow_pressure",
    "signal_prioritization": "signal_prioritization",
}


def _canonical(value: dict) -> bytes:
    return json.dumps(value, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":")).encode()


def _provenance(index: int) -> dict:
    digit = format(index, "x")
    return {
        "run_id": f"synthetic-run-{index}",
        "scientific_identity_sha256": digit * 64,
        "artifact_sha256": format(index + 6, "x") * 64,
        "dataset_identity_sha256": "d" * 64,
        "config_identity_sha256": "e" * 64,
        "code_identity_sha256": "f" * 64,
    }


def _forecast(*, fallback: bool = False) -> dict:
    return {
        "series_id": "hp:H001:P01" if not fallback else "hp:H002:P01",
        "level": "hospital",
        "origin": "2025-03-17",
        "target_date": "2025-03-18",
        "horizon": 1,
        "target": "registrations",
        "org_code": "H001" if not fallback else "H002",
        "region_code": "R1",
        "profile_code": "P01",
        "central_value": 5.0 if not fallback else 2.0,
        "central_semantics": "P50",
        "raw_quantiles": {
            "p10": 3.0 if not fallback else 1.0,
            "p50": 5.0 if not fallback else 2.0,
            "p90": 8.0 if not fallback else 4.0,
            "semantics": "UNCHANGED_MODEL_EVIDENCE",
        },
        "calibrated_uncertainty": None
        if fallback
        else {
            "lower": 2.0,
            "upper": 9.0,
            "nominal_coverage": 0.8,
            "calibration_status": "CALIBRATED",
            "support_class": "hospital_direct",
            "calibration_version": "temporal-count-interval-calibration-v1",
        },
        "calibration_status": "INSUFFICIENT_SUPPORT" if fallback else "CALIBRATED",
        "prediction_source": "REGION_PROFILE_FALLBACK" if fallback else "DIRECT",
        "hierarchy_status": "BOTTOM_UP_CHILD_UNCHANGED",
        "support_status": "FALLBACK_LIMITED" if fallback else "DIRECT_SUPPORTED",
        "fallback_status": "REGION_PROFILE_FALLBACK" if fallback else "NOT_APPLICABLE",
        "uncertainty_status": "INSUFFICIENT_CALIBRATION_SUPPORT" if fallback else "CALIBRATED",
        "provenance_keys": ["flow_quantile", "flow_calibration", "flow_hierarchy"],
        "evidence_facts": ["Synthetic accepted forecast evidence."],
        "limitations": ["Historical-flow counts are not physical capacity."],
    }


def _pressure_signal(*, fallback: bool = False) -> dict:
    org = "H002" if fallback else "H001"
    return {
        "signal_id": "signal-fallback" if fallback else "signal-direct",
        "signal_type": "preventive_flow_pressure",
        "series_id": f"hp:{org}:P01",
        "origin": "2025-03-17",
        "target": "registrations",
        "org_code": org,
        "region_code": "R1",
        "profile_code": "P01",
        "inbox_rank": 2 if fallback else 1,
        "severity": "ELEVATED" if fallback else "HIGH",
        "headline": "Historical-flow pressure requires attention.",
        "concise_reason": "Forecast evidence crosses its historical-flow reference.",
        "materiality_status": "MATERIAL",
        "support_status": "FALLBACK_LIMITED" if fallback else "DIRECT_SUPPORTED",
        "fallback_status": "REGION_PROFILE_FALLBACK" if fallback else "NOT_APPLICABLE",
        "uncertainty_status": "INSUFFICIENT_CALIBRATION_SUPPORT" if fallback else "CALIBRATED",
        "pressure_basis": "historical_flow_proxy_v1",
        "threshold_value": 3.0,
        "threshold_status": "SUPPORTED",
        "forecast_value": 5.0,
        "uncertainty_lower": None if fallback else 4.0,
        "uncertainty_upper": None if fallback else 9.0,
        "first_crossing_date": "2025-03-18",
        "lead_time_days": 1,
        "observed_anomaly_status": "NONE",
        "observed_anomaly_present": False,
        "data_freshness": "2025-03-17",
        "reason_codes": ["HISTORICAL_FLOW_THRESHOLD_CROSSING"],
        "evidence_facts": ["Threshold is an origin-legal historical-flow reference."],
        "provenance_keys": ["flow_pressure", "flow_hierarchy", "signal_prioritization"],
        "anomaly_evidence": None,
        "limitations": ["Not beds, occupancy, staffed capacity, or physical overload."],
    }


def _anomaly_signal() -> dict:
    return {
        "signal_id": "signal-anomaly",
        "signal_type": "observed_unusual_flow",
        "series_id": "hp:H001:P01",
        "origin": "2025-03-17",
        "target": "registrations",
        "org_code": "H001",
        "region_code": "R1",
        "profile_code": "P01",
        "inbox_rank": 3,
        "severity": "ELEVATED",
        "headline": "Observed flow is unusual relative to its history.",
        "concise_reason": "A robust historical residual threshold was crossed.",
        "materiality_status": None,
        "support_status": "DIRECT_SUPPORTED",
        "fallback_status": "NOT_APPLICABLE",
        "uncertainty_status": "UNAVAILABLE",
        "pressure_basis": None,
        "threshold_value": None,
        "threshold_status": None,
        "forecast_value": None,
        "uncertainty_lower": None,
        "uncertainty_upper": None,
        "first_crossing_date": None,
        "lead_time_days": None,
        "observed_anomaly_status": "UNUSUAL_HIGH",
        "observed_anomaly_present": True,
        "data_freshness": "2025-03-17",
        "reason_codes": ["OBSERVED_WEEKLY_RESIDUAL_EXCEEDS_ROBUST_THRESHOLD"],
        "evidence_facts": ["Observed residual is evaluated separately from future pressure."],
        "provenance_keys": ["flow_pressure", "signal_prioritization"],
        "anomaly_evidence": {
            "observed_value": 17.0,
            "weekly_residual": 8.0,
            "reference_median_residual": 0.0,
            "reference_mad": 1.0,
            "robust_z": 5.4,
            "reference_sample_count": 56,
            "reference_max_date": "2025-03-16",
            "causal_claim": False,
        },
        "limitations": ["Unusual flow is not a causal or capacity incident claim."],
    }


def _bundle(
    publication_id: str | None = None,
    *,
    empty: bool = False,
    include_fallback: bool = True,
) -> dict:
    payload = {
        "schema_version": "operational_intelligence_v1",
        "contract_version": "1.0.0",
        "publication_id": publication_id or f"{TEST_PREFIX}{uuid.uuid4().hex}",
        "publication_identity_sha256": "0" * 64,
        "assurance_identity_sha256": ASSURANCE_IDENTITY,
        "source_code_commit": "1" * 40,
        "current_origin": "2025-03-17",
        "freshness_state": "DEGRADED" if empty else "UNKNOWN",
        "publication_status": "EMPTY" if empty else "AVAILABLE",
        "generated_at": "2026-09-22T22:00:00+00:00",
        "source_provenance": {key: _provenance(index) for index, key in enumerate(SOURCE_KEYS, 1)},
        "limitations": ["Historical-flow intelligence for human attention; not physical capacity."],
        "forecasts": [] if empty else [_forecast(), *([_forecast(fallback=True)] if include_fallback else [])],
        "signals": []
        if empty
        else [
            _pressure_signal(),
            *([_pressure_signal(fallback=True)] if include_fallback else []),
            _anomaly_signal(),
        ],
    }
    return _set_identity(payload)


def _set_identity(payload: dict) -> dict:
    validated = OperationalIntelligenceBundle.model_validate(payload)
    projection = validated.model_dump(mode="json")
    projection.pop("publication_identity_sha256")
    projection.pop("generated_at")
    payload["publication_identity_sha256"] = hashlib.sha256(_canonical(projection)).hexdigest()
    return payload


def _raw(payload: dict) -> bytes:
    return (json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode()


def _parsed(payload: dict) -> operational_intelligence.ParsedOperationalBundle:
    return operational_intelligence.parse_bundle(_raw(payload))


@pytest.fixture(autouse=True)
def preserve_current_snapshot() -> Iterator[None]:
    assurance_created = False
    with SessionLocal.begin() as session:
        previous = session.scalar(
            select(OperationalIntelligenceSnapshot.id).where(OperationalIntelligenceSnapshot.is_active.is_(True))
        )
        assurance = session.scalar(
            select(ModelAssuranceSnapshot).where(ModelAssuranceSnapshot.assurance_identity_sha256 == ASSURANCE_IDENTITY)
        )
        if assurance is None:
            assurance = ModelAssuranceSnapshot(
                assurance_id=f"{TEST_PREFIX}assurance",
                contract_version="1.0.0",
                schema_version="model_assurance_v1",
                assurance_identity_sha256=ASSURANCE_IDENTITY,
                bundle_sha256="9" * 64,
                source_code_commit="1" * 40,
                ml_freeze_status="ML_CORE_CLOSED_FROZEN",
                product_contract_version="model-assurance-product-v1",
                generated_at=dt.datetime(2026, 9, 22, tzinfo=dt.UTC),
                is_active=False,
                capability_count=len(SOURCE_KEYS),
                failed_evidence_history=[],
                claim_boundaries={"pressure_basis": "historical_flow_proxy_v1"},
                monitoring_expectations=[],
                freshness_policy={"sla_thresholds": None},
            )
            session.add(assurance)
            session.flush()
            for index, source_key in enumerate(SOURCE_KEYS, 1):
                provenance = _provenance(index)
                session.add(
                    ModelAssuranceCapability(
                        snapshot_id=assurance.id,
                        capability_id=CAPABILITY_BY_SOURCE[source_key],
                        display_name=source_key,
                        evidence_status="ACCEPTED",
                        acceptance_verdict="ACCEPT",
                        product_consumption_status="ELIGIBLE_AFTER_INGESTION",
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
                        pressure_provider_identity="historical_flow_proxy_v1"
                        if source_key == "flow_pressure"
                        else None,
                        prioritization_identity="signals-inbox-v1" if source_key == "signal_prioritization" else None,
                        scenario_identity=None,
                        decision_alternative_identity=None,
                        human_review_required=True,
                        autonomous_action=False,
                        capacity_checked=False,
                        causal_effect_claimed=False,
                        serving_claim=False,
                        physical_feasibility_status="NOT_APPLICABLE",
                        promotion_status="HUMAN_REVIEW_ONLY",
                        freshness_state="UNKNOWN",
                        details={},
                    )
                )
            assurance_created = True
    yield
    with SessionLocal.begin() as session:
        session.execute(update(OperationalIntelligenceSnapshot).values(is_active=False))
        session.execute(
            delete(OperationalIntelligenceSnapshot).where(
                OperationalIntelligenceSnapshot.publication_id.startswith(TEST_PREFIX)
            )
        )
        if previous is not None:
            session.execute(
                update(OperationalIntelligenceSnapshot)
                .where(OperationalIntelligenceSnapshot.id == previous)
                .values(is_active=True)
            )
        if assurance_created:
            session.execute(
                delete(ModelAssuranceSnapshot).where(
                    ModelAssuranceSnapshot.assurance_identity_sha256 == ASSURANCE_IDENTITY
                )
            )


def test_publication_preserves_forecasts_signals_support_and_lineage() -> None:
    parsed = _parsed(_bundle())
    with SessionLocal() as session:
        result = operational_intelligence.publish(session, parsed)
    with SessionLocal() as session:
        snapshot = session.get(OperationalIntelligenceSnapshot, result.snapshot_id)
        forecasts = list(
            session.scalars(
                select(OperationalForecast)
                .where(OperationalForecast.snapshot_id == result.snapshot_id)
                .order_by(OperationalForecast.series_id)
            )
        )
        signals = list(
            session.scalars(
                select(OperationalSignal)
                .where(OperationalSignal.snapshot_id == result.snapshot_id)
                .order_by(OperationalSignal.inbox_rank)
            )
        )
    assert snapshot is not None and snapshot.forecast_count == 2 and snapshot.signal_count == 3
    assert snapshot.source_provenance["flow_hierarchy"]["run_id"] == "synthetic-run-4"
    assert forecasts[0].raw_p50 is not None and forecasts[0].calibrated_lower is not None
    assert forecasts[1].fallback_status == "REGION_PROFILE_FALLBACK"
    assert forecasts[1].calibrated_lower is None
    assert [row.inbox_rank for row in signals] == [1, 2, 3]
    assert signals[0].pressure_basis == "historical_flow_proxy_v1"
    assert signals[2].signal_type == "observed_unusual_flow"
    assert signals[2].pressure_basis is None
    assert signals[2].details["anomaly_evidence"]["causal_claim"] is False


def test_same_identity_is_idempotent_and_new_snapshot_switch_is_atomic() -> None:
    payload = _bundle()
    with SessionLocal() as session:
        first = operational_intelligence.publish(session, _parsed(payload))
    payload["generated_at"] = "2030-01-01T00:00:00+00:00"
    with SessionLocal() as session:
        replay = operational_intelligence.publish(session, _parsed(payload))
    assert replay.created is False and replay.snapshot_id == first.snapshot_id

    with SessionLocal() as session:
        second = operational_intelligence.publish(session, _parsed(_bundle()))
    with SessionLocal() as session:
        snapshots = {
            row.id: row
            for row in session.scalars(
                select(OperationalIntelligenceSnapshot).where(
                    OperationalIntelligenceSnapshot.id.in_([first.snapshot_id, second.snapshot_id])
                )
            )
        }
    assert snapshots[first.snapshot_id].is_active is False
    assert snapshots[second.snapshot_id].is_active is True


def test_conflict_and_malformed_input_fail_closed() -> None:
    payload = _bundle()
    with SessionLocal() as session:
        first = operational_intelligence.publish(session, _parsed(payload))

    conflict = copy.deepcopy(payload)
    conflict["signals"][0]["headline"] = "Changed content"
    _set_identity(conflict)
    with SessionLocal() as session, pytest.raises(ConflictError, match="different identity"):
        operational_intelligence.publish(session, _parsed(conflict))
    with SessionLocal() as session:
        current = session.scalar(
            select(OperationalIntelligenceSnapshot).where(OperationalIntelligenceSnapshot.is_active.is_(True))
        )
        assert current is not None and current.id == first.snapshot_id

    malformed = _bundle()
    malformed["source_provenance"]["flow_pressure"]["scientific_identity_sha256"] = "not-a-sha"
    with pytest.raises(ValidationError, match="invalid operational-intelligence bundle"):
        operational_intelligence.parse_bundle(_raw(malformed))


def test_unassured_source_provenance_fails_before_current_switch() -> None:
    accepted = _bundle()
    with SessionLocal() as session:
        first = operational_intelligence.publish(session, _parsed(accepted))
    mismatched = _bundle()
    mismatched["source_provenance"]["flow_pressure"]["scientific_identity_sha256"] = "b" * 64
    _set_identity(mismatched)
    with SessionLocal() as session, pytest.raises(ValidationError, match="does not match assured capability"):
        operational_intelligence.publish(session, _parsed(mismatched))
    with SessionLocal() as session:
        current = session.scalar(
            select(OperationalIntelligenceSnapshot).where(OperationalIntelligenceSnapshot.is_active.is_(True))
        )
        assert current is not None and current.id == first.snapshot_id


def test_semantic_validation_keeps_calibration_pressure_and_anomaly_distinct() -> None:
    conflated = _bundle()
    conflated["forecasts"][1]["calibrated_uncertainty"] = {
        "lower": 1.0,
        "upper": 3.0,
        "nominal_coverage": 0.8,
        "calibration_status": "CALIBRATED",
        "support_class": "invented",
        "calibration_version": "invented",
    }
    with pytest.raises(ValidationError, match="non-calibrated forecast"):
        operational_intelligence.parse_bundle(_raw(conflated))

    physical = _bundle()
    physical["signals"][0]["pressure_basis"] = "physical_capacity"
    with pytest.raises(ValidationError, match="historical_flow_proxy_v1"):
        operational_intelligence.parse_bundle(_raw(physical))

    anomaly = _bundle()
    anomaly["signals"][2]["threshold_value"] = 10.0
    with pytest.raises(ValidationError, match="distinct from preventive pressure"):
        operational_intelligence.parse_bundle(_raw(anomaly))


@pytest.fixture
def published_snapshot() -> Iterator[operational_intelligence.PublicationResult]:
    with SessionLocal() as session:
        result = operational_intelligence.publish(session, _parsed(_bundle()))
    yield result


@pytest.mark.anyio
async def test_operational_api_requires_authentication(
    anon_client: httpx.AsyncClient,
    published_snapshot: operational_intelligence.PublicationResult,
) -> None:
    for path in (
        "/operational-intelligence/overview",
        "/operational-intelligence/signals",
        "/operational-intelligence/signals/signal-direct",
        "/operational-intelligence/regions/R1",
        "/operational-intelligence/hospitals/H001/profiles/P01",
        "/operational-intelligence/forecasts",
    ):
        assert (await anon_client.get(f"{API}{path}")).status_code == 401


@pytest.mark.anyio
async def test_overview_signals_filters_and_signal_provenance(
    client: httpx.AsyncClient,
    published_snapshot: operational_intelligence.PublicationResult,
) -> None:
    overview = (await client.get(f"{API}/operational-intelligence/overview")).json()
    assert overview["national"]["total_signals"] == 3
    assert overview["national"]["preventive_pressure"] == 2
    assert overview["national"]["observed_unusual_flow"] == 1
    assert overview["snapshot"]["assurance_identity_sha256"] == ASSURANCE_IDENTITY

    response = await client.get(
        f"{API}/operational-intelligence/signals",
        params={"signal_type": "preventive_flow_pressure", "support": "DIRECT_SUPPORTED"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["items"][0]["signal_id"] == "signal-direct"
    assert body["items"][0]["pressure_basis"] == "historical_flow_proxy_v1"

    detail = (await client.get(f"{API}/operational-intelligence/signals/signal-direct")).json()
    assert set(detail["source_provenance"]) == {
        "flow_pressure",
        "flow_hierarchy",
        "signal_prioritization",
    }
    assert detail["publication_identity_sha256"] == published_snapshot.publication_identity_sha256
    assert "artifact_path" not in json.dumps(detail)


@pytest.mark.anyio
async def test_region_hospital_and_forecast_uncertainty_contract(
    client: httpx.AsyncClient,
    published_snapshot: operational_intelligence.PublicationResult,
) -> None:
    region = (await client.get(f"{API}/operational-intelligence/regions/R1")).json()
    assert region["counts"]["total_signals"] == 3
    assert [row["inbox_rank"] for row in region["top_signals"]] == [1, 2, 3]

    hospital = (await client.get(f"{API}/operational-intelligence/hospitals/H001/profiles/P01")).json()
    assert hospital["forecast_point_count"] == 1
    assert hospital["available_targets"] == ["registrations"]
    assert hospital["counts"]["observed_unusual_flow"] == 1

    forecast = await client.get(
        f"{API}/operational-intelligence/forecasts",
        params={"org": "H001", "profile": "P01", "target": "registrations"},
    )
    assert forecast.status_code == 200
    point = forecast.json()["items"][0]
    assert point["central_semantics"] == "P50"
    assert point["raw_quantiles"]["semantics"] == "UNCHANGED_MODEL_EVIDENCE"
    assert point["calibrated_uncertainty"]["calibration_status"] == "CALIBRATED"
    assert point["uncertainty_status"] == "CALIBRATED"

    fallback = (await client.get(f"{API}/operational-intelligence/forecasts", params={"org": "H002"})).json()["items"][
        0
    ]
    assert fallback["support_status"] == "FALLBACK_LIMITED"
    assert fallback["raw_quantiles"] is not None
    assert fallback["calibrated_uncertainty"] is None


@pytest.mark.anyio
async def test_empty_degraded_publication_is_explicit(
    client: httpx.AsyncClient,
    published_snapshot: operational_intelligence.PublicationResult,
) -> None:
    with SessionLocal() as session:
        operational_intelligence.publish(session, _parsed(_bundle(empty=True)))
    overview = (await client.get(f"{API}/operational-intelligence/overview")).json()
    assert overview["snapshot"]["publication_status"] == "EMPTY"
    assert overview["snapshot"]["freshness_state"] == "DEGRADED"
    assert overview["national"]["total_signals"] == 0
    assert (await client.get(f"{API}/operational-intelligence/signals")).json()["items"] == []
    assert (await client.get(f"{API}/operational-intelligence/forecasts")).json()["items"] == []
    assert (await client.get(f"{API}/operational-intelligence/regions/R1")).status_code == 404
    assert (await client.get(f"{API}/operational-intelligence/hospitals/H001/profiles/P01")).status_code == 404


def test_api_adapter_has_no_artifact_or_ml_runtime_dependency() -> None:
    source = "\n".join(
        inspect.getsource(endpoint)
        for endpoint in (
            routes.get_operational_intelligence_overview,
            routes.get_operational_signals,
            routes.get_operational_signal,
            routes.get_operational_intelligence_region,
            routes.get_operational_intelligence_hospital_profile,
            routes.get_operational_forecasts,
        )
    )
    assert "operational_intelligence." in source
    assert "hqai_ml" not in source
    assert "open(" not in source
    assert ".read_bytes(" not in source
    assert ".read_text(" not in source
