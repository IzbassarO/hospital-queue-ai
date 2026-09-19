from __future__ import annotations

import copy
import datetime as dt

import numpy as np
import pandas as pd
import pytest

from hqai_ml.flow_forecast.calibration import (
    CALIBRATED,
    INSUFFICIENT,
    NATIONAL_PROXY_UNSUPPORTED,
    OWN_HISTORY_UNSUPPORTED,
    calibrate_origin,
    calibration_metric_record,
    calibration_support_class,
    calibration_version,
    eligible_temporal_pool,
    finite_sample_quantile,
    interval_conformity_score,
    load_verified_source_predictions,
    median_absolute_residual_score,
    select_calibration_group,
    source_origin_key,
    verify_source_compatibility,
)
from hqai_ml.flow_forecast.config import TemporalCalibrationConfig
from hqai_ml.flow_forecast.quantile import NATIONAL_PROXY
from hqai_ml.registry import store
from hqai_ml.registry.experiment import ExperimentRun, execution_metadata
from hqai_ml.registry.resources import resource_config


def config(**updates) -> TemporalCalibrationConfig:
    raw = {
        "schema_version": 1,
        "version": "test-calibration-v1",
        "seed": 42,
        "nominal_coverage": 0.8,
        "candidate": "quantile_lightgbm",
        "source_variant": "raw",
        "methods": ["conformal_interval_expansion", "median_absolute_residual_baseline"],
        "minimum_scores": 2,
        "minimum_unique_target_dates": 2,
        "fallback_ladder": [
            "support_horizon_date_class",
            "support_horizon",
            "support_date_class",
            "support",
        ],
        "targets": ["registrations", "cohort_hospitalizations"],
        "validation_origins": [dt.date(2025, 1, 10), dt.date(2025, 1, 17)],
        "final_test_origin": dt.date(2025, 1, 24),
        "exclude_national_proxy": True,
        "automatic_promotion": False,
        "identity_sha256": "calibration-config-identity",
    }
    raw.update(updates)
    return TemporalCalibrationConfig(**raw)


def row(
    *,
    origin: str,
    target_date: str,
    phase: str = "validation",
    series_id: str = "hp:h1:p1",
    level: str = "hospital",
    fallback_level: str = "none",
    prediction_source: str = "direct_quantile_ml",
    aggregation_method: str = "none",
    horizon: int = 1,
    y: float = 5.0,
    p10: float = 3.0,
    p50: float = 5.0,
    p90: float = 7.0,
) -> dict:
    return {
        "phase": phase,
        "origin": pd.Timestamp(origin),
        "target_date": pd.Timestamp(target_date),
        "candidate": "quantile_lightgbm",
        "variant": "raw",
        "target": "registrations",
        "level": level,
        "series_id": series_id,
        "horizon": horizon,
        "y": y,
        "p10": p10,
        "p50": p50,
        "p90": p90,
        "fallback_level": fallback_level,
        "prediction_source": prediction_source,
        "aggregation_method": aggregation_method,
    }


def test_conformity_and_residual_scores_are_exact():
    y = np.array([1.0, 5.0, 10.0])
    lower = np.array([2.0, 3.0, 4.0])
    upper = np.array([4.0, 7.0, 8.0])
    assert interval_conformity_score(y, lower, upper).tolist() == [1.0, 0.0, 2.0]
    assert median_absolute_residual_score(y, np.array([2.0, 5.0, 8.0])).tolist() == [1.0, 0.0, 2.0]
    assert finite_sample_quantile(np.array([0.0, 1.0, 2.0, 3.0]), 0.8) == 3.0


def test_temporal_pool_excludes_unobservable_and_final_test_labels():
    frame = pd.DataFrame(
        [
            row(origin="2025-01-10", target_date="2025-01-16"),
            row(origin="2025-01-10", target_date="2025-01-18"),
            row(origin="2025-01-17", target_date="2025-01-18"),
            row(origin="2025-01-10", target_date="2025-01-12", phase="final_test"),
        ]
    )
    pool = eligible_temporal_pool(frame, dt.date(2025, 1, 17))
    assert len(pool) == 1
    assert pool.iloc[0]["target_date"] == pd.Timestamp("2025-01-16")
    assert set(pool["phase"]) == {"validation"}


def scored_pool() -> pd.DataFrame:
    frame = pd.DataFrame(
        [
            row(origin="2025-01-01", target_date="2025-01-11", horizon=1),
            row(origin="2025-01-02", target_date="2025-01-12", horizon=1),
            row(origin="2025-01-03", target_date="2025-01-18", horizon=2),
            row(origin="2025-01-04", target_date="2025-01-19", horizon=3),
        ]
    )
    frame["calibration_support_class"] = calibration_support_class(frame)
    frame["date_class"] = ["weekday", "weekend", "weekend", "weekend"]
    frame["interval_conformity_score"] = [0.0, 1.0, 2.0, 3.0]
    frame["median_absolute_residual_score"] = [1.0, 1.0, 2.0, 3.0]
    return frame


def test_horizon_fallback_pools_date_classes_deterministically():
    key = {
        "target": "registrations",
        "level": "hospital",
        "calibration_support_class": "direct_quantile_ml",
        "horizon": 1,
        "date_class": "holiday",
    }
    selected = select_calibration_group(scored_pool(), key, "interval_conformity_score", config())
    assert selected["calibration_status"] == CALIBRATED
    assert selected["calibration_group_level"] == "support_horizon"


def test_date_class_fallback_pools_horizons_deterministically():
    key = {
        "target": "registrations",
        "level": "hospital",
        "calibration_support_class": "direct_quantile_ml",
        "horizon": 4,
        "date_class": "weekend",
    }
    selected = select_calibration_group(scored_pool(), key, "interval_conformity_score", config())
    assert selected["calibration_status"] == CALIBRATED
    assert selected["calibration_group_level"] == "support_date_class"


def test_support_classes_never_borrow_each_others_scores():
    pool = scored_pool()
    pool["calibration_support_class"] = "region_profile_share_fallback"
    key = {
        "target": "registrations",
        "level": "hospital",
        "calibration_support_class": "direct_quantile_ml",
        "horizon": 1,
        "date_class": "weekday",
    }
    selected = select_calibration_group(pool, key, "interval_conformity_score", config())
    assert selected["calibration_status"] == INSUFFICIENT


def calibration_source(current_phase: str = "validation") -> pd.DataFrame:
    rows = [
        row(origin="2025-01-10", target_date="2025-01-11", y=9.0),
        row(origin="2025-01-10", target_date="2025-01-12", y=1.0),
        row(
            origin="2025-01-17",
            target_date="2025-01-18",
            phase=current_phase,
            p10=-2.0,
            p50=1.0,
            p90=2.0,
        ),
        row(
            origin="2025-01-17",
            target_date="2025-01-18",
            phase=current_phase,
            series_id="hp:zero:p1",
            fallback_level="own_history_zero",
            prediction_source="deterministic_own_history_fallback",
            p10=0.0,
            p50=0.0,
            p90=0.0,
        ),
        row(
            origin="2025-01-17",
            target_date="2025-01-18",
            phase=current_phase,
            series_id="np:p1",
            level="national",
            fallback_level=NATIONAL_PROXY,
            prediction_source=NATIONAL_PROXY,
            aggregation_method=NATIONAL_PROXY,
        ),
    ]
    return pd.DataFrame(rows)


def test_calibration_preserves_raw_values_and_lower_bound_is_nonnegative():
    source = calibration_source()
    raw = source.loc[source["origin"] == pd.Timestamp("2025-01-17"), ["p10", "p50", "p90"]].to_numpy()
    calibrated, audit = calibrate_origin(source, dt.date(2025, 1, 17), config(), set())
    for method in config().methods:
        part = calibrated[calibrated["calibration_method"] == method]
        assert np.array_equal(part[["p10", "p50", "p90"]].to_numpy(), raw)
        assert np.array_equal(part[["raw_p10", "raw_p50", "raw_p90"]].to_numpy(), raw)
        supported = part[part["calibration_status"] == CALIBRATED]
        assert (supported["calibrated_interval_80_lower"] >= 0).all()
    assert audit["calibration_pool_max_target_date"] == "2025-01-12"
    assert audit["final_test_rows_in_calibration_pool"] == 0


def test_own_history_and_national_proxy_emit_explicit_unsupported_status():
    calibrated, _ = calibrate_origin(calibration_source(), dt.date(2025, 1, 17), config(), set())
    statuses = calibrated.groupby("series_id")["calibration_status"].first().to_dict()
    assert statuses["hp:zero:p1"] == OWN_HISTORY_UNSUPPORTED
    assert statuses["np:p1"] == NATIONAL_PROXY_UNSUPPORTED
    unsupported = calibrated[calibrated["series_id"].isin(["hp:zero:p1", "np:p1"])]
    assert unsupported["calibrated_interval_80_lower"].isna().all()
    assert unsupported["calibrated_interval_80_upper"].isna().all()


def test_empirical_coverage_width_and_score_are_reported():
    frame = pd.DataFrame(
        {
            "calibration_status": [CALIBRATED, CALIBRATED],
            "y": [1.0, 5.0],
            "raw_p50": [1.0, 3.0],
            "calibrated_interval_80_lower": [0.0, 2.0],
            "calibrated_interval_80_upper": [2.0, 4.0],
            "target_date": pd.to_datetime(["2025-01-11", "2025-01-12"]),
            "calibration_sample_count": [100, 100],
        }
    )
    metrics = calibration_metric_record(frame, 0.8)
    assert metrics["empirical_coverage_80"] == 0.5
    assert metrics["coverage_gap_from_0_80"] == pytest.approx(-0.3)
    assert metrics["interval_width_mean"] == 2.0
    assert metrics["outcome_sample_count"] == 2


def test_final_test_labels_cannot_change_their_own_calibrated_bounds():
    source = calibration_source(current_phase="final_test")
    source["origin"] = source["origin"].replace({pd.Timestamp("2025-01-17"): pd.Timestamp("2025-01-24")})
    source["target_date"] = source["target_date"].where(
        source["origin"] != pd.Timestamp("2025-01-24"), pd.Timestamp("2025-01-25")
    )
    first, _ = calibrate_origin(source, dt.date(2025, 1, 24), config(), set())
    changed = source.copy()
    changed.loc[changed["phase"] == "final_test", "y"] = 1_000_000.0
    second, _ = calibrate_origin(changed, dt.date(2025, 1, 24), config(), set())
    columns = ["calibrated_interval_80_lower", "calibrated_interval_80_upper"]
    assert np.array_equal(first[columns].to_numpy(), second[columns].to_numpy(), equal_nan=True)


def test_calibration_version_is_independent_of_raw_model_values():
    source = calibration_source()
    changed_model_outputs = source.copy()
    changed_model_outputs[["p10", "p50", "p90"]] += 100.0
    first, _ = calibrate_origin(source, dt.date(2025, 1, 17), config(), set())
    second, _ = calibrate_origin(changed_model_outputs, dt.date(2025, 1, 17), config(), set())
    assert set(first["calibration_version"]) == {calibration_version(config())}
    assert set(second["calibration_version"]) == {calibration_version(config())}
    assert not source[["p10", "p50", "p90"]].equals(changed_model_outputs[["p10", "p50", "p90"]])


def source_plan(code_identity: str = "source-code") -> dict:
    resources = resource_config("smoke", cpu_count=2)
    scientific_identity = {
        "models": ["load_forecast"],
        "candidates": {"load_forecast": "current"},
        "model_families": {"load_forecast": "global_gradient_boosted_count_forecast"},
        "prediction_targets": {"load_forecast": ["registrations", "hospitalizations"]},
        "dataset_identity": "data",
        "config_identity": "config",
        "code_identity": code_identity,
        "implementation_versions": {"python": "3.12", "lightgbm": "4.7.0"},
        "temporal_protocols": {"flow_quantile_evidence": {"horizons": [1], "validation_origins": ["2025-01-10"]}},
        "hyperparameters": {
            "lightgbm": {"seed": 42},
            "quantile_model": {"alphas": [0.1, 0.5, 0.9], "rounds": 400},
        },
        "random_seeds": {"python": 42, "numpy": 42, "model": 42, "lightgbm": {"seed": 42}},
    }
    return {
        "scientific_identity_sha256": "source-science",
        "identity_sha256": "source-science",
        "scientific_identity": scientific_identity,
        "models": ["load_forecast"],
        "model_families": {"load_forecast": "global_gradient_boosted_count_forecast"},
        "prediction_targets": {"load_forecast": ["registrations", "hospitalizations"]},
        "dataset": {"identity_sha256": "data"},
        "configuration": {"sha256": "config"},
        "code": {"source": {"sha256": code_identity}},
        "temporal_protocols": scientific_identity["temporal_protocols"],
        "random_seeds": scientific_identity["random_seeds"],
        "hyperparameters": scientific_identity["hyperparameters"],
        "implementation_versions": scientific_identity["implementation_versions"],
        "execution": execution_metadata(resources),
    }


def test_source_artifact_identity_and_origin_metadata_are_verified_with_new_current_code(tmp_path):
    plan = source_plan()
    current_plan = copy.deepcopy(plan)
    current_plan["scientific_identity_sha256"] = "current-science"
    current_plan["scientific_identity"]["code_identity"] = "current-code"
    current_plan["code"]["source"]["sha256"] = "current-code"
    origin = dt.date(2025, 1, 10)
    key = source_origin_key(origin, "validation")
    parameters = {"quantiles": [0.1, 0.5, 0.9]}
    artifact = tmp_path / "source-origin"
    artifact.mkdir()
    pd.DataFrame([row(origin="2025-01-10", target_date="2025-01-11")]).to_parquet(
        artifact / "evaluation.parquet", index=False
    )
    (artifact / "metadata.json").write_text(
        store.canonical_json(
            {
                "resources": {"origin": "2025-01-10", "phase": "validation"},
                "calibration_audits": [],
            }
        ),
        encoding="utf-8",
    )
    manifest = store.write_artifact_manifest(artifact)
    run = ExperimentRun.start(tmp_path, plan, run_id="source-run")
    run.start_checkpoint(key, parameters=parameters)
    run.complete_checkpoint(
        key,
        parameters=parameters,
        metrics={},
        evaluation_status="completed",
        artifact_path=artifact,
        artifact_sha256=manifest["content_sha256"],
        version="validation-2025-01-10",
    )
    run.complete([key], parameters_by_key={key.identifier: parameters})
    run.release_lock()

    loaded, lineage = load_verified_source_predictions(
        tmp_path,
        "source-run",
        current_plan,
        [(origin, "validation")],
        parameters,
        "quantile_lightgbm",
    )
    assert len(loaded) == 1
    assert lineage["origin_artifacts"][0]["artifact_sha256"] == manifest["content_sha256"]
    assert lineage["source_scientific_identity"] == "source-science"
    assert lineage["source_code_identity"] == "source-code"
    assert lineage["current_code_identity"] == "current-code"
    assert lineage["compatibility"]["code_identity_equal"] is False
    assert lineage["compatibility"]["code_identity_equality_required"] is False


@pytest.mark.parametrize(
    ("component", "changed_value"),
    [
        ("config_identity", "changed-config"),
        ("prediction_targets", {"load_forecast": ["changed_target"]}),
        ("temporal_protocols", {"flow_quantile_evidence": {"horizons": [1, 2]}}),
        (
            "hyperparameters",
            {"lightgbm": {"seed": 42}, "quantile_model": {"alphas": [0.2, 0.5, 0.8], "rounds": 400}},
        ),
    ],
)
def test_source_compatibility_rejects_scientific_protocol_changes(component, changed_value):
    source = source_plan()
    current = copy.deepcopy(source)
    current["scientific_identity"]["code_identity"] = "current-code"
    current["scientific_identity"][component] = changed_value

    with pytest.raises(ValueError, match=component):
        verify_source_compatibility(source, current)
