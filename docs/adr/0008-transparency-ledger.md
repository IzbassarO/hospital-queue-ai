# ADR 0008: Transparency ledger for publications and decisions

Status: Proposed
Date: 2026-09-28
Owners: BizAI

## Context

Aqyl Kezek supports people who make hospitalization-flow decisions from published forecasts and signals. The product
already stores publications with their identities and specialist decisions with the identity of the publication
they were made against, but nothing makes a later silent change to those rows detectable, and an outside reviewer
has to trust the operator's database. A government deployment needs to show what was known and what a person
decided, and when, without publishing personal free text.

## Decision

- Keep an append-only, SHA-256 hash-chained ledger (`transparency_ledger`) in the same PostgreSQL database, with the
  protocol, canonical JSON contract and event builders defined once in `app/domain/transparency` (the first code
  under `app/domain`, so ARCH003 now guards it).
- Every publication snapshot and every human decision appends its entry **in the business transaction**; the ledger
  never commits on its own and nothing is written asynchronously.
- Appends are serialized by a transaction-scoped PostgreSQL advisory lock; `seq`, `entry_hash` and `prev_hash` are
  unique, and triggers reject `UPDATE`, `DELETE` and `TRUNCATE`.
- Private free text is represented by salted SHA-256 commitments; salts are random, stored in their own
  append-only table, never exposed.
- Backfill states only what durable rows prove, in one documented global order, from persisted salts, so it is
  deterministic; activations are recorded live only.
- Three verifiers with distinct claims: offline (stdlib) and browser (Web Crypto) over the public export; server
  verification against rows and salts.
- No signatures for now; trusted heads (receipts, the browser's remembered head, an auditor's `seq:hash`) are the
  anchor against a full rewrite. Ed25519-signed heads are a deployment option.

Details and the threat model: [transparency-ledger.md](../transparency-ledger.md).

## Dependency rules

- `app/domain/transparency` imports only the standard library. Canonical JSON and payload builders are frozen per
  protocol version: a change of meaning is a new event type or protocol version. Migrations never import it.
- Writers of covered tables go through the services that append (`specialist_decisions`, `activity`, the six
  `publish` functions). Writing a covered table any other way is detected as `UNCOVERED_SOURCE_ROW`.
- No endpoint and no export returns a salt or committed free text.
- Tests that write covered rows against the shared database use a rolled-back transaction (`ledger_isolation`).
- `tools/ledger_verify.py` and `frontend/src/verify` re-implement the contract independently and are tested against
  `docs/transparency-ledger-vectors.json`.

## Alternatives considered

- **Audit table without chaining.** Rejected: a row can be changed or removed without trace.
- **Public blockchain or distributed ledger.** Rejected: one writer, no need for consensus; adds cost, latency,
  personal-data risk and vocabulary the product must not use.
- **Asynchronous audit events (queue, outbox).** Rejected for this purpose: a decision and its record could
  diverge; ADR 0001 excludes a message bus.
- **Python-process lock for ordering.** Rejected: several worker processes; the database must serialize.
- **Deterministic salts derived from ids.** Rejected: makes commitments to short text guessable.
- **Ed25519 signatures now.** Deferred: no vetted signing library in the backend dependencies; key custody is a
  deployment decision.

## Consequences

### Positive

- Silent edits to decisions, publications or the ledger itself become detectable with exact entry and reason.
- Specialists get a receipt; anyone with viewer access can verify independently in the browser or offline.
- No personal free text is published.

### Negative

- Covered rows can no longer be deleted for cleanup without breaking verification; tests needed a transactional
  isolation fixture.
- Publishing and deciding take one more short serialized step (single-digit milliseconds).
- A privileged database owner can still rewrite everything; only external heads reveal it.
- Live-only history (activations, concurrent append order) cannot be rebuilt, so migrations 0018/0019 refuse a
  downgrade that would destroy it or the salts; abandoning a release means rolling forward or an explicit restore
  of a pre-upgrade backup after archiving the ledger (transparency-ledger.md §10).

## Migration

Migrations 0018 (salts) and 0019 (ledger, triggers, backfill), on top of 0017. The API role gets `SELECT, INSERT`
on both tables when `hqai.app_role` is set. The migrations import nothing from `app/`: 0019 carries a frozen copy
of protocol v1, held byte-for-byte to the application's builders by `test_transparency_migration.py`, so a clean
database migrated later gets exactly today's bytes. Operators record the head after deployment (`make ledger-verify`).

## Verification

`backend/tests/test_transparency*.py` (append-only triggers, rollback, 20 concurrent appends, idempotent retries,
backfill determinism and order, privacy, tamper cases, API), the shared vectors in Python and TypeScript,
`make ledger-demo`, and `make audit` (architecture rules cover `app/domain`).

## Revisit when

Signed checkpoints become a requirement (choose key custody and a vetted Ed25519 library), the ledger grows beyond
what on-demand full verification handles, or further tables must be covered.
