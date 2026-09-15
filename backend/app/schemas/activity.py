"""Referrals, recommendations, decisions, alerts."""

import datetime as dt
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.common import Status


class ReferralItem(BaseModel):
    """One test-period referral with model outputs. No patient identifiers beyond hospitalization_code."""

    hospitalization_code: str
    registration_date: dt.date
    icd10_code: str | None
    diagnosis_name: str | None = Field(description="name of icd10_code from dim_icd (source systems' spelling)")
    referral_purpose: str | None
    pred_wait_days: float
    pred_refusal_prob: float
    is_high_risk: bool = Field(description="pred_refusal_prob >= high_risk_threshold (0.25)")
    explanation: dict[str, Any] = Field(
        description='{"wait_time": [top-5 factors], "refusal_risk": [top-5 factors]}; each factor has the raw `value`, '
        "a display-ready `value_display` (rates in %, counts as integers, days with 1 decimal, codes with dictionary "
        "names), `short_label`, `effect` in model units (days / probability) and `effect_in_unit` with `unit` "
        "(дн. / п.п.)"
    )


class RecommendationRule(BaseModel):
    region_top_fraction: float
    min_wait_delta_days: float
    max_alternatives: int
    min_registrations_28d: int


class CurrentState(BaseModel):
    load_index: float | None
    status: Status
    region_rank: int | None
    region_n_ranked: int
    in_region_top: bool
    backlog_days: float | None
    median_wait_28d: float | None
    refusal_rate_28d: float | None
    registrations_28d: int


class Alternative(BaseModel):
    recommendation_id: str = Field(description="stable id, pass it to POST /decisions")
    org_code: str
    org_name: str
    region_code: str
    profile_code: str
    expected_wait_current: float
    expected_wait_alternative: float
    delta_days: float = Field(description="expected_wait_current − expected_wait_alternative (> 0 = shorter)")
    refusal_rate_current: float | None
    refusal_rate_alternative: float | None
    backlog_days_current: float
    backlog_days_alternative: float
    load_index_alternative: float | None
    registrations_28d_alternative: int
    method: str
    explanation: str


class RecommendationResponse(BaseModel):
    as_of_date: dt.date
    region_code: str
    region_name: str
    org_code: str
    org_name: str
    profile_code: str
    profile_name: str
    method: str = Field(description="how the wait effect is estimated; v1: historical_median")
    eligible: bool = Field(description="the hospital × profile triggers the rule (top of its region by load_index)")
    reason: str | None = Field(description="why there are no alternatives, in Russian")
    current: CurrentState
    rule: RecommendationRule
    alternatives: list[Alternative]
    disclaimer: str


class DecisionCreate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    region_code: str = Field(min_length=1, max_length=4)
    org_code: str = Field(min_length=1, max_length=8)
    profile_code: str = Field(min_length=1, max_length=8)
    recommendation_id: str | None = Field(default=None, max_length=128)
    alternative_org_code: str | None = Field(
        default=None,
        max_length=8,
        description="the recommended hospital; derived from recommendation_id when omitted",
    )
    action: Literal["confirm", "reject", "defer"]
    comment: str | None = Field(default=None, max_length=4000)
    actor: str = Field(min_length=1, max_length=200)
    idempotency_key: str | None = Field(
        default=None,
        min_length=8,
        max_length=128,
        pattern=r"^[A-Za-z0-9._:-]+$",
        description="client-generated (e.g. a UUID per form submission); resending the same key returns the stored "
        "row with 200 instead of creating a duplicate",
    )


class Decision(DecisionCreate):
    id: int
    created_at: dt.datetime
    alternative_org_name: str | None
    api_key_label: str | None = Field(description="label of the API key that submitted the decision")


class AlertItem(BaseModel):
    region_code: str
    region_name: str
    org_code: str
    org_name: str
    profile_code: str
    profile_name: str
    load_index: float | None
    status: Status
    status_label: str
    region_rank: int | None
    region_n_ranked: int
    queue_now: int
    backlog_days: float | None
    queue_trend_raw_4w: float | None
    queue_trend_4w: float | None
    refusal_rate_28d: float | None
    reasons: list[str] = Field(description="Russian reason strings")
