# The wait-effect estimator seam

A design note, not a package: there is no causal code in the repository, and the folder that used to hold an
empty `hqai_ml.causal` module was removed rather than kept as a placeholder (ADR 0001: empty architecture folders
are not progress).

Estimates of what drives waits and refusals (e.g. capacity vs. demand, referral routing across regions), kept separate from predictive models so that recommendations are not based on correlations alone. Not implemented yet.

Integration point: the API's recommendations (`backend/app/services/recommend.py`) take a `WaitEffectEstimator` —
`method: str` and `estimate(current, alternative) -> WaitEstimate | None`. v1 is `HistoricalMedianEstimator`
(`method = "historical_median"`). A causal estimate should be exposed through the same protocol (e.g. reading a
precomputed effects table), so the trigger, filters, sorting, ids and response schema stay unchanged (`docs/api.md` §4).
