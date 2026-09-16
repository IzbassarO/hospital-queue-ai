# Architecture Decision Records

An Architecture Decision Record (ADR) captures an important, deliberate architecture decision: the
context that required a choice, the decision, its dependency rules and tradeoffs, and how the choice
will be verified and revisited.

ADRs use one of these statuses:

- **Proposed** — under review and not yet an accepted constraint.
- **Accepted** — reviewed and adopted.
- **Superseded** — replaced by a later ADR, which must be linked from the old record.
- **Rejected** — considered and deliberately not adopted.

Files use `NNNN-short-kebab-case-title.md`, for example
`0001-modular-monolith-and-dependency-direction.md`. Start from [`template.md`](template.md) and
allocate the next number.

Once Accepted, an ADR is an immutable historical record except for minor corrections such as typos
or broken links. A material change normally creates a new ADR that supersedes the old one; it does
not rewrite the original decision as though it had always been different.

Generated investigations, exploratory architecture reports and temporary analysis are not ADRs.
They belong in gitignored working locations such as `scratch/` or `reports/`. Only reviewed decision
records belong under `docs/adr/`.

## Index

| ADR | Status | Decision |
|---|---|---|
| [0001](0001-modular-monolith-and-dependency-direction.md) | Accepted | Modular monolith and dependency direction |
| [0002](0002-postgresql-and-schema-ownership.md) | Accepted | PostgreSQL and schema ownership |
| [0003](0003-ml-runtime-boundary.md) | Accepted | ML runtime boundary |
| [0004](0004-openapi-transport-contract.md) | Accepted | OpenAPI transport contract |
