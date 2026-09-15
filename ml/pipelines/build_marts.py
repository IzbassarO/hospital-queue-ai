#!/usr/bin/env python3
"""Serving marts for the API -> Postgres.

Run:  make marts          (applies Alembic migrations first; also runs at the end of `make predict`)

Reads (Postgres): agg_daily_hospital_profile, agg_daily_region_profile, fact_referral, pred_referral,
                  pred_daily_forecast, dim_* ; configs: ml/configs/serving.yaml, ml/configs/models.yaml (test split),
                  ml/configs/explain_templates.yaml (value display rules for the API)
Writes, in one transaction (previous marts are replaced):
  mart_hospital_profile_status, mart_region_profile_status, mart_area_status, mart_build_info
Formulas: docs/api.md. decision_log is never touched.
"""

import sys
import time

import yaml

from hqai_ml.features.icd import CHAPTER_RANGES
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
    # display rules for explanation factor values, copied into mart_build_info.config so the API (which has no
    # access to ml/) formats values exactly like the model explanations
    templates = yaml.safe_load((settings.configs_dir / "explain_templates.yaml").read_text(encoding="utf-8"))
    raw_config["explain_display"] = {
        "features": {
            f: {k: v for k, v in spec.items() if k in ("label", "short_label", "format", "unit")}
            for f, spec in templates["features"].items()
        },
        "icd_chapters": templates["icd_chapters"],
        "icd_chapter_ranges": [list(r) for r in CHAPTER_RANGES],
        "weekdays": templates["weekdays"],
        "missing_value": templates["missing_value"],
    }
    log(
        f"as_of {cfg.as_of_date}: window {cfg.window_start} … {cfg.as_of_date}, "
        f"trend weeks {cfg.trend_start} … {cfg.trend_end}, test period {split['test_start']} … {split['test_end']}"
    )
    result = build(settings.pg_conninfo, cfg, raw_config, split["test_start"], split["test_end"], log=log)
    log(f"postgres: {result['counts']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
