from __future__ import annotations

import datetime as dt
import inspect
from pathlib import Path

import pandas as pd
import pytest

import hqai_ml.origin_journey as public_api
from hqai_ml.origin_journey import cohorts as cohort_module
from hqai_ml.origin_journey.cohorts import build_origin_cohorts
from hqai_ml.origin_journey.config import load_origin_journey_config
from hqai_ml.origin_journey.evaluation import build_evaluation_labels
from hqai_ml.origin_journey.hashing import canonical_frame_sha256
from hqai_ml.origin_journey.time_grid import build_time_grid

CONFIG_PATH = Path(__file__).parents[1] / "configs" / "origin_journey.yaml"


def _source() -> pd.DataFrame:
    rows = [
        # known admission before origin
        (1, "75.A.01.1", "75", "A", "75", "01", "I10", "city", "planned", "state", "2025-03-01", "2025-03-10", None),
        # future admission: censored for training and waiting for scoring
        (2, "75.A.01.2", "75", "A", "75", "01", "I11", "city", "planned", "state", "2025-03-02", "2025-03-20", None),
        # future refusal: censored for training and waiting for scoring
        (3, "75.A.01.3", "75", "A", "75", "01", "I12", "village", "planned", "state", "2025-03-17", None, "2025-04-01"),
        # unresolved at the evaluation cutoff
        (4, "75.B.02.1", "75", "B", "75", "02", "J10", "city", "urgent", "state", "2025-01-01", None, None),
        # resolved on origin: known by end of day, not in scoring
        (5, "75.B.02.2", "75", "B", "75", "02", "J11", "city", "urgent", "state", "2025-03-01", None, "2025-03-17"),
        # registered after origin: in neither model-facing cohort
        (6, "75.B.02.3", "75", "B", "75", "02", "J12", "city", "urgent", "state", "2025-03-18", None, None),
        # product-excluded day hospital
        (7, "75.C.DH.1", "75", "C", "75", "DH", "K10", "city", "planned", "state", "2025-02-01", None, None),
        # conflicting known events are invalid labels, not waiting referrals
        (
            8,
            "75.C.03.1",
            "75",
            "C",
            "75",
            "03",
            "K11",
            "city",
            "planned",
            "state",
            "2025-02-01",
            "2025-03-10",
            "2025-03-11",
        ),
    ]
    return pd.DataFrame(
        rows,
        columns=[
            "referral_id",
            "hospitalization_code",
            "region_code",
            "org_code",
            "hospital_region_code",
            "profile_code",
            "icd10_code",
            "territorial_type",
            "referral_purpose",
            "finance_source",
            "registration_date",
            "hospitalization_date",
            "refusal_date",
        ],
    )


@pytest.fixture
def config():
    return load_origin_journey_config(CONFIG_PATH)


def test_future_outcomes_are_indistinguishable_from_open_at_origin(config):
    cohorts = build_origin_cohorts(_source(), config)
    training = cohorts.training.set_index("referral_id")

    assert list(training.index) == [1, 2, 3, 4, 5, 8]
    assert training.loc[1, "event_type_at_origin"] == "hospitalized"
    assert training.loc[5, "event_type_at_origin"] == "refused"
    for referral_id in (2, 3, 4):
        assert training.loc[referral_id, "event_type_at_origin"] == "censored"
        assert training.loc[referral_id, "administratively_censored"]
        expected = (config.origin - training.loc[referral_id, "registration_date"]).days
        assert training.loc[referral_id, "observed_duration_days"] == expected
    assert training.loc[8, "event_type_at_origin"] == "conflict"
    assert not training.loc[8, "label_eligible"]
    assert not training.loc[8, "administratively_censored"]

    forbidden = {
        "hospitalization_date",
        "refusal_date",
        "resolution_date",
        "outcome",
        "wait_days",
        "evaluation_event_type",
        "evaluation_event_date",
    }
    assert forbidden.isdisjoint(training.columns)


def test_scoring_is_end_of_origin_waiting_list_and_excludes_day_hospital(config):
    scoring = build_origin_cohorts(_source(), config).scoring.set_index("referral_id")

    assert list(scoring.index) == [2, 3, 4]
    assert (pd.to_datetime(scoring["registration_date"]).dt.date <= config.origin).all()
    assert not scoring["profile_code"].isin(config.excluded_profile_codes).any()
    assert scoring.loc[2, "days_waited_at_origin"] == 15
    assert scoring.loc[3, "days_waited_at_origin"] == 0
    assert scoring.loc[4, "days_waited_at_origin"] == 75


def test_evaluation_labels_are_separate_and_training_cannot_reach_them(config):
    source = _source()
    cohorts = build_origin_cohorts(source, config)

    assert "build_evaluation_labels" not in public_api.__all__
    assert not hasattr(public_api, "build_evaluation_labels")
    assert "origin_journey.evaluation" not in inspect.getsource(cohort_module)
    assert set(vars(cohorts)) == {"training", "scoring", "audit"}

    labels = build_evaluation_labels(source, cohorts.scoring["referral_id"], config).set_index("referral_id")
    assert labels.loc[2, "evaluation_event_type"] == "hospitalized"
    assert labels.loc[3, "evaluation_event_type"] == "refused"
    assert labels.loc[4, "evaluation_event_type"] == "censored"
    assert labels.loc[2, "evaluation_event_date"] == dt.date(2025, 3, 20)


def test_time_grid_is_daily_through_30_then_coarser(config):
    intervals = build_time_grid(config)

    assert [(item.start_day, item.end_day) for item in intervals[:3]] == [(0, 1), (1, 2), (2, 3)]
    assert [(item.start_day, item.end_day) for item in intervals[29:32]] == [(29, 30), (30, 45), (45, 60)]
    assert all(item.is_daily for item in intervals[:30])
    assert not any(item.is_daily for item in intervals[30:])
    assert intervals[-1].end_day == 500


def test_frame_hash_is_stable_across_input_order_and_index(config):
    scoring = build_origin_cohorts(_source(), config).scoring
    shuffled = scoring.sample(frac=1, random_state=9).set_index(pd.Index([7, 8, 9]))

    assert canonical_frame_sha256(scoring) == canonical_frame_sha256(shuffled)
