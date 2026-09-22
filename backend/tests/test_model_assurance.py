"""Model Assurance publication, persistence, and authenticated read-API tests."""

from __future__ import annotations

import copy
import hashlib
import inspect
import json
import uuid
from collections.abc import Iterator

import httpx
import pytest
from sqlalchemy import delete, select, update

from app.api import routes
from app.db.models import ModelAssuranceCapability, ModelAssuranceSnapshot
from app.db.session import SessionLocal
from app.services import model_assurance
from app.services.common import ConflictError, ValidationError
from conftest import API

IDENTITY_FIELDS = (
    "run_id",
    "scientific_identity_sha256",
    "artifact_sha256",
    "dataset_identity_sha256",
    "config_identity_sha256",
    "code_identity_sha256",
    "model_identity",
    "estimand_id",
    "calibration_identity",
    "hierarchy_identity",
    "pressure_provider_identity",
    "prioritization_identity",
    "scenario_identity",
    "decision_alternative_identity",
)
TEST_PREFIX = "pytest-assurance-"


def _canonical(value: dict) -> bytes:
    return json.dumps(value, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":")).encode()


def _identity(value=None, *, status="NOT_APPLICABLE", reason="not applicable in synthetic evidence") -> dict:
    return {"status": status, "value": value, "reason": reason}


def _capability(capability_id: str = "flow_pressure") -> dict:
    identities = {field: _identity() for field in IDENTITY_FIELDS}
    identities.update(
        run_id=_identity("synthetic-run-v1", status="AVAILABLE", reason="synthetic test run"),
        scientific_identity_sha256=_identity("a" * 64, status="AVAILABLE", reason="synthetic test identity"),
        artifact_sha256=_identity(["b" * 64, "c" * 64], status="AVAILABLE", reason="synthetic artifacts"),
        dataset_identity_sha256=_identity("d" * 64, status="AVAILABLE", reason="synthetic dataset"),
        config_identity_sha256=_identity("e" * 64, status="AVAILABLE", reason="synthetic config"),
        code_identity_sha256=_identity("f" * 64, status="AVAILABLE", reason="synthetic code"),
        pressure_provider_identity=_identity(
            "historical_flow_proxy_v1", status="AVAILABLE", reason="accepted pressure provider"
        ),
    )
    return {
        "capability_id": capability_id,
        "display_name": "Historical-flow pressure",
        "evidence_status": "ACCEPTED",
        "acceptance_verdict": "ACCEPT",
        "product_consumption_status": "ELIGIBLE_AFTER_INGESTION",
        "run_manifest": "artifacts/ignored/source/run.json",
        "identities": identities,
        "evidence": {"target": "registrations", "pressure_basis": "historical_flow_proxy_v1"},
        "support": {
            "support_semantics": ["DIRECT_SUPPORTED", "FALLBACK_LIMITED", "UNSUPPORTED"],
            "range_semantics": ["COMPLETE", "RANGE_LIMITED"],
        },
        "governance": {
            "human_review_required": True,
            "autonomous_action": False,
            "capacity_checked": False,
            "causal_effect_claimed": False,
            "serving_claim": False,
            "physical_feasibility_status": "NOT_VALIDATED",
            "promotion_status": "HUMAN_REVIEW_ONLY",
        },
        "freshness": {"state": "UNKNOWN", "reason": "synthetic test has no customer SLA"},
        "source_lineage": ["artifacts/ignored/source/run.json"],
        "limitations": ["Not physical capacity."],
        "allowed_claims": ["Historical-flow warning for human review."],
        "forbidden_claims": ["capacity optimizer", "autonomous routing"],
    }


def _bundle(assurance_id: str | None = None, capability_ids: tuple[str, ...] = ("flow_pressure",)) -> dict:
    payload = {
        "schema_version": "model_assurance_v1",
        "contract_version": "1.0.0",
        "assurance_id": assurance_id or f"{TEST_PREFIX}{uuid.uuid4().hex}",
        "source_code_commit": "1" * 40,
        "ml_freeze_status": "ML_CORE_CLOSED_FROZEN",
        "product_contract_version": "model-assurance-product-v1",
        "generated_at": "2026-09-22T20:00:00+00:00",
        "capabilities": [_capability(capability_id) for capability_id in capability_ids],
        "failed_evidence_history": [],
        "claim_boundaries": {
            "pressure_basis": "historical_flow_proxy_v1",
            "decision_alternative_semantics": "retrospective mathematical alternatives for human review",
        },
        "monitoring_expectations": [{"id": "lineage_hash_mismatch", "implementation_status": "FUTURE_EXPECTATION"}],
        "freshness_policy": {"sla_thresholds": None, "states": ["FRESH", "STALE", "DEGRADED", "UNKNOWN"]},
    }
    projection = copy.deepcopy(payload)
    projection.pop("generated_at")
    payload["assurance_identity_sha256"] = hashlib.sha256(_canonical(projection)).hexdigest()
    return payload


def _raw(payload: dict) -> bytes:
    return (json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode()


def _parsed(payload: dict) -> model_assurance.ParsedAssuranceBundle:
    return model_assurance.parse_assurance_bundle(_raw(payload))


def test_assurance_api_adapter_uses_service_without_artifact_file_access() -> None:
    source = "\n".join(
        inspect.getsource(endpoint)
        for endpoint in (
            routes.get_model_assurance,
            routes.get_model_assurance_capabilities,
            routes.get_model_assurance_capability,
        )
    )
    assert "model_assurance." in source
    assert "hqai_ml" not in source
    assert "open(" not in source
    assert ".read_bytes(" not in source
    assert ".read_text(" not in source


@pytest.fixture(autouse=True)
def preserve_current_snapshot() -> Iterator[None]:
    with SessionLocal() as session:
        previous = session.scalar(select(ModelAssuranceSnapshot.id).where(ModelAssuranceSnapshot.is_active.is_(True)))
    yield
    with SessionLocal.begin() as session:
        session.execute(update(ModelAssuranceSnapshot).values(is_active=False))
        session.execute(
            delete(ModelAssuranceSnapshot).where(ModelAssuranceSnapshot.assurance_id.startswith(TEST_PREFIX))
        )
        if previous is not None:
            session.execute(
                update(ModelAssuranceSnapshot).where(ModelAssuranceSnapshot.id == previous).values(is_active=True)
            )


def test_publication_succeeds_and_preserves_capability_and_governance() -> None:
    parsed = _parsed(_bundle(capability_ids=("flow_pressure", "signal_prioritization")))
    with SessionLocal() as session:
        result = model_assurance.publish(session, parsed)
    assert result.created is True

    with SessionLocal() as session:
        snapshot = session.get(ModelAssuranceSnapshot, result.snapshot_id)
        rows = list(
            session.scalars(
                select(ModelAssuranceCapability)
                .where(ModelAssuranceCapability.snapshot_id == result.snapshot_id)
                .order_by(ModelAssuranceCapability.capability_id)
            )
        )
        assert snapshot is not None and snapshot.is_active is True and snapshot.capability_count == 2
        assert [row.capability_id for row in rows] == ["flow_pressure", "signal_prioritization"]
        assert rows[0].artifact_identity == ["b" * 64, "c" * 64]
        assert rows[0].pressure_provider_identity == "historical_flow_proxy_v1"
        assert rows[0].human_review_required is True
        assert rows[0].autonomous_action is False
        assert rows[0].capacity_checked is False
        assert rows[0].details["source_lineage"] == ["artifacts/ignored/source/run.json"]


def test_same_assurance_identity_is_idempotent_even_when_audit_timestamp_changes() -> None:
    payload = _bundle()
    first = _parsed(payload)
    with SessionLocal() as session:
        created = model_assurance.publish(session, first)

    payload["generated_at"] = "2030-01-01T00:00:00+00:00"
    second = _parsed(payload)
    assert second.bundle_sha256 != first.bundle_sha256
    with SessionLocal() as session:
        replay = model_assurance.publish(session, second)
        count = len(
            list(
                session.scalars(
                    select(ModelAssuranceSnapshot).where(ModelAssuranceSnapshot.assurance_id == payload["assurance_id"])
                )
            )
        )
    assert replay.created is False
    assert replay.snapshot_id == created.snapshot_id
    assert count == 1


def test_conflicting_publication_fails_without_changing_current_snapshot() -> None:
    payload = _bundle()
    with SessionLocal() as session:
        first = model_assurance.publish(session, _parsed(payload))

    conflicting = copy.deepcopy(payload)
    conflicting["capabilities"][0]["display_name"] = "Changed content"
    projection = copy.deepcopy(conflicting)
    projection.pop("assurance_identity_sha256")
    projection.pop("generated_at")
    conflicting["assurance_identity_sha256"] = hashlib.sha256(_canonical(projection)).hexdigest()

    with SessionLocal() as session, pytest.raises(ConflictError, match="different identity"):
        model_assurance.publish(session, _parsed(conflicting))

    with SessionLocal() as session:
        current = session.scalar(select(ModelAssuranceSnapshot).where(ModelAssuranceSnapshot.is_active.is_(True)))
        assert current is not None and current.id == first.snapshot_id
        assert current.assurance_identity_sha256 == payload["assurance_identity_sha256"]


def test_new_snapshot_switches_current_atomically_and_preserves_history() -> None:
    with SessionLocal() as session:
        first = model_assurance.publish(session, _parsed(_bundle()))
    with SessionLocal() as session:
        second = model_assurance.publish(session, _parsed(_bundle()))
    with SessionLocal() as session:
        snapshots = {
            row.id: row
            for row in session.scalars(
                select(ModelAssuranceSnapshot).where(
                    ModelAssuranceSnapshot.id.in_([first.snapshot_id, second.snapshot_id])
                )
            )
        }
        assert len(snapshots) == 2
        assert snapshots[first.snapshot_id].is_active is False
        assert snapshots[second.snapshot_id].is_active is True


def test_malformed_and_duplicate_capability_bundles_fail_before_database_write() -> None:
    malformed = _bundle()
    malformed["source_code_commit"] = "not-a-commit"
    with pytest.raises(ValidationError, match="invalid Model Assurance bundle"):
        model_assurance.parse_assurance_bundle(_raw(malformed))

    duplicate = _bundle(capability_ids=("flow_pressure", "flow_pressure"))
    with pytest.raises(ValidationError, match="duplicate capability_id"):
        model_assurance.parse_assurance_bundle(_raw(duplicate))


def test_declared_assurance_identity_must_match_canonical_content() -> None:
    payload = _bundle()
    payload["assurance_identity_sha256"] = "0" * 64
    with pytest.raises(ValidationError, match="does not match canonical content"):
        model_assurance.parse_assurance_bundle(_raw(payload))


@pytest.fixture
def published_snapshot() -> Iterator[model_assurance.PublicationResult]:
    with SessionLocal() as session:
        result = model_assurance.publish(
            session,
            _parsed(_bundle(capability_ids=("flow_pressure", "signal_prioritization"))),
        )
    yield result


@pytest.mark.anyio
async def test_assurance_api_requires_authentication(
    anon_client: httpx.AsyncClient, published_snapshot: model_assurance.PublicationResult
) -> None:
    for path in (
        "/model-assurance",
        "/model-assurance/capabilities",
        "/model-assurance/capabilities/flow_pressure",
    ):
        assert (await anon_client.get(f"{API}{path}")).status_code == 401


@pytest.mark.anyio
async def test_assurance_api_current_list_detail_and_provenance(
    client: httpx.AsyncClient, published_snapshot: model_assurance.PublicationResult
) -> None:
    current = await client.get(f"{API}/model-assurance")
    assert current.status_code == 200
    summary = current.json()
    assert summary["assurance_id"].startswith(TEST_PREFIX)
    assert summary["assurance_identity_sha256"] == published_snapshot.assurance_identity_sha256
    assert (
        summary["bundle_sha256"]
        == hashlib.sha256(
            _raw(_bundle(summary["assurance_id"], ("flow_pressure", "signal_prioritization")))
        ).hexdigest()
    )
    assert summary["source_code_commit"] == "1" * 40
    assert summary["capability_count"] == 2

    listing = await client.get(f"{API}/model-assurance/capabilities")
    assert listing.status_code == 200
    assert [row["capability_id"] for row in listing.json()] == ["flow_pressure", "signal_prioritization"]

    detail = await client.get(f"{API}/model-assurance/capabilities/flow_pressure")
    assert detail.status_code == 200
    body = detail.json()
    assert body["evidence_status"] == "ACCEPTED"
    assert body["product_consumption_status"] == "ELIGIBLE_AFTER_INGESTION"
    assert body["identities"]["run_id"]["value"] == "synthetic-run-v1"
    assert body["governance"]["human_review_required"] is True
    assert body["governance"]["autonomous_action"] is False
    assert body["freshness"]["state"] == "UNKNOWN"
    assert "run_manifest" not in body
    assert "source_lineage" not in body

    assert (await client.get(f"{API}/model-assurance/capabilities/not_real")).status_code == 404


@pytest.mark.anyio
async def test_assurance_api_returns_404_without_current_snapshot(
    client: httpx.AsyncClient, published_snapshot: model_assurance.PublicationResult
) -> None:
    with SessionLocal.begin() as session:
        session.execute(update(ModelAssuranceSnapshot).values(is_active=False))
    try:
        assert (await client.get(f"{API}/model-assurance")).status_code == 404
        assert (await client.get(f"{API}/model-assurance/capabilities")).status_code == 404
    finally:
        with SessionLocal.begin() as session:
            session.execute(
                update(ModelAssuranceSnapshot)
                .where(ModelAssuranceSnapshot.id == published_snapshot.snapshot_id)
                .values(is_active=True)
            )
