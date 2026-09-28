from __future__ import annotations

import datetime as dt
import hashlib
import json
import math
from collections.abc import Iterable
from typing import Any

import numpy as np
import pandas as pd


def _json_scalar(value: Any) -> Any:
    if value is None or value is pd.NA or (isinstance(value, float) and math.isnan(value)):
        return None
    if isinstance(value, (dt.date, dt.datetime, pd.Timestamp)):
        return value.isoformat()
    if isinstance(value, np.generic):
        return value.item()
    return value


def canonical_frame_sha256(
    frame: pd.DataFrame,
    *,
    columns: Iterable[str] | None = None,
    sort_by: tuple[str, ...] = ("referral_id",),
) -> str:
    """Hash a frame as canonical JSON records with explicit schema and ordering.

    The hash does not depend on a parquet writer, platform line endings, dataframe index,
    or the input row order. Non-finite numeric values other than missing values are rejected.
    """
    selected = tuple(columns) if columns is not None else tuple(frame.columns)
    missing = sorted((set(selected) | set(sort_by)) - set(frame.columns))
    if missing:
        raise ValueError(f"columns missing from frame: {missing}")
    ordered = frame.sort_values(list(sort_by), kind="stable")[list(selected)]
    digest = hashlib.sha256()
    header = json.dumps({"columns": selected}, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    digest.update(header.encode("utf-8"))
    digest.update(b"\n")
    for row in ordered.itertuples(index=False, name=None):
        values = [_json_scalar(value) for value in row]
        for value in values:
            if isinstance(value, float) and not math.isfinite(value):
                raise ValueError("canonical frame hashes do not permit infinite values")
        payload = json.dumps(values, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
        digest.update(payload.encode("utf-8"))
        digest.update(b"\n")
    return digest.hexdigest()
