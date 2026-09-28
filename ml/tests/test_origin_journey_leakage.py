from __future__ import annotations

from pathlib import Path

import pandas as pd

from hqai_ml.origin_journey.cohorts import build_origin_cohorts
from hqai_ml.origin_journey.config import load_origin_journey_config

CONFIG_PATH = Path(__file__).parents[1] / "configs" / "origin_journey.yaml"


def test_outcomes_after_origin_never_survive_the_training_boundary():
    config = load_origin_journey_config(CONFIG_PATH)
    source = pd.DataFrame(
        {
            "referral_id": [1, 2],
            "hospitalization_code": ["75.A.01.1", "75.A.01.2"],
            "region_code": ["75", "75"],
            "org_code": ["A", "A"],
            "hospital_region_code": ["75", "75"],
            "profile_code": ["01", "01"],
            "icd10_code": ["I10", "I10"],
            "territorial_type": ["city", "city"],
            "referral_purpose": ["planned", "planned"],
            "finance_source": ["state", "state"],
            "registration_date": ["2025-01-01", "2025-01-01"],
            "hospitalization_date": ["2025-03-18", None],
            "refusal_date": [None, "2026-05-12"],
        }
    )

    training = build_origin_cohorts(source, config).training

    assert set(training["event_type_at_origin"]) == {"censored"}
    assert training["administratively_censored"].all()
    assert training["observed_duration_days"].nunique() == 1
    assert training["observed_duration_days"].iloc[0] == 75
    raw_outcome_columns = {
        "hospitalization_date",
        "refusal_date",
        "resolution_date",
        "outcome",
        "wait_days",
        "wait_to_refusal_days",
    }
    assert raw_outcome_columns.isdisjoint(training.columns)


def test_referrals_registered_after_origin_cannot_enter_scoring():
    config = load_origin_journey_config(CONFIG_PATH)
    source = pd.DataFrame(
        {
            "referral_id": [1],
            "hospitalization_code": ["75.A.01.1"],
            "region_code": ["75"],
            "org_code": ["A"],
            "hospital_region_code": ["75"],
            "profile_code": ["01"],
            "icd10_code": ["I10"],
            "territorial_type": ["city"],
            "referral_purpose": ["planned"],
            "finance_source": ["state"],
            "registration_date": ["2025-03-18"],
            "hospitalization_date": [None],
            "refusal_date": [None],
        }
    )

    cohorts = build_origin_cohorts(source, config)

    assert cohorts.training.empty
    assert cohorts.scoring.empty
