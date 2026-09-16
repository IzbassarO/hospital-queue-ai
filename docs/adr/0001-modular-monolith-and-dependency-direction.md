# ADR 0001: Modular monolith and dependency direction

Status: Proposed
Date: 2026-09-15
Owners: BizAI

## Context

`hospital-queue-ai` is one decision-support product with a FastAPI backend, React frontend,
offline/batch ML pipelines and PostgreSQL integration. The current monorepo and single backend are
small enough to operate and change together. The backend already keeps HTTP routes separate from
service functions, but services directly combine SQLAlchemy persistence, Pydantic mapping and
policy. It does not yet have domain, application or infrastructure boundaries.

Nationwide deployment requires clearer ownership and testable dependency direction, but there is no
measured need for distributed services. Premature distribution would add deployment, consistency,
security and observability costs without removing a demonstrated bottleneck.

## Decision

- Retain the monorepo and the top-level `backend/`, `frontend/`, `ml/`, `db/`, `docs/` and `tools/`
  separation.
- Keep the backend a modular monolith.
- Migrate incrementally toward pragmatic hexagonal/ports-and-adapters boundaries.
- Introduce CQRS-lite only as a logical separation between read/query responsibilities and
  write/command responsibilities.
- Do not introduce microservices, event sourcing, a message bus or separate command/query databases.

The conceptual dependency direction is:

```text
HTTP/API adapters -> application queries/commands -> domain policies
                              ^
                              |
                    infrastructure adapters
```

## Dependency rules

- Domain code must not depend on FastAPI, Pydantic transport types, SQLAlchemy, PostgreSQL, nginx,
  filesystems, networks, frontend code or ML implementation.
- Application code may depend on domain code and define ports. It must not depend on FastAPI
  request/response objects or concrete infrastructure adapters.
- API adapters translate HTTP and invoke application use cases. They contain no raw SQL and do not
  own business policy.
- Infrastructure adapters implement application ports and may depend inward on application/domain
  contracts.
- The composition root may depend on concrete adapters to wire the application.
- Query and command handlers may share PostgreSQL and transactions; CQRS-lite does not authorize
  event sourcing or distributed messaging.

## Alternatives considered

- **Keep the current service layout indefinitely.** Rejected as the target because direct
  framework/database coupling makes policy harder to test and ownership less explicit as the
  product grows. It remains the migration starting point.
- **Big-bang hexagonal rewrite.** Rejected because it would mix widespread movement with behavior
  risk and delay useful, independently verifiable improvements.
- **Microservices.** Rejected because current scale, team ownership and release topology do not
  demonstrate a need that offsets distributed-system cost.
- **Full CQRS/event sourcing.** Rejected because decision logging and analytical reads do not require
  replayable event state, a message bus or independently scaled command/read stores.

## Consequences

### Positive

- One product remains straightforward to run, test and deploy.
- Policy can become independently testable while existing HTTP and PostgreSQL adapters are retained.
- Capability boundaries can be introduced where change pressure is real.
- Cross-module transactions remain simple.

### Negative

- Incremental migration leaves old and new structures coexisting temporarily.
- Boundaries require discipline and later automated import checks.
- A single backend deployment cannot independently scale or release one module; this is accepted
  until evidence says otherwise.

## Migration

Keep all current paths initially. Select one tested capability, separate an application query or
command, define only the ports it needs, and adapt existing route/database code around it. Repeat by
capability without changing public API or runtime behavior. Do not create empty global layers or
move all services at once. Add automated dependency checks only after real target packages exist.

## Verification

- Existing audit, backend tests and API contract checks remain green after every extraction.
- Future checks reject outward dependencies from domain/application code, raw SQL in API adapters
  and cross-module imports that bypass public interfaces.
- Architecture documentation continues to distinguish implemented boundaries from the target.

## Revisit when

Reconsider the modular-monolith decision only with measurable evidence such as independently owned
teams requiring separate release cadence, incompatible availability/security boundaries, sustained
resource isolation needs that cannot be handled in-process, or load measurements showing that a
module cannot scale within the monolith. A proposal must quantify the bottleneck and the operational
cost of distribution.
