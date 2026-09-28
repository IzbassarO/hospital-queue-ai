# Transparency ledger — «Проверяемый ИИ»

Aqyl Kezek's product rule is *the model warns, a person decides*. This ledger makes that rule checkable after the
fact: it proves **what intelligence was published, which publication a specialist had in front of them, what they
decided and when** — and it makes a silent change to any of that detectable. It does not prove that a forecast was
right or a decision was good.

It is a tamper-evident hash chain in PostgreSQL, not a blockchain: one writer (the application), no consensus, no
tokens. The business tables stay the source of truth; the ledger is the integrity layer that makes statements about
them verifiable.

| Where | What |
|---|---|
| `backend/app/domain/transparency/` | canonical JSON, entry hashing, commitments, chain verifier, event builders (pure, no framework) |
| `backend/app/repositories/transparency.py` | advisory lock, head, inserts, reads |
| `backend/app/services/transparency.py` | append in the caller's transaction, receipts, export, **server verification** |
| `backend/alembic/versions/0018_…`, `0019_…` | private salts; ledger table, append-only triggers, deterministic backfill (frozen protocol v1 copy), audit-preserving downgrade |
| `GET /api/v1/transparency/*` | head, entries, lookup, verify, export ([api.md](api.md#transparency-ledger)) |
| `tools/ledger_verify.py` | **offline** verifier, Python standard library only |
| `frontend/src/verify/` | `/verify` page, **browser** verifier (Web Crypto), decision receipt |
| `tools/ledger_tamper_demo.py` | the two tamper demonstrations on a throwaway database |
| `docs/transparency-ledger-vectors.json` | test vectors every implementation must reproduce |

Architecture decision: [ADR 0008](adr/0008-transparency-ledger.md).

## 1. What is recorded

| Event | Subject | When it is written | Backfilled |
|---|---|---|---|
| `ledger.genesis` | `ledger:aqyl-kezek` | migration 0019 | always, entry 1 |
| `publication.published` | `publication:<kind>:<publication_id>` | a new snapshot of a publication is inserted | yes, at `published_at` |
| `publication.activated` | same | a snapshot becomes the active one | **no** |
| `publication.deactivated` | same | the active snapshot is replaced | **no** |
| `decision.recorded` | `specialist_decision:<id>` or `hospital_decision:<id>` | `POST /specialist-decisions`, `POST /decisions` | yes, at `created_at` |

Publication kinds — all six first-class publications of the Control Tower: `model_assurance`,
`operational_intelligence`, `review_evidence`, `waiting_list`, `referral_estimates`, `verification_worklist`. Every
publish path (the `make *-publish` targets and `app.cli load-seed`) goes through `app/services/<kind>.publish`, which
appends in its own transaction. A publication entry states the snapshot's lineage only — publication id, identity and
bundle hashes, contract/schema versions, source commit, publish time — never a row of it: no referral id, no
estimate, no worklist rank. The verification worklist stays what its v2 contract says it is, an administrative list
of formal-queue records to check, decided by a specialist; the ledger records that it was published and which
snapshot was current, not a classification of any referral. An idempotent
republish of the already active snapshot writes nothing; republishing an older one writes `deactivated` for the
current one and `activated` for it.

The database stores `published_at` for every snapshot but keeps no history of activations: `is_active` is
overwritten. So activations and deactivations are written only from now on, at the moment they happen, and never
reconstructed. A specialist decision's payload links the decision to its evidence: the identity of the operational
publication active when it was written (the column `publication_identity_sha256` the server sets) and the ledger
number of that publication's own `publication.published` entry.

## 2. Entry format and hash

```
seq · created_at · event_type · subject · payload · prev_hash · entry_hash
entry_hash = SHA-256( canonical_json({created_at, event_type, payload, prev_hash, seq, subject}) )
```

- `seq` — 1, 2, 3, … without gaps; `prev_hash` of entry *n* is `entry_hash` of entry *n−1*.
- `created_at` — the event time from the source row (`published_at`, `created_at`), in one canonical form
  `YYYY-MM-DDTHH:MM:SS.ffffffZ`. Order is `seq`, not time: concurrent writers can commit in a different order than
  their rows' timestamps.
- **Genesis** (entry 1): subject `ledger:aqyl-kezek`, payload
  `{canonicalization: hqai-canonical-json-v1, commitment_scheme: sha256-salted-v1, hash_algorithm: sha256, protocol:
  aqyl-kezek-transparency-ledger, protocol_version: 1}`, `prev_hash` = 64 zeros, and `created_at` =
  `2026-09-28T00:00:00.000000Z` — **a protocol constant** (the day v1 was defined), not the migration's clock. Every
  database therefore starts with the same genesis, `e7be5330076067f7dd9a0e83868fabb9821fce2238689f525483589724b0eb50`,
  and a downgrade/upgrade reproduces it.

Payload builders live in `app/domain/transparency/events.py` and are shared by the live write path and the server
verifier; migration 0019 carries its own frozen copy for the backfill (§9). They are frozen for protocol v1: changing
what an event states means a new event type or protocol version.

## 3. Canonical JSON (`hqai-canonical-json-v1`)

The bytes are hashed, so the Python verifiers and the browser must produce identical bytes. None of them uses its
runtime's JSON serializer for hashing; each implements this contract, and all three are tested against the same
vectors (`docs/transparency-ledger-vectors.json`: 20 valid values with their canonical text and SHA-256, 21 invalid
inputs with the expected error code, 8 non-canonical spellings, commitments, and a golden 6-entry chain — genesis, three publications including
`referral_estimates` and `verification_worklist`, a hospital and a specialist decision — derived from its
`chain_source` rows by the application's own builders, which a test re-checks).

- **Values:** `null`, `true`, `false`, integers in [−(2⁵³−1), 2⁵³−1], strings, arrays, objects. **No floats**, not
  even integral ones such as `1.0` (a float has no spelling all runtimes agree on); no NaN/Infinity.
- **Object keys** match `[a-z][a-z0-9_]{0,63}`: ASCII only, so code-point, UTF-16 and byte order are the same order.
  Keys are sorted ascending and unique (a duplicate key in input is rejected, not "last wins").
- **Strings:** Unicode scalar values as UTF-8; lone surrogates and U+0000 are rejected (PostgreSQL JSONB cannot
  store U+0000). `"` → `\"`, `\` → `\\`, U+0008/0009/000A/000C/000D → `\b \t \n \f \r`, any other code point below
  U+0020 → `\u00xx` (lowercase hex); everything else is written as itself — no escaping of `/`, of non-ASCII (Russian,
  Kazakh, astral characters), of U+2028/U+2029 or of U+007F.
- **Layout:** no whitespace; arrays keep their order; nesting depth ≤ 32.
- **Timestamps** are strings in the one form above. **Text is never normalised**: `null` ≠ `""`, trailing spaces and
  Unicode normalisation forms (`é` vs `e` + U+0301) are kept and hashed as given.

The export is one canonical entry per line; the verifiers re-encode every parsed line and reject a line whose bytes
differ (`NONCANONICAL_ENCODING`), so an export is checked byte for byte, not only value for value.

## 4. Privacy: salted commitments

A public entry never copies free text, a name, or an identifier the client chose. For a specialist decision these
are `comment`, `actor`, `api_key_label`, `idempotency_key`, `subject_id` (a signal id or a referral id — it can
point at one patient's case) and `run_id`; for a hospital decision `comment`, `actor`, `api_key_label`,
`idempotency_key` and `recommendation_id`. The payload carries, per field,

```
commitment = SHA-256( canonical_json({field, salt, scheme: "sha256-salted-v1", subject, value}) )
```

- `salt` — 32 random bytes from the OS CSPRNG (`secrets.token_hex(32)`), one per subject, stored in
  `transparency_commitment_salt`, **never** returned by an endpoint or an export. Without it, guessing a short
  comment against its commitment is infeasible; with a predictable salt (id, timestamp) it would be a dictionary
  lookup — which is why salts are random, not derived.
- `value` is the stored value exactly: `null`, `""` and `"text"` give three different commitments. (The API strips
  surrounding whitespace from decision fields before storing them; that is the business layer's rule and happens
  before anything is committed.)
- The salt table is append-only (same triggers as the ledger). The API role may read it — the server verifier needs
  it — but no response ever contains it.
- What stays public is what public verification needs and nothing that identifies a person or a case: the action,
  institution codes (region, hospital, profile — public reference codes of organisations), the publication origin,
  the simulation day, the subject *kind* (`alert` / `patient`), server-assigned decision and snapshot ids, and
  publication identities and hashes.

Field-by-field review of every public payload (enforced by `test_public_payloads_carry_only_reviewed_keys`, which
fails on any new key until it is reviewed):

| Event | Public keys | Committed (salted SHA-256 only) | Never in the ledger |
|---|---|---|---|
| `ledger.genesis` | protocol constants | — | — |
| `publication.published` | `publication_kind`, `publication_id`, `snapshot_id`, `identity_sha256`, `bundle_sha256`, `contract_version`, `schema_version`, `source_code_commit`, `published_at` | — | any row of the publication (referral ids, estimates, worklist items, areas), source lineage JSON |
| `publication.activated` / `deactivated` | `publication_kind`, `publication_id`, `snapshot_id`, `identity_sha256` | — | same |
| `decision.recorded` (specialist) | `action`, `decision_id`, `decision_kind`, `subject_kind`, `origin`, `sim_day`, `region_code`, `org_code`, `profile_code`, `evidence` (operational publication identity + its ledger seq) | `subject_id`, `run_id`, `comment`, `actor`, `api_key_label`, `idempotency_key` | salts |
| `decision.recorded` (hospital) | `action`, `decision_id`, `decision_kind`, `region_code`, `org_code`, `profile_code`, `alternative_org_code` | `recommendation_id`, `comment`, `actor`, `api_key_label`, `idempotency_key` | salts |

The same public fields are all that `/transparency/*`, the export, the receipt and the `/verify` page show: the page
renders the stored payload, so it cannot show more. Residual risk, stated plainly: a patient decision's hospital,
profile, day and action are public; with outside knowledge of who was referred where on that day this is a
quasi-identifier for small hospitals. The ledger carries no patient attribute, and every entry is behind an API key
(viewer role), like the rest of the API.

## 5. Same transaction, append-only

The decision (or publication) row, its salt and its ledger entry are written in **one database transaction**. The
ledger functions never commit; the business service does, so either all of it is stored or none of it. There is no
asynchronous or best-effort audit write. If a publish or a decision fails, its entry disappears with it — a test
rolls a decision back after appending and checks the ledger is unchanged.

Idempotency: a decision retried with the same `idempotency_key` returns the stored row with its **original receipt**
(`receipt.ledger_seq`, `receipt.entry_hash`) and appends nothing. The receipt is found through the ledger itself: a
partial unique index allows one `decision.recorded` per subject, and the subject names the decision. Two concurrent
first submissions of one key: one wins; the other's unique violation rolls back its row *and* its entry, and it
returns the winner's receipt.

Enforcement in PostgreSQL (migrations 0018/0019), not only in application code:

- `BEFORE UPDATE OR DELETE … FOR EACH ROW` and `BEFORE TRUNCATE … FOR EACH STATEMENT` triggers on the ledger and on
  the salt table raise `insufficient_privilege` (a row trigger does not fire on `TRUNCATE`, hence the second one);
- `seq` primary key; `entry_hash` unique; **`prev_hash` unique** — a second child of one entry, i.e. a fork, cannot be
  inserted even by code that skipped the lock;
- the restricted API role (`APP_DB_USER`, [security.md](security.md) §5) gets `SELECT, INSERT` on both tables and
  nothing else; it can neither `UPDATE`, `DELETE`, `TRUNCATE`, `DROP` nor disable the triggers (only the owner
  can) — `test_the_api_role_may_only_read_and_append` checks each of these as that role.

## 6. Concurrent appends

`append()` runs inside the caller's transaction:

1. `pg_advisory_xact_lock(<key "hqaiTLv1">)` — a transaction-scoped lock, released only by that transaction's
   `COMMIT`/`ROLLBACK`;
2. read the committed head (READ COMMITTED: the statement after the lock sees the last committed entry);
3. `seq = head.seq + 1`, canonical bytes, SHA-256;
4. insert, flush — no commit.

Appends are serialized for the few milliseconds between the lock and the commit; nothing else waits. Publishing
takes the lock only after its bulk inserts, so a large publication does not block decisions while it loads. A
Python lock would not help: requests run in several processes. Test: 20 threads, each with its own connection,
released together by a barrier, record 20 decisions → 20 contiguous entries, 20 distinct parents, chain and server
verification OK. The isolation level must stay READ COMMITTED for this; under a snapshot taken before the lock the
unique constraints make the append fail, never fork.

## 7. Three verifications

**Offline** — `tools/ledger_verify.py` (standard library only) and **in the browser** — `/verify`, Web Crypto:
both take the public export and check canonical encoding, the protocol genesis, contiguous `seq`, every `prev_hash`
link and every recomputed `entry_hash`, plus an optional **trusted head** `(seq, entry_hash)` recorded earlier that
the chain must still contain. The browser never uses the server's verdict; it downloads the export, re-hashes it and
remembers the head it verified in `localStorage`, so on the next visit a rewritten history is visible even if every
later hash was recomputed. Without HTTPS `crypto.subtle` does not exist; a compact SHA-256 in the page (tested
against Web Crypto) takes over.

These prove: *the export is one unbroken chain from the protocol genesis* (and contains the trusted head). They
**cannot** prove that the database rows still match their commitments — the export deliberately has no salts and no
rows. Change a decision's comment directly in the database, and the public chain still verifies.

**Server** — `GET /transparency/verify` has the database and the salts. After the chain checks it rebuilds every
covered payload from the current row and compares:

| Reason | Meaning |
|---|---|
| `COMMITMENT_MISMATCH` | a committed private field (comment, actor, …) now has a different value |
| `SOURCE_FIELD_MISMATCH` | a public field (action, codes, origin, time, evidence link) differs |
| `SOURCE_ROW_MISSING` | the decision row or publication snapshot of an entry is gone |
| `UNCOVERED_SOURCE_ROW` | a row exists with no entry — inserted around the application |
| `PUBLICATION_MISMATCH` | a snapshot's identity, hashes, versions or time differ from its entry |
| `ACTIVE_STATE_MISMATCH` | the active publication differs from the last recorded activation |
| `SALT_MISSING`, `DUPLICATE_SUBJECT_EVENT`, `UNKNOWN_EVENT_TYPE` | integrity of the ledger's own bookkeeping |

Chain reasons (shared by all three verifiers): `EMPTY_LEDGER`, `MALFORMED_ENTRY`, `NONCANONICAL_VALUE`,
`NONCANONICAL_ENCODING`, `GENESIS_INVALID`, `DUPLICATE_SEQ`, `SEQUENCE_GAP`, `SEQUENCE_ORDER`, `PREV_HASH_MISMATCH`,
`ENTRY_HASH_MISMATCH`, `TRUSTED_HEAD_MISSING`, `TRUSTED_HEAD_MISMATCH`. The response reports the first problem by
seq (`failure_seq`, `reason_code`, `subject`), `verified_through_seq`, and up to 20 issues whose details name
fields, never values.

## 8. Threat model

A hash chain is **tamper-evident relative to a head someone trusted before**, not tamper-proof.

It detects:

- accidental or ordinary unauthorized `UPDATE`/`DELETE`/`TRUNCATE` of the ledger — refused by the database;
- an edited, deleted, inserted, duplicated or reordered entry in an export or a copy — offline and browser verifiers,
  at the exact seq;
- a partial rewrite that recomputes hashes from some entry on — against any trusted head at or after that entry
  (a browser that visited before, an auditor's recorded `seq:hash`, the receipt a specialist kept);
- a decision or publication changed, deleted or added directly in its table — server verifier, with the entry and
  subject;
- an attempt to fork the chain — refused by the unique `prev_hash`.

It does **not** protect against:

- a PostgreSQL superuser, the schema owner or anyone controlling the host: they can disable triggers, rewrite the
  whole ledger and recompute every hash. That rewrite is detectable **only** by comparison with a head recorded
  outside their control — which is why receipts, the browser's remembered head and `--trusted-head` exist;
- disclosure of the salts: whoever has them and the export can test guesses of short comments; they must be
  protected like the database itself (they are in it, in a table no endpoint returns);
- a wrong forecast or a bad decision: the ledger shows what was known and decided, not whether it was right;
- anything outside the covered tables (e.g. marts rebuilt by pipelines, `access_log`).

**Trust anchors in this implementation:** the genesis constant (in every verifier), the receipt returned with a
decision, the head remembered by a browser, and a `seq:hash` an operator or auditor stores elsewhere
(`make ledger-verify HEAD=seq:hash`). There is **no signature**: `cryptography`/Ed25519 is not a backend dependency,
and adding one only for this was out of scope. A deployment that needs non-repudiation can sign
`{covered_seq, covered_entry_hash, issued_at, key_id}` of a *prior* head with an Ed25519 key held outside the
database (HSM/KMS) and append that signature as its own entry — the signed head is never the entry that carries the
signature. Until then, publish heads to a place the database owner does not control.

**How the layers relate operationally:**

| Layer | Stops / detects | Blind to |
|---|---|---|
| Append-only triggers + API role with `SELECT, INSERT` | the application, the API role and ordinary operators rewriting or deleting history | the schema owner / superuser, who can disable triggers |
| Public chain verification (offline, browser) | any edit, gap, reorder or fork in an export or copy | a complete rewrite with recomputed hashes, unless a trusted head is given |
| Trusted heads (receipts, browser memory, `--trusted-head`, archived `/transparency/head`) | a complete rewrite of everything up to that head | entries after the newest head held outside |
| Server covered-row verification | business rows changed, deleted or inserted around the application; commitments that no longer match | a consistent rewrite of rows *and* ledger by someone with the salts and owner rights |
| Backups / disaster recovery | loss of the database | a backup restored from before an entry loses that entry: restore is itself a rewrite of recent history, so the ledger head is archived before any restore (§10) |

So: the database refuses routine tampering; the chain makes the rest detectable against a head held elsewhere;
the server check ties the chain to the business rows; backups keep it from being lost, and a restore is treated as
an explicit, documented event, never a silent rollback.

## 9. Migrations, the deterministic backfill and replay safety

The ledger sits on top of the current head of `main`: **0017** (verification worklist) → **0018** → **0019**. One
Alembic head.

- **0018** creates `transparency_commitment_salt` and gives every existing decision a salt, once, from the CSPRNG;
  append-only triggers; grants for the API role.
- **0019** creates `transparency_ledger` and backfills it from the durable rows: genesis, then one
  `publication.published` per snapshot and one `decision.recorded` per decision, in **one global order**
  `(event time in UTC, source rank, id)` with ranks model assurance 1, operational intelligence 2, review evidence 3,
  waiting list 4, referral estimates 5, verification worklist 6, hospital decision 7, specialist decision 8
  (publications before decisions at the same instant; a decision can only refer to an earlier publication).
  Timestamps come from the rows; nothing is invented — activations and deactivations are not stored, so none are
  backfilled.

Same rows + same salts → same bytes. Downgrading only 0019 keeps the salts; upgrading again rebuilds a
byte-identical ledger — tested on a throwaway database with all six publication kinds and both decision tables
(`test_backfill_is_deterministic_ordered_and_invents_nothing`).

**Replay invariant.** A migration runs again on every clean database for the life of the project, so what it writes
must not depend on application code that keeps evolving. 0018 and 0019 import nothing from `app/` (a test parses
them and fails on any `app` import). 0019 carries a **frozen copy of protocol v1** — canonical JSON, genesis,
commitment scheme, payload builders, global order — and `backend/tests/test_transparency_migration.py` holds the two
copies together: the application's builders must agree with the frozen ones byte for byte, the frozen canonical
JSON must reproduce the shared vectors, and the frozen backfill of a fixed source must keep producing a pinned golden
head. If the application's builders ever change, that test fails: the change is then either reverted or made a new
event type / protocol version with its own migration — never an edit of 0019.

All live source timestamps are server-side `now()` and never NULL, so no fallback time was needed.

## 10. Audit-preserving downgrade and rollback

The ledger and the salts are audit evidence. A generic rollback — `alembic downgrade <older revision>`, which is what
an automatic, migration-aware deployment rollback runs — must never destroy it silently. So the migrations
themselves refuse, whoever calls them:

- **0019 downgrade** drops the ledger only when it is exactly what upgrading again would rebuild (genesis plus the
  backfill of the current rows, compared entry by entry). Once anything was written live — an activation, a
  deactivation, a publication or decision appended in an order the backfill would not reproduce — it refuses.
- **0018 downgrade** refuses while the salt table holds any salt: salts are random, so dropping them makes every
  commitment made with them permanently unverifiable.

The refusal is an ordinary migration error (exit code 1, nothing changed — PostgreSQL rolls the transaction back)
that prints the recovery procedure. It is lifted only by an explicit Alembic argument,
`alembic -x transparency_audit=discard downgrade <revision>` — not an environment variable, so no deployment script
and no `DEPLOY_ALLOW_*` switch can pass it on the operator's behalf. Tests:
`test_downgrade_refuses_to_destroy_live_ledger_history_and_salts` (a live decision and activation; downgrades to
0017, 0018 and base all refuse and the export is byte-identical afterwards; with the explicit argument the ledger step
goes, and the salts step still refuses on its own) and `test_a_ledger_with_nothing_to_lose_round_trips_without_the_override`.

Operator procedure when a release that ran 0018/0019 must be abandoned:

1. **Prefer rolling forward**: fix and deploy, or deploy an older *application* commit that already contains
   0018/0019 — the schema stays, nothing is lost. (The backend runs `alembic upgrade head` on start, so an
   application commit older than 0019 cannot start against this schema; that is by design.)
2. If an older schema is truly required, **archive the evidence first**: `GET /api/v1/transparency/export` and
   `GET /api/v1/transparency/head` to storage outside the server, plus a fresh `make backup`.
3. Then **restore the verified backup taken before the upgrade** (`make restore FILE=backups/…`). Everything written
   since that backup survives only in the archive from step 2; record the restore and the archived head as an
   incident, and re-verify the restored ledger against the head it should still contain.
4. The `-x transparency_audit=discard` downgrade exists for development databases and for an operator who has done
   step 2 and accepts the loss in writing; it is never automatic.

Deployment tooling: [`tools/deploy.sh rollback`](../tools/deploy.sh) does not rely on reaching this refusal. Both
migrations carry `AUDIT_SENSITIVE = True` (`test_audit_migrations_are_marked_for_the_deploy_rollback` holds exactly
these two to it). The script refuses a rollback to a commit without them before it backs up, downgrades, checks out
or restarts anything, and prints choices 1–3 above. The one exception is a database that never reached them. No
`DEPLOY_ALLOW_*` variable affects this, and the script never passes `-x transparency_audit=discard`
([deploy-shared-server.md §10.1](deploy-shared-server.md#101-rollback-across-the-transparency-ledger-audit-sensitive-migrations);
tests in `tools/deploy_test.sh`).

## 11. Performance and limits

Measured on a development container (PostgreSQL 16, one CPU share), not a production SLA:

| | |
|---|---|
| decision write incl. salt + ledger append | 5.6 ms per decision (2 000 sequential, new session each) |
| ledger of 2 001 entries: server verification | 0.62 s (loads every covered row once) |
| export | 2.2 MB, 0.24 s |
| `tools/ledger_verify.py` on it | 0.44 s |
| demo database from `seed/` | 13 entries: genesis + 6 publications × (published, activated); reloading the seed adds none |

Head and recent entries are primary-key lookups; a decision never scans the chain.

Abuse and resource bounds of the endpoints (all require an API key, viewer role, like every read endpoint):

- `entries` pages are at most 500 (`limit`), `event_type` at most 64 characters; `lookup` takes exactly one of a hex
  hash prefix of 8–64 characters or a subject of at most 256 characters and returns at most 50 entries; `seq` must be
  ≥ 1. Invalid input is a 422 with a plain message — no SQL, table or path in any error.
- Server verification and the export read the whole ledger (and verification every covered row and salt), so their
  cost grows with the ledger. **Only one of them runs at a time** across all API workers: each takes the
  transaction-scoped advisory lock `"hqaiTLrd"`; a concurrent request (the `/verify` page asks for both at once) waits
  for it up to 15 s (`lock_timeout`) and then gets `503` with `Retry-After: 5` instead of a second full read. A
  waiting request holds one pooled database connection, so a flood of them ends in the pool's own `503`, never in
  parallel full reads. The lock is separate from the append lock, so decisions are never blocked by a verification.

Residual limits, stated honestly: the export is assembled in memory for the one request allowed at a time (about
1 KB per entry); verification holds every covered decision row in memory while it runs. Beyond a few hundred
thousand entries both want streaming and incremental checkpoints. There is no per-client rate limit in the API
itself; the UI's nginx proxy limits each client address to 100 API requests per second
(`frontend/nginx.conf.template`), which does not stop one key from repeating a full read every few seconds.

Known limits: no signed checkpoints (§8); `access_log` and the serving marts are not covered; the offline
verifier's `--url` sends the key only as a header from `HQAI_API_KEY`; the browser's remembered head is per browser.

## 12. Tamper demo (30 seconds)

```bash
make ledger-demo           # throwaway database hqai_tamper_demo_<random>; dropped at the end
make ledger-demo KEEP=1    # keep it and look at BROKEN in /verify (the command prints how)
```

It never touches the database in `.env`. It records three decisions the normal way (receipts printed), shows the
ledger refusing an `UPDATE`, then:

- **A — covered source row:** rewrites one decision's comment with plain SQL. The public chain still verifies
  (`VERIFIED · entries: 4`); the server verification reports `BROKEN · entry №3 · COMMITMENT_MISMATCH ·
  specialist_decision:2`.
- **B — exported copy:** edits one old entry of the exported JSONL (`decline` → `accept`); `tools/ledger_verify.py`
  answers `BROKEN · seq: 2 · reason: ENTRY_HASH_MISMATCH`, exit code 1.

## 13. Commands

```bash
make ledger-verify                          # the running API's export (key from DEMO_API_KEY, as a header)
make ledger-verify FILE=ledger.jsonl        # a downloaded export
make ledger-verify FILE=ledger.jsonl HEAD=1427:83ab…12f9   # must still contain that head
python3 tools/ledger_verify.py --url http://localhost:8000 --expect-head <hash>
make ledger-demo [KEEP=1]
curl -H "X-API-Key: $KEY" localhost:8000/api/v1/transparency/verify
```

Tests: `backend/tests/test_transparency.py` (throwaway databases: triggers, API-role privileges, rollback, 20
concurrent appends, retries, fork refusal, backfill determinism and order across all six kinds, audit-preserving
downgrade, privacy, both tamper demos, vectors, offline verifier), `test_transparency_migration.py` (replay safety),
`test_transparency_api.py` (auth, bounds, single full read), `test_transparency_publications.py`,
`test_seed_smoke.py` (every seed publication chained, verification OK), `frontend/src/verify/canonical.test.ts`,
`frontend/src/test/verify.test.tsx`. Tests that publish or decide against the shared database run inside a
rolled-back transaction (`ledger_isolation` in `backend/tests/conftest.py`), because an append-only ledger cannot
be cleaned up afterwards.
