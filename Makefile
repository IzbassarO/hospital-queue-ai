-include .env
export

PY           ?= $(CURDIR)/.venv/bin/python
ML_PATH      := $(CURDIR)/ml
API_DEV_PORT ?= 8001
PYTHON3      ?= python3

# Bare `make` prints the targets; starting a stack is always an explicit choice.
.DEFAULT_GOAL := help

.PHONY: help smoke env demo up down prod-config pipe pipe-build migrate ingest baseline psql train tournament flow-evidence flow-quantile flow-calibration flow-hierarchy flow-pressure signal-prioritization flow-scenario decision-alternatives model-assurance assurance-publish operational-intelligence-bundle operational-intelligence-publish review-evidence-bundle review-evidence-publish waiting-list-bundle waiting-list-publish referral-estimates-bundle referral-estimates-publish verification-worklist-bundle verification-worklist-publish predict registry marts create-key backup restore api-dev test ml-test \
        models-export models-quantile-export models-test lint fmt audit fixture fixture-load seed-build seed-load web-install web-dev web-lint web-test web-build web-build-off

help:          ## list the targets (bare `make` shows this)
	@echo "hospital-queue-ai — make targets. First run: make demo"
	@grep -hE '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
	  | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-26s\033[0m %s\n", $$1, $$2}'

smoke:         ## check a running stack: API health and the published evidence (make demo runs it at the end)
	@test -n "$$DEMO_API_KEY" || { echo "  DEMO_API_KEY is not set in .env: run make env"; exit 1; }
	@api=http://localhost:$${API_PORT:-8000}; ui=http://localhost:$${FRONTEND_PORT:-3000}; \
	curl -fsS "$$api/health" > /dev/null && echo "  liveness      ok" || { echo "  liveness      FAILED ($$api/health)"; exit 1; }; \
	curl -fsS -H "X-API-Key: $$DEMO_API_KEY" "$$api/api/v1/operational-intelligence/overview" > /tmp/hqai-smoke.json \
	  || { echo "  publication   FAILED: no operational publication - run: docker compose --profile demo run --rm seed"; exit 1; }; \
	$(PYTHON3) tools/smoke_publication.py < /tmp/hqai-smoke.json; \
	curl -fsS -H "X-API-Key: $$DEMO_API_KEY" "$$api/api/v1/model-assurance" > /dev/null && echo "  passport      ok" || { echo "  passport      FAILED"; exit 1; }; \
	curl -fsS -H "X-API-Key: $$DEMO_API_KEY" "$$api/api/v1/review-evidence/overview" > /dev/null && echo "  evidence      ok" || { echo "  evidence      FAILED"; exit 1; }; \
	curl -fsS -H "X-API-Key: $$DEMO_API_KEY" "$$api/api/v1/waiting-list/hospitals?limit=1" > /dev/null && echo "  waiting list  ok" || { echo "  waiting list  FAILED"; exit 1; }; \
	curl -fsS -H "X-API-Key: $$DEMO_API_KEY" "$$api/api/v1/referral-estimates/publication" > /dev/null && echo "  estimates     ok" || { echo "  estimates     FAILED"; exit 1; }; \
	curl -fsS -H "X-API-Key: $$DEMO_API_KEY" "$$api/api/v1/verification-worklist/publication" > /dev/null && echo "  worklist      ok" || { echo "  worklist      FAILED"; exit 1; }; \
	curl -fsS -o /dev/null -w "  UI            HTTP %{http_code}\n" "$$ui/" || { echo "  UI            FAILED"; exit 1; }; \
	rm -f /tmp/hqai-smoke.json

up:            ## build and start postgres + backend + frontend (UI http://localhost:3000, API docs http://localhost:8000/docs)
	docker compose up -d --build --wait

down:          ## stop all services (data volume is kept)
	docker compose down

env:           ## create .env from .env.example with a random database password and demo API key (kept if it exists)
	@if [ -f .env ]; then echo ".env exists, kept"; \
	  if grep -q '^\(DEMO_API_KEY\)=[[:space:]]*$$' .env; then \
	    echo "WARNING: DEMO_API_KEY in .env is EMPTY -> the UI will show 'API key required'."; \
	    echo "         Set it (python3 -c 'import secrets; print(\"hqai_\" + secrets.token_urlsafe(32))')"; \
	    echo "         or delete .env and run 'make env' again, then 'make up'."; fi; else \
	  pw=$$(LC_ALL=C tr -dc 'A-Za-z0-9' < /dev/urandom | head -c 32); \
	  key=hqai_$$(LC_ALL=C tr -dc 'A-Za-z0-9_-' < /dev/urandom | head -c 43); \
	  sed -e "s|^\(POSTGRES_PASSWORD\)=.*|\1=$$pw|" -e "s|^\(DEMO_API_KEY\)=.*|\1=$$key|" .env.example > .env \
	  && echo ".env created (generated POSTGRES_PASSWORD and DEMO_API_KEY; see docs/security.md)"; fi

demo: env      ## fresh clone -> running product with the published evidence for all regions (Docker only): .env, containers, seed
	@echo "note: on a machine that already runs the stack, 'make up' (docker compose up --build) rebuilds the images and recreates the backend container"
	$(MAKE) up
	docker compose --profile demo run --rm seed
	@$(MAKE) --no-print-directory smoke
	@echo "UI       http://localhost:$${FRONTEND_PORT:-3000}"
	@echo "API docs http://localhost:$${API_PORT:-8000}/docs"

prod-config:   ## check the production overlay (docker-compose.prod.yml) without starting anything
	docker compose -f docker-compose.yml -f docker-compose.prod.yml --profile demo --profile pipelines config > /dev/null
	@echo "docker-compose.yml + docker-compose.prod.yml: valid (docs/operations.md)"

.PHONY: deploy-check
deploy-check:  ## shared server: verify rootless docker, linger, .env ports/UI_BIND, free ports, permissions; changes nothing
	@bash tools/deploy.sh check

pipe-build:    ## build the ML pipelines image (ml/Dockerfile) used by `make pipe`
	docker compose --profile pipelines build pipelines

pipe:          ## run an ML pipeline in that image, no host Python: make pipe CMD='ml/pipelines/flow_quantile.py --plan'
	@test -n "$(CMD)" || { echo "usage: make pipe CMD='ml/pipelines/flow_quantile.py --plan'"; exit 2; }
	docker compose --profile pipelines run --rm --no-deps --user $$(id -u):$$(id -g) pipelines python $(CMD)

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

flow-quantile: ## non-promoting p10/p50/p90 flow evidence; PROFILE=laptop, ARGS="--plan|--run-id ...|--resume ..."
	PYTHONPATH=$(ML_PATH) $(PY) ml/pipelines/flow_quantile.py --profile $(or $(PROFILE),laptop) $(ARGS)

flow-calibration: ## temporal interval calibration from a completed flow-quantile run; ARGS="--source-run ... --run-id ..."
	PYTHONPATH=$(ML_PATH) $(PY) ml/pipelines/flow_calibration.py --profile $(or $(PROFILE),laptop) $(ARGS)

flow-hierarchy: ## central hierarchy/fallback evidence from accepted quantile + calibration runs
	PYTHONPATH=$(ML_PATH) $(PY) ml/pipelines/flow_hierarchy.py --profile $(or $(PROFILE),laptop) $(ARGS)

flow-pressure: ## preventive historical-flow pressure and unusual-flow warning evidence
	PYTHONPATH=$(ML_PATH) $(PY) ml/pipelines/flow_pressure.py --profile $(or $(PROFILE),laptop) $(ARGS)

signal-prioritization: ## deterministic entity/origin Signals Inbox preparation
	PYTHONPATH=$(ML_PATH) $(PY) ml/pipelines/signal_prioritization.py --profile $(or $(PROFILE),laptop) $(ARGS)

flow-scenario: ## offline non-causal forecast stress tests from the accepted flow chain
	PYTHONPATH=$(ML_PATH) $(PY) ml/pipelines/flow_scenario.py --profile $(or $(PROFILE),laptop) $(ARGS)

decision-alternatives: ## retrospective constrained mathematical alternatives; no serving or physical-capacity claim
	PYTHONPATH=$(ML_PATH) $(PY) ml/pipelines/decision_alternatives.py --profile $(or $(PROFILE),laptop) $(ARGS)

model-assurance: ## deterministic assurance bundle over accepted evidence; no model fitting or science recomputation
	PYTHONPATH=$(ML_PATH) $(PY) ml/pipelines/model_assurance.py $(ARGS)

assurance-publish: migrate ## validate and transactionally publish BUNDLE=/path/to/model_assurance.json
	@test -n "$(BUNDLE)" || { echo 'usage: make assurance-publish BUNDLE=/path/to/model_assurance.json'; exit 2; }
	cd backend && $(PY) -m app.cli publish-assurance --bundle "$(BUNDLE)"

operational-intelligence-bundle: ## offline projection of the explicit accepted final-test evidence; no ML fitting
	$(PY) tools/operational_bundle.py

operational-intelligence-publish: migrate ## publish BUNDLE=/path/to/operational_intelligence.json
	@test -n "$(BUNDLE)" || { echo 'usage: make operational-intelligence-publish BUNDLE=/path/to/operational_intelligence.json'; exit 2; }
	cd backend && $(PY) -m app.cli publish-operational-intelligence --bundle "$(BUNDLE)"

review-evidence-bundle: ## offline projection of the accepted stress-test and decision-alternative evidence; no ML fitting
	$(PY) tools/review_evidence_bundle.py

review-evidence-publish: migrate ## publish BUNDLE=/path/to/review_evidence.json (requires the operational publication)
	@test -n "$(BUNDLE)" || { echo 'usage: make review-evidence-publish BUNDLE=/path/to/review_evidence.json'; exit 2; }
	cd backend && $(PY) -m app.cli publish-review-evidence --bundle "$(BUNDLE)"

waiting-list-bundle: ## offline export of the measured waiting list at the origin from postgres; no model output
	$(PY) tools/waiting_list_bundle.py

waiting-list-publish: migrate ## publish BUNDLE=/path/to/waiting_list.json
	@test -n "$(BUNDLE)" || { echo 'usage: make waiting-list-publish BUNDLE=/path/to/waiting_list.json'; exit 2; }
	cd backend && $(PY) -m app.cli publish-waiting-list --bundle "$(abspath $(BUNDLE))"

referral-estimates-bundle: ## per-referral estimates of an origin_journey run -> artifacts/referral_estimates/
	$(PY) tools/referral_estimates_bundle.py

referral-estimates-publish: migrate ## publish BUNDLE=/path/to/referral_estimates.json
	@test -n "$(BUNDLE)" || { echo 'usage: make referral-estimates-publish BUNDLE=/path/to/referral_estimates.json'; exit 2; }
	cd backend && $(PY) -m app.cli publish-referral-estimates --bundle "$(abspath $(BUNDLE))"

verification-worklist-bundle: ## ghost-queue run -> artifacts/verification_worklist/ (administrative review list)
	$(PY) tools/verification_worklist_bundle.py

verification-worklist-publish: migrate ## publish BUNDLE=/path/to/verification_worklist.json
	@test -n "$(BUNDLE)" || { echo 'usage: make verification-worklist-publish BUNDLE=/path/to/verification_worklist.json'; exit 2; }
	cd backend && $(PY) -m app.cli publish-verification-worklist --bundle "$(abspath $(BUNDLE))"

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

models-export: ## rebuild models/ (released model modules) from artifacts/ + data/processed; then run models-test
	PYTHONPATH=$(ML_PATH) $(PY) ml/pipelines/export_models.py $(ARGS)

models-quantile-export: ## refit + verify the final-origin p10/p50/p90 boosters -> models/flow_quantile (about 3 minutes)
	PYTHONPATH=$(ML_PATH) $(PY) ml/pipelines/export_flow_quantile_models.py $(ARGS)

models-test:   ## release contract of models/: manifest digests, standalone predict.py and joblib bundles reproduce the examples
	cd ml && $(PY) -m pytest tests/test_models_release.py

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

seed-build:    ## rebuild the demo seed from the current database and artifacts -> seed/ (tools/seed_bundle.py)
	PYTHONPATH=$(ML_PATH) $(PY) tools/seed_bundle.py

seed-load: migrate ## load seed/ into an EMPTY migrated database from the host; REPLACE=1 truncates the seeded data tables first
	cd backend && $(PY) -m app.cli load-seed --dir ../seed $(if $(REPLACE),--replace,)

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

web-build-off: ## production build without the synthetic layer (VITE_SYNTHETIC=off, frontend/src/synthetic/README.md)
	$(WEB) VITE_SYNTHETIC=off npm run build
