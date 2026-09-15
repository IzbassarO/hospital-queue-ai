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
  `api_keys` (hashes), `access_log` (who called which endpoint, when, from which address).
- **The API never returns** patient identifiers beyond `hospitalization_code` (docs/api.md, referrals endpoint).

## 2. What is protected

| control | how | where |
|---|---|---|
| Authentication | every endpoint except `GET /health` and `GET /api/v1/health` requires `X-API-Key`; missing / unknown / revoked key → `401` | `backend/app/core/security.py` |
| Authorisation (roles) | `viewer` — every `GET` (incl. exports); `specialist` — plus `POST /decisions`; `admin` — plus `/admin/keys*`, `/admin/access-log`; lower role → `403` | same; route declarations in `backend/app/api/routes.py` |
| Enforcement check | `make audit` fails if any FastAPI route other than the health checks has no auth dependency; CI runs the role-matrix tests | `tools/audit.py` (`api-auth`), `backend/tests/test_security_ops.py` |
| Key storage | keys are 256-bit random tokens (`hqai_` + 43 URL-safe characters); only SHA-256 is stored, plus a 6-character prefix for recognition; the key is shown once (CLI or `POST /admin/keys`) | `api_keys`; `make create-key` |
| Key lifecycle | create (CLI, admin API), list (never shows key or hash), revoke (`revoked_at`; effective on the next request) | `app.cli`, `/admin/keys` |
| Audit trail | one `access_log` row per `/api` request — timestamp, key label, role, method, path, status, latency, TCP peer, `X-Forwarded-For`; `401`s are logged without a label; decisions store `api_key_label` next to the free-text `actor` | `backend/app/core/access_log.py`, `decision_log` |
| Integrity of decisions | validation of codes and hospital ↔ region ↔ alternative; client-supplied `idempotency_key` with a unique index — retries do not duplicate, reuse with other content → `409` | `backend/app/services/activity.py` |
| Least exposure in the UI image | nginx serves static files and proxies only `/api/`; the backend container runs as a non-root user | `frontend/nginx.conf`, `backend/Dockerfile` |
| Secrets in the repository | `make audit` scans every file that would be committed for keys, passwords, tokens and `.env` files; `.env` and `backups/` are gitignored | `tools/audit.py` (`secrets`) |
| Backups | `make backup` writes a `pg_dump` to `backups/` (gitignored); `make restore` asks for confirmation | `Makefile` |

## 3. What is NOT protected (be aware)

1. **The demo key is public to anyone who opens the UI.** `DEMO_API_KEY` is compiled into the JavaScript bundle so the
   demo works without login; anyone who can load http://localhost:3000 can read it and act as a *specialist* (read
   everything, record decisions). This is acceptable only on a single demo machine or a closed network.
2. **API keys identify a client, not a person.** There is no login, no SSO, no personal accounts. `actor` in a
   decision is whatever the person typed. Several people sharing a key are indistinguishable in the audit trail.
3. **No transport encryption.** The docker stack serves plain HTTP (`:3000` UI, `:8000` API, `:5432` Postgres, all
   published on the host). Keys travel in clear text; anyone on the network path can capture them.
4. **The backend port bypasses nginx.** `:8000` is published for development; `X-Forwarded-For` is recorded but not
   trusted (it can be forged on direct calls), so `client_ip` is only as good as the network setup.
5. **Secrets in `.env`.** Postgres password and the demo key live in a plain file on the host and in container
   environment variables; no secret manager, no rotation.
6. **No rate limiting, lockout or brute-force protection** on the key check (keys are long random values, so guessing
   is impractical, but floods are not throttled).
7. **The access log is written by the application into the same database** it audits: an attacker with database
   write access, or an admin, can alter or delete rows. It is not tamper-evident and has no retention policy.
8. **OpenAPI docs are open** (`/docs`, `/redoc`, `/openapi.json`) — they reveal the API shape, not data. They can be
   switched off with `DOCS_ENABLED=false`.
9. **Database access is not role-separated**: the API, the pipelines and the migrations use one Postgres role with full
   rights on the schema.
10. **Exports leave the system**: XLSX/PDF files are not watermarked or logged beyond the access-log row of the
    download request.
11. **Backups are unencrypted** files containing all data, key hashes and the access log.
12. **No dependency or image vulnerability scanning** in CI.

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
- Publish only the reverse proxy; the API and the database on an internal network; no host ports for Postgres.
- Trust `X-Forwarded-For` only from the known proxy (uvicorn `--forwarded-allow-ips=<proxy address>`).
- Rate limiting and request size limits at the proxy; a WAF if the service is reachable beyond the department network.

**Secrets**
- Secret storage (HashiCorp Vault, a cloud KMS / secret manager, or the government cloud's equivalent) for the database
  credentials, the key-hash pepper (add an HMAC secret to the key hash) and TLS keys; no secrets in `.env` files or
  images; rotation schedule and immediate rotation on staff changes.
- Separate database roles: read-only for the API's GET paths, a writer limited to `decision_log` / `access_log` /
  `api_keys`, a migration role, and a pipeline role; no superuser at runtime.

**Audit, retention, monitoring**
- Ship access and admin logs to an append-only store (SIEM / central logging) in real time; make them tamper-evident
  (write-once storage or hash chaining); alert on bursts of `401`/`403`, new admin keys, off-hours exports.
- Retention policy agreed with the data owner and legal requirements, e.g.: access log — 12 months online, then
  archive or delete; decision log — for the retention period of planning documents; exports — not stored server-side;
  backups — encrypted, 30 days rolling plus monthly archives, with restore tested regularly.
- Personal-data compliance with the Law of the Republic of Kazakhstan "On personal data and their protection" and
  health-information requirements: data-processing registration, data-owner agreement with the MoH, access reviews,
  and a data-protection impact assessment before connecting non-public (identifiable) sources.

**Application and supply chain**
- Encrypt backups and restrict who can run `make restore`; test restores.
- Dependency and container scanning in CI (pip-audit / npm audit / image scanning), pinned base images with regular
  updates, signed images.
- Security headers on the UI (Content-Security-Policy, frame-ancestors, strict referrer policy), `DOCS_ENABLED=false`.
- Penetration test and threat model review before go-live; incident response contacts and procedure.

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
(a revoked demo key is not re-activated). After changing `DEMO_API_KEY`, rebuild the frontend (`make up`), since the
key is compiled into the bundle.
