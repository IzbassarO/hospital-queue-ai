#!/usr/bin/env python3
"""Predictions of the current registry models -> Postgres.

Run:  make predict        (applies Alembic migrations first; needs `make train`)
      make registry       (--registry-only: refresh model_registry rows, incl. model cards, without predicting)

Writes, in one transaction (previous predictions are replaced):
  pred_referral        wait time + refusal risk + top-5 explanations for every referral registered in the test period
  pred_daily_forecast  14-day forecast from the configured origin for every hospital × profile and
                       region × profile series
  model_registry       one row per model version; is_current marks the versions used here; `card` = the
                       artifact's card.json (ml/configs/model_cards.yaml for versions trained before cards existed)
"""

import argparse
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
from hqai_ml.registry.resources import resource_config

T0 = time.time()
BATCH = 20_000


def log(msg: str) -> None:
    print(f"[{time.time() - T0:6.1f}s] {msg}", flush=True)


def headline_metrics(name: str, metrics: dict) -> dict:
    if name in ("wait_time", "refusal_risk"):
        return {"population": metrics["population"], "overall": metrics["overall"]}
    return {
        "series": metrics["series"],
        "beats_seasonal_naive": metrics["beats_seasonal_naive"],
        "pooled": metrics["pooled"],
    }


def registry_row(name: str, artifact: dict, manifest_entry: dict, card: dict | None) -> dict:
    evidence = store.registration_evidence(artifact)
    return {
        "model_name": name,
        "version": artifact["version"],
        "trained_at": artifact["meta"]["trained_at"],
        "train_window": json.dumps(artifact["meta"]["training_window"]),
        "metrics": json.dumps(headline_metrics(name, artifact["metrics"]), ensure_ascii=False),
        "artifact_path": manifest_entry["path"],
        "card": json.dumps(card or {}, ensure_ascii=False),
        "run_id": evidence["run_id"],
        "artifact_sha256": evidence["artifact_sha256"],
        "dataset_identity": evidence["dataset_identity"],
        "config_identity": evidence["config_identity"],
        "code_identity": evidence["code_identity"],
        "evaluation_status": evidence["evaluation_status"],
        "lineage": evidence["lineage"],
    }


def registry_rows(settings: IngestSettings) -> list[dict]:
    """Verified database records for one atomic snapshot of the filesystem current set."""
    manifest = store.read_manifest(settings.artifacts_dir)
    cards = store.load_cards(settings.configs_dir)
    rows = []
    for name in ("wait_time", "refusal_risk", "load_forecast"):
        if name not in manifest:
            raise store.ArtifactIntegrityError(f"current-set manifest has no entry for {name!r}")
        entry = manifest[name]
        a = store.load(settings.artifacts_dir, name, entry["current"])
        if entry.get("path") != a["path"].relative_to(settings.artifacts_dir).as_posix():
            raise store.ArtifactIntegrityError(f"current-set path conflicts with artifact {name!r}")
        if entry.get("artifact_sha256") != a["artifact_sha256"]:
            raise store.ArtifactIntegrityError(f"current-set checksum conflicts with artifact {name!r}")
        row = registry_row(name, a, entry, a.get("card") or cards.get(name))
        if row["lineage"] == "legacy_unattributed":
            log(f"  {name} {a['version']}: legacy artifact has no run lineage; checksum adopted and verified")
        if not a.get("card"):
            log(f"  {name} {a['version']}: no card.json in the artifact, using ml/configs/model_cards.yaml")
        rows.append(row)
    return rows


def write_registry(cur: psycopg.Cursor, rows: list[dict]) -> None:
    """Replace current flags and upsert the verified set inside the caller's transaction."""
    for row in rows:
        if not row["artifact_sha256"]:
            raise store.ArtifactIntegrityError(f"registry row {row['model_name']!r} has no verified checksum")
        lineage = [
            row["run_id"],
            row["dataset_identity"],
            row["config_identity"],
            row["code_identity"],
            row["evaluation_status"],
        ]
        if any(value is not None for value in lineage) and not all(value is not None for value in lineage):
            raise store.ArtifactIntegrityError(f"attributed registry row {row['model_name']!r} has missing lineage")
        if row["run_id"] is not None and row["evaluation_status"] != "completed":
            raise store.ArtifactIntegrityError(
                f"attributed registry row {row['model_name']!r} has no completed evaluation"
            )
    names = [row["model_name"] for row in rows]
    cur.execute("UPDATE model_registry SET is_current = false WHERE model_name = ANY(%s)", (names,))
    for row in rows:
        cur.execute(
            """INSERT INTO model_registry (model_name, version, trained_at, train_window,
                       metrics, is_current, artifact_path, card, run_id, artifact_sha256,
                       dataset_identity, config_identity, code_identity, evaluation_status)
                       VALUES (%(model_name)s, %(version)s, %(trained_at)s, %(train_window)s,
                               %(metrics)s, true, %(artifact_path)s, %(card)s, %(run_id)s,
                               %(artifact_sha256)s, %(dataset_identity)s, %(config_identity)s,
                               %(code_identity)s, %(evaluation_status)s)
                       ON CONFLICT (model_name, version) DO UPDATE
                       SET metrics = EXCLUDED.metrics, train_window = EXCLUDED.train_window,
                           artifact_path = EXCLUDED.artifact_path, card = EXCLUDED.card,
                           run_id = EXCLUDED.run_id, artifact_sha256 = EXCLUDED.artifact_sha256,
                           dataset_identity = EXCLUDED.dataset_identity,
                           config_identity = EXCLUDED.config_identity, code_identity = EXCLUDED.code_identity,
                           evaluation_status = EXCLUDED.evaluation_status, is_current = true""",
            row,
        )


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--registry-only", action="store_true", help="only refresh model_registry (no predictions)")
    ap.add_argument("--resource-profile", choices=("smoke", "laptop", "overnight"), default="laptop")
    ap.add_argument("--model-threads", type=int, help="override model/DuckDB thread limit")
    ap.add_argument("--duckdb-memory-mb", type=int, help="override DuckDB memory within profile budget")
    args = ap.parse_args()
    warnings.filterwarnings("ignore", category=UserWarning)
    settings = IngestSettings()
    resources = resource_config(
        args.resource_profile,
        model_threads=args.model_threads,
        duckdb_memory_mb=args.duckdb_memory_mb,
    )
    if args.registry_only:
        rows = registry_rows(settings)
        with psycopg.connect(settings.pg_conninfo) as pg, pg.cursor() as cur:
            write_registry(cur, rows)
            pg.commit()
        log(f"model_registry: {[(r['model_name'], r['version']) for r in rows]}")
        return 0
    cfg = load_model_config(settings)
    con = connect(settings.processed_dir, resources)

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
        part = test.iloc[start : start + BATCH]
        pred_wait = wait.predict(part)
        pred_ref = refusal.predict(part)
        ex_wait = explain_batch(wait, part, cfg.explain.top_k)
        ex_ref = explain_batch(refusal, part, cfg.explain.top_k)
        for i, rid in enumerate(part["referral_id"].to_numpy()):
            referral_rows.append(
                (
                    int(rid),
                    codes.at[rid, "hospitalization_code"],
                    part["registration_date"].iat[i],
                    part["org_code"].iat[i],
                    part["profile_code"].iat[i],
                    wait.version,
                    refusal.version,
                    float(pred_wait[i]),
                    float(pred_ref[i]),
                    json.dumps({"wait_time": ex_wait[i], "refusal_risk": ex_ref[i]}, ensure_ascii=False),
                )
            )
        log(f"  explained {min(start + BATCH, len(test)):,} / {len(test):,}")

    # ---- load forecast
    art = store.load(settings.artifacts_dir, "load_forecast")
    boosters = {t: art["boosters"][f"model_{t}.txt"] for t in load_forecast.TARGETS}
    hospital, region = load_panels(con)
    fc = load_forecast.production_forecast(hospital, region, boosters, art["categories"], art["series"], cfg)
    fc["model_version"] = art["version"]
    log(
        f"forecast rows: {len(fc):,} (origin {cfg.load_forecast.forecast_origin}, {fc['series_id'].nunique():,} series)"
    )

    # ---- write
    current = registry_rows(settings)

    fc_cols = [
        "series_id",
        "origin_date",
        "horizon",
        "target_date",
        "level",
        "org_code",
        "region_code",
        "profile_code",
        "method",
        "pred_registrations",
        "pred_hospitalizations",
        "pred_queue",
        "model_version",
    ]
    with psycopg.connect(settings.pg_conninfo) as pg, pg.cursor() as cur:
        cur.execute("TRUNCATE pred_referral, pred_daily_forecast")
        with cur.copy("""COPY pred_referral (referral_id, hospitalization_code, registration_date,
                         org_code, profile_code,
                         wait_model_version, refusal_model_version, pred_wait_days, pred_refusal_prob, explanation)
                         FROM STDIN""") as copy:
            for row in referral_rows:
                copy.write_row(row)
        with cur.copy(f"COPY pred_daily_forecast ({', '.join(fc_cols)}) FROM STDIN") as copy:
            for row in fc[fc_cols].itertuples(index=False):
                copy.write_row(
                    [
                        None if pd.isna(v) else (int(v) if k == "horizon" else v)
                        for k, v in zip(fc_cols, row, strict=True)
                    ]
                )
        write_registry(cur, current)
        counts = {
            t: cur.execute(f"SELECT count(*) FROM {t}").fetchone()[0]
            for t in ("pred_referral", "pred_daily_forecast", "model_registry")
        }
        if counts["pred_referral"] != len(referral_rows) or counts["pred_daily_forecast"] != len(fc):
            raise RuntimeError(f"row count mismatch after load: {counts}")
        pg.commit()
    log(f"postgres: {counts}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
