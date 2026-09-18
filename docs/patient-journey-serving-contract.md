# Patient Journey serving contract draft

Status: design draft only. Step 6B.2A does not add or change backend routes,
OpenAPI schemas, database tables, or frontend behavior.

A future serving implementation should expose a candidate-independent Patient
Journey response. It must not reveal XGBoost-, LightGBM-, AFT-, discrete-hazard,
or other model-family implementation details.

The serving contract describes prediction semantics, not model internals.
Different model families may implement the same estimand without changing the
public API contract.

| Field | Contract |
|---|---|
| `estimand_id` | Immutable/versioned identifier defining the statistical meaning of the emitted probabilities |
| `hospitalization_probability_7d` | Number in `[0,1]` |
| `hospitalization_probability_14d` | Number in `[0,1]` |
| `hospitalization_probability_30d` | Number in `[0,1]` |
| `refusal_probability_7d`, `refusal_probability_14d`, `refusal_probability_30d` | Optional; emitted only when the active estimand explicitly models refusal as an outcome/cause |
| `unresolved_probability_7d`, `unresolved_probability_14d`, `unresolved_probability_30d` | Optional; emitted only when the active estimand explicitly defines unresolved as a mutually exclusive state |
| `model_version` | Immutable model artifact identifier |
| `calibration_version` | Immutable calibration artifact identifier |
| `support_confidence_metadata` | Structured cohort/support information; semantics must be versioned |
| `prediction_timestamp` | RFC 3339 timestamp |
| `data_freshness_metadata` | Structured source and feature freshness timestamps |

## Probability semantics

For a competing-risk estimand that explicitly models hospitalized, refused,
and unresolved as mutually exclusive states, the three probabilities must sum
to one at each emitted horizon, within documented numerical tolerance.

For a hospitalization-only estimand, the serving response emits hospitalization
probabilities only. It must not synthesize refusal probabilities from another
model or label `1 - P(hospitalized)` as an unresolved probability.

For a refusal-only estimand, refusal probabilities may be emitted independently,
but they must not be combined with independently trained hospitalization
probabilities into a joint three-state distribution unless a separate synthesis
method has been explicitly defined and validated.

Probabilities produced by independently trained hospitalization and refusal
models are therefore not assumed to be mutually exclusive or jointly coherent.

## Versioning

`estimand_id` versions the meaning of the prediction independently from the
underlying model implementation.

`model_version` identifies the immutable predictive model artifact.

`calibration_version` identifies the immutable calibration artifact and is
versioned independently from `model_version`.

Changes to probability semantics require a new `estimand_id` even when the
underlying model family remains unchanged.

Changes to model or calibration artifacts do not require a public API schema
change when the estimand semantics remain unchanged.

## Support and freshness

`support_confidence_metadata` must provide enough structured information for
the serving layer and UI to distinguish supported predictions from low-support
or fallback predictions. Its schema and semantics must be versioned before
production serving is implemented.

`data_freshness_metadata` must expose enough structured source/feature timestamp
information for the serving layer and UI to detect stale or degraded inputs.

A future implementation must fail visibly into a documented degraded or
unsupported state rather than silently presenting stale, unsupported, or
synthetically completed probabilities as equivalent to fully supported
predictions.

## Governance

Model-family selection and model promotion remain human-controlled.

This contract does not imply automatic promotion of either XGBoost AFT,
discrete hospitalization hazard, empirical competing-risk, refusal LightGBM,
or any future candidate.

Step 6B.2A establishes scientific evidence and candidate-independent serving
semantics only. Actual backend/OpenAPI/frontend serving implementation belongs
to a later integration step.