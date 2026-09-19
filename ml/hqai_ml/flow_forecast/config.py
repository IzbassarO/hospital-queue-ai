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
