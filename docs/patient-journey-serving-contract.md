# Patient Journey serving contract draft

Status: design draft only. Step 6B.2A does not add or change backend routes, OpenAPI schemas, database tables, or
frontend behavior.

A future serving implementation should expose a candidate-independent Patient Journey response. It must not reveal
XGBoost-, LightGBM-, AFT-, or discrete-hazard implementation details.

| Field | Contract |
|---|---|
| `hospitalization_probability_7d` | Number in `[0,1]` |
| `hospitalization_probability_14d` | Number in `[0,1]` |
| `hospitalization_probability_30d` | Number in `[0,1]` |
| `refusal_probability_7d`, `refusal_probability_14d`, `refusal_probability_30d` | Optional; present only when the selected estimand models refusal as a cause |
| `unresolved_probability_7d`, `unresolved_probability_14d`, `unresolved_probability_30d` | Number in `[0,1]` for each horizon |
| `model_version` | Immutable model artifact identifier |
| `calibration_version` | Immutable calibration artifact identifier |
| `support_confidence_metadata` | Structured cohort/support information; semantics must be versioned |
| `prediction_timestamp` | RFC 3339 timestamp |
| `data_freshness_metadata` | Structured source and feature freshness timestamps |

For a competing-risk estimand, hospitalization, refusal, and unresolved probabilities must sum to one at each
horizon. For a hospitalization-only estimand, refusal probabilities are omitted rather than synthesized. Probability
calibration versioning is independent of the underlying model version.
