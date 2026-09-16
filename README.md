# hospital-queue-ai

A data-driven prototype for monitoring and forecasting planned-hospitalization queues and hospital
load in Kazakhstan, built on Ministry of Health open data (GovTech Camp 2026, Case 1). The goal is
to show where referral queues build up, how quickly patients are admitted or refused, and which
hospitals and regions are overloaded relative to their capacity.

## Quickstart

With the database already loaded (the `pgdata` volume holds steps 2–3):

```bash
make up                   # postgres + backend (FastAPI) + frontend (nginx), waits until all are healthy
open http://localhost:3000        # the web UI
open http://localhost:8000/docs   # API (Swagger)
```

The UI ([docs/frontend.md](docs/frontend.md)) has five screens: Обзор, Регион, Карточка стационара (chart, «Почему»,
recommendations with decisions, referrals), Сигналы, О моделях. Demo path: Обзор → г. Астана → профиль «Патологии
беременности» → ZIQ9 → подтвердить рекомендацию → решение в истории → Сигналы.

The API is described in [docs/api.md](docs/api.md): overview, regions, hospital cards with series, forecast and
explanations, referrals, rule-based recommendations, alerts, models, dictionaries, and `POST /decisions` for the
human-in-the-loop record.

### From scratch

Prerequisites: Python ≥ 3.12, Docker, Node.js ≥ 22.12 (frontend development only), the raw datasets in
`data/raw/` (see below).
On macOS LightGBM also needs the OpenMP runtime: `brew install libomp`.

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt

cp .env.example .env      # set POSTGRES_PASSWORD and DEMO_API_KEY (the specialist key the UI's proxy adds server-side)
make up                   # postgres (pgvector/pgvector:pg16) + backend; data endpoints answer 503 until marts exist
make ingest               # migrations + raw CSV -> data/processed/*.parquet -> postgres (~2 min)
make baseline             # reports/01_baseline.md
make train                # models A, B, C -> artifacts/models/, reports/02_models.md (~5 min)
make predict              # predictions -> pred_referral, pred_daily_forecast, model_registry (~2 min), then marts
open http://localhost:8000/docs
make create-key ROLE=admin LABEL="администратор"   # API key, printed once (docs/security.md)
make test                 # API tests against the running postgres
make web-install          # frontend dependencies (npm ci) — needed for make audit and make web-dev
make audit                # repository audit: layout, secrets, alembic check, ruff, tests, docs/api.md vs routes,
                          # frontend lint + production build
```

Other targets: `make marts` (rebuild the serving marts after editing `ml/configs/serving.yaml`), `make registry`
(refresh model cards / metrics in `model_registry` after editing `ml/configs/model_cards.yaml`), `make backup` /
`make restore FILE=…` (pg_dump to `backups/`, restore asks for confirmation),
`make api-dev` (local uvicorn with auto-reload on port 8001), `make lint` / `make fmt` (ruff check / fix + format on
`backend/`, `ml/`, `tools/`; config in the root `pyproject.toml`), `make fixture` (rebuild the 2-region CI test
fixture from the current database), `make fixture-load` (load it into an empty database), `make web-dev` (Vite on http://localhost:5173 with `/api`
proxied to localhost:8000), `make web-test` / `make web-lint` / `make web-build` (frontend tests, ESLint + Prettier,
production build), `make train MODEL=load_forecast` (one model:
wait_time | refusal_risk | load_forecast), `make psql` (shell in the database), `make migrate`, `make down`.
The step-1 inventory was a one-off and lives in scratch: `.venv/bin/python scratch/00_inventory.py` →
`reports/00_inventory.md` (only if `scratch/` is present locally; it is not versioned).

## Development rules

- **Run `make audit` before every commit** (Postgres up, marts built). It fails if a file that would be committed
  sits outside the allowed top level (`backend ml frontend db docs tools .github` + root config files), if any such
  file is a `.env` or contains something that looks like a secret, if `alembic check` sees drift between models and
  migrations, if ruff or pytest fail, if `docs/api.md` and the app's endpoints disagree, if any API route other
  than the health checks lacks an auth dependency, or if the frontend lint or production build fails. CI (GitHub
  Actions) runs the backend lint + tests and the frontend lint + tests + build on every push and pull request.
- **Every new endpoint declares a role** (`ViewerDep`, `SpecialistDep` or `AdminDep` from `app.core.security`) and is
  documented in docs/api.md; never commit API keys — `.env` and `backups/` are gitignored.
- **Never modify, move or delete anything under `data/raw/`.** Pipelines only read it.
- **Scratch work goes to `scratch/` and nowhere else.** Any temporary, exploratory or
  self-verification file — scratch scripts, ad-hoc checks, test dumps, comparison outputs, logs of
  one-off runs — is created under `scratch/` (gitignored). Everything outside `scratch/` must be
  product code, configuration, migrations, docs or tests that a maintainer would keep.
- Generated outputs have fixed homes: `data/processed/` (Parquet), `reports/` (reports),
  `artifacts/models/` (model versions) — all gitignored.
- Schema changes only through Alembic migrations in `backend/alembic/versions/`.
- Code style: ruff (`make fmt` to fix, `make lint` to check), line length 120.
- Test fixtures (`backend/tests/fixtures/`) are small (< 5 MB), rebuilt with `make fixture`, and contain only rows
  derived from the open data and model outputs — never copy anything else there.

## Layout

```
backend/    FastAPI service (/api/v1: routers, schemas, services), SQLAlchemy models, Alembic migrations,
            tests (pytest + httpx; fixtures/ = 2-region CI dataset), Dockerfile
ml/         hqai_ml package (ingest, features, models, evaluation, explain, registry, serving implemented;
            causal is a placeholder), pipelines/ (ingest, baseline, train, predict, build_marts), configs/
frontend/   web UI: React 18 + Vite + TypeScript, TanStack Query, Recharts, Tailwind; strings in src/i18n/ru.ts;
            Dockerfile (node build → nginx, /api proxy)
tools/      audit.py (make audit), test_fixture.py (make fixture / fixture-load)
.github/    workflows/ci.yml — lint + API tests on push and pull request
db/         init.sql (pgvector, pg_trgm)
docs/       architecture.md (structure + data flow), data.md (tables, columns, cleaning rules), frontend.md (screen
            map, API calls per screen), security.md (access control, audit trail, what production must add),
            model_card.md (models, evaluation, limitations, intended use), api.md (endpoints, auth, load_index,
            recommendation rule)
data/       raw/ input (read-only), processed/ Parquet          — gitignored
reports/    generated reports                                   — gitignored
artifacts/  models/<name>/<version>/ + manifest.json            — gitignored
notebooks/                                                      — gitignored
scratch/    temporary / exploratory / verification files        — gitignored (see Development rules)
backups/    make backup (pg_dump)                               — gitignored
```

## Data

`data/raw/` contains folders `1 dataset` … `8 dataset`:

| # | content | source | role |
|---|---|---|---|
| 1 | Referrals for planned hospitalization (CSV parts) | IS BG | core |
| 2 | Patients waiting for planned hospitalization (CSV) | IS BG | core (same cohort as 1, used for region codes) |
| 3 | Refusals at the admission unit (CSV parts) | IS BG | core |
| 4 | Treated cases per medical organization (CSV) | ERSB | core |
| 5 | Vaccination facts (may be empty) | | secondary |
| 6 | Vaccination refusals and contraindications (CSV) | | secondary |
| 7 | Newly diagnosed oncology patients (XLSX) | | secondary |
| 8 | Advanced-stage malignant neoplasms by localization (XLSX) | | secondary |

Details, cleaning rules and every derived column: [docs/data.md](docs/data.md).

## Status

- [x] Step 1 — raw data inventory (`reports/00_inventory.md`)
- [x] Step 2 — data layer: Postgres schema (Alembic), DuckDB ingest to Parquet and Postgres,
      dictionaries (`ml/configs/regions.yaml` to review), daily aggregates incl. queue reconstruction,
      descriptive baseline (`reports/01_baseline.md`)
- [x] Step 3 — models: wait time (A), refusal risk (B), 14-day load forecast (C) with temporal
      evaluation against naive baselines, SHAP explanations in Russian, artifact registry, predictions in
      Postgres (`reports/02_models.md`, [docs/model_card.md](docs/model_card.md))
- [x] Step 4 — backend: serving marts (Alembic `0003`, `make marts`) with `load_index`, FastAPI `/api/v1`
      (overview, regions, hospital cards, referrals, rule-based recommendations, alerts, models, dictionaries),
      human-in-the-loop `decision_log`, docker `backend` service, API tests ([docs/api.md](docs/api.md))
- [x] Step 4b — excess queue trend (Alembic `0004`), display-ready explanation values, ruff, `make audit`, CI with
      a 2-region fixture
- [x] Step 5 — frontend: five screens against the API, decisions from the card, docker `frontend` service on
      port 3000 ([docs/frontend.md](docs/frontend.md))
- [x] Step 6 — API gaps closed (model cards, `/config`, decision alternative + idempotency, ICD names, short labels,
      units, alert filters, `high_load_share`), API-key auth with roles and access log, XLSX/PDF export, backup /
      restore, frontend CI job ([docs/security.md](docs/security.md))
- [ ] Causal effect estimate for recommendations (replaces `historical_median`)
