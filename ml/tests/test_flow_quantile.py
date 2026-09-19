from __future__ import annotations

import datetime as dt

import numpy as np
import pandas as pd
import pytest
from pydantic import ValidationError

from hqai_ml.features.load import Panel
from hqai_ml.flow_forecast.config import FlowQuantileConfig
from hqai_ml.flow_forecast.evidence import combine_panels, national_panel
from hqai_ml.flow_forecast.quantile import (
    BASELINE,
    NATIONAL_PROXY,
    RAW_VARIANT,
    REPAIRED_VARIANT,
    _apply_hierarchy_fallback,
    _prediction_frame,
    empirical_interval_coverage,
    empirical_residual_predictions,
    interval_score_80,
    interval_width,
    negative_output_rate,
    pinball_loss,
    quantile_crossing,
    quantile_extrapolation_diagnostics,
    repair_quantiles,
    summarize_probabilistic_evaluation,
    validation_retention,
    weighted_interval_score_80,
)
from hqai_ml.registry import store
from hqai_ml.registry.experiment import ExperimentRun, execution_metadata
from hqai_ml.registry.resources import resource_config
from pipelines.flow_quantile import (
    calibration_identity,
    public_hierarchy_diagnostics,
    quantile_origin_key,
    scientific_lightgbm_parameters,
    temporal_protocol,
)


def config(**updates) -> FlowQuantileConfig:
    raw = {
        "schema_version": 1,
        "seed": 42,
        "horizon": 2,
        "targets": ["registrations", "cohort_hospitalizations"],
        "validation_origins": [dt.date(2025, 1, 20), dt.date(2025, 1, 25)],
        "final_test_origin": dt.date(2025, 1, 29),
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
        "residual_uncertainty": {
            "method": "horizon_specific_empirical_residual",
            "window_days": 14,
            "minimum_samples": 7,
        },
        "challenger": {
            "id": "quantile_lightgbm",
            "quantiles": [0.1, 0.5, 0.9],
            "rounds": 10,
            "scientific_evidence_variant": RAW_VARIANT,
            "serving_diagnostic_variant": REPAIRED_VARIANT,
        },
        "automatic_promotion": False,
    }
    raw.update(updates)
    return FlowQuantileConfig(**raw)


def panel(level: str, series: list[tuple[str, str, str]], values: np.ndarray) -> Panel:
    dates = [dt.date(2025, 1, 1) + dt.timedelta(days=offset) for offset in range(values.shape[1])]
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


def test_pinball_loss_for_under_over_and_exact_predictions():
    y = np.array([10.0, 10.0, 10.0])
    prediction = np.array([8.0, 12.0, 10.0])
    assert pinball_loss(y, prediction, 0.1).tolist() == pytest.approx([0.2, 1.8, 0.0])
    assert pinball_loss(y, prediction, 0.9).tolist() == pytest.approx([1.8, 0.2, 0.0])


def test_interval_score_and_wis_are_exact_for_covered_value():
    y = np.array([5.0])
    lower, median, upper = np.array([3.0]), np.array([5.0]), np.array([7.0])
    assert interval_score_80(y, lower, upper)[0] == 4.0
    assert weighted_interval_score_80(y, lower, median, upper)[0] == pytest.approx(0.4 / 1.5)


def test_coverage_interval_width_and_negative_output_rate_are_directly_scored():
    y = np.array([0.0, 1.0, 2.0, 3.0])
    lower = np.array([0.0, 0.5, 2.1, 0.0])
    upper = np.array([0.0, 1.5, 4.0, 2.0])
    assert empirical_interval_coverage(y, lower, upper) == 0.5
    assert interval_width(lower, upper).tolist() == pytest.approx([0.0, 1.0, 1.9, 2.0])
    assert negative_output_rate(
        np.array([-1.0, 0.0]),
        np.array([0.0, -2.0]),
        np.array([1.0, 2.0]),
    ) == pytest.approx(2 / 6)


def test_residual_calibration_never_uses_targets_after_origin():
    values = np.arange(1, 41, dtype=float)[None, :]
    series = panel("hospital", [("hp:h1:p1", "r1", "p1")], values)
    predictions, audit = empirical_residual_predictions(series, "registrations", 24, config())
    assert audit["targets_at_or_before_origin"] is True
    assert audit["maximum_calibration_target_date"] == "2025-01-25"
    assert all(len(predictions[quantile]) == 2 for quantile in (0.1, 0.5, 0.9))


def test_crossing_is_detected_and_repair_is_explicit_nonnegative_monotone():
    raw = np.array([[-1.0, 4.0, 2.0], [3.0, 2.0, 1.0]])
    assert quantile_crossing(raw[:, 0], raw[:, 1], raw[:, 2]).tolist() == [True, True]
    repaired = repair_quantiles(raw)
    assert repaired.tolist() == [[0.0, 4.0, 4.0], [3.0, 3.0, 3.0]]
    assert (repaired >= 0).all()
    assert (np.diff(repaired, axis=1) >= 0).all()


def metric_frame() -> pd.DataFrame:
    rows = []
    for level, series_id in (
        ("hospital", "hp:h:p"),
        ("region", "rp:r:p"),
        ("national", "np:p"),
    ):
        rows.append(
            {
                "phase": "validation",
                "candidate": BASELINE,
                "variant": RAW_VARIANT,
                "target": "registrations",
                "level": level,
                "series_id": series_id,
                "horizon": 1,
                "density_band": "dense",
                "supported": True,
                "fallback_level": "none",
                "aggregation_method": "none",
                "prediction_source": "statistical_residual_baseline",
                "uncertainty_support": "estimated",
                "y": 2.0,
                "p10": 1.0,
                "p50": 2.0,
                "p90": 3.0,
                "rmsse_scale": 1.0,
            }
        )
    return pd.DataFrame(rows)


def test_canonical_metrics_never_pool_hierarchy_levels():
    summary = summarize_probabilistic_evaluation(metric_frame())
    assert "overall" not in summary
    canonical = summary["canonical_per_level"]
    assert len(canonical) == 3
    assert {row["level"] for row in canonical} == {"hospital", "region", "national"}
    assert all(row["actual_total"] == 2.0 for row in canonical)


def test_fallback_quantiles_use_region_share_and_preserve_provenance():
    hospital = panel("hospital", [("hp:h1:p1", "r1", "p1")], np.ones((1, 40)))
    region = panel("region", [("rp:r1:p1", "r1", "p1")], np.full((1, 40), 4.0))
    panels = {"hospital": hospital, "region": region, "national": national_panel(region)}
    combined = combine_panels(panels.values())
    direct = {
        quantile: {("rp:r1:p1", horizon): value for horizon in (1, 2)}
        for quantile, value in ((0.1, 8.0), (0.5, 12.0), (0.9, 16.0))
    }
    supported = {"hp:h1:p1": False, "rp:r1:p1": True, "np:p1": True}
    predictions, provenance = _apply_hierarchy_fallback(
        direct,
        panels,
        combined,
        supported,
        "registrations",
        24,
        config(),
    )
    assert predictions[0.5][("hp:h1:p1", 1)] == 3.0
    assert provenance["hp:h1:p1"] == "region_profile_share"
    assert provenance["np:p1"] == NATIONAL_PROXY


def test_candidate_provenance_and_degenerate_uncertainty_are_explicit():
    metadata = pd.DataFrame(
        {
            "series_id": ["direct", "zero", "national"],
            "horizon": [1, 1, 1],
            "level": ["hospital", "hospital", "national"],
        }
    )
    predictions = {
        quantile: {(series_id, 1): value for series_id in metadata["series_id"]}
        for quantile, value in ((0.1, 0.0), (0.5, 1.0), (0.9, 2.0))
    }
    fallback = {
        "direct": "direct_model",
        "zero": "own_history_zero",
        "national": NATIONAL_PROXY,
    }
    baseline = _prediction_frame(metadata, predictions, fallback, BASELINE, "calibration")
    raw = baseline[baseline["variant"] == RAW_VARIANT].set_index("series_id")
    assert raw.loc["direct", "prediction_source"] == "statistical_residual_baseline"
    assert raw.loc["direct", "fallback_level"] == "none"
    assert raw.loc["zero", "prediction_source"] == "deterministic_own_history_fallback"
    assert raw.loc["zero", "uncertainty_support"] == ("degenerate_interval_no_estimated_uncertainty_support")
    assert raw.loc["national", "aggregation_method"] == NATIONAL_PROXY

    challenger = _prediction_frame(metadata, predictions, fallback, "quantile_lightgbm", "not_applicable")
    challenger_raw = challenger[challenger["variant"] == RAW_VARIANT].set_index("series_id")
    assert challenger_raw.loc["direct", "prediction_source"] == "direct_quantile_ml"


def test_extrapolation_diagnostics_cover_each_quantile_and_zero_history():
    frame = metric_frame().iloc[[0]].copy()
    frame["origin"] = pd.to_datetime(["2025-01-20"])
    frame["historical_support_max"] = 0.0
    frame[["p10", "p50", "p90"]] = [0.0, 1.0, 2.0]
    diagnostics = quantile_extrapolation_diagnostics(frame, threshold=5.0, example_limit=10)
    groups = diagnostics["by_phase_candidate_variant_target_level_quantile"]
    assert {group["quantile"] for group in groups} == {"p10", "p50", "p90"}
    assert sum(group["flagged_cells"] for group in groups) == 2
    assert diagnostics["predictions_clipped_to_threshold"] is False


def test_thread_count_is_execution_metadata_and_not_scientific_parameters():
    one = scientific_lightgbm_parameters({"learning_rate": 0.05, "num_threads": 1})
    four = scientific_lightgbm_parameters({"learning_rate": 0.05, "num_threads": 4})
    assert one == four == {"learning_rate": 0.05}


def test_repaired_metrics_cannot_change_raw_validation_retention():
    def metrics(repaired_model_pinball: float, repaired_model_wis: float) -> dict:
        rows = []
        for variant in (RAW_VARIANT, REPAIRED_VARIANT):
            rows.extend(
                [
                    {
                        "phase": "validation",
                        "candidate": BASELINE,
                        "variant": variant,
                        "target": "registrations",
                        "level": "hospital",
                        "mean_pinball_macro_series": 0.5,
                        "wis_80_macro_series": 1.0,
                    },
                    {
                        "phase": "validation",
                        "candidate": "quantile_lightgbm",
                        "variant": variant,
                        "target": "registrations",
                        "level": "hospital",
                        "mean_pinball_macro_series": (0.4 if variant == RAW_VARIANT else repaired_model_pinball),
                        "wis_80_macro_series": 0.8 if variant == RAW_VARIANT else repaired_model_wis,
                    },
                ]
            )
        return {"canonical_per_level": rows}

    repaired_wins = validation_retention(metrics(0.1, 0.1), "quantile_lightgbm")
    repaired_loses = validation_retention(metrics(9.0, 9.0), "quantile_lightgbm")
    assert repaired_wins == repaired_loses
    assert repaired_wins["outcome"] == "both_retained"
    assert repaired_wins["primary_scientific_evidence_variant"] == RAW_VARIANT
    assert repaired_wins["repaired_metrics_govern_retention"] is False


def test_plan_protocol_and_checkpoint_identities_are_deterministic():
    configured = config()
    protocol = temporal_protocol(configured)
    assert protocol["validation_origins"] == ["2025-01-20", "2025-01-25"]
    assert protocol["final_test_used_for_selection_or_calibration"] is False
    first = quantile_origin_key(dt.date(2025, 1, 20), "validation")
    again = quantile_origin_key(dt.date(2025, 1, 20), "validation")
    final = quantile_origin_key(dt.date(2025, 1, 29), "final_test")
    assert first.identifier == again.identifier
    assert first.identifier != final.identifier


def test_completed_quantile_origin_is_reusable_after_resume(tmp_path):
    resources = resource_config("smoke", cpu_count=2)
    plan = {
        "scientific_identity_sha256": "quantile-plan",
        "identity_sha256": "quantile-plan",
        "scientific_identity": {"workflow": "flow-quantile-evidence"},
        "models": ["load_forecast"],
        "model_families": {"load_forecast": "global_gradient_boosted_count_forecast"},
        "prediction_targets": {"load_forecast": ["registrations", "hospitalizations"]},
        "dataset": {"identity_sha256": "data"},
        "configuration": {"sha256": "config"},
        "code": {"source": {"sha256": "code"}},
        "implementation_versions": {"python": "3.12", "lightgbm": "4.7.0"},
        "execution": execution_metadata(resources),
    }
    key = quantile_origin_key(dt.date(2025, 1, 20), "validation")
    parameters = {"quantiles": [0.1, 0.5, 0.9], "calibration_identity": "calibration"}
    artifact = tmp_path / "quantile" / "origin"
    artifact.mkdir(parents=True)
    (artifact / "evaluation.json").write_text("{}\n", encoding="utf-8")
    manifest = store.write_artifact_manifest(artifact)
    run = ExperimentRun.start(tmp_path, plan, run_id="quantile-resume")
    run.start_checkpoint(key, parameters=parameters)
    run.complete_checkpoint(
        key,
        parameters=parameters,
        metrics={"mean_pinball": 1.0},
        evaluation_status="completed",
        artifact_path=artifact,
        artifact_sha256=manifest["content_sha256"],
        version="validation-2025-01-20",
    )
    run.pause()
    run.release_lock()

    resumed = ExperimentRun.start(tmp_path, plan, resume_run_id="quantile-resume")
    try:
        checkpoint = resumed.reusable_checkpoint(key, parameters=parameters)
        assert checkpoint is not None
        assert checkpoint["metrics"]["mean_pinball"] == 1.0
    finally:
        resumed.release_lock()


def test_calibration_has_an_independent_deterministic_identity():
    first = config()
    second = config(
        residual_uncertainty={
            "method": "horizon_specific_empirical_residual",
            "window_days": 21,
            "minimum_samples": 7,
        }
    )
    assert calibration_identity(first) == calibration_identity(first)
    assert calibration_identity(first) != calibration_identity(second)


def test_public_target_name_must_be_cohort_hospitalizations():
    with pytest.raises(ValidationError, match="cohort_hospitalizations"):
        config(targets=["registrations", "hospitalizations"])


def test_generated_hierarchy_summary_uses_public_cohort_name():
    converted = public_hierarchy_diagnostics(
        {"aggregation_checks": {"registrations": {}, "hospitalizations": {"exact": True}}}
    )
    assert "hospitalizations" not in converted["aggregation_checks"]
    assert converted["aggregation_checks"]["cohort_hospitalizations"] == {"exact": True}
