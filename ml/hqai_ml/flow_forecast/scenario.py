"""Deterministic, non-causal forecast stress tests for accepted registration forecasts."""

from __future__ import annotations

import datetime as dt
import hashlib
import json
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from hqai_ml.flow_forecast.config import FlowPressureConfig, SignalPrioritizationConfig
from hqai_ml.flow_forecast.pressure import (
    ALERT_SEVERITIES,
    aggregate_pressure_signals,
    severity_for_row,
)
from hqai_ml.flow_forecast.prioritization import prepare_inbox
from hqai_ml.registry import store

SCENARIO_TARGET = "registrations"
SECONDARY_TARGET = "cohort_hospitalizations"
SCENARIO_RANGE_METHOD = "additive_central_shift_v1"
SCENARIO_RANGE_STATUS = "TRANSFORMED_BASELINE_UNCERTAINTY_RANGE"
SCENARIO_RANGE_UNAVAILABLE = "UNAVAILABLE"
SCENARIO_RANGE_NOT_ADJUSTED = "NOT_SCENARIO_ADJUSTED"
SCENARIO_RANGE_REASON_UNAVAILABLE = "SCENARIO_SENSITIVITY_RANGE_UNAVAILABLE"
EDGE_POLICY = "shift_within_selected_horizon_window_zero_fill_no_wrap_no_redistribution"
# Accepted operator wording that quotes a calibrated bound, and its scenario replacement. Under a
# scenario the quoted bound is a transformed sensitivity bound, so the calibrated wording is illegal.
SCENARIO_EXPLANATION_REWRITES = {
    "Calibrated lower forecast bound": "Derived scenario sensitivity lower bound",
    "Calibrated upper forecast bound": "Derived scenario sensitivity upper bound",
}
# Spec fields that are audit metadata only. They must never change the scientific identity.
SPEC_AUDIT_ONLY_FIELDS = ("created_at",)
ALLOCATION_HEURISTIC = "proportional_to_baseline_central_heuristic"
FLOAT_TOLERANCE = 1e-9
REVERSIBILITY_NOTE = (
    "multipliers above zero and transfers are algebraically reversible; edge-losing time shifts are not"
)

# Identity-gate comparisons are explicit (scenario public field, accepted artifact field) pairs because
# scenario artifacts deliberately publish scenario-scoped names instead of accepted calibrated names.
SCIENTIFIC_DAILY_FIELD_PAIRS = [
    ("scenario_central", "forecast_value"),
    ("scenario_sensitivity_lower", "uncertainty_lower"),
    ("scenario_sensitivity_upper", "uncertainty_upper"),
    ("severity", "severity"),
    ("threshold_value", "threshold_value"),
    ("threshold_status", "threshold_status"),
    ("source_reason_code", "source_reason_code"),
]
SCIENTIFIC_ENTITY_FIELD_PAIRS = [
    ("severity", "severity"),
    ("max_severity_7d", "max_severity_7d"),
    ("max_severity_14d", "max_severity_14d"),
    ("first_crossing_date", "first_crossing_date"),
    ("first_crossing_severity", "first_crossing_severity"),
    ("lead_time_days", "lead_time_days"),
    ("any_alert_7d", "any_alert_7d"),
    ("any_alert_14d", "any_alert_14d"),
    ("severity_evidence_horizon", "severity_evidence_horizon"),
    ("severity_evidence_date", "severity_evidence_date"),
    ("scenario_central", "forecast_value"),
    ("threshold_value", "threshold_value"),
    ("scenario_sensitivity_lower", "uncertainty_lower"),
    ("scenario_sensitivity_upper", "uncertainty_upper"),
    ("source_reason_code", "source_reason_code"),
]
SCIENTIFIC_INBOX_FIELD_PAIRS = [
    ("source_severity", "source_severity"),
    ("first_crossing_date", "first_crossing_date"),
    ("lead_time_days", "lead_time_days"),
    ("materiality_status", "materiality_status"),
    ("operational_priority_status", "operational_priority_status"),
    ("priority_support_class", "priority_support_class"),
    ("inbox_rank", "inbox_rank"),
]
# Retrospective labels inherited from the accepted evaluation baseline. They describe observed history,
# never scenario predictions, and a future serving adapter must strip them.
RETROSPECTIVE_EVALUATION_LABELS = [
    "phase",
    "y",
    "actual_exceeds_threshold",
    "actual_event_within_7d",
    "actual_event_within_14d",
    "evaluation_supported_7d",
    "evaluation_supported_14d",
]
# Accepted pressure/prioritization helpers require these legacy working names. They are private
# compatibility columns and must never appear in a published scenario artifact.
PRIVATE_COMPATIBILITY_COLUMNS = [
    "forecast_value",
    "uncertainty_lower",
    "uncertainty_upper",
    "uncertainty_status",
    "calibration_status",
    "calibration_version",
    "level_local_interval_80_lower",
    "level_local_interval_80_upper",
]


class ScenarioClassification(StrEnum):
    SAFE_NON_CAUSAL_STRESS_TEST = "SAFE_NON_CAUSAL_STRESS_TEST"
    MECHANISTIC_ACCOUNTING_SCENARIO = "MECHANISTIC_ACCOUNTING_SCENARIO"
    REQUIRES_CAUSAL_IDENTIFICATION = "REQUIRES_CAUSAL_IDENTIFICATION"
    REQUIRES_MISSING_CAPACITY_DATA = "REQUIRES_MISSING_CAPACITY_DATA"
    NOT_SUPPORTED = "NOT_SUPPORTED"


class ScenarioType(StrEnum):
    IDENTITY = "identity"
    DEMAND_MULTIPLIER = "demand_multiplier"
    PROFILE_SURGE = "profile_surge"
    INFLOW_TRANSFER = "inflow_transfer"
    TIME_SHIFT = "time_shift"


class ScopeType(StrEnum):
    ALL_HOSPITALS = "all_hospitals"
    HOSPITAL_PROFILE = "hospital_profile"
    REGION_PROFILE = "region_profile"
    PROFILE = "profile"


class ScenarioContractError(ValueError):
    """Machine-readable scenario contract failure."""

    def __init__(self, code: str, reason: str):
        self.code = code
        self.reason = reason
        super().__init__(f"{code}: {reason}")

    def as_dict(self) -> dict[str, str]:
        return {"code": self.code, "reason": self.reason}


class BaselineProvenance(BaseModel):
    model_config = ConfigDict(extra="forbid")

    hierarchy_run_id: str
    pressure_run_id: str
    prioritization_run_id: str
    execution_mode: str = "EVALUATION"

    @model_validator(mode="after")
    def validate_mode(self) -> BaselineProvenance:
        if self.execution_mode != "EVALUATION":
            raise ValueError("scenario v1 supports retrospective EVALUATION mode only")
        return self


class ScenarioScope(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scope_type: ScopeType = ScopeType.ALL_HOSPITALS
    hospital_id: str | None = None
    region_id: str | None = None
    profile_id: str | None = None
    horizon_start: int = Field(default=1, ge=1, le=14)
    horizon_end: int = Field(default=14, ge=1, le=14)

    @model_validator(mode="after")
    def validate_scope(self) -> ScenarioScope:
        if self.horizon_start > self.horizon_end:
            raise ValueError("horizon_start must not exceed horizon_end")
        required = {
            ScopeType.ALL_HOSPITALS: (),
            ScopeType.HOSPITAL_PROFILE: ("hospital_id", "profile_id"),
            ScopeType.REGION_PROFILE: ("region_id", "profile_id"),
            ScopeType.PROFILE: ("profile_id",),
        }[self.scope_type]
        missing = [name for name in required if getattr(self, name) is None]
        if missing:
            raise ValueError(f"{self.scope_type.value} scope requires {missing}")
        allowed = {
            ScopeType.ALL_HOSPITALS: set(),
            ScopeType.HOSPITAL_PROFILE: {"hospital_id", "profile_id"},
            ScopeType.REGION_PROFILE: {"region_id", "profile_id"},
            ScopeType.PROFILE: {"profile_id"},
        }[self.scope_type]
        supplied = {name for name in ("hospital_id", "region_id", "profile_id") if getattr(self, name) is not None}
        unexpected = sorted(supplied - allowed)
        if unexpected:
            raise ValueError(f"{self.scope_type.value} scope cannot carry ignored filters {unexpected}")
        return self


class ScenarioLever(BaseModel):
    model_config = ConfigDict(extra="forbid")

    lever_type: str
    classification: ScenarioClassification
    scope: ScenarioScope = Field(default_factory=ScenarioScope)
    parameters: dict[str, Any] = Field(default_factory=dict)


class ScenarioSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scenario_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
    scenario_version: str
    scenario_type: str
    classification: ScenarioClassification
    baseline_provenance: BaselineProvenance
    scope: ScenarioScope = Field(default_factory=ScenarioScope)
    parameters: dict[str, Any] = Field(default_factory=dict)
    levers: list[ScenarioLever] = Field(default_factory=list)
    created_at: dt.datetime

    @model_validator(mode="after")
    def normalize_single_lever(self) -> ScenarioSpec:
        if self.levers and self.scenario_type == "composite":
            if self.parameters:
                raise ValueError("composite specs must keep top-level parameters empty")
        elif self.levers:
            expected = ScenarioLever(
                lever_type=self.scenario_type,
                classification=self.classification,
                scope=self.scope,
                parameters=self.parameters,
            )
            if len(self.levers) != 1 or self.levers[0] != expected:
                raise ValueError("non-composite specs may contain only their redundant normalized lever")
        else:
            self.levers = [
                ScenarioLever(
                    lever_type=self.scenario_type,
                    classification=self.classification,
                    scope=self.scope,
                    parameters=self.parameters,
                )
            ]
        return self


class StandardScenarioConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scenario_id: str
    scenario_type: str
    classification: ScenarioClassification
    scope: ScenarioScope
    parameters: dict[str, Any]
    created_at: dt.datetime


class FlowScenarioConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: int
    scenario_contract_version: str
    target: str
    source_hierarchy_run: str
    source_pressure_run: str
    source_prioritization_run: str
    allowed_levers: list[str]
    classification_mapping: dict[str, ScenarioClassification]
    default_demand_stress_levels: list[float]
    uncertainty_transform: str
    range_semantics: str
    coverage_guarantee: bool
    hierarchy_method: str
    parent_allocation_method: str
    materiality_config_reference: str
    standard_scenarios: list[StandardScenarioConfig]
    identity_sha256: str = ""

    @model_validator(mode="after")
    def validate_contract(self) -> FlowScenarioConfig:
        if self.target != SCENARIO_TARGET:
            raise ValueError("scenario v1 target must be registrations")
        if self.uncertainty_transform != SCENARIO_RANGE_METHOD:
            raise ValueError(f"scenario uncertainty transform must be {SCENARIO_RANGE_METHOD}")
        if self.range_semantics != "derived_sensitivity_range_not_recalibrated":
            raise ValueError("scenario range semantics must explicitly say it is not recalibrated")
        if self.coverage_guarantee:
            raise ValueError("scenario sensitivity ranges cannot claim coverage")
        if self.hierarchy_method != "bottom_up_hospital_exact_central":
            raise ValueError("scenario hierarchy must be exact bottom-up hospital central aggregation")
        if self.parent_allocation_method != ALLOCATION_HEURISTIC:
            raise ValueError(f"parent allocation method must be {ALLOCATION_HEURISTIC}")
        if self.default_demand_stress_levels != [0.9, 1.1, 1.2]:
            raise ValueError("reviewed default demand stress levels must remain [0.9, 1.1, 1.2]")
        expected = {item.value for item in ScenarioType}
        if set(self.allowed_levers) != expected:
            raise ValueError(f"allowed_levers must be exactly {sorted(expected)}")
        if set(self.classification_mapping) != expected:
            raise ValueError("classification_mapping must cover every allowed lever")
        configured_multipliers = [
            float(item.parameters["multiplier"])
            for item in self.standard_scenarios
            if item.scenario_type == ScenarioType.DEMAND_MULTIPLIER.value
        ]
        if configured_multipliers != self.default_demand_stress_levels:
            raise ValueError("default_demand_stress_levels must exactly match standard demand-multiplier scenarios")
        return self


@dataclass(frozen=True)
class ScenarioEvaluation:
    spec: ScenarioSpec
    daily_cells: pd.DataFrame
    hierarchy_cells: pd.DataFrame
    entity_signals: pd.DataFrame
    inbox: pd.DataFrame
    baseline_inbox: pd.DataFrame
    unsupported: pd.DataFrame
    low_volume_attention: pd.DataFrame
    secondary_context: pd.DataFrame
    daily_differences: pd.DataFrame
    entity_differences: pd.DataFrame
    validation: dict[str, Any]
    metadata: dict[str, Any]


def load_flow_scenario_config(path: Path) -> FlowScenarioConfig:
    raw = path.read_bytes()
    config = FlowScenarioConfig(**yaml.safe_load(raw))
    return config.model_copy(update={"identity_sha256": hashlib.sha256(raw).hexdigest()})


def scenario_specs_from_config(config: FlowScenarioConfig) -> list[ScenarioSpec]:
    provenance = BaselineProvenance(
        hierarchy_run_id=config.source_hierarchy_run,
        pressure_run_id=config.source_pressure_run,
        prioritization_run_id=config.source_prioritization_run,
    )
    return [
        ScenarioSpec(
            scenario_id=item.scenario_id,
            scenario_version=config.scenario_contract_version,
            scenario_type=item.scenario_type,
            classification=item.classification,
            baseline_provenance=provenance,
            scope=item.scope,
            parameters=item.parameters,
            created_at=item.created_at,
        )
        for item in config.standard_scenarios
    ]


def _unsupported(reason: str) -> None:
    raise ScenarioContractError("LEVER_UNSUPPORTED", reason)


def validate_executable_spec(spec: ScenarioSpec) -> None:
    if spec.scenario_type == "composite" or len(spec.levers) != 1:
        raise ScenarioContractError(
            "COMPOSITE_NOT_SUPPORTED_V1",
            "scenario v1 executes exactly one reviewed lever; ordered composite semantics are unsupported",
        )


def _validate_lever(lever: ScenarioLever) -> ScenarioType:
    if lever.classification not in {
        ScenarioClassification.SAFE_NON_CAUSAL_STRESS_TEST,
        ScenarioClassification.MECHANISTIC_ACCOUNTING_SCENARIO,
    }:
        _unsupported(f"classification {lever.classification.value} is not executable")
    try:
        kind = ScenarioType(lever.lever_type)
    except ValueError:
        _unsupported(f"lever {lever.lever_type!r} is not supported by scenario contract v1")
    expected = {
        ScenarioType.IDENTITY: ScenarioClassification.SAFE_NON_CAUSAL_STRESS_TEST,
        ScenarioType.DEMAND_MULTIPLIER: ScenarioClassification.SAFE_NON_CAUSAL_STRESS_TEST,
        ScenarioType.PROFILE_SURGE: ScenarioClassification.SAFE_NON_CAUSAL_STRESS_TEST,
        ScenarioType.INFLOW_TRANSFER: ScenarioClassification.MECHANISTIC_ACCOUNTING_SCENARIO,
        ScenarioType.TIME_SHIFT: ScenarioClassification.SAFE_NON_CAUSAL_STRESS_TEST,
    }[kind]
    if lever.classification != expected:
        _unsupported(f"lever {kind.value!r} requires classification {expected.value}")
    allowed_parameters = {
        ScenarioType.IDENTITY: set(),
        ScenarioType.DEMAND_MULTIPLIER: {"multiplier"},
        ScenarioType.PROFILE_SURGE: {"multiplier"},
        ScenarioType.INFLOW_TRANSFER: {
            "source_hospital_id",
            "destination_hospital_id",
            "fraction",
            "source_profile_id",
            "destination_profile_id",
        },
        ScenarioType.TIME_SHIFT: {"days"},
    }[kind]
    unexpected = sorted(set(lever.parameters) - allowed_parameters)
    if unexpected:
        raise ScenarioContractError(
            "INVALID_LEVER_PARAMETERS", f"lever {kind.value!r} has ignored/unknown parameters: {unexpected}"
        )
    return kind


def _require_columns(frame: pd.DataFrame, columns: set[str], name: str) -> None:
    missing = sorted(columns - set(frame.columns))
    if missing:
        raise ValueError(f"{name} is missing required columns: {missing}")


def _scope_mask(frame: pd.DataFrame, scope: ScenarioScope) -> pd.Series:
    mask = (
        frame["target"].eq(SCENARIO_TARGET)
        & frame["horizon"].between(scope.horizon_start, scope.horizon_end)
        & frame["level"].eq("hospital")
    )
    if scope.scope_type == ScopeType.HOSPITAL_PROFILE:
        mask &= frame["hospital_id"].eq(scope.hospital_id) & frame["profile_id"].eq(scope.profile_id)
    elif scope.scope_type == ScopeType.REGION_PROFILE:
        mask &= frame["region_id"].eq(scope.region_id) & frame["profile_id"].eq(scope.profile_id)
    elif scope.scope_type == ScopeType.PROFILE:
        mask &= frame["profile_id"].eq(scope.profile_id)
    return mask


def _demand_multiplier(frame: pd.DataFrame, lever: ScenarioLever, kind: ScenarioType) -> dict[str, Any]:
    raw_multiplier = lever.parameters.get("multiplier")
    if isinstance(raw_multiplier, (bool, np.bool_)):
        raise ScenarioContractError("INVALID_MULTIPLIER", "demand multiplier must be numeric and cannot be boolean")
    try:
        multiplier = float(raw_multiplier)
    except (KeyError, TypeError, ValueError) as exc:
        raise ScenarioContractError(
            "INVALID_MULTIPLIER", "demand multiplier requires numeric parameter 'multiplier'"
        ) from exc
    if not np.isfinite(multiplier) or multiplier < 0:
        raise ScenarioContractError("INVALID_MULTIPLIER", "demand multiplier must be finite and >= 0")
    if kind == ScenarioType.PROFILE_SURGE and lever.scope.scope_type != ScopeType.REGION_PROFILE:
        raise ScenarioContractError("INVALID_SCOPE", "profile_surge requires region_profile scope")
    mask = _scope_mask(frame, lever.scope)
    if not mask.any():
        raise ScenarioContractError("INVALID_SCOPE", "scenario scope selects no registration forecast cells")
    before = frame.loc[mask, "scenario_central"].to_numpy(float)
    parent_scoped = lever.scope.scope_type in {
        ScopeType.ALL_HOSPITALS,
        ScopeType.REGION_PROFILE,
        ScopeType.PROFILE,
    }
    if parent_scoped and multiplier != 1.0 and float(before.sum()) <= FLOAT_TOLERANCE:
        raise ScenarioContractError(
            "ALLOCATION_WITHOUT_SUPPORT",
            "all eligible child baseline central values are zero; parent change cannot be allocated",
        )
    frame.loc[mask, "scenario_central"] = before * multiplier
    return {
        "lever_type": kind.value,
        "multiplier": multiplier,
        "affected_cells": int(mask.sum()),
        "baseline_total": float(before.sum()),
        "scenario_total": float(frame.loc[mask, "scenario_central"].sum()),
        "allocation_method": ALLOCATION_HEURISTIC if parent_scoped else "direct_hospital_cell_transform",
        "allocation_is_heuristic": parent_scoped,
        "causal_effect_claimed": False,
    }


def _inflow_transfer(frame: pd.DataFrame, lever: ScenarioLever) -> dict[str, Any]:
    if lever.scope.profile_id is None:
        raise ScenarioContractError("INVALID_SCOPE", "inflow_transfer requires a profile-constrained scope")
    source = str(lever.parameters.get("source_hospital_id", ""))
    destination = str(lever.parameters.get("destination_hospital_id", ""))
    source_profile = str(lever.parameters.get("source_profile_id", lever.scope.profile_id))
    destination_profile = str(lever.parameters.get("destination_profile_id", lever.scope.profile_id))
    if source_profile != destination_profile or source_profile != lever.scope.profile_id:
        raise ScenarioContractError("INVALID_SCOPE", "inflow transfer cannot cross profiles")
    if not source or not destination or source == destination:
        raise ScenarioContractError(
            "INVALID_SCOPE", "inflow transfer requires distinct source_hospital_id and destination_hospital_id"
        )
    raw_fraction = lever.parameters.get("fraction")
    if isinstance(raw_fraction, (bool, np.bool_)):
        raise ScenarioContractError("INVALID_TRANSFER_FRACTION", "inflow transfer fraction cannot be boolean")
    try:
        fraction = float(raw_fraction)
    except (KeyError, TypeError, ValueError) as exc:
        raise ScenarioContractError(
            "INVALID_TRANSFER_FRACTION", "inflow transfer requires numeric parameter 'fraction'"
        ) from exc
    if not np.isfinite(fraction) or not 0 <= fraction <= 1:
        raise ScenarioContractError("INVALID_TRANSFER_FRACTION", "inflow transfer fraction must be in [0,1]")
    scope_mask = _scope_mask(frame, lever.scope)
    source_mask = scope_mask & frame["hospital_id"].eq(source)
    destination_mask = scope_mask & frame["hospital_id"].eq(destination)
    if not source_mask.any() or not destination_mask.any():
        raise ScenarioContractError(
            "INVALID_SCOPE", "transfer source and destination must both exist in every selected scope"
        )
    pair_keys = ["phase", "origin", "target", "horizon", "target_date", "profile_id"]
    donors = frame.loc[source_mask, pair_keys + ["scenario_central"]].copy().sort_values(pair_keys)
    receivers = frame.loc[destination_mask, pair_keys + ["scenario_central"]].copy().sort_values(pair_keys)
    if donors.duplicated(pair_keys).any() or receivers.duplicated(pair_keys).any():
        raise ScenarioContractError("INVALID_TRANSFER_ALIGNMENT", "transfer hospital/profile cells are not unique")
    donor_keys = pd.MultiIndex.from_frame(donors[pair_keys])
    receiver_keys = pd.MultiIndex.from_frame(receivers[pair_keys])
    if not donor_keys.equals(receiver_keys):
        raise ScenarioContractError(
            "INVALID_TRANSFER_ALIGNMENT", "transfer source and destination cells are not aligned"
        )
    moved = donors["scenario_central"].to_numpy(float) * fraction
    total_before = float(donors["scenario_central"].sum() + receivers["scenario_central"].sum())
    frame.loc[donors.index, "scenario_central"] = donors["scenario_central"].to_numpy(float) - moved
    frame.loc[receivers.index, "scenario_central"] = receivers["scenario_central"].to_numpy(float) + moved
    total_after = float(
        frame.loc[source_mask, "scenario_central"].sum() + frame.loc[destination_mask, "scenario_central"].sum()
    )
    if not np.isclose(total_before, total_after, atol=FLOAT_TOLERANCE, rtol=0):
        raise RuntimeError("inflow transfer did not conserve profile/date central")
    return {
        "lever_type": ScenarioType.INFLOW_TRANSFER.value,
        "source_hospital_id": source,
        "destination_hospital_id": destination,
        "profile_id": lever.scope.profile_id,
        "fraction": fraction,
        "transferred_total": float(moved.sum()),
        "conservation_error": abs(total_after - total_before),
        "feasibility": "UNKNOWN",
        "capacity_checked": False,
        "causal_effect_claimed": False,
    }


def _time_shift(frame: pd.DataFrame, lever: ScenarioLever) -> dict[str, Any]:
    try:
        raw_days = lever.parameters["days"]
        days = int(raw_days)
    except (KeyError, TypeError, ValueError) as exc:
        raise ScenarioContractError("INVALID_TIME_SHIFT", "time_shift requires integer parameter 'days'") from exc
    if isinstance(raw_days, bool) or float(raw_days) != days:
        raise ScenarioContractError("INVALID_TIME_SHIFT", "time_shift requires integer parameter 'days'")
    window_length = lever.scope.horizon_end - lever.scope.horizon_start + 1
    if abs(days) >= window_length:
        raise ScenarioContractError(
            "INVALID_TIME_SHIFT",
            f"absolute time shift must be smaller than selected horizon window length {window_length}",
        )
    if days == 0:
        return {
            "lever_type": ScenarioType.TIME_SHIFT.value,
            "days": 0,
            "edge_mass_lost": 0.0,
            "edge_mass_gained": 0.0,
            "edge_handling": EDGE_POLICY,
            "causal_effect_claimed": False,
        }
    mask = _scope_mask(frame, lever.scope)
    if not mask.any():
        raise ScenarioContractError("INVALID_SCOPE", "time-shift scope selects no registration forecast cells")
    group_keys = ["phase", "origin", "series_id", "target", "hospital_id", "profile_id"]
    selected = frame.loc[mask].sort_values([*group_keys, "horizon"])
    edge_mass_lost = 0.0
    for _, part in selected.groupby(group_keys, sort=True, observed=True):
        horizons = part["horizon"].astype(int).tolist()
        expected = list(range(lever.scope.horizon_start, lever.scope.horizon_end + 1))
        if horizons != expected:
            raise ScenarioContractError(
                "INVALID_TIME_SHIFT", "time shift requires a complete selected horizon window per series"
            )
        original = part["scenario_central"].to_numpy(float)
        shifted = np.zeros_like(original)
        for index, value in enumerate(original):
            destination = index + days
            if 0 <= destination < len(original):
                shifted[destination] += value
            else:
                edge_mass_lost += float(value)
        frame.loc[part.index, "scenario_central"] = shifted
    return {
        "lever_type": ScenarioType.TIME_SHIFT.value,
        "days": days,
        "direction": "delay" if days > 0 else "advance",
        "affected_cells": int(mask.sum()),
        "edge_mass_lost": edge_mass_lost,
        "edge_mass_gained": 0.0,
        "edge_handling": EDGE_POLICY,
        "causal_effect_claimed": False,
    }


def apply_scenario_levers(baseline_daily: pd.DataFrame, spec: ScenarioSpec) -> tuple[pd.DataFrame, list[dict]]:
    """Apply deterministic hospital-level registration levers without mutating the baseline."""
    validate_executable_spec(spec)
    _require_columns(
        baseline_daily,
        {
            "phase",
            "origin",
            "target",
            "level",
            "series_id",
            "horizon",
            "target_date",
            "hospital_id",
            "region_id",
            "profile_id",
            "forecast_value",
        },
        "baseline daily pressure frame",
    )
    frame = baseline_daily.copy(deep=True)
    frame["baseline_central"] = frame["forecast_value"].astype(float)
    frame["scenario_central"] = frame["baseline_central"]
    baseline_names = {
        "uncertainty_lower": "baseline_uncertainty_lower",
        "uncertainty_upper": "baseline_uncertainty_upper",
        "uncertainty_status": "baseline_uncertainty_status",
        "calibration_status": "baseline_calibration_status",
        "calibration_version": "baseline_calibration_version",
        "level_local_interval_80_lower": "baseline_level_local_interval_80_lower",
        "level_local_interval_80_upper": "baseline_level_local_interval_80_upper",
    }
    frame = frame.rename(columns={key: value for key, value in baseline_names.items() if key in frame.columns})
    frame = frame.drop(columns=["forecast_value"])
    metadata = []
    for lever in spec.levers:
        kind = _validate_lever(lever)
        if kind == ScenarioType.IDENTITY:
            metadata.append({"lever_type": kind.value, "affected_cells": 0, "causal_effect_claimed": False})
        elif kind in {ScenarioType.DEMAND_MULTIPLIER, ScenarioType.PROFILE_SURGE}:
            metadata.append(_demand_multiplier(frame, lever, kind))
        elif kind == ScenarioType.INFLOW_TRANSFER:
            metadata.append(_inflow_transfer(frame, lever))
        elif kind == ScenarioType.TIME_SHIFT:
            metadata.append(_time_shift(frame, lever))
    if (frame["scenario_central"] < -FLOAT_TOLERANCE).any():
        raise RuntimeError("scenario produced a negative registration central value")
    frame["scenario_central"] = frame["scenario_central"].clip(lower=0)
    unchanged_secondary = frame["target"].eq(SECONDARY_TARGET)
    if not np.array_equal(
        frame.loc[unchanged_secondary, "scenario_central"].to_numpy(),
        frame.loc[unchanged_secondary, "baseline_central"].to_numpy(),
    ):
        raise RuntimeError("scenario changed cohort_hospitalizations")
    return frame, metadata


def transform_sensitivity_range(frame: pd.DataFrame) -> pd.DataFrame:
    """Derive a non-calibrated sensitivity range by shifting usable baseline bounds with central."""
    result = frame.copy(deep=True)
    _require_columns(
        result,
        {"baseline_uncertainty_lower", "baseline_uncertainty_upper", "baseline_uncertainty_status"},
        "scenario frame",
    )
    baseline_usable = (
        result["baseline_uncertainty_status"].eq("level_local_calibrated")
        & np.isfinite(result["baseline_uncertainty_lower"])
        & np.isfinite(result["baseline_uncertainty_upper"])
    )
    scenario_target = result["target"].eq(SCENARIO_TARGET)
    usable = baseline_usable & scenario_target
    secondary_context = result["target"].eq(SECONDARY_TARGET)
    delta = result["scenario_central"] - result["baseline_central"]
    lower = np.maximum(0.0, result["baseline_uncertainty_lower"] + delta)
    upper = np.maximum(lower, result["baseline_uncertainty_upper"] + delta)
    result["scenario_sensitivity_lower"] = lower.where(usable)
    result["scenario_sensitivity_upper"] = upper.where(usable)
    result.loc[secondary_context, "scenario_sensitivity_lower"] = result.loc[
        secondary_context, "baseline_uncertainty_lower"
    ]
    result.loc[secondary_context, "scenario_sensitivity_upper"] = result.loc[
        secondary_context, "baseline_uncertainty_upper"
    ]
    result["scenario_uncertainty_status"] = np.select(
        [usable, secondary_context],
        [SCENARIO_RANGE_STATUS, SCENARIO_RANGE_NOT_ADJUSTED],
        default=SCENARIO_RANGE_UNAVAILABLE,
    )
    result["scenario_uncertainty_method"] = SCENARIO_RANGE_METHOD
    result["scenario_calibration_status"] = np.where(
        scenario_target, "baseline_only_not_scenario", SCENARIO_RANGE_NOT_ADJUSTED
    )
    result["scenario_range_semantics"] = "derived_sensitivity_range_not_recalibrated"
    result["scenario_range_coverage_guarantee"] = False
    return result


def reevaluate_daily_pressure(frame: pd.DataFrame) -> pd.DataFrame:
    """Evaluate accepted pressure severity using scenario central and valid sensitivity ranges."""
    result = frame.copy(deep=True)
    rows = [
        severity_for_row(forecast, threshold, lower, upper, status == "supported")
        for forecast, threshold, lower, upper, status in zip(
            result["scenario_central"],
            result["threshold_value"],
            result["scenario_sensitivity_lower"],
            result["scenario_sensitivity_upper"],
            result["threshold_status"],
            strict=True,
        )
    ]
    result["severity"] = [item[0] for item in rows]
    reasons = []
    for (_, reason), target, range_status, fallback, forecast_fallback, baseline_reasons in zip(
        rows,
        result["target"],
        result["scenario_uncertainty_status"],
        result["threshold_fallback_level"],
        result["fallback_status"],
        result["reason_codes"],
        strict=True,
    ):
        if target == SECONDARY_TARGET:
            reasons.append(list(baseline_reasons))
            continue
        reasons.append(
            [reason]
            + ([] if range_status == SCENARIO_RANGE_STATUS else [SCENARIO_RANGE_REASON_UNAVAILABLE])
            + (["REGION_THRESHOLD_FALLBACK"] if str(fallback).startswith("region_") else [])
            + (["FORECAST_FALLBACK"] if forecast_fallback != "not_applicable" else [])
        )
    result["reason_codes"] = reasons
    result["source_reason_code"] = [codes[0] if codes else None for codes in reasons]
    result["is_alert"] = result["severity"].isin(ALERT_SEVERITIES)
    return result


def _pressure_working_frame(frame: pd.DataFrame) -> pd.DataFrame:
    """Private adapter for accepted pressure functions; compatibility names must never be published."""
    working = frame.copy(deep=True)
    working["forecast_value"] = working["scenario_central"]
    working["uncertainty_lower"] = working["scenario_sensitivity_lower"]
    working["uncertainty_upper"] = working["scenario_sensitivity_upper"]
    working["uncertainty_status"] = working["baseline_uncertainty_status"]
    working["calibration_version"] = working["baseline_calibration_version"]
    return working


def _public_scenario_frame(frame: pd.DataFrame) -> pd.DataFrame:
    """Remove private accepted-pressure compatibility names from scenario-facing artifacts.

    Scenario central and range values are already published as ``scenario_central`` and
    ``scenario_sensitivity_*``; the accepted calibrated names would misdescribe them.
    """
    result = frame.copy(deep=True).drop(columns=PRIVATE_COMPATIBILITY_COLUMNS, errors="ignore")
    if "uncertainty_available" in result:
        result = result.rename(columns={"uncertainty_available": "baseline_uncertainty_available"})
    leaked = sorted(set(PRIVATE_COMPATIBILITY_COLUMNS) & set(result.columns))
    if leaked:
        raise RuntimeError(f"private pressure compatibility columns leaked into a scenario artifact: {leaked}")
    return result


def build_bottom_up_hierarchy(daily: pd.DataFrame) -> pd.DataFrame:
    """Return hospital central rows plus exact region and national bottom-up aggregates."""
    hospital = daily[daily["level"].eq("hospital")].copy()
    hospital["hierarchy_level"] = "hospital"
    hospital["hierarchy_uncertainty_status"] = hospital["scenario_uncertainty_status"]
    hospital["hierarchy_method"] = "hospital_scenario_input"
    keep = [
        "phase",
        "origin",
        "target",
        "horizon",
        "target_date",
        "hospital_id",
        "region_id",
        "profile_id",
        "series_id",
        "hierarchy_level",
        "baseline_central",
        "scenario_central",
        "scenario_sensitivity_lower",
        "scenario_sensitivity_upper",
        "hierarchy_uncertainty_status",
        "hierarchy_method",
    ]
    hospital = hospital[keep]
    region_keys = ["phase", "origin", "target", "horizon", "target_date", "region_id", "profile_id"]
    region = (
        hospital.groupby(region_keys, sort=True, observed=True)[["baseline_central", "scenario_central"]]
        .sum()
        .reset_index()
    )
    region["hospital_id"] = "__region__"
    region["series_id"] = "rp:" + region["region_id"].astype(str) + ":" + region["profile_id"].astype(str)
    region["hierarchy_level"] = "region"
    region["scenario_sensitivity_lower"] = np.nan
    region["scenario_sensitivity_upper"] = np.nan
    region["hierarchy_uncertainty_status"] = "NOT_SCENARIO_ADJUSTED"
    region["hierarchy_method"] = "bottom_up_hospital_exact_central"
    national_keys = ["phase", "origin", "target", "horizon", "target_date", "profile_id"]
    national = (
        region.groupby(national_keys, sort=True, observed=True)[["baseline_central", "scenario_central"]]
        .sum()
        .reset_index()
    )
    national["hospital_id"] = "__national__"
    national["region_id"] = "__national__"
    national["series_id"] = "np:" + national["profile_id"].astype(str)
    national["hierarchy_level"] = "national"
    national["scenario_sensitivity_lower"] = np.nan
    national["scenario_sensitivity_upper"] = np.nan
    national["hierarchy_uncertainty_status"] = "NOT_SCENARIO_ADJUSTED"
    national["hierarchy_method"] = "bottom_up_region_exact_central"
    result = pd.concat([hospital, region[keep], national[keep]], ignore_index=True)
    return result.sort_values(
        ["phase", "origin", "target", "horizon", "hierarchy_level", "region_id", "hospital_id", "profile_id"],
        kind="stable",
    ).reset_index(drop=True)


def hierarchy_coherence(hierarchy: pd.DataFrame) -> dict[str, float | bool]:
    hospital = hierarchy[hierarchy["hierarchy_level"].eq("hospital")]
    region = hierarchy[hierarchy["hierarchy_level"].eq("region")]
    national = hierarchy[hierarchy["hierarchy_level"].eq("national")]
    region_keys = ["phase", "origin", "target", "horizon", "target_date", "region_id", "profile_id"]
    national_keys = ["phase", "origin", "target", "horizon", "target_date", "profile_id"]
    hospital_sum = hospital.groupby(region_keys, observed=True)["scenario_central"].sum().sort_index()
    region_value = region.set_index(region_keys)["scenario_central"].sort_index()
    region_error = float((hospital_sum - region_value).abs().max()) if len(region_value) else 0.0
    region_sum = region.groupby(national_keys, observed=True)["scenario_central"].sum().sort_index()
    national_value = national.set_index(national_keys)["scenario_central"].sort_index()
    national_error = float((region_sum - national_value).abs().max()) if len(national_value) else 0.0
    return {
        "region_max_absolute_error": region_error,
        "national_max_absolute_error": national_error,
        "within_tolerance": region_error <= FLOAT_TOLERANCE and national_error <= FLOAT_TOLERANCE,
    }


def _attach_entity_scenario_fields(entity: pd.DataFrame, daily: pd.DataFrame) -> pd.DataFrame:
    keys = ["phase", "origin", "target", "series_id", "horizon"]
    evidence = daily[
        keys
        + [
            "baseline_central",
            "scenario_central",
            "baseline_uncertainty_lower",
            "baseline_uncertainty_upper",
            "baseline_uncertainty_status",
            "baseline_calibration_status",
            "baseline_calibration_version",
            "scenario_uncertainty_status",
            "scenario_uncertainty_method",
            "scenario_sensitivity_lower",
            "scenario_sensitivity_upper",
            "scenario_calibration_status",
            "scenario_range_semantics",
            "scenario_range_coverage_guarantee",
        ]
    ].rename(columns={"horizon": "severity_evidence_horizon"})
    merge_keys = ["phase", "origin", "target", "series_id", "severity_evidence_horizon"]
    return entity.merge(evidence, on=merge_keys, how="left", validate="one_to_one")


def _replace_scenario_explanations(frame: pd.DataFrame) -> pd.DataFrame:
    result = frame.copy()
    if result.empty:
        return result
    result["scenario_range_available"] = result["scenario_uncertainty_status"].eq(SCENARIO_RANGE_STATUS)
    result["evidence_facts"] = [
        [
            fact
            for fact in facts
            if fact not in {"Calibrated uncertainty is available.", "Estimated uncertainty is unavailable."}
        ]
        + [
            (
                "A derived scenario sensitivity range is available; it is not re-calibrated "
                "and has no coverage guarantee."
                if available
                else "A scenario sensitivity range is unavailable."
            )
        ]
        for facts, available in zip(result["evidence_facts"], result["scenario_range_available"], strict=True)
    ]
    # HIGH quotes the lower bound and WATCH the upper bound. Both are deterministic transformed
    # sensitivity bounds under this scenario, so neither may keep the accepted calibrated wording.
    for accepted_wording, scenario_wording in SCENARIO_EXPLANATION_REWRITES.items():
        result["concise_reason"] = result["concise_reason"].str.replace(accepted_wording, scenario_wording, regex=False)
    return result


def _daily_difference(baseline: pd.DataFrame, scenario: pd.DataFrame) -> pd.DataFrame:
    keys = ["phase", "origin", "target", "series_id", "horizon", "target_date"]
    left = baseline[keys + ["forecast_value", "severity", "threshold_value"]].rename(
        columns={
            "forecast_value": "baseline_central",
            "severity": "baseline_severity",
            "threshold_value": "baseline_threshold",
        }
    )
    right = scenario[keys + ["scenario_central", "severity", "threshold_value"]].rename(
        columns={
            "severity": "scenario_severity",
            "threshold_value": "scenario_threshold",
        }
    )
    result = left.merge(right, on=keys, validate="one_to_one")
    result["absolute_delta"] = result["scenario_central"] - result["baseline_central"]
    result["relative_delta"] = np.where(
        result["baseline_central"].ne(0),
        result["absolute_delta"] / result["baseline_central"],
        np.nan,
    )
    result["severity_changed"] = result["baseline_severity"].ne(result["scenario_severity"])
    return result


def _inbox_identity(frame: pd.DataFrame) -> pd.DataFrame:
    keys = ["phase", "origin", "target", "hospital_id", "profile_id"]
    if frame.empty:
        return pd.DataFrame(columns=keys + ["inbox_rank"])
    return frame[keys + ["inbox_rank"]].copy()


def _entity_difference(
    baseline: pd.DataFrame,
    scenario: pd.DataFrame,
    baseline_inbox: pd.DataFrame,
    scenario_inbox: pd.DataFrame,
) -> pd.DataFrame:
    keys = ["phase", "origin", "target", "hospital_id", "profile_id"]
    left = baseline[keys + ["severity", "forecast_value", "threshold_value"]].rename(
        columns={
            "severity": "baseline_severity",
            "forecast_value": "baseline_central",
            "threshold_value": "baseline_threshold",
        }
    )
    right = scenario[keys + ["severity", "scenario_central", "threshold_value"]].rename(
        columns={
            "severity": "scenario_severity",
            "threshold_value": "scenario_threshold",
        }
    )
    result = left.merge(right, on=keys, validate="one_to_one")
    result = result.merge(
        _inbox_identity(baseline_inbox).rename(columns={"inbox_rank": "baseline_inbox_rank"}),
        on=keys,
        how="left",
        validate="one_to_one",
    )
    result = result.merge(
        _inbox_identity(scenario_inbox).rename(columns={"inbox_rank": "scenario_inbox_rank"}),
        on=keys,
        how="left",
        validate="one_to_one",
    )
    result["absolute_delta"] = result["scenario_central"] - result["baseline_central"]
    result["relative_delta"] = np.where(
        result["baseline_central"].ne(0),
        result["absolute_delta"] / result["baseline_central"],
        np.nan,
    )
    result["severity_changed"] = result["baseline_severity"].ne(result["scenario_severity"])
    baseline_eligible = result["baseline_inbox_rank"].notna()
    scenario_eligible = result["scenario_inbox_rank"].notna()
    result["entered_primary_inbox"] = ~baseline_eligible & scenario_eligible
    result["left_primary_inbox"] = baseline_eligible & ~scenario_eligible
    return result


def _with_source_reason_code(frame: pd.DataFrame) -> pd.DataFrame:
    """Expose the accepted source reason (never a severity label) as a comparable scalar column."""
    if "source_reason_code" in frame.columns or "reason_codes" not in frame.columns:
        return frame
    result = frame.copy()
    result["source_reason_code"] = [
        codes[0] if codes is not None and len(codes) else None for codes in result["reason_codes"]
    ]
    return result


def _frame_scientific_hash(frame: pd.DataFrame, columns: list[str]) -> str:
    available = [column for column in columns if column in frame.columns]
    normalized = frame[available].copy()
    for column in normalized.select_dtypes(include=["datetime", "datetimetz"]).columns:
        normalized[column] = normalized[column].astype("string")
    payload = normalized.to_json(orient="split", index=False, date_format="iso", double_precision=15)
    return hashlib.sha256(payload.encode()).hexdigest()


def assert_baseline_reproduction(
    recomputed_daily: pd.DataFrame,
    accepted_daily: pd.DataFrame,
    recomputed_entity: pd.DataFrame,
    accepted_entity: pd.DataFrame,
    recomputed_inbox: pd.DataFrame,
    accepted_inbox: pd.DataFrame,
    recomputed_unsupported: pd.DataFrame | None = None,
    accepted_unsupported: pd.DataFrame | None = None,
    recomputed_low_volume: pd.DataFrame | None = None,
    accepted_low_volume: pd.DataFrame | None = None,
    *,
    tolerance: float = FLOAT_TOLERANCE,
) -> dict[str, Any]:
    """Strongly compare accepted and no-op scientific fields, ignoring runtime metadata."""
    daily_keys = ["phase", "origin", "target", "series_id", "horizon"]
    entity_keys = ["phase", "origin", "target", "series_id"]
    inbox_keys = ["phase", "origin", "target", "hospital_id", "profile_id"]
    compared: dict[str, list[str]] = {}

    def prepare(frame: pd.DataFrame, keys: list[str], fields: list[str]) -> pd.DataFrame:
        working = _with_source_reason_code(frame)
        missing = sorted(set(keys + fields) - set(working.columns))
        if missing:
            raise ScenarioContractError(
                "BASELINE_REPRODUCTION_FAILED", f"identity gate cannot compare missing fields {missing}"
            )
        return working[keys + fields].sort_values(keys).reset_index(drop=True)

    def compare(
        left: pd.DataFrame,
        right: pd.DataFrame,
        keys: list[str],
        pairs: list[tuple[str, str]],
        label: str,
    ) -> None:
        a = prepare(left, keys, [pair[0] for pair in pairs])
        b = prepare(right, keys, [pair[1] for pair in pairs])
        if len(a) != len(b) or not a[keys].equals(b[keys]):
            raise ScenarioContractError("BASELINE_REPRODUCTION_FAILED", f"{label} row identities differ")
        for scenario_field, accepted_field in pairs:
            left_values, right_values = a[scenario_field], b[accepted_field]
            if pd.api.types.is_numeric_dtype(left_values) and pd.api.types.is_numeric_dtype(right_values):
                if not np.allclose(left_values, right_values, atol=tolerance, rtol=0, equal_nan=True):
                    raise ScenarioContractError(
                        "BASELINE_REPRODUCTION_FAILED", f"{label}.{scenario_field} differs from {accepted_field}"
                    )
            elif not left_values.fillna("__NA__").equals(right_values.fillna("__NA__")):
                raise ScenarioContractError(
                    "BASELINE_REPRODUCTION_FAILED", f"{label}.{scenario_field} differs from {accepted_field}"
                )
        compared[label] = [pair[0] for pair in pairs]

    compare(recomputed_daily, accepted_daily, daily_keys, SCIENTIFIC_DAILY_FIELD_PAIRS, "daily")
    compare(recomputed_entity, accepted_entity, entity_keys, SCIENTIFIC_ENTITY_FIELD_PAIRS, "entity")
    compare(recomputed_inbox, accepted_inbox, inbox_keys, SCIENTIFIC_INBOX_FIELD_PAIRS, "inbox")
    optional_views = [
        (recomputed_unsupported, accepted_unsupported, "data_quality_rank", "unsupported"),
        (recomputed_low_volume, accepted_low_volume, "attention_rank", "low_volume"),
    ]
    for recomputed, accepted, rank_field, label in optional_views:
        if (recomputed is None) != (accepted is None):
            raise ValueError(f"both accepted and recomputed {label} views must be supplied")
        if recomputed is not None and accepted is not None:
            compare(
                recomputed,
                accepted,
                inbox_keys,
                [
                    ("source_severity", "source_severity"),
                    ("materiality_status", "materiality_status"),
                    ("operational_priority_status", "operational_priority_status"),
                    ("priority_support_class", "priority_support_class"),
                    (rank_field, rank_field),
                ],
                label,
            )
    return {
        "status": "PASS",
        "tolerance": tolerance,
        "daily_rows": len(recomputed_daily),
        "entity_rows": len(recomputed_entity),
        "inbox_rows": len(recomputed_inbox),
        "unsupported_rows": len(recomputed_unsupported) if recomputed_unsupported is not None else None,
        "low_volume_rows": len(recomputed_low_volume) if recomputed_low_volume is not None else None,
        "compared_fields": compared,
    }


def evaluate_scenario(
    baseline_daily: pd.DataFrame,
    anomalies: pd.DataFrame,
    pressure_config: FlowPressureConfig,
    prioritization_config: SignalPrioritizationConfig,
    spec: ScenarioSpec,
) -> ScenarioEvaluation:
    """Run a deterministic scenario through hierarchy, pressure, aggregation, and prioritization."""
    baseline_snapshot = baseline_daily.copy(deep=True)
    anomalies_snapshot = anomalies.copy(deep=True)
    transformed, lever_metadata = apply_scenario_levers(baseline_daily, spec)
    transformed = transform_sensitivity_range(transformed)
    daily = reevaluate_daily_pressure(transformed)
    hierarchy = build_bottom_up_hierarchy(daily)
    coherence = hierarchy_coherence(hierarchy)
    if not coherence["within_tolerance"]:
        raise RuntimeError("scenario hierarchy is not coherent")

    # Accepted pressure/prioritization helpers are reused unchanged through a private working frame
    # that carries their legacy column names; published artifacts use scenario-scoped names only.
    working_daily = _pressure_working_frame(daily)
    baseline_entity = aggregate_pressure_signals(baseline_daily.copy(deep=True), pressure_config)
    working_entity = aggregate_pressure_signals(working_daily, pressure_config)
    working_entity = _attach_entity_scenario_fields(working_entity, daily)
    baseline_inbox, _, _, _ = prepare_inbox(baseline_entity, anomalies, prioritization_config)
    working_inbox, working_unsupported, working_low_volume, working_secondary = prepare_inbox(
        working_entity, anomalies, prioritization_config
    )

    entity = _public_scenario_frame(working_entity)
    inbox = _replace_scenario_explanations(_public_scenario_frame(working_inbox))
    unsupported = _replace_scenario_explanations(_public_scenario_frame(working_unsupported))
    low_volume = _replace_scenario_explanations(_public_scenario_frame(working_low_volume))
    # Cohort rows are untouched secondary context, so their accepted explanations are preserved verbatim.
    secondary = _public_scenario_frame(working_secondary)

    daily_difference = _daily_difference(baseline_daily, daily)
    entity_difference = _entity_difference(baseline_entity, entity, baseline_inbox, inbox)
    if not baseline_daily.equals(baseline_snapshot) or not anomalies.equals(anomalies_snapshot):
        raise RuntimeError("scenario evaluation mutated source dataframes")
    secondary_rows = daily["target"].eq(SECONDARY_TARGET)
    secondary_unchanged = bool(
        np.array_equal(
            daily.loc[secondary_rows, "scenario_central"].to_numpy(),
            daily.loc[secondary_rows, "baseline_central"].to_numpy(),
        )
    )
    scientific_hash = _frame_scientific_hash(
        daily,
        [
            "phase",
            "origin",
            "target",
            "series_id",
            "horizon",
            "baseline_central",
            "scenario_central",
            "scenario_sensitivity_lower",
            "scenario_sensitivity_upper",
            "severity",
            "threshold_value",
        ],
    )
    registration_rows = daily["target"].eq(SCENARIO_TARGET)
    central_delta = daily.loc[registration_rows, "scenario_central"] - daily.loc[registration_rows, "baseline_central"]
    allowed_change = pd.Series(False, index=daily.index)
    for lever in spec.levers:
        lever_mask = _scope_mask(daily, lever.scope)
        if lever.lever_type == ScenarioType.INFLOW_TRANSFER.value:
            hospitals = {
                str(lever.parameters.get("source_hospital_id", "")),
                str(lever.parameters.get("destination_hospital_id", "")),
            }
            lever_mask &= daily["hospital_id"].isin(hospitals)
        if lever.lever_type != ScenarioType.IDENTITY.value:
            allowed_change |= lever_mask
    changed = (daily["scenario_central"] - daily["baseline_central"]).abs() > FLOAT_TOLERANCE
    unexpected_changes = changed & ~allowed_change
    multiplier_values = [
        item["multiplier"] for item in lever_metadata if item["lever_type"] in {"demand_multiplier", "profile_surge"}
    ]
    monotonicity_status = "NOT_APPLICABLE"
    if multiplier_values and all(value >= 1 for value in multiplier_values):
        monotonicity_status = "PASS" if (central_delta >= -FLOAT_TOLERANCE).all() else "FAIL"
    elif multiplier_values and all(value <= 1 for value in multiplier_values):
        monotonicity_status = "PASS" if (central_delta <= FLOAT_TOLERANCE).all() else "FAIL"
    transfer_checks = [item["conservation_error"] for item in lever_metadata if "conservation_error" in item]
    edge_checks = [item for item in lever_metadata if item["lever_type"] == ScenarioType.TIME_SHIFT.value]
    validation = {
        "hierarchy_coherence": coherence,
        "conservation": {
            "status": (
                "PASS"
                if transfer_checks and max(transfer_checks) <= FLOAT_TOLERANCE
                else ("NOT_APPLICABLE" if not transfer_checks else "FAIL")
            ),
            "maximum_error": max(transfer_checks) if transfer_checks else None,
            "tolerance": FLOAT_TOLERANCE,
        },
        "monotonicity": {"status": monotonicity_status},
        "scope_invariance": {
            "status": "PASS" if not unexpected_changes.any() else "FAIL",
            "unexpected_changed_cells": int(unexpected_changes.sum()),
            "unchanged_registration_cells": int((central_delta.abs() <= FLOAT_TOLERANCE).sum()),
            "changed_registration_cells": int((central_delta.abs() > FLOAT_TOLERANCE).sum()),
        },
        "boundaries": {"status": "PASS", "time_shift": edge_checks},
        "determinism": {"scientific_output_sha256": scientific_hash},
        "reversibility": {
            "status": "CONDITIONAL",
            "note": REVERSIBILITY_NOTE,
        },
        "restricted_historical_replay": {
            "status": "NOT_RUN",
            "scope": "threshold_and_severity_reaction_only",
            "counterfactual_validation": False,
        },
        "source_frames_unchanged": True,
        "cohort_hospitalizations_unchanged": secondary_unchanged,
        "raw_quantiles_untouched": True,
        "scenario_range_coverage_guarantee": False,
        "causal_effect_claimed": False,
        "scientific_output_sha256": scientific_hash,
    }
    metadata = {
        "scenario_id": spec.scenario_id,
        "scenario_version": spec.scenario_version,
        "scenario_type": spec.scenario_type,
        "classification": spec.classification.value,
        "created_at": spec.created_at.isoformat(),
        "evaluation_metadata": {
            "status": "completed",
            "timestamp_authority": "experiment_run_manifest",
        },
        "execution_mode": spec.baseline_provenance.execution_mode,
        "baseline_provenance": spec.baseline_provenance.model_dump(mode="json"),
        "levers": lever_metadata,
        "uncertainty": {
            "method": SCENARIO_RANGE_METHOD,
            "label": SCENARIO_RANGE_STATUS,
            "semantics": "derived sensitivity range",
            "recalibrated": False,
            "coverage_guarantee": False,
        },
        "hierarchy": {
            "method": "bottom_up_hospital_exact_central",
            "probabilistic_reconciliation": False,
            "parent_uncertainty_manufactured": False,
        },
        "pressure_semantics": pressure_config.threshold_semantics,
        "ranking_method": "fixed_lexicographic_no_learned_or_weighted_score",
        "observed_anomaly_transformed": False,
        "primary_target": SCENARIO_TARGET,
        "secondary_context_target": SECONDARY_TARGET,
        "cohort_hospitalizations_scenario_adjusted": False,
        "retrospective_evaluation_labels": {
            "fields": RETROSPECTIVE_EVALUATION_LABELS,
            "semantics": "observed retrospective baseline evaluation labels, not scenario predictions",
            "serving_eligible": False,
        },
        "serving_claim": False,
    }
    return ScenarioEvaluation(
        spec=spec,
        daily_cells=daily,
        hierarchy_cells=hierarchy,
        entity_signals=entity,
        inbox=inbox,
        baseline_inbox=baseline_inbox,
        unsupported=unsupported,
        low_volume_attention=low_volume,
        secondary_context=secondary,
        daily_differences=daily_difference,
        entity_differences=entity_difference,
        validation=validation,
        metadata=metadata,
    )


def _severity_counts(values: pd.Series) -> dict[str, int]:
    return {str(key): int(count) for key, count in values.value_counts().sort_index().items()}


def scenario_summary(evaluation: ScenarioEvaluation) -> dict[str, Any]:
    """Summarize per target. The untouched cohort context never dilutes the registrations denominator."""
    differences = evaluation.daily_differences
    entities = evaluation.entity_differences
    signals = evaluation.entity_signals
    inbox = evaluation.inbox

    primary_daily = differences[differences["target"].eq(SCENARIO_TARGET)]
    primary_entities = entities[entities["target"].eq(SCENARIO_TARGET)]
    primary_signals = signals[signals["target"].eq(SCENARIO_TARGET)]
    secondary_daily = differences[differences["target"].eq(SECONDARY_TARGET)]
    secondary_entities = entities[entities["target"].eq(SECONDARY_TARGET)]

    transitions = (
        primary_daily.groupby(["baseline_severity", "scenario_severity"], observed=True)
        .size()
        .rename("count")
        .reset_index()
        .to_dict(orient="records")
    )
    direct = int(inbox["direct_supported"].sum()) if len(inbox) else 0
    return {
        "scenario": evaluation.metadata,
        "validation": evaluation.validation,
        "primary_target": SCENARIO_TARGET,
        "targets": {
            SCENARIO_TARGET: {
                "daily_cells": {
                    "total": len(primary_daily),
                    "severity_changed_count": int(primary_daily["severity_changed"].sum()),
                    "severity_changed_share": (
                        float(primary_daily["severity_changed"].mean()) if len(primary_daily) else 0.0
                    ),
                    "transition_matrix": transitions,
                    "severity_counts": _severity_counts(primary_daily["scenario_severity"]),
                },
                "entities": {
                    "total": len(primary_entities),
                    "severity_counts": _severity_counts(primary_signals["severity"]),
                    "changed_count": int(primary_entities["severity_changed"].sum()),
                    "changed_share": (
                        float(primary_entities["severity_changed"].mean()) if len(primary_entities) else 0.0
                    ),
                },
                "inbox": {
                    "baseline_size": len(evaluation.baseline_inbox),
                    "scenario_size": len(inbox),
                    "entered": int(primary_entities["entered_primary_inbox"].sum()),
                    "left": int(primary_entities["left_primary_inbox"].sum()),
                    "direct_supported": direct,
                    "fallback_limited": int(len(inbox) - direct),
                    "zero_baseline_low_volume_attention": len(evaluation.low_volume_attention),
                },
            },
            SECONDARY_TARGET: {
                "scenario_adjustment": "NONE",
                "semantic_role": "UNCHANGED_SECONDARY_CONTEXT",
                "row_count": len(secondary_daily),
                "entity_count": len(secondary_entities),
                "severity_changed_count": int(secondary_daily["severity_changed"].sum()),
            },
        },
    }


def scenario_spec_scientific_payload(spec: ScenarioSpec) -> dict[str, Any]:
    """Spec content that defines the science. ``created_at`` is audit metadata and is excluded."""
    payload = spec.model_dump(mode="json")
    for field in SPEC_AUDIT_ONLY_FIELDS:
        payload.pop(field, None)
    return payload


def canonical_spec_identity(spec: ScenarioSpec) -> str:
    return hashlib.sha256(store.canonical_json(scenario_spec_scientific_payload(spec)).encode()).hexdigest()


def load_scenario_spec(path: Path) -> ScenarioSpec:
    return ScenarioSpec(**json.loads(path.read_text(encoding="utf-8")))
