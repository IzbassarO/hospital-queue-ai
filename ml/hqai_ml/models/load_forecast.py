"""Model C — 1..14-day forecast of daily registrations and hospitalizations.

Series: hospital × profile with train-period mean registrations >= min_series_mean are modelled
individually; all region × profile series are modelled too (same global model per target, with
`level` as a feature). Smaller hospital × profile series get the forecast of their region × profile
series scaled by their train-period share of it (fallback).

Direct multi-horizon: one row per (series, origin t = last known day, horizon h); the model predicts
the value on day t+h from features known on day t.
"""

import datetime as dt

import lightgbm as lgb
import numpy as np
import pandas as pd

from hqai_ml.evaluation.backtest import error_table, horizon_bucket, rolling_origin
from hqai_ml.features.load import SERIES_CATEGORICAL, Panel, build_rows, concat, feature_names
from hqai_ml.models.config import ModelConfig
from hqai_ml.models.lgbm import encode, fit_categories

NAME = "load_forecast"
TARGETS = ["registrations", "hospitalizations"]
MIN_CUTOFF = 6  # first origin index used for training rows (lag_7 available from here)
METHODS = {"model": "pred", "seasonal_naive": "b_seasonal_naive", "mean_28d": "b_mean_28d", "mean_7d": "b_mean_7d"}


# ------------------------------------------------------------------ series setup
def split_series(hospital: Panel, region: Panel, cfg: ModelConfig) -> dict:
    """Modelled vs fallback hospital series (by train-period mean registrations) and fallback shares."""
    s, e = hospital.index_of(cfg.split.train_start), hospital.index_of(cfg.split.train_end)
    mean_reg = hospital.registrations[:, s : e + 1].mean(axis=1)
    modelled = mean_reg >= cfg.load_forecast.min_series_mean
    region_pos = {
        (r, p): i for i, (r, p) in enumerate(zip(region.meta["region_code"], region.meta["profile_code"], strict=True))
    }
    shares = {}
    for i in np.flatnonzero(~modelled):
        m = hospital.meta.iloc[i]
        j = region_pos[(m["region_code"], m["profile_code"])]
        entry = {"region_series": region.meta["series_id"].iloc[j]}
        for tgt in TARGETS:
            num = hospital.target(tgt)[i, s : e + 1].sum()
            den = region.target(tgt)[j, s : e + 1].sum()
            entry[tgt] = float(num / den) if den > 0 else 0.0
        shares[m["series_id"]] = entry
    return {"modelled_mask": modelled, "fallback_shares": shares}


def lgb_params(cfg: ModelConfig) -> dict:
    return {**cfg.lightgbm, "objective": cfg.load_forecast.objective, "metric": cfg.load_forecast.objective}


def _features(cfg: ModelConfig) -> list[str]:
    return feature_names(cfg.load_forecast.lags, cfg.load_forecast.rolling)


def _rows(panel: Panel, target: str, cutoffs, cfg: ModelConfig, max_target_index):
    lf = cfg.load_forecast
    return build_rows(panel, target, list(cutoffs), lf.horizon, lf.lags, lf.rolling, set(lf.holidays), max_target_index)


def fit_target(panel: Panel, target: str, last_known: int, categories: dict, cfg: ModelConfig) -> lgb.Booster:
    rows = _rows(panel, target, range(MIN_CUTOFF, last_known), cfg, max_target_index=last_known)
    X = encode(rows, _features(cfg), categories)
    return lgb.train(
        lgb_params(cfg),
        lgb.Dataset(X, rows["y"].to_numpy(float), categorical_feature=SERIES_CATEGORICAL),
        num_boost_round=cfg.load_forecast.rounds,
    )


def forecast_rows(
    panel: Panel, boosters: dict[str, lgb.Booster], last_known: int, categories: dict, cfg: ModelConfig
) -> pd.DataFrame:
    """One row per (series, horizon) with predictions and the baseline values for both targets."""
    out = None
    for tgt in TARGETS:
        rows = _rows(panel, tgt, [last_known], cfg, max_target_index=None)
        pred = boosters[tgt].predict(encode(rows, _features(cfg), categories))
        part = rows[
            ["series_id", "level", "org_code", "region_code", "profile_code", "horizon", "target_day_index"]
        ].copy()
        part[f"y_{tgt}"] = rows["y"].to_numpy(float)
        part[f"pred_{tgt}"] = pred
        part[f"b_seasonal_naive_{tgt}"] = rows["same_weekday_last"].to_numpy(float)
        part[f"b_mean_28d_{tgt}"] = rows["roll_mean_28"].to_numpy(float)
        part[f"b_mean_7d_{tgt}"] = rows["roll_mean_7"].to_numpy(float)
        out = part if out is None else out.merge(part, on=list(part.columns[:7]))
    return out


def add_fallback(
    fc_region: pd.DataFrame, small: Panel, shares: dict, last_known: int, cfg: ModelConfig
) -> pd.DataFrame:
    """Forecasts for small hospital series = region × profile forecast × train-period share."""
    base = {}
    for tgt in TARGETS:
        rows = _rows(small, tgt, [last_known], cfg, max_target_index=None)
        keep = rows[
            ["series_id", "level", "org_code", "region_code", "profile_code", "horizon", "target_day_index"]
        ].copy()
        keep[f"y_{tgt}"] = rows["y"].to_numpy(float)
        keep[f"b_seasonal_naive_{tgt}"] = rows["same_weekday_last"].to_numpy(float)
        keep[f"b_mean_28d_{tgt}"] = rows["roll_mean_28"].to_numpy(float)
        keep[f"b_mean_7d_{tgt}"] = rows["roll_mean_7"].to_numpy(float)
        base[tgt] = keep
    fb = base[TARGETS[0]].merge(base[TARGETS[1]], on=list(base[TARGETS[0]].columns[:7]))
    reg = fc_region.set_index(["series_id", "horizon"])
    fb["region_series"] = fb["series_id"].map(lambda sid: shares[sid]["region_series"])
    for tgt in TARGETS:
        share = fb["series_id"].map(lambda sid, tgt=tgt: shares[sid][tgt]).to_numpy(float)
        region_pred = (
            reg[f"pred_{tgt}"].reindex(pd.MultiIndex.from_arrays([fb["region_series"], fb["horizon"]])).to_numpy(float)
        )
        fb[f"pred_{tgt}"] = region_pred * share
    return fb.drop(columns=["region_series"])


def queue_path(fc: pd.DataFrame, last_queue: pd.Series) -> np.ndarray:
    """queue(t+h) = max(0, queue(t+h-1) + pred_registrations − pred_hospitalizations), per series.

    `fc` must be sorted by series_id, horizon. Refusals are not forecast, so this path is biased upward.
    """
    q = last_queue.reindex(fc["series_id"]).to_numpy(float)
    net = (fc["pred_registrations"] - fc["pred_hospitalizations"]).to_numpy(float)
    out = np.empty(len(fc))
    prev_sid, level = None, 0.0
    for i, (sid, start) in enumerate(zip(fc["series_id"].to_numpy(), q, strict=True)):
        if sid != prev_sid:
            level, prev_sid = start, sid
        level = max(0.0, level + net[i])
        out[i] = level
    return out


# --------------------------------------------------------------------- backtest
def _long(fc: pd.DataFrame, eval_level: str) -> pd.DataFrame:
    parts = []
    for tgt in TARGETS:
        p = fc[["series_id", "org_code", "region_code", "profile_code", "horizon"]].copy()
        p["eval_level"], p["target"] = eval_level, tgt
        p["y"] = fc[f"y_{tgt}"]
        p["pred"] = fc[f"pred_{tgt}"]
        for b in ("seasonal_naive", "mean_28d", "mean_7d"):
            p[f"b_{b}"] = fc[f"b_{b}_{tgt}"]
        parts.append(p)
    return pd.concat(parts, ignore_index=True)


def train_and_evaluate(hospital: Panel, region: Panel, cfg: ModelConfig, log=print) -> dict:
    lf = cfg.load_forecast
    setup = split_series(hospital, region, cfg)
    modelled_h = hospital.subset(setup["modelled_mask"])
    small_h = hospital.subset(~setup["modelled_mask"])
    panel = concat(modelled_h, region)
    categories = fit_categories(panel.meta, SERIES_CATEGORICAL)
    queue_by_series = {}

    def one_origin(origin: dt.date) -> pd.DataFrame:
        last = panel.index_of(origin)
        boosters = {tgt: fit_target(panel, tgt, last, categories, cfg) for tgt in TARGETS}
        fc = forecast_rows(panel, boosters, last, categories, cfg)
        fb = add_fallback(fc[fc["level"] == "region"], small_h, setup["fallback_shares"], last, cfg)
        allq = pd.Series(
            np.concatenate([panel.queue[:, last], small_h.queue[:, last]]),
            index=pd.concat([panel.meta["series_id"], small_h.meta["series_id"]]),
        )
        both = pd.concat([fc, fb], ignore_index=True).sort_values(["series_id", "horizon"]).reset_index(drop=True)
        both["pred_queue"] = queue_path(both, allq)
        actual_q = pd.Series(
            np.concatenate([panel.queue, small_h.queue]).tolist(),
            index=pd.concat([panel.meta["series_id"], small_h.meta["series_id"]]),
        )
        both["y_queue"] = [
            actual_q[s][int(ti)] for s, ti in zip(both["series_id"], both["target_day_index"], strict=True)
        ]
        both["b_last_queue"] = allq.reindex(both["series_id"]).to_numpy(float)
        both["eval_level"] = np.where(
            both["level"] == "region",
            "region × profile",
            np.where(
                both["series_id"].isin(small_h.meta["series_id"]),
                "hospital × profile (fallback)",
                "hospital × profile (modelled)",
            ),
        )
        queue_by_series[str(origin)] = both[
            ["series_id", "eval_level", "horizon", "y_queue", "pred_queue", "b_last_queue"]
        ]
        long = pd.concat(
            [_long(both[both["eval_level"] == lvl], lvl) for lvl in both["eval_level"].unique()], ignore_index=True
        )
        return long

    ev = rolling_origin(lf.backtest_origins, one_origin, log=log)
    ev["bucket"] = horizon_bucket(ev["horizon"])

    per_origin = error_table(ev, ["origin", "target", "eval_level", "bucket"], METHODS)
    pooled = error_table(ev, ["target", "eval_level", "bucket"], METHODS)
    pooled_all = error_table(ev, ["target", "eval_level"], METHODS)
    by_region = error_table(ev[ev["eval_level"] == "region × profile"], ["target", "region_code"], METHODS)

    s, e = hospital.index_of(cfg.split.train_start), hospital.index_of(cfg.split.train_end)
    vol = (
        pd.Series(modelled_h.registrations[:, s : e + 1].sum(axis=1), index=modelled_h.meta["org_code"])
        .groupby(level=0)
        .sum()
    )
    top_orgs = vol.sort_values(ascending=False).head(lf.top_hospitals).index.tolist()
    hosp_ev = ev[(ev["eval_level"] == "hospital × profile (modelled)") & ev["org_code"].isin(top_orgs)]
    by_top_hospital = error_table(hosp_ev, ["target", "org_code"], METHODS)
    for r in by_top_hospital:
        r["train_registrations"] = float(vol[r["org_code"]])

    q = pd.concat([d.assign(origin=o) for o, d in queue_by_series.items()], ignore_index=True)
    q["bucket"] = horizon_bucket(q["horizon"])
    q = q.rename(columns={"y_queue": "y", "pred_queue": "pred"})
    queue_table = error_table(
        q, ["origin", "eval_level", "bucket"], {"model": "pred", "last_value": "b_last_queue"}, bias=True
    )

    # calendar check: test-period days with national volume far below their weekday median but no holiday flag
    nat = region.registrations.sum(axis=0)
    t0, t1 = region.index_of(cfg.split.test_start), region.index_of(cfg.split.test_end)
    cal = pd.DataFrame({"date": region.dates, "registrations": nat})
    cal["weekday"] = [d.isoweekday() for d in region.dates]
    cal["weekday_median"] = cal.groupby("weekday")["registrations"].transform("median")
    cal["ratio"] = cal["registrations"] / cal["weekday_median"]
    cal["is_holiday_flag"] = cal["date"].isin(set(lf.holidays))
    low = cal.iloc[t0 : t1 + 1]
    low = low[low["ratio"] < 0.2]
    calendar_check = [
        {
            "date": str(r.date),
            "weekday": int(r.weekday),
            "registrations": float(r.registrations),
            "weekday_median": float(r.weekday_median),
            "holiday_flag": bool(r.is_holiday_flag),
        }
        for r in low.itertuples()
        if r.weekday <= 5
    ]

    beats = []
    for r in pooled_all:
        cells = [c for c in per_origin if c["target"] == r["target"] and c["eval_level"] == r["eval_level"]]
        beats.append(
            {
                "target": r["target"],
                "eval_level": r["eval_level"],
                "wape_model": r["wape_model"],
                "wape_seasonal_naive": r["wape_seasonal_naive"],
                "wape_mean_28d": r["wape_mean_28d"],
                "wape_mean_7d": r["wape_mean_7d"],
                "beats_seasonal_naive": r["wape_model"] < r["wape_seasonal_naive"],
                "beats_all_baselines": r["wape_model"]
                < min(r["wape_seasonal_naive"], r["wape_mean_28d"], r["wape_mean_7d"]),
                "cells_beating_seasonal_naive": sum(c["wape_model"] < c["wape_seasonal_naive"] for c in cells),
                "cells": len(cells),
            }
        )

    # production model: all data up to the forecast origin
    last = panel.index_of(lf.forecast_origin)
    log(f"  final fit on data up to {lf.forecast_origin} …")
    final = {tgt: fit_target(panel, tgt, last, categories, cfg) for tgt in TARGETS}
    importance = {
        tgt: sorted(
            (
                {"feature": f, "gain": float(g)}
                for f, g in zip(b.feature_name(), b.feature_importance("gain"), strict=True)
            ),
            key=lambda x: -x["gain"],
        )
        for tgt, b in final.items()
    }
    return {
        "boosters": final,
        "categories": categories,
        "series": {
            "modelled_hospital_series": modelled_h.meta["series_id"].tolist(),
            "region_series": region.meta["series_id"].tolist(),
            "fallback_shares": setup["fallback_shares"],
        },
        "metrics": {
            "series": {
                "hospital_profile_total": len(hospital.meta),
                "hospital_profile_modelled": len(modelled_h.meta),
                "hospital_profile_fallback": len(small_h.meta),
                "region_profile": len(region.meta),
                "min_series_mean": lf.min_series_mean,
            },
            "backtest_origins": [str(o) for o in lf.backtest_origins],
            "per_origin": per_origin,
            "pooled_by_bucket": pooled,
            "pooled": pooled_all,
            "by_region": by_region,
            "by_top_hospital": by_top_hospital,
            "queue": queue_table,
            "calendar_check": calendar_check,
            "beats_seasonal_naive": beats,
            "gain_importance": importance,
        },
    }


def production_forecast(
    hospital: Panel, region: Panel, boosters: dict, categories: dict, series: dict, cfg: ModelConfig
) -> pd.DataFrame:
    """Forecast for every hospital × profile and region × profile series from the configured origin."""
    modelled_ids = set(series["modelled_hospital_series"])
    mask = hospital.meta["series_id"].isin(modelled_ids).to_numpy()
    modelled_h, small_h = hospital.subset(mask), hospital.subset(~mask)
    panel = concat(modelled_h, region)
    last = panel.index_of(cfg.load_forecast.forecast_origin)
    fc = forecast_rows(panel, boosters, last, categories, cfg)
    fc["method"] = "model"
    fb = add_fallback(fc[fc["level"] == "region"], small_h, series["fallback_shares"], last, cfg)
    fb["method"] = "region_share_fallback"
    both = pd.concat([fc, fb], ignore_index=True).sort_values(["series_id", "horizon"]).reset_index(drop=True)
    lastq = pd.Series(
        np.concatenate([panel.queue[:, last], small_h.queue[:, last]]),
        index=pd.concat([panel.meta["series_id"], small_h.meta["series_id"]]),
    )
    both["pred_queue"] = queue_path(both, lastq)
    origin = cfg.load_forecast.forecast_origin
    both["origin_date"] = origin
    both["target_date"] = [origin + dt.timedelta(days=int(h)) for h in both["horizon"]]
    both["org_code"] = both["org_code"].where(both["level"] == "hospital")
    return both[
        [
            "series_id",
            "level",
            "org_code",
            "region_code",
            "profile_code",
            "method",
            "origin_date",
            "target_date",
            "horizon",
            "pred_registrations",
            "pred_hospitalizations",
            "pred_queue",
        ]
    ]
