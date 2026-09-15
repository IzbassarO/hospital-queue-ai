"""A trained referral-level model (A: wait_time, B: refusal_risk) with everything needed to predict and explain."""

from dataclasses import dataclass, field
from pathlib import Path

import lightgbm as lgb
import numpy as np
import pandas as pd

from hqai_ml.models.lgbm import encode
from hqai_ml.registry import store

MODEL_FILE = "model.txt"


@dataclass
class ReferralModel:
    name: str  # "wait_time" or "refusal_risk"
    booster: lgb.Booster
    features: list[str]
    categories: dict[str, list[str]]
    display: dict = field(default_factory=dict)  # code -> readable name lookups (region, org, profile)
    version: str | None = None

    @property
    def is_classifier(self) -> bool:
        return self.name == "refusal_risk"

    def X(self, df: pd.DataFrame) -> pd.DataFrame:
        return encode(df, self.features, self.categories)

    def raw_score(self, df: pd.DataFrame) -> np.ndarray:
        """log1p(days) for wait_time, log-odds for refusal_risk."""
        return self.booster.predict(self.X(df), raw_score=True)

    def predict(self, df: pd.DataFrame) -> np.ndarray:
        """Days for wait_time (clipped at 0), probability for refusal_risk."""
        raw = self.raw_score(df)
        return 1 / (1 + np.exp(-raw)) if self.is_classifier else np.clip(np.expm1(raw), 0, None)

    @classmethod
    def load(cls, artifacts_dir: Path, name: str, version: str | None = None) -> "ReferralModel":
        art = store.load(artifacts_dir, name, version)
        return cls(
            name=name,
            booster=art["boosters"][MODEL_FILE],
            features=art["features"],
            categories=art["categories"],
            display=art.get("display", {}),
            version=art["version"],
        )
