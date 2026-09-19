from __future__ import annotations

import datetime as dt
import hashlib
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator


class BaselineConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    trailing_mean_days: int = Field(ge=1)
    trailing_median_days: int = Field(ge=1)
    recent_seasonal_periods: int = Field(ge=1)


class SupportConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    min_history_days: int = Field(ge=2)
    hospital_min_mean_registrations: float = Field(ge=0)
    region_parents_direct: bool
    national_from_region_aggregation: bool
    sparse_zero_rate: float = Field(ge=0, le=1)
    zero_heavy_zero_rate: float = Field(ge=0, le=1)

    @model_validator(mode="after")
    def ordered_sparsity(self) -> SupportConfig:
        if self.zero_heavy_zero_rate < self.sparse_zero_rate:
            raise ValueError("zero-heavy threshold must be at least the sparse threshold")
        return self


class ChallengerConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    source_config: str


class FlowForecastConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: int
    seed: int
    horizon: int = Field(ge=1)
    validation_origins: list[dt.date] = Field(min_length=2)
    final_test_origin: dt.date
    extrapolation_report_ratio_threshold: float = Field(gt=1)
    extrapolation_examples: int = Field(ge=1)
    baselines: BaselineConfig
    support: SupportConfig
    challenger: ChallengerConfig
    automatic_promotion: bool
    identity_sha256: str = ""

    @model_validator(mode="after")
    def validate_protocol(self) -> FlowForecastConfig:
        if self.validation_origins != sorted(set(self.validation_origins)):
            raise ValueError("validation origins must be unique and sorted")
        validation_end = self.validation_origins[-1] + dt.timedelta(days=self.horizon)
        test_start = self.final_test_origin + dt.timedelta(days=1)
        if validation_end >= test_start:
            raise ValueError("validation targets must end before the untouched final test starts")
        if self.automatic_promotion:
            raise ValueError("the evidence workflow cannot enable automatic promotion")
        return self


def load_flow_config(path: Path) -> FlowForecastConfig:
    raw = path.read_bytes()
    config = FlowForecastConfig(**yaml.safe_load(raw))
    return config.model_copy(update={"identity_sha256": hashlib.sha256(raw).hexdigest()})


class ResidualUncertaintyConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    method: str
    window_days: int = Field(ge=7)
    minimum_samples: int = Field(ge=3)


class QuantileChallengerConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    quantiles: list[float] = Field(min_length=3, max_length=3)
    rounds: int = Field(ge=1)
    scientific_evidence_variant: str
    serving_diagnostic_variant: str

    @model_validator(mode="after")
    def validate_quantiles(self) -> QuantileChallengerConfig:
        if self.quantiles != [0.1, 0.5, 0.9]:
            raise ValueError("flow quantiles must be exactly [0.1, 0.5, 0.9]")
        if self.scientific_evidence_variant != "raw":
            raise ValueError("raw predictions must be the primary scientific evidence")
        if self.serving_diagnostic_variant != "repaired_nonnegative_monotone":
            raise ValueError("serving diagnostic must explicitly repair non-negativity and monotonicity")
        return self


class FlowQuantileConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: int
    seed: int
    horizon: int = Field(ge=1)
    targets: list[str]
    validation_origins: list[dt.date] = Field(min_length=2)
    final_test_origin: dt.date
    extrapolation_report_ratio_threshold: float = Field(gt=1)
    extrapolation_examples: int = Field(ge=1)
    baselines: BaselineConfig
    support: SupportConfig
    residual_uncertainty: ResidualUncertaintyConfig
    challenger: QuantileChallengerConfig
    automatic_promotion: bool
    identity_sha256: str = ""

    @model_validator(mode="after")
    def validate_protocol(self) -> FlowQuantileConfig:
        if self.targets != ["registrations", "cohort_hospitalizations"]:
            raise ValueError("targets must preserve registrations and cohort_hospitalizations semantics")
        if self.validation_origins != sorted(set(self.validation_origins)):
            raise ValueError("validation origins must be unique and sorted")
        validation_end = self.validation_origins[-1] + dt.timedelta(days=self.horizon)
        test_start = self.final_test_origin + dt.timedelta(days=1)
        if validation_end >= test_start:
            raise ValueError("validation targets must end before the untouched final test starts")
        if self.automatic_promotion:
            raise ValueError("the quantile evidence workflow cannot enable automatic promotion")
        return self


def load_flow_quantile_config(path: Path) -> FlowQuantileConfig:
    raw = path.read_bytes()
    config = FlowQuantileConfig(**yaml.safe_load(raw))
    return config.model_copy(update={"identity_sha256": hashlib.sha256(raw).hexdigest()})


class TemporalCalibrationConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: int
    version: str
    seed: int
    nominal_coverage: float = Field(gt=0, lt=1)
    candidate: str
    source_variant: str
    methods: list[str]
    minimum_scores: int = Field(ge=1)
    minimum_unique_target_dates: int = Field(ge=1)
    fallback_ladder: list[str]
    targets: list[str]
    validation_origins: list[dt.date] = Field(min_length=2)
    final_test_origin: dt.date
    exclude_national_proxy: bool
    automatic_promotion: bool
    identity_sha256: str = ""

    @model_validator(mode="after")
    def validate_contract(self) -> TemporalCalibrationConfig:
        expected_methods = ["conformal_interval_expansion", "median_absolute_residual_baseline"]
        if self.methods != expected_methods:
            raise ValueError(f"calibration methods must be exactly {expected_methods}")
        expected_ladder = [
            "support_horizon_date_class",
            "support_horizon",
            "support_date_class",
            "support",
        ]
        if self.fallback_ladder != expected_ladder:
            raise ValueError(f"calibration fallback ladder must be exactly {expected_ladder}")
        if self.source_variant != "raw":
            raise ValueError("temporal calibration must consume unchanged raw quantile predictions")
        if self.targets != ["registrations", "cohort_hospitalizations"]:
            raise ValueError("calibration targets must preserve cohort_hospitalizations semantics")
        if self.validation_origins != sorted(set(self.validation_origins)):
            raise ValueError("validation origins must be unique and sorted")
        if not self.exclude_national_proxy:
            raise ValueError("national region-quantile-sum proxy cannot claim calibrated coverage")
        if self.automatic_promotion:
            raise ValueError("calibration evidence cannot enable automatic promotion")
        return self


def load_temporal_calibration_config(path: Path) -> TemporalCalibrationConfig:
    raw = path.read_bytes()
    config = TemporalCalibrationConfig(**yaml.safe_load(raw))
    return config.model_copy(update={"identity_sha256": hashlib.sha256(raw).hexdigest()})


class HierarchyFallbackConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    candidates: list[str]
    full_own_weight_nonzero_days: int = Field(ge=1)
    maximum_own_weight: float = Field(gt=0, lt=1)
    selection_metrics: list[str]

    @model_validator(mode="after")
    def validate_contract(self) -> HierarchyFallbackConfig:
        expected = ["current_region_profile_share", "support_weighted_parent_own_blend"]
        if self.candidates != expected:
            raise ValueError(f"fallback candidates must be exactly {expected}")
        if self.selection_metrics != ["wape", "mae_macro_series", "rmsse_macro_series"]:
            raise ValueError("fallback selection must use the precommitted WAPE/MAE/RMSSE order")
        return self


class FlowHierarchyConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: int
    version: str
    seed: int
    horizon: int = Field(ge=1)
    targets: list[str]
    validation_origins: list[dt.date] = Field(min_length=2)
    final_test_origin: dt.date
    source_candidate: str
    source_raw_variant: str
    source_central_variant: str
    calibration_method: str
    alternatives: list[str]
    hierarchy_selection_metrics: list[str]
    coherence_tolerance: float = Field(gt=0)
    material_change_absolute: float = Field(ge=0)
    material_change_relative: float = Field(ge=0)
    fallback: HierarchyFallbackConfig
    automatic_promotion: bool
    probabilistic_reconciliation_applied: bool
    identity_sha256: str = ""

    @model_validator(mode="after")
    def validate_contract(self) -> FlowHierarchyConfig:
        if self.targets != ["registrations", "cohort_hospitalizations"]:
            raise ValueError("hierarchy targets must preserve cohort_hospitalizations semantics")
        if self.validation_origins != sorted(set(self.validation_origins)):
            raise ValueError("hierarchy validation origins must be unique and sorted")
        if self.horizon != 14:
            raise ValueError("hierarchy preparation must preserve horizons 1..14")
        expected_alternatives = ["current_direct", "bottom_up_hospital", "parent_consistent_region_scaling"]
        if self.alternatives != expected_alternatives:
            raise ValueError(f"hierarchy alternatives must be exactly {expected_alternatives}")
        expected_metrics = [
            "hospital_wape",
            "region_wape",
            "national_wape",
            "hospital_mae_macro_series",
            "hospital_rmsse_macro_series",
        ]
        if self.hierarchy_selection_metrics != expected_metrics:
            raise ValueError(f"hierarchy selection metrics must be exactly {expected_metrics}")
        if self.source_raw_variant != "raw":
            raise ValueError("raw quantile evidence must be preserved")
        if self.source_central_variant != "repaired_nonnegative_monotone":
            raise ValueError("operational central input must use the accepted repaired p50 variant")
        if self.calibration_method != "conformal_interval_expansion":
            raise ValueError("hierarchy preparation must retain the accepted primary calibration method")
        if self.automatic_promotion:
            raise ValueError("hierarchy evidence cannot enable automatic promotion")
        if self.probabilistic_reconciliation_applied:
            raise ValueError("this step cannot claim probabilistic reconciliation")
        return self


def load_flow_hierarchy_config(path: Path) -> FlowHierarchyConfig:
    raw = path.read_bytes()
    config = FlowHierarchyConfig(**yaml.safe_load(raw))
    return config.model_copy(update={"identity_sha256": hashlib.sha256(raw).hexdigest()})


class HistoricalFlowThresholdConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    method: str
    quantile: float = Field(gt=0.5, lt=1)
    history_window_days: int = Field(ge=28)
    minimum_date_class_observations: int = Field(ge=2)
    minimum_date_class_positive_days: int = Field(ge=1)
    minimum_pooled_observations: int = Field(ge=7)
    minimum_pooled_positive_days: int = Field(ge=1)
    fallback_ladder: list[str]
    event_comparison: str

    @model_validator(mode="after")
    def validate_contract(self) -> HistoricalFlowThresholdConfig:
        expected = ["hospital_date_class", "hospital_pooled", "region_date_class", "region_pooled"]
        if self.fallback_ladder != expected:
            raise ValueError(f"threshold fallback ladder must be exactly {expected}")
        if self.method != "origin_legal_empirical_quantile_higher":
            raise ValueError("only the transparent empirical-quantile threshold is supported")
        if self.event_comparison != "actual_strictly_greater_than_threshold":
            raise ValueError("retrospective high-flow events must strictly exceed the threshold")
        return self


class FlowAnomalyConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    method: str
    target: str
    lookback_days: int = Field(ge=21)
    minimum_residuals: int = Field(ge=5)
    robust_z_threshold: float = Field(gt=0)

    @model_validator(mode="after")
    def validate_contract(self) -> FlowAnomalyConfig:
        if self.method != "weekly_residual_median_mad":
            raise ValueError("only the transparent weekly-residual MAD detector is supported")
        if self.target != "registrations":
            raise ValueError("the anomaly companion currently supports registrations only")
        return self


class FlowPressureConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: int
    version: str
    seed: int
    threshold_semantics: str
    compatible_future_threshold_semantics: str
    primary_target: str
    secondary_target: str
    horizon: int = Field(ge=1)
    validation_origins: list[dt.date] = Field(min_length=2)
    final_test_origin: dt.date
    severity_order: list[str]
    threshold: HistoricalFlowThresholdConfig
    anomaly: FlowAnomalyConfig
    automatic_promotion: bool
    autonomous_action: bool
    identity_sha256: str = ""

    @model_validator(mode="after")
    def validate_contract(self) -> FlowPressureConfig:
        if self.threshold_semantics != "historical_flow_proxy_v1":
            raise ValueError("current pressure evidence must use historical_flow_proxy_v1")
        if self.compatible_future_threshold_semantics != "physical_capacity_provider_v1":
            raise ValueError("future provider contract must remain physical_capacity_provider_v1")
        if self.primary_target != "registrations" or self.secondary_target != "cohort_hospitalizations":
            raise ValueError("pressure targets must preserve registrations and cohort semantics")
        if self.horizon != 14:
            raise ValueError("pressure preparation must preserve horizons 1..14")
        if self.validation_origins != sorted(set(self.validation_origins)):
            raise ValueError("pressure validation origins must be unique and sorted")
        if self.severity_order != ["NORMAL", "WATCH", "ELEVATED", "HIGH"]:
            raise ValueError("severity order must be NORMAL, WATCH, ELEVATED, HIGH")
        if self.automatic_promotion or self.autonomous_action:
            raise ValueError("pressure signals cannot promote models or trigger autonomous action")
        return self


def load_flow_pressure_config(path: Path) -> FlowPressureConfig:
    raw = path.read_bytes()
    config = FlowPressureConfig(**yaml.safe_load(raw))
    return config.model_copy(update={"identity_sha256": hashlib.sha256(raw).hexdigest()})


class SignalPrioritizationConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: int
    version: str
    seed: int
    source_signal_contract_version: str
    source_alert_unit: str
    primary_target: str
    secondary_target: str
    materiality_floor_expected_count: float = Field(gt=0)
    alert_severities: list[str]
    ranking_order: list[str]
    demo_top_n: int = Field(ge=1, le=100)
    regional_top_profiles: int = Field(ge=1, le=20)
    human_review_required: bool
    autonomous_action: bool
    automatic_promotion: bool
    identity_sha256: str = ""

    @model_validator(mode="after")
    def validate_contract(self) -> SignalPrioritizationConfig:
        if self.source_signal_contract_version != "preventive-flow-pressure-v1":
            raise ValueError("Signals Inbox requires the corrected preventive-flow-pressure-v1 contract")
        if self.source_alert_unit != "hospital_profile_target_origin":
            raise ValueError("Signals Inbox must consume entity/origin signals, not daily cells")
        if self.primary_target != "registrations" or self.secondary_target != "cohort_hospitalizations":
            raise ValueError("Signals Inbox must keep registrations primary and cohort evidence secondary")
        if self.materiality_floor_expected_count != 1.0:
            raise ValueError("the fixed product materiality floor must be exactly 1.0 expected count/day")
        if self.alert_severities != ["HIGH", "ELEVATED", "WATCH"]:
            raise ValueError("alert severity precedence must be HIGH, ELEVATED, WATCH")
        expected_ranking = [
            "severity_desc",
            "lead_time_days_asc",
            "direct_supported_first",
            "calibrated_uncertainty_first",
            "valid_central_threshold_ratio_desc",
            "region_id_asc",
            "hospital_id_asc",
            "profile_id_asc",
            "series_id_asc",
        ]
        if self.ranking_order != expected_ranking:
            raise ValueError(f"ranking order must be exactly {expected_ranking}")
        if not self.human_review_required or self.autonomous_action or self.automatic_promotion:
            raise ValueError("Signals Inbox is human-review-only and cannot act or promote automatically")
        return self


def load_signal_prioritization_config(path: Path) -> SignalPrioritizationConfig:
    raw = path.read_bytes()
    config = SignalPrioritizationConfig(**yaml.safe_load(raw))
    return config.model_copy(update={"identity_sha256": hashlib.sha256(raw).hexdigest()})
