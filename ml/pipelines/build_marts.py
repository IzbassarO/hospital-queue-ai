#!/usr/bin/env python3
"""Serving marts for the API -> Postgres.

Run:  make marts          (applies Alembic migrations first; also runs at the end of `make predict`)

Reads (Postgres): agg_daily_hospital_profile, agg_daily_region_profile, fact_referral, pred_referral,
                  pred_daily_forecast, dim_* ; configs: ml/configs/serving.yaml, ml/configs/models.yaml (test split)
Writes, in one transaction (previous marts are replaced):
  mart_hospital_profile_status, mart_region_profile_status, mart_area_status, mart_build_info
Formulas: docs/api.md. decision_log is never touched.
"""
import sys
import time

import yaml

from hqai_ml.ingest.config import IngestSettings
from hqai_ml.serving.config import load_serving_config
from hqai_ml.serving.marts import build

T0 = time.time()


def log(msg: str) -> None:
    print(f"[{time.time() - T0:6.1f}s] {msg}", flush=True)


def main() -> int:
    settings = IngestSettings()
    cfg = load_serving_config(settings.configs_dir)
    raw_config = yaml.safe_load((settings.configs_dir / "serving.yaml").read_text(encoding="utf-8"))
    split = yaml.safe_load((settings.configs_dir / "models.yaml").read_text(encoding="utf-8"))["split"]
    log(f"as_of {cfg.as_of_date}: window {cfg.window_start} … {cfg.as_of_date}, "
        f"trend weeks {cfg.trend_start} … {cfg.trend_end}, test period {split['test_start']} … {split['test_end']}")
    result = build(settings.pg_conninfo, cfg, raw_config, split["test_start"], split["test_end"], log=log)
    log(f"postgres: {result['counts']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
