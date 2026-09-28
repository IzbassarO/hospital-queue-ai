from __future__ import annotations

import inspect
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from hqai_ml.origin_journey import aft as aft_module
from hqai_ml.origin_journey import baseline as baseline_module
from hqai_ml.origin_journey import hazard as hazard_module
from hqai_ml.origin_journey.aft import AFTModel
from hqai_ml.origin_journey.baseline import AJCurve, HierarchicalAJ
from hqai_ml.origin_journey.config import load_origin_journey_config
from hqai_ml.origin_journey.encoding import CATEGORICAL_FEATURES, NUMERIC_FEATURES, FeatureEncoder
from hqai_ml.origin_journey.evaluation import apply_decision_rule
from hqai_ml.origin_journey.hazard import CompetingHazardModel, expand_person_period

CONFIG_PATH = Path(__file__).parents[1] / "configs" / "origin_journey.yaml"


def _features(rows: int) -> pd.DataFrame:
    frame = pd.DataFrame(index=range(rows))
    for column in CATEGORICAL_FEATURES:
        frame[column] = "x"
    for column in NUMERIC_FEATURES:
        frame[column] = 0
    return frame


def test_aalen_johansen_conditional_cif_and_hierarchical_fallback():
    config = load_origin_journey_config(CONFIG_PATH)
    training = _features(5)
    training["org_code"] = ["A", "A", "A", "B", "B"]
    training["hospital_region_code"] = "R"
    training["profile_code"] = "P"
    training["observed_duration_days"] = [1.0, 2.0, 3.0, 4.0, 5.0]
    training["event_type_at_origin"] = ["hospitalized", "refused", "censored", "hospitalized", "censored"]
    training["label_eligible"] = True
    config.baseline.min_rows = 3
    model = HierarchicalAJ.fit(training, config)
    scoring = _features(2)
    scoring["org_code"] = ["A", "B"]
    scoring["hospital_region_code"] = "R"
    scoring["profile_code"] = "P"
    scoring["days_waited_at_origin"] = [1, 1]

    probabilities, levels = model.probabilities(scoring, (1,))

    assert levels == ["org_codexprofile_code", "hospital_region_codexprofile_code"]
    curve_a = AJCurve.fit(training.iloc[:3])
    start_h, _, start_s = curve_a.state(1)
    end_h, _, _ = curve_a.state(2)
    assert probabilities[1]["hospitalized"][0] == pytest.approx(float((end_h - start_h) / start_s))
    assert np.allclose(
        probabilities[1]["hospitalized"] + probabilities[1]["refused"] + probabilities[1]["unresolved"],
        1,
    )


def test_person_period_expansion_marks_event_only_in_its_actual_interval():
    frame = _features(1)
    frame["observed_duration_days"] = [3.0]
    frame["event_type_at_origin"] = ["hospitalized"]
    encoder = FeatureEncoder.fit(frame)

    _, labels = expand_person_period(frame, encoder, (0, 1, 2, 3, 4))

    assert labels.tolist() == [0, 0, 1]


class _FixedHazardBooster:
    def predict(self, matrix, num_iteration=None):
        return np.tile([0.7, 0.2, 0.1], (len(matrix), 1))


def test_competing_hazard_is_left_truncated_and_coherent():
    scoring = _features(2)
    scoring["days_waited_at_origin"] = [0, 1]
    encoder = FeatureEncoder.fit(scoring)
    model = CompetingHazardModel(_FixedHazardBooster(), encoder, (0, 1, 2), 1)

    probabilities = model.probabilities(scoring, (1,))[1]

    assert probabilities["hospitalized"] == pytest.approx([0.2, 0.2])
    assert probabilities["refused"] == pytest.approx([0.1, 0.1])
    assert probabilities["unresolved"] == pytest.approx([0.7, 0.7])
    assert np.allclose(probabilities["hospitalized"] + probabilities["refused"] + probabilities["unresolved"], 1)


class _FixedAFTBooster:
    def predict(self, matrix, iteration_range=None):
        return np.full(matrix.num_row(), 10.0)


def test_aft_uses_conditional_survival_after_elapsed_wait():
    scoring = _features(1)
    scoring["days_waited_at_origin"] = [5]
    encoder = FeatureEncoder.fit(scoring)
    model = AFTModel(_FixedAFTBooster(), encoder, "logistic", 1.0, 1)

    probability = model.probabilities(scoring, (5,))[5]["hospitalized"][0]

    assert probability == pytest.approx(0.25)


def test_precommitted_decision_requires_overall_win_and_bucket_noninferiority():
    config = load_origin_journey_config(CONFIG_PATH)

    def result(overall, bucket):
        return {
            "overall": {"mean_admission_and_refusal_brier": overall},
            "subgroups": {
                "days_waited": {
                    name: {"mean_admission_and_refusal_brier": value}
                    for name, value in zip(("0", "1-6", "7-13", "14-29", "30-59", "60+"), bucket, strict=True)
                }
            },
        }

    metrics = {
        "aalen_johansen": result(0.10, [0.10] * 6),
        "xgboost_aft": result(0.09, [0.10] * 5 + [0.106]),
        "discrete_competing_risk": result(0.095, [0.101] * 6),
    }

    decision = apply_decision_rule(metrics, config)

    assert not decision["candidate_decisions"]["xgboost_aft"]["accepted"]
    assert decision["candidate_decisions"]["discrete_competing_risk"]["accepted"]
    assert decision["selected_model"] == "discrete_competing_risk"
    assert config.decision.max_days_waited_bucket_degradation == 0.005


def test_training_modules_have_no_hindsight_dependency():
    for module in (aft_module, baseline_module, hazard_module):
        assert "origin_journey.evaluation" not in inspect.getsource(module)
