# ml

Python package `hqai_ml` plus runnable pipelines and configuration.

```
ml/
  hqai_ml/
    ingest/       implemented — raw data → Parquet → Postgres
    features/     placeholder
    models/       placeholder
    causal/       placeholder
    evaluation/   placeholder
    explain/      placeholder
    registry/     placeholder
  pipelines/
    ingest.py     make ingest
    baseline.py   make baseline → reports/01_baseline.md
  configs/
    ingest.yaml   pipeline parameters (window, date ranges, thresholds)
    regions.yaml  region code dictionary — generated, reviewed by hand
```

Pipelines are run with `PYTHONPATH=ml` (the Makefile sets it).
