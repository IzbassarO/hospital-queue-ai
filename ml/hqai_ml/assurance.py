"""Deterministic, candidate-independent Model Assurance contract generation."""

from __future__ import annotations

import copy
import hashlib
import json
import re
from pathlib import Path
from typing import Any

import yaml


class AssuranceContractError(ValueError):
    """Raised when a versioned assurance registry violates its contract."""


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
EVIDENCE_STATUSES = {"ACCEPTED", "REJECTED", "EXPERIMENTAL"}
ACCEPTANCE_VERDICTS = {"ACCEPT", "ACCEPT_WITH_P2", "DO_NOT_PROMOTE", "NOT_APPLICABLE"}
PRODUCT_STATUSES = {
    "ELIGIBLE_AFTER_INGESTION",
    "EVALUATION_ONLY",
    "REFERENCE_ONLY",
    "NOT_FOR_PRODUCT",
}
SUPPORT_STATUSES = {"DIRECT_SUPPORTED", "FALLBACK_LIMITED", "UNSUPPORTED"}
RANGE_STATUSES = {"COMPLETE", "RANGE_LIMITED"}
FRESHNESS_STATES = {"FRESH", "STALE", "DEGRADED", "UNKNOWN"}
IDENTITY_STATUSES = {"AVAILABLE", "UNKNOWN", "NOT_APPLICABLE"}
PROMOTION_STATUSES = {"PROMOTED", "HUMAN_REVIEW_ONLY", "NO_PROMOTION", "NOT_APPLICABLE"}
PHYSICAL_FEASIBILITY_STATUSES = {"VALIDATED", "NOT_VALIDATED", "UNKNOWN", "NOT_APPLICABLE"}
SHA256_FIELDS = {
    "scientific_identity_sha256",
    "artifact_sha256",
    "dataset_identity_sha256",
    "config_identity_sha256",
    "code_identity_sha256",
}


def canonical_json_bytes(value: Any) -> bytes:
    """Return the one canonical encoding used for assurance identity."""
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _required(mapping: dict[str, Any], key: str, context: str) -> Any:
    if key not in mapping:
        raise AssuranceContractError(f"{context} is missing required field {key!r}")
    return mapping[key]


def _identity_record(raw: Any, field: str, capability_id: str) -> dict[str, Any]:
    if isinstance(raw, (str, list)):
        record = {
            "status": "AVAILABLE",
            "value": copy.deepcopy(raw),
            "reason": "Recorded in the referenced accepted repository evidence.",
        }
    elif isinstance(raw, dict):
        record = copy.deepcopy(raw)
    elif raw is None:
        record = {
            "status": "NOT_APPLICABLE",
            "value": None,
            "reason": f"{field} does not apply to capability {capability_id}.",
        }
    else:
        raise AssuranceContractError(f"{capability_id}.{field} has an invalid identity record")

    status = _required(record, "status", f"{capability_id}.{field}")
    if status not in IDENTITY_STATUSES:
        raise AssuranceContractError(f"{capability_id}.{field} has invalid status {status!r}")
    record.setdefault("value", None)
    reason = record.get("reason")
    if status == "AVAILABLE" and record["value"] in (None, "", []):
        raise AssuranceContractError(f"{capability_id}.{field} is AVAILABLE without a value")
    if (
        status == "AVAILABLE"
        and field in SHA256_FIELDS
        and not (
            isinstance(record["value"], str)
            and re.fullmatch(r"[0-9a-f]{64}", record["value"])
            or isinstance(record["value"], list)
            and record["value"]
            and all(isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value) for value in record["value"])
        )
    ):
        raise AssuranceContractError(f"{capability_id}.{field} must contain lowercase SHA256 digests")
    if status != "AVAILABLE" and (record["value"] is not None or not reason):
        raise AssuranceContractError(f"{capability_id}.{field} {status} must have null value and a reason")
    return record


def _validate_governance(governance: dict[str, Any], capability_id: str) -> None:
    expected_bools = (
        "human_review_required",
        "autonomous_action",
        "capacity_checked",
        "causal_effect_claimed",
        "serving_claim",
    )
    for field in expected_bools:
        if not isinstance(_required(governance, field, f"{capability_id}.governance"), bool):
            raise AssuranceContractError(f"{capability_id}.governance.{field} must be boolean")
    if governance["autonomous_action"]:
        raise AssuranceContractError(f"{capability_id} cannot authorize autonomous action")
    if governance["capacity_checked"] or governance["causal_effect_claimed"]:
        raise AssuranceContractError(f"{capability_id} cannot claim capacity or causal evidence")
    if governance["serving_claim"]:
        raise AssuranceContractError(f"{capability_id} cannot claim live serving")
    if governance.get("promotion_status") not in PROMOTION_STATUSES:
        raise AssuranceContractError(f"{capability_id} has an invalid promotion_status")
    if governance.get("physical_feasibility_status") not in PHYSICAL_FEASIBILITY_STATUSES:
        raise AssuranceContractError(f"{capability_id} has an invalid physical_feasibility_status")


def _normalize_capability(raw: dict[str, Any]) -> dict[str, Any]:
    capability = copy.deepcopy(raw)
    capability_id = str(_required(capability, "capability_id", "capability"))
    if capability.get("evidence_status") not in EVIDENCE_STATUSES:
        raise AssuranceContractError(f"{capability_id} has invalid evidence_status")
    if capability.get("acceptance_verdict") not in ACCEPTANCE_VERDICTS:
        raise AssuranceContractError(f"{capability_id} has invalid acceptance_verdict")
    if capability.get("product_consumption_status") not in PRODUCT_STATUSES:
        raise AssuranceContractError(f"{capability_id} has invalid product_consumption_status")

    identities = capability.get("identities", {})
    if not isinstance(identities, dict):
        raise AssuranceContractError(f"{capability_id}.identities must be an object")
    capability["identities"] = {
        field: _identity_record(identities.get(field), field, capability_id) for field in IDENTITY_FIELDS
    }

    support = _required(capability, "support", capability_id)
    if not set(_required(support, "support_semantics", f"{capability_id}.support")) <= SUPPORT_STATUSES:
        raise AssuranceContractError(f"{capability_id} has invalid support semantics")
    if not set(_required(support, "range_semantics", f"{capability_id}.support")) <= RANGE_STATUSES:
        raise AssuranceContractError(f"{capability_id} has invalid range semantics")
    if capability.get("freshness", {}).get("state") not in FRESHNESS_STATES:
        raise AssuranceContractError(f"{capability_id} has invalid freshness state")
    _validate_governance(_required(capability, "governance", capability_id), capability_id)

    for field in ("evidence", "source_lineage", "limitations", "allowed_claims", "forbidden_claims"):
        _required(capability, field, capability_id)
    return capability


def validate_assurance_payload(payload: dict[str, Any], *, identity_required: bool = True) -> None:
    """Validate hard semantic gates not expressible safely through configuration alone."""
    for field in (
        "schema_version",
        "contract_version",
        "assurance_id",
        "source_code_commit",
        "ml_freeze_status",
        "capabilities",
        "failed_evidence_history",
        "claim_boundaries",
        "monitoring_expectations",
        "product_contract_version",
    ):
        _required(payload, field, "model assurance")
    if payload["schema_version"] != "model_assurance_v1":
        raise AssuranceContractError("schema_version must be model_assurance_v1")
    if re.fullmatch(r"[0-9a-f]{40}", str(payload["source_code_commit"])) is None:
        raise AssuranceContractError("source_code_commit must be a full lowercase Git commit")
    if payload["ml_freeze_status"] != "ML_CORE_CLOSED_FROZEN":
        raise AssuranceContractError("the v1 closure bundle must explicitly freeze the ML core")

    capabilities = payload["capabilities"]
    ids = [item["capability_id"] for item in capabilities]
    if ids != sorted(ids) or len(ids) != len(set(ids)):
        raise AssuranceContractError("capabilities must be unique and sorted by capability_id")

    boundaries = payload["claim_boundaries"]
    if boundaries.get("pressure_basis") != "historical_flow_proxy_v1":
        raise AssuranceContractError("pressure basis must remain historical_flow_proxy_v1")
    required_forbidden = {
        "AI recommender",
        "patient router",
        "autonomous routing system",
        "capacity optimizer",
        "capacity planner",
        "Digital Twin",
        "causal simulator",
        "intervention engine",
        "free beds",
        "occupancy",
        "staffed capacity",
        "physical feasibility",
        "causal benefit",
        "clinical benefit",
        "reduced waiting time",
        "improved outcomes",
    }
    if not required_forbidden <= set(boundaries.get("forbidden_project_descriptions_and_claims", [])):
        raise AssuranceContractError("claim boundaries omit required forbidden claims")
    if boundaries.get("decision_alternative_semantics") != ("retrospective mathematical alternatives for human review"):
        raise AssuranceContractError("decision-alternative semantics drifted")

    failed_ids = {item.get("run_id") for item in payload["failed_evidence_history"]}
    if failed_ids != {"decision-alternatives-6b4-real-v1", "decision-alternatives-6b4-real-v2"}:
        raise AssuranceContractError("failed decision-alternative evidence history is incomplete")
    if any(item.get("classification") != "FAILED_EVIDENCE" for item in payload["failed_evidence_history"]):
        raise AssuranceContractError("failed executions must remain FAILED_EVIDENCE")

    freshness = payload.get("freshness_policy", {})
    if freshness.get("sla_thresholds") is not None or not freshness.get("sla_unresolved_reason"):
        raise AssuranceContractError("unresolved customer refresh SLA must remain explicit")
    if not payload["monitoring_expectations"]:
        raise AssuranceContractError("future monitoring expectations must be present")
    if any(item.get("implementation_status") != "FUTURE_EXPECTATION" for item in payload["monitoring_expectations"]):
        raise AssuranceContractError("monitoring expectations cannot claim a live monitor")

    if identity_required:
        identity = payload.get("assurance_identity_sha256")
        if not isinstance(identity, str) or len(identity) != 64:
            raise AssuranceContractError("assurance_identity_sha256 must be a SHA256 hex digest")


def load_assurance_config(path: Path) -> dict[str, Any]:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise AssuranceContractError("assurance configuration must be an object")
    payload = copy.deepcopy(raw)
    payload["capabilities"] = sorted(
        (_normalize_capability(item) for item in payload.get("capabilities", [])),
        key=lambda item: item["capability_id"],
    )
    validate_assurance_payload(payload, identity_required=False)
    return payload


def assurance_identity_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Remove audit-only/mutable fields from the assurance identity projection."""
    identity_payload = copy.deepcopy(payload)
    identity_payload.pop("assurance_identity_sha256", None)
    identity_payload.pop("generated_at", None)
    return identity_payload


def build_assurance(config_path: Path, *, generated_at: str | None = None) -> dict[str, Any]:
    payload = load_assurance_config(config_path)
    identity = hashlib.sha256(canonical_json_bytes(assurance_identity_payload(payload))).hexdigest()
    payload["assurance_identity_sha256"] = identity
    if generated_at is not None:
        payload["generated_at"] = generated_at
    validate_assurance_payload(payload)
    return payload


def verify_evidence_sources(root: Path, payload: dict[str, Any], *, require_present: bool = False) -> dict[str, int]:
    """Cross-check copied identities against run manifests without recomputing science."""
    verified = 0
    absent = 0
    for capability in payload["capabilities"]:
        source = capability.get("run_manifest")
        if not source:
            continue
        path = root / source
        if not path.is_file():
            absent += 1
            if require_present:
                raise AssuranceContractError(f"missing evidence source: {source}")
            continue
        manifest = json.loads(path.read_text(encoding="utf-8"))
        identities = capability["identities"]
        expected = {
            "run_id": manifest.get("run_id"),
            "scientific_identity_sha256": manifest.get("scientific_identity_sha256"),
            "artifact_sha256": manifest.get("artifacts", {}).get("load_forecast", {}).get("sha256"),
            "dataset_identity_sha256": manifest.get("dataset", {}).get("identity_sha256"),
            "config_identity_sha256": manifest.get("configuration", {}).get("sha256"),
            "code_identity_sha256": manifest.get("code", {}).get("source", {}).get("sha256"),
        }
        for field, actual in expected.items():
            record = identities[field]
            if actual is not None and (record["status"] != "AVAILABLE" or record["value"] != actual):
                raise AssuranceContractError(f"{capability['capability_id']}.{field} does not match {source}")
        verified += 1
    return {"verified_run_manifests": verified, "absent_run_manifests": absent}


def write_assurance_bundle(payload: dict[str, Any], output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(".json.partial")
    temporary.write_bytes(json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True).encode("utf-8") + b"\n")
    temporary.replace(output)
