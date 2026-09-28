from __future__ import annotations

import gzip
import inspect
from pathlib import Path

import pandas as pd

from hqai_ml.origin_journey import ghost_queue as ghost_queue_module
from hqai_ml.origin_journey.baseline import HierarchicalAJ
from hqai_ml.origin_journey.config import load_origin_journey_config
from hqai_ml.origin_journey.ghost_queue import (
    FORBIDDEN_GHOST_KEYS,
    build_ghost_queue_bundle,
    validate_ghost_queue_bundle,
    write_ghost_queue_bundle,
)

CONFIG_PATH = Path(__file__).parents[1] / "configs" / "origin_journey.yaml"


def _training() -> pd.DataFrame:
    rows = []
    for index in range(100):
        rows.append(
            {
                "referral_id": index,
                "org_code": "A",
                "hospital_region_code": "R",
                "profile_code": "P",
                "observed_duration_days": float(index % 20 + 1),
                "event_type_at_origin": "refused",
                "label_eligible": True,
            }
        )
    return pd.DataFrame(rows)


def _scoring() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "referral_id": [103, 101, 102],
            "org_code": ["A", "A", "A"],
            "hospital_region_code": ["R", "R", "R"],
            "profile_code": ["P", "P", "P"],
            "days_waited_at_origin": [60, 30, 29],
        }
    )


def _all_keys(value) -> set[str]:
    if isinstance(value, dict):
        return set(value) | set().union(*(_all_keys(item) for item in value.values()), set())
    if isinstance(value, list):
        return set().union(*(_all_keys(item) for item in value), set())
    return set()


def test_worklist_score_and_history_warning_are_origin_only():
    config = load_origin_journey_config(CONFIG_PATH)
    model = HierarchicalAJ.fit(_training(), config)
    bundle = build_ghost_queue_bundle(_scoring(), model, config)
    rows = {row["referral_id"]: row for row in bundle["referrals"]}

    assert rows[103]["verification_rank"] == 1
    assert rows[101]["verification_rank"] == 2
    assert rows[102]["verification_rank"] == 3
    assert rows[101]["history_quality_warning"] is True
    assert rows[101]["history_quality_reason_code"] == "insufficient_and_degenerate_comparable_history"
    assert rows[101]["comparable_training_at_risk_rows"] == 0
    assert "origin_journey.evaluation" not in inspect.getsource(ghost_queue_module)
    assert FORBIDDEN_GHOST_KEYS.isdisjoint(_all_keys(bundle))


def test_flags_and_gzip_are_deterministic(tmp_path):
    config = load_origin_journey_config(CONFIG_PATH)
    model = HierarchicalAJ.fit(_training(), config)
    first = build_ghost_queue_bundle(_scoring(), model, config)
    second = build_ghost_queue_bundle(_scoring().sample(frac=1, random_state=7), model, config)

    assert first == second
    first_path = tmp_path / "first.json.gz"
    second_path = tmp_path / "second.json.gz"
    write_ghost_queue_bundle(first_path, first)
    write_ghost_queue_bundle(second_path, second)
    assert first_path.read_bytes() == second_path.read_bytes()
    assert gzip.decompress(first_path.read_bytes()).endswith(b"\n")


def test_aggregates_sum_to_formal_queue_and_probabilities_are_bounded():
    config = load_origin_journey_config(CONFIG_PATH)
    bundle = build_ghost_queue_bundle(_scoring(), HierarchicalAJ.fit(_training(), config), config)
    validate_ghost_queue_bundle(bundle)

    formal = bundle["headline"]["formal_queue_count"]
    warning = bundle["headline"]["history_quality_warning_count"]
    for groups in bundle["aggregates"].values():
        assert sum(group["formal_queue_count"] for group in groups) == formal
        assert sum(group["history_quality_warning_count"] for group in groups) == warning
    for row in bundle["referrals"]:
        assert 0 <= row["probability_admitted_within_30d"] <= 1
        assert 0 <= row["probability_admitted_within_90d"] <= 1
        assert 0 <= row["probability_ever_admitted_within_observable_curve"] <= 1
        assert 0 <= row["verification_priority_score"] <= 1
    assert sorted(row["verification_rank"] for row in bundle["referrals"]) == [1, 2, 3]
