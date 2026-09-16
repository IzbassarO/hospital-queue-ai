"""Focused tests for the repository architecture fitness checker."""

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
CHECKER_PATH = ROOT / "tools" / "architecture_check.py"
SPEC = importlib.util.spec_from_file_location("hqai_architecture_check", CHECKER_PATH)
assert SPEC and SPEC.loader
architecture_check = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = architecture_check
SPEC.loader.exec_module(architecture_check)


def write(root: Path, relative: str, source: str) -> Path:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(source, encoding="utf-8")
    return path


def by_rule(root: Path, rule: str):
    return [violation for violation in architecture_check.check_repository(root) if violation.rule == rule]


def test_allowed_imports_pass(tmp_path: Path):
    write(tmp_path, "backend/app/main.py", "from fastapi import FastAPI\n")
    write(tmp_path, "ml/hqai_ml/models/model.py", "import pandas as pd\n")
    assert architecture_check.check_repository(tmp_path) == []


def test_arch001_detects_backend_importing_ml(tmp_path: Path):
    write(tmp_path, "backend/app/services/predict.py", "from hqai_ml.models import wait_time\n")
    violations = by_rule(tmp_path, "ARCH001")
    assert len(violations) == 1
    assert violations[0].file == "backend/app/services/predict.py"
    assert violations[0].line == 1
    assert "hqai_ml.models.wait_time" in violations[0].problem


@pytest.mark.parametrize("module", ["app.services.status", "backend.app.api.routes"])
def test_arch002_detects_ml_importing_backend(tmp_path: Path, module: str):
    write(tmp_path, "ml/pipelines/predict.py", f"import {module}\n")
    violations = by_rule(tmp_path, "ARCH002")
    assert len(violations) == 1
    assert module in violations[0].problem


def test_arch003_activates_for_future_domain_boundary(tmp_path: Path):
    write(tmp_path, "backend/app/domain/policy.py", "from fastapi import Request\n")
    violations = by_rule(tmp_path, "ARCH003")
    assert len(violations) == 1
    assert "fastapi.Request" in violations[0].problem


def test_arch004_resolves_relative_outward_import(tmp_path: Path):
    write(tmp_path, "backend/app/application/use_case.py", "from ..infrastructure.repo import SqlRepo\n")
    violations = by_rule(tmp_path, "ARCH004")
    assert len(violations) == 1
    assert "app.infrastructure.repo.SqlRepo" in violations[0].problem


def test_comments_docstrings_and_strings_do_not_create_import_violations(tmp_path: Path):
    write(
        tmp_path,
        "backend/app/service.py",
        '"""Example only: from hqai_ml.models import train."""\n'
        "# import hqai_ml\n"
        'EXAMPLE = "import hqai_ml.features"\n',
    )
    assert by_rule(tmp_path, "ARCH001") == []


def test_violation_format_includes_rule_file_line_and_remediation(tmp_path: Path):
    write(tmp_path, "backend/app/service.py", "import hqai_ml.explain\n")
    rendered = by_rule(tmp_path, "ARCH001")[0].format()
    assert rendered.startswith("ARCH001 backend/app/service.py:1")
    assert "hqai_ml.explain" in rendered
    assert "Remediation:" in rendered


def test_arch005_detects_executable_raw_sql_but_not_sql_prose(tmp_path: Path):
    write(
        tmp_path,
        "backend/app/api/routes.py",
        "from sqlalchemy import text as sql_text\n"
        'EXAMPLE = "SELECT is harmless prose here"\n'
        'statement = sql_text("SELECT 1")\n',
    )
    violations = by_rule(tmp_path, "ARCH005")
    assert len(violations) == 1
    assert violations[0].line == 3
    assert "sqlalchemy.text" in violations[0].problem
