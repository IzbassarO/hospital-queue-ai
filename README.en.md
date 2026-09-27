# Aqyl Kezek · Hospital Flow Intelligence

**The model warns. People decide.**

GovTech Camp 2026, AI GovTech track, **Case 1 "Hospital load and planned-hospitalization queues"**. Team BizAI.
Russian version: [README.md](README.md).

The system forecasts the flow of planned-hospitalization referrals for every hospital × profile pair 14 days ahead,
compares the forecast with the series' own historical norm, and raises a signal with the date the flow is expected
to exceed that norm. A specialist accepts, declines or requests data, and the decision is stored together with the
hash of the publication it answered, so it stays possible to reconstruct exactly which numbers the person saw.

![Control centre](docs/img/control-centre.png)

## Running it

You need git, GNU make and Docker with the compose plugin. No Python, no Node, no access to Ministry data.

```bash
git clone https://github.com/IzbassarO/hospital-queue-ai.git
cd hospital-queue-ai
make demo
```

The same `main` branch also sits in the submission repository: https://github.com/BAITC-Hacks/hack-043b4fcc-bizai

Measured twice on a clean copy: 7 minutes 41 seconds when Docker pulls and builds everything from scratch, and
3 minutes 47 seconds with the images already cached. Almost all of it is building.
`make demo` ends by checking itself (`make smoke`) and printing the addresses:

```
  liveness      ok
  publication   operational-intelligence-slice5-final-test-2025-03-17-v1 (4194 signals, 225680 forecast rows)
  passport      ok
  evidence      ok
  UI            HTTP 200
UI       http://localhost:3000
API docs http://localhost:8000/docs
```

`make demo` is `make env` (writes `.env` with a random database password and demo key, keeps an existing file),
then `make up`, then a one-shot `seed` container that loads the published evidence. A plain `make up` never touches
data. If the ports are taken, change `FRONTEND_PORT`, `API_PORT`, `POSTGRES_PORT` in `.env`. The database and the
API listen on localhost only; just the UI faces outwards. Bare `make` lists the targets.

The one-minute demo path: **Run** → the clock stops at "Specialist needed" → **Details** → **Accept** → the decision
appears in the journal. The whole interface exists in Russian and Kazakh.

## What works today

A map of all 1 406 hospitals coloured by published signals, an inbox with a deterministic rank, the referral queue
and the decision journal, the model passport with its hashes, a six-scene story of one signal, and an assistant that
explains published facts and gives no advice. Without a provider key the assistant says it is not connected and
everything else keeps working.

For the 17 March 2025 origin the system published 4 194 signals. The composition is worth naming precisely:

| What it is | Count |
|---|---|
| Flow-pressure forecast above the materiality floor: HIGH | 3 |
| Flow-pressure forecast above the materiality floor: ELEVATED | 90 |
| Anomalies in already observed flow (a separate detector) | 505 |
| **Total in the specialist's inbox** | **598** |
| WATCH above the floor | 2 428 |
| Cut by the materiality floor (zero norm, under one referral a day) | 1 047 |
| No threshold, data-quality queue | 121 |

The materiality floor removes series whose historical norm is zero and whose forecast is under one referral a day.
They produce HIGH by the rule, but alerting a person about them is pointless. Of the 93 forecast signals, 42 belong
to the day-hospital profile and 53 have a norm of at most one referral a day. Hospitals with a chronically long
queue (Almaty City Clinical Hospital No 1, cardiology: 719 waiting) do not enter this queue by construction: the
signal reacts to a change against the series' own norm, while the chronic level is what the load-index mart shows.

## Data

Ministry of Health open data for Q1 2025: 767 130 referrals for planned hospitalization, 1 508 732 admission-unit
refusals, an ERSB snapshot and the waiting list. 1 406 hospitals, 20 regions, 97 profiles, 6 537 daily hospital ×
profile series. The files carry no names or national IDs and the pipeline does not expect any. On 31 March 2025:
89 545 referrals in the queue, a median wait of 8 days (13 in Zhetisu), 18 816 refusals over 28 days, or 9.5 %.

The raw files (17.1 GB, 119 of them) are not in the repository; the organisers hand them out. So that a reviewer can
check their own copy, `docs/raw-manifest.json` records the size, SHA-256, header and row count of every file, plus
whether the pipeline reads it. We use 2.2 GB of what was given (datasets 1–4); the vaccination and oncology sets are
untouched because nothing links them to referrals. Verifying a copy is one command:

```bash
python tools/raw_manifest.py --verify docs/raw-manifest.json
```

Before anything becomes Parquet the data passes a quality gateway (`ml/hqai_ml/ingest/quality.py`): a contract on
columns and types, code formats, a plausibility window for dates, registration-before-outcome ordering, duplicates
and the day-hospital share. On the current data that is 125 checks over 10 tables and 3 032 300 rows, status PASS. A
hard violation stops the load and the previous data layer stays in place. The report can be produced without
reloading anything: `python ml/pipelines/ingest.py --check-quality`.

## Models

Time-based validation only: training on January–February 2025, rolling origins 16.02 / 23.02 / 02.03, and an
untouched final slice of 17 March 2025 that never selects a model, a feature or a calibrator.

| Model | Question | Algorithm | Quality | Status |
|---|---|---|---|---|
| Flow quantiles | referrals per day for 14 days, p10/p50/p90 | LightGBM quantile + conformal calibration + bottom-up hierarchy | WIS80 0.69 → 0.57; coverage 83 % on validation, 70 % on the final test against a nominal 80 % | in product |
| Point flow forecast | mean referrals per day | Poisson LightGBM against five simple methods | WAPE 63 % against 86 % for seasonal naive | not promoted |
| Admission by 7/14/30 days | probability of making it in time | XGBoost AFT | C-index 0.85, calibration error 0.01 | accepted |
| Admission by 7/14/30 days | same question, other approach | LightGBM discrete hazard | C-index 0.80 | accepted |
| Three outcomes | admitted / refused / waiting | Aalen–Johansen, no training | reference | accepted |
| Three outcomes, ML challenger | beat the reference | discrete competing risks | did not | rejected |
| Wait per referral | days until admission | LightGBM regression | MAE 10.5 against 11.1 for the rule; Spearman 0.73 against 0.70 | accepted |
| Refusal risk | probability of refusal | LightGBM classification | ROC-AUC 0.79 against 0.76 for the baseline | accepted |

Retrospective warning quality over 14 days: recall 0.68, hospital-level precision 0.39. The threshold leans towards
recall, because a missed exceedance costs more than a second look.

The point Poisson model lost to a plain same-weekday average in five of six validation cells, so the quantile model
went into the product and the point forecast stayed as evidence. A queue forecast derived from the flow forecast
turned out worse than simply keeping the last observed value, and we do not show it; the API says so plainly. The
ML model for three outcomes did not beat the Aalen–Johansen estimator, a statistic with no training, and was
rejected under the tournament rule.

The model passport (`docs/model-assurance-6b5.md`) holds 13 capabilities: 10 accepted, 2 accepted with reservations
(the stress test and the mathematical alternatives are evaluation-only), 1 not promoted. The passport identity is
`f504defe…39f5`, the operational publication `43da33ec…5cfd`, the review evidence `e07be2f1…3c22`. The same values
appear in the interface and in API responses, so any number on screen can be traced back to an accepted run.

### Models as modules

`models/` stands on its own: download it separately from the repository and use it anywhere. Six models in their
native format (LightGBM `model.txt`, XGBoost `model.json`), each with `predict.py` (CSV in, CSV out), the feature
contract, categories, metrics, an example input and its expected output, and for five of the six a `bundle.joblib`.
The only dependencies are lightgbm or xgboost, pandas and numpy. A SHA-256 per file lives in `models/manifest.json`.

```bash
python models/refusal_risk/predict.py --input referrals.csv --output scored.csv
```

We checked this the way an outsider would: copied two folders outside the repository and ran them with an empty
`PYTHONPATH`. Predictions matched the shipped expected output to 1e-16. The quantile boosters were never persisted
by the accepted run, so we refitted them with the same code at the 17 March 2025 origin and compared against the
published quantiles: a difference of 0.0 across 47 782 cells.

### The synthetic layer

The queue of pseudonymous referrals, the day simulation and the scenarios live entirely in
`frontend/src/synthetic/` — two JSON files and a generator, reached through a single import line. Everything of the
sort is labelled "synthetic" on screen, and `make web-build-off` removes the layer altogether. Nothing synthetic
enters the published forecasts, thresholds, severities, crossing dates or ranks.

## Architecture

A modular monolith with one direction of dependencies: `ml → database ← backend ← frontend`. The backend never
imports ML code, ML never runs inside an HTTP request, and the database schema changes only through Alembic.
Evidence reaches the read models through an explicit publication step. The rules are recorded in ADR 0001–0007 and
checked by `tools/architecture_check.py` on every CI run.

- `ml/` — Python 3.12+, DuckDB, LightGBM 4.7, XGBoost 3.4, scikit-learn, SHAP. Every run writes a manifest with
  hashes of data, configuration, code and artefacts, and resumes after an interruption. 396 tests, no database.
- `backend/` — FastAPI, SQLAlchemy 2, Alembic: 13 migrations, 32 tables, 38 OpenAPI operations, viewer / specialist
  / admin roles, an access log, idempotent decisions, XLSX and PDF export, a server-side assistant proxy. 153 tests;
  every endpoint answers in under 70 ms on the current data.
- `frontend/` — React 18, Vite, TypeScript, TanStack Query, an inline-SVG map. No scientific computation in the
  browser. 48 tests.
- `seed/` (30 MB) — what makes a clean clone work: the three publications byte for byte and the serving tables for
  all 20 regions. Record-level referrals are a two-region slice, enough to exercise the API.

## Integration

[docs/integration.md](docs/integration.md) describes three ways in: as a service beside your systems over the
`backend/openapi.json` contract; as ML modules from `models/` inside your own code; or as data, with the three JSON
publications loaded into your PostgreSQL by one command. No internet is needed at runtime, and the assistant is
optional and switches to an in-country model through one setting.

## Verification

```bash
make audit      # 14 gates: layout, secrets, ARCH001-005, OpenAPI contract, Alembic drift,
                # ruff, backend and ML tests, API docs, authorisation, frontend
make test       # 153 API tests          make ml-test   # 396 ML tests
make web-test   # 48 interface tests     make smoke     # a live stack answers and the publications are present
```

CI runs four jobs on every push: `backend` (migrations, the two-region fixture, marts, the full audit),
`demo-seed` (a clean database, the `seed/` load, identity checks through the API), `frontend` (Vitest) and
`docker-images` (building both images). All 14 gates are currently green.

## Limitations

Three months of data, so the model has not seen annual seasonality and claims none. One retrospective origin instead
of a live feed. Interval coverage on the final test is 70 % against the promised 80 %, worst at weekends (59.7 %)
and on holidays (66.7 %), and we show that rather than hide it. The open datasets contain no bed or staffing data,
which is why the signal is called flow pressure and not something stronger. The 7/14/30-day models are accepted but
not on screen; they need a daily referral feed. The mathematical alternatives take 6.7 hours on a laptop and are for
human review only. The prototype has no TLS and no SSO: nginx injects the demo key, so access to the UI port equals
access to the data.

## Before a production deployment

- **Data.** 21 months of history for seasonality, a daily feed of referrals and outcomes, bed and staffing figures.
  Expected result: interval coverage above 78 % and a median lead time of at least five days.
- **Infrastructure.** One server with 8 vCPU / 32 GB, a nightly recompute under two hours per origin, object
  storage for artefacts, an in-country language model or no assistant at all.
- **Security** ([docs/security.md](docs/security.md) §4). Ministry SSO instead of a shared key, TLS, a secret
  manager, separate PostgreSQL roles, a tamper-evident log shipped to a SIEM, a penetration test.
- **Product.** A live origin, admission probabilities on screen, a two-region pilot with measured indicators. The
  targets "8 → 7 days" and "9.5 % → 8 %" are pilot hypotheses, not a measured effect.
- **Monitoring** ([docs/monitoring.md](docs/monitoring.md)). The metrics and their baselines are already computed;
  alert thresholds get set from the first weeks of a pilot.

## How the work went

The code was written between 14 and 27 September: 43 commits by the 24th and the repository packaging after that.
Weeks 1 and 2 are reconstructed from the programme plan.

| Week | Dates | What was done |
|---|---|---|
| 1 | 3–6 Sep | Programme start, reviewing the cases, choosing Case 1, forming the team. <!-- confirm --> |
| 2 | 7–13 Sep | Webinars with the agencies, receiving the datasets, first reading of the data, a draft architecture: monolith, PostgreSQL, offline ML. <!-- confirm --> |
| 3 | 14–20 Sep | 14.09 project skeleton, Postgres in Docker, ingest, inventory. 15.09 wait, refusal-risk and flow models, time-based validation, SHAP, registry, the first interface, keys and roles, access log, export, CI. 16.09 architecture baseline, ADR 0001–0004, the OpenAPI contract. 17.09 reproducible runs with manifests, the patient-journey tournament. 18.09 the flow chain: quantiles, conformal calibration, hierarchy, pressure; a call with a NITEC ML engineer. 19.09 signal ranking, ADR 0005. 20.09 the stress-test engine, ADR 0006. |
| 4 | 21–27 Sep | 21.09 the constrained-alternatives engine with full verification. 22.09 the model passport, freezing the ML core, publishing the read models. 23.09 the control centre: map, inbox, queue, decisions in the database, assistant proxy, RU/KK. 24.09 README with screenshots, the deck, the speech and jury questions. 26–27.09 preparing for submission: `seed/` for a clean clone, `models/` as standalone modules, extracting the synthetic layer, the data-quality gateway, the raw-file manifest, the monitoring plan, this README. |
| 5 | 28 Sep – 3 Oct | Repository submission on the 28th, technical defence on the 29th, Digital Bridge 1–3 October. |

## Who did what

| Who | What |
|---|---|
| Izbassar Orynbassar | data, ML, backend, frontend, infrastructure — all of the code |
| Madina Sissenbay | technical coordination, project management, contact with the organisers and agencies, the demo scenario and the deck, testing the specialist workflow <!-- confirm --> |

## Documentation

[docs/architecture.md](docs/architecture.md) and [docs/adr/](docs/adr/) for boundaries and decisions ·
[docs/api.md](docs/api.md) for the 38 operations · [docs/data.md](docs/data.md) for sources and cleaning rules ·
[docs/model_card.md](docs/model_card.md) and [docs/project-evidence-index.md](docs/project-evidence-index.md) for
models and accepted runs · [docs/integration.md](docs/integration.md), [docs/security.md](docs/security.md),
[docs/monitoring.md](docs/monitoring.md) for deployment · [models/README.md](models/README.md),
[seed/README.md](seed/README.md), [frontend/src/synthetic/README.md](frontend/src/synthetic/README.md).

Licence: [MIT](LICENSE); the Ministry data and the evidence derived from it are not covered by it.
