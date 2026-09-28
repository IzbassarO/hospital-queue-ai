from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

CATEGORICAL_FEATURES = (
    "region_code",
    "org_code",
    "hospital_region_code",
    "profile_code",
    "icd10_code",
    "territorial_type",
    "referral_purpose",
    "finance_source",
)
NUMERIC_FEATURES = ("registration_weekday", "registration_day_index")
MODEL_FEATURES = CATEGORICAL_FEATURES + NUMERIC_FEATURES


@dataclass(frozen=True)
class FeatureEncoder:
    categories: dict[str, tuple[str, ...]]

    @classmethod
    def fit(cls, frame: pd.DataFrame) -> FeatureEncoder:
        missing = sorted(set(MODEL_FEATURES) - set(frame.columns))
        if missing:
            raise ValueError(f"model features missing: {missing}")
        return cls(
            {column: tuple(sorted(frame[column].dropna().astype(str).unique())) for column in CATEGORICAL_FEATURES}
        )

    def transform(self, frame: pd.DataFrame) -> pd.DataFrame:
        output = pd.DataFrame(index=frame.index)
        for column in CATEGORICAL_FEATURES:
            output[column] = pd.Categorical(frame[column].astype("string"), categories=self.categories[column])
        for column in NUMERIC_FEATURES:
            output[column] = pd.to_numeric(frame[column], errors="coerce").astype("float32")
        return output[list(MODEL_FEATURES)]

    def to_dict(self) -> dict[str, list[str]]:
        return {column: list(values) for column, values in sorted(self.categories.items())}
