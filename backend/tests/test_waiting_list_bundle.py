"""Offline waiting-list export controls: small synthetic rows, no database and no artifact dependency.

The four properties this file exists to protect:
  1. the cohort is exactly "registered by the origin and unresolved at the end of the origin day";
  2. day-hospital profiles are excluded;
  3. no row registered after the origin can reach the publication;
  4. the hindsight field stays hindsight — marked on every row, and never mirrored into an origin-time field.
"""

from __future__ import annotations

import datetime as dt
import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import ValidationError as PydanticValidationError

from app.schemas.waiting_list import (
    HINDSIGHT_DISCLOSURE,
    ObservedAfterOrigin,
    SupportThresholds,
    WaitingListBundle,
)
from app.services.common import ValidationError
from app.services.waiting_list import identity_of, parse_bundle

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("waiting_list_offline", ROOT / "tools/waiting_list_bundle.py")
assert SPEC and SPEC.loader
builder = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = builder
SPEC.loader.exec_module(builder)

ORIGIN = dt.date(2025, 3, 17)
COMMIT = "0" * 40


def source_row(
    referral_id: int = 1,
    *,
    registration_date: dt.date = dt.date(2025, 1, 10),
    resolution_date: dt.date | None = None,
    outcome: str = "open",
    profile_code: str = "021",
    org_code: str = "H001",
    is_dup_code: bool = False,
) -> SimpleNamespace:
    return SimpleNamespace(
        referral_id=referral_id,
        hospitalization_code=f"61.{org_code}.{profile_code}.{referral_id}",
        is_dup_code=is_dup_code,
        org_code=org_code,
        hospital_region_code="61",
        patient_region_code="61",
        profile_code=profile_code,
        registration_date=registration_date,
        resolution_date=resolution_date,
        outcome=outcome,
    )


def bundle_payload(rows: list[SimpleNamespace]) -> dict:
    thresholds = SupportThresholds(sufficient_min=50, limited_min=20)
    referrals = builder.referral_rows(rows, ORIGIN)
    payload = {
        "schema_version": "waiting_list_v1",
        "contract_version": "1.0.0",
        "publication_id": "test-waiting-list",
        "publication_identity_sha256": "0" * 64,
        "source_code_commit": COMMIT,
        "origin": ORIGIN.isoformat(),
        "outcome_cutoff": "2026-05-13T00:00:00",
        "observed_through": "2026-05-12",
        "cohort": {
            "waiting_rule": "registration_date <= origin AND (resolution_date IS NULL OR resolution_date > origin)",
            "excluded_profile_codes": ["DH"],
            "excluded_profile_reason": "day hospital",
            "registration_floor": "2025-01-01",
            "lower_bound_note": "source starts at the floor",
        },
        "support_thresholds": thresholds.model_dump(mode="json"),
        "carries_model_output": False,
        "generated_at": "2026-09-27T00:00:00+00:00",
        "limitations": ["measured data, not a forecast"],
        "hospitals": builder.hospital_rows(referrals, thresholds),
        "referrals": referrals,
    }
    bundle = WaitingListBundle.model_validate(payload)
    payload = bundle.model_dump(mode="json")
    payload["publication_identity_sha256"] = identity_of(bundle)
    return payload


# ------------------------------------------------------------------------------ 1. cohort at the origin


def test_cohort_sql_states_the_origin_rule_and_excludes_day_hospital() -> None:
    sql = " ".join(builder.COHORT_SQL.split())
    assert "registration_date <= :origin" in sql
    assert "(resolution_date IS NULL OR resolution_date > :origin)" in sql
    assert "profile_code <> ALL(:excluded)" in sql
    assert builder.EXCLUDED_PROFILE_CODES == ("DH",)


def test_days_waited_is_measured_from_the_origin_not_from_the_outcome() -> None:
    row = source_row(
        registration_date=dt.date(2025, 1, 10), resolution_date=dt.date(2025, 4, 1), outcome="hospitalized"
    )
    (published,) = builder.referral_rows([row], ORIGIN)
    assert published["days_waited_at_origin"] == (ORIGIN - dt.date(2025, 1, 10)).days == 66
    assert published["observed_after_origin"]["days_from_origin"] == 15


def test_a_referral_registered_on_the_origin_day_waits_zero_days() -> None:
    (published,) = builder.referral_rows([source_row(registration_date=ORIGIN)], ORIGIN)
    assert published["days_waited_at_origin"] == 0
    assert WaitingListBundle.model_validate(bundle_payload([source_row(registration_date=ORIGIN)]))


# ------------------------------------------------------------------------------ 2. day-hospital exclusion


def test_a_day_hospital_row_is_rejected_by_the_contract() -> None:
    payload = bundle_payload([source_row(), source_row(2)])
    payload["referrals"][1]["profile_code"] = "DH"
    with pytest.raises(PydanticValidationError, match="excluded profile"):
        WaitingListBundle.model_validate(payload)


# ------------------------------------------------------------------------------ 3. nothing after the origin


def test_a_referral_registered_after_the_origin_is_rejected() -> None:
    payload = bundle_payload([source_row()])
    payload["referrals"][0]["registration_date"] = "2025-03-18"
    payload["referrals"][0]["days_waited_at_origin"] = -1
    with pytest.raises(PydanticValidationError):
        WaitingListBundle.model_validate(payload)


def test_an_outcome_on_or_before_the_origin_is_rejected() -> None:
    """A referral that already left the queue at the origin was never waiting."""
    payload = bundle_payload([source_row(resolution_date=dt.date(2025, 4, 1), outcome="hospitalized")])
    payload["referrals"][0]["observed_after_origin"]["event_date"] = ORIGIN.isoformat()
    payload["referrals"][0]["observed_after_origin"]["days_from_origin"] = 0
    with pytest.raises(PydanticValidationError):
        WaitingListBundle.model_validate(payload)


def test_an_inconsistent_days_waited_is_rejected() -> None:
    payload = bundle_payload([source_row()])
    payload["referrals"][0]["days_waited_at_origin"] += 1
    with pytest.raises(PydanticValidationError, match="inconsistent days_waited_at_origin"):
        WaitingListBundle.model_validate(payload)


# ------------------------------------------------------------------------------ 4. hindsight stays hindsight


def test_every_row_carries_the_hindsight_disclosure() -> None:
    rows = [
        source_row(1),
        source_row(2, resolution_date=dt.date(2025, 4, 1), outcome="hospitalized"),
        source_row(3, resolution_date=dt.date(2025, 5, 2), outcome="refused"),
    ]
    published = builder.referral_rows(rows, ORIGIN)
    assert {row["observed_after_origin"]["disclosure"] for row in published} == {HINDSIGHT_DISCLOSURE}
    assert [row["observed_after_origin"]["status"] for row in published] == [
        "STILL_WAITING_AT_CUTOFF",
        "ADMITTED",
        "REFUSED",
    ]


def test_the_disclosure_cannot_be_weakened() -> None:
    with pytest.raises(PydanticValidationError):
        ObservedAfterOrigin(disclosure="AVAILABLE_AT_ORIGIN", status="ADMITTED")


def test_an_unresolved_row_must_not_carry_an_event_date() -> None:
    with pytest.raises(PydanticValidationError, match="must not carry an event date"):
        ObservedAfterOrigin(
            disclosure=HINDSIGHT_DISCLOSURE,
            status="STILL_WAITING_AT_CUTOFF",
            event_date=dt.date(2025, 4, 1),
            days_from_origin=15,
        )


def test_a_resolved_row_must_carry_both_date_and_distance() -> None:
    with pytest.raises(PydanticValidationError, match="needs both event_date and days_from_origin"):
        ObservedAfterOrigin(disclosure=HINDSIGHT_DISCLOSURE, status="ADMITTED", event_date=dt.date(2025, 4, 1))


def test_hindsight_never_leaks_into_an_origin_time_field() -> None:
    """Only `observed_after_origin` may mention the outcome: no sibling key repeats it at row level."""
    rows = [source_row(1, resolution_date=dt.date(2025, 4, 1), outcome="hospitalized")]
    (published,) = builder.referral_rows(rows, ORIGIN)
    origin_time_keys = set(published) - {"observed_after_origin"}
    forbidden = {"outcome", "resolution_date", "hospitalization_date", "refusal_date", "wait_days", "status"}
    assert not origin_time_keys & forbidden
    serialized = json.dumps({key: published[key] for key in origin_time_keys}, ensure_ascii=False)
    assert "2025-04-01" not in serialized
    assert "ADMITTED" not in serialized


def test_the_publication_declares_that_it_carries_no_model_output() -> None:
    payload = bundle_payload([source_row()])
    assert payload["carries_model_output"] is False
    payload["carries_model_output"] = True
    with pytest.raises(PydanticValidationError):
        WaitingListBundle.model_validate(payload)


def _keys(value: object) -> set[str]:
    if isinstance(value, dict):
        return set(value) | {key for item in value.values() for key in _keys(item)}
    if isinstance(value, list):
        return {key for item in value for key in _keys(item)}
    return set()


def test_no_model_bearing_key_is_present_anywhere_in_the_bundle() -> None:
    """Prose may say "not a forecast"; a *field* named after a model value must never appear."""
    payload = bundle_payload([source_row(), source_row(2, org_code="H002")])
    keys = _keys(payload)
    forbidden = ("pred", "probability", "severity", "forecast", "score", "risk", "calibration", "model_version")
    offenders = {key for key in keys if any(token in key for token in forbidden)}
    assert not offenders, f"model-bearing field(s) in a measured waiting list: {sorted(offenders)}"


# ------------------------------------------------------------------------------ aggregate and identity


def test_hospital_aggregate_must_agree_with_its_referrals() -> None:
    payload = bundle_payload([source_row(1), source_row(2), source_row(3, org_code="H002")])
    payload["hospitals"][0]["waiting_count"] += 1
    with pytest.raises(PydanticValidationError, match="waiting_count does not match"):
        WaitingListBundle.model_validate(payload)


def test_support_class_must_follow_the_published_thresholds() -> None:
    payload = bundle_payload([source_row(i) for i in range(1, 4)])
    assert payload["hospitals"][0]["support_class"] == "SPARSE"
    payload["hospitals"][0]["support_class"] = "SUFFICIENT"
    with pytest.raises(PydanticValidationError, match="contradicts the published thresholds"):
        WaitingListBundle.model_validate(payload)


def test_support_classification_at_the_threshold_boundaries() -> None:
    thresholds = SupportThresholds(sufficient_min=50, limited_min=20)
    assert thresholds.classify(50) == "SUFFICIENT"
    assert thresholds.classify(49) == "LIMITED"
    assert thresholds.classify(20) == "LIMITED"
    assert thresholds.classify(19) == "SPARSE"


def test_identity_covers_the_content_but_not_the_generation_time() -> None:
    payload = bundle_payload([source_row()])
    parsed = parse_bundle(json.dumps(payload, ensure_ascii=False).encode())
    later = dict(payload, generated_at="2027-01-01T00:00:00+00:00")
    assert parse_bundle(json.dumps(later, ensure_ascii=False).encode()).bundle.publication_identity_sha256 == (
        parsed.bundle.publication_identity_sha256
    )
    changed = dict(payload)
    changed["limitations"] = ["something else"]
    with pytest.raises(ValidationError, match="does not match canonical content"):
        parse_bundle(json.dumps(changed, ensure_ascii=False).encode())


def test_duplicate_referral_ids_are_rejected() -> None:
    payload = bundle_payload([source_row(1), source_row(2)])
    payload["referrals"][1]["referral_id"] = payload["referrals"][0]["referral_id"]
    with pytest.raises(PydanticValidationError, match="duplicate referral_id"):
        WaitingListBundle.model_validate(payload)


def test_a_duplicate_hospitalization_code_is_allowed_but_flagged() -> None:
    """The source code is not unique; referral_id is the key and the collision is marked, not dropped."""
    rows = [source_row(1, is_dup_code=True), source_row(2, is_dup_code=True)]
    published = builder.referral_rows(rows, ORIGIN)
    published[1]["hospitalization_code"] = published[0]["hospitalization_code"]
    payload = bundle_payload(rows)
    payload["referrals"] = published
    bundle = WaitingListBundle.model_validate(payload)
    assert all(row.is_duplicate_code for row in bundle.referrals)
