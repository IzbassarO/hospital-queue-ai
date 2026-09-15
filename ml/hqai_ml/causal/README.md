# hqai_ml.causal

Estimates of what drives waits and refusals (e.g. capacity vs. demand, referral routing across regions), kept separate from predictive models so that recommendations are not based on correlations alone. Not implemented yet.

Integration point: the API's recommendations (`backend/app/services/recommend.py`) take a `WaitEffectEstimator` —
`method: str` and `estimate(current, alternative) -> WaitEstimate | None`. v1 is `HistoricalMedianEstimator`
(`method = "historical_median"`). A causal estimate should be exposed through the same protocol (e.g. reading a
precomputed effects table), so the trigger, filters, sorting, ids and response schema stay unchanged (`docs/api.md` §4).
