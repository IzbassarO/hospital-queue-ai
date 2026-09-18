from __future__ import annotations

import math

import numpy as np
import pandas as pd
from sklearn.isotonic import IsotonicRegression
from sklearn.linear_model import LogisticRegression

from hqai_ml.evaluation.metrics import calibration_table
from hqai_ml.tournament.labels import EVENT_CENSORED, EVENT_HOSPITALIZED, EVENT_REFUSED


def assert_horizon_observable(labels: pd.DataFrame, horizon: int) -> None:
    """Reject naive horizon metrics when administrative censoring enters the horizon."""
    duration = labels["journey_duration_days"].to_numpy(float)
    event = labels["journey_event"].to_numpy(int)
    inside = (event == EVENT_CENSORED) & (duration < horizon)
    if inside.any():
        raise ValueError(
            f"cannot evaluate naive Brier/concordance at {horizon} days: "
            f"{int(inside.sum())} referrals are censored inside the evaluated horizon; "
            "use an IPCW estimator or a later label cutoff"
        )


def observed_outcomes(labels: pd.DataFrame, horizon: int) -> tuple[np.ndarray, np.ndarray]:
    assert_horizon_observable(labels, horizon)
    duration = labels["journey_duration_days"].to_numpy(float)
    event = labels["journey_event"].to_numpy(int)
    observed = (duration >= horizon) | ((event != 0) & (duration <= horizon))
    outcome = np.zeros(len(labels), dtype=np.int8)
    outcome[(event == EVENT_HOSPITALIZED) & (duration <= horizon)] = EVENT_HOSPITALIZED
    outcome[(event == EVENT_REFUSED) & (duration <= horizon)] = EVENT_REFUSED
    return outcome, observed


def harrell_concordance(labels: pd.DataFrame, resolved_risk: np.ndarray, limit: int = 2000) -> float | None:
    """Deterministic bounded Harrell C for any terminal event."""
    if len(labels) > limit:
        index = np.linspace(0, len(labels) - 1, limit, dtype=int)
        labels = labels.iloc[index]
        resolved_risk = np.asarray(resolved_risk)[index]
    duration = labels["journey_duration_days"].to_numpy(float)
    event = labels["journey_event"].to_numpy(int) != 0
    concordant = comparable = 0.0
    for i in range(len(labels)):
        if not event[i]:
            continue
        later = duration > duration[i]
        comparable += later.sum()
        concordant += (resolved_risk[i] > resolved_risk[later]).sum()
        concordant += 0.5 * (resolved_risk[i] == resolved_risk[later]).sum()
    return float(concordant / comparable) if comparable else None


def expected_calibration_error(y: np.ndarray, probability: np.ndarray, bins: int = 10) -> float:
    table = calibration_table(y, probability, min(bins, max(1, len(y))))
    total = sum(row["n"] for row in table)
    return float(sum(row["n"] * abs(row["mean_pred"] - row["observed"]) for row in table) / total)


def journey_metrics(
    labels: pd.DataFrame,
    probabilities: dict[int, dict[str, np.ndarray]],
    *,
    hospitalization_only: bool = False,
) -> dict:
    rows = {}
    max_horizon = max(probabilities)
    assert_horizon_observable(labels, max_horizon)
    for horizon, values in sorted(probabilities.items()):
        outcome, observed = observed_outcomes(labels, horizon)
        if not observed.any():
            continue
        p_h = np.asarray(values["hospitalized"])[observed]
        p_r = np.asarray(values["refused"])[observed]
        p_u = np.asarray(values["unresolved"])[observed]
        y = outcome[observed]
        coherence = np.abs(p_h + p_r + p_u - 1)
        unresolved_target = (y != EVENT_HOSPITALIZED) if hospitalization_only else (y == 0)
        brier_refused = None if hospitalization_only else float(np.mean((p_r - (y == EVENT_REFUSED)) ** 2))
        brier_multiclass = None
        if not hospitalization_only:
            brier_multiclass = float(
                np.mean(
                    (p_h - (y == EVENT_HOSPITALIZED)) ** 2
                    + (p_r - (y == EVENT_REFUSED)) ** 2
                    + (p_u - unresolved_target) ** 2
                )
            )
        rows[str(horizon)] = {
            "n": int(observed.sum()),
            "brier_survival": float(np.mean((p_u - unresolved_target) ** 2)),
            "brier_hospitalized": float(np.mean((p_h - (y == EVENT_HOSPITALIZED)) ** 2)),
            "brier_refused": brier_refused,
            "brier_multiclass": brier_multiclass,
            "mean_predicted": {
                "hospitalized": float(p_h.mean()),
                "refused": float(p_r.mean()),
                "unresolved": float(p_u.mean()),
            },
            "observed": {
                "hospitalized": float((y == EVENT_HOSPITALIZED).mean()),
                "refused": float((y == EVENT_REFUSED).mean()),
                "unresolved": float(unresolved_target.mean()),
            },
            "calibration": {
                "hospitalized": calibration_table((y == EVENT_HOSPITALIZED).astype(int), p_h, min(10, len(y))),
                "refused": (
                    None
                    if hospitalization_only
                    else calibration_table((y == EVENT_REFUSED).astype(int), p_r, min(10, len(y)))
                ),
                "unresolved": calibration_table(unresolved_target.astype(int), p_u, min(10, len(y))),
            },
            "coherence_max_abs_error": float(coherence.max()),
        }
    risk = 1 - np.asarray(probabilities[max_horizon]["unresolved"])
    estimand = (
        "cumulative incidence of hospitalization by each emitted horizon; refusal treated as competing censoring"
        if hospitalization_only
        else "three-state distribution of hospitalized, refused, or unresolved by each emitted horizon"
    )
    primary_name = (
        "mean_hospitalization_brier_at_emitted_horizons"
        if hospitalization_only
        else "mean_multiclass_brier_at_emitted_horizons"
    )
    component = "brier_hospitalized" if hospitalization_only else "brier_multiclass"
    primary = float(np.mean([row[component] for row in rows.values()]))
    return {
        "by_horizon": rows,
        "primary_metric_name": primary_name,
        "primary_metric": primary,
        "concordance": harrell_concordance(
            labels
            if not hospitalization_only
            else labels.assign(
                journey_event=np.where(labels["journey_event"] == EVENT_HOSPITALIZED, EVENT_HOSPITALIZED, 0)
            ),
            risk,
        ),
        "estimand": estimand,
        "evaluated_horizons_days": [int(horizon) for horizon in sorted(probabilities)],
        "metric_note": "arithmetic mean of Brier scores only at matching emitted prediction horizons",
    }


def hpo_objective(
    validation_labels: pd.DataFrame,
    validation_probabilities: dict[int, dict[str, np.ndarray]],
    *,
    hospitalization_only: bool,
) -> tuple[float, dict]:
    """The HPO API intentionally accepts validation data only, never final-test labels."""
    metrics = journey_metrics(
        validation_labels,
        validation_probabilities,
        hospitalization_only=hospitalization_only,
    )
    return metrics["primary_metric"], metrics


class ProbabilityCalibrator:
    def __init__(self, method: str):
        self.method = method
        self.model = None

    def fit(self, probability: np.ndarray, y: np.ndarray) -> ProbabilityCalibrator:
        p = np.clip(np.asarray(probability, float), 1e-6, 1 - 1e-6)
        if self.method == "uncalibrated":
            return self
        if self.method == "sigmoid":
            self.model = LogisticRegression(C=1.0, solver="lbfgs", random_state=42).fit(
                np.log(p / (1 - p)).reshape(-1, 1), y
            )
        elif self.method == "isotonic":
            self.model = IsotonicRegression(out_of_bounds="clip").fit(p, y)
        else:
            raise ValueError(f"unknown calibration method {self.method!r}")
        return self

    def predict(self, probability: np.ndarray) -> np.ndarray:
        p = np.clip(np.asarray(probability, float), 1e-6, 1 - 1e-6)
        if self.method == "uncalibrated":
            return p
        if self.method == "sigmoid":
            return self.model.predict_proba(np.log(p / (1 - p)).reshape(-1, 1))[:, 1]
        return np.asarray(self.model.predict(p), float)

    def to_dict(self) -> dict:
        payload = {"method": self.method}
        if self.method == "sigmoid" and self.model is not None:
            payload.update(
                coefficient=float(self.model.coef_[0, 0]),
                intercept=float(self.model.intercept_[0]),
            )
        elif self.method == "isotonic" and self.model is not None:
            payload.update(
                x_thresholds=self.model.X_thresholds_.astype(float).tolist(),
                y_thresholds=self.model.y_thresholds_.astype(float).tolist(),
            )
        return payload

    @classmethod
    def from_dict(cls, payload: dict) -> ProbabilityCalibrator:
        calibrator = cls(payload["method"])
        if calibrator.method == "sigmoid":
            model = LogisticRegression()
            model.classes_ = np.array([0, 1])
            model.coef_ = np.array([[payload["coefficient"]]], dtype=float)
            model.intercept_ = np.array([payload["intercept"]], dtype=float)
            model.n_features_in_ = 1
            calibrator.model = model
        elif calibrator.method == "isotonic":
            model = IsotonicRegression(out_of_bounds="clip")
            x = np.asarray(payload["x_thresholds"], dtype=float)
            y = np.asarray(payload["y_thresholds"], dtype=float)
            model.X_thresholds_ = x
            model.y_thresholds_ = y
            model.X_min_, model.X_max_ = x[0], x[-1]
            model.f_ = lambda values: np.interp(values, x, y)
            calibrator.model = model
        return calibrator


def select_calibrator(probability: np.ndarray, y: np.ndarray) -> tuple[str, dict]:
    """Fit on the earlier half, choose on the later half; never inspect final-test labels."""
    if len(y) < 20 or len(np.unique(y)) < 2:
        return "uncalibrated", {"reason": "insufficient temporal calibration support"}
    cut = len(y) // 2
    scores = {}
    for method in ("uncalibrated", "sigmoid", "isotonic"):
        try:
            calibrator = ProbabilityCalibrator(method).fit(probability[:cut], y[:cut])
            pred = calibrator.predict(probability[cut:])
            scores[method] = float(np.mean((pred - y[cut:]) ** 2))
        except ValueError:
            scores[method] = math.inf
    selected = min(scores, key=scores.get)
    return selected, {"selection_brier": scores, "fit_rows": cut, "selection_rows": len(y) - cut}


def calibrate_journey(
    calibration_labels: pd.DataFrame,
    calibration_probabilities: dict[int, dict[str, np.ndarray]],
    test_probabilities: dict[int, dict[str, np.ndarray]],
) -> tuple[dict[int, dict[str, np.ndarray]], dict]:
    """Calibrate resolved probability, preserving cause shares and exact probability coherence."""
    output, evidence = {}, {}
    for horizon, test in sorted(test_probabilities.items()):
        outcome, observed = observed_outcomes(calibration_labels, horizon)
        resolved = 1 - np.asarray(calibration_probabilities[horizon]["unresolved"])
        method, selection = select_calibrator(resolved[observed], (outcome[observed] != 0).astype(int))
        calibrator = ProbabilityCalibrator(method).fit(resolved[observed], (outcome[observed] != 0).astype(int))
        test_resolved_raw = 1 - np.asarray(test["unresolved"])
        test_resolved = calibrator.predict(test_resolved_raw)
        cause_total = np.asarray(test["hospitalized"]) + np.asarray(test["refused"])
        hospital_share = np.divide(
            np.asarray(test["hospitalized"]), cause_total, out=np.ones_like(cause_total), where=cause_total > 0
        )
        p_h = test_resolved * hospital_share
        p_r = test_resolved * (1 - hospital_share)
        output[horizon] = {"hospitalized": p_h, "refused": p_r, "unresolved": 1 - test_resolved}
        evidence[str(horizon)] = {
            "selected": method,
            "target": "any_terminal_event_by_horizon",
            "parameters": calibrator.to_dict(),
            **selection,
        }
    return output, evidence


def calibrate_hospitalization(
    calibration_labels: pd.DataFrame,
    calibration_probabilities: dict[int, dict[str, np.ndarray]],
    test_probabilities: dict[int, dict[str, np.ndarray]],
) -> tuple[dict[int, dict[str, np.ndarray]], dict]:
    """Calibrate hospitalization-only models without pretending they model refusal."""
    output, evidence = {}, {}
    for horizon, test in sorted(test_probabilities.items()):
        outcome, observed = observed_outcomes(calibration_labels, horizon)
        probability = np.asarray(calibration_probabilities[horizon]["hospitalized"])
        y = (outcome == EVENT_HOSPITALIZED).astype(int)
        method, selection = select_calibrator(probability[observed], y[observed])
        calibrator = ProbabilityCalibrator(method).fit(probability[observed], y[observed])
        p_h = calibrator.predict(np.asarray(test["hospitalized"]))
        output[horizon] = {
            "hospitalized": p_h,
            "refused": np.zeros(len(p_h)),
            "unresolved": 1 - p_h,
        }
        evidence[str(horizon)] = {
            "selected": method,
            "target": "hospitalized_by_horizon",
            "parameters": calibrator.to_dict(),
            **selection,
        }
    return output, evidence


def subgroup_assurance(
    labels: pd.DataFrame,
    probabilities: dict[int, dict[str, np.ndarray]],
    baseline: dict[int, dict[str, np.ndarray]],
    support_buckets: list[int],
    *,
    hospitalization_only: bool = False,
) -> dict:
    horizon = max(probabilities)
    outcome, observed = observed_outcomes(labels, horizon)
    p = np.asarray(probabilities[horizon]["unresolved"])
    b = (
        1 - np.asarray(baseline[horizon]["hospitalized"])
        if hospitalization_only
        else np.asarray(baseline[horizon]["unresolved"])
    )
    rows = labels.loc[observed, ["region_code", "profile_code"]].copy()
    target = outcome[observed] != EVENT_HOSPITALIZED if hospitalization_only else outcome[observed] == 0
    rows["error"] = (p[observed] - target) ** 2
    rows["baseline_error"] = (b[observed] - target) ** 2

    def summarize(column: str) -> list[dict]:
        return [
            {
                "segment": str(segment),
                "n": int(len(group)),
                "brier": float(group["error"].mean()),
                "baseline_brier": float(group["baseline_error"].mean()),
            }
            for segment, group in rows.groupby(column, dropna=False)
        ]

    regions = summarize("region_code")
    profiles = summarize("profile_code")
    supported_regions = [row for row in regions if row["n"] >= support_buckets[0]]
    region_values = [row["brier"] for row in supported_regions]
    cuts = [-1, *support_buckets, np.inf]
    names = [
        f"0-{support_buckets[0]}",
        *[f"{a + 1}-{b}" for a, b in zip(support_buckets, support_buckets[1:], strict=False)],
        f">{support_buckets[-1]}",
    ]
    region_frame = pd.DataFrame(regions)
    region_frame["support_bucket"] = pd.cut(region_frame["n"], bins=cuts, labels=names)
    return {
        "regions": regions,
        "supported_regions": supported_regions,
        "major_profiles": sorted(profiles, key=lambda row: row["n"], reverse=True)[:10],
        "median_region_brier": float(np.median(region_values)) if region_values else None,
        "worst_region_brier": float(max(region_values)) if region_values else None,
        "regions_losing_baseline": int(sum(row["brier"] > row["baseline_brier"] for row in supported_regions)),
        "low_support_regions": [row for row in regions if row["n"] < support_buckets[0]],
        "support_buckets": [
            {"bucket": str(bucket), "regions": int(len(group))}
            for bucket, group in region_frame.groupby("support_bucket", observed=True)
        ],
    }
