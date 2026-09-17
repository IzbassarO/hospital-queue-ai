"""Focused tests for the canonical OpenAPI snapshot and stable operation inventory."""

import importlib.util
import os
import re
import subprocess
import sys
from pathlib import Path

from fastapi.routing import APIRoute

ROOT = Path(__file__).resolve().parents[2]
CHECKER_PATH = ROOT / "tools" / "openapi_contract.py"
SPEC = importlib.util.spec_from_file_location("hqai_openapi_contract", CHECKER_PATH)
assert SPEC and SPEC.loader
openapi_contract = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = openapi_contract
SPEC.loader.exec_module(openapi_contract)


def test_every_operation_has_a_non_empty_operation_id():
    actual = openapi_contract.operations(openapi_contract.build_schema())
    assert all(isinstance(operation_id, str) and operation_id for operation_id in actual.values())


def test_operation_ids_are_unique():
    operation_ids = list(openapi_contract.operations(openapi_contract.build_schema()).values())
    assert len(operation_ids) == len(set(operation_ids))


def test_operation_inventory_and_ids_are_stable():
    assert openapi_contract.operations(openapi_contract.build_schema()) == openapi_contract.EXPECTED_OPERATIONS


def test_liveness_metadata_is_stable_but_excluded_from_openapi():
    from app.main import app

    liveness = [route for route in app.routes if isinstance(route, APIRoute) and route.path == "/health"]
    assert len(liveness) == 1
    assert liveness[0].operation_id == "liveness_get"
    assert liveness[0].include_in_schema is False


def test_security_scheme_matches_protected_operation_inventory():
    schema = openapi_contract.build_schema()
    assert schema["components"]["securitySchemes"]["ApiKeyAuth"] == {
        "type": "apiKey",
        "description": "API key issued by hospital-queue-ai",
        "in": "header",
        "name": "X-API-Key",
    }
    for (method, path), operation_id in openapi_contract.EXPECTED_OPERATIONS.items():
        operation = schema["paths"][path][method.lower()]
        expected = None if operation_id == "health_get" else [{"ApiKeyAuth": []}]
        assert operation.get("security") == expected, operation_id
        assert not any(parameter.get("name") == "X-API-Key" for parameter in operation.get("parameters", []))


def test_schema_serialization_is_deterministic():
    first = {"z": [3, {"b": 2, "a": 1}], "a": "Казахстан"}
    second = {"a": "Казахстан", "z": [3, {"a": 1, "b": 2}]}
    assert openapi_contract.serialize_schema(first) == openapi_contract.serialize_schema(second)
    assert openapi_contract.serialize_schema(first).endswith("\n")


def test_schema_generation_restores_process_environment(monkeypatch):
    monkeypatch.setenv("APP_NAME", "test-sentinel")
    monkeypatch.delenv("DEMO_API_KEY", raising=False)
    openapi_contract.build_schema()
    assert os.environ["APP_NAME"] == "test-sentinel"
    assert "DEMO_API_KEY" not in os.environ


def test_stale_snapshot_is_detected(tmp_path: Path, capsys):
    snapshot = tmp_path / "openapi.json"
    snapshot.write_text("{}\n", encoding="utf-8")
    assert openapi_contract.check(snapshot) == 1
    assert "stale" in capsys.readouterr().err


def test_current_committed_snapshot_passes():
    assert openapi_contract.check() == 0


def test_snapshot_contains_no_demo_key_secret_or_local_path():
    snapshot = (ROOT / "backend" / "openapi.json").read_text(encoding="utf-8")
    assert not re.search(r"hqai_[A-Za-z0-9_-]{20,}", snapshot)
    assert not re.search(r"(?:/Users/|/home/|[A-Za-z]:\\\\)", snapshot)
    assert str(ROOT) not in snapshot


def test_check_command_failure_explains_how_to_regenerate(tmp_path: Path):
    missing = tmp_path / "missing.json"
    result = subprocess.run(
        [sys.executable, str(CHECKER_PATH), "check", "--snapshot", str(missing)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 1
    assert "missing" in result.stderr
    assert "python tools/openapi_contract.py generate" in result.stderr
