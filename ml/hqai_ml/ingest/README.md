# hqai_ml.ingest

Raw open data (`data/raw`, read-only) → DuckDB → clean Parquet (`data/processed`) → Postgres.
Entry point: `ml/pipelines/ingest.py` (`make ingest`). Every table, derived column and cleaning
rule is documented in [docs/data.md](../../../docs/data.md).

| module | role |
|---|---|
| `config.py` | settings from `.env` + parameters from `ml/configs/ingest.yaml` |
| `sources.py` | find CSV parts, reject invalid/truncated files, stage them as VARCHAR tables |
| `normalize.py` | whitespace/quotes/homoglyph normalization, matching keys |
| `staging.py` | typed and cleaned `stg_*` tables |
| `dictionaries.py` | `dim_region` (+ `regions.yaml`), `dim_profile`, `dim_organization`, `ersb_snapshot` |
| `facts.py` | `fact_referral`, `fact_admission_refusal` |
| `aggregates.py` | daily aggregates incl. queue-length reconstruction |
| `load_postgres.py` | streaming COPY of all Parquet files in one transaction |
