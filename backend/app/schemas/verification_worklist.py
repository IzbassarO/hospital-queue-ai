"""Publication input and API DTOs for the verification worklist at a fixed origin.

**What this is.** An administrative list for the hospitalisation bureau: the whole formal queue at the origin, in
the order the ML side's origin-safe verification priority suggests checking records against the patient and the
paperwork. It is produced from the ML side's ghost-queue bundle (schema 2), and this module's whole job is to keep
the product's language and guarantees around it straight.

**What this is not**, enforced here rather than left to whoever writes the screen:

* It is **not a queue.** The measured queue is `app/schemas/waiting_list.py` and it stands unchanged; nothing in
  this publication removes, reorders or shortens it. The list ranks every referral of the formal queue — the
  parser refuses a publication whose ranked count differs from the formal queue — so there is no subset whose
  difference could be presented as "the real queue".
* It is **not a decision** and **not a classifier.** `decision_owner` is a literal the parser enforces, and
  `not_a_decision` carries the sentence that says the specialist decides, on the publication and on every API
  response. A priority score orders clerical work; it never says a referral is stale, fictitious or removable.
  Every sentence the product puts on a screen is published in both interface languages.
* It is **not a claim about a person.** The history-quality codes are about how much comparable history backs the
  number, and the vocabulary is fixed here.

`yield_curve` is hindsight — how many of the first N in this order turned out to be no longer current, against the
whole queue's base rate — and carries the same disclosure marker as everywhere else in the product. It exists to
tell a bureau how much the order helps, and it feeds nothing. No row carries an outcome.
"""

from __future__ import annotations

import datetime as dt
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.schemas.waiting_list import HINDSIGHT_DISCLOSURE

SHA256 = r"^[0-9a-f]{64}$"
# probabilities and scores are published rounded to six decimals. The source model's curve can land exactly on a
# threshold and clear `strictly below` only by floating-point representation (0.09999999999999991 < 0.1), so the
# threshold checks here tolerate exactly that rounding and no more.
ROUNDING = 1e-6
# the sentence that travels with every response; the UI renders it, it is not decoration
DECISION_OWNER = "SPECIALIST_DECIDES"
# the tiers of the source model's fallback hierarchy, finest first
EstimateTier = Literal["hospital_profile", "region_profile", "profile", "global"]
# why the source says a row's number rests on thin history; codes containing "insufficient" mean the assigned
# risk set had fewer comparable at-risk referrals than `ranking.minimum_comparable_at_risk_rows`
HistoryQualityReason = Literal[
    "insufficient_comparable_history",
    "insufficient_and_degenerate_comparable_history",
    "degenerate_conditional_distribution",
]
WorklistOrder = Literal["rank", "longest_wait"]


class LocalisedText(BaseModel):
    """One sentence in both interface languages. The framing is only as good as the half a reader understands."""

    model_config = ConfigDict(extra="forbid")

    ru: str = Field(min_length=1, max_length=600)
    kk: str = Field(min_length=1, max_length=600)


class SourcePublication(BaseModel):
    """The ML bundle this worklist was read from, by its own identity. Part of the publication identity."""

    model_config = ConfigDict(extra="forbid")

    publication_id: str = Field(min_length=1, max_length=128)
    publication_identity_sha256: str = Field(pattern=SHA256)
    file_sha256: str = Field(pattern=SHA256, description="sha256 of the compressed artifact as produced")
    schema_version: int = Field(ge=2)
    model: str = Field(min_length=1, max_length=200)


class LegacyRule(BaseModel):
    """The earlier binary rule, kept for comparison only: it does not select or order this list."""

    model_config = ConfigDict(extra="forbid")

    role: Literal["AUDITED_REFERENCE_ONLY"]
    reason_code: str = Field(min_length=1, max_length=64)
    minimum_days_waited: int = Field(ge=0)
    horizon_days: int = Field(ge=1)
    probability_strictly_below: float = Field(gt=0, lt=1)
    selected_count: int = Field(ge=0, description="rows of this list the old rule would have selected")
    training_only_justification: str = Field(min_length=1, max_length=600)
    statement: LocalisedText = Field(description="the rule and its role in one sentence, for the screen")


class RankingRule(BaseModel):
    """How the worklist is ordered, as the ML side fixed it before any hindsight was looked at."""

    model_config = ConfigDict(extra="forbid")

    definition: LocalisedText
    keys: list[str] = Field(min_length=1, description="the ordering keys, most significant first")
    score_name: str = Field(min_length=1, max_length=64)
    score_formula: str = Field(min_length=1, max_length=128)
    wait_maturity_days: int = Field(ge=1)
    minimum_comparable_at_risk_rows: int = Field(ge=1)
    training_only_justification: str = Field(min_length=1, max_length=600)


class HistoryQuality(BaseModel):
    """How many rows rest on thin comparable history, and why. Read from the source, never re-derived."""

    model_config = ConfigDict(extra="forbid")

    definition: LocalisedText
    warning_count: int = Field(ge=0)
    warning_share: float = Field(ge=0, le=1, allow_inf_nan=False)
    reason_counts: dict[HistoryQualityReason, int] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_reasons(self) -> HistoryQuality:
        if sum(self.reason_counts.values()) != self.warning_count:
            raise ValueError("history-quality reason counts do not sum to the warning count")
        return self


class WorklistCounts(BaseModel):
    """The formal queue and the ranked list are the same referrals: the list reorders for checking, never subtracts."""

    model_config = ConfigDict(extra="forbid")

    formal_queue_count: int = Field(ge=1, description="the measured queue at the origin; unchanged by this list")
    ranked_count: int = Field(ge=1, description="referrals in the verification order; always the whole formal queue")

    @model_validator(mode="after")
    def validate_counts(self) -> WorklistCounts:
        if self.ranked_count != self.formal_queue_count:
            raise ValueError("the verification order must rank the whole formal queue, no more and no less")
        return self


class YieldBase(BaseModel):
    """The whole formal queue's share that turned out no longer current: what checking at random would find."""

    model_config = ConfigDict(extra="forbid")

    evaluated: int = Field(ge=1)
    no_longer_current: int = Field(ge=0)
    share: float = Field(ge=0, le=1, allow_inf_nan=False)

    @model_validator(mode="after")
    def validate_base(self) -> YieldBase:
        if self.no_longer_current > self.evaluated:
            raise ValueError("more findings than referrals evaluated")
        if abs(self.share - self.no_longer_current / self.evaluated) > 1e-6:
            raise ValueError("base share does not match the counts")
        return self


class YieldPoint(BaseModel):
    """One point of the retrospective yield curve: check the first `checked`, find `no_longer_current`."""

    model_config = ConfigDict(extra="forbid")

    checked: int = Field(ge=1)
    no_longer_current: int = Field(ge=0)
    share: float = Field(ge=0, le=1, allow_inf_nan=False)
    lift: float = Field(ge=0, allow_inf_nan=False, description="share divided by the base share")

    @model_validator(mode="after")
    def validate_point(self) -> YieldPoint:
        if self.no_longer_current > self.checked:
            raise ValueError("more findings than referrals checked")
        if abs(self.share - self.no_longer_current / self.checked) > 1e-6:
            raise ValueError("share does not match the counts")
        return self


class YieldCurve(BaseModel):
    """Hindsight, marked as such: what checking the first N of this order would have turned up, against the base."""

    model_config = ConfigDict(extra="forbid")

    disclosure: Literal["HINDSIGHT_NOT_AVAILABLE_AT_ORIGIN"]
    definition: LocalisedText
    outcome_source: str = Field(min_length=1, max_length=128, description="publication the outcomes were read from")
    outcome_source_identity_sha256: str = Field(pattern=SHA256)
    base: YieldBase
    points: list[YieldPoint] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_curve(self) -> YieldCurve:
        checked = [point.checked for point in self.points]
        if checked != sorted(set(checked)):
            raise ValueError("yield points must be unique and ascending")
        for point in self.points:
            expected = point.no_longer_current / point.checked / self.base.share if self.base.share else 0.0
            if abs(point.lift - expected) > 1e-5:
                raise ValueError(f"top {point.checked}: lift does not match the share and the base")
        return self


class AreaRow(BaseModel):
    """One region's or one hospital's formal queue and how much of it rests on thin history. Counts only."""

    model_config = ConfigDict(extra="forbid")

    level: Literal["region", "hospital"]
    code: str = Field(min_length=1, max_length=8)
    region_code: str | None = Field(default=None, max_length=4, description="set on hospital rows")
    formal_queue_count: int = Field(ge=0)
    history_quality_warning_count: int = Field(ge=0)
    history_quality_warning_share: float = Field(ge=0, le=1, allow_inf_nan=False)

    @model_validator(mode="after")
    def validate_area(self) -> AreaRow:
        if self.history_quality_warning_count > self.formal_queue_count:
            raise ValueError(f"{self.level} {self.code}: more warnings than referrals in the formal queue")
        expected = self.history_quality_warning_count / self.formal_queue_count if self.formal_queue_count else 0.0
        if abs(self.history_quality_warning_share - expected) > 1e-6:
            raise ValueError(f"{self.level} {self.code}: history_quality_warning_share does not match its counts")
        if self.level == "hospital" and self.region_code is None:
            raise ValueError(f"hospital {self.code}: region_code is required")
        if self.level == "region" and self.region_code is not None:
            raise ValueError(f"region {self.code}: region_code must not repeat the code")
        return self


class WorklistItem(BaseModel):
    """One referral in the verification order. Origin-time fields only: `extra="forbid"` keeps outcomes out."""

    model_config = ConfigDict(extra="forbid")

    referral_id: int = Field(ge=1)
    rank: int = Field(ge=1, description="1 is checked first, under the published ranking rule")
    org_code: str = Field(min_length=1, max_length=8)
    region_code: str = Field(min_length=1, max_length=4)
    profile_code: str = Field(min_length=1, max_length=8)
    days_waited_at_origin: int = Field(ge=0)
    probability_admitted_30d: float = Field(ge=0, le=1, allow_inf_nan=False)
    probability_admitted_horizon: float = Field(ge=0, le=1, allow_inf_nan=False)
    probability_ever_admitted: float = Field(ge=0, le=1, allow_inf_nan=False)
    observable_curve_end_day: float = Field(ge=0, allow_inf_nan=False)
    estimate_tier: EstimateTier
    verification_priority_score: float = Field(ge=0, le=1, allow_inf_nan=False)
    comparable_training_at_risk_rows: int = Field(ge=0)
    history_quality_warning: bool
    history_quality_reason_code: HistoryQualityReason | None

    @model_validator(mode="after")
    def validate_item(self) -> WorklistItem:
        if self.probability_admitted_30d > self.probability_admitted_horizon + ROUNDING:
            raise ValueError(f"referral {self.referral_id}: the 30-day chance exceeds the horizon chance")
        if self.probability_admitted_horizon > self.probability_ever_admitted + ROUNDING:
            raise ValueError(f"referral {self.referral_id}: the horizon chance exceeds the whole-curve chance")
        if self.history_quality_warning != (self.history_quality_reason_code is not None):
            raise ValueError(f"referral {self.referral_id}: a history-quality warning needs exactly one reason")
        return self


class VerificationWorklistBundle(BaseModel):
    """The whole publication. Identity covers every field except the identity itself and `generated_at`."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["verification_worklist_v2"]
    contract_version: Literal["2.0.0"]
    publication_id: str = Field(min_length=1, max_length=128)
    publication_identity_sha256: str = Field(pattern=SHA256)
    source_code_commit: str = Field(pattern=r"^[0-9a-f]{40}$")
    origin: dt.date
    decision_owner: Literal["SPECIALIST_DECIDES"]
    not_a_decision: LocalisedText = Field(description="shown wherever this list is shown, in both languages")
    source_publication: SourcePublication
    ranking: RankingRule
    legacy_rule: LegacyRule
    history_quality: HistoryQuality
    estimands: dict[str, str] = Field(min_length=1)
    counts: WorklistCounts
    yield_curve: YieldCurve
    areas: list[AreaRow] = Field(min_length=1)
    generated_at: dt.datetime | None = None
    limitations: list[str] = Field(min_length=1)
    items: list[WorklistItem] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_bundle(self) -> VerificationWorklistBundle:
        if len(self.items) != self.counts.ranked_count:
            raise ValueError("the worklist does not hold exactly the ranked referrals")
        ids = [item.referral_id for item in self.items]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate referral_id")
        ordered = sorted(self.items, key=lambda item: item.rank)
        if [item.rank for item in ordered] != list(range(1, len(self.items) + 1)):
            raise ValueError("rank must be a dense 1..n sequence")
        for before, after in zip(ordered, ordered[1:], strict=False):
            if after.verification_priority_score > before.verification_priority_score + ROUNDING:
                raise ValueError(f"rank {after.rank}: a higher priority score is ranked after a lower one")

        minimum = self.ranking.minimum_comparable_at_risk_rows
        reasons: dict[str, int] = {}
        for item in self.items:
            code = item.history_quality_reason_code
            if code is not None:
                reasons[code] = reasons.get(code, 0) + 1
            thin = item.comparable_training_at_risk_rows < minimum
            if thin != (code is not None and code.startswith("insufficient")):
                raise ValueError(
                    f"referral {item.referral_id}: the insufficient-history code disagrees with its support"
                )
        if reasons != {code: count for code, count in self.history_quality.reason_counts.items() if count}:
            raise ValueError("history_quality.reason_counts does not match the items")
        if abs(self.history_quality.warning_share - self.history_quality.warning_count / len(self.items)) > 1e-6:
            raise ValueError("history_quality.warning_share does not match the counts")

        # the source counted on unrounded probabilities; rows sitting on the threshold after rounding may go either
        # way, so the published count must lie between the strict and the tolerant reading of the rounded rows
        rule = self.legacy_rule
        waited = [item for item in self.items if item.days_waited_at_origin >= rule.minimum_days_waited]
        low = sum(item.probability_admitted_horizon < rule.probability_strictly_below - ROUNDING for item in waited)
        high = sum(item.probability_admitted_horizon <= rule.probability_strictly_below + ROUNDING for item in waited)
        if not low <= rule.selected_count <= high:
            raise ValueError("legacy_rule.selected_count does not match the items")

        levels = {(row.level, row.code) for row in self.areas}
        if len(levels) != len(self.areas):
            raise ValueError("duplicate area row")
        regions = [row for row in self.areas if row.level == "region"]
        if not regions:
            raise ValueError("the publication needs its region view")
        if sum(row.formal_queue_count for row in regions) != self.counts.formal_queue_count:
            raise ValueError("the region rows do not sum to the formal queue")
        if sum(row.history_quality_warning_count for row in regions) != self.history_quality.warning_count:
            raise ValueError("the region rows do not sum to the history-quality warnings")

        if self.yield_curve.base.evaluated != self.counts.formal_queue_count:
            raise ValueError("the yield base must be the whole formal queue")
        if max(point.checked for point in self.yield_curve.points) > self.counts.ranked_count:
            raise ValueError("the yield curve checks more referrals than the list holds")
        return self


# ---------------------------------------------------------------------------------------------- API responses


class WorklistPublication(BaseModel):
    """Repeated on every row so a stored response stays attributable — and keeps the framing with it."""

    publication_id: str
    publication_identity_sha256: str
    origin: dt.date
    decision_owner: Literal["SPECIALIST_DECIDES"]
    not_a_decision: LocalisedText


class WorklistItemResponse(WorklistPublication):
    referral_id: int
    rank: int
    org_code: str
    region_code: str
    profile_code: str
    profile_name: str
    days_waited_at_origin: int
    registration_date: dt.date | None = Field(description="from the measured queue; null if it no longer stands")
    hospitalization_code: str | None = Field(description="the operational code, for the bureau to look the row up")
    probability_admitted_30d: float
    probability_admitted_horizon: float
    horizon_days: int
    estimate_tier: EstimateTier
    verification_priority_score: float
    comparable_training_at_risk_rows: int
    history_quality_warning: bool
    history_quality_reason_code: HistoryQualityReason | None


class WorklistAreaResponse(BaseModel):
    level: Literal["region", "hospital"]
    code: str
    name: str
    region_code: str | None
    formal_queue_count: int
    history_quality_warning_count: int
    history_quality_warning_share: float


class WorklistHospitalResponse(WorklistPublication):
    """One hospital's part of the verification order: its counts, its region's counts, and a ranked page."""

    org_code: str
    org_name: str
    region_code: str
    region_name: str
    formal_queue_count: int
    history_quality_warning_count: int
    history_quality_warning_share: float
    region: WorklistAreaResponse
    items: list[WorklistItemResponse]
    total: int
    limit: int
    offset: int


class VerificationWorklistPublicationResponse(BaseModel):
    """The publication itself: the order, what the marks mean, and what checking in this order would have found."""

    publication_id: str
    schema_version: str
    contract_version: str
    publication_identity_sha256: str
    bundle_sha256: str
    source_code_commit: str
    origin: dt.date
    published_at: dt.datetime
    generated_at: dt.datetime | None
    decision_owner: Literal["SPECIALIST_DECIDES"]
    not_a_decision: LocalisedText
    source_publication: SourcePublication
    ranking: RankingRule
    legacy_rule: LegacyRule
    history_quality: HistoryQuality
    estimands: dict[str, str]
    counts: WorklistCounts
    yield_curve: YieldCurve
    limitations: list[str]


__all__ = [
    "DECISION_OWNER",
    "HINDSIGHT_DISCLOSURE",
    "AreaRow",
    "EstimateTier",
    "HistoryQuality",
    "HistoryQualityReason",
    "LegacyRule",
    "LocalisedText",
    "RankingRule",
    "SourcePublication",
    "VerificationWorklistBundle",
    "VerificationWorklistPublicationResponse",
    "WorklistAreaResponse",
    "WorklistCounts",
    "WorklistHospitalResponse",
    "WorklistItem",
    "WorklistItemResponse",
    "WorklistOrder",
    "YieldBase",
    "YieldCurve",
    "YieldPoint",
]
