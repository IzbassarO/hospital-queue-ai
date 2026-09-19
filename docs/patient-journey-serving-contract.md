# Patient Journey component serving contract

Status: component draft under the normative
[`6B.2D intelligence serving contract`](serving-contract-6b2d.md). Step 6B.2A does not add or change backend routes,
OpenAPI schemas, database tables, or frontend behavior.

A future serving implementation should expose a candidate-independent Patient
Journey response. It must not reveal XGBoost-, LightGBM-, AFT-, discrete-hazard,
or other model-family implementation details.

The serving contract describes prediction semantics, not model internals.
Different model families may implement the same estimand without changing the
public API contract.

| Field | Contract |
|---|---|
| `assessment_id` | Deterministic identity for referral × estimand × prediction origin |
| `referral` | Referral reference with an explicit ID scheme; current identifiers are not confirmed stable government IDs |
| `estimand_id` | Immutable/versioned identifier defining the statistical meaning of the emitted probabilities |
| `estimand_family` | `HOSPITALIZATION_CUMULATIVE_INCIDENCE`, `JOINT_COMPETING_RISK`, or `REFUSAL_CONDITIONAL_ON_TERMINAL_OUTCOME` |
| `prediction_origin_at` | RFC 3339 latest-information timestamp for the assessment |
| `hospitalization_probability_7d` | Number in `[0,1]` |
| `hospitalization_probability_14d` | Number in `[0,1]` |
| `hospitalization_probability_30d` | Number in `[0,1]` |
| `refusal_probability_7d`, `refusal_probability_14d`, `refusal_probability_30d` | Emitted only for a validated `JOINT_COMPETING_RISK` estimand |
| `unresolved_probability_7d`, `unresolved_probability_14d`, `unresolved_probability_30d` | Emitted only for a validated `JOINT_COMPETING_RISK` estimand |
| `refusal_probability_given_terminal_outcome` | One horizon-free conditional probability, emitted only for `REFUSAL_CONDITIONAL_ON_TERMINAL_OUTCOME` |
| `model_version` | Immutable model artifact identifier |
| `calibration_version` | Immutable calibration artifact identifier; nullable when calibration does not apply or is unavailable |
| `support` | Structured, versioned support state; it must not collapse independent support dimensions into a score |
| `freshness` | Separate availability and SLA state; SLA remains `UNKNOWN` until a customer refresh policy exists |
| `provenance` | Producing run and available scientific/dataset/config/code/artifact identities |

## Probability semantics

For a `JOINT_COMPETING_RISK` estimand that explicitly models hospitalized,
refused, and unresolved as mutually exclusive states, the three probabilities
must sum to one at each emitted horizon, within documented numerical tolerance.
The only accepted current joint implementation is the empirical
competing-risk/Aalen–Johansen-style baseline with its documented low-support
fallback. The individual ML hospitalization and refusal models do not implement
this joint estimand, and the ML joint challenger was not promoted.

For a hospitalization-only estimand, the serving response emits hospitalization
probabilities only. It must not synthesize refusal probabilities from another
model or label `1 - P(hospitalized)` as an unresolved probability.

The accepted refusal LightGBM estimand is probability of refusal conditional on
an observed terminal referral outcome. It emits only
`refusal_probability_given_terminal_outcome`: this is horizon-free and is not
`P(refusal <= 7d/14d/30d)`. It must not be displayed beside hospitalization
horizon probabilities in a way that implies comparability or joint coherence.

Probabilities produced by independently trained hospitalization and refusal
models are therefore not assumed to be mutually exclusive or jointly coherent.
Adapters must not join assessments with different `estimand_id` values into one
display that implies a single distribution.

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

`support` must provide enough structured information for
the serving layer and UI to distinguish supported predictions from low-support
or fallback predictions. Its schema and semantics must be versioned before
production serving is implemented.

`freshness` must expose enough structured source/feature timestamp
information for the serving layer and UI to detect stale or degraded inputs.
An unknown refresh SLA must not silently produce a `FRESH` state.

A future implementation must fail visibly into a documented degraded or
unsupported state rather than silently presenting stale, unsupported, or
synthetically completed probabilities as equivalent to fully supported
predictions.

## Pre-integration naming drift

The ML draft helper still contains `support_confidence_metadata`,
`prediction_timestamp`, `data_freshness_metadata`, grouped refusal/unresolved
horizon placeholders, and no versioned `estimand_id`. Saved evidence uses
free-text `estimand`. These are legacy draft names, not this component contract;
future adapters must correct them without modifying accepted evidence.

## Governance

Model-family selection and model promotion remain human-controlled.

This contract does not imply automatic promotion of either XGBoost AFT,
discrete hospitalization hazard, empirical competing-risk, refusal LightGBM,
or any future candidate.

Step 6B.2A establishes scientific evidence and candidate-independent serving
semantics only. Actual backend/OpenAPI/frontend serving implementation belongs
to a later integration step.
