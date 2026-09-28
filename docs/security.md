# Security — hospital-queue-ai

What the prototype protects today, what it does not, and what a production deployment in a health department must
add. The access control is minimal but real: it is enforced on every API route and tested; it is **not** a substitute
for the organisation's identity and security infrastructure.

## 1. Data handled

- **Source**: MoH open data (referrals, waiting list, admission refusals, ERSB treated cases). The published datasets
  carry no names or national IDs. They still contain per-referral records: `hospitalization_code`, registration and
  hospitalization dates, ICD-10 code, patient region and city/village type. Combined with other sources such records
  could narrow down individuals, so the database is treated as **sensitive**, even though each field is public.
- **Derived**: aggregates, model predictions, SHAP explanations, recommendations — no new personal data.
- **Produced by the system**: `decision_log` (who decided what: free-text `actor`, comment, the API key label),
  `api_keys` (hashes), `access_log` (who called which endpoint with which query string, when, from which address,
  under which request id). No request body is ever stored.
- **The API never returns** patient identifiers beyond `hospitalization_code` (docs/api.md, referrals endpoint).

## 2. What is protected

| control | how | where |
|---|---|---|
| Authentication | every endpoint except `GET /health` and `GET /api/v1/health` requires `X-API-Key`; missing / unknown / revoked key → `401` | `backend/app/core/security.py` |
| Authorisation (roles) | `viewer` — every `GET` (incl. exports); `specialist` — plus `POST /decisions`; `admin` — plus `/admin/keys*`, `/admin/access-log`; lower role → `403` | same; route declarations in `backend/app/api/routes.py` |
| Enforcement check | `make audit` fails if any FastAPI route other than the health checks has no auth dependency; CI runs the role-matrix tests | `tools/audit.py` (`api-auth`), `backend/tests/test_security_ops.py` |
| Key storage | keys are 256-bit random tokens (`hqai_` + 43 URL-safe characters); only SHA-256 is stored, plus a 6-character prefix for recognition; the key is shown once (CLI or `POST /admin/keys`) | `api_keys`; `make create-key` |
| Key lifecycle | create (CLI, admin API), list (never shows key or hash), revoke (`revoked_at`; effective on the next request) | `app.cli`, `/admin/keys` |
| Audit trail | one `access_log` row per `/api` request — timestamp, key label, role, method, path, truncated query string, status, latency, client address, `X-Forwarded-For`, request id; `401`s are logged without a label, `OPTIONS` preflights are not logged at all; indexed by `(key_label, ts)` and `(status, ts)`, the two filters `/admin/access-log` offers; decisions store `api_key_label` next to the free-text `actor` | `backend/app/core/access_log.py`, `decision_log` |
| Client address in the audit trail | `client_ip` is the first `X-Forwarded-For` entry only when the TCP peer is in `TRUSTED_PROXY_CIDRS` (default: the docker bridge, where the only peer is the UI's nginx), and that nginx **replaces** the header with the address the request actually came from (`proxy_set_header X-Forwarded-For $remote_addr`) rather than appending to whatever the caller sent — without that, a caller could put any address ahead of its own and that is what would be recorded. A request reaching the API directly is recorded with the address it connected from. The header itself is kept verbatim in `forwarded_for` | `backend/app/core/access_log.py`, `.env.example` |
| Request ids | every response carries `X-Request-ID` — the caller's own value when it fits `[A-Za-z0-9._:-]{1,128}`, otherwise a generated one. The same id is on every log line of that call and in its `access_log` row, so a question about one request can be answered from the container log and the database together | `backend/app/core/logging.py` |
| Application log | one JSON object per line on stdout (time, level, logger, message, request id, traceback), level from `LOG_LEVEL`; uvicorn's own loggers use the same handler. Standard library only, no new dependency | `backend/app/core/logging.py` |
| Database role for the API | with `APP_DB_USER` / `APP_DB_PASSWORD` in the environment of the PostgreSQL container, `db/init.sql` creates a login role that is **not** a superuser and has no DDL rights: `SELECT` on the read tables, `INSERT` on `decision_log` / `specialist_decision` / `access_log`, `UPDATE` on `api_keys`, nothing on `alembic_version`. It cannot `DROP`, `DELETE` or `TRUNCATE` anything. Migrations, the seed loader and the ML pipelines keep the owner role; empty values (the demo default) mean the API also uses the owner role | `db/init.sql`, `backend/app/core/config.py`, `backend/app/db/session.py` |
| Bounded request cost | the API pool keeps `DB_POOL_SIZE` connections plus `DB_MAX_OVERFLOW` and waits at most `DB_POOL_TIMEOUT` seconds for a free one, so a burst fails fast instead of hanging; every request connection carries `statement_timeout` (`DB_STATEMENT_TIMEOUT_MS`, 15 s); one request opens one database session (the audit row is committed by a background writer, not in the request path) | `backend/app/db/session.py`, `backend/app/core/access_log.py` |
| Request rate at the proxy | `limit_req` per client address: 20 r/s with a burst of 40 for `/api/`, and 1 r/s with a burst of 3 for `POST /api/v1/assistant`, which waits on an external provider and costs provider tokens; over the limit the proxy answers `429`. Clients behind one NAT share a bucket | `frontend/nginx.conf.template` |
| No extension, no custom image | the schema needs no PostgreSQL extension and `db/init.sql` creates none: a DBA-managed PostgreSQL 14+ from an internal repository is enough | `db/init.sql` |
| Integrity of decisions | validation of codes and hospital ↔ region ↔ alternative; client-supplied `idempotency_key` with a unique index — retries do not duplicate, reuse with other content → `409` | `backend/app/services/activity.py` |
| Least exposure in the UI image | nginx serves static files and proxies only `/api/`; the backend container runs as a non-root user | `frontend/nginx.conf.template`, `backend/Dockerfile` |
| Host ports | Postgres and the API bind to `127.0.0.1` only; the UI port binds to `UI_BIND` (default every interface, so a second device on the demo network can open it; `UI_BIND=127.0.0.1` in `.env` closes that) | `docker-compose.yml`, `.env.example` |
| Browser hardening | every UI response carries `Content-Security-Policy` (scripts and connections only from the UI origin, no plugins, no framing), `X-Frame-Options: DENY`, `X-Content-Type-Options: nosniff`, `Referrer-Policy: same-origin`; `server_tokens off`; the production bundle ships without source maps | `frontend/nginx.conf.template`, `frontend/vite.config.ts` |
| Generated secrets | `make env` (run by `make demo`) fills `POSTGRES_PASSWORD` and `DEMO_API_KEY` from `/dev/urandom` and warns when an existing `.env` has an empty demo key | `Makefile` |
| Credentials stay server-side | the demo key is **not** in the JavaScript bundle: nginx (docker) and the Vite dev server (`make web-dev`) add `X-API-Key` to proxied `/api` requests from their own environment; a request that already carries a key keeps it, so an operator can use a personal viewer/admin key | `frontend/nginx.conf.template`, `frontend/vite.config.ts` |
| No secret in the built bundle | `make audit` (`web-bundle`) scans `frontend/dist` after the production build and fails on any key-like string | `tools/audit.py` |
| Secrets in the repository | `make audit` scans every file that would be committed for keys, passwords, tokens and `.env` files; `.env` and `backups/` are gitignored | `tools/audit.py` (`secrets`) |
| Backups | `make backup` writes a `pg_dump` to `backups/` (gitignored); `make restore` asks for confirmation | `Makefile` |

## 3. What is NOT protected (be aware)

1. **Reaching the UI port is enough to act as a specialist.** The key itself is no longer exposed (it lives in the
   proxy's environment, not in the bundle), but the proxy adds it to every `/api` request it forwards, so anyone who
   can open http://localhost:3000 — or send a request to it — reads all data and records decisions under the demo
   key's label, without logging in. There is no per-person session: this is acceptable only on a single demo machine
   or a closed network. A real deployment replaces the injection with an SSO session (§4).
2. **API keys identify a client, not a person.** There is no login, no SSO, no personal accounts. `actor` in a
   decision is whatever the person typed. Several people sharing a key are indistinguishable in the audit trail.
3. **No transport encryption.** The docker stack serves plain HTTP. The UI port (`:3000`) is the only one reachable
   from other machines; the API (`:8000`) and Postgres (`:5432`) are bound to `127.0.0.1` on the host. Keys still
   travel in clear text to the UI port; anyone on the network path can capture a request. `UI_BIND=127.0.0.1` keeps
   even the UI local.
4. **The backend port bypasses nginx.** `127.0.0.1:8000` is published for development on the host itself (`/docs`,
   `make test` against a running server); a request that carries its own key skips the proxy, its rate limits and its
   headers. Such a request is recorded with the address it connected from — `X-Forwarded-For` is believed only from
   `TRUSTED_PROXY_CIDRS` (§2) — so `client_ip` is correct but coarse: everything arriving through the UI container
   shows that container's forwarded address, and a direct caller on the host shows as the host.
5. **Secrets in `.env`.** Postgres password and the demo key live in a plain file on the host and in container
   environment variables; `make env` generates random values, but there is no secret manager and no rotation.
   The `Content-Security-Policy` allows inline `style` attributes (`style-src 'unsafe-inline'`) because the chart and
   map libraries set them; scripts are restricted to the hashed bundle from the UI origin, so an injected inline
   script would not run.
6. **No lockout or brute-force protection** on the key check (keys are long random values, so guessing is
   impractical). The proxy throttles by request rate per address (§2), not by failed attempts, and only for traffic
   that goes through it: a caller on the published API port is not throttled at all.
7. **The access log is written by the application into the same database** it audits: an attacker with database
   write access, or an admin, can alter or delete rows. It is not tamper-evident. It is also not guaranteed to be
   complete under a flood: rows queue in memory (2 000) and are committed in batches within a quarter of a second,
   and if the queue overflows the row is dropped with a `WARNING` in the log that says how many — the response is
   never delayed for the audit write.
8. **Retention of the access log is an open decision, not a policy.** Rows are kept indefinitely today. The table
   grows with every poll of the control centre, so a pilot has to choose before it starts: how long rows stay
   online, who approves deletion, and whether they are archived first. Until the data owner decides, the operator's
   own tools apply — a scheduled `DELETE FROM access_log WHERE ts < now() - interval '<N> days'` after a backup, or
   a partitioned table. The same question is open for `decision_log` and `specialist_decision`, which are records of
   human decisions and probably follow the retention period of planning documents rather than a log policy (§4).
9. **OpenAPI docs are open** (`/docs`, `/redoc`, `/openapi.json`) — they reveal the API shape, not data. They can be
   switched off with `DOCS_ENABLED=false`.
10. **The role split is optional and partial.** The demo stack ships without `APP_DB_USER`, so the API, the pipelines
    and the migrations all use the owner role, which in the docker image is a superuser. With the application role
    configured (§2) the request path loses its DDL rights, but the seed loader, the publish commands and the
    migrations still run as the owner, and there is no separate read-only or pipeline role. The role is created by
    `db/init.sql`, which PostgreSQL runs only when the data directory is new: on a database that already exists, the
    DBA applies the same statements once (`CREATE ROLE … NOSUPERUSER`, then the `GRANT`s the file documents).
11. **Exports leave the system**: XLSX/PDF files are not watermarked or logged beyond the access-log row of the
    download request.
12. **Backups are unencrypted** files containing all data, key hashes and the access log.
13. **No dependency or image vulnerability scanning** in CI.

## 4. What a production deployment must add

**Identity and access**
- Replace API keys for people with the organisation's identity provider: SSO via OpenID Connect / SAML against the
  ministry's directory (or the national eGov IDP / digital-signature-based login used in state systems). Map directory
  groups to `viewer / specialist / admin`; record the authenticated person (internal user id — not the ИИН — full name,
  organisation) in `decision_log` instead of free-text `actor`.
- Keep API keys only for service-to-service calls (e.g. integration with the document-management system — ЕСЭДО — or
  a regional reporting system), each with its own label, least role, expiry date and rotation.
- Integrate decisions with document workflow where a decision has legal weight: send the confirmed recommendation to
  ЕСЭДО as a document requiring an electronic signature (ЭЦП) of the responsible official, and store the document id
  and signature status next to the decision. The prototype's decision log is an operational note, not a signed act.
- Remove the compiled-in demo key; the UI obtains a short-lived session token after SSO login.
- Four-eyes principle for admin actions (key creation, role changes) and an admin action log separate from the access
  log.

**Transport and network**
- TLS everywhere: HTTPS termination with certificates from the organisation's CA (HSTS, TLS 1.2+); TLS between the
  proxy, the API and Postgres (`sslmode=verify-full`).
- Publish only the reverse proxy; the API and the database on an internal network; no host ports for Postgres
  (the compose file already binds them to the loopback interface; a production deployment drops the `ports` entries).
- Narrow `TRUSTED_PROXY_CIDRS` (§2) to the real proxy address instead of the whole docker bridge, and pass the same
  address to uvicorn (`--forwarded-allow-ips=<proxy address>`) so the framework agrees with the audit log.
- Tune the proxy's `limit_req` zones (§2) to the expected number of operators, add request size limits, and put a WAF
  in front if the service is reachable beyond the department network.

**Secrets**
- Secret storage (HashiCorp Vault, a cloud KMS / secret manager, or the government cloud's equivalent) for the database
  credentials, the key-hash pepper (add an HMAC secret to the key hash) and TLS keys; no secrets in `.env` files or
  images; rotation schedule and immediate rotation on staff changes.
- Finish the database role split: `APP_DB_USER` (§2) already gives the API a non-superuser role without DDL rights;
  a production deployment adds a separate pipeline role and a migration role, keeps the owner role out of the running
  containers, and gives the backups their own read-only role. No superuser at runtime.

**Audit, retention, monitoring**
- Ship access and admin logs to an append-only store (SIEM / central logging) in real time; make them tamper-evident
  (write-once storage or hash chaining); alert on bursts of `401`/`403`, new admin keys, off-hours exports. The JSON
  lines on stdout and the `X-Request-ID` of every response (§2) are what such a collector needs; nothing ships them
  anywhere today.
- Decide the retention policy left open in §3, with the data owner and the legal requirements, e.g.: access log —
  12 months online, then
  archive or delete; decision log — for the retention period of planning documents; exports — not stored server-side;
  backups — encrypted, 30 days rolling plus monthly archives, with restore tested regularly.
- Personal-data compliance with the Law of the Republic of Kazakhstan "On personal data and their protection" and
  health-information requirements: data-processing registration, data-owner agreement with the MoH, access reviews,
  and a data-protection impact assessment before connecting non-public (identifiable) sources.

**Application and supply chain**
- Encrypt backups and restrict who can run `make restore`; test restores.
- Dependency and container scanning in CI (pip-audit / npm audit / image scanning), pinned base images with regular
  updates, signed images.
- Keep the UI security headers (`Content-Security-Policy`, `frame-ancestors 'none'`, `Referrer-Policy`) that the
  nginx template already sets; add `Strict-Transport-Security` once TLS terminates there; `DOCS_ENABLED=false`.
- Penetration test and threat model review before go-live; incident response contacts and procedure.

**Closed-contour build (no internet on the target network)**
- The two images build offline from a local mirror of the registries they pull from: the PostgreSQL, `python:3.12-slim`
  and `node:22-alpine` / `nginx:1.29-alpine` base images pinned in `docker-compose.yml` and the Dockerfiles (Docker
  Hub) — the database needs no extension, so a vanilla PostgreSQL image or a DBA-managed server both work —, Python
  wheels for `backend/pyproject.toml`
  (PyPI) and the packages pinned in `frontend/package-lock.json` (npm). Point `pip` and `npm` at the mirror through
  build arguments or a `~/.pip/pip.conf` / `.npmrc` copied into the build context, or build the images on a connected
  machine and move them with `docker save` / `docker load`; CI (`docker-images` job) builds both images on every push,
  so the Dockerfiles are known to build.
- `make demo` needs nothing beyond the repository and Docker: the data comes from the committed `seed/`, the models from
  the committed `models/`; no download at run time.
- `VITE_SYNTHETIC=off` in `.env` builds a published-only UI: no synthetic queue or day simulation, only the published
  signals and forecasts (`frontend/src/synthetic/README.md`); use it for any deployment that is not a demo.

## 5. Operating the prototype

```bash
make create-key ROLE=viewer LABEL="Аналитик УОЗ, демо"        # prints the key once
cd backend && ../.venv/bin/python -m app.cli list-keys         # prefixes, roles, revoked
cd backend && ../.venv/bin/python -m app.cli revoke-key --id 3
curl -H "X-API-Key: $KEY" http://localhost:8000/api/v1/me       # check a key
make backup                                                    # backups/hqai_<timestamp>.dump
make restore FILE=backups/hqai_<timestamp>.dump                # asks for "yes"
```

`DEMO_API_KEY` in `.env` (generate: `python3 -c 'import secrets; print("hqai_" + secrets.token_urlsafe(32))'`) is
seeded as a specialist key each time the backend container starts; revoking it in the database wins over seeding
(a revoked demo key is not re-activated). It is passed to the frontend container as an environment variable and
injected by nginx at request time, so changing it needs only a restart (`make up`), not a rebuild, and it never
reaches the browser. It is still readable by anyone who can run `docker inspect` or exec into the container.

`make demo` (through `make env`) creates `.env` from `.env.example` when there is none, filling `POSTGRES_PASSWORD`
and `DEMO_API_KEY` from `/dev/urandom` (the key is `hqai_` + 43 URL-safe characters, as `seed-demo-key` requires).
The values stay in the gitignored `.env` and are never printed; an existing `.env` is kept as it is. The trust model
is the one above: whoever reaches the UI acts as a specialist through the demo key, so `make demo` is for a laptop or
a closed demo network, not for a host on the internet.

### The application database role on a database that already exists

`db/init.sql` runs only when PostgreSQL initialises a new data directory. On an existing database — the usual case in
a DBA-managed environment — the same result is three statements, run once by the owner of the schema, plus
`APP_DB_USER` / `APP_DB_PASSWORD` in the API's environment:

```sql
CREATE ROLE hqai_app LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE PASSWORD '<password>';
GRANT CONNECT ON DATABASE hqai TO hqai_app;
GRANT USAGE ON SCHEMA public TO hqai_app;

GRANT SELECT ON ALL TABLES IN SCHEMA public TO hqai_app;
REVOKE ALL ON TABLE alembic_version FROM hqai_app;
GRANT INSERT ON TABLE access_log, decision_log, specialist_decision TO hqai_app;
-- transparency ledger (migrations 0016/0017 grant these themselves when hqai.app_role is set)
GRANT INSERT ON TABLE transparency_ledger, transparency_commitment_salt TO hqai_app;
GRANT INSERT, UPDATE ON TABLE api_keys TO hqai_app;
GRANT USAGE, SELECT ON SEQUENCE
    access_log_id_seq, decision_log_id_seq, specialist_decision_id_seq, api_keys_id_seq TO hqai_app;

-- so that the next migration's tables are readable without repeating the grant
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO hqai_app;
```

Check it the way the repository does: as `hqai_app`, `SELECT` from a mart and `INSERT` into `access_log` must
succeed, and `DROP TABLE`, `DELETE` and `TRUNCATE` must all be refused.

### Transparency ledger

Decisions and publications are chained in an append-only ledger ([transparency-ledger.md](transparency-ledger.md)).
Its public entries carry no free text: a decision's comment, actor, API-key label and idempotency key appear only as
salted SHA-256 commitments. The salts are in `transparency_commitment_salt`, readable by the API role (the server
verification needs them) and returned by no endpoint; treat them like the rest of the database. Triggers refuse
`UPDATE`, `DELETE` and `TRUNCATE` on both tables for every role, but the schema owner or a superuser can still
disable them: a full rewrite is detectable only against a head recorded outside the database (a receipt, a browser
that visited `/verify` before, `make ledger-verify HEAD=seq:hash`).
