#!/usr/bin/env python3
"""Generate or verify the repository's canonical OpenAPI contract snapshot."""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
SNAPSHOT = BACKEND / "openapi.json"
HTTP_METHODS = {"delete", "get", "head", "options", "patch", "post", "put", "trace"}

# These identifiers are public contract names. Keep them stable across Python function/path refactors.
EXPECTED_OPERATIONS = {
    ("GET", "/api/v1/admin/access-log"): "admin_access_log_list",
    ("POST", "/api/v1/admin/keys"): "admin_key_create",
    ("GET", "/api/v1/admin/keys"): "admin_keys_list",
    ("POST", "/api/v1/admin/keys/{key_id}/revoke"): "admin_key_revoke",
    ("GET", "/api/v1/alerts"): "alerts_list",
    ("GET", "/api/v1/config"): "config_get",
    ("GET", "/api/v1/dictionaries"): "dictionaries_get",
    ("POST", "/api/v1/decisions"): "decision_create",
    ("GET", "/api/v1/decisions"): "decisions_list",
    ("POST", "/api/v1/specialist-decisions"): "specialist_decision_create",
    ("GET", "/api/v1/specialist-decisions"): "specialist_decisions_list",
    ("GET", "/api/v1/assistant/status"): "assistant_status",
    ("POST", "/api/v1/assistant"): "assistant_ask",
    ("GET", "/api/v1/health"): "health_get",
    ("GET", "/api/v1/hospitals/{org_code}/profiles/{profile_code}/export"): "hospital_export_get",
    ("GET", "/api/v1/hospitals/{org_code}/profiles/{profile_code}"): "hospital_profile_get",
    ("GET", "/api/v1/hospitals/{org_code}/profiles/{profile_code}/recommendations"): ("hospital_recommendations_get"),
    ("GET", "/api/v1/hospitals/{org_code}/profiles/{profile_code}/referrals"): "hospital_referrals_list",
    ("GET", "/api/v1/me"): "caller_get",
    ("GET", "/api/v1/model-assurance"): "model_assurance_current_get",
    ("GET", "/api/v1/model-assurance/capabilities"): "model_assurance_capabilities_list",
    ("GET", "/api/v1/model-assurance/capabilities/{capability_id}"): "model_assurance_capability_get",
    ("GET", "/api/v1/models"): "models_list",
    ("GET", "/api/v1/operational-intelligence/forecasts"): "operational_forecasts_list",
    ("GET", "/api/v1/operational-intelligence/hospitals/{org_code}/profiles/{profile_code}"): (
        "operational_intelligence_hospital_profile_get"
    ),
    ("GET", "/api/v1/operational-intelligence/overview"): "operational_intelligence_overview_get",
    ("GET", "/api/v1/operational-intelligence/regions/{region_code}"): "operational_intelligence_region_get",
    ("GET", "/api/v1/operational-intelligence/signals"): "operational_signals_list",
    ("GET", "/api/v1/operational-intelligence/signals/{signal_id}"): "operational_signal_get",
    ("GET", "/api/v1/operational-intelligence/signals/{signal_id}/explanation"): ("operational_signal_explanation_get"),
    ("GET", "/api/v1/overview"): "overview_get",
    ("GET", "/api/v1/regions/{region_code}/hospitals"): "region_hospitals_list",
    ("GET", "/api/v1/review-evidence/decision-alternatives"): "review_decision_alternatives_list",
    ("GET", "/api/v1/review-evidence/decision-alternatives/{set_id}"): "review_decision_alternative_set_get",
    ("GET", "/api/v1/review-evidence/overview"): "review_evidence_overview_get",
    ("GET", "/api/v1/review-evidence/signals/{signal_id}/decision-alternatives"): (
        "review_signal_decision_alternatives_get"
    ),
    ("GET", "/api/v1/review-evidence/signals/{signal_id}/stress-test"): "review_signal_stress_test_get",
    ("GET", "/api/v1/regions/{region_code}"): "region_get",
}


def build_schema() -> dict[str, Any]:
    """Import the app under canonical non-secret settings and return its OpenAPI document."""
    inserted_path = str(BACKEND) not in sys.path
    if inserted_path:
        sys.path.insert(0, str(BACKEND))
    # Environment variables take precedence over a developer's .env. Only settings that influence
    # OpenAPI are fixed; database access and credentials are neither required nor embedded.
    canonical_environment = {
        "APP_NAME": "hospital-queue-ai",
        "API_PREFIX": "/api/v1",
        "DOCS_ENABLED": "true",
        "DEMO_API_KEY": "",
    }
    previous_environment = {name: os.environ.get(name) for name in canonical_environment}
    try:
        os.environ.update(canonical_environment)
        from app.main import app

        return app.openapi()
    finally:
        for name, value in previous_environment.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value
        if inserted_path:
            sys.path.remove(str(BACKEND))


def serialize_schema(schema: dict[str, Any]) -> str:
    """Serialize with stable ordering, UTF-8 characters and one final newline."""
    return json.dumps(schema, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def operations(schema: dict[str, Any]) -> dict[tuple[str, str], str | None]:
    result: dict[tuple[str, str], str | None] = {}
    for path, path_item in schema.get("paths", {}).items():
        for method, operation in path_item.items():
            if method.lower() in HTTP_METHODS:
                result[(method.upper(), path)] = operation.get("operationId")
    return result


def validate_operations(schema: dict[str, Any]) -> list[str]:
    actual = operations(schema)
    problems = [f"{method} {path}: missing operationId" for (method, path), value in actual.items() if not value]
    counts = Counter(value for value in actual.values() if value)
    problems.extend(f"duplicate operationId: {value}" for value, count in counts.items() if count > 1)
    for key in sorted(EXPECTED_OPERATIONS):
        expected = EXPECTED_OPERATIONS[key]
        if key not in actual:
            problems.append(f"missing operation: {key[0]} {key[1]}")
        elif actual[key] != expected:
            problems.append(f"{key[0]} {key[1]}: expected operationId {expected!r}, found {actual[key]!r}")
    for method, path in sorted(actual.keys() - EXPECTED_OPERATIONS.keys()):
        problems.append(f"unexpected operation: {method} {path} (add its stable ID to EXPECTED_OPERATIONS)")
    return problems


def generate(snapshot: Path = SNAPSHOT) -> int:
    schema = build_schema()
    problems = validate_operations(schema)
    if problems:
        print("OpenAPI contract generation refused: operation inventory is invalid.", file=sys.stderr)
        for problem in problems:
            print(f"- {problem}", file=sys.stderr)
        return 1
    snapshot.write_text(serialize_schema(schema), encoding="utf-8")
    print(f"wrote {snapshot.relative_to(ROOT)} ({len(operations(schema))} operations)")
    return 0


def check(snapshot: Path = SNAPSHOT) -> int:
    schema = build_schema()
    problems = validate_operations(schema)
    if problems:
        print("OpenAPI contract check failed: operation inventory changed.", file=sys.stderr)
        for problem in problems:
            print(f"- {problem}", file=sys.stderr)
        return 1
    expected = serialize_schema(schema)
    if not snapshot.is_file():
        print(
            f"OpenAPI contract check failed: {snapshot} is missing. Run `python tools/openapi_contract.py generate`.",
            file=sys.stderr,
        )
        return 1
    if snapshot.read_text(encoding="utf-8") != expected:
        print(
            "OpenAPI contract check failed: backend/openapi.json is stale. "
            "Review the API change, then run `python tools/openapi_contract.py generate`.",
            file=sys.stderr,
        )
        return 1
    print(f"OpenAPI contract: PASS ({len(operations(schema))} stable operations; snapshot current)")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("generate", "check"))
    parser.add_argument("--snapshot", type=Path, default=SNAPSHOT, help="snapshot path (default: backend/openapi.json)")
    args = parser.parse_args(argv)
    return generate(args.snapshot) if args.mode == "generate" else check(args.snapshot)


if __name__ == "__main__":
    sys.exit(main())
