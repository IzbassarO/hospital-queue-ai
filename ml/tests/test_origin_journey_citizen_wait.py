from __future__ import annotations

import gzip
import inspect
from pathlib import Path

import pandas as pd

from hqai_ml.origin_journey import citizen_wait as citizen_wait_module
from hqai_ml.origin_journey.baseline import HierarchicalAJ
from hqai_ml.origin_journey.citizen_wait import (
    FORBIDDEN_PUBLIC_KEYS,
    build_citizen_wait_bundle,
    validate_citizen_wait_bundle,
    write_citizen_wait_bundle,
)
from hqai_ml.origin_journey.config import load_origin_journey_config

CONFIG_PATH = Path(__file__).parents[1] / "configs" / "origin_journey.yaml"


def _training() -> pd.DataFrame:
    rows = []
    referral_id = 1
    specifications = [("A", "R", "P", 49), ("B", "R", "P", 11), ("C", "S", "Q", 50)]
    for org, region, profile, count in specifications:
        for index in range(count):
            rows.append(
                {
                    "referral_id": referral_id,
                    "org_code": org,
                    "hospital_region_code": region,
                    "profile_code": profile,
                    "observed_duration_days": float(index % 10 + 1),
                    "event_type_at_origin": "refused" if index % 10 == 0 else "hospitalized",
                    "label_eligible": True,
                }
            )
            referral_id += 1
    return pd.DataFrame(rows)


def _all_keys(value) -> set[str]:
    if isinstance(value, dict):
        keys = set(value)
        for item in value.values():
            keys.update(_all_keys(item))
        return keys
    if isinstance(value, list):
        keys = set()
        for item in value:
            keys.update(_all_keys(item))
        return keys
    return set()


def test_privacy_suppression_uses_region_fallback_below_fifty():
    config = load_origin_journey_config(CONFIG_PATH)
    training = _training()
    model = HierarchicalAJ.fit(training, config)

    bundle = build_citizen_wait_bundle(training, model, config)
    cells = {(row["org_code"], row["profile_code"]): row for row in bundle["cells"]}

    assert config.citizen_wait.minimum_hospital_training_rows == 50
    assert cells[("A", "P")]["hospital_estimate_suppressed"] is True
    assert cells[("A", "P")]["estimate_tier"] == "region_profile"
    assert cells[("B", "P")]["hospital_estimate_suppressed"] is True
    assert cells[("C", "Q")]["hospital_estimate_suppressed"] is False
    assert cells[("C", "Q")]["estimate_tier"] == "hospital_profile"
    assert "hospital_training_rows" not in cells[("A", "P")]


def test_public_quantiles_are_monotone_and_probabilities_are_bounded():
    config = load_origin_journey_config(CONFIG_PATH)
    training = _training()
    bundle = build_citizen_wait_bundle(training, HierarchicalAJ.fit(training, config), config)

    validate_citizen_wait_bundle(bundle)
    for cell in bundle["cells"]:
        median = cell["median_days_to_admission"]
        p80 = cell["admitted_80pct_by_day"]
        assert median is None or p80 is None or median <= p80
        assert 0 <= cell["refusal_probability_30d"] <= 1


def test_admission_quantiles_are_conditional_on_eventual_admission():
    config = load_origin_journey_config(CONFIG_PATH)
    rows = []
    for index in range(100):
        rows.append(
            {
                "referral_id": index,
                "org_code": "A",
                "hospital_region_code": "R",
                "profile_code": "P",
                "observed_duration_days": float(index + 1),
                "event_type_at_origin": "hospitalized" if index < 20 else "refused",
                "label_eligible": True,
            }
        )
    training = pd.DataFrame(rows)
    bundle = build_citizen_wait_bundle(training, HierarchicalAJ.fit(training, config), config)
    cell = bundle["cells"][0]

    # The raw admission CIF never reaches 0.5, but its admission-conditional distribution does.
    assert cell["median_days_to_admission"] is not None
    assert cell["admitted_80pct_by_day"] is not None
    assert bundle["estimands"]["admission_time_conditioning"].startswith("conditional_on_eventual")


def test_bundle_has_no_per_referral_or_hindsight_fields_and_gzip_is_deterministic(tmp_path):
    config = load_origin_journey_config(CONFIG_PATH)
    training = _training()
    bundle = build_citizen_wait_bundle(training, HierarchicalAJ.fit(training, config), config)

    assert FORBIDDEN_PUBLIC_KEYS.isdisjoint(_all_keys(bundle))
    assert len(bundle["cells"]) == 3
    first = tmp_path / "first.json.gz"
    second = tmp_path / "second.json.gz"
    write_citizen_wait_bundle(first, bundle)
    write_citizen_wait_bundle(second, bundle)

    assert first.read_bytes() == second.read_bytes()
    assert gzip.decompress(first.read_bytes()).endswith(b"\n")
    assert "origin_journey.evaluation" not in inspect.getsource(citizen_wait_module)
