"""Temporal split helpers. Never random."""

import datetime as dt

import pandas as pd

from hqai_ml.models.config import Split


def temporal_masks(dates: pd.Series, split: Split) -> tuple[pd.Series, pd.Series]:
    """(train, test) boolean masks by date (inclusive bounds)."""
    train = (dates >= split.train_start) & (dates <= split.train_end)
    test = (dates >= split.test_start) & (dates <= split.test_end)
    return train, test


def holdout_mask(dates: pd.Series, train_end: dt.date, days: int) -> pd.Series:
    """The last `days` days of the train period (used only for early stopping)."""
    return dates > train_end - dt.timedelta(days=days)
