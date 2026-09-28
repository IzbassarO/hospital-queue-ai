from __future__ import annotations

import datetime as dt
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator


class LabelContract(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_on_origin_is_known: bool
    outcomes_after_origin_are_censored: bool
    outcome_cutoff_is_exclusive: bool
    refusal_is_competing_terminal_event: bool
    same_day_min_duration_days: float = Field(gt=0)


class TimeGridConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    daily_start_day: int = Field(ge=0)
    daily_through_day: int = Field(gt=0)
    coarse_edges: tuple[int, ...]

    @model_validator(mode="after")
    def validate_edges(self) -> TimeGridConfig:
        if self.daily_start_day != 0:
            raise ValueError("the journey time grid must start at day zero")
        if tuple(sorted(set(self.coarse_edges))) != self.coarse_edges:
            raise ValueError("coarse_edges must be unique and increasing")
        if not self.coarse_edges or self.coarse_edges[0] <= self.daily_through_day:
            raise ValueError("coarse_edges must start after daily_through_day")
        return self


class SimilarHistoryConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    columns: tuple[str, ...]
    min_rows: int = Field(gt=0)

    @model_validator(mode="after")
    def validate_group(self) -> SimilarHistoryConfig:
        if self.columns != ("org_code", "profile_code"):
            raise ValueError("similar history is defined by hospital x profile")
        return self


class BaselineConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    hierarchy: tuple[tuple[str, ...], ...]
    min_rows: int = Field(gt=0)

    @model_validator(mode="after")
    def validate_hierarchy(self) -> BaselineConfig:
        expected = (
            ("org_code", "profile_code"),
            ("hospital_region_code", "profile_code"),
            ("profile_code",),
        )
        if self.hierarchy != expected:
            raise ValueError("baseline hierarchy must be hospital x profile, region x profile, then profile")
        return self


class AFTConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    max_depth: int = Field(gt=0)
    learning_rate: float = Field(gt=0)
    min_child_weight: float = Field(gt=0)
    distribution: str
    distribution_scale: float = Field(gt=0)
    max_rounds: int = Field(gt=0)

    @model_validator(mode="after")
    def validate_distribution(self) -> AFTConfig:
        if self.distribution not in {"normal", "logistic", "extreme"}:
            raise ValueError("unsupported AFT distribution")
        return self


class HazardConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    num_leaves: int = Field(gt=1)
    learning_rate: float = Field(gt=0)
    min_data_in_leaf: int = Field(gt=0)
    max_rounds: int = Field(gt=0)


class TrainingConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    validation_registration_start: dt.date
    threads: int = Field(gt=0)
    early_stopping_rounds: int = Field(gt=0)
    aft: AFTConfig
    competing_hazard: HazardConfig


class EvaluationConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reliability_bins: int = Field(gt=1)
    days_waited_buckets: tuple[int, ...]
    region_column: str
    admission_interval_coverage: float = Field(gt=0, lt=1)

    @model_validator(mode="after")
    def validate_evaluation(self) -> EvaluationConfig:
        if self.days_waited_buckets != (0, 1, 7, 14, 30, 60):
            raise ValueError("days-waited buckets must encode 0, 1-6, 7-13, 14-29, 30-59, 60+")
        if self.region_column != "hospital_region_code":
            raise ValueError("hospital-mode regional evaluation uses the hospital region")
        return self


class DecisionConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    metric: str
    max_days_waited_bucket_degradation: float = Field(ge=0)
    require_strict_overall_improvement: bool
    product_priority: tuple[str, ...]
    fallback: str

    @model_validator(mode="after")
    def validate_decision(self) -> DecisionConfig:
        if self.metric != "mean_admission_and_refusal_brier_at_7_14_30":
            raise ValueError("decision metric must remain the precommitted two-cause mean Brier")
        if not self.require_strict_overall_improvement:
            raise ValueError("the origin-journey decision requires strict overall improvement")
        if self.product_priority != ("discrete_competing_risk", "xgboost_aft"):
            raise ValueError("product priority must prefer the coherent competing-risk candidate")
        if self.fallback != "aalen_johansen":
            raise ValueError("Aalen-Johansen must be the product fallback")
        return self


class CitizenWaitConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: int = Field(ge=1)
    minimum_hospital_training_rows: int = Field(gt=0)
    suppression_justification: str = Field(min_length=1)
    admission_quantiles: tuple[float, ...]
    admission_quantile_estimand: str
    refusal_horizon_days: int = Field(gt=0)
    evaluation_registration_period: tuple[dt.date, dt.date]

    @model_validator(mode="after")
    def validate_citizen_wait(self) -> CitizenWaitConfig:
        if self.admission_quantiles != (0.5, 0.8):
            raise ValueError("citizen wait must publish the admission median and 80th percentile")
        if self.admission_quantile_estimand != "conditional_on_eventual_admission_within_observable_curve":
            raise ValueError("citizen wait quantiles must be conditional on eventual observed-curve admission")
        start, end = self.evaluation_registration_period
        if start > end:
            raise ValueError("citizen-wait evaluation period is reversed")
        return self


class GhostQueueConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: int = Field(ge=1)
    minimum_days_waited: int = Field(ge=0)
    admission_probability_horizon_days: int = Field(gt=0)
    admission_probability_threshold: float = Field(gt=0, lt=1)
    rule_reason_code: str = Field(pattern=r"^[a-z0-9_]+$")
    training_only_justification: str = Field(min_length=1)
    ranking_score_name: str = Field(pattern=r"^[a-z0-9_]+$")
    ranking_score_formula: str
    wait_maturity_days: int = Field(gt=0)
    minimum_comparable_at_risk_rows: int = Field(gt=0)
    degeneracy_tolerance: float = Field(gt=0, lt=1)
    yield_cutoffs: tuple[int, ...]
    recommended_history_months: int = Field(gt=0)
    ranking_justification: str = Field(min_length=1)

    @model_validator(mode="after")
    def validate_ghost_queue(self) -> GhostQueueConfig:
        if self.admission_probability_horizon_days != 90:
            raise ValueError("ghost-queue admission horizon must remain 90 days")
        if self.ranking_score_formula != "one_minus_p_admit_90d_x_wait_maturity_x_at_risk_support":
            raise ValueError("ghost-queue ranking formula changed")
        if self.wait_maturity_days != self.minimum_days_waited:
            raise ValueError("ranking wait maturity must match the audited legacy rule")
        if tuple(sorted(set(self.yield_cutoffs))) != self.yield_cutoffs:
            raise ValueError("ghost-queue yield cutoffs must be unique and increasing")
        if self.yield_cutoffs != (500, 1000, 2000, 5000, 13328):
            raise ValueError("ghost-queue yield cutoffs changed")
        if self.recommended_history_months != 21:
            raise ValueError("long-wait history recommendation must remain 21 months")
        return self


class OriginJourneyConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: int = Field(ge=1)
    seed: int = Field(ge=0)
    origin: dt.date
    history_start: dt.date
    outcome_cutoff: dt.datetime
    excluded_profile_codes: tuple[str, ...]
    horizons: tuple[int, ...]
    label_contract: LabelContract
    time_grid: TimeGridConfig
    similar_history: SimilarHistoryConfig
    baseline: BaselineConfig
    training: TrainingConfig
    evaluation: EvaluationConfig
    decision: DecisionConfig
    citizen_wait: CitizenWaitConfig
    ghost_queue: GhostQueueConfig

    @model_validator(mode="after")
    def validate_policy(self) -> OriginJourneyConfig:
        if self.history_start > self.origin:
            raise ValueError("history_start must not be after origin")
        if self.outcome_cutoff.tzinfo is not None:
            raise ValueError("outcome_cutoff must be a naive source-data timestamp")
        if self.outcome_cutoff.date() <= self.origin:
            raise ValueError("outcome_cutoff must be after origin")
        if tuple(sorted(set(self.excluded_profile_codes))) != self.excluded_profile_codes:
            raise ValueError("excluded_profile_codes must be unique and ordered")
        if tuple(sorted(set(self.horizons))) != self.horizons or any(day <= 0 for day in self.horizons):
            raise ValueError("horizons must be unique, increasing, positive days")
        if any(day > self.time_grid.daily_through_day for day in self.horizons):
            raise ValueError("operational horizons must lie on the daily part of the grid")
        if not self.history_start < self.training.validation_registration_start <= self.origin:
            raise ValueError("validation registration start must lie inside the as-of-origin history")
        if self.baseline.min_rows != self.similar_history.min_rows:
            raise ValueError("baseline and cohort support thresholds must agree")
        if self.citizen_wait.minimum_hospital_training_rows != self.baseline.min_rows:
            raise ValueError("citizen-wait suppression threshold must match the model support threshold")
        if self.citizen_wait.refusal_horizon_days not in self.horizons:
            raise ValueError("citizen-wait refusal horizon must be an evaluated model horizon")
        evaluation_start, _ = self.citizen_wait.evaluation_registration_period
        if evaluation_start <= self.origin:
            raise ValueError("citizen-wait hindsight evaluation must start after the origin")
        contract = self.label_contract
        if not (
            contract.event_on_origin_is_known
            and contract.outcomes_after_origin_are_censored
            and contract.outcome_cutoff_is_exclusive
            and contract.refusal_is_competing_terminal_event
        ):
            raise ValueError("origin journey requires the committed leakage and competing-risk contract")
        return self


def load_origin_journey_config(path: Path) -> OriginJourneyConfig:
    """Load and strictly validate the origin-specific cohort policy."""
    return OriginJourneyConfig(**yaml.safe_load(path.read_text(encoding="utf-8")))
