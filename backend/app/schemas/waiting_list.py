"""Publication input and API DTOs for the real waiting list at a fixed origin.

This publication carries **no model output of any kind** — no wait estimate, no refusal probability, no survival
curve, no severity. It is the measured queue as it stood at the end of the origin day, plus, in a separate and
explicitly marked field, what the Ministry of Health data later recorded as the actual outcome.

`observed_after_origin` is hindsight. Nothing in it was knowable at the origin, and nothing in the product may feed
it into a prediction, a ranking or a threshold: it exists to score an origin-time claim after the fact and for
nothing else. `ObservedAfterOrigin.disclosure` carries that statement on every single row, so a consumer that
strips context still sees it.
"""

from __future__ import annotations

import datetime as dt
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

SHA256 = r"^[0-9a-f]{64}$"
HINDSIGHT_DISCLOSURE = "HINDSIGHT_NOT_AVAILABLE_AT_ORIGIN"

ObservedStatus = Literal["ADMITTED", "REFUSED", "STILL_WAITING_AT_CUTOFF"]
# waiting_count of the hospital at the origin, against the published thresholds; a read-time UI uses it to refuse
# to draw a per-hospital view that a handful of referrals cannot support (docs/api.md)
SupportClass = Literal["SUFFICIENT", "LIMITED", "SPARSE"]


class CohortDefinition(BaseModel):
    """The frozen rule that produced the cohort. Part of the publication identity, so it cannot drift silently."""

    model_config = ConfigDict(extra="forbid")

    waiting_rule: str = Field(min_length=1, max_length=500)
    excluded_profile_codes: list[str] = Field(min_length=1)
    excluded_profile_reason: str = Field(min_length=1, max_length=500)
    registration_floor: dt.date = Field(description="earliest registration_date present in the source data")
    lower_bound_note: str = Field(min_length=1, max_length=500)


class SupportThresholds(BaseModel):
    """Published, not recomputed: the support class of every hospital row is auditable against these numbers."""

    model_config = ConfigDict(extra="forbid")

    sufficient_min: int = Field(ge=1, description="waiting_count at or above this is SUFFICIENT")
    limited_min: int = Field(ge=1, description="waiting_count at or above this, but below sufficient_min, is LIMITED")

    @model_validator(mode="after")
    def validate_thresholds(self) -> SupportThresholds:
        if self.limited_min >= self.sufficient_min:
            raise ValueError("limited_min must be below sufficient_min")
        return self

    def classify(self, waiting_count: int) -> str:
        if waiting_count >= self.sufficient_min:
            return "SUFFICIENT"
        return "LIMITED" if waiting_count >= self.limited_min else "SPARSE"


class ObservedAfterOrigin(BaseModel):
    """Hindsight only. Never an input to anything: see the module docstring."""

    model_config = ConfigDict(extra="forbid")

    disclosure: Literal["HINDSIGHT_NOT_AVAILABLE_AT_ORIGIN"]
    status: ObservedStatus
    event_date: dt.date | None = Field(default=None, description="admission or refusal date; null while waiting")
    days_from_origin: int | None = Field(default=None, ge=1, description="event_date - origin, in days")

    @model_validator(mode="after")
    def validate_observation(self) -> ObservedAfterOrigin:
        resolved = self.status in {"ADMITTED", "REFUSED"}
        if resolved and (self.event_date is None or self.days_from_origin is None):
            raise ValueError("a resolved observed outcome needs both event_date and days_from_origin")
        if not resolved and (self.event_date is not None or self.days_from_origin is not None):
            raise ValueError("STILL_WAITING_AT_CUTOFF must not carry an event date")
        return self


class WaitingReferralRow(BaseModel):
    """One referral that was waiting at the end of the origin day."""

    model_config = ConfigDict(extra="forbid")

    referral_id: int = Field(ge=1, description="fact_referral surrogate key: stable across ingest runs, no patient id")
    hospitalization_code: str = Field(min_length=1, max_length=32)
    is_duplicate_code: bool = Field(description="hospitalization_code occurs on more than one source row")
    org_code: str = Field(min_length=1, max_length=8)
    region_code: str = Field(min_length=1, max_length=4, description="region of the receiving hospital")
    patient_region_code: str = Field(min_length=1, max_length=4, description="patient's region of origin")
    profile_code: str = Field(min_length=1, max_length=8)
    registration_date: dt.date
    days_waited_at_origin: int = Field(ge=0, description="origin - registration_date, in days")
    observed_after_origin: ObservedAfterOrigin


class WaitingHospitalRow(BaseModel):
    """One hospital's queue at the origin. Counts only — no model value, no rank, no severity."""

    model_config = ConfigDict(extra="forbid")

    org_code: str = Field(min_length=1, max_length=8)
    region_code: str = Field(min_length=1, max_length=4)
    waiting_count: int = Field(ge=1)
    profile_count: int = Field(ge=1)
    median_days_waited: float = Field(ge=0, allow_inf_nan=False)
    max_days_waited: int = Field(ge=0)
    support_class: SupportClass


class WaitingListBundle(BaseModel):
    """The whole publication. Identity covers every field except the identity itself and `generated_at`."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["waiting_list_v1"]
    contract_version: Literal["1.0.0"]
    publication_id: str = Field(min_length=1, max_length=128)
    publication_identity_sha256: str = Field(pattern=SHA256)
    source_code_commit: str = Field(pattern=r"^[0-9a-f]{40}$")
    origin: dt.date
    outcome_cutoff: dt.datetime = Field(description="exclusive label cutoff of the source data")
    observed_through: dt.date = Field(description="last date on which the source data records any outcome")
    cohort: CohortDefinition
    support_thresholds: SupportThresholds
    carries_model_output: Literal[False] = Field(
        description="always false: this publication is measured data and hindsight, never a prediction"
    )
    generated_at: dt.datetime | None = None
    limitations: list[str] = Field(min_length=1)
    hospitals: list[WaitingHospitalRow]
    referrals: list[WaitingReferralRow]

    @model_validator(mode="after")
    def validate_bundle(self) -> WaitingListBundle:
        if self.observed_through >= self.outcome_cutoff.date():
            raise ValueError("observed_through must lie before the exclusive outcome_cutoff")
        if self.origin >= self.observed_through:
            raise ValueError("origin must lie before observed_through")
        if self.cohort.registration_floor > self.origin:
            raise ValueError("registration_floor must not lie after the origin")

        excluded = set(self.cohort.excluded_profile_codes)
        ids = [row.referral_id for row in self.referrals]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate referral_id")
        for row in self.referrals:
            if row.registration_date > self.origin:
                raise ValueError(f"referral {row.referral_id} was registered after the origin")
            if row.days_waited_at_origin != (self.origin - row.registration_date).days:
                raise ValueError(f"referral {row.referral_id} has an inconsistent days_waited_at_origin")
            if row.profile_code in excluded:
                raise ValueError(f"referral {row.referral_id} carries an excluded profile {row.profile_code!r}")
            observed = row.observed_after_origin
            if observed.event_date is not None:
                if observed.event_date <= self.origin:
                    raise ValueError(f"referral {row.referral_id} resolved on or before the origin")
                if observed.event_date > self.observed_through:
                    raise ValueError(f"referral {row.referral_id} resolved after observed_through")
                if observed.days_from_origin != (observed.event_date - self.origin).days:
                    raise ValueError(f"referral {row.referral_id} has an inconsistent days_from_origin")

        org_codes = [row.org_code for row in self.hospitals]
        if len(org_codes) != len(set(org_codes)):
            raise ValueError("duplicate org_code in hospitals")
        counted: dict[str, list[WaitingReferralRow]] = {}
        for row in self.referrals:
            counted.setdefault(row.org_code, []).append(row)
        if set(counted) != set(org_codes):
            raise ValueError("hospitals and referrals cover different org_code sets")
        for hospital in self.hospitals:
            rows = counted[hospital.org_code]
            if hospital.waiting_count != len(rows):
                raise ValueError(f"hospital {hospital.org_code} waiting_count does not match its referrals")
            if hospital.profile_count != len({row.profile_code for row in rows}):
                raise ValueError(f"hospital {hospital.org_code} profile_count does not match its referrals")
            if hospital.max_days_waited != max(row.days_waited_at_origin for row in rows):
                raise ValueError(f"hospital {hospital.org_code} max_days_waited does not match its referrals")
            if hospital.support_class != self.support_thresholds.classify(hospital.waiting_count):
                raise ValueError(f"hospital {hospital.org_code} support_class contradicts the published thresholds")
            if {row.region_code for row in rows} != {hospital.region_code}:
                raise ValueError(f"hospital {hospital.org_code} region_code does not match its referrals")
        return self


# ---------------------------------------------------------------------------------------------- API responses


class WaitingProfileBreakdown(BaseModel):
    """One bed profile's share of a hospital's queue at the origin. Counts only."""

    profile_code: str
    profile_name: str
    waiting_count: int
    median_days_waited: float
    max_days_waited: int


class WaitingDaysBucket(BaseModel):
    """One bar of the days-already-waited histogram; `to_days` is exclusive, null on the open-ended last bucket."""

    from_days: int
    to_days: int | None
    count: int


class ObservedAfterOriginCounts(BaseModel):
    """Hindsight totals, under the same rule as the per-referral field: display only, never an input."""

    disclosure: Literal["HINDSIGHT_NOT_AVAILABLE_AT_ORIGIN"]
    admitted: int
    refused: int
    still_waiting_at_cutoff: int


class WaitingListPublication(BaseModel):
    """Which publication answered, repeated on every row so a stored response stays attributable."""

    publication_id: str
    publication_identity_sha256: str
    origin: dt.date


class WaitingHospitalResponse(WaitingListPublication):
    org_code: str
    org_name: str
    region_code: str
    region_name: str
    waiting_count: int
    profile_count: int
    median_days_waited: float
    max_days_waited: int
    support_class: SupportClass


class WaitingReferralResponse(WaitingListPublication):
    referral_id: int
    hospitalization_code: str
    is_duplicate_code: bool
    org_code: str
    region_code: str
    patient_region_code: str
    profile_code: str
    profile_name: str
    registration_date: dt.date
    days_waited_at_origin: int
    observed_after_origin: ObservedAfterOrigin


class WaitingListSnapshotResponse(BaseModel):
    publication_id: str
    schema_version: str
    contract_version: str
    publication_identity_sha256: str
    bundle_sha256: str
    source_code_commit: str
    origin: dt.date
    outcome_cutoff: dt.datetime
    observed_through: dt.date
    published_at: dt.datetime
    generated_at: dt.datetime | None
    carries_model_output: Literal[False]
    hospital_count: int
    waiting_count: int
    cohort: CohortDefinition
    support_thresholds: SupportThresholds
    limitations: list[str]


class WaitingHospitalDetailResponse(WaitingHospitalResponse):
    """One hospital's queue at the origin, with everything the hospital screen needs in a single request."""

    profiles: list[WaitingProfileBreakdown]
    days_waited_histogram: list[WaitingDaysBucket]
    observed_after_origin: ObservedAfterOriginCounts
