import inspect
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from hqai_ml.registry.experiment import CheckpointKey, ExperimentRun
from hqai_ml.tournament.candidates import (
    AFTModel,
    CategoricalFrameEncoder,
    FrequencyEncoder,
    HazardModel,
    _aj_estimate,
    _expanded_hazard_rows,
)
from hqai_ml.tournament.config import (
    LabelContract,
    TournamentConfig,
    deterministic_trials,
    load_tournament_config,
)
from hqai_ml.tournament.evaluation import (
    ProbabilityCalibrator,
    hpo_objective,
    journey_metrics,
    select_calibrator,
    subgroup_assurance,
)
from hqai_ml.tournament.labels import (
    EVENT_CENSORED,
    EVENT_HOSPITALIZED,
    EVENT_REFUSED,
    aft_bounds,
    construct_journey_labels,
    recensor_at,
)
from pipelines.tournament import legacy_fold_eligibility, select_cross_fold_trial

ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = ROOT / "ml" / "configs" / "tournament.yaml"


def contract() -> LabelContract:
    return LabelContract(
        start="registration_dt",
        cutoff="2025-04-01T00:00:00",
        same_day_min_duration_days=0.5,
        refusal_is_terminal=True,
        refusal_basis="source queue-resolution timestamp",
        exclude_event_conflicts=True,
        exclude_events_before_registration=True,
    )


def raw_rows() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "referral_id": range(1, 8),
            "registration_dt": pd.to_datetime(
                [
                    "2025-03-01 10:00",
                    "2025-03-01",
                    "2025-03-01",
                    "2025-03-02",
                    None,
                    "2025-03-01",
                    "2025-03-01 12:00",
                ],
                format="mixed",
            ),
            "hospitalization_dt": pd.to_datetime(
                ["2025-03-01 12:00", None, None, "2025-03-01", None, "2025-03-10", "2025-03-01 08:00"],
                format="mixed",
            ),
            "refusal_dt": pd.to_datetime([None, "2025-03-06", None, None, None, "2025-03-11", None], format="mixed"),
            "is_dup_code": [False, False, True, False, False, False, False],
            "org_code": ["H1", "H1", "H2", "H2", "H2", "H1", "H1"],
            "profile_code": ["P1", "P1", "P2", "P2", "P2", "P1", "P1"],
            "referral_purpose": ["A", "A", "B", "B", "B", "A", "A"],
        }
    )


def test_right_censor_terminal_semantics_and_fixed_cutoff():
    result = construct_journey_labels(raw_rows(), contract())
    assert result.rows["journey_event"].tolist() == [
        EVENT_HOSPITALIZED,
        EVENT_REFUSED,
        EVENT_CENSORED,
        EVENT_HOSPITALIZED,
    ]
    assert result.rows.loc[0, "journey_duration_days"] == 0.5
    assert result.rows.loc[2, "journey_raw_duration_days"] == 31
    assert result.rows.loc[3, "journey_duration_days"] == 0.5
    assert result.audit["event_counts"] == {"censored": 1, "hospitalized": 2, "refused": 1}
    assert result.audit["same_calendar_pre_registration_included"] == 1
    assert result.audit["strict_timestamp_order_sensitivity"]["additional_exclusions_vs_main"] == 1
    assert set(result.audit["cohort_by_dimension"]) == {"hospital", "profile", "purpose"}
    assert result.audit["cutoff"] == "2025-04-01T00:00:00"


def test_impossible_and_conflicting_events_are_counted_not_silently_clamped():
    result = construct_journey_labels(raw_rows(), contract())
    assert result.audit["excluded_rows"] == 3
    assert result.audit["exclusion_reasons"] == {
        "conflicting_terminal_events": 1,
        "event_on_earlier_calendar_date": 1,
        "missing_registration": 1,
    }
    assert (result.rows["journey_duration_days"] >= 0.5).all()


def test_event_after_cutoff_becomes_censored_at_the_fixed_cutoff():
    rows = raw_rows().iloc[[0]].copy()
    rows["hospitalization_dt"] = pd.Timestamp("2025-04-02")
    result = construct_journey_labels(rows, contract())
    assert result.rows.loc[0, "journey_event"] == EVENT_CENSORED
    assert result.audit["events_hidden_after_cutoff"] == 1


def test_aft_bounds_use_infinity_for_right_censoring():
    labels = pd.DataFrame(
        {"journey_duration_days": [2.0, 4.0, 8.0], "journey_event": [EVENT_HOSPITALIZED, EVENT_REFUSED, 0]}
    )
    lower, upper = aft_bounds(labels)
    assert lower.tolist() == [2, 4, 8]
    assert upper[0] == 2 and np.isinf(upper[1:]).all()


def feature_frame(n: int) -> pd.DataFrame:
    from hqai_ml.tournament.candidates import FEATURES

    frame = pd.DataFrame(index=range(n))
    for feature in FEATURES:
        frame[feature] = (
            "x"
            if feature.endswith("code")
            or feature
            in {
                "referral_purpose",
                "finance_source",
                "territorial_type",
                "icd_chapter",
                "icd3",
            }
            else 0.0
        )
    return frame


class FixedHazardBooster:
    def __init__(self, competing: bool):
        self.competing = competing

    def predict(self, matrix, num_iteration=None):
        if self.competing:
            return np.tile([0.7, 0.2, 0.1], (len(matrix), 1))
        return np.full(len(matrix), 0.2)


def test_discrete_hazard_survival_is_monotonic_and_competing_probabilities_cohere():
    frame = feature_frame(3)
    encoder = CategoricalFrameEncoder.fit(frame)
    model = HazardModel(FixedHazardBooster(True), encoder, [0, 1, 7, 14, 30], True, 1)
    probabilities = model.probabilities(frame, [1, 7, 14, 30])
    survival = np.array([probabilities[h]["unresolved"] for h in [1, 7, 14, 30]])
    assert np.all(np.diff(survival, axis=0) <= 0)
    for values in probabilities.values():
        assert np.allclose(values["hospitalized"] + values["refused"] + values["unresolved"], 1)


def test_discrete_expansion_does_not_count_partial_censored_interval_as_no_event():
    frame = feature_frame(2)
    frame["journey_duration_days"] = [2.0, 2.0]
    frame["journey_event"] = [EVENT_HOSPITALIZED, EVENT_CENSORED]
    encoder = CategoricalFrameEncoder.fit(frame)
    _, labels = _expanded_hazard_rows(frame, encoder, [0, 1, 3], competing=False)
    assert labels.tolist() == [0, 0, 1]


class CaptureAFTBooster:
    def __init__(self):
        self.iteration_range = None

    def predict(self, matrix, *, iteration_range=None):
        self.iteration_range = iteration_range
        return np.full(matrix.num_row(), 10.0)


def test_aft_prediction_uses_only_early_stopped_trees():
    frame = feature_frame(2)
    booster = CaptureAFTBooster()
    model = AFTModel(booster, CategoricalFrameEncoder.fit(frame), "logistic", 1.0, best_iteration=4)
    model.probabilities(frame, [7])
    assert booster.iteration_range == (0, 5)


def test_native_categories_and_train_only_frequency_encoding_are_not_ordinal():
    frame = feature_frame(3)
    frame["region_code"] = ["A", "A", "B"]
    native = CategoricalFrameEncoder.fit(frame).transform(frame)
    assert isinstance(native["region_code"].dtype, pd.CategoricalDtype)
    assert "day_of_window" not in native
    frequency = FrequencyEncoder.fit(frame)
    assert frequency.transform(frame)[:, 0].tolist() == pytest.approx([2 / 3, 2 / 3, 1 / 3])
    unseen = frame.iloc[[0]].copy()
    unseen["region_code"] = "never-seen"
    assert frequency.transform(unseen)[0, 0] == 0


def test_hpo_contract_has_no_final_test_argument_and_calibration_split_is_temporal():
    assert "test" not in inspect.signature(hpo_objective).parameters
    probability = np.linspace(0.01, 0.99, 40)
    y = (probability > 0.5).astype(int)
    _, evidence = select_calibrator(probability, y)
    assert evidence["fit_rows"] == evidence["selection_rows"] == 20


def simple_probabilities(n: int):
    return {
        horizon: {
            "hospitalized": np.full(n, 0.4),
            "refused": np.full(n, 0.1),
            "unresolved": np.full(n, 0.5),
        }
        for horizon in (7, 14, 30)
    }


def test_subgroup_metrics_include_worst_region_and_low_support():
    labels = pd.DataFrame(
        {
            "journey_duration_days": [2, 8, 40, 40],
            "journey_event": [1, 2, 0, 0],
            "region_code": ["A", "A", "A", "B"],
            "profile_code": ["P", "P", "P", "Q"],
        }
    )
    metrics = journey_metrics(labels, simple_probabilities(4))
    assert metrics["by_horizon"]["30"]["coherence_max_abs_error"] == pytest.approx(0)
    assert metrics["primary_metric_name"] == "mean_multiclass_brier_at_emitted_horizons"
    assert metrics["primary_metric"] == pytest.approx(
        np.mean([row["brier_multiclass"] for row in metrics["by_horizon"].values()])
    )
    assert not any("integrated" in key for key in metrics)
    assurance = subgroup_assurance(labels, simple_probabilities(4), simple_probabilities(4), [3, 10])
    assert assurance["worst_region_brier"] is not None
    assert {row["segment"] for row in assurance["supported_regions"]} == {"A"}
    assert {row["segment"] for row in assurance["low_support_regions"]} == {"B"}


def test_metrics_fail_when_censoring_enters_an_evaluated_horizon():
    labels = pd.DataFrame(
        {
            "journey_duration_days": [10.0],
            "journey_event": [EVENT_CENSORED],
            "region_code": ["A"],
            "profile_code": ["P"],
        }
    )
    with pytest.raises(ValueError, match="censored inside the evaluated horizon"):
        journey_metrics(labels, simple_probabilities(1))


def test_empirical_competing_risk_curve_matches_known_counts():
    labels = pd.DataFrame({"journey_duration_days": [1.0, 2.0, 3.0, 40.0], "journey_event": [1, 2, 1, 0]})
    curve = _aj_estimate(labels, [1, 2, 3])
    assert curve[1] == pytest.approx((0.25, 0.0, 0.75))
    assert sum(curve[3]) == pytest.approx(1.0)


@pytest.mark.parametrize("method", ["sigmoid", "isotonic"])
def test_persisted_calibrator_reproduces_predictions(method):
    probability = np.linspace(0.05, 0.95, 40)
    y = (probability > 0.45).astype(int)
    calibrator = ProbabilityCalibrator(method).fit(probability, y)
    restored = ProbabilityCalibrator.from_dict(calibrator.to_dict())
    assert restored.predict(probability) == pytest.approx(calibrator.predict(probability))


def test_historical_recensoring_hides_only_outcomes_unknown_at_cutoff():
    labels = pd.DataFrame(
        {
            "registration_dt": pd.to_datetime(["2025-01-01", "2025-01-01"]),
            "journey_duration_days": [5.0, 20.0],
            "journey_event": [EVENT_HOSPITALIZED, EVENT_REFUSED],
        }
    )
    historical = recensor_at(labels, pd.Timestamp("2025-01-11"))
    assert historical["journey_event"].tolist() == [EVENT_HOSPITALIZED, EVENT_CENSORED]
    assert historical["journey_duration_days"].tolist() == [5.0, 10.0]


def test_sobol_search_is_deterministic_bounded_and_overnight_sized():
    config = load_tournament_config(CONFIG_PATH)
    first = deterministic_trials(config, "xgboost_aft", 32)
    assert first == deterministic_trials(config, "xgboost_aft", 32)
    assert len(first) == 32 and len({json.dumps(row, sort_keys=True) for row in first}) == 32
    assert all(2 <= row["max_depth"] <= 6 and 80 <= row["rounds"] <= 300 for row in first)
    assert config.profiles["overnight"].max_trials == 32


def test_cross_fold_selection_and_legacy_contamination_policy():
    trials = [
        {"trial_id": "trial-000", "mean_validation_primary_metric": 0.20},
        {"trial_id": "trial-001", "mean_validation_primary_metric": 0.15},
    ]
    assert select_cross_fold_trial(trials)["trial_id"] == "trial-001"
    config = load_tournament_config(CONFIG_PATH)
    for fold in config.folds:
        eligible, reason = legacy_fold_eligibility(
            "legacy_wait_regression", fold, config.legacy_artifacts_trained_through
        )
        assert not eligible and "in-sample metrics are excluded" in reason


def run_plan(config_identity: str) -> dict:
    resources = {
        "profile": "smoke",
        "detected_cpu_count": 1,
        "cpu_budget": 1,
        "model_threads": 1,
        "parallel_trials": 1,
        "process_concurrency": 1,
        "detected_memory_bytes": 1024**3,
        "memory_budget_bytes": 512 * 1024**2,
        "duckdb_threads": 1,
        "duckdb_memory_limit": "512MiB",
    }
    return {
        "scientific_identity_sha256": config_identity,
        "identity_sha256": config_identity,
        "scientific_identity": {},
        "models": ["patient_journey"],
        "model_families": {"patient_journey": "survival_and_competing_risk_tournament"},
        "prediction_targets": {"patient_journey": ["hospitalized_by_horizon"]},
        "dataset": {"identity_sha256": "data"},
        "configuration": {"sha256": config_identity},
        "code": {"source": {"sha256": "code"}},
        "temporal_protocols": {},
        "random_seeds": {"python": 42},
        "hyperparameters": {},
        "implementation_versions": {},
        "execution": {"resources": resources, "platform": {"system": "test", "machine": "test"}},
    }


def test_trial_fold_checkpoint_is_reused_with_identical_identity(tmp_path: Path):
    config = load_tournament_config(CONFIG_PATH)
    plan = run_plan(config.identity_sha256)
    run = ExperimentRun.start(tmp_path, plan, run_id="journey-resume")
    key = CheckpointKey("patient_journey", "xgboost_aft", "trial-000", "q1_final")
    parameters = {"max_depth": 3}
    run.start_checkpoint(key, parameters=parameters)
    run.complete_checkpoint(
        key, parameters=parameters, metrics={"validation_primary_metric": 0.2}, evaluation_status="completed"
    )
    run.release_lock()
    resumed = ExperimentRun.start(tmp_path, plan, resume_run_id="journey-resume")
    assert resumed.reusable_checkpoint(key, parameters=parameters)["metrics"]["validation_primary_metric"] == 0.2
    resumed.complete([key], parameters_by_key={key.identifier: parameters})
    assert resumed.manifest["status"] == "completed"
    resumed.release_lock()


def test_tournament_config_identity_is_deterministic_and_auto_promotion_is_impossible():
    first = load_tournament_config(CONFIG_PATH)
    second = load_tournament_config(CONFIG_PATH)
    assert first.identity_sha256 == second.identity_sha256
    assert first.promotion_constraints.automatic_promotion is False
    source = (ROOT / "ml" / "pipelines" / "tournament.py").read_text(encoding="utf-8")
    assert "set_current" not in source
    assert json.loads(first.model_dump_json())["horizons"] == [7, 14, 30]


def test_competing_risk_requires_validated_terminal_refusal_semantics():
    payload = load_tournament_config(CONFIG_PATH).model_dump(mode="json")
    payload["label_contract"]["refusal_is_terminal"] = False
    with pytest.raises(ValueError, match="terminal-refusal semantics"):
        TournamentConfig(**payload)
