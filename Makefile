-include .env
export

PY           ?= $(CURDIR)/.venv/bin/python
ML_PATH      := $(CURDIR)/ml
API_DEV_PORT ?= 8001

.PHONY: up down migrate ingest baseline psql train predict marts api-dev test lint fmt audit fixture fixture-load \
        web-install web-dev web-lint web-test web-build

up:            ## build and start postgres + backend + frontend (UI http://localhost:3000, API docs http://localhost:8000/docs)
	docker compose up -d --build --wait

down:          ## stop all services (data volume is kept)
	docker compose down

migrate:       ## apply Alembic migrations
	cd backend && $(PY) -m alembic upgrade head

ingest: migrate ## raw CSV -> data/processed/*.parquet -> postgres
	PYTHONPATH=$(ML_PATH) $(PY) ml/pipelines/ingest.py

baseline:      ## descriptive baseline report from data/processed -> reports/01_baseline.md
	PYTHONPATH=$(ML_PATH) $(PY) ml/pipelines/baseline.py

psql:          ## interactive psql inside the container
	docker compose exec postgres psql -U $(POSTGRES_USER) -d $(POSTGRES_DB)

train:         ## train + evaluate models A, B, C -> artifacts/models, reports/02_models.md (MODEL=<name> for one)
	PYTHONPATH=$(ML_PATH) $(PY) ml/pipelines/train.py $(if $(MODEL),--model $(MODEL),)

predict: migrate ## predictions of the current models -> postgres (pred_referral, pred_daily_forecast, model_registry), then marts
	PYTHONPATH=$(ML_PATH) $(PY) ml/pipelines/predict.py
	PYTHONPATH=$(ML_PATH) $(PY) ml/pipelines/build_marts.py

marts: migrate ## serving marts for the API (mart_* tables) from facts, aggregates and predictions; config ml/configs/serving.yaml
	PYTHONPATH=$(ML_PATH) $(PY) ml/pipelines/build_marts.py

api-dev:       ## run the API locally with auto-reload on http://localhost:$(API_DEV_PORT) (docker backend keeps 8000)
	cd backend && $(PY) -m uvicorn app.main:app --reload --host 127.0.0.1 --port $(API_DEV_PORT)

test:          ## API tests (pytest + httpx) against the running postgres; HQAI_API_BASE_URL=http://localhost:8000 to test a running server
	cd backend && $(PY) -m pytest

LINT_PATHS := backend ml tools

lint:          ## ruff lint + format check (config: pyproject.toml)
	$(PY) -m ruff check $(LINT_PATHS)
	$(PY) -m ruff format --check $(LINT_PATHS)

fmt:           ## ruff: apply safe lint fixes, then format
	$(PY) -m ruff check --fix $(LINT_PATHS)
	$(PY) -m ruff format $(LINT_PATHS)

audit:         ## repository audit before every commit: layout, secrets, alembic check, ruff, pytest, docs/api.md vs routes
	PYTHONPATH=$(ML_PATH) $(PY) tools/audit.py

fixture:       ## rebuild the 2-region CI test fixture from the current database -> backend/tests/fixtures
	PYTHONPATH=$(ML_PATH) $(PY) tools/test_fixture.py build

fixture-load: migrate ## load the CI test fixture into an EMPTY database (CI); then run `make marts`
	PYTHONPATH=$(ML_PATH) $(PY) tools/test_fixture.py load

WEB := cd frontend &&

web-install:   ## install frontend dependencies from the lockfile (npm ci)
	$(WEB) npm ci

web-dev:       ## Vite dev server on http://localhost:5173, /api proxied to localhost:8000 (API_PROXY_TARGET to change)
	$(WEB) npm run dev

web-lint:      ## ESLint + Prettier check
	$(WEB) npm run lint

web-test:      ## Vitest smoke tests (routes render, API client parses real responses)
	$(WEB) npm test

web-build:     ## type-check and production build -> frontend/dist
	$(WEB) npm run build
