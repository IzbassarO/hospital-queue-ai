from __future__ import annotations

import datetime as dt
import hashlib
from pathlib import Path

import numpy as np
import yaml
from pydantic import BaseModel, ConfigDict, model_validator
from scipy.stats import qmc

from hqai_ml.registry.store import canonical_json


class LabelContract(BaseModel):
    start: str
    cutoff: dt.datetime
    same_day_min_duration_days: float
    refusal_is_terminal: bool
    refusal_basis: str
    exclude_event_conflicts: bool
    exclude_events_before_registration: bool


class FoldConfig(BaseModel):
    id: str
    train: tuple[dt.date, dt.date]
    validation: tuple[dt.date, dt.date]
    calibration: tuple[dt.date, dt.date]
    test: tuple[dt.date, dt.date]

    @model_validator(mode="after")
    def ordered(self) -> FoldConfig:
        periods = (self.train, self.validation, self.calibration, self.test)
        if any(start > end for start, end in periods):
            raise ValueError(f"fold {self.id}: period starts after it ends")
        if not all(periods[i][1] < periods[i + 1][0] for i in range(3)):
            raise ValueError(f"fold {self.id}: train/validation/calibration/test must be disjoint and ordered")
        return self


class CandidateConfig(BaseModel):
    enabled: bool
    hpo: bool


class GroupBaselineConfig(BaseModel):
    columns: list[str]
    min_support: int


class ProfileConfig(BaseModel):
    sample_rows: int | None
    max_trials: int
    folds: list[str]
    round_cap: int


class MetricsConfig(BaseModel):
    principal: list[str]
    secondary: list[str]


class PromotionConstraints(BaseModel):
    automatic_promotion: bool
    require_complete_lineage: bool
    require_probability_coherence: bool
    require_calibration_artifacts: bool
    require_regional_comparison: bool
    outcome_if_not_clearly_superior: str


class TournamentConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: int
    seed: int
    legacy_artifacts_trained_through: dt.date
    label_contract: LabelContract
    horizons: list[int]
    time_bins: list[int]
    group_baseline: GroupBaselineConfig
    folds: list[FoldConfig]
    candidates: dict[str, CandidateConfig]
    search_spaces: dict[str, dict]
    metrics: MetricsConfig
    support_buckets: list[int]
    refusal_benchmarks: dict
    profiles: dict[str, ProfileConfig]
    promotion_constraints: PromotionConstraints

    @model_validator(mode="after")
    def validate_policy(self) -> TournamentConfig:
        if self.horizons != sorted(set(self.horizons)) or any(h <= 0 for h in self.horizons):
            raise ValueError("horizons must be unique, ordered, positive days")
        if self.time_bins != sorted(set(self.time_bins)) or self.time_bins[0] != 0:
            raise ValueError("time_bins must be unique, ordered, and start at zero")
        if not set(self.horizons).issubset(self.time_bins):
            raise ValueError("every operational horizon must be a time-bin edge")
        fold_ids = {fold.id for fold in self.folds}
        if len(fold_ids) != len(self.folds):
            raise ValueError("fold IDs must be unique")
        for name, profile in self.profiles.items():
            if not set(profile.folds).issubset(fold_ids):
                raise ValueError(f"profile {name!r} references an unknown fold")
        if self.promotion_constraints.automatic_promotion:
            raise ValueError("the patient-journey tournament must never auto-promote")
        if (
            not self.label_contract.refusal_is_terminal
            and self.candidates.get("discrete_competing_risk", CandidateConfig(enabled=False, hpo=False)).enabled
        ):
            raise ValueError("competing-risk candidate requires validated terminal-refusal semantics")
        return self

    @property
    def identity_sha256(self) -> str:
        payload = self.model_dump(mode="json")
        return hashlib.sha256(canonical_json(payload).encode()).hexdigest()


def load_tournament_config(path: Path) -> TournamentConfig:
    return TournamentConfig(**yaml.safe_load(path.read_text(encoding="utf-8")))


def deterministic_trials(config: TournamentConfig, candidate: str, count: int) -> list[dict]:
    """Generate a deterministic scrambled-Sobol bounded search for a tree candidate."""
    if not config.candidates[candidate].hpo:
        return [{}]
    specification = config.search_spaces[candidate]
    dimensions = specification["dimensions"]
    names = list(dimensions)
    seed_material = hashlib.sha256(f"{config.seed}:{candidate}".encode()).digest()
    seed = int.from_bytes(seed_material[:4], "big")
    points = qmc.Sobol(d=len(names), scramble=True, seed=seed).random(count)
    trials = []
    for point in points:
        parameters = dict(specification.get("fixed", {}))
        for name, unit in zip(names, point, strict=True):
            dimension = dimensions[name]
            kind = dimension["type"]
            if kind == "categorical":
                choices = dimension["choices"]
                parameters[name] = choices[min(int(unit * len(choices)), len(choices) - 1)]
            elif kind == "int":
                low, high = int(dimension["low"]), int(dimension["high"])
                parameters[name] = low + min(int(unit * (high - low + 1)), high - low)
            elif kind == "float":
                low, high = float(dimension["low"]), float(dimension["high"])
                parameters[name] = low + unit * (high - low)
            elif kind == "log_float":
                low, high = float(dimension["low"]), float(dimension["high"])
                parameters[name] = float(np.exp(np.log(low) + unit * (np.log(high) - np.log(low))))
            else:
                raise ValueError(f"unknown search dimension type {kind!r} for {candidate}.{name}")
        trials.append(parameters)
    return trials
