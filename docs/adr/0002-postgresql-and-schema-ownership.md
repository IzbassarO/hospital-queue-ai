# ADR 0002: PostgreSQL and schema ownership

Status: Proposed
Date: 2026-09-15
Owners: BizAI

## Context

PostgreSQL currently holds durable source-derived tables, predictions, registry metadata, serving
marts, decisions, API keys and access logs. Offline ML/data pipelines populate documented tables;
the FastAPI backend reads them and owns operational writes. Alembic migrations under `backend/`
define the schema, and `alembic check` compares it with SQLAlchemy models.

This shared database is a deliberate integration boundary, but shared access must not become
independent schema ownership. The current data volume and query latency do not justify partitioning
or a second database technology. Docker Compose and prototype backup commands do not define a
nationwide production topology or recovery objective.

## Decision

- PostgreSQL remains the primary durable data store.
- Alembic remains the sole schema migration authority.
- Backend and ML may communicate through deliberately documented database contracts.
- Neither subsystem may independently create, alter or drop schema outside Alembic migrations.
- Partitioning and database scaling changes require measured evidence; indexing and query-plan work
  comes first.
- Docker Compose remains local/demo topology, not the production deployment architecture.
- Final backup, RPO, RTO and point-in-time recovery design waits for deployment, data-owner and
  government hosting requirements.

## Dependency rules

- Every schema change is represented by an Alembic migration and reflected in SQLAlchemy metadata.
- Pipelines may load, truncate or rebuild data only within their documented table contracts.
- Shared tables must document grain, writer, readers, refresh/transaction semantics and model
  identity where relevant.
- Backend application policy must not depend on pipeline implementation details; ML must not import
  backend application code to use the schema.
- Production database credentials and privileges should eventually separate migration, pipeline,
  read and operational-write responsibilities, without changing schema authority.

## Alternatives considered

- **Separate backend and ML databases now.** Rejected: it adds replication, consistency and
  operational work without a current isolation or scaling requirement.
- **Allow each subsystem to manage its own tables.** Rejected: cross-boundary contracts would drift
  and migrations could conflict.
- **Adopt an analytical database or distributed data platform.** Rejected: PostgreSQL marts meet
  current serving needs, and no measured workload justifies ClickHouse, Spark or similar systems.
- **Partition tables pre-emptively.** Rejected until retention, volume and query plans show a benefit.

## Consequences

### Positive

- One auditable migration history governs the whole product schema.
- Transactional batch publication and backend reads remain simple.
- Existing tooling, tests and operational knowledge are retained.

### Negative

- Shared-database contracts require coordination between backend and ML changes.
- Workloads can contend for the same database if scheduling and resource controls are neglected.
- Final availability and disaster-recovery guarantees remain unresolved until deployment
  requirements are known.

## Migration

Document existing shared tables and their ownership before changing them. Add contract checks and
least-privilege roles in later atomic steps. Optimize measured queries with indexes or mart design
before considering partitioning or another store. Define production backup/PITR procedures only
after RPO/RTO, retention, hosting and data classification are approved.

## Verification

- `alembic check` and migration tests remain green.
- Repository checks detect schema mutation outside Alembic once such a fitness function is added.
- Data/API documentation identifies writers and readers of integration tables.
- Query-plan and volume evidence accompanies any scaling proposal.

## Revisit when

Revisit when measured data size, retention, write throughput, query latency, workload contention,
availability isolation or legal residency requirements cannot be met through PostgreSQL schema,
indexing, marts, replicas or operational configuration. Revisit recovery design when the deployment
authority supplies explicit RPO, RTO, PITR, retention and encryption requirements.
