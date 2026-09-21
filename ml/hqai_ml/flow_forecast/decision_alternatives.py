"""Exact constrained decision alternatives over the accepted scenario surrogate.

This module is an offline search and verification layer.  It deliberately imports the
accepted 6B.3/6B.2C functions instead of reproducing or modifying their science.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import math
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from enum import StrEnum
from fractions import Fraction
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from hqai_ml.flow_forecast.config import FlowPressureConfig, SignalPrioritizationConfig
from hqai_ml.flow_forecast.pressure import SEVERITY_RANK, severity_for_row
from hqai_ml.flow_forecast.scenario import (
    FLOAT_TOLERANCE,
    BaselineProvenance,
    ScenarioClassification,
    ScenarioScope,
    ScenarioSpec,
    ScopeType,
    evaluate_scenario,
    reevaluate_daily_pressure,
    scenario_spec_scientific_payload,
    transform_sensitivity_range,
)
from hqai_ml.registry import store

OPTIMIZER_CONTRACT_VERSION = "constrained-decision-alternatives-v1"
SCENARIO_CONTRACT_VERSION = "forecast-stress-test-v1"
ACCEPTED_SOURCE_RUN_IDS = {
    "hierarchy": "flow-hierarchy-6b2b3-real-v1",
    "pressure": "flow-pressure-6b2c1-real-v2",
    "prioritization": "signal-prioritization-6b2c2-real-v2",
    "scenario": "flow-scenario-6b3-real-v1",
}
TARGET = "registrations"
PUBLIC_TARGET = "REGISTRATIONS"
DONOR_GOAL = "CENTRAL_EXCEEDANCE_CLEARED"
RECEIVER_CONSTRAINT = "NO_WORSE_HISTORICAL_FLOW_PROXY_STATE"
DECISION_BASIS = "CENTRAL_CASE"
ALGORITHM = "EXACT_BREAKPOINT_ENUMERATION_V1"
TRANSFER_CERTIFICATION = "ALGEBRAIC_MINIMUM_CERTIFIED_UPWARD_FLOAT64"
VERIFIED = "VERIFIED_FULL_ENGINE"
EXECUTION_MODE = "EVALUATION"
FEASIBILITY_STATUS = "NOT_PHYSICAL_CAPACITY_VALIDATED"
LIMITATIONS = [
    "NOT_PHYSICAL_CAPACITY_VALIDATED",
    "THRESHOLD_COMPARATOR_ASSUMPTION",
    "PHYSICAL_FEASIBILITY_UNKNOWN",
]
REQUIRED_HORIZONS = tuple(range(1, 15))
SUPPORT_MAP = {
    "direct_supported": "DIRECT_SUPPORTED",
    "fallback_or_limited_history": "FALLBACK_LIMITED",
}
FORBIDDEN_PUBLIC_FIELD_PARTS = (
    "recommendation",
    "recommended_",
    "best_",
    "optimal_",
    "chosen_",
    "selected_action",
    "action_plan",
    "routing_decision",
)
FORBIDDEN_EXPLANATION_TERMS = (
    "caused",
    "causes",
    "causal",
    "driver",
    "drives",
    "attributable",
    "recommend",
    "recommended",
    "should transfer",
    "route",
    "routing",
    "reroute",
    "optimal",
    "best",
    "capacity",
    "spare capacity",
    "beds",
    "bed",
    "staffing",
    "occupancy",
    "available",
    "availability",
    "accept patients",
    "absorb",
    "avoid overload",
    "prevent",
    "reduce waiting",
    "waiting time",
    "refusal",
    "outcome improves",
    "benefit",
    "safe",
    "feasible",
)
ALLOWED_NEGATED_EXPLANATION_PHRASES = (
    "physical capacity was not checked",
    "not an action, instruction, or recommendation",
)


class AbstentionCode(StrEnum):
    NO_ELIGIBLE_RECEIVER = "NO_ELIGIBLE_RECEIVER"
    DONOR_CENTRAL_RELIEF_INFEASIBLE = "DONOR_CENTRAL_RELIEF_INFEASIBLE"
    TRANSFER_BUDGET_INSUFFICIENT = "TRANSFER_BUDGET_INSUFFICIENT"
    RECEIVER_BLOCKED = "RECEIVER_BLOCKED"
    INSUFFICIENT_SUPPORT = "INSUFFICIENT_SUPPORT"
    UNSUPPORTED_SIGNAL = "UNSUPPORTED_SIGNAL"
    NO_NON_DOMINATED_ALTERNATIVE = "NO_NON_DOMINATED_ALTERNATIVE"
    DONOR_NOT_CENTRAL_DRIVEN = "DONOR_NOT_CENTRAL_DRIVEN"
    DONOR_NOT_MATERIALLY_ELIGIBLE = "DONOR_NOT_MATERIALLY_ELIGIBLE"
    DONOR_TIER_EXCLUDED = "DONOR_TIER_EXCLUDED"
    RECEIVER_UNSUPPORTED_EVIDENCE = "RECEIVER_UNSUPPORTED_EVIDENCE"
    RECEIVER_ALIGNMENT_INCOMPLETE = "RECEIVER_ALIGNMENT_INCOMPLETE"
    RECEIVER_OUTSIDE_SAME_REGION_POLICY = "RECEIVER_OUTSIDE_SAME_REGION_POLICY"
    RECEIVER_NOT_ALLOW_LISTED = "RECEIVER_NOT_ALLOW_LISTED"
    PHI_CERTIFICATION_FAILED = "PHI_CERTIFICATION_FAILED"
    FULL_VERIFICATION_FAILED = "FULL_VERIFICATION_FAILED"


class DonorCohortConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    origins: list[dt.date]
    top_n_primary_donors: int = Field(ge=1)
    top_n_fallback_donors: int = Field(ge=1)
    severities: list[str]
    require_central_driven: bool
    primary_tier: str
    include_fallback_tier_separately: bool


class ReceiverPolicyConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    same_profile: bool
    same_region: bool
    geographic_scope: str
    require_supported_threshold_all_affected_horizons: bool
    require_aligned_full_horizon_window: bool
    eligible_receiver_ids: list[str] | None = None


class DecisionAlternativesConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: int
    optimizer_contract_version: str
    target: str
    source_hierarchy_run: str
    source_pressure_run: str
    source_prioritization_run: str
    source_scenario_run: str
    scenario_contract_version: str
    donor_goal: str
    decision_basis: str
    algorithm: str
    donor_cohort: DonorCohortConfig
    receiver_policy: ReceiverPolicyConfig
    transfer_budget_ladder: list[float]
    max_total_synthetic_transfer: float | None
    shortlist_max_alternatives: int = Field(ge=1)
    phi_guard_max_steps: int = Field(ge=0)
    float_tolerance: float = Field(gt=0)
    materiality_config_reference: str
    range_recalibrated: bool
    coverage_guarantee: bool
    capacity_checked: bool
    causal_effect_claimed: bool
    human_review_required: bool
    autonomous_action: bool
    execution_mode: str
    serving_claim: bool
    identity_sha256: str = ""

    @model_validator(mode="after")
    def validate_contract(self) -> DecisionAlternativesConfig:
        constants = {
            "optimizer_contract_version": (self.optimizer_contract_version, OPTIMIZER_CONTRACT_VERSION),
            "target": (self.target, TARGET),
            "scenario_contract_version": (self.scenario_contract_version, SCENARIO_CONTRACT_VERSION),
            "donor_goal": (self.donor_goal, DONOR_GOAL),
            "decision_basis": (self.decision_basis, DECISION_BASIS),
            "algorithm": (self.algorithm, ALGORITHM),
            "execution_mode": (self.execution_mode, EXECUTION_MODE),
        }
        for name, (actual, expected) in constants.items():
            if actual != expected:
                raise ValueError(f"{name} must be {expected}")
        source_runs = {
            "hierarchy": self.source_hierarchy_run,
            "pressure": self.source_pressure_run,
            "prioritization": self.source_prioritization_run,
            "scenario": self.source_scenario_run,
        }
        if source_runs != ACCEPTED_SOURCE_RUN_IDS:
            raise ValueError(f"source runs must be the accepted 6B.4 chain: {ACCEPTED_SOURCE_RUN_IDS}")
        if not self.receiver_policy.same_profile or not self.receiver_policy.same_region:
            raise ValueError("v1 receivers must use same_profile=true and same_region=true")
        if self.receiver_policy.geographic_scope != "SAME_REGION":
            raise ValueError("v1 receiver geographic_scope must be SAME_REGION")
        if not self.receiver_policy.require_supported_threshold_all_affected_horizons:
            raise ValueError("affected receiver horizons must require supported thresholds")
        if not self.receiver_policy.require_aligned_full_horizon_window:
            raise ValueError("receivers must require an aligned complete horizon window")
        if self.donor_cohort.severities != ["ELEVATED", "HIGH"]:
            raise ValueError("donor severities must be [ELEVATED, HIGH]")
        if not self.donor_cohort.require_central_driven:
            raise ValueError("donor cohort must require central-driven signals")
        if self.donor_cohort.primary_tier != "direct_supported":
            raise ValueError("primary donor tier must be direct_supported")
        if self.transfer_budget_ladder != [0.05, 0.10, 0.25, 1.00]:
            raise ValueError("transfer budget ladder must remain [0.05, 0.10, 0.25, 1.00]")
        if any(isinstance(value, bool) or not 0 <= value <= 1 for value in self.transfer_budget_ladder):
            raise ValueError("every transfer budget must be a numeric fraction in [0,1]")
        if self.max_total_synthetic_transfer is not None and self.max_total_synthetic_transfer < 0:
            raise ValueError("max_total_synthetic_transfer must be null or nonnegative")
        safety = {
            "range_recalibrated": self.range_recalibrated,
            "coverage_guarantee": self.coverage_guarantee,
            "capacity_checked": self.capacity_checked,
            "causal_effect_claimed": self.causal_effect_claimed,
            "autonomous_action": self.autonomous_action,
            "serving_claim": self.serving_claim,
        }
        enabled = sorted(name for name, value in safety.items() if value)
        if enabled or not self.human_review_required:
            raise ValueError(f"invalid fixed safety semantics: enabled={enabled}")
        return self


def load_decision_alternatives_config(path: Path) -> DecisionAlternativesConfig:
    raw = path.read_bytes()
    config = DecisionAlternativesConfig(**yaml.safe_load(raw))
    return config.model_copy(update={"identity_sha256": hashlib.sha256(raw).hexdigest()})


@dataclass(frozen=True)
class CertifiedBound:
    algebraic: Fraction
    value: float
    steps: int


@dataclass(frozen=True)
class DonorMinimum:
    algebraic: Fraction
    value: float
    certify_up_steps: int
    binding_horizon: int
    binding_cell: dict[str, Any]
    binding_horizons: tuple[int, ...]
    zero_threshold_binding_present: bool


@dataclass(frozen=True)
class ReceiverMaximum:
    algebraic: Fraction
    value: float
    binding_cell: dict[str, Any] | None
    breakpoints: tuple[dict[str, Any], ...]


@dataclass
class InternalCandidate:
    receiver_id: str
    receiver_region_id: str
    receiver_series_id: str
    transfer_fraction: float
    certify_up_steps: int
    receiver_phi_max: float
    receiver_binding_cell: dict[str, Any] | None
    donor_support_class: str
    receiver_support_class: str
    forecast_support_tier: str
    receiver_range_evidence: str
    fast: dict[str, Any]


@dataclass(frozen=True)
class VerificationCacheKey:
    origin: str
    phase: str
    target: str
    region_id: str
    profile_id: str
    donor_hospital_id: str
    donor_series_id: str
    receiver_hospital_id: str
    receiver_series_id: str
    phi_hex: str
    scenario_contract_version: str
    hierarchy_run_id: str
    pressure_run_id: str
    prioritization_run_id: str
    scenario_run_id: str
    scenario_scientific_identity: str
    decision_config_identity_sha256: str
    code_identity_sha256: str


@dataclass(frozen=True, slots=True)
class VerificationCacheEntry:
    success: bool
    scenario_spec_scientific_payload_json: str | None
    scientific_output_sha256: str | None
    verification_only_fields_json: str | None
    failure_code: str | None
    failure_detail: str | None
    fast_payload_fingerprint: str

    @property
    def succeeded(self) -> bool:
        return self.success

    def scenario_spec_scientific_payload(self) -> dict[str, Any]:
        if self.scenario_spec_scientific_payload_json is None:
            raise ValueError("failed verification has no scenario scientific payload")
        return json.loads(self.scenario_spec_scientific_payload_json)

    def verification_only_fields(self) -> dict[str, Any]:
        if self.verification_only_fields_json is None:
            raise ValueError("failed verification has no verification-only fields")
        return json.loads(self.verification_only_fields_json)


class FullVerificationCache:
    """Run-scoped memoization for immutable full-engine verification outcomes."""

    def __init__(self) -> None:
        self._entries: dict[VerificationCacheKey, VerificationCacheEntry] = {}
        self.evaluation_count = 0
        self.reuse_count = 0

    def verify(
        self,
        key: VerificationCacheKey,
        fast_payload_fingerprint: str,
        evaluate: Callable[[], Any],
        compare: Callable[[Any], None],
        compact: Callable[[Any], tuple[dict[str, Any], str, dict[str, Any]]],
    ) -> VerificationCacheEntry:
        cached = self._entries.get(key)
        if cached is not None:
            if cached.fast_payload_fingerprint != fast_payload_fingerprint:
                raise ValueError("verification cache fast-payload fingerprint mismatch")
            self.reuse_count += 1
            return cached
        self.evaluation_count += 1
        try:
            result = evaluate()
            compare(result)
            scenario_payload, scientific_output_sha256, verification_fields = compact(result)
            entry = VerificationCacheEntry(
                success=True,
                scenario_spec_scientific_payload_json=store.canonical_json(scenario_payload),
                scientific_output_sha256=scientific_output_sha256,
                verification_only_fields_json=store.canonical_json(verification_fields),
                failure_code=None,
                failure_detail=None,
                fast_payload_fingerprint=fast_payload_fingerprint,
            )
            del result
        except Exception as exc:  # cache scientific verification failures as deterministic evidence
            entry = VerificationCacheEntry(
                success=False,
                scenario_spec_scientific_payload_json=None,
                scientific_output_sha256=None,
                verification_only_fields_json=None,
                failure_code=AbstentionCode.FULL_VERIFICATION_FAILED.value,
                failure_detail=str(exc),
                fast_payload_fingerprint=fast_payload_fingerprint,
            )
        self._entries[key] = entry
        return entry

    @property
    def unique_scenarios(self) -> int:
        return len(self._entries)

    @property
    def entries(self) -> tuple[VerificationCacheEntry, ...]:
        return tuple(self._entries.values())


def _fraction(value: float | int) -> Fraction:
    value = float(value)
    if not math.isfinite(value):
        raise ValueError("decision arithmetic requires finite binary64 inputs")
    return Fraction.from_float(value)


def _canonical_hash(value: Any) -> str:
    return hashlib.sha256(store.canonical_json(value).encode()).hexdigest()


def _json_records(frame: pd.DataFrame) -> list[dict[str, Any]]:
    # pandas owns Timestamp/NaN normalization here; canonical JSON owns deterministic ordering later.
    import json

    return json.loads(frame.to_json(orient="records", date_format="iso"))


def _normalized_support(value: Any) -> str | None:
    return SUPPORT_MAP.get(str(value))


def _daily_support_class(entity_row: pd.Series) -> str | None:
    if "priority_support_class" in entity_row and pd.notna(entity_row["priority_support_class"]):
        return _normalized_support(entity_row["priority_support_class"])
    direct = (
        entity_row.get("support_status") == "supported"
        and entity_row.get("fallback_status") == "not_applicable"
        and "fallback" not in str(entity_row.get("forecast_source", "")).lower()
    )
    return "DIRECT_SUPPORTED" if direct else "FALLBACK_LIMITED"


def _usable_range(frame: pd.DataFrame) -> pd.Series:
    return (
        frame["uncertainty_status"].eq("level_local_calibrated")
        & np.isfinite(frame["uncertainty_lower"])
        & np.isfinite(frame["uncertainty_upper"])
    )


def _ordered_daily(frame: pd.DataFrame) -> pd.DataFrame:
    return frame.sort_values(["horizon", "target_date"], kind="stable").reset_index(drop=True)


def _aligned_window(frame: pd.DataFrame, donor: pd.DataFrame) -> bool:
    if len(frame) != 14 or frame.duplicated(["horizon", "target_date"]).any():
        return False
    if frame["horizon"].astype(int).tolist() != list(REQUIRED_HORIZONS):
        return False
    return frame["target_date"].reset_index(drop=True).equals(donor["target_date"].reset_index(drop=True))


def donor_binding_horizons(donor: pd.DataFrame) -> tuple[int, ...]:
    binding = donor[
        donor["threshold_status"].eq("supported")
        & np.isfinite(donor["threshold_value"])
        & (donor["forecast_value"] > donor["threshold_value"])
    ]
    return tuple(sorted(binding["horizon"].astype(int).tolist()))


def _donor_bound_passes(phi: float, algebraic: Fraction, donor: pd.DataFrame, binding: set[int]) -> bool:
    if not math.isfinite(phi) or not 0 <= phi <= 1 or _fraction(phi) < algebraic:
        return False
    selected = donor[donor["horizon"].astype(int).isin(binding)]
    moved = phi * selected["forecast_value"].to_numpy(float)
    scenario = selected["forecast_value"].to_numpy(float) - moved
    return bool(np.all(scenario <= selected["threshold_value"].to_numpy(float)))


def derive_donor_minimum(donor: pd.DataFrame, guard_max_steps: int) -> DonorMinimum:
    donor = _ordered_daily(donor)
    binding_horizons = donor_binding_horizons(donor)
    if not binding_horizons:
        raise ValueError(AbstentionCode.DONOR_NOT_CENTRAL_DRIVEN.value)
    bounds: list[tuple[Fraction, int, pd.Series]] = []
    for row in donor[donor["horizon"].astype(int).isin(binding_horizons)].itertuples(index=False):
        central = _fraction(row.forecast_value)
        threshold = _fraction(row.threshold_value)
        bounds.append((Fraction(1) - threshold / central, int(row.horizon), pd.Series(row._asdict())))
    algebraic = max(item[0] for item in bounds)
    binding = min((item for item in bounds if item[0] == algebraic), key=lambda item: item[1])
    candidate = float(algebraic)
    steps = 0
    binding_set = set(binding_horizons)
    while True:
        if _donor_bound_passes(candidate, algebraic, donor, binding_set):
            break
        if steps == guard_max_steps:
            raise ValueError(AbstentionCode.PHI_CERTIFICATION_FAILED.value)
        candidate = math.nextafter(candidate, math.inf)
        steps += 1
    row = binding[2]
    return DonorMinimum(
        algebraic=algebraic,
        value=candidate,
        certify_up_steps=steps,
        binding_horizon=binding[1],
        binding_cell={
            "horizon": binding[1],
            "target_date": pd.Timestamp(row["target_date"]).date().isoformat(),
            "donor_central": float(row["forecast_value"]),
            "threshold_value": float(row["threshold_value"]),
        },
        binding_horizons=binding_horizons,
        zero_threshold_binding_present=any(
            float(item.threshold_value) == 0.0
            for item in donor[donor["horizon"].astype(int).isin(binding_horizons)].itertuples(index=False)
        ),
    )


def _receiver_breakpoints(donor: pd.DataFrame, receiver: pd.DataFrame) -> list[dict[str, Any]]:
    receiver_by_horizon = receiver.set_index("horizon")
    breakpoints: list[dict[str, Any]] = []
    for donor_row in donor.itertuples(index=False):
        moved_base = float(donor_row.forecast_value)
        if moved_base <= 0:
            continue
        row = receiver_by_horizon.loc[int(donor_row.horizon)]
        baseline_severity, _ = severity_for_row(
            float(row["forecast_value"]),
            float(row["threshold_value"]),
            float(row["uncertainty_lower"]) if pd.notna(row["uncertainty_lower"]) else None,
            float(row["uncertainty_upper"]) if pd.notna(row["uncertainty_upper"]) else None,
            row["threshold_status"] == "supported",
        )
        rank = SEVERITY_RANK[baseline_severity]
        usable = (
            row["uncertainty_status"] == "level_local_calibrated"
            and np.isfinite(row["uncertainty_lower"])
            and np.isfinite(row["uncertainty_upper"])
        )
        predicates: list[tuple[str, int, float]] = []
        if rank < 3 and usable:
            predicates.append(("SENSITIVITY_LOWER", 3, float(row["uncertainty_lower"])))
        if rank < 2:
            predicates.append(("CENTRAL", 2, float(row["forecast_value"])))
        if rank < 1 and usable:
            predicates.append(("SENSITIVITY_UPPER", 1, float(row["uncertainty_upper"])))
        for predicate, predicate_rank, baseline_value in predicates:
            bound = (_fraction(row["threshold_value"]) - _fraction(baseline_value)) / _fraction(moved_base)
            if bound < 0:
                raise AssertionError("accepted severity cascade produced a negative applicable receiver breakpoint")
            breakpoints.append(
                {
                    "algebraic": bound,
                    "horizon": int(donor_row.horizon),
                    "target_date": pd.Timestamp(row["target_date"]).date().isoformat(),
                    "predicate": predicate,
                    "predicate_rank": predicate_rank,
                    "threshold_value": float(row["threshold_value"]),
                    "baseline_value": baseline_value,
                    "donor_central": moved_base,
                    "receiver_hospital_id": str(row["hospital_id"]),
                }
            )
    return sorted(
        breakpoints,
        key=lambda item: (
            item["algebraic"],
            item["horizon"],
            item["predicate_rank"],
            item["receiver_hospital_id"],
        ),
    )


def _local_transformed(donor: pd.DataFrame, receiver: pd.DataFrame, phi: float) -> pd.DataFrame:
    pair = pd.concat([donor, receiver], ignore_index=True).copy(deep=True)
    pair["baseline_central"] = pair["forecast_value"].astype(float)
    pair["scenario_central"] = pair["baseline_central"]
    donor_mask = pair["hospital_id"].eq(str(donor.iloc[0]["hospital_id"]))
    receiver_mask = pair["hospital_id"].eq(str(receiver.iloc[0]["hospital_id"]))
    donor_values = pair.loc[donor_mask, "baseline_central"].to_numpy(float)
    moved = donor_values * phi
    pair.loc[donor_mask, "scenario_central"] = donor_values - moved
    pair.loc[receiver_mask, "scenario_central"] = pair.loc[receiver_mask, "baseline_central"].to_numpy(float) + moved
    pair = pair.rename(
        columns={
            "uncertainty_lower": "baseline_uncertainty_lower",
            "uncertainty_upper": "baseline_uncertainty_upper",
            "uncertainty_status": "baseline_uncertainty_status",
        }
    )
    return reevaluate_daily_pressure(transform_sensitivity_range(pair))


def _receiver_no_worse(donor: pd.DataFrame, receiver: pd.DataFrame, phi: float) -> bool:
    transformed = _local_transformed(donor, receiver, phi)
    receiver_id = str(receiver.iloc[0]["hospital_id"])
    scenario = _ordered_daily(transformed[transformed["hospital_id"].eq(receiver_id)])
    baseline = _ordered_daily(receiver)
    return bool(
        np.all(
            scenario["severity"].map(SEVERITY_RANK).to_numpy(int)
            <= baseline["severity"].map(SEVERITY_RANK).to_numpy(int)
        )
    )


def _certify_upper(
    algebraic: Fraction,
    predicate: Callable[[float], bool],
    guard_max_steps: int,
) -> CertifiedBound:
    candidate = float(algebraic)
    steps = 0
    while True:
        if _fraction(candidate) <= algebraic and predicate(candidate):
            return CertifiedBound(algebraic=algebraic, value=candidate, steps=steps)
        if steps == guard_max_steps or candidate == 0.0:
            raise ValueError(AbstentionCode.PHI_CERTIFICATION_FAILED.value)
        candidate = math.nextafter(candidate, 0.0)
        steps += 1


def derive_receiver_maximum(
    donor: pd.DataFrame,
    receiver: pd.DataFrame,
    guard_max_steps: int,
) -> ReceiverMaximum:
    breakpoints = _receiver_breakpoints(donor, receiver)
    algebraic = min([Fraction(1), *(item["algebraic"] for item in breakpoints)])
    bound = _certify_upper(algebraic, lambda phi: _receiver_no_worse(donor, receiver, phi), guard_max_steps)
    binding = next((item for item in breakpoints if item["algebraic"] == algebraic), None)
    public_binding = None
    if binding is not None:
        public_binding = {key: value for key, value in binding.items() if key != "algebraic"}
    public_breakpoints = tuple(
        {**{key: value for key, value in item.items() if key != "algebraic"}, "bound": float(item["algebraic"])}
        for item in breakpoints
    )
    return ReceiverMaximum(
        algebraic=algebraic,
        value=bound.value,
        binding_cell=public_binding,
        breakpoints=public_breakpoints,
    )


def _entity_summary(frame: pd.DataFrame) -> dict[str, Any]:
    ordered = _ordered_daily(frame)

    def maximum(window: int) -> str:
        values = ordered.loc[ordered["horizon"] <= window, "severity"]
        return max(values, key=lambda value: SEVERITY_RANK[str(value)])

    displayed = maximum(14)
    evidence = ordered[ordered["severity"].eq(displayed)].iloc[0]
    return {
        "displayed_severity": displayed,
        "max_severity_7d": maximum(7),
        "max_severity_14d": displayed,
        "severity_evidence_horizon": int(evidence["horizon"]),
        "severity_evidence_date": pd.Timestamp(evidence["target_date"]).date().isoformat(),
    }


def _state(frame: pd.DataFrame, scenario: bool) -> dict[str, Any]:
    summary = _entity_summary(frame)
    cells = []
    for row in _ordered_daily(frame).itertuples(index=False):
        if scenario:
            cell = {
                "horizon": int(row.horizon),
                "target_date": pd.Timestamp(row.target_date).date().isoformat(),
                "central": float(row.scenario_central),
                "sensitivity_lower": (
                    float(row.scenario_sensitivity_lower) if pd.notna(row.scenario_sensitivity_lower) else None
                ),
                "sensitivity_upper": (
                    float(row.scenario_sensitivity_upper) if pd.notna(row.scenario_sensitivity_upper) else None
                ),
                "scenario_uncertainty_status": str(row.scenario_uncertainty_status),
                "scenario_uncertainty_method": str(row.scenario_uncertainty_method),
            }
        else:
            cell = {
                "horizon": int(row.horizon),
                "target_date": pd.Timestamp(row.target_date).date().isoformat(),
                "central": float(row.forecast_value),
                "sensitivity_lower": float(row.uncertainty_lower) if pd.notna(row.uncertainty_lower) else None,
                "sensitivity_upper": float(row.uncertainty_upper) if pd.notna(row.uncertainty_upper) else None,
                "uncertainty_status": str(row.uncertainty_status),
            }
        source_reason = getattr(row, "source_reason_code", None)
        if source_reason is None:
            reasons = getattr(row, "reason_codes", [])
            source_reason = reasons[0] if reasons else None
        cell |= {
            "threshold_value": float(row.threshold_value) if pd.notna(row.threshold_value) else None,
            "threshold_status": str(row.threshold_status),
            "threshold_fallback_level": str(row.threshold_fallback_level),
            "severity": str(row.severity),
            "source_reason_code": str(source_reason),
        }
        cells.append(cell)
    return summary | {"cells": cells}


def fast_evaluate(
    donor: pd.DataFrame,
    receiver: pd.DataFrame,
    phi: float,
    donor_minimum: DonorMinimum,
    receiver_maximum: ReceiverMaximum,
    max_transfer_fraction: float,
    max_total_synthetic_transfer: float | None,
) -> dict[str, Any]:
    transformed = _local_transformed(donor, receiver, phi)
    donor_id = str(donor.iloc[0]["hospital_id"])
    receiver_id = str(receiver.iloc[0]["hospital_id"])
    donor_after = _ordered_daily(transformed[transformed["hospital_id"].eq(donor_id)])
    receiver_after = _ordered_daily(transformed[transformed["hospital_id"].eq(receiver_id)])
    donor = _ordered_daily(donor)
    receiver = _ordered_daily(receiver)
    affected = donor["forecast_value"].to_numpy(float) > 0
    moved = phi * donor["forecast_value"].to_numpy(float)
    donor_goal = bool(
        np.all(
            donor_after.loc[
                donor_after["horizon"].astype(int).isin(donor_minimum.binding_horizons), "scenario_central"
            ].to_numpy(float)
            <= donor.loc[donor["horizon"].astype(int).isin(donor_minimum.binding_horizons), "threshold_value"].to_numpy(
                float
            )
        )
    )
    donor_baseline_rank = donor["severity"].map(SEVERITY_RANK).to_numpy(int)
    donor_after_rank = donor_after["severity"].map(SEVERITY_RANK).to_numpy(int)
    receiver_baseline_rank = receiver["severity"].map(SEVERITY_RANK).to_numpy(int)
    receiver_after_rank = receiver_after["severity"].map(SEVERITY_RANK).to_numpy(int)
    no_worse = bool(np.all(receiver_after_rank <= receiver_baseline_rank))
    total_moved = float(moved.sum())
    budget = phi <= max_transfer_fraction and (
        max_total_synthetic_transfer is None or total_moved <= max_total_synthetic_transfer
    )
    before_sum = donor["forecast_value"].to_numpy(float) + receiver["forecast_value"].to_numpy(float)
    after_sum = donor_after["scenario_central"].to_numpy(float) + receiver_after["scenario_central"].to_numpy(float)
    errors = np.abs(after_sum - before_sum)
    total_error = abs(float(after_sum.sum()) - float(before_sum.sum()))
    max_error = max(float(errors.max(initial=0.0)), total_error)
    usable = _usable_range(receiver).to_numpy(bool)
    range_masking = bool(np.any(affected & ~usable))
    if range_masking:
        sensitivity_result = "RANGE_EVIDENCE_INCOMPLETE"
        range_evidence = "RANGE_LIMITED"
    else:
        upper = receiver_after["scenario_sensitivity_upper"].to_numpy(float)
        threshold = receiver_after["threshold_value"].to_numpy(float)
        sensitivity_result = (
            "ROBUST_TO_TRANSFORMED_RANGE"
            if np.all(upper[affected] <= threshold[affected])
            else "NOT_ROBUST_TO_TRANSFORMED_RANGE"
        )
        range_evidence = "COMPLETE"
    receiver_severities = receiver_after.loc[affected, "severity"]
    worst_receiver = max(receiver_severities, key=lambda value: SEVERITY_RANK[str(value)])
    headroom = receiver["threshold_value"].to_numpy(float) - receiver_after["scenario_central"].to_numpy(float)
    residual_high = (
        donor_after[
            donor_after["threshold_status"].eq("supported")
            & np.isfinite(donor_after["scenario_sensitivity_lower"])
            & (donor_after["scenario_sensitivity_lower"] > donor_after["threshold_value"])
        ]["horizon"]
        .astype(int)
        .tolist()
    )
    return {
        "baseline_donor_state": _state(donor, scenario=False),
        "scenario_donor_state": _state(donor_after, scenario=True),
        "baseline_receiver_state": _state(receiver, scenario=False),
        "scenario_receiver_state": _state(receiver_after, scenario=True),
        "source_central_goal_satisfied": donor_goal,
        "donor_severity_never_worsened": bool(np.all(donor_after_rank <= donor_baseline_rank)),
        "receiver_no_worse_constraint_satisfied": no_worse,
        "budget_constraint_satisfied": bool(budget),
        "conservation_satisfied": max_error <= FLOAT_TOLERANCE,
        "pair_conservation_max_absolute_error": max_error,
        "transferred_expected_registrations_total": total_moved,
        "transferred_by_horizon": [
            {
                "horizon": int(row.horizon),
                "target_date": pd.Timestamp(row.target_date).date().isoformat(),
                "moved": float(amount),
            }
            for row, amount in zip(donor.itertuples(index=False), moved, strict=True)
        ],
        "receiver_min_central_headroom": float(np.min(headroom[affected])),
        "receiver_worst_severity_after": str(worst_receiver),
        "receiver_range_evidence": range_evidence,
        "receiver_range_masking_present": range_masking,
        "sensitivity_range_result": sensitivity_result,
        "receiver_range_worst_severity_after": str(worst_receiver),
        "donor_residual_range_driven_high_horizons": residual_high,
        "donor_severity_after": _entity_summary(donor_after)["displayed_severity"],
    }


def _policy_upper_bound(value: float, guard_max_steps: int) -> CertifiedBound:
    algebraic = _fraction(value)
    return _certify_upper(algebraic, lambda candidate: candidate <= value, guard_max_steps)


def _total_budget_upper_bound(
    donor_total: float,
    maximum: float | None,
    guard_max_steps: int,
) -> CertifiedBound:
    algebraic = Fraction(1) if maximum is None else min(Fraction(1), _fraction(maximum) / _fraction(donor_total))
    return _certify_upper(
        algebraic,
        lambda candidate: maximum is None or candidate * donor_total <= maximum,
        guard_max_steps,
    )


def _final_certification(
    donor: pd.DataFrame,
    receiver: pd.DataFrame,
    phi: float,
    donor_minimum: DonorMinimum,
    receiver_maximum: ReceiverMaximum,
    fraction_budget: CertifiedBound,
    total_budget: CertifiedBound,
    max_total: float | None,
) -> tuple[bool, bool]:
    """Return (all constraints pass, failure is an upper/domain/conservation failure)."""
    fast = fast_evaluate(
        donor,
        receiver,
        phi,
        donor_minimum,
        receiver_maximum,
        fraction_budget.value,
        max_total,
    )
    upper_ok = (
        0 <= phi <= 1
        and phi <= receiver_maximum.value
        and phi <= fraction_budget.value
        and phi <= total_budget.value
        and fast["receiver_no_worse_constraint_satisfied"]
        and fast["budget_constraint_satisfied"]
        and fast["conservation_satisfied"]
    )
    return bool(upper_ok and fast["source_central_goal_satisfied"]), not upper_ok


def _candidate_for_receiver(
    donor: pd.DataFrame,
    receiver: pd.DataFrame,
    donor_minimum: DonorMinimum,
    donor_support: str,
    receiver_support: str,
    max_transfer_fraction: float,
    max_total_synthetic_transfer: float | None,
    guard_max_steps: int,
) -> tuple[InternalCandidate | None, AbstentionCode | None]:
    try:
        receiver_maximum = derive_receiver_maximum(donor, receiver, guard_max_steps)
        fraction_budget = _policy_upper_bound(max_transfer_fraction, guard_max_steps)
        donor_total = float(donor["forecast_value"].sum())
        total_budget = _total_budget_upper_bound(donor_total, max_total_synthetic_transfer, guard_max_steps)
    except ValueError:
        return None, AbstentionCode.PHI_CERTIFICATION_FAILED
    if donor_minimum.value > receiver_maximum.value:
        return None, AbstentionCode.RECEIVER_BLOCKED
    if donor_minimum.value > fraction_budget.value or donor_minimum.value > total_budget.value:
        return None, AbstentionCode.TRANSFER_BUDGET_INSUFFICIENT
    phi = donor_minimum.value
    steps = donor_minimum.certify_up_steps
    while True:
        passed, upper_failure = _final_certification(
            donor,
            receiver,
            phi,
            donor_minimum,
            receiver_maximum,
            fraction_budget,
            total_budget,
            max_total_synthetic_transfer,
        )
        if passed:
            break
        if upper_failure or steps == guard_max_steps:
            return None, AbstentionCode.PHI_CERTIFICATION_FAILED
        phi = math.nextafter(phi, math.inf)
        steps += 1
    fast = fast_evaluate(
        donor,
        receiver,
        phi,
        donor_minimum,
        receiver_maximum,
        max_transfer_fraction,
        max_total_synthetic_transfer,
    )
    tier = "DIRECT_SUPPORTED" if donor_support == receiver_support == "DIRECT_SUPPORTED" else "FALLBACK_LIMITED"
    return (
        InternalCandidate(
            receiver_id=str(receiver.iloc[0]["hospital_id"]),
            receiver_region_id=str(receiver.iloc[0]["region_id"]),
            receiver_series_id=str(receiver.iloc[0]["series_id"]),
            transfer_fraction=phi,
            certify_up_steps=steps,
            receiver_phi_max=receiver_maximum.value,
            receiver_binding_cell=receiver_maximum.binding_cell,
            donor_support_class=donor_support,
            receiver_support_class=receiver_support,
            forecast_support_tier=tier,
            receiver_range_evidence=fast["receiver_range_evidence"],
            fast=fast,
        ),
        None,
    )


def dominates(left: InternalCandidate, right: InternalCandidate) -> bool:
    if (left.forecast_support_tier, left.receiver_range_evidence) != (
        right.forecast_support_tier,
        right.receiver_range_evidence,
    ):
        return False
    left_values = (
        left.fast["transferred_expected_registrations_total"],
        SEVERITY_RANK[left.fast["receiver_worst_severity_after"]],
        left.fast["receiver_min_central_headroom"],
    )
    right_values = (
        right.fast["transferred_expected_registrations_total"],
        SEVERITY_RANK[right.fast["receiver_worst_severity_after"]],
        right.fast["receiver_min_central_headroom"],
    )
    no_worse = (
        left_values[0] <= right_values[0] and left_values[1] <= right_values[1] and left_values[2] >= right_values[2]
    )
    strict = left_values[0] < right_values[0] or left_values[1] < right_values[1] or left_values[2] > right_values[2]
    return bool(no_worse and strict)


def pareto_filter(candidates: Iterable[InternalCandidate]) -> list[InternalCandidate]:
    items = list(candidates)
    return [item for item in items if not any(dominates(other, item) for other in items if other is not item)]


def display_order(candidate: InternalCandidate) -> tuple[Any, ...]:
    return (
        0 if candidate.forecast_support_tier == "DIRECT_SUPPORTED" else 1,
        0 if candidate.receiver_range_evidence == "COMPLETE" else 1,
        candidate.fast["transferred_expected_registrations_total"],
        SEVERITY_RANK[candidate.fast["receiver_worst_severity_after"]],
        -candidate.fast["receiver_min_central_headroom"],
        candidate.receiver_region_id,
        candidate.receiver_id,
        candidate.receiver_series_id,
    )


def _compare_fast_full(candidate: InternalCandidate, result: Any, donor: pd.DataFrame) -> None:
    donor_id = str(donor.iloc[0]["hospital_id"])
    donor_series_id = str(donor.iloc[0]["series_id"])
    keys = ["hospital_id", "horizon"]
    full_pair: dict[str, pd.DataFrame] = {}
    for hospital_id, series_id in (
        (donor_id, donor_series_id),
        (candidate.receiver_id, candidate.receiver_series_id),
    ):
        full = _ordered_daily(
            result.daily_cells[result.daily_cells["target"].eq(TARGET) & result.daily_cells["series_id"].eq(series_id)]
        )
        state_name = "scenario_donor_state" if hospital_id == donor_id else "scenario_receiver_state"
        fast_cells = pd.DataFrame(candidate.fast[state_name]["cells"])
        if len(full) != 14 or len(fast_cells) != 14:
            raise ValueError("full verification cell alignment differs from the fast evaluator")
        for fast_row, full_row in zip(fast_cells.itertuples(index=False), full.itertuples(index=False), strict=True):
            if int(fast_row.horizon) != int(full_row.horizon):
                raise ValueError(f"full verification {keys} differ")
            numeric = {
                "central": full_row.scenario_central,
                "sensitivity_lower": full_row.scenario_sensitivity_lower,
                "sensitivity_upper": full_row.scenario_sensitivity_upper,
                "threshold_value": full_row.threshold_value,
            }
            for field, full_value in numeric.items():
                fast_value = getattr(fast_row, field)
                if fast_value is None and pd.isna(full_value):
                    continue
                if (
                    fast_value is None
                    or pd.isna(full_value)
                    or not math.isclose(float(fast_value), float(full_value), abs_tol=FLOAT_TOLERANCE, rel_tol=0)
                ):
                    raise ValueError(f"full verification mismatch: {hospital_id}.{field}")
            categorical = {
                "severity": full_row.severity,
                "source_reason_code": full_row.source_reason_code,
                "scenario_uncertainty_status": full_row.scenario_uncertainty_status,
                "scenario_uncertainty_method": full_row.scenario_uncertainty_method,
            }
            for field, full_value in categorical.items():
                if str(getattr(fast_row, field)) != str(full_value):
                    raise ValueError(f"full verification mismatch: {hospital_id}.{field}")
        full_pair[hospital_id] = full
    entities = result.entity_signals[
        result.entity_signals["target"].eq(TARGET)
        & result.entity_signals["profile_id"].astype(str).eq(str(donor.iloc[0]["profile_id"]))
    ].set_index("hospital_id")
    for hospital_id, state_name in (
        (donor_id, "scenario_donor_state"),
        (candidate.receiver_id, "scenario_receiver_state"),
    ):
        row = entities.loc[hospital_id]
        fast_state = candidate.fast[state_name]
        for field in (
            "displayed_severity",
            "max_severity_7d",
            "max_severity_14d",
            "severity_evidence_horizon",
        ):
            full_field = "severity" if field == "displayed_severity" else field
            if str(fast_state[field]) != str(row[full_field]):
                raise ValueError(f"full verification mismatch: {hospital_id}.{field}")
    if not result.validation["hierarchy_coherence"]["within_tolerance"]:
        raise ValueError("full verification hierarchy is not coherent")
    if not result.validation["conservation"]["status"] == "PASS":
        raise ValueError("full verification conservation failed")
    if result.validation["scope_invariance"]["status"] != "PASS":
        raise ValueError("full verification scope invariance failed")
    if result.validation["scope_invariance"]["unexpected_changed_cells"] != 0:
        raise ValueError("full verification changed registration cells outside the specified transfer scope")
    lever = result.metadata["levers"][0]
    if not math.isclose(
        float(lever["transferred_total"]),
        candidate.fast["transferred_expected_registrations_total"],
        abs_tol=FLOAT_TOLERANCE,
        rel_tol=0,
    ):
        raise ValueError("full verification transferred total differs from the fast evaluator")
    donor_full = full_pair[donor_id]
    receiver_full = full_pair[candidate.receiver_id]
    before = donor_full["baseline_central"].to_numpy(float) + receiver_full["baseline_central"].to_numpy(float)
    after = donor_full["scenario_central"].to_numpy(float) + receiver_full["scenario_central"].to_numpy(float)
    full_conservation_error = max(
        float(np.abs(after - before).max(initial=0.0)),
        abs(float(after.sum()) - float(before.sum())),
    )
    if not math.isclose(
        full_conservation_error,
        candidate.fast["pair_conservation_max_absolute_error"],
        abs_tol=FLOAT_TOLERANCE,
        rel_tol=0,
    ):
        raise ValueError("full verification conservation error differs from the fast evaluator")


def _verification_only_fields(
    result: Any,
    donor_id: str,
    receiver_id: str,
    profile_id: str,
) -> dict[str, Any]:
    entity = result.entity_differences[
        result.entity_differences["target"].eq(TARGET)
        & result.entity_differences["profile_id"].astype(str).eq(profile_id)
    ].set_index("hospital_id")

    def fields(hospital_id: str) -> dict[str, Any]:
        row = entity.loc[hospital_id]
        return {
            "baseline_inbox_rank": int(row["baseline_inbox_rank"]) if pd.notna(row["baseline_inbox_rank"]) else None,
            "scenario_inbox_rank": int(row["scenario_inbox_rank"]) if pd.notna(row["scenario_inbox_rank"]) else None,
            "entered_primary_inbox": bool(row["entered_primary_inbox"]),
            "left_primary_inbox": bool(row["left_primary_inbox"]),
            "baseline_severity": str(row["baseline_severity"]),
            "scenario_severity": str(row["scenario_severity"]),
        }

    inbox_views = pd.concat([result.inbox, result.unsupported, result.low_volume_attention], ignore_index=True)
    inbox_views = inbox_views[inbox_views["profile_id"].astype(str).eq(profile_id)]
    materiality = {}
    for hospital_id in (donor_id, receiver_id):
        rows = inbox_views[inbox_views["hospital_id"].eq(hospital_id)]
        materiality[hospital_id] = str(rows.iloc[0]["materiality_status"]) if not rows.empty else "NOT_OBSERVED"
    return {
        "donor_inbox": fields(donor_id),
        "receiver_inbox": fields(receiver_id),
        "materiality_status": materiality,
        "hierarchy_coherence": result.validation["hierarchy_coherence"],
        "daily_difference_summary": {
            "changed_cells": int(result.daily_differences["severity_changed"].sum()),
        },
        "entity_difference_summary": {
            "changed_entities": int(result.entity_differences["severity_changed"].sum()),
        },
    }


def _explanation(candidate: InternalCandidate, donor_minimum: DonorMinimum) -> dict[str, Any]:
    receiver_binding = (
        (
            f"Receiver horizon {candidate.receiver_binding_cell['horizon']} and predicate "
            f"{candidate.receiver_binding_cell['predicate']} define its certified upper bound."
        )
        if candidate.receiver_binding_cell is not None
        else "No receiver breakpoint applies before fraction 1."
    )
    text = (
        f"Moving a synthetic fraction {candidate.transfer_fraction:.17g} of this hospital/profile's expected "
        f"registrations to {candidate.receiver_id} for the same profile and target dates moves "
        f"{candidate.fast['transferred_expected_registrations_total']:.17g} total synthetic expected "
        "registrations and removes the donor's "
        f"central historical-flow threshold exceedance on horizons {list(donor_minimum.binding_horizons)}, with "
        f"horizon {donor_minimum.binding_horizon} binding. Under the accepted historical-flow proxy, no affected "
        f"receiver day has a modelled state higher than its baseline state. {receiver_binding} The same-profile, "
        "same-date total is "
        f"conserved within {FLOAT_TOLERANCE:.0e}. Donor evidence: {candidate.donor_support_class}. Receiver evidence: "
        f"{candidate.receiver_support_class}. Forecast support tier: {candidate.forecast_support_tier}; independent "
        f"receiver range evidence: {candidate.receiver_range_evidence}. Derived scenario sensitivity range result: "
        f"{candidate.fast['sensitivity_range_result']}; this range is not re-calibrated and carries no probability, "
        "confidence level, or coverage guarantee. Physical feasibility is unknown and physical capacity was not "
        "checked; the receiver's historical-flow threshold was estimated without this synthetic flow. This is a "
        "mathematical alternative under stated constraints, requires human review, and is not an action, instruction, "
        "or recommendation."
    )
    non_claims = [
        "Clearing central exceedance does not imply a NORMAL donor state.",
        "Clearing central exceedance does not establish that the donor leaves the primary Inbox.",
        "No real-world improvement is claimed.",
    ]
    if candidate.fast["donor_residual_range_driven_high_horizons"]:
        non_claims.append("Range-driven HIGH evidence remains on one or more donor horizons.")
    return {"text": text, "non_claims": non_claims}


def _public_alternative(
    candidate: InternalCandidate,
    donor: pd.DataFrame,
    receiver: pd.DataFrame,
    donor_minimum: DonorMinimum,
    canonical_unit_id: str,
    search_policy: dict[str, Any],
    constraint_policy: dict[str, Any],
    provenance: dict[str, Any],
    verification: VerificationCacheEntry,
) -> dict[str, Any]:
    if not verification.succeeded or verification.scientific_output_sha256 is None:
        raise ValueError("public alternatives require a successful compact verification record")
    donor_id = str(donor.iloc[0]["hospital_id"])
    identity = {
        "canonical_unit_id": canonical_unit_id,
        "receiver_hospital_id": candidate.receiver_id,
        "donor_goal": DONOR_GOAL,
        "search_policy_identity": search_policy["identity_sha256"],
        "constraint_policy_identity": constraint_policy["identity_sha256"],
        "phi_hex": candidate.transfer_fraction.hex(),
    }
    return {
        "alternative_id": _canonical_hash(identity),
        "donor": {
            "hospital_id": donor_id,
            "region_id": str(donor.iloc[0]["region_id"]),
            "profile_id": str(donor.iloc[0]["profile_id"]),
            "series_id": str(donor.iloc[0]["series_id"]),
        },
        "receiver": {
            "hospital_id": candidate.receiver_id,
            "region_id": candidate.receiver_region_id,
            "profile_id": str(receiver.iloc[0]["profile_id"]),
            "series_id": candidate.receiver_series_id,
        },
        "transfer_fraction": candidate.transfer_fraction,
        "transfer_fraction_decimal": format(candidate.transfer_fraction, ".17g"),
        "phi_hex": candidate.transfer_fraction.hex(),
        "certify_up_steps": candidate.certify_up_steps,
        "transfer_fraction_certification": TRANSFER_CERTIFICATION,
        "transferred_expected_registrations_total": candidate.fast["transferred_expected_registrations_total"],
        "transferred_by_horizon": candidate.fast["transferred_by_horizon"],
        "baseline_donor_state": candidate.fast["baseline_donor_state"],
        "scenario_donor_state": candidate.fast["scenario_donor_state"],
        "baseline_receiver_state": candidate.fast["baseline_receiver_state"],
        "scenario_receiver_state": candidate.fast["scenario_receiver_state"],
        "source_central_goal_satisfied": candidate.fast["source_central_goal_satisfied"],
        "receiver_no_worse_constraint_satisfied": candidate.fast["receiver_no_worse_constraint_satisfied"],
        "budget_constraint_satisfied": candidate.fast["budget_constraint_satisfied"],
        "conservation_satisfied": candidate.fast["conservation_satisfied"],
        "donor_support_class": candidate.donor_support_class,
        "receiver_support_class": candidate.receiver_support_class,
        "receiver_min_central_headroom": candidate.fast["receiver_min_central_headroom"],
        "receiver_worst_severity_after": candidate.fast["receiver_worst_severity_after"],
        "decision_basis": DECISION_BASIS,
        "forecast_support_tier": candidate.forecast_support_tier,
        "receiver_range_evidence": candidate.receiver_range_evidence,
        "sensitivity_range_result": candidate.fast["sensitivity_range_result"],
        "range_recalibrated": False,
        "coverage_guarantee": False,
        "feasibility_status": FEASIBILITY_STATUS,
        "capacity_checked": False,
        "causal_effect_claimed": False,
        "verification_state": VERIFIED,
        "human_review_required": True,
        "explanation": _explanation(candidate, donor_minimum),
        "provenance": provenance
        | {
            "verification_scenario": verification.scenario_spec_scientific_payload(),
            "scenario_scientific_output_sha256": verification.scientific_output_sha256,
        },
        "execution_mode": EXECUTION_MODE,
        "serving_claim": False,
        "donor_binding_cell": donor_minimum.binding_cell,
        "donor_binding_horizons": list(donor_minimum.binding_horizons),
        "donor_zero_threshold_binding_present": donor_minimum.zero_threshold_binding_present,
        "donor_residual_range_driven_high_horizons": candidate.fast["donor_residual_range_driven_high_horizons"],
        "donor_severity_after": candidate.fast["donor_severity_after"],
        "receiver_binding_cell": candidate.receiver_binding_cell,
        "receiver_phi_max": candidate.receiver_phi_max,
        "receiver_range_masking_present": candidate.fast["receiver_range_masking_present"],
        "receiver_range_worst_severity_after": candidate.fast["receiver_range_worst_severity_after"],
        "pair_conservation_max_absolute_error": candidate.fast["pair_conservation_max_absolute_error"],
        "limitations": LIMITATIONS,
        "verification_only_fields": verification.verification_only_fields(),
    }


def _verification_spec(
    donor: pd.DataFrame,
    candidate: InternalCandidate,
    scenario_contract_version: str,
    baseline_provenance: BaselineProvenance,
) -> ScenarioSpec:
    donor_row = donor.iloc[0]
    phi_id = candidate.transfer_fraction.hex().replace(".", "_")
    return ScenarioSpec(
        scenario_id=f"decision-alternative-{candidate.receiver_id}-{phi_id}",
        scenario_version=scenario_contract_version,
        scenario_type="inflow_transfer",
        classification=ScenarioClassification.MECHANISTIC_ACCOUNTING_SCENARIO,
        baseline_provenance=baseline_provenance,
        scope=ScenarioScope(
            scope_type=ScopeType.REGION_PROFILE,
            region_id=str(donor_row["region_id"]),
            profile_id=str(donor_row["profile_id"]),
            horizon_start=1,
            horizon_end=14,
        ),
        parameters={
            "source_hospital_id": str(donor_row["hospital_id"]),
            "destination_hospital_id": candidate.receiver_id,
            "source_profile_id": str(donor_row["profile_id"]),
            "destination_profile_id": str(donor_row["profile_id"]),
            "fraction": candidate.transfer_fraction,
        },
        created_at=dt.datetime(2000, 1, 1, tzinfo=dt.UTC),
    )


def _donor_rejection(donor_signal: pd.Series, donor: pd.DataFrame, include_fallback: bool) -> AbstentionCode | None:
    if str(donor_signal.get("target")) != TARGET:
        return AbstentionCode.UNSUPPORTED_SIGNAL
    if donor_signal.get("operational_priority_status") in {
        "zero_baseline_low_volume",
        "unsupported_data_quality",
    }:
        return AbstentionCode.DONOR_NOT_MATERIALLY_ELIGIBLE
    if donor_signal.get("operational_priority_status") != "primary_inbox_eligible":
        return AbstentionCode.DONOR_NOT_MATERIALLY_ELIGIBLE
    if donor_signal.get("threshold_status") != "supported":
        return AbstentionCode.UNSUPPORTED_SIGNAL
    support = _normalized_support(donor_signal.get("priority_support_class"))
    if support is None:
        return AbstentionCode.INSUFFICIENT_SUPPORT
    if support == "FALLBACK_LIMITED" and not include_fallback:
        return AbstentionCode.DONOR_TIER_EXCLUDED
    if not donor_binding_horizons(donor):
        return AbstentionCode.DONOR_NOT_CENTRAL_DRIVEN
    if donor_signal.get("source_severity", donor_signal.get("severity")) not in {"ELEVATED", "HIGH"}:
        return AbstentionCode.UNSUPPORTED_SIGNAL
    return None


def _receiver_groups(
    baseline_daily: pd.DataFrame,
    donor: pd.DataFrame,
) -> list[tuple[str, pd.DataFrame]]:
    first = donor.iloc[0]
    frame = baseline_daily[
        baseline_daily["target"].eq(TARGET)
        & baseline_daily["level"].eq("hospital")
        & baseline_daily["origin"].eq(first["origin"])
        & baseline_daily["profile_id"].eq(first["profile_id"])
        & baseline_daily["phase"].eq(first["phase"])
        & baseline_daily["hospital_id"].ne(first["hospital_id"])
    ]
    return [(str(hospital_id), _ordered_daily(part)) for hospital_id, part in frame.groupby("hospital_id", sort=True)]


def _shortlist(
    candidates: list[InternalCandidate],
    maximum: int,
) -> tuple[list[InternalCandidate], list[dict[str, Any]]]:
    selected: list[InternalCandidate] = []
    dropped: list[dict[str, Any]] = []
    strata: dict[tuple[str, str], list[InternalCandidate]] = {}
    for candidate in sorted(candidates, key=display_order):
        strata.setdefault((candidate.forecast_support_tier, candidate.receiver_range_evidence), []).append(candidate)
    for stratum in sorted(strata, key=lambda item: (item[0] != "DIRECT_SUPPORTED", item[1] != "COMPLETE")):
        ordered = strata[stratum]
        selected.extend(ordered[:maximum])
        dropped.extend(
            {
                "receiver_hospital_id": item.receiver_id,
                "forecast_support_tier": item.forecast_support_tier,
                "receiver_range_evidence": item.receiver_range_evidence,
                "reason": "SHORTLIST_BOUND",
            }
            for item in ordered[maximum:]
        )
    return sorted(selected, key=display_order), dropped


def _is_sha256(value: Any) -> bool:
    text = str(value)
    return len(text) == 64 and all(character in "0123456789abcdef" for character in text)


def _validate_provenance(provenance: dict[str, Any], config: DecisionAlternativesConfig) -> None:
    required = {
        "accepted_source_run_ids",
        "scenario_contract_version",
        "scenario_scientific_identity",
        "decision_config_identity_sha256",
        "code_identity_sha256",
        "execution_mode",
    }
    missing = sorted(required - set(provenance))
    if missing:
        raise ValueError(f"decision alternative provenance is missing required fields: {missing}")
    if provenance["accepted_source_run_ids"] != ACCEPTED_SOURCE_RUN_IDS:
        raise ValueError("decision alternative provenance does not reference the exact accepted source runs")
    if provenance["scenario_contract_version"] != config.scenario_contract_version:
        raise ValueError("decision alternative provenance has an incompatible scenario contract")
    if provenance["decision_config_identity_sha256"] != config.identity_sha256:
        raise ValueError("decision alternative provenance has a different decision configuration identity")
    for field in ("scenario_scientific_identity", "decision_config_identity_sha256", "code_identity_sha256"):
        if not _is_sha256(provenance[field]):
            raise ValueError(f"decision alternative provenance field {field} is not a SHA256 identity")
    if provenance["execution_mode"] != EXECUTION_MODE:
        raise ValueError("decision alternative provenance must use EVALUATION execution mode")


def _verification_cache_key(
    donor: pd.DataFrame,
    candidate: InternalCandidate,
    config: DecisionAlternativesConfig,
    provenance: dict[str, Any],
) -> VerificationCacheKey:
    row = donor.iloc[0]
    return VerificationCacheKey(
        origin=pd.Timestamp(row["origin"]).date().isoformat(),
        phase=str(row["phase"]),
        target=TARGET,
        region_id=str(row["region_id"]),
        profile_id=str(row["profile_id"]),
        donor_hospital_id=str(row["hospital_id"]),
        donor_series_id=str(row["series_id"]),
        receiver_hospital_id=candidate.receiver_id,
        receiver_series_id=candidate.receiver_series_id,
        phi_hex=candidate.transfer_fraction.hex(),
        scenario_contract_version=config.scenario_contract_version,
        hierarchy_run_id=config.source_hierarchy_run,
        pressure_run_id=config.source_pressure_run,
        prioritization_run_id=config.source_prioritization_run,
        scenario_run_id=config.source_scenario_run,
        scenario_scientific_identity=str(provenance["scenario_scientific_identity"]),
        decision_config_identity_sha256=str(provenance["decision_config_identity_sha256"]),
        code_identity_sha256=str(provenance["code_identity_sha256"]),
    )


def _receiver_zero_threshold_diagnostic(receiver: pd.DataFrame, donor: pd.DataFrame) -> dict[str, Any]:
    affected_horizons = set(donor.loc[donor["forecast_value"].gt(0), "horizon"].astype(int))
    cells = receiver.loc[
        receiver["horizon"].astype(int).isin(affected_horizons)
        & receiver["threshold_status"].eq("supported")
        & receiver["threshold_value"].eq(0)
    ]
    return {
        "zero_threshold_baseline_severities": {
            severity: int(cells["severity"].eq(severity).sum()) for severity in ("NORMAL", "ELEVATED", "HIGH")
        }
    }


def generate_decision_alternative_set(
    *,
    baseline_daily: pd.DataFrame,
    baseline_entity: pd.DataFrame,
    donor_signal: pd.Series | dict[str, Any],
    anomalies: pd.DataFrame,
    pressure_config: FlowPressureConfig,
    prioritization_config: SignalPrioritizationConfig,
    config: DecisionAlternativesConfig,
    max_transfer_fraction: float,
    provenance: dict[str, Any],
    full_evaluator: Callable[..., Any] = evaluate_scenario,
    verification_cache: FullVerificationCache | None = None,
) -> dict[str, Any]:
    """Generate one canonical alternative set; an empty set is a complete valid result."""
    _validate_provenance(provenance, config)
    verification_cache = verification_cache or FullVerificationCache()
    signal = pd.Series(donor_signal)
    donor_mask = (
        baseline_daily["target"].eq(TARGET)
        & baseline_daily["level"].eq("hospital")
        & baseline_daily["origin"].eq(signal["origin"])
        & baseline_daily["hospital_id"].astype(str).eq(str(signal["hospital_id"]))
        & baseline_daily["profile_id"].astype(str).eq(str(signal["profile_id"]))
    )
    if "phase" in signal and pd.notna(signal["phase"]):
        donor_mask &= baseline_daily["phase"].eq(signal["phase"])
    donor = _ordered_daily(baseline_daily[donor_mask])
    donor_ref = {
        "signal_id": str(signal.get("signal_id", "")),
        "hospital_id": str(signal["hospital_id"]),
        "profile_id": str(signal["profile_id"]),
        "target": PUBLIC_TARGET,
        "origin": pd.Timestamp(signal["origin"]).date().isoformat(),
        "displayed_severity": str(signal.get("source_severity", signal.get("severity"))),
        "priority_support_class": str(signal.get("priority_support_class")),
        "operational_priority_status": str(signal.get("operational_priority_status")),
        "materiality_status": str(signal.get("materiality_status")),
        "binding_horizons": list(donor_binding_horizons(donor)) if not donor.empty else [],
    }
    search_policy = {
        "donor_cohort_rule": config.donor_cohort.model_dump(mode="json"),
        "receiver_candidate_rule": config.receiver_policy.model_dump(mode="json"),
        "donor_goal": DONOR_GOAL,
        "decision_basis": DECISION_BASIS,
        "algorithm": ALGORITHM,
        "pareto_dimensions": [
            "total_synthetic_flow_moved:minimize",
            "receiver_worst_severity_after:minimize",
            "receiver_min_central_headroom:maximize",
        ],
        "display_order": [
            "forecast_support_tier",
            "receiver_range_evidence",
            "transferred_expected_registrations_total",
            "receiver_worst_severity_after",
            "receiver_min_central_headroom_desc",
            "stable_receiver_id",
        ],
    }
    search_policy["identity_sha256"] = _canonical_hash(search_policy)
    constraint_policy = {
        "scientific_constraint_set_version": OPTIMIZER_CONTRACT_VERSION,
        "receiver_geographic_scope": "SAME_REGION",
        "max_transfer_fraction": max_transfer_fraction,
        "max_total_synthetic_transfer": config.max_total_synthetic_transfer,
        "eligible_receiver_ids": config.receiver_policy.eligible_receiver_ids,
        "phi_guard_max_steps": config.phi_guard_max_steps,
        "float_tolerance": config.float_tolerance,
        "policy_budget_not_physical_capacity": True,
    }
    constraint_policy["identity_sha256"] = _canonical_hash(constraint_policy)
    canonical_identity = {
        "optimizer_contract_version": OPTIMIZER_CONTRACT_VERSION,
        "origin": donor_ref["origin"],
        "target": PUBLIC_TARGET,
        "profile_id": donor_ref["profile_id"],
        "donor_hospital_id": donor_ref["hospital_id"],
        "donor_goal": DONOR_GOAL,
        "search_policy_identity": search_policy["identity_sha256"],
        "constraint_policy_identity": constraint_policy["identity_sha256"],
    }
    canonical_unit_id = _canonical_hash(canonical_identity)
    base = {
        "optimizer_contract_version": OPTIMIZER_CONTRACT_VERSION,
        "canonical_unit_id": canonical_unit_id,
        "origin": donor_ref["origin"],
        "target": PUBLIC_TARGET,
        "profile": donor_ref["profile_id"],
        "donor_signal_ref": donor_ref,
        "search_policy": search_policy,
        "constraint_policy": constraint_policy,
        "alternatives": [],
        "alternatives_dropped_by_shortlist_bound": [],
        "verification_failures": [],
        "provenance": provenance | {"execution_mode": EXECUTION_MODE},
        "human_review_required": True,
        "execution_mode": EXECUTION_MODE,
        "serving_claim": False,
        "limitations": LIMITATIONS,
    }

    def finish(
        codes: list[AbstentionCode],
        rejected: list[dict[str, Any]],
        considered: int,
        eligible: int,
        donor_minimum: DonorMinimum | None,
    ) -> dict[str, Any]:
        counts: dict[str, int] = {}
        support_pairs: dict[str, int] = {}
        for alternative in base["alternatives"]:
            key = f"{alternative['forecast_support_tier']}|{alternative['receiver_range_evidence']}"
            counts[key] = counts.get(key, 0) + 1
            pair = f"{alternative['donor_support_class']}|{alternative['receiver_support_class']}"
            support_pairs[pair] = support_pairs.get(pair, 0) + 1
        base["evidence_policy"] = {
            "forecast_support_tier_definition": "floor_of_donor_and_receiver_support",
            "receiver_range_evidence_definition": "usable_range_on_every_affected_receiver_horizon",
            "primary_acceptance_stratum": ["DIRECT_SUPPORTED", "COMPLETE"],
            "stratum_counts": counts,
            "donor_receiver_support_class_pair_counts": support_pairs,
        }
        base["receiver_candidates_considered"] = considered
        base["receiver_candidates_eligible"] = eligible
        base["donor_minimum_transfer_fraction"] = donor_minimum.value if donor_minimum else None
        base["donor_zero_threshold_binding_present"] = (
            donor_minimum.zero_threshold_binding_present if donor_minimum else False
        )
        base["shortlist_bound"] = config.shortlist_max_alternatives
        base.setdefault("alternatives_fast_feasible", 0)
        base.setdefault("alternatives_pareto_surviving", 0)
        base.setdefault("alternatives_shortlisted", 0)
        unique_codes = sorted({code.value for code in codes})
        base["abstention_status"] = {
            "abstained": not bool(base["alternatives"]),
            "codes": unique_codes,
            "rejected_receivers": rejected,
        }
        scientific = {key: value for key, value in base.items() if key != "scientific_output_sha256"}
        base["scientific_output_sha256"] = _canonical_hash(scientific)
        assert_public_contract(base)
        return base

    donor_rejection = _donor_rejection(
        signal,
        donor,
        config.donor_cohort.include_fallback_tier_separately,
    )
    if donor_rejection is not None or not _aligned_window(donor, donor):
        code = donor_rejection or AbstentionCode.INSUFFICIENT_SUPPORT
        return finish([code], [], 0, 0, None)
    try:
        donor_minimum = derive_donor_minimum(donor, config.phi_guard_max_steps)
    except ValueError as exc:
        code = (
            AbstentionCode(str(exc))
            if str(exc) in {item.value for item in AbstentionCode}
            else AbstentionCode.PHI_CERTIFICATION_FAILED
        )
        return finish([code], [], 0, 0, None)
    donor_support = _normalized_support(signal["priority_support_class"])
    if donor_support is None:
        return finish([AbstentionCode.INSUFFICIENT_SUPPORT], [], 0, 0, donor_minimum)

    allow_list = set(config.receiver_policy.eligible_receiver_ids or []) or None
    groups = _receiver_groups(baseline_daily, donor)
    rejected: list[dict[str, Any]] = []
    eligible: list[tuple[pd.DataFrame, str]] = []
    affected = donor["forecast_value"].to_numpy(float) > 0
    entity_index = baseline_entity[
        baseline_entity["target"].eq(TARGET)
        & baseline_entity["origin"].eq(donor.iloc[0]["origin"])
        & baseline_entity["profile_id"].astype(str).eq(str(donor.iloc[0]["profile_id"]))
        & baseline_entity["phase"].eq(donor.iloc[0]["phase"])
    ].set_index("hospital_id")
    for receiver_id, receiver in groups:
        code = None
        if not receiver["region_id"].astype(str).eq(str(donor.iloc[0]["region_id"])).all():
            code = AbstentionCode.RECEIVER_OUTSIDE_SAME_REGION_POLICY
        elif allow_list is not None and receiver_id not in allow_list:
            code = AbstentionCode.RECEIVER_NOT_ALLOW_LISTED
        elif not _aligned_window(receiver, donor):
            code = AbstentionCode.RECEIVER_ALIGNMENT_INCOMPLETE
        elif not bool(np.all(receiver.loc[affected, "threshold_status"].eq("supported"))):
            code = AbstentionCode.RECEIVER_UNSUPPORTED_EVIDENCE
        elif receiver_id not in entity_index.index:
            code = AbstentionCode.INSUFFICIENT_SUPPORT
        else:
            support = _daily_support_class(entity_index.loc[receiver_id])
            if support is None:
                code = AbstentionCode.INSUFFICIENT_SUPPORT
        if code is not None:
            rejected.append(
                {"receiver_hospital_id": receiver_id, "code": code.value}
                | _receiver_zero_threshold_diagnostic(receiver, donor)
            )
        else:
            eligible.append((receiver, support))
    if not eligible:
        codes = [AbstentionCode.NO_ELIGIBLE_RECEIVER]
        if rejected and all(item["code"] == AbstentionCode.RECEIVER_UNSUPPORTED_EVIDENCE.value for item in rejected):
            codes.append(AbstentionCode.INSUFFICIENT_SUPPORT)
        return finish(codes, rejected, len(groups), 0, donor_minimum)

    candidates: list[InternalCandidate] = []
    failure_codes: list[AbstentionCode] = []
    receiver_frames: dict[str, pd.DataFrame] = {}
    for receiver, receiver_support in eligible:
        receiver_id = str(receiver.iloc[0]["hospital_id"])
        receiver_frames[receiver_id] = receiver
        candidate, code = _candidate_for_receiver(
            donor,
            receiver,
            donor_minimum,
            donor_support,
            receiver_support,
            max_transfer_fraction,
            config.max_total_synthetic_transfer,
            config.phi_guard_max_steps,
        )
        if candidate is None:
            assert code is not None
            failure_codes.append(code)
            rejected.append(
                {"receiver_hospital_id": receiver_id, "code": code.value}
                | _receiver_zero_threshold_diagnostic(receiver, donor)
            )
        else:
            candidates.append(candidate)
    pareto = sorted(pareto_filter(candidates), key=display_order)
    base["alternatives_pareto_surviving"] = len(pareto)
    if candidates and not pareto:
        failure_codes.append(AbstentionCode.NO_NON_DOMINATED_ALTERNATIVE)
    shortlisted, dropped = _shortlist(pareto, config.shortlist_max_alternatives)
    base["alternatives_fast_feasible"] = len(candidates)
    base["alternatives_shortlisted"] = len(shortlisted)
    base["alternatives_dropped_by_shortlist_bound"] = dropped
    baseline_provenance = BaselineProvenance(
        hierarchy_run_id=config.source_hierarchy_run,
        pressure_run_id=config.source_pressure_run,
        prioritization_run_id=config.source_prioritization_run,
    )
    verification_context: tuple[pd.DataFrame, pd.DataFrame] | None = None

    def evaluation_context() -> tuple[pd.DataFrame, pd.DataFrame]:
        nonlocal verification_context
        if verification_context is None:
            verification_context = (
                baseline_daily[
                    baseline_daily["origin"].eq(donor.iloc[0]["origin"])
                    & baseline_daily["phase"].eq(donor.iloc[0]["phase"])
                ].copy(),
                anomalies[anomalies["forecast_origin"].eq(donor.iloc[0]["origin"])].copy(),
            )
        return verification_context

    for candidate in shortlisted:
        receiver = receiver_frames[candidate.receiver_id]
        spec = _verification_spec(donor, candidate, config.scenario_contract_version, baseline_provenance)

        def evaluate_full(scenario_spec=spec):
            verification_daily, verification_anomalies = evaluation_context()
            return full_evaluator(
                verification_daily,
                verification_anomalies,
                pressure_config,
                prioritization_config,
                scenario_spec,
            )

        def compact_full(result, internal_candidate=candidate):
            return (
                scenario_spec_scientific_payload(result.spec),
                str(result.validation["scientific_output_sha256"]),
                _verification_only_fields(
                    result,
                    str(donor.iloc[0]["hospital_id"]),
                    internal_candidate.receiver_id,
                    str(donor.iloc[0]["profile_id"]),
                ),
            )

        cache_entry = verification_cache.verify(
            _verification_cache_key(donor, candidate, config, provenance),
            _canonical_hash(candidate.fast),
            evaluate_full,
            lambda result, internal_candidate=candidate: _compare_fast_full(internal_candidate, result, donor),
            compact_full,
        )
        if cache_entry.succeeded:
            base["alternatives"].append(
                _public_alternative(
                    candidate,
                    donor,
                    receiver,
                    donor_minimum,
                    canonical_unit_id,
                    search_policy,
                    constraint_policy,
                    provenance,
                    cache_entry,
                )
            )
        else:
            failure_codes.append(AbstentionCode.FULL_VERIFICATION_FAILED)
            base["verification_failures"].append(
                {
                    "receiver_hospital_id": candidate.receiver_id,
                    "code": cache_entry.failure_code,
                    "detail": cache_entry.failure_detail,
                }
            )
    base["alternatives"] = sorted(
        base["alternatives"],
        key=lambda item: (
            item["forecast_support_tier"] != "DIRECT_SUPPORTED",
            item["receiver_range_evidence"] != "COMPLETE",
            item["transferred_expected_registrations_total"],
            SEVERITY_RANK[item["receiver_worst_severity_after"]],
            -item["receiver_min_central_headroom"],
            item["receiver"]["region_id"],
            item["receiver"]["hospital_id"],
            item["receiver"]["series_id"],
        ),
    )
    if not base["alternatives"] and not failure_codes:
        failure_codes.append(AbstentionCode.NO_NON_DOMINATED_ALTERNATIVE)
    return finish(failure_codes, rejected, len(groups), len(eligible), donor_minimum)


def assert_public_contract(value: dict[str, Any]) -> None:
    """Block internal/failed states, forbidden keys, and safety-semantic drift."""

    def walk(item: Any) -> None:
        if isinstance(item, dict):
            for key, child in item.items():
                lowered = str(key).lower()
                if any(part in lowered for part in FORBIDDEN_PUBLIC_FIELD_PARTS):
                    raise ValueError(f"forbidden public field name: {key}")
                walk(child)
        elif isinstance(item, list):
            for child in item:
                walk(child)

    walk(value)
    provenance = value.get("provenance")
    if not isinstance(provenance, dict):
        raise ValueError("decision alternative set requires public provenance")
    required_provenance = {
        "accepted_source_run_ids",
        "scenario_contract_version",
        "scenario_scientific_identity",
        "decision_config_identity_sha256",
        "code_identity_sha256",
        "execution_mode",
    }
    missing_provenance = sorted(required_provenance - set(provenance))
    if missing_provenance:
        raise ValueError(f"decision alternative set provenance is missing fields: {missing_provenance}")
    if provenance["accepted_source_run_ids"] != ACCEPTED_SOURCE_RUN_IDS:
        raise ValueError("decision alternative set provenance has unaccepted source runs")
    if provenance["scenario_contract_version"] != SCENARIO_CONTRACT_VERSION:
        raise ValueError("decision alternative set provenance has an incompatible scenario contract")
    for field in ("scenario_scientific_identity", "decision_config_identity_sha256", "code_identity_sha256"):
        if not _is_sha256(provenance[field]):
            raise ValueError(f"decision alternative set provenance field {field} is not a SHA256 identity")
    if provenance["execution_mode"] != EXECUTION_MODE:
        raise ValueError("decision alternative set provenance must use EVALUATION execution mode")
    for alternative in value.get("alternatives", []):
        if alternative.get("verification_state") != VERIFIED:
            raise ValueError("every public alternative must be VERIFIED_FULL_ENGINE")
        if alternative.get("verification_only_fields") is None:
            raise ValueError("verified alternatives require verification-only fields")
        fixed = {
            "human_review_required": True,
            "capacity_checked": False,
            "causal_effect_claimed": False,
            "range_recalibrated": False,
            "coverage_guarantee": False,
            "feasibility_status": FEASIBILITY_STATUS,
            "execution_mode": EXECUTION_MODE,
            "serving_claim": False,
        }
        for key, expected in fixed.items():
            if alternative.get(key) != expected:
                raise ValueError(f"public alternative has invalid fixed field {key}")
        explanation = str(alternative.get("explanation", {}).get("text", "")).lower()
        checked = explanation
        for phrase in ALLOWED_NEGATED_EXPLANATION_PHRASES:
            checked = checked.replace(phrase, "")
        illegal = sorted(term for term in FORBIDDEN_EXPLANATION_TERMS if term in checked)
        if illegal:
            raise ValueError(f"public explanation contains prohibited wording: {illegal}")
