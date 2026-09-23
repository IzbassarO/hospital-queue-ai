"""Offline projection controls; small synthetic records, no fitting or real artifact dependency."""

import importlib.util
import json
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.schemas.operational_intelligence import ForecastPublicationRow, RawQuantiles

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("offline_bundle", ROOT / "tools/operational_bundle.py")
assert SPEC and SPEC.loader
builder = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = builder
SPEC.loader.exec_module(builder)


def source_forecast():
    return {
        "series_id": "hp:H001:P01",
        "level": "hospital",
        "origin": "2025-03-17",
        "target_date": "2025-03-18",
        "horizon": 1,
        "target": "registrations",
        "org_code": "H001",
        "region_code": "10",
        "profile_code": "P01",
        "forecast_value": 5.0,
        "forecast_source": "direct_quantile_ml",
        "raw_p10": -1.0,
        "raw_p50": -2.0,
        "raw_p90": 3.0,
        "raw_quantile_semantics": "unchanged_model_evidence",
        "level_local_interval_80_lower": 1.0,
        "level_local_interval_80_upper": 3.0,
        "calibration_version": "test-v1",
        "calibration_status": "calibrated",
        "calibration_support_class": "direct_quantile_ml",
        "hierarchy_status": "bottom_up_child_unchanged",
        "support_status": "supported",
        "fallback_status": "not_applicable",
        "uncertainty_status": "level_local_calibrated",
    }


def test_unrepaired_quantiles_and_separate_interval_are_preserved():
    result = builder.forecast_row(source_forecast(), ["synthetic test"])
    assert result["raw_quantiles"] == {"p10": -1.0, "p50": -2.0, "p90": 3.0, "semantics": "UNCHANGED_MODEL_EVIDENCE"}
    assert result["central_value"] == 5.0
    assert result["central_semantics"] == "POINT_FORECAST"
    assert result["calibrated_uncertainty"]["lower"] == 1.0
    assert result["calibrated_uncertainty"]["upper"] == 3.0
    result["calibrated_uncertainty"]["lower"] = 4.0
    with pytest.raises(ValidationError, match="lower bound exceeds"):
        ForecastPublicationRow.model_validate(result)


@pytest.mark.parametrize("value", [float("nan"), float("inf"), -float("inf")])
def test_raw_quantiles_reject_nonfinite_evidence(value):
    with pytest.raises(ValidationError):
        RawQuantiles(p10=value, p50=2, p90=3, semantics="UNCHANGED_MODEL_EVIDENCE")


def test_national_proxy_is_not_mislabelled_as_a_predictive_interval():
    row = source_forecast() | {
        "level": "national",
        "series_id": "np:P01",
        "forecast_source": "exact_region_central_sum",
        "raw_quantile_semantics": "historical_region_quantile_sum_proxy_not_national_distribution",
        "fallback_status": "national_historical_quantile_proxy",
        "uncertainty_status": "national_proxy_not_predictive_distribution",
    }
    result = builder.forecast_row(row, [])
    assert result["raw_quantiles"] is None
    assert result["calibrated_uncertainty"] is None
    assert result["central_value"] == 5.0
    assert result["central_semantics"] == "BOTTOM_UP_CENTRAL"
    assert result["org_code"] is None and result["region_code"] is None
    assert '"p10": -1.0' in result["evidence_facts"][-1]
    assert "not national predictive quantiles" in result["evidence_facts"][-1]


def test_unknown_semantics_and_partial_quantiles_fail_closed():
    with pytest.raises(KeyError):
        builder.forecast_row(source_forecast() | {"support_status": "invented"}, [])
    with pytest.raises(ValueError, match="partial raw"):
        builder.forecast_row(source_forecast() | {"raw_p10": None}, [])


def artifact(root):
    directory = root / "artifacts/test-explicit-run"
    directory.mkdir(parents=True)
    (directory / "rows.json").write_text('{"value": 7}')
    files = [{"path": "rows.json", "bytes": 12, "sha256": builder.file_hash(directory / "rows.json")}]
    manifest = {"files": files, "content_sha256": builder.evidence_hash({"files": files})}
    (directory / "artifact-manifest.json").write_text(json.dumps(manifest))
    return directory, {"path": "test-explicit-run", "sha256": manifest["content_sha256"]}


def test_artifact_validation_rejects_modified_missing_or_mixed_content(tmp_path):
    directory, reference = artifact(tmp_path)
    evidence = builder.Evidence(tmp_path)
    assert evidence.artifact(reference) == directory
    with pytest.raises(ValueError, match="identity mismatch"):
        evidence.artifact(reference | {"sha256": "0" * 64})
    (directory / "rows.json").write_text('{"value": 8}')
    with pytest.raises(ValueError, match="checksum mismatch"):
        evidence.artifact(reference)
    (directory / "rows.json").unlink()
    with pytest.raises(ValueError, match="partial/unexpected"):
        evidence.artifact(reference)
    with pytest.raises(ValueError, match="inside artifacts"):
        evidence.path("../escape")


def test_wrong_assurance_identity_fails_before_artifact_loading(tmp_path, monkeypatch):
    from types import SimpleNamespace

    monkeypatch.setattr(builder.Evidence, "json", lambda self, path: {})
    monkeypatch.setattr(
        builder,
        "parse_assurance_bundle",
        lambda raw: SimpleNamespace(bundle=SimpleNamespace(assurance_identity_sha256="0" * 64)),
    )
    with pytest.raises(ValueError, match="unaccepted Model Assurance"):
        builder.Evidence(tmp_path).verify()
