from __future__ import annotations

import lightgbm as lgb
import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from hqai_ml.evaluation.metrics import classification_metrics
from hqai_ml.features.referral import CATEGORICAL
from hqai_ml.models.referral_model import ReferralModel
from hqai_ml.tournament.candidates import CategoricalFrameEncoder, FrequencyEncoder
from hqai_ml.tournament.evaluation import ProbabilityCalibrator, expected_calibration_error, select_calibrator
from hqai_ml.tournament.labels import EVENT_HOSPITALIZED, EVENT_REFUSED


def _resolved(frame: pd.DataFrame) -> pd.DataFrame:
    return frame[frame["journey_event"].isin([EVENT_HOSPITALIZED, EVENT_REFUSED])].copy()


def _metrics(y: np.ndarray, probability: np.ndarray) -> dict:
    result = classification_metrics(y, probability, 0.10)
    result["calibration_error"] = expected_calibration_error(y, probability)
    return result


def refusal_benchmarks(
    train: pd.DataFrame,
    validation: pd.DataFrame,
    calibration: pd.DataFrame,
    test: pd.DataFrame,
    artifacts_dir,
    policy: dict,
    threads: int,
    low_support_threshold: int,
    *,
    legacy_eligible: bool = False,
    legacy_ineligibility_reason: str | None = None,
) -> dict:
    train, validation, calibration, test = map(_resolved, (train, validation, calibration, test))
    frequency_encoder = FrequencyEncoder.fit(train)
    categorical_encoder = CategoricalFrameEncoder.fit(train)

    y_train = (train["journey_event"] == EVENT_REFUSED).to_numpy(int)
    y_test = (test["journey_event"] == EVENT_REFUSED).to_numpy(int)
    logistic_probe = make_pipeline(
        StandardScaler(),
        LogisticRegression(C=float(policy["logistic_c"]), max_iter=1000, solver="lbfgs", random_state=42),
    ).fit(frequency_encoder.transform(train), y_train)
    y_validation = (validation["journey_event"] == EVENT_REFUSED).to_numpy(int)
    logistic_validation = logistic_probe.predict_proba(frequency_encoder.transform(validation))[:, 1]
    lgb_policy = policy["lightgbm"]
    lgb_params = {
        "objective": "binary",
        "metric": "binary_logloss",
        "num_leaves": int(lgb_policy["num_leaves"]),
        "learning_rate": float(lgb_policy["learning_rate"]),
        "min_data_in_leaf": int(lgb_policy["min_data_in_leaf"]),
        "num_threads": threads,
        "seed": 42,
        "verbosity": -1,
        "deterministic": True,
        "force_row_wise": True,
    }
    lgb_probe = lgb.train(
        lgb_params,
        lgb.Dataset(categorical_encoder.transform(train), y_train, categorical_feature=CATEGORICAL),
        int(lgb_policy["rounds"]),
        valid_sets=[
            lgb.Dataset(categorical_encoder.transform(validation), y_validation, categorical_feature=CATEGORICAL)
        ],
        callbacks=[lgb.early_stopping(20, verbose=False)],
    )
    lgb_validation = lgb_probe.predict(
        categorical_encoder.transform(validation), num_iteration=lgb_probe.best_iteration
    )
    validation_brier = {
        "regularized_logistic": float(np.mean((logistic_validation - y_validation) ** 2)),
        "fold_lightgbm": float(np.mean((lgb_validation - y_validation) ** 2)),
    }
    selected = min(validation_brier, key=validation_brier.get)
    development = pd.concat([train, validation], ignore_index=True)
    y_development = (development["journey_event"] == EVENT_REFUSED).to_numpy(int)
    if selected == "regularized_logistic":
        development_frequency_encoder = FrequencyEncoder.fit(development)
        strongest = make_pipeline(
            StandardScaler(),
            LogisticRegression(C=float(policy["logistic_c"]), max_iter=1000, solver="lbfgs", random_state=42),
        ).fit(development_frequency_encoder.transform(development), y_development)

        def strongest_predict(frame):
            return strongest.predict_proba(development_frequency_encoder.transform(frame))[:, 1]

    else:
        development_categorical_encoder = CategoricalFrameEncoder.fit(development)
        strongest = lgb.train(
            lgb_params,
            lgb.Dataset(
                development_categorical_encoder.transform(development),
                y_development,
                categorical_feature=CATEGORICAL,
            ),
            max(1, lgb_probe.best_iteration),
        )

        def strongest_predict(frame):
            return strongest.predict(development_categorical_encoder.transform(frame))

    p_logistic = logistic_probe.predict_proba(frequency_encoder.transform(test))[:, 1]
    p_lgb = lgb_probe.predict(categorical_encoder.transform(test), num_iteration=lgb_probe.best_iteration)
    prevalence = float(y_train.mean())
    output = {
        "estimand": "probability of refusal conditional on an observed terminal referral outcome",
        "population": {
            "train_rows": len(train),
            "validation_rows": len(validation),
            "calibration_rows": len(calibration),
            "test_rows": len(test),
            "test_refusal_rate": float(y_test.mean()),
        },
        "empirical_prevalence": _metrics(y_test, np.full(len(test), prevalence)),
        "regularized_logistic": _metrics(y_test, p_logistic),
        "fold_lightgbm": _metrics(y_test, p_lgb),
        "strongest_selected_on_validation": selected,
        "validation_brier": validation_brier,
        "calibration": {},
    }
    if legacy_eligible:
        try:
            legacy = ReferralModel.load(artifacts_dir, "refusal_risk")
            output["legacy_lightgbm_secondary_benchmark"] = _metrics(y_test, legacy.predict(test))
            output["legacy_note"] = "eligible out-of-sample secondary benchmark; never used for HPO"
        except FileNotFoundError:
            output["legacy_note"] = "current refusal artifact unavailable"
    else:
        output["legacy_note"] = legacy_ineligibility_reason or "legacy artifact excluded from this fold"
        output["legacy_eligible"] = False

    p_cal = strongest_predict(calibration)
    p_strongest_test = strongest_predict(test)
    y_cal = (calibration["journey_event"] == EVENT_REFUSED).to_numpy(int)
    for method in ("uncalibrated", "sigmoid", "isotonic"):
        calibrator = ProbabilityCalibrator(method).fit(p_cal, y_cal)
        output["calibration"][method] = {
            **_metrics(y_test, calibrator.predict(p_strongest_test)),
            "parameters": calibrator.to_dict(),
        }
    selected_calibration, selection_evidence = select_calibrator(p_cal, y_cal)
    selected_calibrator = ProbabilityCalibrator(selected_calibration).fit(p_cal, y_cal)
    selected_probability = selected_calibrator.predict(p_strongest_test)
    region_rows = []
    for region, indexes in test.groupby("region_code", dropna=False).groups.items():
        positions = test.index.get_indexer(indexes)
        metrics = _metrics(y_test[positions], selected_probability[positions])
        region_rows.append({"region": str(region), **metrics})
    supported = [row for row in region_rows if row["n"] >= low_support_threshold]
    output["selected_calibration"] = {
        "method": selected_calibration,
        "parameters": selected_calibrator.to_dict(),
        **selection_evidence,
    }
    output["regional_assurance"] = {
        "regions": region_rows,
        "median_supported_region_brier": float(np.median([row["brier"] for row in supported])) if supported else None,
        "worst_supported_region_brier": max((row["brier"] for row in supported), default=None),
        "worst_region_degradation_vs_national": max(
            (row["brier"] - output["calibration"][selected_calibration]["brier"] for row in supported), default=None
        ),
        "low_support_regions": [row for row in region_rows if row["n"] < low_support_threshold],
    }
    output["calibration_policy"] = (
        "strongest eligible fold classifier selected on validation; calibrators fit calibration only; final test "
        "is evaluation-only"
    )
    return output
