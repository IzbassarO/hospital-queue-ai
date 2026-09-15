#!/usr/bin/env python3
"""Train and evaluate the models, save artifacts to the registry, write reports/02_models.md.

Run:  make train                                   (all three models)
      PYTHONPATH=ml .venv/bin/python ml/pipelines/train.py --model wait_time|refusal_risk|load_forecast
Reads data/processed/*.parquet only (no Postgres).
"""

import argparse
import sys
import time
import warnings

from hqai_ml.evaluation.report import write_report
from hqai_ml.features.data import connect, display_lookups
from hqai_ml.features.load import load_panels
from hqai_ml.features.referral import build_referral_features
from hqai_ml.ingest.config import IngestSettings
from hqai_ml.models import load_forecast, refusal_risk, wait_time
from hqai_ml.models.config import load_model_config
from hqai_ml.registry import store

T0 = time.time()
MODELS = {"wait_time": wait_time, "refusal_risk": refusal_risk, "load_forecast": load_forecast}


def log(msg: str) -> None:
    print(f"[{time.time() - T0:6.1f}s] {msg}", flush=True)


def compare_with_current(
    settings: IngestSettings, name: str, new_metrics: dict, new_holidays: list[str]
) -> dict | None:
    """Pooled WAPE of the version about to be replaced vs the new run, copied into the new metrics.json
    so the change stays traceable after old versions are deleted."""
    try:
        old = store.load(settings.artifacts_dir, name)
    except FileNotFoundError:
        return None
    old_holidays = old["meta"].get("holidays")
    if old_holidays is None:  # versions trained before the holiday list was stored in meta.json
        flagged = {c["date"] for c in old["metrics"].get("calendar_check", []) if c["holiday_flag"]}
        unflagged = {c["date"] for c in old["metrics"].get("calendar_check", []) if not c["holiday_flag"]}
        added = sorted(d for d in new_holidays if d in unflagged)
        removed = sorted(d for d in flagged if d not in new_holidays)
    else:
        added = sorted(set(new_holidays) - set(old_holidays))
        removed = sorted(set(old_holidays) - set(new_holidays))
    before = {(r["target"], r["eval_level"]): r for r in old["metrics"]["pooled"]}
    rows = [
        {
            "target": r["target"],
            "eval_level": r["eval_level"],
            "wape_model_before": before.get((r["target"], r["eval_level"]), {}).get("wape_model"),
            "wape_model_after": r["wape_model"],
            "wape_seasonal_naive": r["wape_seasonal_naive"],
        }
        for r in new_metrics["pooled"]
    ]
    return {"previous_version": old["version"], "holidays_added": added, "holidays_removed": removed, "pooled": rows}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--model", choices=["all", *MODELS], default="all")
    args = ap.parse_args()
    selected = list(MODELS) if args.model == "all" else [args.model]
    warnings.filterwarnings("ignore", category=UserWarning)

    settings = IngestSettings()
    cards = store.load_cards(settings.configs_dir)
    cfg = load_model_config(settings)
    con = connect(settings.processed_dir)
    split = cfg.split.model_dump(mode="json")

    referral_models = [m for m in selected if m in ("wait_time", "refusal_risk")]
    if referral_models:
        df = build_referral_features(con, cfg.split.train_start)
        display = display_lookups(con)
        log(f"referral features: {len(df):,} rows")
        for name in referral_models:
            log(f"training {name} …")
            res = MODELS[name].train_and_evaluate(df, cfg, display)
            model = res["model"]
            meta = {
                "training_window": {
                    "train": [split["train_start"], split["train_end"]],
                    "test": [split["test_start"], split["test_end"]],
                    "date_column": "registration_date",
                    "early_stopping_holdout_days": cfg.early_stopping.holdout_days,
                },
                "population": res["metrics"]["population"],
                "target": "log1p(wait_days)" if name == "wait_time" else "outcome == refused",
                "best_iteration": res["best_iteration"],
                "lightgbm_params": {**cfg.lightgbm, **MODELS[name].OBJECTIVE},
            }
            version, path = store.save(
                settings.artifacts_dir,
                name,
                {"model.txt": model.booster},
                features=model.features,
                categories=model.categories,
                meta=meta,
                metrics=res["metrics"],
                extra={"display.json": display, "card.json": cards.get(name, {})},
            )
            log(f"  saved {name} {version} -> {path.relative_to(settings.artifacts_dir.parent)}")

    if "load_forecast" in selected:
        log("training load_forecast (rolling-origin backtest + final fit) …")
        hospital, region = load_panels(con)
        res = load_forecast.train_and_evaluate(hospital, region, cfg, log=log)
        lf = cfg.load_forecast
        meta = {
            "training_window": {
                "series_selection": [split["train_start"], split["train_end"]],
                "backtest_origins": [str(o) for o in lf.backtest_origins],
                "final_model_data_through": str(lf.forecast_origin),
            },
            "targets": load_forecast.TARGETS,
            "holidays": [str(d) for d in lf.holidays],
            "lightgbm_params": {**load_forecast.lgb_params(cfg), "num_boost_round": lf.rounds},
        }
        comparison = compare_with_current(settings, "load_forecast", res["metrics"], meta["holidays"])
        if comparison:
            res["metrics"]["previous_version_comparison"] = comparison
        boosters = {f"model_{t}.txt": b for t, b in res["boosters"].items()}
        version, path = store.save(
            settings.artifacts_dir,
            "load_forecast",
            boosters,
            features=load_forecast._features(cfg),
            categories=res["categories"],
            meta=meta,
            metrics=res["metrics"],
            extra={"series.json": res["series"], "card.json": cards.get("load_forecast", {})},
        )
        log(f"  saved load_forecast {version} -> {path.relative_to(settings.artifacts_dir.parent)}")

    report = write_report(settings, cfg)
    log(f"report: {report}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
