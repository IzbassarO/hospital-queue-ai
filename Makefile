-include .env
export

PY           ?= $(CURDIR)/.venv/bin/python
ML_PATH      := $(CURDIR)/ml
API_DEV_PORT ?= 8001

.PHONY: up down migrate ingest baseline psql train tournament flow-evidence predict registry marts create-key backup restore api-dev test ml-test \
        lint fmt audit fixture fixture-load web-install web-dev web-lint web-test web-build

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

train:         ## train + evaluate candidates; ARGS="--promote" publishes the current set (MODEL=<name>, ARGS="...")
	PYTHONPATH=$(ML_PATH) $(PY) ml/pipelines/train.py $(if $(MODEL),--model $(MODEL),) $(ARGS)

tournament:    ## patient-journey tournament; PROFILE=smoke|laptop|overnight, ARGS="--resume <run-id>"
	PYTHONPATH=$(ML_PATH) $(PY) ml/pipelines/tournament.py --profile $(or $(PROFILE),smoke) $(ARGS)

flow-evidence: ## non-promoting 1..14-day flow-forecast evidence; PROFILE=laptop, ARGS="--resume <run-id>"
	PYTHONPATH=$(ML_PATH) $(PY) ml/pipelines/flow_forecast.py --profile $(or $(PROFILE),laptop) $(ARGS)

predict: migrate ## predictions of the current models -> postgres (pred_referral, pred_daily_forecast, model_registry), then marts
	PYTHONPATH=$(ML_PATH) $(PY) ml/pipelines/predict.py
	PYTHONPATH=$(ML_PATH) $(PY) ml/pipelines/build_marts.py

registry: migrate ## refresh model_registry (metrics + model cards from ml/configs/model_cards.yaml) without predicting
	PYTHONPATH=$(ML_PATH) $(PY) ml/pipelines/predict.py --registry-only

marts: migrate ## serving marts for the API (mart_* tables) from facts, aggregates and predictions; config ml/configs/serving.yaml
	PYTHONPATH=$(ML_PATH) $(PY) ml/pipelines/build_marts.py

create-key:    ## create an API key and print it once: make create-key ROLE=specialist LABEL="Иванова А., УОЗ г. Астана"
	@test -n "$(ROLE)" -a -n "$(LABEL)" || { echo 'usage: make create-key ROLE=viewer|specialist|admin LABEL="who uses it"'; exit 2; }
	@cd backend && $(PY) -m app.cli create-key --role "$(ROLE)" --label "$(LABEL)"

BACKUP_DIR := backups

backup:        ## pg_dump of the whole database (custom format) -> backups/hqai_<timestamp>.dump
	@mkdir -p $(BACKUP_DIR)
	@f=$(BACKUP_DIR)/hqai_$$(date +%Y%m%d-%H%M%S).dump; \
	docker compose exec -T postgres pg_dump -U $(POSTGRES_USER) -d $(POSTGRES_DB) --format=custom --no-owner > $$f.partial \
	  && mv $$f.partial $$f && echo "backup: $$f ($$(du -h $$f | cut -f1))" \
	  || { rm -f $$f.partial; echo "backup failed"; exit 1; }

restore:       ## restore a backup INTO $(POSTGRES_DB), replacing its tables: make restore FILE=backups/hqai_….dump [CONFIRM=yes]
	@test -f "$(FILE)" || { echo "usage: make restore FILE=backups/hqai_<timestamp>.dump"; exit 2; }
	@if [ "$(CONFIRM)" != "yes" ]; then \
	  printf "Replace all tables of database '$(POSTGRES_DB)' with $(FILE)? Type yes: "; read answer; \
	  [ "$$answer" = "yes" ] || { echo "aborted"; exit 1; }; fi
	docker compose exec -T postgres pg_restore -U $(POSTGRES_USER) -d $(POSTGRES_DB) --clean --if-exists --no-owner --single-transaction < "$(FILE)"
	@echo "restored $(FILE) into $(POSTGRES_DB); restart the backend if it was running: docker compose restart backend"

api-dev:       ## run the API locally with auto-reload on http://localhost:$(API_DEV_PORT) (docker backend keeps 8000)
	cd backend && $(PY) -m uvicorn app.main:app --reload --host 127.0.0.1 --port $(API_DEV_PORT)

test:          ## API tests (pytest + httpx) against the running postgres; HQAI_API_BASE_URL=http://localhost:8000 to test a running server
	cd backend && $(PY) -m pytest

ml-test:       ## deterministic ML experiment/registry contract tests (no model fitting or database)
	cd ml && $(PY) -m pytest

LINT_PATHS := backend ml tools

lint:          ## ruff lint + format check (config: pyproject.toml)
	$(PY) -m ruff check $(LINT_PATHS)
	$(PY) -m ruff format --check $(LINT_PATHS)

fmt:           ## ruff: apply safe lint fixes, then format
	$(PY) -m ruff check --fix $(LINT_PATHS)
	$(PY) -m ruff format $(LINT_PATHS)

audit:         ## repository audit: architecture, OpenAPI/generated types, database, tests, docs/auth, frontend and secrets
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
