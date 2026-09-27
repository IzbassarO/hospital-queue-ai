# ADR 0007: Committed release data: demo seed and released model modules

Status: Accepted
Date: 2026-09-26
Acceptance date: 2026-09-26
Owners: BizAI

## Context

Until this decision every row the product serves and every model it is built on lived only in gitignored locations:
`data/` (16 GB of raw Ministry of Health open-data files, obtained from the organisers), `data/processed/` (42 MB of
Parquet) and `artifacts/` (1.3 GB of checksummed run, model, tournament and publication output). Section 10 of
[`../architecture.md`](../architecture.md) made that a rule: model binaries, experiment output and datasets stay
out of the version-controlled product surface.

The rule was right for experiment output and it produced an empty product. A fresh `git clone` followed by `make up`
gave a migrated but empty PostgreSQL database; the UI answered "Опубликованная модель недоступна", the API
served nothing, and the only way to see the product was to obtain the raw data and run about eight hours of
pipelines. The
GovTech Camp evaluators (a CTO, NITEC engineers, inDrive engineers) clone the repository from GitHub and judge
production-integration readiness from what they can run. The trained models, which the pitch presents as a
deliverable, were not downloadable either: they existed only as reproducible artifacts on one laptop.

Three facts shaped the decision:

- The accepted publications are identified by content digests (`publication_identity_sha256`: `43da33ec…5cfd` for
  `operational-intelligence-slice5-final-test-2025-03-17-v1`, `e07be2f1…3c22` for
  `review-evidence-slice6-final-test-2025-03-17-v1`, `f504defe…39f5` for `model-assurance-6b5-v1`). Any copy that
  changes a byte is a different publication, so a committed copy must be byte-identical and verifiable.
- The ML core is frozen (6B.5). Nothing committed may change model science, configuration or accepted evidence.
- The organisers' clone must work with plain `git` and Docker. Git LFS, release assets and external object storage
  need a second tool, a token or a network step that a stranger's `git clone` does not perform.

## Decision

Commit two kinds of release data and treat them as products of the pipelines, never as sources.

1. **`seed/` — the demo seed** (30 MB on disk; budget 40 MB). It holds:
   - the three accepted publications as the exact published bytes: `model_assurance.json` as is,
     `operational_intelligence.json.gz` and `review_evidence.json.gz` gzipped without timestamp or file name.
     `manifest.json` records both the compressed and the decompressed (`raw_sha256`) digests and the publication
     identity; the loader verifies them and the publish services recompute the identities, so a seeded database
     serves the same `publication_identity_sha256` values as the machine the evidence was produced on;
   - the national serving tables as `tables/*.csv.gz` (`dim_*`, `ersb_snapshot`, `agg_daily_*`, `mart_*`,
     `model_registry`), all 20 regions;
   - a two-region facts slice (`fact_referral`, `pred_referral`, `pred_daily_forecast` for regions 62 and 59) so the
     legacy referral endpoints and the loader tests have real rows without the national fact tables.

   The seed is loaded by the backend CLI, `python -m app.cli load-seed --dir <seed>` (`backend/app/services/seed.py`):
   sha256 verification against `manifest.json`, `COPY` in foreign-key order inside one transaction, row-count check,
   refusal when the database already holds other data (`--replace` truncates only the seeded tables), then the three
   existing publish services. It never writes API keys, access logs or specialist decisions. `make demo` is the
   fresh-clone path: `make env` (a `.env` with generated secrets, kept if present) → `make up` → `docker compose
   --profile demo run --rm seed`. The one-shot `seed` service lives only in the `demo` compose profile, so plain
   `make up` never touches the data. The seed is rebuilt only by `tools/seed_bundle.py` (`make seed-build`) from the
   database and `artifacts/`; unchanged data rebuilds byte-identically.

2. **`models/` — the released model modules** (81.4 MB in 76 files; budget 90 MB, every file under 50 MB). One folder
   per frozen model (`wait_time`, `refusal_risk`, `load_forecast`, `patient_journey_aft`, `patient_journey_hazard`,
   `flow_quantile`) with the native model file copied byte for byte from its checksummed artifact (LightGBM
   `model*.txt`, XGBoost `model.json`), the feature contract as JSON (`features.json`, `categories.json`, `meta.json`,
   `metrics.json`, `inference.json` where the model has one), a standalone `predict.py` (CSV in → CSV out; `load()`,
   `from_bundle()`, `predict(df)`; depends only on lightgbm or xgboost, pandas and numpy), a `bundle.joblib`, an
   `example.csv.gz` with the `example_expected.csv.gz` the repository's own code path produced for it, and a
   README. `models/manifest.json`
   lists every file with size, sha256 and origin (`artifact (byte-identical)`, `generated`, `refit`, `hand-written`)
   plus per-model provenance (artifact path and digest, run ids, training window, library versions). **A file whose
   digest differs from the manifest is a different model.** The folder is rebuilt only by
   `ml/pipelines/export_models.py`; the `flow_quantile` boosters, which the accepted run did not persist, come from
   `ml/pipelines/export_flow_quantile_models.py`, a deterministic refit verified against the published raw quantiles
   before anything is written (maximum difference 0.0 on 47 782 cells) and therefore shipped without a joblib bundle.

3. **Release data is not evidence and not a source.** `artifacts/` remains the checksummed authority for models and
   publications and `data/` for inputs; both stay gitignored. `seed/` and `models/` are derived copies whose digests
   point back into `artifacts/`. Nothing in them is edited by hand, and a change in either folder is a change in a
   pipeline output, reviewed as such.

## Dependency rules

- `seed/` and `models/` are written only by `tools/seed_bundle.py`, `ml/pipelines/export_models.py` and
  `ml/pipelines/export_flow_quantile_models.py`. Hand edits, including "small fixes" to a JSON file, are forbidden;
  `ml/tests/test_models_release.py` and the seed loader's digest checks turn them into failures.
- Committing release data changes no science: `ml/configs/`, `ml/hqai_ml/`, the accepted runs and the published
  identities are untouched. The identities `43da33ec…5cfd`, `e07be2f1…3c22` and `f504defe…39f5` must stay
  identical after a load from `seed/`; the CI job `demo-seed` and `backend/tests/test_seed_smoke.py` check them.
- The backend loads the seed through its own CLI and the existing publish services; it still does not import
  `hqai_ml` (ARCH001). `models/*/predict.py` import nothing from the repository; the release tests run them as
  subprocesses with no repository code on the path.
- Size budgets: `seed/` at most 40 MB, `models/` at most 90 MB, no single file over 50 MB (GitHub's warning threshold),
  so the repository stays clonable with plain `git` and no LFS pointer files.
- The compose `seed` service stays in the `demo` profile. `make up`, `make migrate`, the backend image entrypoint and
  the pipelines never load the seed implicitly; `make marts` on a seeded database is documented as "do not" because it
  would rebuild the national marts from the two-region slice.
- `.gitignore` keeps `artifacts/`, `data/`, `reports/`, `scratch/` ignored and un-ignores exactly `seed/**` and
  `models/**`; `tools/audit.py` lists both directories in its layout allow-list and skips files over 4 MB in its
  secrets scan instead of decompressing bundles.

## Alternatives considered

- **Keep everything out of git (status quo).** Rejected. A clone showed an empty product, which fails the mandatory
  "locally reproducible demo" requirement and gives the evaluators nothing to run.
- **Git LFS for the bundles and models.** Rejected. A clone without `git-lfs` installed receives pointer files, `make
  demo` then fails on a sha256 mismatch with a confusing message, and GitHub LFS bandwidth quotas apply to every
  evaluator's clone. The whole payload is about 111 MB, which plain git handles.
- **GitHub release assets or an object store, downloaded by `make demo`.** Rejected. It adds a network step, a URL
  that must outlive the camp, and a second place where identities must be verified; the evaluators' clone must work
  offline once cloned.
- **Ship the database as a `pg_dump`.** Rejected. A dump binds the demo to one PostgreSQL major version and one schema
  revision, cannot be diffed, and bypasses Alembic and the publish services whose identity recomputation is the
  point. CSV per table plus the published JSON keeps every row reviewable in `git diff`.
- **Commit the national fact tables too.** Rejected on size (hundreds of MB) and need: the product reads serving
  tables and publications, not facts; a two-region slice covers the legacy endpoints and the loader tests.
- **Commit only the three publications, rebuild the tables in the container.** Rejected. Rebuilding aggregates and
  marts needs the raw data or the national facts, which is what the seed avoids.
- **Smaller XGBoost file (`.ubj`).** Rejected for now. UBJSON saves 3 % (34.1 MB vs 35.2 MB) but breaks the byte
  identity between the released file and its checksummed artifact.
- **Retrain the flow quantile boosters at load time.** Rejected. It would need `data/processed/` and three minutes
  of CPU inside the demo, and would move a refit out of the verified export pipeline.

## Consequences

### Positive

- `git clone` + `make demo` shows the whole product for all 20 regions with the accepted publications, on Docker
  alone, in a few minutes; the numbers on screen equal the numbers in the model passport and the presentation
  because the identities are recomputed from identical bytes.
- The models are downloadable modules with a stated contract, an example and a digest; an integrator can score a CSV
  without cloning the repository or installing it.
- Release data is diffable and reviewable: unchanged data rebuilds byte-identically, so a pull request shows only real
  changes.
- CI proves the path on every push: `demo-seed` loads the seed into a fresh PostgreSQL and smoke-tests row counts,
  identities and key endpoints; `make ml-test` reproduces every example through `predict.py` and the joblib bundles.

### Negative

- The repository grows by about 111 MB and every future refresh of the seed or the models adds that much history
  again; the budgets above cap one version, not the history. A history rewrite is not planned; if the growth becomes
  a problem the answer is a new ADR, not a silent move to LFS.
- The seed fixes the product at the retrospective final-test origin 2025-03-17 and the data cut 2025-03-31. It is a
  demonstration of the accepted evidence, not live data; the UI says so through the published-origin lead and the
  freshness fields.
- Two copies of the model files exist (artifact and release); the manifests tie them together, and the release tests
  fail if they drift, but reviewers must remember that `artifacts/` is the authority.
- `bundle.joblib` is a Python pickle bound to the lightgbm/xgboost major versions it was built with; the native files
  are the portable form and are the ones whose digests the release contract protects.
- The `flow_quantile` release is a verified refit rather than an artifact copy, which is disclosed in its README and
  in the manifest origin field.

## Migration

1. Build `seed/` with `tools/seed_bundle.py` from the database that served the accepted publications; confirm the
   rebuild is byte-identical and the loaded identities match (done 2026-09-26).
2. Build `models/` with `ml/pipelines/export_models.py` and the quantile refit; confirm `make ml-test` passes and the
   artifact copies are byte-identical (done 2026-09-26).
3. Add the `demo` compose profile, `make env`/`make demo`, the `load-seed` CLI, the CI job `demo-seed`, the
   `.gitignore` negations and the audit allow-list (done 2026-09-26).
4. Commit both folders together with this ADR; the user performs the commit.
5. Refresh: after a new accepted publication or a new promoted model, rerun the builder or the export pipeline,
   review the `git diff` of the manifests (only the changed files may differ), rerun `make ml-test` and the seed
   smoke test, and commit the release data with the pipeline change that produced it. Never edit a shipped file.

## Verification

- `backend/tests/test_seed_smoke.py` (with `HQAI_SEED_SMOKE=1`, run by the CI job `demo-seed` after `load-seed` into a
  fresh PostgreSQL): row counts per table, the three publication identities, the overview, signals, model-assurance,
  review-evidence and dictionary endpoints.
- `ml/tests/test_models_release.py` (part of `make ml-test`): the manifest matches the folder, artifact copies are
  byte-identical to their checksummed artifacts, and `predict.py` run as a subprocess plus the joblib bundle both
  reproduce `example_expected.csv.gz` within 1e-6.
- `tools/seed_bundle.py` and `ml/pipelines/export_models.py` are deterministic: rerunning them on unchanged inputs
  changes no data file (manifest `built_at` excepted for the seed).
- `make audit`: the layout gate accepts `seed/` and `models/`, the secrets gate skips files over 4 MB, ARCH001–ARCH005
  are unchanged.
- Size: `du -sh seed models` stays within 40 MB and 90 MB; `models/manifest.json` records `total_bytes`.

## Revisit when

Revisit when a live data feed replaces the retrospective origin (the seed then becomes a test fixture rather than the
demo content), when a refresh cadence makes repository growth measurable, when the customer's hosting provides an
artifact registry that its own operators prefer, or when a model file exceeds 50 MB. Any of these creates a new ADR;
none of them moves release data to LFS or an external store without one.
