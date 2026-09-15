"""Daily series panels and direct multi-horizon feature rows for Model C (load forecast).

A row describes: series s, forecast origin t (the LAST KNOWN day), horizon h (target day t+h).
All features use values on days <= t only.
"""
import datetime as dt
from dataclasses import dataclass

import duckdb
import numpy as np
import pandas as pd

SERIES_CATEGORICAL = ["level", "org_code", "region_code", "profile_code"]
REGION_ORG = "__region__"


@dataclass
class Panel:
    dates: list[dt.date]          # T consecutive days
    meta: pd.DataFrame            # one row per series: series_id, level, org_code, region_code, profile_code
    registrations: np.ndarray     # [S, T]
    hospitalizations: np.ndarray  # [S, T]
    queue: np.ndarray             # [S, T] end-of-day queue length

    def index_of(self, day: dt.date) -> int:
        return (day - self.dates[0]).days

    def subset(self, mask: np.ndarray) -> "Panel":
        return Panel(self.dates, self.meta[mask].reset_index(drop=True), self.registrations[mask],
                     self.hospitalizations[mask], self.queue[mask])

    def target(self, name: str) -> np.ndarray:
        return {"registrations": self.registrations, "hospitalizations": self.hospitalizations}[name]


def _dense(con, sql: str, keys: list[str]) -> tuple[pd.DataFrame, list[dt.date], dict[str, np.ndarray]]:
    df = con.execute(sql).df().sort_values(keys + ["date"])
    dates = sorted(pd.to_datetime(df["date"]).dt.date.unique())
    meta = df[keys].drop_duplicates().reset_index(drop=True)
    S, T = len(meta), len(dates)
    if len(df) != S * T:
        raise ValueError(f"panel is not dense: {len(df)} rows for {S} series x {T} days")
    arrays = {c: df[c].to_numpy(float).reshape(S, T) for c in ("registrations", "hospitalizations", "queue_length")}
    return meta, dates, arrays


def load_panels(con: duckdb.DuckDBPyConnection) -> tuple[Panel, Panel]:
    """(hospital x profile panel, region x profile panel) over the whole aggregate window."""
    hm, hd, ha = _dense(con, """SELECT date, org_code, region_code, profile_code, registrations, hospitalizations, queue_length
                                FROM agg_daily_hospital_profile""", ["org_code", "region_code", "profile_code"])
    hm.insert(0, "level", "hospital")
    hm.insert(0, "series_id", "hp:" + hm["org_code"] + ":" + hm["profile_code"])
    rm, rd, ra = _dense(con, """SELECT date, region_code, profile_code, registrations, hospitalizations, queue_length
                                FROM agg_daily_region_profile""", ["region_code", "profile_code"])
    rm.insert(0, "level", "region")
    rm.insert(1, "org_code", REGION_ORG)
    rm.insert(0, "series_id", "rp:" + rm["region_code"] + ":" + rm["profile_code"])
    if hd != rd:
        raise ValueError("hospital and region panels cover different dates")
    hospital = Panel(hd, hm, ha["registrations"], ha["hospitalizations"], ha["queue_length"])
    region = Panel(rd, rm, ra["registrations"], ra["hospitalizations"], ra["queue_length"])
    return hospital, region


def concat(a: Panel, b: Panel) -> Panel:
    return Panel(a.dates, pd.concat([a.meta, b.meta], ignore_index=True),
                 np.vstack([a.registrations, b.registrations]), np.vstack([a.hospitalizations, b.hospitalizations]),
                 np.vstack([a.queue, b.queue]))


def feature_names(lags: list[int], rolling: list[int]) -> list[str]:
    return (SERIES_CATEGORICAL + ["horizon"] + [f"lag_{k}" for k in lags] + [f"roll_mean_{w}" for w in rolling]
            + ["same_weekday_last", "queue_at_origin", "target_weekday", "target_is_holiday", "target_day_index"])


def build_rows(panel: Panel, target: str, cutoffs: list[int], horizon: int, lags: list[int], rolling: list[int],
               holidays: set[dt.date], max_target_index: int | None) -> pd.DataFrame:
    """Rows for every series x cutoff t x horizon h (target index t+h <= max_target_index if given).

    y is NaN when the target day lies outside the panel (production forecast).
    """
    Y = panel.target(target)
    S, T = Y.shape
    csum = np.concatenate([np.zeros((S, 1)), np.cumsum(Y, axis=1)], axis=1)  # csum[:, j] = sum Y[:, :j]
    start = panel.dates[0]
    blocks = []
    hs_all = np.arange(1, horizon + 1)
    for t in cutoffs:
        hs = hs_all if max_target_index is None else hs_all[t + hs_all <= max_target_index]
        if len(hs) == 0:
            continue
        n_h = len(hs)
        cols = {
            "series_idx": np.repeat(np.arange(S), n_h),
            "cutoff": np.full(S * n_h, t),
            "horizon": np.tile(hs, S),
        }
        for k in lags:
            j = t - k + 1
            cols[f"lag_{k}"] = np.repeat(Y[:, j] if j >= 0 else np.full(S, np.nan), n_h)
        for w in rolling:
            j0 = t - w + 1
            cols[f"roll_mean_{w}"] = np.repeat((csum[:, t + 1] - csum[:, j0]) / w if j0 >= 0 else np.full(S, np.nan), n_h)
        # most recent observed value on the target's weekday
        back = t + hs - 7 * np.ceil(hs / 7).astype(int)
        cols["same_weekday_last"] = np.where(back >= 0, Y[:, np.clip(back, 0, None)], np.nan).reshape(-1)
        cols["queue_at_origin"] = np.repeat(panel.queue[:, t], n_h)
        tdays = [start + dt.timedelta(days=int(t + h)) for h in hs]
        cols["target_weekday"] = np.tile([d.isoweekday() for d in tdays], S)
        cols["target_is_holiday"] = np.tile([float(d in holidays) for d in tdays], S)
        cols["target_day_index"] = np.tile(t + hs, S)
        ti = t + hs
        cols["y"] = np.where(ti < T, Y[:, np.clip(ti, None, T - 1)], np.nan).reshape(-1)
        blocks.append(pd.DataFrame(cols))
    rows = pd.concat(blocks, ignore_index=True)
    meta = panel.meta[SERIES_CATEGORICAL + ["series_id"]]
    rows = pd.concat([meta.iloc[rows["series_idx"]].reset_index(drop=True), rows], axis=1)
    for c in rows.columns:
        if rows[c].dtype == np.float64 and c not in ("y",):
            rows[c] = rows[c].astype(np.float32)
    return rows
