# seed/ — demo seed for `make demo`

What a fresh clone needs to show the product with Docker alone: the serving tables for all 20 regions and the four
accepted publications, about 30 MB in total. `make demo` loads it into the compose database
(`backend/app/services/seed.py`, `python -m app.cli load-seed`). Nothing here is needed by the pipelines, which
rebuild every row from the MoH open data; the seed only spares a stranger the 16 GB of raw files and the hours of
pipeline runs. `manifest.json` is the authoritative list of files, rows, sizes and SHA-256 digests.

## Contents

| File | Rows | Scope |
| --- | ---: | --- |
| `tables/dim_region.csv.gz` | 20 | national |
| `tables/dim_profile.csv.gz` | 97 | national |
| `tables/dim_icd.csv.gz` | 6 479 | national |
| `tables/ersb_snapshot.csv.gz` | 2 196 | national |
| `tables/dim_organization.csv.gz` | 1 406 | national |
| `tables/fact_referral.csv.gz` | 19 698 | regions 62, 59 |
| `tables/agg_daily_hospital_profile.csv.gz` | 588 330 | national |
| `tables/agg_daily_region_profile.csv.gz` | 128 340 | national |
| `tables/agg_daily_admission_refusals.csv.gz` | 29 570 | national |
| `tables/pred_referral.csv.gz` | 8 320 | regions 62, 59 |
| `tables/pred_daily_forecast.csv.gz` | 5 544 | regions 62, 59 |
| `tables/model_registry.csv.gz` | 3 | national |
| `tables/mart_hospital_profile_status.csv.gz` | 6 537 | national |
| `tables/mart_region_profile_status.csv.gz` | 1 426 | national |
| `tables/mart_area_status.csv.gz` | 21 | national |
| `tables/mart_build_info.csv.gz` | 1 | national |
| `model_assurance.json` | 13 capabilities | `model-assurance-6b5-v1`, identity `f504defe…39f5` |
| `operational_intelligence.json.gz` | 225 680 forecasts, 4 194 signals | `operational-intelligence-slice5-final-test-2025-03-17-v1`, identity `43da33ec…5cfd` |
| `review_evidence.json.gz` | 4 scenarios, 10 084 entities, 141 176 cells, 460 alternative sets | `review-evidence-slice6-final-test-2025-03-17-v1`, identity `e07be2f1…3c22` |
| `waiting_list.json.gz` | 640 hospitals, 65 232 waiting referrals | `waiting-list-origin-2025-03-17-v1`, identity `1c4fceb1…b188` |

Tables are `COPY … TO STDOUT (FORMAT csv, HEADER true)` ordered by primary key, gzip level 9 without timestamp or file
name, so a rebuild of unchanged data is byte-identical and `git diff` shows only real changes. The bundles are the
exact bytes that were published (`model_assurance.json` as is, the two large ones gzipped the same way): the loader
checks the decompressed content against `raw_sha256`, and the publish services recompute the identities, so a
seeded database serves the same `publication_identity_sha256` values as the machine the evidence was produced on.

## National versus two regions

Everything the map, the region and hospital cards, the signals inbox, Model Assurance, the review evidence and the
waiting list read is national: dictionaries, daily aggregates, serving marts (built from the full data as of
2025-03-31), model registry and the four publications. The waiting list is national in particular: all 20 regions,
all 640 hospitals that had a queue at the 17.03.2025 origin, so `/waiting-list/hospitals` answers everywhere even
though `fact_referral` itself is a two-region slice. Only `fact_referral`, `pred_referral` and `pred_daily_forecast` are a slice, the same one
as the CI fixture (`tools/test_fixture.py`): regions 62 and 59, referrals since 2025-02-02, per-referral predictions
for the test period 2025-03-01 to 2025-03-31, daily forecasts from the serving origin. The referral list endpoints and
per-referral predictions therefore answer for those two regions and return empty pages elsewhere. Do not run
`make marts` on a seeded database: it would rebuild the national marts from the two-region facts.

Not included: raw MoH files (`data/`, 16 GB), processed parquet, model files (`models/`), API keys, the access log
and the specialist decisions. The loader never writes `api_keys`, `access_log`, `decision_log` or
`specialist_decision`.

## Loading

```bash
make demo                                     # fresh clone: .env with generated secrets, containers, seed
docker compose --profile demo run --rm seed   # seed again, for example after `docker compose down -v`
make seed-load                                # from the host into an empty migrated database (.venv)
make seed-load REPLACE=1                      # truncate the seeded data tables first; keys, log, decisions kept
```

The loader verifies every file's size and SHA-256 against `manifest.json` before writing anything, refuses a database
that holds data other than this seed unless `--replace` is given, leaves a database that already holds exactly the
seed alone (the publications are re-activated, not duplicated), loads the tables in foreign-key order in one
transaction with row counts checked against the manifest, then publishes the four bundles through the same services
as `make assurance-publish`, `make operational-intelligence-publish`, `make review-evidence-publish` and
`make waiting-list-publish`. Exit code 2
on any failure. A full load takes about 2.5 minutes on a laptop; the two large publications dominate.

## Rebuilding

```bash
make seed-build        # running database with the full data + artifacts/ -> seed/ (tools/seed_bundle.py)
```

The builder exports the tables from the running database, copies each active publication's bundle from `artifacts/`
after checking its SHA-256 against `bundle_sha256` of the active snapshot, removes stale table files and writes
`manifest.json` with provenance (publication ids, identities, source run ids, source code commit, serving
`as_of_date`, the slice definition). Budget: 40 MB. Regions: `--regions 62 59` (default, from the fixture).


## Loading into a database that is not empty

The loader never overwrites data it did not write itself, and tells four situations apart:

| State of the database | What `load-seed` does |
|---|---|
| empty | loads the tables, then publishes the three bundles |
| already holds exactly this seed | leaves the tables alone, re-activates the publications |
| holds more than the seed (a full pipeline run: 767 130 referrals against the seed's two-region slice) | leaves the tables alone, loads only the publications |
| some table holds fewer rows than the seed | stops and asks for `--replace` |

So `make demo` is safe on a machine that has already run `make ingest predict marts`: the full data stays, and the
published evidence appears on screen. `--replace` truncates only the tables the seed loads (plus
`fact_admission_refusal`, which references them) and never touches API keys, the access log or specialist decisions.

## Reproducing everything from the open data

`make ingest predict marts` rebuilds the tables from the MoH files described in `docs/data.md`; the evidence chain
(`make flow-quantile`, `flow-calibration`, `flow-hierarchy`, `flow-pressure`, `signal-prioritization`,
`flow-scenario`, `decision-alternatives`, `model-assurance`) and the projections `tools/operational_bundle.py`
and `tools/review_evidence_bundle.py` produce the bundles; the `*-publish` targets load them. The run ids are listed
in `manifest.json` and `docs/project-evidence-index.md`.
