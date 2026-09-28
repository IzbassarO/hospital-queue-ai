from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

from hqai_ml.origin_journey.config import OriginJourneyConfig

EVENT_HOSPITALIZED = "hospitalized"
EVENT_REFUSED = "refused"


@dataclass(frozen=True)
class AJCurve:
    event_times: np.ndarray
    hospitalized_cif: np.ndarray
    refused_cif: np.ndarray
    survival: np.ndarray
    rows: int
    risk_times: np.ndarray
    at_risk_counts: np.ndarray

    @classmethod
    def fit(cls, frame: pd.DataFrame) -> AJCurve:
        duration = frame["observed_duration_days"].to_numpy(float)
        event = frame["event_type_at_origin"].astype(str).to_numpy()
        event_mask = np.isin(event, [EVENT_HOSPITALIZED, EVENT_REFUSED])
        times, inverse = np.unique(duration[event_mask], return_inverse=True)
        event_values = event[event_mask]
        admitted = np.bincount(
            inverse,
            weights=(event_values == EVENT_HOSPITALIZED).astype(np.int64),
            minlength=len(times),
        )
        refused = np.bincount(
            inverse,
            weights=(event_values == EVENT_REFUSED).astype(np.int64),
            minlength=len(times),
        )
        sorted_duration = np.sort(duration)
        at_risk = len(duration) - np.searchsorted(sorted_duration, times, side="left")
        survival = 1.0
        cif_h = 0.0
        cif_r = 0.0
        survival_values = np.empty(len(times), dtype=float)
        hospitalized_values = np.empty(len(times), dtype=float)
        refused_values = np.empty(len(times), dtype=float)
        for index in range(len(times)):
            risk = at_risk[index]
            if risk:
                cif_h += survival * admitted[index] / risk
                cif_r += survival * refused[index] / risk
                survival *= 1 - (admitted[index] + refused[index]) / risk
            hospitalized_values[index] = cif_h
            refused_values[index] = cif_r
            survival_values[index] = survival
        risk_times, risk_counts = np.unique(duration, return_counts=True)
        at_risk_counts = np.cumsum(risk_counts[::-1])[::-1]
        return cls(
            times,
            hospitalized_values,
            refused_values,
            survival_values,
            len(frame),
            risk_times,
            at_risk_counts,
        )

    def at_risk(self, day: float) -> int:
        """Origin-safe count still under observation immediately before ``day``."""
        position = int(np.searchsorted(self.risk_times, day, side="left"))
        if position >= len(self.risk_times):
            return 0
        return int(self.at_risk_counts[position])

    def state(self, days: np.ndarray | float) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        values = np.asarray(days, dtype=float)
        flat = values.reshape(-1)
        positions = np.searchsorted(self.event_times, flat, side="right") - 1
        valid = positions >= 0
        hospitalized = np.zeros(len(flat), dtype=float)
        refused = np.zeros(len(flat), dtype=float)
        survival = np.ones(len(flat), dtype=float)
        hospitalized[valid] = self.hospitalized_cif[positions[valid]]
        refused[valid] = self.refused_cif[positions[valid]]
        survival[valid] = self.survival[positions[valid]]
        shape = values.shape
        return hospitalized.reshape(shape), refused.reshape(shape), survival.reshape(shape)

    def to_dict(self) -> dict[str, Any]:
        return {
            "rows": self.rows,
            "event_times": self.event_times.tolist(),
            "hospitalized_cif": self.hospitalized_cif.tolist(),
            "refused_cif": self.refused_cif.tolist(),
            "survival": self.survival.tolist(),
            "risk_times": self.risk_times.tolist(),
            "at_risk_counts": self.at_risk_counts.tolist(),
        }


def _key(values: tuple[Any, ...]) -> tuple[str, ...]:
    return tuple("<missing>" if pd.isna(value) else str(value) for value in values)


@dataclass(frozen=True)
class HierarchicalAJ:
    hierarchy: tuple[tuple[str, ...], ...]
    min_rows: int
    global_curve: AJCurve
    curves: tuple[dict[tuple[str, ...], AJCurve], ...]

    @classmethod
    def fit(cls, training: pd.DataFrame, config: OriginJourneyConfig) -> HierarchicalAJ:
        eligible = training.loc[training["label_eligible"]].copy()
        levels: list[dict[tuple[str, ...], AJCurve]] = []
        for columns in config.baseline.hierarchy:
            fitted = {}
            grouper: str | list[str] = columns[0] if len(columns) == 1 else list(columns)
            for raw_key, group in eligible.groupby(grouper, dropna=False, sort=True):
                key_values = raw_key if isinstance(raw_key, tuple) else (raw_key,)
                if len(group) >= config.baseline.min_rows:
                    fitted[_key(key_values)] = AJCurve.fit(group)
            levels.append(fitted)
        return cls(
            hierarchy=config.baseline.hierarchy,
            min_rows=config.baseline.min_rows,
            global_curve=AJCurve.fit(eligible),
            curves=tuple(levels),
        )

    def _curve_for_row(self, row: tuple[Any, ...], columns: tuple[str, ...]) -> tuple[str, tuple[str, ...], AJCurve]:
        values = dict(zip(columns, row, strict=True))
        for level_columns, level_curves in zip(self.hierarchy, self.curves, strict=True):
            key = _key(tuple(values[column] for column in level_columns))
            curve = level_curves.get(key)
            if curve is not None:
                return "x".join(level_columns), key, curve
        return "global", (), self.global_curve

    def assignments(self, scoring: pd.DataFrame) -> list[tuple[str, tuple[str, ...], AJCurve]]:
        columns = tuple(dict.fromkeys(column for level in self.hierarchy for column in level))
        return [self._curve_for_row(row, columns) for row in scoring[list(columns)].itertuples(index=False, name=None)]

    def probabilities(
        self, scoring: pd.DataFrame, horizons: tuple[int, ...]
    ) -> tuple[dict[int, dict[str, np.ndarray]], list[str]]:
        assignments = self.assignments(scoring)
        waited = scoring["days_waited_at_origin"].to_numpy(float)
        output = {
            horizon: {
                "hospitalized": np.zeros(len(scoring), dtype=float),
                "refused": np.zeros(len(scoring), dtype=float),
                "unresolved": np.ones(len(scoring), dtype=float),
            }
            for horizon in horizons
        }
        grouped: dict[int, tuple[AJCurve, list[int]]] = {}
        for index, (_, _, curve) in enumerate(assignments):
            identifier = id(curve)
            if identifier not in grouped:
                grouped[identifier] = (curve, [])
            grouped[identifier][1].append(index)
        for curve, indexes_list in grouped.values():
            indexes = np.asarray(indexes_list, dtype=int)
            start_h, start_r, start_s = curve.state(waited[indexes])
            denominator = np.clip(start_s, 1e-12, None)
            for horizon in horizons:
                end_h, end_r, end_s = curve.state(waited[indexes] + horizon)
                output[horizon]["hospitalized"][indexes] = np.clip((end_h - start_h) / denominator, 0, 1)
                output[horizon]["refused"][indexes] = np.clip((end_r - start_r) / denominator, 0, 1)
                output[horizon]["unresolved"][indexes] = np.clip(end_s / denominator, 0, 1)
        levels = [assignment[0] for assignment in assignments]
        return output, levels

    def admission_intervals(self, scoring: pd.DataFrame, coverage: float, max_day: int) -> pd.DataFrame:
        waited = scoring["days_waited_at_origin"].to_numpy(float)
        lower_q = (1 - coverage) / 2
        upper_q = 1 - lower_q
        lower = np.full(len(scoring), np.nan)
        upper = np.full(len(scoring), np.nan)
        future_mass = np.zeros(len(scoring), dtype=float)
        for index, (_, _, curve) in enumerate(self.assignments(scoring)):
            start_h = float(curve.state(waited[index])[0])
            end_h = float(curve.state(float(max_day))[0])
            mass = max(0.0, end_h - start_h)
            future_mass[index] = mass
            if mass <= 1e-12:
                continue
            for quantile, target in ((lower_q, lower), (upper_q, upper)):
                threshold = start_h + quantile * mass
                position = int(np.searchsorted(curve.hospitalized_cif, threshold, side="left"))
                if position < len(curve.event_times):
                    target[index] = max(0.0, curve.event_times[position] - waited[index])
        return pd.DataFrame(
            {
                "admission_interval_lower_days": lower,
                "admission_interval_upper_days": upper,
                "admission_interval_width_days": upper - lower,
                "future_admission_mass_through_grid": future_mass,
            }
        )

    def to_dict(self) -> dict[str, Any]:
        levels = []
        for columns, curves in zip(self.hierarchy, self.curves, strict=True):
            levels.append(
                {
                    "columns": list(columns),
                    "curves": [{"key": list(key), **curve.to_dict()} for key, curve in sorted(curves.items())],
                }
            )
        return {
            "method": "aalen_johansen",
            "min_rows": self.min_rows,
            "global_curve": self.global_curve.to_dict(),
            "levels": levels,
        }
