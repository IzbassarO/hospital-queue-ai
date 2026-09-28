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
| `backend/alembic/versions/0016_…`, `0017_…` | private salts; ledger table, append-only triggers, deterministic backfill |
| `GET /api/v1/transparency/*` | head, entries, lookup, verify, export ([api.md](api.md#transparency-ledger)) |
| `tools/ledger_verify.py` | **offline** verifier, Python standard library only |
| `frontend/src/verify/` | `/verify` page, **browser** verifier (Web Crypto), decision receipt |
| `tools/ledger_tamper_demo.py` | the two tamper demonstrations on a throwaway database |
| `docs/transparency-ledger-vectors.json` | test vectors every implementation must reproduce |

Architecture decision: [ADR 0008](adr/0008-transparency-ledger.md).

## 1. What is recorded

| Event | Subject | When it is written | Backfilled |
|---|---|---|---|
| `ledger.genesis` | `ledger:aqyl-kezek` | migration 0017 | always, entry 1 |
| `publication.published` | `publication:<kind>:<publication_id>` | a new snapshot of a publication is inserted | yes, at `published_at` |
| `publication.activated` | same | a snapshot becomes the active one | **no** |
| `publication.deactivated` | same | the active snapshot is replaced | **no** |
| `decision.recorded` | `specialist_decision:<id>` or `hospital_decision:<id>` | `POST /specialist-decisions`, `POST /decisions` | yes, at `created_at` |

Publication kinds: `model_assurance`, `operational_intelligence`, `review_evidence`, `waiting_list` — every
publish path goes through `app/services/<kind>.publish`, which now appends in its own transaction. An idempotent
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

Payload builders live in `app/domain/transparency/events.py` and are shared by the live write path, the backfill
migration and the server verifier. They are frozen for protocol v1: changing what an event states means a new event
type or protocol version.

## 3. Canonical JSON (`hqai-canonical-json-v1`)

The bytes are hashed, so the Python verifiers and the browser must produce identical bytes. None of them uses its
runtime's JSON serializer for hashing; each implements this contract, and all three are tested against the same
vectors (`docs/transparency-ledger-vectors.json`: 20 valid values with their canonical text and SHA-256, 21 invalid
inputs with the expected error code, 8 non-canonical spellings, commitments, and a golden 4-entry chain).

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

A public entry never copies free text a person typed or that names a person. For a decision these are `comment`,
`actor`, `api_key_label` and the client's `idempotency_key`; the payload carries, per field,

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
- Codes, identifiers and dates stay public: action, region/hospital/profile codes, origin, run id, simulation day,
  subject id (a signal id or a synthetic referral id), publication identities.

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

Enforcement in PostgreSQL (migrations 0016/0017), not only in application code:

- `BEFORE UPDATE OR DELETE … FOR EACH ROW` and `BEFORE TRUNCATE … FOR EACH STATEMENT` triggers on the ledger and on
  the salt table raise `insufficient_privilege` (a row trigger does not fire on `TRUNCATE`, hence the second one);
- `seq` primary key; `entry_hash` unique; **`prev_hash` unique** — a second child of one entry, i.e. a fork, cannot be
  inserted even by code that skipped the lock;
- the restricted API role (`APP_DB_USER`, [security.md](security.md) §5) gets `SELECT, INSERT` on both tables and
  nothing else.

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

## 9. Migrations and the deterministic backfill

- **0016** creates `transparency_commitment_salt` and gives every existing decision a salt, once, from the CSPRNG;
  append-only triggers; grants for the API role.
- **0017** creates `transparency_ledger` and backfills it from the durable rows: genesis, then one
  `publication.published` per snapshot and one `decision.recorded` per decision, in **one global order**
  `(event time in UTC, source rank, id)` with ranks model assurance 1, operational intelligence 2, review evidence 3,
  waiting list 4, hospital decision 5, specialist decision 6 (publications before decisions at the same instant; a
  decision can only refer to an earlier publication). Timestamps come from the rows; nothing is invented —
  activations and deactivations are not stored, so none are backfilled.

Same rows + same salts → same bytes. Downgrading only 0017 keeps the salts; upgrading again rebuilds a
byte-identical ledger. Tested on a throwaway database (`test_backfill_is_deterministic_ordered_and_invents_nothing`)
and measured on the database loaded from `seed/`: two downgrade/upgrade cycles gave the same export
(`sha256 28c29a86…1b68`, 7 entries). Entries that exist only because they were written live — activations,
deactivations, the commit order of concurrent appends — are lost if 0017 is downgraded; that is a real loss of
history and why downgrading it in production is not a routine operation.

All live source timestamps are server-side `now()` and never NULL, so no fallback time was needed.

## 10. Tamper demo (30 seconds)

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

## 11. Performance and limits

Measured on a development container (PostgreSQL 16, one CPU share), not a production SLA:

| | |
|---|---|
| decision write incl. salt + ledger append | 7.4 ms per decision (2 000 sequential, new session each) |
| ledger of 2 004 entries: server verification | ~0.8 s (loads every covered row once) |
| export | 1.9 MB, 0.6 s |
| `tools/ledger_verify.py` on it | 0.57 s |
| browser verification (headless Chromium, Web Crypto) | 344 ms |
| demo database from `seed/` | 11 entries (4 publications × published + activated, 2 decisions, genesis) |

Head and recent entries are primary-key lookups; a decision never scans the chain. Server verification and the
export read everything and are meant for on-demand use; the export is assembled in memory per request. Beyond a few
hundred thousand entries both would want streaming and incremental checkpoints — not needed now.

Known limits: no signed checkpoints (§8); `access_log` and the serving marts are not covered; the offline
verifier's `--url` sends the key only as a header from `HQAI_API_KEY`; the browser's remembered head is per browser.

## 12. Commands

```bash
make ledger-verify                          # the running API's export (key from DEMO_API_KEY, as a header)
make ledger-verify FILE=ledger.jsonl        # a downloaded export
make ledger-verify FILE=ledger.jsonl HEAD=1427:83ab…12f9   # must still contain that head
python3 tools/ledger_verify.py --url http://localhost:8000 --expect-head <hash>
make ledger-demo [KEEP=1]
curl -H "X-API-Key: $KEY" localhost:8000/api/v1/transparency/verify
```

Tests: `backend/tests/test_transparency.py` (throwaway databases: triggers, rollback, 20 concurrent appends,
retries, fork refusal, backfill determinism and order, privacy, both tamper demos, vectors, offline verifier),
`test_transparency_api.py`, `test_transparency_publications.py`, `frontend/src/verify/canonical.test.ts`,
`frontend/src/test/verify.test.tsx`. Tests that publish or decide against the shared database run inside a
rolled-back transaction (`ledger_isolation` in `backend/tests/conftest.py`), because an append-only ledger cannot
be cleaned up afterwards.
