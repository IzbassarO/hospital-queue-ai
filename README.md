# hospital-queue-ai

A data-driven prototype for monitoring and forecasting planned-hospitalization queues and hospital
load in Kazakhstan, built on Ministry of Health open data (GovTech Camp 2026, Case 1). The goal is
to show where referral queues build up, how quickly patients are admitted or refused, and which
hospitals and regions are overloaded relative to their capacity.

## Quickstart

Prerequisites: Python ≥ 3.12, Docker, the raw datasets in `data/raw/` (see below).

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt

cp .env.example .env      # set POSTGRES_PASSWORD
make up                   # postgres (pgvector/pgvector:pg16) with a healthcheck
make ingest               # migrations + raw CSV -> data/processed/*.parquet -> postgres (~2 min)
make baseline             # reports/01_baseline.md
```

Other targets: `make psql` (shell in the database), `make migrate`, `make down`.
Step 1 inventory of the raw files: `.venv/bin/python scripts/00_inventory.py` → `reports/00_inventory.md`.

## Layout

```
backend/    FastAPI app skeleton (/health), SQLAlchemy models, Alembic migrations
ml/         hqai_ml package (ingest implemented; features, models, causal, evaluation,
            explain, registry are placeholders), pipelines/, configs/
frontend/   placeholder
db/         init.sql (pgvector, pg_trgm)
docs/       architecture.md (structure + data flow), data.md (tables, columns, cleaning rules)
scripts/    00_inventory.py
data/       raw/ input (read-only), processed/ Parquet          — gitignored
reports/    generated reports                                   — gitignored
notebooks/, artifacts/                                          — gitignored
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
- [ ] Features and forecasting models
- [ ] API endpoints
- [ ] Frontend
