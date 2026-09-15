# hqai_ml.models

Implemented. `wait_time.py` (Model A, LightGBM regression on log1p days), `refusal_risk.py` (Model B, LightGBM binary), `load_forecast.py` (Model C, global LightGBM Poisson models for daily registrations and hospitalizations, rolling-origin backtest, region-share fallback, derived queue path). Shared pieces: `config.py` (ml/configs/models.yaml), `lgbm.py` (stable categorical encoding, early-stopped fit), `referral_training.py`, `referral_model.py` (a trained referral model with predict).
