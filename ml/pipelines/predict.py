#!/usr/bin/env python3
"""Predictions of the current registry models -> Postgres.

Run:  make predict        (applies Alembic migrations first; needs `make train`)

Writes, in one transaction (previous predictions are replaced):
  pred_referral        wait time + refusal risk + top-5 explanations for every referral registered in the test period
  pred_daily_forecast  14-day forecast from the configured origin for every hospital × profile and region × profile series
  model_registry       one row per model version; is_current marks the versions used here
"""
import json
import sys
import time
import warnings

import pandas as pd
import psycopg

from hqai_ml.explain.shap_explain import explain_batch
from hqai_ml.features.data import connect
from hqai_ml.features.load import load_panels
from hqai_ml.features.referral import build_referral_features
from hqai_ml.ingest.config import IngestSettings
from hqai_ml.models import load_forecast
from hqai_ml.models.config import load_model_config
from hqai_ml.models.referral_model import ReferralModel
from hqai_ml.registry import store

T0 = time.time()
BATCH = 20_000


def log(msg: str) -> None:
    print(f"[{time.time() - T0:6.1f}s] {msg}", flush=True)


def headline_metrics(name: str, metrics: dict) -> dict:
    if name in ("wait_time", "refusal_risk"):
        return {"population": metrics["population"], "overall": metrics["overall"]}
    return {"series": metrics["series"], "beats_seasonal_naive": metrics["beats_seasonal_naive"], "pooled": metrics["pooled"]}


def main() -> int:
    warnings.filterwarnings("ignore", category=UserWarning)
    settings = IngestSettings()
    cfg = load_model_config(settings)
    con = connect(settings.processed_dir)

    # ---- referral models
    wait = ReferralModel.load(settings.artifacts_dir, "wait_time")
    refusal = ReferralModel.load(settings.artifacts_dir, "refusal_risk")
    log(f"models: wait_time {wait.version}, refusal_risk {refusal.version}")
    df = build_referral_features(con, cfg.split.train_start)
    test = df[(df["registration_date"] >= cfg.split.test_start) & (df["registration_date"] <= cfg.split.test_end)]
    test = test.reset_index(drop=True)
    codes = con.execute("SELECT referral_id, hospitalization_code FROM fact_referral").df().set_index("referral_id")
    log(f"test-period referrals: {len(test):,}")

    referral_rows = []
    for start in range(0, len(test), BATCH):
        part = test.iloc[start:start + BATCH]
        pred_wait = wait.predict(part)
        pred_ref = refusal.predict(part)
        ex_wait = explain_batch(wait, part, cfg.explain.top_k)
        ex_ref = explain_batch(refusal, part, cfg.explain.top_k)
        for i, rid in enumerate(part["referral_id"].to_numpy()):
            referral_rows.append((
                int(rid), codes.at[rid, "hospitalization_code"], part["registration_date"].iat[i],
                part["org_code"].iat[i], part["profile_code"].iat[i], wait.version, refusal.version,
                float(pred_wait[i]), float(pred_ref[i]),
                json.dumps({"wait_time": ex_wait[i], "refusal_risk": ex_ref[i]}, ensure_ascii=False),
            ))
        log(f"  explained {min(start + BATCH, len(test)):,} / {len(test):,}")

    # ---- load forecast
    art = store.load(settings.artifacts_dir, "load_forecast")
    boosters = {t: art["boosters"][f"model_{t}.txt"] for t in load_forecast.TARGETS}
    hospital, region = load_panels(con)
    fc = load_forecast.production_forecast(hospital, region, boosters, art["categories"], art["series"], cfg)
    fc["model_version"] = art["version"]
    log(f"forecast rows: {len(fc):,} (origin {cfg.load_forecast.forecast_origin}, {fc['series_id'].nunique():,} series)")

    # ---- write
    manifest = store.read_manifest(settings.artifacts_dir)
    registry_rows = []
    for name in ("wait_time", "refusal_risk", "load_forecast"):
        a = store.load(settings.artifacts_dir, name)
        registry_rows.append((name, a["version"], a["meta"]["trained_at"], json.dumps(a["meta"]["training_window"]),
                              json.dumps(headline_metrics(name, a["metrics"]), ensure_ascii=False),
                              manifest[name]["path"]))

    fc_cols = ["series_id", "origin_date", "horizon", "target_date", "level", "org_code", "region_code", "profile_code",
               "method", "pred_registrations", "pred_hospitalizations", "pred_queue", "model_version"]
    with psycopg.connect(settings.pg_conninfo) as pg, pg.cursor() as cur:
        cur.execute("TRUNCATE pred_referral, pred_daily_forecast")
        with cur.copy("""COPY pred_referral (referral_id, hospitalization_code, registration_date, org_code, profile_code,
                         wait_model_version, refusal_model_version, pred_wait_days, pred_refusal_prob, explanation)
                         FROM STDIN""") as copy:
            for row in referral_rows:
                copy.write_row(row)
        with cur.copy(f"COPY pred_daily_forecast ({', '.join(fc_cols)}) FROM STDIN") as copy:
            for row in fc[fc_cols].itertuples(index=False):
                copy.write_row([None if pd.isna(v) else (int(v) if k == "horizon" else v) for k, v in zip(fc_cols, row)])
        for name, version, trained_at, window, metrics, path in registry_rows:
            cur.execute("""INSERT INTO model_registry (model_name, version, trained_at, train_window, metrics, is_current, artifact_path)
                           VALUES (%s, %s, %s, %s, %s, true, %s)
                           ON CONFLICT (model_name, version) DO UPDATE
                           SET metrics = EXCLUDED.metrics, train_window = EXCLUDED.train_window, is_current = true""",
                        (name, version, trained_at, window, metrics, path))
            cur.execute("UPDATE model_registry SET is_current = false WHERE model_name = %s AND version <> %s", (name, version))
        counts = {t: cur.execute(f"SELECT count(*) FROM {t}").fetchone()[0]
                  for t in ("pred_referral", "pred_daily_forecast", "model_registry")}
        if counts["pred_referral"] != len(referral_rows) or counts["pred_daily_forecast"] != len(fc):
            raise RuntimeError(f"row count mismatch after load: {counts}")
        pg.commit()
    log(f"postgres: {counts}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
