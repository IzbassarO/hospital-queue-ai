# ADR 0003: ML runtime boundary

Status: Proposed
Date: 2026-09-15
Owners: BizAI

## Context

Model training, temporal evaluation, SHAP explanation and batch prediction are implemented in the
`ml/` package. The backend image contains backend dependencies only and reads persisted predictions,
model metadata and serving marts from PostgreSQL. Current artifacts live in versioned filesystem
directories with a current-version manifest; selected metadata is mirrored into the PostgreSQL
`model_registry` table.

This already keeps expensive model work out of HTTP requests, but registry and lineage guarantees
are incomplete. Versions are time-derived, artifacts are not checksummed, and complete
dataset/config/code provenance and production monitoring are not yet recorded.

## Decision

- Training/evaluation and HTTP serving are separate runtime concerns.
- The backend must not runtime-import ML training, model, feature or explanation implementation.
- ML must not import backend application implementation.
- Batch prediction plus documented PostgreSQL prediction, metadata and serving tables is the
  integration contract.
- The current PostgreSQL model registry remains for now.
- A registry abstraction and lineage hardening must precede any decision about MLflow.
- Registered predictions must become attributable to immutable, checksummed artifact identities
  with reproducible dataset, configuration and code provenance.

The lifecycle is:

```text
data -> validate -> features -> train -> evaluate/backtest -> register -> predict -> monitor
```

## Dependency rules

- HTTP request handling consumes persisted outputs and never loads LightGBM/SHAP training code.
- `ml/` may use database contracts but not backend services, routes or application use cases.
- Registration follows evaluation; the registry records the version that produced predictions.
- Prediction and mart publication preserve transactional completeness so the API does not observe a
  partial batch.
- Monitoring spans freshness, distribution drift and outcome-based performance when labels exist.

## Alternatives considered

- **Online model inference inside FastAPI.** Rejected for the current use case: predictions are
  batch-oriented, and online loading would couple API availability and dependencies to ML runtime.
- **Merge backend and ML packages.** Rejected because it erases the existing runtime boundary and
  expands the production API dependency/supply-chain surface.
- **Adopt MLflow immediately.** Rejected until registry behavior, lineage gaps and operational needs
  are specified; a tool should implement a contract rather than define it accidentally.
- **Add a feature store.** Rejected because offline features and current batch serving have no
  demonstrated online feature-consistency requirement.

## Consequences

### Positive

- API latency and availability remain independent of training and batch compute.
- ML dependencies stay out of the backend runtime.
- Persisted tables provide an inspectable integration contract and suit current batch use.

### Negative

- Predictions are only as fresh as the batch pipeline.
- PostgreSQL/filesystem registry behavior needs custom hardening and monitoring.
- Schema and publication changes require coordination across ML and backend consumers.

## Migration

First define a `ModelRegistry` contract around the current filesystem/PostgreSQL implementation.
Add immutable artifact checksums and dataset/config/code/evaluation lineage, then link prediction
batches to those identities. Add freshness and drift monitoring, followed by outcome performance
when labels arrive. Evaluate MLflow only after these requirements and operating constraints are
measurable.

## Verification

- Automated import checks prevent backend runtime imports from `hqai_ml` and ML imports from backend
  application code.
- Prediction rows reference a registered model version whose artifact checksum verifies.
- Registration cannot promote a model without recorded evaluation and required provenance.
- Freshness/drift/performance checks publish observable status once implemented.

## Revisit when

Revisit batch serving if a measured decision workflow requires per-request features or latency that
scheduled prediction cannot meet. Revisit MLflow when multiple concurrent model owners, remote
artifact storage, approval workflows, experiment comparison or deployment promotion requirements
exceed the explicit registry contract and justify its operational cost.
