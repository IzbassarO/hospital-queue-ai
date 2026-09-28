"""Offline contract of the per-referral estimate publication: small synthetic rows, no database, no artifacts.

The five properties this file exists to protect:
  1. probabilities are coherent — admission rises with the horizon and admission plus refusal never exceeds one;
  2. abstention is a named reason, never a missing window and never a zero;
  3. the published attention flag is exactly the published threshold, and a collapsed 30-day distribution is
     flagged rather than printed as a confident 0% or 100%;
  4. the tournament a reader sees is the tournament that was decided — one baseline, and the fallback only when
     nothing was accepted;
  5. the publication identity covers the content and nothing else, so a re-generated bundle republishes cleanly.
"""

from __future__ import annotations

import copy
import importlib.util
import json
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError as PydanticValidationError

from app.schemas.referral_estimates import ReferralEstimateRow, ReferralEstimatesBundle
from app.services.common import ValidationError
from app.services.referral_estimates import identity_of, parse_bundle

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("referral_estimates_offline", ROOT / "tools/referral_estimates_bundle.py")
assert SPEC and SPEC.loader
builder = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = builder
SPEC.loader.exec_module(builder)

COMMIT = "0" * 40
SHA = "a" * 64


def estimate_row(
    referral_id: int = 1,
    *,
    admitted: tuple[float, float, float] = (0.2, 0.4, 0.6),
    refused: float = 0.1,
    tier: str = "hospital_profile",
    rows: int = 120,
    window: tuple[float, float] | None = (2.0, 18.0),
) -> dict:
    return {
        "referral_id": referral_id,
        "org_code": "H001",
        "profile_code": "021",
        "estimate_tier": tier,
        "similar_training_rows": rows,
        "admitted_7d": admitted[0],
        "admitted_14d": admitted[1],
        "admitted_30d": admitted[2],
        "refused_30d": refused,
        "window_lower_days": None if window is None else window[0],
        "window_upper_days": None if window is None else window[1],
        "abstention_reason": None if window else builder.NO_WINDOW,
        "refusal_attention": refused >= 0.3,
        "degenerate_30d": builder.degenerate(admitted[2], refused),
    }


def bundle_payload(rows: list[dict], **overrides) -> dict:
    tiers: dict[str, int] = {}
    abstentions: dict[str, int] = {}
    for row in rows:
        tiers[row["estimate_tier"]] = tiers.get(row["estimate_tier"], 0) + 1
        if row["abstention_reason"]:
            abstentions[row["abstention_reason"]] = abstentions.get(row["abstention_reason"], 0) + 1
    payload = {
        "schema_version": "referral_estimates_v1",
        "contract_version": "1.0.0",
        "publication_id": "test-referral-estimates",
        "publication_identity_sha256": "0" * 64,
        "source_code_commit": COMMIT,
        "origin": "2025-03-17",
        "outcome_cutoff": "2026-05-13T00:00:00",
        "horizons": [7, 14, 30],
        "admission_window_coverage": 0.8,
        "source_run": {
            "run_id": "b2-origin-2025-03-17-v2",
            "artifact_identity_sha256": SHA,
            "scientific_identity_sha256": SHA,
            "training_sha256": SHA,
            "scoring_sha256": SHA,
            "seed": 42,
            "library_versions": {"python": "3.14.7"},
        },
        "selection": {
            "metric": "mean_admission_and_refusal_brier_at_7_14_30",
            "decision_rule": "fixed before the run",
            "tolerance": 0.005,
            "require_strict_overall_improvement": True,
            "selected_model": "aalen_johansen",
            "fallback_used": True,
            "candidates": [
                {
                    "model_key": "aalen_johansen",
                    "role": "baseline",
                    "accepted": None,
                    "overall_mean_brier": 0.0979,
                    "overall_delta": None,
                    "worst_bucket_delta": None,
                    "strict_overall_improvement": None,
                    "within_bucket_tolerance": None,
                    "brier_by_horizon": {"7": 0.08, "14": 0.1, "30": 0.11},
                },
                {
                    "model_key": "xgboost_aft",
                    "role": "candidate",
                    "accepted": False,
                    "overall_mean_brier": 0.1045,
                    "overall_delta": 0.0066,
                    "worst_bucket_delta": 0.0233,
                    "strict_overall_improvement": False,
                    "within_bucket_tolerance": False,
                    "brier_by_horizon": {"7": 0.09, "14": 0.11, "30": 0.12},
                },
            ],
        },
        "calibration": {
            "disclosure": "HINDSIGHT_NOT_AVAILABLE_AT_ORIGIN",
            "model_key": "aalen_johansen",
            "rows": len(rows),
            "bins": [
                {
                    "horizon_days": 14,
                    "outcome": "hospitalized",
                    "bin_index": 0,
                    "n": len(rows),
                    "mean_predicted": 0.4,
                    "observed_rate": 0.3,
                    "probability_min": 0.0,
                    "probability_max": 1.0,
                }
            ],
        },
        "estimate_tiers": tiers,
        "abstention_counts": abstentions,
        "degeneracy": builder.degeneracy_block(rows),
        "attention": {
            "metric": "refused_30d",
            "quantile": 0.9,
            "threshold": 0.3,
            "definition": "upper decile of the cohort",
            "intended_use": "administrative follow-up only",
            "flagged_count": sum(row["refusal_attention"] for row in rows),
        },
        "generated_at": "2026-09-28T00:00:00+00:00",
        "limitations": ["origin-time estimates"],
        "referrals": rows,
    }
    payload.update(overrides)
    return payload


def validated(payload: dict) -> ReferralEstimatesBundle:
    bundle = ReferralEstimatesBundle.model_validate(payload)
    body = bundle.model_dump(mode="json")
    body["publication_identity_sha256"] = identity_of(bundle)
    return ReferralEstimatesBundle.model_validate(body)


# ------------------------------------------------------------------------------- coherent probabilities


def test_admission_probability_may_not_fall_as_the_horizon_grows() -> None:
    with pytest.raises(PydanticValidationError):
        ReferralEstimateRow.model_validate(estimate_row(admitted=(0.5, 0.4, 0.6)))


def test_admission_and_refusal_may_not_exceed_one() -> None:
    with pytest.raises(PydanticValidationError):
        ReferralEstimateRow.model_validate(estimate_row(admitted=(0.2, 0.5, 0.8), refused=0.4))


def test_the_published_rounding_is_tolerated_but_real_incoherence_is_not() -> None:
    """Six decimals of rounding may push the sum a hair over one; a hundredth over is a contradiction."""
    ReferralEstimateRow.model_validate(estimate_row(admitted=(0.2, 0.5, 0.9), refused=0.1000005))
    with pytest.raises(PydanticValidationError):
        ReferralEstimateRow.model_validate(estimate_row(admitted=(0.2, 0.5, 0.9), refused=0.11))


# ------------------------------------------------------------------------------- abstention


def test_a_row_carries_either_a_window_or_a_reason_never_both_and_never_neither() -> None:
    row = estimate_row(window=None)
    ReferralEstimateRow.model_validate(row)
    with pytest.raises(PydanticValidationError):
        ReferralEstimateRow.model_validate({**row, "window_lower_days": 1.0, "window_upper_days": 4.0})
    with pytest.raises(PydanticValidationError):
        ReferralEstimateRow.model_validate({**estimate_row(), "abstention_reason": builder.NO_WINDOW})


def test_a_missing_window_is_not_silently_an_empty_pair() -> None:
    with pytest.raises(PydanticValidationError):
        ReferralEstimateRow.model_validate({**estimate_row(), "window_upper_days": None})


def test_the_abstention_counts_must_match_the_rows() -> None:
    payload = bundle_payload([estimate_row(1, window=None)])
    payload["abstention_counts"] = {}
    with pytest.raises(PydanticValidationError, match="abstention_counts"):
        ReferralEstimatesBundle.model_validate(payload)


# ------------------------------------------------------------------------------- the follow-up threshold


def test_the_attention_flag_is_exactly_the_published_threshold() -> None:
    payload = bundle_payload([estimate_row(1, refused=0.31), estimate_row(2, refused=0.1)])
    validated(payload)
    lying = copy.deepcopy(payload)
    lying["referrals"][1]["refusal_attention"] = True
    lying["attention"]["flagged_count"] = 2
    with pytest.raises(PydanticValidationError, match="contradicts the threshold"):
        ReferralEstimatesBundle.model_validate(lying)


def test_the_threshold_carries_the_sentence_that_bounds_its_use() -> None:
    bundle = validated(bundle_payload([estimate_row()]))
    assert "administrative" in bundle.attention.intended_use


# ------------------------------------------------------------------------------- degeneracy


def test_a_collapsed_thirty_day_distribution_is_flagged() -> None:
    """All mass on one outcome is thin comparable history, and the row has to say so."""
    assert builder.degenerate(0.0, 0.0) is True  # everything on "still waiting"
    assert builder.degenerate(1.0, 0.0) is True
    assert builder.degenerate(0.0, 1.0) is True
    assert builder.degenerate(0.55, 0.12) is False


def test_the_flag_may_not_disagree_with_the_published_probabilities() -> None:
    with pytest.raises(PydanticValidationError, match="degenerate_30d contradicts"):
        ReferralEstimateRow.model_validate({**estimate_row(), "degenerate_30d": True})
    with pytest.raises(PydanticValidationError, match="degenerate_30d contradicts"):
        ReferralEstimateRow.model_validate(
            {**estimate_row(admitted=(0.0, 0.0, 0.0), refused=0.0, window=None), "degenerate_30d": False}
        )


def test_the_published_count_splits_by_the_outcome_the_mass_collapsed_onto() -> None:
    rows = [
        estimate_row(1, admitted=(0.0, 0.0, 0.0), refused=0.0, window=None),
        estimate_row(2, admitted=(1.0, 1.0, 1.0), refused=0.0),
        estimate_row(3, admitted=(0.0, 0.0, 0.0), refused=1.0, tier="profile", rows=0, window=None),
        estimate_row(4, admitted=(0.2, 0.4, 0.6), refused=0.1),
    ]
    bundle = validated(bundle_payload(rows))
    assert bundle.degeneracy.count == 3
    assert bundle.degeneracy.by_outcome == {"still_waiting": 1, "admitted": 1, "refused": 1}
    assert "не уверенности" in bundle.degeneracy.definition or bundle.degeneracy.definition.strip()


def test_the_degeneracy_count_must_match_the_rows() -> None:
    payload = bundle_payload([estimate_row(1, admitted=(0.0, 0.0, 0.0), refused=0.0, window=None)])
    payload["degeneracy"]["count"] = 0
    with pytest.raises(PydanticValidationError, match="degeneracy.count"):
        ReferralEstimatesBundle.model_validate(payload)


# ------------------------------------------------------------------------------- the tournament


def test_the_fallback_may_not_be_claimed_beside_an_accepted_candidate() -> None:
    payload = bundle_payload([estimate_row()])
    payload["selection"]["candidates"][1]["accepted"] = True
    with pytest.raises(PydanticValidationError, match="fallback_used"):
        ReferralEstimatesBundle.model_validate(payload)


def test_a_baseline_is_neither_accepted_nor_rejected() -> None:
    payload = bundle_payload([estimate_row()])
    payload["selection"]["candidates"][0]["accepted"] = False
    with pytest.raises(PydanticValidationError):
        ReferralEstimatesBundle.model_validate(payload)


def test_the_calibration_must_describe_the_model_that_serves() -> None:
    payload = bundle_payload([estimate_row()])
    payload["calibration"]["model_key"] = "xgboost_aft"
    with pytest.raises(PydanticValidationError, match="calibration must describe"):
        ReferralEstimatesBundle.model_validate(payload)


def test_a_hospital_level_tier_needs_hospital_history() -> None:
    payload = bundle_payload([estimate_row(rows=0)])
    with pytest.raises(PydanticValidationError, match="hospital history"):
        ReferralEstimatesBundle.model_validate(payload)


# ------------------------------------------------------------------------------- identity


def test_identity_covers_the_content_and_ignores_the_generation_time() -> None:
    bundle = validated(bundle_payload([estimate_row(1), estimate_row(2, refused=0.4)]))
    raw = json.dumps(bundle.model_dump(mode="json"), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    parsed = parse_bundle(raw.encode())
    assert parsed.bundle.publication_identity_sha256 == bundle.publication_identity_sha256

    later = bundle.model_dump(mode="json")
    later["generated_at"] = "2027-01-01T00:00:00+00:00"
    again = json.dumps(later, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    assert parse_bundle(again.encode()).bundle.publication_identity_sha256 == bundle.publication_identity_sha256


def test_a_bundle_whose_identity_does_not_match_its_content_is_refused() -> None:
    bundle = validated(bundle_payload([estimate_row()]))
    tampered = bundle.model_dump(mode="json")
    tampered["referrals"][0]["similar_training_rows"] = 999
    raw = json.dumps(tampered, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    with pytest.raises(ValidationError, match="does not match canonical content"):
        parse_bundle(raw.encode())


# ------------------------------------------------------------------------------- the builder's own mapping


def test_the_builder_renames_every_hierarchy_level_to_a_product_tier() -> None:
    assert set(builder.TIERS.values()) == {"hospital_profile", "region_profile", "profile", "national"}


def test_the_threshold_is_the_upper_decile_of_the_cohort() -> None:
    rows = [estimate_row(i + 1, refused=i / 100) for i in range(100)]
    attention = builder.apply_attention(rows)
    assert attention["quantile"] == 0.9
    assert attention["threshold"] == pytest.approx(0.9, abs=0.01)
    assert attention["flagged_count"] == sum(row["refusal_attention"] for row in rows)
    assert 1 <= attention["flagged_count"] <= 11
