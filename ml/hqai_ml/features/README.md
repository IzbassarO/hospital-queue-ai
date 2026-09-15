# hqai_ml.features

Implemented. `data.py` opens the data layer (Parquet) in DuckDB; `referral.py` builds the referral-level features of Models A and B, every value as of the start of the registration date (aggregates up to d−1, label-derived statistics only from outcomes before d); `icd.py` maps ICD-10 codes to chapters; `load.py` builds the daily series panels and direct multi-horizon rows of Model C (features use only days ≤ the forecast origin). Leakage notes per feature: `hqai_ml/evaluation/feature_notes.py` and docs/model_card.md.
