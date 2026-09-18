from __future__ import annotations

import datetime as dt

import numpy as np
import pandas as pd
import pytest
from pydantic import ValidationError

from hqai_ml.features.load import Panel
from hqai_ml.flow_forecast.config import FlowForecastConfig
from hqai_ml.flow_forecast.evidence import (
    _fallback_predictions,
    assert_dense_observed,
    baseline_arrays,
    combine_panels,
    extrapolation_diagnostics,
    forecast_hierarchy_diagnostics,
    hierarchy_diagnostics,
    metric_record,
    national_panel,
    summarize_evaluation,
    support_mask,
    validation_recommendation,
)
from hqai_ml.registry import store
from hqai_ml.registry.experiment import ExperimentRun, execution_metadata
from hqai_ml.registry.resources import resource_config
from pipelines.flow_forecast import origin_key, scientific_lightgbm_parameters


def config(**updates) -> FlowForecastConfig:
    raw = {
        "schema_version": 1,
        "seed": 42,
        "horizon": 2,
        "validation_origins": [dt.date(2025, 1, 8), dt.date(2025, 1, 10)],
        "final_test_origin": dt.date(2025, 1, 13),
        "extrapolation_report_ratio_threshold": 5.0,
        "extrapolation_examples": 10,
        "baselines": {
            "trailing_mean_days": 3,
            "trailing_median_days": 4,
            "recent_seasonal_periods": 2,
        },
        "support": {
            "min_history_days": 7,
            "hospital_min_mean_registrations": 1.0,
            "region_parents_direct": True,
            "national_from_region_aggregation": True,
            "sparse_zero_rate": 0.5,
            "zero_heavy_zero_rate": 0.8,
        },
        "challenger": {"id": "current_poisson_lightgbm", "source_config": "models.yaml"},
        "automatic_promotion": False,
    }
    raw.update(updates)
    return FlowForecastConfig(**raw)


def panel(
    *,
    level: str,
    series: list[tuple[str, str, str]],
    values: np.ndarray,
    dates: list[dt.date] | None = None,
) -> Panel:
    dates = dates or [dt.date(2025, 1, 1) + dt.timedelta(days=offset) for offset in range(values.shape[1])]
    meta = pd.DataFrame(
        [
            {
                "series_id": series_id,
                "level": level,
                "org_code": series_id if level == "hospital" else f"__{level}__",
                "region_code": region_code,
                "profile_code": profile_code,
            }
            for series_id, region_code, profile_code in series
        ]
    )
    return Panel(dates, meta, values.copy(), values.copy(), np.zeros_like(values))


def hierarchy_panels() -> dict[str, Panel]:
    hospital = panel(
        level="hospital",
        series=[("hp:h1:p1", "r1", "p1"), ("hp:h2:p1", "r1", "p1")],
        values=np.array([[1.0] * 16, [3.0] * 16]),
    )
    region = panel(
        level="region",
        series=[("rp:r1:p1", "r1", "p1")],
        values=np.array([[4.0] * 16]),
    )
    return {"hospital": hospital, "region": region, "national": national_panel(region)}


def test_temporal_protocol_rejects_validation_target_overlap_with_final_test():
    with pytest.raises(ValidationError, match="validation targets must end"):
        config(final_test_origin=dt.date(2025, 1, 11))


def test_baselines_use_only_values_at_or_before_origin():
    values = np.array([[1, 2, 3, 4, 5, 6, 7, 80, 90, 100, 110, 120, 130, 140, 150, 160]], dtype=float)
    original = panel(level="hospital", series=[("hp:h1:p1", "r1", "p1")], values=values)
    changed = panel(level="hospital", series=[("hp:h1:p1", "r1", "p1")], values=values)
    changed.registrations[:, 7:] = 9999
    first = baseline_arrays(original, "registrations", 6, config())
    second = baseline_arrays(changed, "registrations", 6, config())
    assert first.keys() == second.keys()
    assert all(np.array_equal(first[name], second[name]) for name in first)


def test_missing_calendar_date_is_not_treated_as_zero():
    dates = [dt.date(2025, 1, 1), dt.date(2025, 1, 3)]
    broken = panel(
        level="hospital",
        series=[("hp:h1:p1", "r1", "p1")],
        values=np.zeros((1, 2)),
        dates=dates,
    )
    with pytest.raises(ValueError, match="missing dates"):
        assert_dense_observed(broken)


def test_zero_heavy_short_history_is_unsupported_and_metrics_remain_finite():
    values = np.array([[0.0] * 15 + [1.0]])
    sparse = panel(level="hospital", series=[("hp:h1:p1", "r1", "p1")], values=values)
    assert not support_mask(sparse, "registrations", 5, config())[0]
    scored = pd.DataFrame(
        {
            "series_id": ["a", "a", "b", "b"],
            "y": [0.0, 0.0, 0.0, 1.0],
            "prediction": [0.0, 0.2, 0.0, 0.8],
            "rmsse_scale": [0.0, 0.0, 1.0, 1.0],
            "supported": [False, False, True, True],
            "fallback_level": ["own_history_zero", "own_history_zero", "direct_model", "direct_model"],
        }
    )
    metrics = metric_record(scored)
    assert np.isfinite(metrics["poisson_deviance_pooled"])
    assert metrics["rmsse_supported_series"] == 1


def test_zero_only_parent_remains_direct_to_preserve_current_challenger_semantics():
    zero_parent = panel(
        level="region",
        series=[("rp:r1:p1", "r1", "p1")],
        values=np.zeros((1, 16)),
    )
    assert support_mask(zero_parent, "hospitalizations", 12, config())[0]


def test_national_forecast_diagnostic_requires_exact_region_sum():
    rows = []
    for level, series_id, region_code, prediction in (
        ("hospital", "hp:h1:p1", "r1", 1.5),
        ("region", "rp:r1:p1", "r1", 2.0),
        ("national", "np:p1", "__national__", 2.0),
    ):
        rows.append(
            {
                "candidate": "current_poisson_lightgbm",
                "level": level,
                "series_id": series_id,
                "phase": "validation",
                "origin": pd.Timestamp("2025-03-02"),
                "target": "registrations",
                "horizon": 1,
                "region_code": region_code,
                "profile_code": "p1",
                "prediction": prediction,
            }
        )
    diagnostics = forecast_hierarchy_diagnostics(pd.DataFrame(rows), "current_poisson_lightgbm")
    assert diagnostics["hospital_to_region"]["max_absolute_difference"] == 0.5
    assert diagnostics["region_to_national"]["max_absolute_difference"] == 0.0


def test_fallback_ladder_uses_supported_parent_and_records_level():
    panels = hierarchy_panels()
    combined = combine_panels(panels.values())
    direct = {("np:p1", horizon): 8.0 for horizon in (1, 2)}
    supported = {series_id: series_id == "np:p1" for series_id in combined.meta["series_id"]}
    predictions, levels = _fallback_predictions(
        combined,
        direct,
        supported,
        "registrations",
        origin_index=12,
        config=config(),
    )
    assert predictions[("rp:r1:p1", 1)] == 8.0
    assert predictions[("hp:h1:p1", 1)] == 2.0
    assert predictions[("hp:h2:p1", 1)] == 6.0
    assert levels["rp:r1:p1"] == "national_profile_share"
    assert levels["hp:h1:p1"] == "region_profile_share"


def test_hierarchy_rollups_are_exact_and_all_children_are_eligible():
    diagnostics = hierarchy_diagnostics(hierarchy_panels())
    assert diagnostics["hospital_series_with_region_profile_parent"] == 2
    assert diagnostics["region_series_with_national_profile_parent"] == 1
    assert diagnostics["data_rollups_exact"]
    assert "reconciliation_eligible" not in diagnostics
    assert all(check["region_to_national_exact"] for check in diagnostics["aggregation_checks"].values())


def test_summary_keeps_hierarchy_levels_separate_without_pooled_overall():
    rows = []
    for level, series_id, actual in (
        ("hospital", "hp:h1:p1", 1.0),
        ("region", "rp:r1:p1", 1.0),
        ("national", "np:p1", 1.0),
    ):
        rows.append(
            {
                "phase": "validation",
                "candidate": "recent_value",
                "target": "registrations",
                "level": level,
                "series_id": series_id,
                "region_code": "r1",
                "density_band": "dense",
                "fallback_level": "direct_history",
                "supported": True,
                "horizon": 1,
                "y": actual,
                "prediction": actual,
                "rmsse_scale": 1.0,
            }
        )
    summary = summarize_evaluation(pd.DataFrame(rows))
    assert "overall" not in summary
    assert {row["level"] for row in summary["canonical_per_level"]} == {
        "hospital",
        "region",
        "national",
    }
    assert sum(row["actual_total"] for row in summary["canonical_per_level"]) == 3.0
    assert all(row["actual_total"] == 1.0 for row in summary["canonical_per_level"])


def test_recommendation_uses_validation_only_and_names_strongest_baseline():
    rows = []
    for phase in ("validation", "final_test"):
        for target in ("registrations", "hospitalizations"):
            for level in ("hospital", "region", "national"):
                rows.extend(
                    [
                        {
                            "phase": phase,
                            "candidate": "current_poisson_lightgbm",
                            "target": target,
                            "level": level,
                            "wape": 0.4 if phase == "validation" else 0.01,
                        },
                        {
                            "phase": phase,
                            "candidate": "trailing_mean",
                            "target": target,
                            "level": level,
                            "wape": 0.3 if phase == "validation" else 0.9,
                        },
                    ]
                )
    result = validation_recommendation({"canonical_per_level": rows}, "current_poisson_lightgbm")
    assert result["candidate_level_target_wins"] == 0
    assert all(row["strongest_baseline"] == "trailing_mean" for row in result["comparisons"])
    assert "0/6" in result["reason"]
    assert result["selection_evidence"] == "validation only; final test excluded"


def test_extrapolation_diagnostics_are_report_only_and_handle_zero_support():
    frame = pd.DataFrame(
        {
            "candidate": ["model", "model", "model"],
            "phase": ["validation"] * 3,
            "target": ["registrations"] * 3,
            "level": ["region"] * 3,
            "series_id": ["rp:75:DH", "zero-zero", "zero-positive"],
            "origin": pd.to_datetime(["2025-02-23"] * 3),
            "horizon": [1, 1, 1],
            "historical_support_max": [10.0, 0.0, 0.0],
            "prediction": [60.0, 0.0, 2.0],
        }
    )
    result = extrapolation_diagnostics(frame, "model", threshold=5.0, example_limit=10)
    group = result["by_phase_target_level"][0]
    assert group["flagged_cells"] == 2
    assert group["positive_predictions_without_historical_support"] == 1
    assert result["predictions_clipped_to_threshold"] is False
    assert result["tracked_rp_75_DH"]["maximum_finite_ratio"] == 6.0
    assert len(result["positive_without_support_examples"]) == 1
    assert len(result["threshold_exceedance_examples"]) == 1
    assert result["worst_finite_ratio_examples"][0]["series_id"] == "rp:75:DH"


def test_atomic_artifact_publication_ignores_incomplete_attempts(tmp_path):
    parent = tmp_path / "artifacts"
    abandoned_partial = parent / ".validation-2025-03-02.partial-abandoned"
    abandoned_published = parent / "validation-2025-03-02-abandoned"
    abandoned_partial.mkdir(parents=True)
    abandoned_published.mkdir()
    (abandoned_partial / "half-written").write_text("partial", encoding="utf-8")

    def writer(path):
        (path / "result.json").write_text("{}\n", encoding="utf-8")

    published, manifest = store.publish_artifact_directory(parent, "validation-2025-03-02", writer)
    assert published != abandoned_published
    assert published.is_dir()
    assert store.verify_artifact_manifest(published) == manifest
    assert abandoned_partial.exists()


def test_origin_checkpoint_identity_is_deterministic_and_phase_specific():
    origin = dt.date(2025, 3, 2)
    first = origin_key(origin, "validation")
    second = origin_key(origin, "validation")
    test = origin_key(origin, "final_test")
    assert first.identifier == second.identifier
    assert first.identifier != test.identifier
    assert first.forecast_origin == "2025-03-02"


def test_lightgbm_thread_count_is_not_a_scientific_hyperparameter():
    one_thread = scientific_lightgbm_parameters({"learning_rate": 0.05, "num_threads": 1})
    four_threads = scientific_lightgbm_parameters({"learning_rate": 0.05, "num_threads": 4})
    assert one_thread == four_threads == {"learning_rate": 0.05}


def test_completed_origin_checkpoint_is_reused_on_resume(tmp_path):
    resources = resource_config("smoke", cpu_count=2)
    plan = {
        "scientific_identity_sha256": "flow-plan",
        "identity_sha256": "flow-plan",
        "scientific_identity": {"workflow": "flow-evidence"},
        "models": ["load_forecast"],
        "model_families": {"load_forecast": "global_gradient_boosted_count_forecast"},
        "prediction_targets": {"load_forecast": ["registrations", "hospitalizations"]},
        "dataset": {"identity_sha256": "data"},
        "configuration": {"sha256": "config"},
        "code": {"source": {"sha256": "code"}},
        "implementation_versions": {"python": "3.12", "lightgbm": "4.7.0"},
        "execution": execution_metadata(resources),
    }
    key = origin_key(dt.date(2025, 3, 2), "validation")
    parameters = {"challenger": "current_poisson_lightgbm", "tuning": False}
    artifact = tmp_path / "flow" / "origin"
    artifact.mkdir(parents=True)
    (artifact / "metrics.json").write_text("{}\n", encoding="utf-8")
    manifest = store.write_artifact_manifest(artifact)
    run = ExperimentRun.start(tmp_path, plan, run_id="flow-resume")
    run.start_checkpoint(key, parameters=parameters)
    run.complete_checkpoint(
        key,
        parameters=parameters,
        metrics={"wape": 1.0},
        evaluation_status="completed",
        artifact_path=artifact,
        artifact_sha256=manifest["content_sha256"],
        version="validation-2025-03-02",
    )
    run.pause()
    run.release_lock()

    resumed = ExperimentRun.start(tmp_path, plan, resume_run_id="flow-resume")
    try:
        checkpoint = resumed.reusable_checkpoint(key, parameters=parameters)
        assert checkpoint is not None
        assert checkpoint["metrics"]["wape"] == 1.0
    finally:
        resumed.release_lock()
