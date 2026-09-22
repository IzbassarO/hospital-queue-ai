# Step 6B.5 — Model Assurance

Status: **6B.5 — CLOSED**  
ML status: **ML CORE — CLOSED / FROZEN**

This stage adds a deterministic, versioned assurance layer over already accepted scientific evidence. It does not
train, tune, recalibrate, select, promote, or serve a model. The bundle is candidate-independent and remains inside
the ML/evidence boundary.

## 1. Preconditions and closure decision

- Accepted evidence baseline commit: `1dcda96b8d8bf760e481c61357b98d98c914b9ed`
  (`docs(ml): close decision alternatives real-data evidence`).
- GitHub CI for that commit: completed successfully on 2026-09-22, run `35740567213`.
- Authoritative flow chain is represented without an implicit “latest” substitution:
  `flow-evidence-6b2b1-corrected-v3` → `flow-quantile-6b2b2-real-v1` →
  `flow-calibration-6b2b2b-real-v1` → `flow-hierarchy-6b2b3-real-v1` →
  `flow-pressure-6b2c1-real-v2` → `signal-prioritization-6b2c2-real-v2` →
  `flow-scenario-6b3-real-v1` → `decision-alternatives-6b4-real-v3`.
- Patient Journey is represented separately by estimand semantics. Missing versioned estimand IDs are `UNKNOWN`
  with a reason; they are not invented.
- Decision-alternative v1/v2 implementation/data-representation failures remain `FAILED_EVIDENCE`, not rejected
  science. Accepted v3 remains `ACCEPT_WITH_P2`.

All G0–G12 gates pass. There was no retraining, recalibration, model selection, real-data pipeline run, runtime
backend change, database migration, API/OpenAPI change, generated TypeScript change, or frontend change.

## 2. Versioned contract and generation

The normative schema is `docs/model-assurance-contract-v1.schema.json`. The reviewed registry is
`ml/configs/model_assurance.yaml`; it is intentionally separate from `ml/configs/model_cards.yaml`. The generator is
`ml/hqai_ml/assurance.py`, exposed by `ml/pipelines/model_assurance.py` and `make model-assurance`.

Generated output is confined to the ignored path:

```text
artifacts/model_assurance/model-assurance-6b5-v1/model_assurance.json
```

The top-level `model_assurance_v1` contract contains:

- schema/contract/product-contract versions, assurance ID and SHA256 identity;
- accepted-evidence source commit and `ML_CORE_CLOSED_FROZEN` state;
- canonical capability records;
- failed-evidence history;
- global claim boundaries;
- explicit future monitoring expectations; and
- freshness semantics with unresolved SLA thresholds kept null.

Each capability keeps scientific lifecycle, acceptance verdict, and product-consumption status separate. Its
identity block always has all v1 identity fields. A known value is `AVAILABLE`; a missing value is `UNKNOWN` with a
reason; a concept that does not apply is `NOT_APPLICABLE` with a reason. Support tier
(`DIRECT_SUPPORTED` / `FALLBACK_LIMITED` / `UNSUPPORTED`) and range completeness
(`COMPLETE` / `RANGE_LIMITED`) are separate arrays and are never collapsed into a score.

The generated local closure bundle has assurance identity:

`f504defefdd87bcbb01c670b68469ba4c0e016be7f40ca89452baf69b73f39f5`

## 3. Canonical inventory

| Capability ID | Evidence | Verdict | Product consumption |
|---|---|---|---|
| `patient_journey_hospitalization` | ACCEPTED | ACCEPT | ELIGIBLE_AFTER_INGESTION |
| `patient_journey_refusal` | ACCEPTED | ACCEPT | ELIGIBLE_AFTER_INGESTION |
| `patient_journey_competing_risk_baseline` | ACCEPTED | ACCEPT | ELIGIBLE_AFTER_INGESTION |
| `patient_journey_competing_risk_ml_challenger` | REJECTED | DO_NOT_PROMOTE | NOT_FOR_PRODUCT |
| `flow_point_forecast` | ACCEPTED | ACCEPT | ELIGIBLE_AFTER_INGESTION |
| `flow_quantile_forecast` | ACCEPTED | ACCEPT | ELIGIBLE_AFTER_INGESTION |
| `flow_temporal_calibration` | ACCEPTED | ACCEPT | ELIGIBLE_AFTER_INGESTION |
| `flow_hierarchical_coherence` | ACCEPTED | ACCEPT | ELIGIBLE_AFTER_INGESTION |
| `preventive_flow_pressure` | ACCEPTED | ACCEPT | ELIGIBLE_AFTER_INGESTION |
| `observed_unusual_flow` | ACCEPTED | ACCEPT | ELIGIBLE_AFTER_INGESTION |
| `signal_prioritization` | ACCEPTED | ACCEPT | ELIGIBLE_AFTER_INGESTION |
| `forecast_stress_test` | ACCEPTED | ACCEPT_WITH_P2 | EVALUATION_ONLY |
| `decision_alternatives` | ACCEPTED | ACCEPT_WITH_P2 | EVALUATION_ONLY |

Eligibility means a future explicit, validated publication/ingestion path may consume the evidence. It does not
mean live serving exists. Scenario and decision-alternative evidence remains retrospective evaluation-only.

## 4. Identity and reproducibility

The assurance identity is SHA256 over canonical UTF-8 JSON (sorted keys, compact separators, no NaN) after removing
only `assurance_identity_sha256` and the audit-only `generated_at`. Therefore different audit timestamps over the
same versioned configuration produce the same identity. Capability/run/scientific/data/config/code/artifact values
are copied from the named run manifests; generation cross-checks every locally available manifest and can require
all ignored evidence files with `--require-evidence-files`. It never recomputes accepted metrics or decisions.

The bundle retains source-document and run-manifest references. The accepted-evidence source commit is explicit,
and no source is resolved by an implicit newest/latest lookup. A clean checkout may lack ignored real-data artifacts;
the versioned identity snapshot and lineage references remain usable, while strict local verification can fail on
absence when requested.

## 5. Claim and governance boundary

The current pressure provider is exactly `historical_flow_proxy_v1`; it is not physical capacity. The contract and
tests prohibit describing the project as an AI recommender, patient router, autonomous routing system, capacity
optimizer/planner, Digital Twin, causal simulator, or intervention engine. They also prohibit claims about free
beds, occupancy, staffed capacity, physical feasibility, causal/clinical benefit, reduced waiting time, or improved
outcomes without future accepted evidence.

Every capability serializes `human_review_required`, `autonomous_action`, `capacity_checked`,
`causal_effect_claimed`, `serving_claim`, `physical_feasibility_status`, and `promotion_status`. V1 validation fails
if autonomous action, capacity evidence, causal effects, or live serving are asserted. Decision alternatives remain
“retrospective mathematical alternatives for human review.”

## 6. Freshness and monitoring

The four future runtime states are `FRESH`, `STALE`, `DEGRADED`, and `UNKNOWN`. Current static evidence is `UNKNOWN`
because no approved customer refresh SLA or runtime publication timestamp exists. The contract stores no invented
threshold.

Monitoring entries are explicitly `FUTURE_EXPECTATION`, not live-system claims. They cover data freshness, schema
and stable-ID drift, lineage/hash mismatch, publication failures, support/range mix, fallback/unsupported growth,
predictive/calibration evidence and interval coverage where applicable, pressure-provider availability, scenario
verification, receiver-worsening/full-verification failures, runtime/resources, and human-review audit trails.

## 7. Recommended PostgreSQL projection (design only)

Do not put scenario or decision-alternative records into the existing model registry as fake models. The next stage
should ingest the JSON bundle explicitly and project it into two compact read-model tables:

### `model_assurance_snapshot`

| Column | Recommended semantics |
|---|---|
| `id` | internal primary key |
| `assurance_id` | contract assurance ID |
| `contract_version` | assurance contract version |
| `bundle_sha256` | `assurance_identity_sha256` |
| `source_commit` | evidence source commit |
| `ml_freeze_status` | frozen lifecycle state |
| `published_at` | ingestion/publication timestamp, not identity input |
| `is_active` | explicitly activated current snapshot; unique active row |

Recommended uniqueness: `(assurance_id, bundle_sha256)`. Publication should be transactional, verify the bundle
identity before insertion, and retain superseded snapshots for audit.

### `model_assurance_capability`

| Column | Recommended semantics |
|---|---|
| `id` | internal primary key |
| `snapshot_id` | FK to snapshot, cascade only under an explicit retention policy |
| `capability_id` | stable capability ID, unique within snapshot |
| `evidence_status` | ACCEPTED / REJECTED / EXPERIMENTAL |
| `acceptance_verdict` | independent scientific verdict |
| `product_consumption_status` | independent product eligibility |
| identity columns | run/scientific/artifact/data/config/code values where available |
| governance columns | review/action/capacity/causal/serving/feasibility/promotion fields |
| `freshness_state` | FRESH / STALE / DEGRADED / UNKNOWN |
| `details` JSONB | heterogeneous estimand, lineage, support, evidence, limitations, claims, monitoring references |

The backend must ingest/persist the candidate-independent JSON and must not runtime-import `hqai_ml`. The frontend
must consume backend DTOs and must never read artifact JSON directly. No migration or runtime code is part of 6B.5.

## 8. Closure evidence and focused review

- Targeted assurance tests: `10 passed`.
- Strict source verification during generation: `13 verified, 0 absent`.
- `git diff --check`: PASS.
- `make audit`: PASS.
- P0 findings: none.
- P1 findings: the focused review found that Patient Journey artifact SHA values were initially marked unknown even
  though final-confirmation/source-run checkpoint artifacts carried them; the canonical records now retain the
  applicable artifact SHA values. No P1 remains.
- P2 findings: versioned Patient Journey estimand IDs remain unresolved pending the reviewed estimand registry and
  product adapter; production refresh SLA remains unresolved; ignored artifacts may be absent in a clean checkout,
  so strict source-file verification is an explicit publication control. These limitations are recorded and do not
  alter accepted science.

The next work is production integration only:

`PostgreSQL read models → backend repositories/use cases → API/OpenAPI → generated TypeScript → frontend Control Tower`

That integration is not implemented in this stage.
