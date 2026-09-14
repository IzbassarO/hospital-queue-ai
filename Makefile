-include .env
export

PY      ?= $(CURDIR)/.venv/bin/python
ML_PATH := $(CURDIR)/ml

.PHONY: up down migrate ingest baseline psql

up:            ## start postgres and wait until it is healthy
	docker compose up -d --wait

down:          ## stop postgres (data volume is kept)
	docker compose down

migrate:       ## apply Alembic migrations
	cd backend && $(PY) -m alembic upgrade head

ingest: migrate ## raw CSV -> data/processed/*.parquet -> postgres
	PYTHONPATH=$(ML_PATH) $(PY) ml/pipelines/ingest.py

baseline:      ## descriptive baseline report from data/processed -> reports/01_baseline.md
	PYTHONPATH=$(ML_PATH) $(PY) ml/pipelines/baseline.py

psql:          ## interactive psql inside the container
	docker compose exec postgres psql -U $(POSTGRES_USER) -d $(POSTGRES_DB)
