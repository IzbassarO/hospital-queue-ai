# ml

Python package `hqai_ml` plus runnable pipelines and configuration.

```
ml/
  hqai_ml/
    ingest/       raw data → Parquet → Postgres
    features/     referral features (A, B), series panels and horizon rows (C)
    models/       wait_time (A), refusal_risk (B), load_forecast (C)
    causal/       placeholder
    evaluation/   temporal split, metrics, backtest, report
    explain/      SHAP explanations with Russian templates
    registry/     versioned artifacts under artifacts/models/
    serving/      serving marts for the API (SQL run inside Postgres; docs/api.md)
  pipelines/
    ingest.py     make ingest
    baseline.py   make baseline → reports/01_baseline.md
    train.py      make train    → artifacts/models/, reports/02_models.md  (--model to run one)
    predict.py    make predict  → pred_referral, pred_daily_forecast, model_registry (then build_marts.py)
    build_marts.py make marts   → mart_hospital_profile_status, mart_region_profile_status, mart_area_status
  configs/
    serving.yaml  as-of date, windows, load_index weights, status / alert thresholds, recommendation rule
    ingest.yaml   pipeline parameters (window, date ranges, thresholds)
    regions.yaml  region code dictionary — generated, reviewed by hand
    org_matches.yaml       manual hospital ↔ ERSB match overrides
    models.yaml            split, LightGBM defaults, forecast settings, holidays
    explain_templates.yaml Russian sentence templates for explanations
```

Pipelines are run with `PYTHONPATH=ml` (the Makefile sets it).
