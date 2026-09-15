# hqai_ml.registry

Implemented. `store.py` saves each trained model to artifacts/models/<model_name>/<YYYYMMDD-HHMM>/ (LightGBM model files, features.json, categories.json, meta.json with training window and parameters, metrics.json, extras such as display names or series lists) and keeps artifacts/models/manifest.json pointing to the current version of each model. ml/pipelines/predict.py mirrors the versions into the Postgres table model_registry.
