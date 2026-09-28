"""Publication input and API DTOs for the per-referral journey estimates at a fixed origin.

Sibling of `app/schemas/waiting_list.py` and deliberately a separate publication. The waiting list is measured
data and its contract forbids a model column; these are model output for exactly the same cohort at the same
origin. Keeping them apart means a reader always knows which of the two numbers on a row was measured and which
was estimated, and the measured publication keeps its `carries_model_output: false` guarantee.

Three rules the parser enforces rather than trusts:

* **Origin-time only.** Every estimate is produced from history up to the origin day. Nothing in this publication
  may depend on an outcome recorded after it; the hindsight that scores these estimates lives in the waiting-list
  publication and in `calibration`, which is marked with the same disclosure string and is display-only.
* **Coherence.** `admitted_*` rises with the horizon and `admitted_30d + refused_30d <= 1`: the remainder is the
  probability of still waiting on day 30, which the UI derives instead of the bundle repeating it.
* **Abstention is a value, not a gap.** A referral with no admission window carries a named reason. An empty cell
  that could mean either "no window" or "we forgot" is not acceptable on a clinical-adjacent screen.
* **A degenerate estimate says so.** The served curve is conditional on how long the referral has already waited,
  and past sixty days the comparable history that is still at risk is thin enough that the whole 30-day
  probability mass lands on one outcome — 0%, or 100%. Such a row carries `degenerate_30d`, because a bare "0%"
  read as a probability is a far stronger claim than the evidence behind it, and the longest-waiting referrals
  are exactly the ones a specialist opens first.

`estimate_tier` says which historical cell the curve came from — this hospital and profile, the region and
profile, the profile nationally, or the national pool. It is provenance, not confidence, and the UI shows it in
words next to every number rather than in a footnote.
"""

from __future__ import annotations

import datetime as dt
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.schemas.waiting_list import HINDSIGHT_DISCLOSURE, WaitingReferralResponse

SHA256 = r"^[0-9a-f]{64}$"
HORIZONS: tuple[int, ...] = (7, 14, 30)
# the four levels of the published fallback hierarchy, finest first; the wording the UI shows lives in i18n
EstimateTier = Literal["hospital_profile", "region_profile", "profile", "national"]
# the single reason an admission window is withheld: the comparable history holds no admission inside the model's
# time grid, so no central interval exists to quote. A different reason would need a new literal and a new label.
AbstentionReason = Literal["NO_ADMISSION_IN_COMPARABLE_HISTORY"]
JourneyModel = Literal["aalen_johansen", "xgboost_aft", "discrete_competing_risk"]
ReferralOrder = Literal["longest_wait", "shortest_wait", "highest_refusal_risk"]


class SourceRun(BaseModel):
    """The ML run these estimates were read from, by its own identity hashes. Part of the publication identity."""

    model_config = ConfigDict(extra="forbid")

    run_id: str = Field(min_length=1, max_length=128)
    artifact_identity_sha256: str = Field(pattern=SHA256, description="every file of the run directory")
    scientific_identity_sha256: str = Field(pattern=SHA256, description="the run minus timing and memory")
    training_sha256: str = Field(pattern=SHA256)
    scoring_sha256: str = Field(pattern=SHA256)
    seed: int
    library_versions: dict[str, str] = Field(min_length=1)


class CandidateDecision(BaseModel):
    """One competitor in the model tournament, scored on the metric fixed before the run."""

    model_config = ConfigDict(extra="forbid")

    model_key: JourneyModel
    role: Literal["baseline", "candidate"]
    accepted: bool | None = Field(description="null for the baseline: it is the thing candidates must beat")
    overall_mean_brier: float = Field(ge=0, le=1, allow_inf_nan=False)
    overall_delta: float | None = Field(default=None, description="candidate minus baseline; negative is better")
    worst_bucket_delta: float | None = Field(default=None, description="worst days-waited bucket, same sign rule")
    strict_overall_improvement: bool | None = None
    within_bucket_tolerance: bool | None = None
    brier_by_horizon: dict[str, float] = Field(
        min_length=1, description="mean of the admission and refusal Brier score at each horizon"
    )

    @model_validator(mode="after")
    def validate_candidate(self) -> CandidateDecision:
        baseline = self.role == "baseline"
        if baseline and self.accepted is not None:
            raise ValueError("the baseline is not accepted or rejected; it is the comparison")
        if not baseline and self.accepted is None:
            raise ValueError("a candidate must record whether it was accepted")
        if not baseline and self.overall_delta is None:
            raise ValueError("a candidate must record its delta against the baseline")
        return self


class ModelSelection(BaseModel):
    """Why this model serves. The rule is published with the numbers, so a reader can re-apply it themselves."""

    model_config = ConfigDict(extra="forbid")

    metric: str = Field(min_length=1, max_length=120)
    decision_rule: str = Field(min_length=1, max_length=600, description="the rule as it was fixed, before the run")
    tolerance: float = Field(ge=0, le=1, allow_inf_nan=False)
    require_strict_overall_improvement: bool
    selected_model: JourneyModel
    fallback_used: bool = Field(description="true when no candidate cleared the rule and the baseline serves")
    candidates: list[CandidateDecision] = Field(min_length=2)

    @model_validator(mode="after")
    def validate_selection(self) -> ModelSelection:
        keys = [row.model_key for row in self.candidates]
        if len(keys) != len(set(keys)):
            raise ValueError("duplicate model in the tournament")
        if self.selected_model not in keys:
            raise ValueError("the selected model did not take part in the tournament")
        baselines = [row for row in self.candidates if row.role == "baseline"]
        if len(baselines) != 1:
            raise ValueError("the tournament needs exactly one baseline")
        accepted = [row for row in self.candidates if row.accepted]
        if self.fallback_used:
            if accepted:
                raise ValueError("fallback_used contradicts an accepted candidate")
            if self.selected_model != baselines[0].model_key:
                raise ValueError("fallback_used must select the baseline")
        elif self.selected_model != baselines[0].model_key and not accepted:
            raise ValueError("a selected candidate must be accepted")
        return self


class ReliabilityBin(BaseModel):
    """One row of the reliability table: what the model said, against what the data later recorded."""

    model_config = ConfigDict(extra="forbid")

    horizon_days: int
    outcome: Literal["hospitalized", "refused"]
    bin_index: int = Field(ge=0)
    n: int = Field(ge=1)
    mean_predicted: float = Field(ge=0, le=1, allow_inf_nan=False)
    observed_rate: float = Field(ge=0, le=1, allow_inf_nan=False)
    probability_min: float = Field(ge=0, le=1, allow_inf_nan=False)
    probability_max: float = Field(ge=0, le=1, allow_inf_nan=False)


class Calibration(BaseModel):
    """Hindsight, and labelled as such on the object itself: how the served model's numbers turned out.

    Computed by the ML run over the whole published cohort, never per request and never per hospital: a few dozen
    referrals cannot support a reliability curve, and drawing one would invite exactly the reading it cannot bear.
    """

    model_config = ConfigDict(extra="forbid")

    disclosure: Literal["HINDSIGHT_NOT_AVAILABLE_AT_ORIGIN"]
    model_key: JourneyModel
    rows: int = Field(ge=1)
    bins: list[ReliabilityBin] = Field(min_length=1)


class DegeneracyRule(BaseModel):
    """How many rows put the whole 30-day mass on one outcome, and the sentence that says what that means."""

    model_config = ConfigDict(extra="forbid")

    definition: str = Field(min_length=1, max_length=500)
    count: int = Field(ge=0)
    by_outcome: dict[str, int] = Field(description="count per outcome the mass collapsed onto")


class AttentionRule(BaseModel):
    """The administrative follow-up threshold, published with its definition so the cut is auditable.

    This is a queue-management cut for paperwork — check the referral is still valid, reach the patient — and the
    API carries that sentence next to the number. It is not triage and it is not a clinical statement.
    """

    model_config = ConfigDict(extra="forbid")

    metric: Literal["refused_30d"]
    quantile: float = Field(gt=0, lt=1, allow_inf_nan=False)
    threshold: float = Field(ge=0, le=1, allow_inf_nan=False)
    definition: str = Field(min_length=1, max_length=400)
    intended_use: str = Field(min_length=1, max_length=400)
    flagged_count: int = Field(ge=0)


class ReferralEstimateRow(BaseModel):
    """One referral's origin-time estimates. No patient identifier: the key is the fact_referral surrogate key."""

    model_config = ConfigDict(extra="forbid")

    referral_id: int = Field(ge=1)
    org_code: str = Field(min_length=1, max_length=8)
    profile_code: str = Field(min_length=1, max_length=8)
    estimate_tier: EstimateTier
    similar_training_rows: int = Field(ge=0, description="rows of this hospital and profile in the training window")
    admitted_7d: float = Field(ge=0, le=1, allow_inf_nan=False)
    admitted_14d: float = Field(ge=0, le=1, allow_inf_nan=False)
    admitted_30d: float = Field(ge=0, le=1, allow_inf_nan=False)
    refused_30d: float = Field(ge=0, le=1, allow_inf_nan=False)
    window_lower_days: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    window_upper_days: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    abstention_reason: AbstentionReason | None = None
    refusal_attention: bool
    degenerate_30d: bool = Field(
        description="the whole 30-day probability mass sits on one outcome: thin comparable history, not certainty"
    )

    @property
    def still_waiting_30d(self) -> float:
        return max(0.0, 1.0 - self.admitted_30d - self.refused_30d)

    @model_validator(mode="after")
    def validate_row(self) -> ReferralEstimateRow:
        if not (self.admitted_7d <= self.admitted_14d <= self.admitted_30d):
            raise ValueError(f"referral {self.referral_id}: admission probability falls as the horizon grows")
        # 1e-6 is the rounding the publication applies to every probability; anything beyond it is incoherence
        if self.admitted_30d + self.refused_30d > 1 + 1e-6:
            raise ValueError(f"referral {self.referral_id}: admission and refusal by day 30 exceed one")
        window = (self.window_lower_days, self.window_upper_days)
        if (self.abstention_reason is None) == (window == (None, None)):
            raise ValueError(f"referral {self.referral_id}: exactly one of an admission window and a reason")
        if window != (None, None):
            if None in window:
                raise ValueError(f"referral {self.referral_id}: an admission window needs both ends")
            if self.window_lower_days > self.window_upper_days:
                raise ValueError(f"referral {self.referral_id}: the admission window ends before it starts")
        collapsed = max(self.admitted_30d, self.refused_30d, self.still_waiting_30d) >= 1 - 1e-6
        if self.degenerate_30d != collapsed:
            raise ValueError(f"referral {self.referral_id}: degenerate_30d contradicts the published probabilities")
        return self


class ReferralEstimatesBundle(BaseModel):
    """The whole publication. Identity covers every field except the identity itself and `generated_at`."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["referral_estimates_v1"]
    contract_version: Literal["1.0.0"]
    publication_id: str = Field(min_length=1, max_length=128)
    publication_identity_sha256: str = Field(pattern=SHA256)
    source_code_commit: str = Field(pattern=r"^[0-9a-f]{40}$")
    origin: dt.date
    outcome_cutoff: dt.datetime
    horizons: list[int] = Field(min_length=1)
    admission_window_coverage: float = Field(gt=0, lt=1, allow_inf_nan=False)
    source_run: SourceRun
    selection: ModelSelection
    calibration: Calibration
    estimate_tiers: dict[str, int] = Field(min_length=1, description="referral count per tier")
    abstention_counts: dict[str, int] = Field(description="referral count per abstention reason")
    degeneracy: DegeneracyRule
    attention: AttentionRule
    generated_at: dt.datetime | None = None
    limitations: list[str] = Field(min_length=1)
    referrals: list[ReferralEstimateRow] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_bundle(self) -> ReferralEstimatesBundle:
        if self.origin >= self.outcome_cutoff.date():
            raise ValueError("origin must lie before the exclusive outcome_cutoff")
        if list(self.horizons) != sorted(set(self.horizons)):
            raise ValueError("horizons must be unique and ascending")
        if tuple(self.horizons) != HORIZONS:
            raise ValueError(f"this contract serves the horizons {HORIZONS}")
        if self.calibration.model_key != self.selection.selected_model:
            raise ValueError("the calibration must describe the model that serves")
        if {row.horizon_days for row in self.calibration.bins} - set(self.horizons):
            raise ValueError("the calibration scores a horizon this publication does not carry")

        ids = [row.referral_id for row in self.referrals]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate referral_id")
        tiers: dict[str, int] = {}
        abstentions: dict[str, int] = {}
        collapsed: dict[str, int] = {}
        flagged = 0
        for row in self.referrals:
            if row.degenerate_30d:
                outcome = (
                    "admitted"
                    if row.admitted_30d >= 1 - 1e-6
                    else "refused"
                    if row.refused_30d >= 1 - 1e-6
                    else "still_waiting"
                )
                collapsed[outcome] = collapsed.get(outcome, 0) + 1
            tiers[row.estimate_tier] = tiers.get(row.estimate_tier, 0) + 1
            if row.abstention_reason is not None:
                abstentions[row.abstention_reason] = abstentions.get(row.abstention_reason, 0) + 1
            if row.refusal_attention != (row.refused_30d >= self.attention.threshold):
                raise ValueError(f"referral {row.referral_id}: the attention flag contradicts the threshold")
            flagged += row.refusal_attention
            if row.estimate_tier == "hospital_profile" and row.similar_training_rows == 0:
                raise ValueError(f"referral {row.referral_id}: a hospital-level tier needs hospital history")
        if tiers != {key: value for key, value in self.estimate_tiers.items() if value}:
            raise ValueError("estimate_tiers does not match the referrals")
        if abstentions != {key: value for key, value in self.abstention_counts.items() if value}:
            raise ValueError("abstention_counts does not match the referrals")
        if flagged != self.attention.flagged_count:
            raise ValueError("attention.flagged_count does not match the referrals")
        if sum(collapsed.values()) != self.degeneracy.count:
            raise ValueError("degeneracy.count does not match the referrals")
        if collapsed != {key: value for key, value in self.degeneracy.by_outcome.items() if value}:
            raise ValueError("degeneracy.by_outcome does not match the referrals")
        return self


# ---------------------------------------------------------------------------------------------- API responses


class ReferralEstimateResponse(BaseModel):
    """One referral's estimates, with the publication that produced them repeated on the row."""

    publication_id: str
    publication_identity_sha256: str
    origin: dt.date
    selected_model: JourneyModel
    estimate_tier: EstimateTier
    similar_training_rows: int
    admitted_7d: float
    admitted_14d: float
    admitted_30d: float
    refused_30d: float
    still_waiting_30d: float = Field(description="1 - admitted_30d - refused_30d, clamped at zero")
    window_lower_days: float | None
    window_upper_days: float | None
    window_coverage: float
    abstention_reason: AbstentionReason | None
    refusal_attention: bool
    degenerate_30d: bool = Field(
        description="the whole 30-day mass sits on one outcome; the number is thin evidence, not a certainty"
    )


class QueueReferralResponse(WaitingReferralResponse):
    """A measured queue row with its origin-time estimate, or `null` when this referral has none.

    Two publications on one row, each carrying its own id and identity: `observed_after_origin` is what the data
    recorded afterwards, `estimate` is what was knowable on the origin day. Neither is derived from the other.
    """

    estimate: ReferralEstimateResponse | None


class ReferralEstimatesPublicationResponse(BaseModel):
    """The publication itself: what serves, why it was chosen, how well it turned out, and what it withholds."""

    publication_id: str
    schema_version: str
    contract_version: str
    publication_identity_sha256: str
    bundle_sha256: str
    source_code_commit: str
    origin: dt.date
    outcome_cutoff: dt.datetime
    published_at: dt.datetime
    generated_at: dt.datetime | None
    referral_count: int
    horizons: list[int]
    admission_window_coverage: float
    source_run: SourceRun
    selection: ModelSelection
    calibration: Calibration
    estimate_tiers: dict[str, int]
    abstention_counts: dict[str, int]
    degeneracy: DegeneracyRule
    attention: AttentionRule
    limitations: list[str]
    matches_waiting_list: bool = Field(
        description="true when the active waiting list stands at the same origin, so the two can be read on one row"
    )


__all__ = [
    "HINDSIGHT_DISCLOSURE",
    "HORIZONS",
    "AbstentionReason",
    "AttentionRule",
    "Calibration",
    "CandidateDecision",
    "DegeneracyRule",
    "EstimateTier",
    "JourneyModel",
    "ModelSelection",
    "QueueReferralResponse",
    "ReferralEstimateResponse",
    "ReferralEstimateRow",
    "ReferralEstimatesBundle",
    "ReferralEstimatesPublicationResponse",
    "ReferralOrder",
    "ReliabilityBin",
    "SourceRun",
]
