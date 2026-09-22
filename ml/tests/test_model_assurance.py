from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from hqai_ml.assurance import (
    IDENTITY_FIELDS,
    AssuranceContractError,
    assurance_identity_payload,
    build_assurance,
    canonical_json_bytes,
    validate_assurance_payload,
    verify_evidence_sources,
    write_assurance_bundle,
)

ROOT = Path(__file__).resolve().parents[2]
CONFIG = ROOT / "ml" / "configs" / "model_assurance.yaml"
SCHEMA = ROOT / "docs" / "model-assurance-contract-v1.schema.json"

EXPECTED_CAPABILITIES = {
    "decision_alternatives",
    "flow_hierarchical_coherence",
    "flow_point_forecast",
    "flow_quantile_forecast",
    "flow_temporal_calibration",
    "forecast_stress_test",
    "observed_unusual_flow",
    "patient_journey_competing_risk_baseline",
    "patient_journey_competing_risk_ml_challenger",
    "patient_journey_hospitalization",
    "patient_journey_refusal",
    "preventive_flow_pressure",
    "signal_prioritization",
}


def bundle(timestamp: str = "2026-09-22T18:00:00+00:00") -> dict:
    return build_assurance(CONFIG, generated_at=timestamp)


def by_id(payload: dict) -> dict[str, dict]:
    return {item["capability_id"]: item for item in payload["capabilities"]}


def test_inventory_and_contract_are_complete() -> None:
    payload = bundle()
    assert payload["schema_version"] == "model_assurance_v1"
    assert payload["contract_version"] == "1.0.0"
    assert payload["ml_freeze_status"] == "ML_CORE_CLOSED_FROZEN"
    assert {item["capability_id"] for item in payload["capabilities"]} == EXPECTED_CAPABILITIES
    assert [item["capability_id"] for item in payload["capabilities"]] == sorted(EXPECTED_CAPABILITIES)
    for capability in payload["capabilities"]:
        assert tuple(capability["identities"]) == IDENTITY_FIELDS
        for identity in capability["identities"].values():
            assert identity["status"] in {"AVAILABLE", "UNKNOWN", "NOT_APPLICABLE"}
            if identity["status"] != "AVAILABLE":
                assert identity["value"] is None
                assert identity["reason"]


def test_assurance_identity_is_canonical_and_excludes_audit_timestamp() -> None:
    first = bundle("2026-09-22T18:00:00+00:00")
    second = bundle("2030-01-01T00:00:00+00:00")
    assert first["assurance_identity_sha256"] == second["assurance_identity_sha256"]
    assert canonical_json_bytes(assurance_identity_payload(first)) == canonical_json_bytes(
        assurance_identity_payload(second)
    )
    assert first != second


def test_claim_boundaries_and_governance_cannot_drift() -> None:
    payload = bundle()
    boundaries = payload["claim_boundaries"]
    assert boundaries["pressure_basis"] == "historical_flow_proxy_v1"
    assert boundaries["decision_alternative_semantics"] == ("retrospective mathematical alternatives for human review")
    forbidden = set(boundaries["forbidden_project_descriptions_and_claims"])
    assert {"AI recommender", "patient router", "capacity optimizer", "Digital Twin"} <= forbidden
    for capability in payload["capabilities"]:
        governance = capability["governance"]
        assert governance["autonomous_action"] is False
        assert governance["capacity_checked"] is False
        assert governance["causal_effect_claimed"] is False
        assert governance["serving_claim"] is False

    mutated = copy.deepcopy(payload)
    mutated["claim_boundaries"]["pressure_basis"] = "physical_capacity_provider_v1"
    with pytest.raises(AssuranceContractError, match="historical_flow_proxy_v1"):
        validate_assurance_payload(mutated)


def test_acceptance_product_support_and_freshness_are_separate() -> None:
    capabilities = by_id(bundle())
    rejected = capabilities["patient_journey_competing_risk_ml_challenger"]
    assert rejected["evidence_status"] == "REJECTED"
    assert rejected["acceptance_verdict"] == "DO_NOT_PROMOTE"
    assert rejected["product_consumption_status"] == "NOT_FOR_PRODUCT"
    decision = capabilities["decision_alternatives"]
    assert decision["evidence_status"] == "ACCEPTED"
    assert decision["product_consumption_status"] == "EVALUATION_ONLY"
    assert decision["support"]["support_semantics"] == [
        "DIRECT_SUPPORTED",
        "FALLBACK_LIMITED",
        "UNSUPPORTED",
    ]
    assert decision["support"]["range_semantics"] == ["COMPLETE", "RANGE_LIMITED"]
    assert all(item["freshness"]["state"] == "UNKNOWN" for item in capabilities.values())


def test_failed_execution_history_is_not_scientific_rejection() -> None:
    history = bundle()["failed_evidence_history"]
    assert {item["run_id"] for item in history} == {
        "decision-alternatives-6b4-real-v1",
        "decision-alternatives-6b4-real-v2",
    }
    assert all(item["classification"] == "FAILED_EVIDENCE" for item in history)
    assert all(item["scientific_rejection"] is False for item in history)


def test_existing_run_manifests_match_versioned_identity_snapshot() -> None:
    result = verify_evidence_sources(ROOT, bundle(), require_present=True)
    assert result == {"verified_run_manifests": 13, "absent_run_manifests": 0}


def test_source_mismatch_fails_closed(tmp_path: Path) -> None:
    payload = bundle()
    one = copy.deepcopy(payload["capabilities"][0])
    fake_manifest = tmp_path / "run.json"
    fake_manifest.write_text(
        json.dumps({"run_id": "wrong-run", "scientific_identity_sha256": "f" * 64}),
        encoding="utf-8",
    )
    one["run_manifest"] = str(fake_manifest.relative_to(tmp_path))
    minimal = {"capabilities": [one]}
    with pytest.raises(AssuranceContractError, match="does not match"):
        verify_evidence_sources(tmp_path, minimal, require_present=True)


def test_malformed_versioned_sha_fails_before_publication(tmp_path: Path) -> None:
    raw = CONFIG.read_text(encoding="utf-8")
    malformed = raw.replace(
        "fb7410fa230d4c252c58cbbe98e4ccfbe45102800d5422ba45f8ce79d788a7a8",
        "not-a-sha",
        1,
    )
    config = tmp_path / "model_assurance.yaml"
    config.write_text(malformed, encoding="utf-8")
    with pytest.raises(AssuranceContractError, match="lowercase SHA256"):
        build_assurance(config)


def test_json_schema_and_bundle_are_valid_json(tmp_path: Path) -> None:
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    assert schema["properties"]["schema_version"]["const"] == "model_assurance_v1"
    assert set(IDENTITY_FIELDS) == set(schema["$defs"]["identities"]["required"])
    output = tmp_path / "model_assurance.json"
    write_assurance_bundle(bundle(), output)
    restored = json.loads(output.read_text(encoding="utf-8"))
    assert restored["assurance_identity_sha256"] == bundle()["assurance_identity_sha256"]


def test_monitoring_is_specification_only_and_sla_is_unresolved() -> None:
    payload = bundle()
    assert payload["freshness_policy"]["sla_thresholds"] is None
    assert payload["freshness_policy"]["sla_unresolved_reason"]
    ids = {item["id"] for item in payload["monitoring_expectations"]}
    assert {
        "data_freshness",
        "schema_drift",
        "stable_id_drift",
        "lineage_hash_mismatch",
        "artifact_publication_failure",
        "support_mix",
        "fallback_and_unsupported_growth",
        "predictive_and_calibration_evidence",
        "pressure_provider_availability",
        "scenario_verification",
        "decision_alternative_verification",
        "runtime_and_resources",
        "human_review_audit",
    } == ids
    assert all(item["implementation_status"] == "FUTURE_EXPECTATION" for item in payload["monitoring_expectations"])
