# Architecture baseline

This document records the implemented architecture and the proposed direction for
`hospital-queue-ai`. It is a baseline for incremental change, not a claim that the target
boundaries already exist. Detailed endpoint, data, UI, model and security behavior remains in
[`api.md`](api.md), [`data.md`](data.md), [`frontend.md`](frontend.md),
[`model_card.md`](model_card.md) and [`security.md`](security.md).

The decisions behind the proposed direction are under [`adr/`](adr/). ADRs 0001–0005 are **Accepted**. The
candidate-independent [`6B.2D intelligence serving contract`](serving-contract-6b2d.md) is **Accepted / closed** as
a semantic design; persistence, API, frontend, and legal-origin runtime scoring remain future work. The boundaries
automated today are listed in section 13.

## 1. Architecture principles

- Keep the system understandable and deployable as one product. Add distribution only for a
  measured operational reason.
- Separate policy from delivery and storage concerns. FastAPI, SQLAlchemy, PostgreSQL, files and
  networks are implementation details around application behavior.
- Prefer incremental extraction with tests over a big-bang rewrite.
- Keep human accountability explicit: forecasts and recommendations support decisions; they do
  not make clinical or administrative decisions automatically.
- Treat schemas and contracts as owned assets. Database changes go through Alembic; HTTP transport
  changes originate in FastAPI/Pydantic and OpenAPI.
- Keep training/evaluation outside the request path. The API consumes persisted predictions and
  serving marts rather than importing model code.
- Make model outputs attributable to a model version and progressively strengthen reproducibility,
  lineage and monitoring.
- Create only boundaries that have current consumers. Empty architecture folders are not progress.
- Keep reviewed production documentation in `docs/`; keep generated and exploratory work out of
  the version-controlled product surface.

## 2. Current architecture

### Repository and deployment

The current monorepo deliberately retains these top-level responsibilities:

| path | current responsibility |
|---|---|
| `backend/` | FastAPI HTTP service, Pydantic schemas, SQLAlchemy models, Alembic migrations and API tests |
| `frontend/` | React 18/Vite/TypeScript UI, runtime response validation and TanStack Query integration |
| `ml/` | offline ingestion, feature building, LightGBM training/evaluation, batch prediction, registry persistence and serving-mart builds |
| `db/` | PostgreSQL extension initialization |
| `docs/` | reviewed product, architecture, API, data, model and security documentation |
| `tools/` | repository audit and test-fixture tooling |

Docker Compose currently runs PostgreSQL, the FastAPI backend and the nginx-served frontend for
local/demo use. nginx proxies `/api` and injects the demo API key server-side; the built browser
bundle contains no supported-setup credential. Compose is not a production topology.

### Backend

The backend is presently a conventional layered-by-folder FastAPI application:

```text
app/main.py -> app/api/routes.py -> app/services/* -> SQLAlchemy/PostgreSQL
                         |                 |
                         +-> Pydantic schemas <-+
```

`main.py` is the application entry point and middleware/exception composition point. Routes
perform HTTP binding and call service functions. Services contain query composition, decision
validation, recommendation policy, export assembly and schema mapping. They depend directly on
SQLAlchemy sessions/models and on Pydantic response types; some contain raw SQL. Authentication,
configuration and access logging live under `app/core/`.

This is **not currently hexagonal architecture**. There are no application, domain or
infrastructure boundaries, and service code mixes application policy with persistence and
presentation concerns. Route functions do not contain raw SQL, which provides a useful starting
boundary.

### ML and data

The implemented offline flow is:

```text
raw files -> validate/normalize -> Parquet + PostgreSQL facts/aggregates
          -> features -> train/tournament -> temporal evaluation/calibration/backtest
          -> disk artifacts/current-version manifest -> batch predict
          -> PostgreSQL predictions/model_registry -> PostgreSQL serving marts
```

Training reads Parquet and does not run in the API process. `ml/pipelines/predict.py` loads current
disk artifacts, produces batch predictions and writes prediction and registry tables.
`ml/pipelines/build_marts.py` builds the read-oriented `mart_*` tables consumed by the backend.
The current registry is a checksummed filesystem artifact/run layout plus the PostgreSQL `model_registry` table.
Verified artifact SHA256 and nullable run/data/config/code/evaluation lineage are mirrored into dedicated
PostgreSQL columns; unavailable historical provenance remains `NULL`. There is no general registry interface or
production drift/outcome monitor yet.

The patient-journey tournament is an offline experiment branch over the same Parquet feature boundary. It constructs
fixed-cutoff right-censored labels, evaluates empirical, AFT and discrete hazard/competing-risk candidates, and writes
checksummed ignored artifacts plus a human-review decision. It does not publish current pointers, write serving
predictions, change PostgreSQL or introduce an API/runtime dependency. Candidate/trial/fold and calibration state is
written only by the coordinator through the existing fenced checkpoint contract. Hyperparameters are selected once
per candidate from aggregate validation performance across compatible temporal folds; legacy artifacts are never
scored where their training window overlaps validation, calibration or test. The principal cohort treats source
time-order reversals on the same calendar date as 0.5-day events and reports a strict timestamp-order sensitivity.

The proposed 6B.2D contract is the semantic boundary between accepted Patient Journey/flow/signal artifacts and
future persistence, API and UI adapters. It is candidate-independent; keeps raw quantiles, calibrated uncertainty,
central hierarchy, pressure, anomaly, materiality, support and freshness distinct; and excludes retrospective
evaluation labels from serving objects. This is documentation only: no serving table, endpoint or UI behavior has
been implemented for that contract.

The backend package has no ML dependency and does not import `hqai_ml`. The ML package does not
import backend application code. Shared PostgreSQL tables are the implemented integration boundary.

### Frontend

The frontend currently uses technical folders: `api/`, `components/`, `pages/`, `i18n/`, `lib/`
and `test/`. Pages compose shared components and TanStack Query hooks. There are no page-to-page
imports. `routes.tsx` imports pages and assembles the route tree.

HTTP request functions, handwritten runtime schemas and inferred view-facing TypeScript types live under
`src/api/`. Generated OpenAPI transport types now live under `src/api/generated/`, while the existing client keeps
runtime validation of untrusted responses. The current adapters still duplicate some transport shapes and will be
migrated incrementally. This is **not currently Feature-Sliced Design**.

## 3. Target architecture

The proposed target is a **modular monolith** with pragmatic ports-and-adapters boundaries,
**CQRS-lite**, an explicit ML runtime boundary and incremental feature slicing in the frontend.

“Modular monolith” means one product and one primary backend deployment, with module boundaries
enforced inside the codebase. “Pragmatic hexagonal” means domain/application code is protected
from frameworks where that protection pays for itself; it does not require wrapping every library.
“CQRS-lite” means separating query and command responsibilities in code. It does not imply a
message bus or separate data stores.

The conceptual backend direction is:

```text
HTTP/API adapters
        |
        v
application queries / commands ----> application ports
        |                                  ^
        v                                  |
domain policies                    infrastructure adapters
                                           |
                                     PostgreSQL/files/auth
```

Target modules should follow product capabilities such as monitoring, recommendations, decisions,
catalog and administration rather than becoming one global set of technical layers. No target
folder is created until code is being moved behind a tested boundary.

## 4. Runtime boundaries

| runtime concern | current boundary | governing direction |
|---|---|---|
| browser UI | static React bundle served by nginx; `/api` only | depends on the documented HTTP contract, never on database or ML internals |
| HTTP backend | FastAPI process backed by PostgreSQL | owns request handling, authorization, application orchestration and decision writes; does not train or runtime-import models |
| PostgreSQL | durable facts, predictions, registry metadata, marts, decisions, keys and access logs | explicit integration boundary with schema controlled only by Alembic |
| ingest/train/evaluate | offline Python processes using raw data/Parquet and filesystem artifacts | may be compute-heavy and independently scheduled; never runs in an HTTP request |
| predict/mart build | offline batch processes writing documented PostgreSQL contracts | publishes complete transactional batches for backend consumption |
| nginx | local/demo static server and reverse proxy | deployment adapter, not domain policy or a presumed national production edge design |

Docker Compose defines the local/demo topology only. Production hosting, network separation,
identity, secrets, observability and high-availability topology remain subject to actual government
and hosting constraints documented in `security.md`.

## 5. Backend dependency direction

The target dependency rules are:

- `domain` is independent of FastAPI, Pydantic transport models, SQLAlchemy, PostgreSQL, nginx,
  filesystem/network infrastructure, the frontend and ML implementation.
- `application` may depend on domain policy and may define ports/interfaces. It must not accept or
  return FastAPI `Request`/`Response` objects or depend directly on concrete infrastructure.
- API adapters may validate/translate HTTP and invoke application queries/commands. They must not
  contain raw SQL or become the home for business policy.
- Infrastructure adapters implement application ports and may depend inward on application/domain
  contracts. Database, auth, export and telemetry details belong here when extracted.
- The composition root (`main.py` or an equivalent bootstrap module) may know concrete adapters and
  wire them to application use cases.
- Dependencies point inward; domain/application code does not import API or infrastructure code.

CQRS-lite will distinguish read-heavy analytical queries from commands such as recording decisions
or administering credentials. Both may continue to use the same PostgreSQL database and normal
transactions. There is no event sourcing, message bus or separate read/write database.

## 6. ML lifecycle and runtime boundary

The target lifecycle is explicit even where current automation is incomplete:

```text
data -> validate -> features -> temporal protocol -> train -> evaluate/backtest
     -> calibrate/uncertainty -> register -> predict -> monitor
```

Rules:

- Registration follows successful evaluation; “trained” and “eligible for prediction” are distinct
  lifecycle states even if the current pipeline performs them in one command.
- The backend must not runtime-import ML training, feature, explanation or model implementation.
- ML must not import backend application implementation.
- Batch predictions plus documented PostgreSQL metadata/serving tables remain the integration
  contract for the current scale and latency needs.
- Every served prediction must be attributable to an immutable model/version identity.
- New model artifacts are atomically published with deterministic per-file and aggregate SHA256 manifests.
  Loading and registration reject checksum mismatches.
- Each training invocation owns an atomic `artifacts/runs/<run_id>/run.json` record. It separates semantic dataset,
  normalized configuration and ML source/Git identities; records temporal availability rules, seeds, relevant
  implementation versions, metrics and baselines. Execution resources/platform are recorded separately from the
  scientific identity. Independently atomic per-unit checkpoint files support candidate/trial/fold/origin resume,
  and an atomic local lock permits only one writer per run.
- Registration requires successful evaluation and complete artifact identity. Pre-6B.1 artifacts are checksummed
  on first load but remain explicitly `legacy_unattributed` rather than gaining invented provenance.
- Evaluation completion does not imply approval. Training retains candidates by default, and an explicit operator
  promotion atomically replaces the validated multi-model filesystem current set.
- Only the coordinator writes experiment/checkpoint state. On-disk lock identities fence every mutation; stale-lock
  recovery requires exact confirmation, refuses a same-host live owner and records an audit event.
- Monitoring must eventually cover pipeline/data freshness, input and prediction distribution
  drift, and outcome-based model performance when labels become available.

The current PostgreSQL registry remains in place. Alongside model/version, training window, metrics, current status,
artifact path and card, it stores verified artifact SHA256 plus nullable data/config/code/run identities and
evaluation status. The filesystem manifest is the atomic candidate-selection authority; PostgreSQL is the
transactional serving snapshot. They are intentionally retryable rather than a distributed transaction. This
baseline does not introduce MLflow or a feature store.

## 7. Frontend dependency direction

The proposed incremental Feature-Sliced dependency direction is:

```text
app -> pages -> widgets -> features -> entities -> shared
```

Higher layers may depend on lower layers, never the reverse. Specific rules:

- Do not create unused layers. The first physical migration may need only `app`, `pages` and
  `shared`.
- Pages must not import other pages.
- Slices should eventually expose public APIs so callers do not depend on arbitrary internal files.
- Generated HTTP transport code belongs under `shared/api` or an equivalent low-level integration
  location.
- OpenAPI transport DTOs and UI/view models are separate concerns. Handwritten presentation models
  may remain, while duplicated handwritten HTTP DTOs should disappear after generation is adopted.

The current `pages`, `components` and `api` layout remains until a concrete feature migration is
selected and protected by tests.

## 8. Database and schema ownership

- PostgreSQL remains the primary durable store.
- Alembic under `backend/alembic/` is the sole schema migration authority. SQLAlchemy models are
  checked against migrations with `alembic check`.
- Backend and ML may exchange data through intentionally documented tables/contracts. Current key
  contracts include facts/aggregates, `pred_*`, `model_registry`, `mart_*` and backend-owned
  decision/security tables; details are in `data.md` and `api.md`.
- Neither backend runtime code nor ML pipelines may create or alter schema outside Alembic
  migrations. Pipelines may load/truncate/rebuild data only according to the table contract.
- Indexing and measured query-plan work precede speculative database scaling changes.
- Partitioning is not assumed. It requires measured table volume, retention or query-plan evidence.
- Docker Compose is not the production database architecture.
- Production backup, RPO, RTO and point-in-time recovery design is deferred until deployment and
  data-owner requirements are known; the current `make backup`/`make restore` flow is prototype
  operations, not that final design.

## 9. API contract ownership

FastAPI OpenAPI is the implemented canonical HTTP transport contract:

```text
Pydantic request/response models
        |
        v
FastAPI OpenAPI
        |
        v
generated TypeScript transport types
        |
        v
frontend query/view adapters
```

Every public schema operation has a stable, explicit, unique `operationId`. `tools/openapi_contract.py` generates
the deterministic committed `backend/openapi.json` snapshot and checks it directly against the current application.
`@hey-api/openapi-ts` generates type-only artifacts under `frontend/src/api/generated/`; `npm run api:check`
regenerates into a temporary directory and byte-compares the result. `make audit` runs both checks, and GitHub CI
runs the same audit after Python, Node and PostgreSQL fixture setup.

Generated transport DTOs describe wire data; they must not become UI view models by default.
Frontend adapters may combine, format or narrow them for screens. Existing handwritten UI types may
remain. The existing handwritten schemas also retain runtime response validation, which generated TypeScript types
do not provide. Duplicate handwritten HTTP request/response contracts should be removed incrementally as adapters
migrate, not by weakening runtime validation.

## 10. Documentation and generated-artifact policy

Version-controlled, reviewed material belongs under `docs/`, including architecture documentation,
ADRs, API documentation, security documentation, model cards, data contracts and curated operational
runbooks.

The following are transient and must remain in gitignored locations such as `scratch/`, `reports/`,
`artifacts/`, `notebooks/` or `data/`: exploratory or generated reports, temporary research and
reasoning, scratch files, model binaries, experiment output, notebook transient output, raw/local
datasets and local exports. An ADR is a reviewed decision record, not a generated investigation.

## 11. Explicit non-goals

The target does not introduce the following without a future measurable requirement:

- microservices or independently deployed domain services;
- Kubernetes, Terraform or a production deployment topology;
- Kafka, Redis, Spark or ClickHouse;
- event sourcing, a message bus or separate command/query databases;
- Next.js;
- MLflow or a feature store;
- speculative PostgreSQL partitioning.

These are not maturity badges. A proposal to add one must identify the observed constraint, expected
benefit, operational ownership and a simpler alternative that was measured first.

## 12. Migration strategy

1. Keep the current root layout and green audit/test/build gates.
2. Record and review architectural decisions before structural work; retain ADRs 0001–0005 and implement ADR 0005's
   accepted semantic boundary only through separately reviewed persistence, API, frontend, and scoring changes.
3. Select one backend capability and separate an application query or command behind a port while
   preserving routes and behavior. Move policy inward only when tests demonstrate the seam.
4. Maintain stable OpenAPI operation IDs and deterministic generated transport types; migrate frontend adapters
   incrementally before removing duplicated transport definitions or runtime validation.
5. Introduce frontend layers only as migrated code needs them; prevent page-to-page and reverse-layer
   dependencies.
6. Build on the checksummed PostgreSQL/filesystem registry baseline with a registry interface when justified,
   without changing the serving boundary.
7. Add automated dependency and contract checks after the physical boundaries exist.

Each step must be independently releasable. No step combines a directory rewrite with API, schema,
frontend or ML behavior changes unless that behavior change is itself the reviewed objective.

## 13. Architecture fitness functions

`tools/architecture_check.py` uses Python's AST and runs as the `architecture` step of `make audit`.
It checks production Python paths, not comments, docstrings or ordinary string literals. Its source
targets exclude current test, migration and generated-artifact locations.

The `openapi` audit step validates the stable operation inventory and current `backend/openapi.json`; the
`web-contract` step regenerates the frontend TypeScript artifacts in a temporary directory and compares bytes.
GitHub Actions runs the complete `make audit`, so these contract checks and ARCH001–ARCH005 are continuous on every
push and pull request.

| rule | status | protected boundary |
|---|---|---|
| ARCH001 | ENFORCED | `backend/app/**/*.py` must not import `hqai_ml` or ML pipeline implementation; persisted predictions, registry metadata and serving tables remain the integration boundary |
| ARCH002 | ENFORCED | `ml/hqai_ml/**/*.py` and `ml/pipelines/**/*.py` must not import the backend's `app` implementation |
| ARCH003 | ENFORCED | if present, `backend/app/domain/**/*.py` must not import FastAPI, SQLAlchemy/psycopg, backend API/application/infrastructure implementation or ML implementation |
| ARCH004 | ENFORCED | if present, `backend/app/application/**/*.py` must not import FastAPI, SQLAlchemy/psycopg, concrete backend adapters/API/services or ML implementation; domain imports remain allowed |
| ARCH005 | ENFORCED | `backend/app/api/**/*.py` must not construct raw SQL through `sqlalchemy.text` or pass a literal SQL statement to `execute`/`executemany` |
| ARCH006 | DEFERRED | a repository-wide DDL-string rule would flag legitimate ephemeral DuckDB table creation in ML ingestion and cannot reliably identify the target database without connection/data-flow analysis; Alembic drift checking remains active but is not claimed as full static enforcement |

ARCH003 and ARCH004 require no empty scaffolding: they have no targets today and activate
automatically when the corresponding directories contain Python files.

Still planned for later steps: frontend layer/public-API rules after physical slices exist; explicit
backward-compatibility classification beyond freshness checks; explicit shared-table ownership checks; model
monitoring evidence; and generated-artifact policy enforcement.
