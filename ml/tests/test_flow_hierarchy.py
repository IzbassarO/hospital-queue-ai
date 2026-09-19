from __future__ import annotations

import datetime as dt

import numpy as np
import pandas as pd
import pytest

from hqai_ml.flow_forecast.config import FlowHierarchyConfig
from hqai_ml.flow_forecast.hierarchy import (
    BLENDED_FALLBACK,
    BOTTOM_UP,
    CURRENT_FALLBACK,
    PARENT_SCALING,
    calibration_source_origin_key,
    coherence_metrics,
    evaluate_hierarchy,
    fallback_forecast_values,
    load_verified_calibration_intervals,
    reconcile_central,
)
from hqai_ml.registry import store
from hqai_ml.registry.experiment import ExperimentRun, execution_metadata
from hqai_ml.registry.resources import resource_config


def config(**updates) -> FlowHierarchyConfig:
    raw = {
        "schema_version": 1,
        "version": "test-hierarchy-v1",
        "seed": 42,
        "horizon": 14,
        "targets": ["registrations", "cohort_hospitalizations"],
        "validation_origins": [dt.date(2025, 2, 16), dt.date(2025, 2, 23), dt.date(2025, 3, 2)],
        "final_test_origin": dt.date(2025, 3, 17),
        "source_candidate": "quantile_lightgbm",
        "source_raw_variant": "raw",
        "source_central_variant": "repaired_nonnegative_monotone",
        "calibration_method": "conformal_interval_expansion",
        "alternatives": ["current_direct", "bottom_up_hospital", "parent_consistent_region_scaling"],
        "hierarchy_selection_metrics": [
            "hospital_wape",
            "region_wape",
            "national_wape",
            "hospital_mae_macro_series",
            "hospital_rmsse_macro_series",
        ],
        "coherence_tolerance": 1e-9,
        "material_change_absolute": 0.1,
        "material_change_relative": 0.05,
        "fallback": {
            "candidates": [CURRENT_FALLBACK, BLENDED_FALLBACK],
            "full_own_weight_nonzero_days": 14,
            "maximum_own_weight": 0.5,
            "selection_metrics": ["wape", "mae_macro_series", "rmsse_macro_series"],
        },
        "automatic_promotion": False,
        "probabilistic_reconciliation_applied": False,
        "identity_sha256": "test-config",
    }
    raw.update(updates)
    return FlowHierarchyConfig(**raw)


def hierarchy_frame() -> pd.DataFrame:
    entities = [
        ("hospital", "hp:h1:p1", "h1", "r1", 6.0, 6.0, True, "none", 6.0),
        ("hospital", "hp:h2:p1", "h2", "r1", 4.0, 8.0, False, "region_profile_share", 8.0),
        ("hospital", "hp:h3:p1", "h3", "r2", 3.0, 3.0, True, "none", 3.0),
        ("hospital", "hp:h4:p1", "h4", "r2", 2.0, 4.0, False, "region_profile_share", 4.0),
        ("region", "rp:r1:p1", "__region__", "r1", 12.0, 12.0, True, "none", np.nan),
        ("region", "rp:r2:p1", "__region__", "r2", 4.0, 4.0, True, "none", np.nan),
        (
            "national",
            "np:p1",
            "__national__",
            "__national__",
            20.0,
            16.0,
            True,
            "region_quantile_sum_proxy",
            np.nan,
        ),
    ]
    rows = []
    for phase, origin in (("validation", "2025-03-02"), ("final_test", "2025-03-17")):
        for level, series_id, org_code, region_code, central, y, supported, fallback, own in entities:
            rows.append(
                {
                    "phase": phase,
                    "origin": pd.Timestamp(origin),
                    "target": "registrations",
                    "level": level,
                    "series_id": series_id,
                    "org_code": org_code,
                    "region_code": region_code,
                    "profile_code": "p1",
                    "horizon": 1,
                    "target_date": pd.Timestamp(origin) + pd.Timedelta(days=1),
                    "y": y,
                    "rmsse_scale": 1.0,
                    "supported": supported,
                    "fallback_level": fallback,
                    "prediction_source": "direct_quantile_ml" if supported else "parent_scaled_direct_quantile_ml",
                    "uncertainty_support": "estimated",
                    "source_central_value": central,
                    "raw_p10": central - 1.0,
                    "raw_p50": central,
                    "raw_p90": central + 1.0,
                    "own_recent_seasonal": own,
                    "history_total": 20.0 if level == "hospital" else np.nan,
                    "history_nonzero_days": 14 if level == "hospital" else np.nan,
                    "calibration_status": "calibrated" if level != "national" else "unsupported",
                    "calibration_version": "cal-v1",
                    "level_local_interval_80_lower": central - 2.0 if level != "national" else np.nan,
                    "level_local_interval_80_upper": central + 2.0 if level != "national" else np.nan,
                    "base_forecast_source": "direct_quantile_ml",
                }
            )
    return pd.DataFrame(rows)


@pytest.mark.parametrize("alternative", [BOTTOM_UP, PARENT_SCALING])
def test_reconciled_central_forecasts_are_exact_at_both_boundaries(alternative):
    frame = hierarchy_frame()
    values, _, _ = reconcile_central(frame, frame["source_central_value"].to_numpy(), alternative)
    diagnostics = coherence_metrics(frame, values, 1e-9)
    assert all(row["exact_within_tolerance"] for row in diagnostics)
    assert all(row["max_absolute_error"] == pytest.approx(0.0) for row in diagnostics)


def test_parent_scaling_preserves_region_parent_and_handles_zero_parent():
    frame = hierarchy_frame().query("phase == 'validation'").reset_index(drop=True)
    base = frame["source_central_value"].to_numpy(copy=True)
    base[frame["region_code"].eq("r1") & frame["level"].eq("region")] = 0.0
    values, _, _ = reconcile_central(frame, base, PARENT_SCALING)
    r1_children = frame["region_code"].eq("r1") & frame["level"].eq("hospital")
    assert values[r1_children].tolist() == [0.0, 0.0]
    region = frame["level"].eq("region")
    assert values[region].tolist() == base[region].tolist()


def test_positive_parent_with_zero_children_uses_history_and_rejects_no_history():
    frame = hierarchy_frame().query("phase == 'validation'").reset_index(drop=True)
    r1_children = frame["region_code"].eq("r1") & frame["level"].eq("hospital")
    base = frame["source_central_value"].to_numpy(copy=True)
    base[r1_children] = 0.0
    frame.loc[r1_children, "history_total"] = [60.0, 40.0]
    values, _, _ = reconcile_central(frame, base, PARENT_SCALING)
    assert values[r1_children].tolist() == pytest.approx([7.2, 4.8])
    frame.loc[r1_children, "history_total"] = 0.0
    with pytest.raises(ValueError, match="no historical support"):
        reconcile_central(frame, base, PARENT_SCALING)


def test_fallback_blend_preserves_no_history_and_records_provenance():
    frame = hierarchy_frame()
    first = frame.index[(frame["level"] == "hospital") & (frame["fallback_level"] == "region_profile_share")][0]
    frame.loc[first, ["history_total", "history_nonzero_days", "own_recent_seasonal"]] = [0.0, 0, 0.0]
    frame.loc[first, "fallback_level"] = "own_history_zero"
    frame.loc[first, "source_central_value"] = 0.0
    forecasts = fallback_forecast_values(frame, config())
    assert forecasts[BLENDED_FALLBACK][first] == forecasts[CURRENT_FALLBACK][first] == 0.0
    output, analysis = evaluate_hierarchy(frame, config())
    assert analysis["fallback_selection"]["final_test_used_for_selection"] is False
    assert set(output["fallback_status"]) >= {"no_history_deterministic_zero"}


def test_raw_predictions_and_probabilistic_semantics_are_preserved():
    frame = hierarchy_frame()
    raw = frame[["raw_p10", "raw_p50", "raw_p90"]].to_numpy(copy=True)
    output, _ = evaluate_hierarchy(frame, config())
    assert np.array_equal(output[["raw_p10", "raw_p50", "raw_p90"]].to_numpy(), raw)
    assert not {"p10", "p50", "p90", "reconciled_p10", "reconciled_p90"} & set(output.columns)
    national = output[output["level"] == "national"]
    assert set(national["raw_quantile_semantics"]) == {"historical_region_quantile_sum_proxy_not_national_distribution"}
    assert not output["probabilistic_reconciliation_applied"].any()


def test_selection_is_validation_only_and_ui_metadata_is_complete():
    frame = hierarchy_frame()
    first, first_analysis = evaluate_hierarchy(frame, config())
    changed = frame.copy()
    changed.loc[changed["phase"] == "final_test", "y"] = 1_000_000.0
    second, second_analysis = evaluate_hierarchy(changed, config())
    assert first_analysis["fallback_selection"] == second_analysis["fallback_selection"]
    assert first_analysis["hierarchy_selection"] == second_analysis["hierarchy_selection"]
    expected = {
        "forecast_value",
        "forecast_source",
        "hierarchy_status",
        "support_status",
        "fallback_status",
        "uncertainty_status",
        "calibration_version",
    }
    assert expected <= set(first.columns)


def test_calibration_artifact_checkpoint_and_source_lineage_are_verified(tmp_path):
    resources = resource_config("smoke", cpu_count=2)
    version = "cal-v1"
    plan = {
        "scientific_identity_sha256": "calibration-science",
        "identity_sha256": "calibration-science",
        "scientific_identity": {"workflow": "calibration"},
        "models": ["load_forecast"],
        "model_families": {"load_forecast": "global_gradient_boosted_count_forecast"},
        "prediction_targets": {"load_forecast": ["registrations", "hospitalizations"]},
        "dataset": {"identity_sha256": "data"},
        "configuration": {"sha256": "config"},
        "code": {"source": {"sha256": "code"}},
        "implementation_versions": {"python": "3.12"},
        "hyperparameters": {
            "calibration_version": version,
            "calibration": {
                "methods": ["conformal_interval_expansion"],
                "source_variant": "raw",
            },
            "source_run": {
                "run_id": "source-run",
                "scientific_identity": "source-science",
                "artifact_identity": "source-artifacts",
            },
        },
        "execution": execution_metadata(resources),
    }
    origin = dt.date(2025, 2, 16)
    key = calibration_source_origin_key(origin, "validation", version)
    parameters = {
        "calibration_version": version,
        "source_artifact_identity": "source-artifacts",
        "methods": ["conformal_interval_expansion"],
        "source_variant": "raw",
    }
    artifact = tmp_path / "calibration-origin"
    artifact.mkdir()
    pd.DataFrame(
        [{"calibration_method": "conformal_interval_expansion", "origin": origin, "phase": "validation"}]
    ).to_parquet(artifact / "calibrated-evaluation.parquet", index=False)
    (artifact / "metadata.json").write_text(
        store.canonical_json({"resources": {"origin": str(origin), "phase": "validation"}}), encoding="utf-8"
    )
    manifest = store.write_artifact_manifest(artifact)
    run = ExperimentRun.start(tmp_path, plan, run_id="calibration-run")
    run.start_checkpoint(key, parameters=parameters)
    run.complete_checkpoint(
        key,
        parameters=parameters,
        metrics={},
        evaluation_status="completed",
        artifact_path=artifact,
        artifact_sha256=manifest["content_sha256"],
        version=version,
    )
    run.complete([key], parameters_by_key={key.identifier: parameters})
    run.release_lock()

    loaded, lineage = load_verified_calibration_intervals(
        tmp_path,
        "calibration-run",
        "source-run",
        "source-science",
        "source-artifacts",
        [(origin, "validation")],
        "conformal_interval_expansion",
    )
    assert len(loaded) == 1
    assert lineage["origin_artifacts"][0]["artifact_sha256"] == manifest["content_sha256"]
    with pytest.raises(ValueError, match="artifact_identity"):
        load_verified_calibration_intervals(
            tmp_path,
            "calibration-run",
            "source-run",
            "source-science",
            "changed-artifacts",
            [(origin, "validation")],
            "conformal_interval_expansion",
        )
