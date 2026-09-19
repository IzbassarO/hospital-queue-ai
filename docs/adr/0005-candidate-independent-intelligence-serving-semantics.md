# ADR 0005: Candidate-independent intelligence serving semantics

Status: Accepted
Date: 2026-09-19
Accepted: 2026-09-19
Owners: BizAI

## Context

The accepted 6B.2 intelligence chain now includes Patient Journey probabilities, point and quantile flow forecasts,
temporal calibration, central hierarchy coherence, preventive flow pressure, observed anomaly context, and
deterministic signal prioritization. Their experiment artifacts are scientifically governed but intentionally contain
candidate, evaluation, checkpoint, and retrospective fields that are not suitable as a public runtime contract.

The existing backend and frontend expose an older load-index, central-forecast, referral, and alert generation. Its
`Status`, `Forecast`, `ReferralItem`, `AlertItem`, and `/alerts` meanings differ from the new intelligence semantics.
Binding new artifacts directly to those types would either erase uncertainty/support meaning or silently redefine
an existing API.

Model families and selected artifacts may change independently from product meaning. Persistence, HTTP, and UI work
therefore need a stable semantic boundary before any new table or endpoint is designed.

## Decision

- Adopt [`../serving-contract-6b2d.md`](../serving-contract-6b2d.md) as the normative boundary between
  accepted intelligence artifacts and future persistence/API/UI adapters.
- Define public read models by estimand and product meaning, never by model family or artifact column layout.
- Preserve raw quantiles, calibrated uncertainty, central hierarchy, pressure, anomaly, materiality, support, and
  freshness as distinct semantic dimensions.
- Exclude retrospective labels and evaluation partitions from serving objects.
- Treat all accepted 6B.2B/6B.2C rows as retrospective evidence, not directly serving-eligible records; a dedicated
  legal-origin serving execution remains future reviewed code work.
- Require explicit artifact-to-contract adapters and immutable provenance; backend runtime code continues to consume
  persisted outputs rather than importing ML implementation.
- Integrate additively. Existing schemas and endpoints remain unchanged until a separately reviewed migration
  introduces new Control Tower capabilities.
- Accept this semantic boundary following independent adversarial review, corrective specification, and final
  targeted re-review. This acceptance does not implement persistence, API, frontend, or legal-origin runtime scoring.

This decision specifies no endpoint, Pydantic class, database table, migration, UI behavior, publication schedule,
or production freshness SLA.

## Dependency rules

- ML candidates and artifacts may implement the contract but must not define its public semantics accidentally.
- Future domain/application read models must not depend on LightGBM, XGBoost, AFT, hazard, or experiment classes.
- Artifact adapters must whitelist serving-legal fields and reject incompatible/ambiguous mappings.
- Pydantic/OpenAPI schemas must derive from the accepted semantic contract; generated TypeScript remains transport,
  not a UI model.
- PostgreSQL schema changes, if later approved, are owned only by Alembic and must preserve atomic batch lineage.
- Observed anomalies may provide context but cannot mutate pressure severity or Inbox ranking.
- Materiality/queue classification cannot rewrite source pressure severity.
- Estimand adapters must keep hospitalization cumulative incidence, joint competing risk, and horizon-free
  refusal-conditional-on-terminal-outcome assessments separate.

## Alternatives considered

- **Expose accepted Parquet/JSON rows directly.** Rejected because they contain evaluation labels, candidate details,
  inconsistent namespaces, and storage-specific fields.
- **Reuse legacy `Status`, `Forecast`, `ReferralItem`, `AlertItem`, and `/alerts`.** Rejected because their existing
  meanings are materially different and in-place redefinition would be a breaking semantic change.
- **Make each winning model family own a serving DTO.** Rejected because it couples clients to implementation and
  forces transport changes when candidates change.
- **Design database tables or endpoints first.** Rejected because storage/transport choices would prematurely define
  unresolved estimands, support, freshness, and identifier meaning.
- **Collapse support and uncertainty into one score.** Rejected because forecast, calibration, hierarchy, and
  threshold support answer different questions and cannot be combined honestly without a validated policy.

## Consequences

### Positive

- Model families can change while stable product semantics remain reviewable.
- Future API/UI work can distinguish raw probability evidence, calibration, fallback, freshness, and product triage.
- Evaluation leakage and physical-capacity overclaims have an explicit rejection boundary.
- Legacy product behavior can coexist during incremental migration.

### Negative

- A reviewed adapter layer is required before accepted artifacts can be served.
- Some current fields cannot map losslessly: Patient Journey needs a versioned estimand registry, non-registration
  anomaly context currently conflates false with not-applicable, anomaly severity namespace reuse must be removed at
  the adapter boundary, and production freshness remains unknown.
- Additive integration temporarily leaves old and new contracts side by side.

## Migration

After acceptance, implement a dedicated legal-origin scoring mode plus pure read-model types and artifact
mapping tests first. Then define atomic publication and, if justified, Alembic-owned read tables. Add versioned
Pydantic/OpenAPI endpoints and generated TypeScript transport only after the mapping is accepted. Build UI adapters
last, preserving legacy endpoints until an explicit deprecation plan exists.

## Verification

- Contract tests enforce every invariant in section 11 of the serving contract.
- Fixture tests prove accepted artifact fields map without reinterpretation and that serving-illegal fields are
  absent.
- OpenAPI and generated transport checks remain deterministic when integration begins.
- Architecture checks continue to prohibit backend runtime imports from ML implementation.
- No model is promoted and no scientific result is changed by adopting the semantic boundary.

## Revisit when

Revisit when customer decisions establish stable IDs, integration mode, refresh SLA,
capacity data, production ownership, and access/retention constraints. A future physical-capacity provider requires
new evidence and review; it cannot be introduced by renaming the historical-flow proxy.
