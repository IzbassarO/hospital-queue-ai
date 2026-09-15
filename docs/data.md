# Data layer

What the ingest pipeline (`make ingest` → `ml/pipelines/ingest.py`) reads, how it cleans it, and
what every table and column means. Profiling of the raw files: `reports/00_inventory.md`.
Parameters referenced below (`window_start`, …) live in `ml/configs/ingest.yaml`.

Contents: [1 Sources](#1-sources) · [2 Cleaning rules](#2-cleaning-rules) ·
[3 Dictionaries](#3-dictionaries) · [4 Facts](#4-facts) · [5 Aggregates](#5-daily-aggregates) ·
[6 Load](#6-parquet-and-postgres-load) · [7 Known limitations](#7-known-limitations)

---

## 1. Sources

All files are Ministry of Health open data in `data/raw/` (read-only for every script).

| # | folder | content | used for | grain |
|---|---|---|---|---|
| 1 | `1 dataset` | Referrals for planned hospitalization (IS BG), 3 CSV parts | `fact_referral`, dictionaries | one referral (registrations 2025-01-01 … 2025-03-31) |
| 2 | `2 dataset` | "Patients waiting for planned hospitalization" (IS BG) | only the list of `region_origin_code` values for `dim_region` | one referral |
| 3 | `3 dataset` | Refusals of hospitalization at the admission unit (IS BG), 6 CSV parts | `fact_admission_refusal`, region vote | one refusal event (2025-01-01 … 2025-03-31) |
| 4 | `4 dataset` | Treated cases per medical organization (ERSB) | `ersb_snapshot`, hospital capacity proxy | one organization, no period column |
| 5–8 | | vaccination, oncology | not ingested yet (secondary) | |

Why dataset 2 is not a fact table: every one of its rows matches a dataset-1 referral via
`region_origin_code.mo_destination_code.profile_code.patient_seq_no = hospitalization_code`, over the
same registration window, and ~99% of those referrals already have an outcome in dataset 1. It is the
same cohort with coded columns, not a current waiting list.

### Source validation (`sources.py`)

Every CSV part must (1) be non-empty, (2) not be an XML error body (failed S3 download),
(3) have exactly the expected header, (4) end with a newline. Invalid parts are **skipped, not
fatal**, and listed in `data/processed/_manifest.json` and in section 0 of `reports/01_baseline.md`.
Parts are read with DuckDB `read_csv` (header, `,` delimiter, `"` quote/escape, all columns VARCHAR),
then typed explicitly with `CAST` so that an unparseable value fails the run instead of silently
becoming NULL.

---

## 2. Cleaning rules

### 2.1 Text (`clean`)

Applied to every text field: all whitespace runs (incl. NBSP, narrow/figure spaces, BOM) → one
space; trim; empty string → NULL. Codes (`icd10_code`) are additionally upper-cased.

### 2.2 Organization and region names (`normalize.py`)

Applied to `referring_mo`, `hospital_mo` (ds1), `org_in`, `attach_org`, `region_in`,
`attach_region` (ds3) and `medicine_organization` (ds4). Computed once per distinct spelling
(table `name_map`: `raw → name, key`) and joined back.

| step | rule | example |
|---|---|---|
| 1 | `clean` (whitespace, trim) | `"  ТОО  Х "` → `ТОО Х` |
| 2 | unify quotes: `« » „ “ ” ‟ ″ ＂` → `"`, `‘ ’ ‚ ‛ \` ´` → `'` | `ТОО «МЕD»` → `ТОО "МЕD"` |
| 3a | Latin homoglyphs inside a Cyrillic word → Cyrillic: `O C A E H P K M T X B a c e o p x` | `Oбласть` → `Область`, `РУДHЕHСКИЙ` → `РУДНЕНСКИЙ` |
| 3b | a word whose Latin letters are not all look-alikes but whose Cyrillic letters are → Latin | `МЕD` (Cyrillic М, Е) → `MED` |
| 4 | `clean` again | |

A word that contains non-look-alike letters of both alphabets (e.g. `МЕDИКЕР`) is left unchanged.

**Matching key** (`name_key`) = normalized name, case-folded, `ё → е`, every non-word character
(quotes, `№`, punctuation) → space, collapsed. Used for all exact name matches.

**Core key** (`core_key`, fuzzy matching only) = `name_key` with diacritics removed (`ẏ → y`,
`й → и`) and legal-form/administrative words removed (`товарищество`, `ограниченной`,
`ответственностью`, `государственное`, `коммунальное`, `предприятие`, `на праве хозяйственного
ведения`, `управления здравоохранения`, `акимата`, `области`, `города`, … — full list
`LEGAL_FORM_STOPWORDS` in `normalize.py`). Without this, boilerplate dominates the score and
unrelated organizations match.

### 2.3 Dates

- All timestamps are stored as `TIMESTAMP` without time zone, exactly as in the source (local time).
- `planned_dt` outside **[`planned_dt_min`, `planned_dt_max`] = [2024-06-01, 2026-06-30]** is a
  placeholder (1900-01-01, 1970-01-01, far future) and set to NULL; the original stays in `planned_dt_raw`.

---

## 3. Dictionaries

### `dim_region` — region code → name

Codes: the distinct `region_origin_code` of dataset 2 (20 values; same set as part 1 of
`hospitalization_code`). Part 1 of the code is the patient's **region of origin**, not the hospital's:
415 of 1 406 hospital codes receive referrals under several prefixes.

**Majority vote, weighted by referrals.** Every dataset-1 referral with code *C* votes for the
dataset-3 `region_in` of its hospital (hospital name matched on `name_key`; a hospital's dataset-3
region is its most frequent `region_in`). The name with most votes wins. Weighting by referrals is
essential: one vote per hospital maps e.g. 19 (Almaty region) to Almaty city, because many
Almaty-region patients are treated in city hospitals. With referral weighting all 20 codes map to
20 distinct regions consistent with the KATO classifier.

`ml/configs/regions.yaml` is written on every run and is the place to review and fix the mapping:
set `name` + `manual_override: true` to pin a name; add historical spellings to `aliases`.

| column | meaning |
|---|---|
| `region_code` | 2-digit code (PK) |
| `region_name` | name used by the pipeline (vote winner, or manual override) — spelled as in dataset 3 |
| `vote_region_name` | vote winner |
| `vote_share` | winner's share of referral votes |
| `vote_referrals` | number of referrals that voted |
| `runner_up_name`, `runner_up_share` | second-best name |
| `is_ambiguous` | `vote_share < region_vote_min_share` (0.8) — review in `regions.yaml` |
| `manual_override` | name comes from `regions.yaml`, not from the vote |

Region names of dataset 3 (`region_in`, `attach_region`) map to codes through `region_lookup`
(`name_key` of `region_name` and of every alias).

### `dim_profile` — bed profile code → name

Codes: part 3 of `hospitalization_code` (= dataset 2 `profile_code`, e.g. `021`, `381`, `DH`).
Name = most frequent `bed_profile` of dataset 1 among referrals with that code. Code **`DH`**
(`day_hospital_code`) has no `bed_profile` in the source and is named `Дневной стационар`
(`day_hospital_name`).

| column | meaning |
|---|---|
| `profile_code` | PK |
| `profile_name` | majority `bed_profile`; `Дневной стационар` for DH |
| `name_share` | share of the majority name among named referrals (NULL for DH) |
| `n_referrals` | referrals with this code |
| `is_day_hospital` | code = DH |

### `dim_organization` — hospital code → hospital

Codes: part 2 of `hospitalization_code` (= dataset 2 `mo_destination_code`). Part 2 identifies the
**receiving hospital** (each code maps to exactly one `hospital_mo` name). Referring organizations
have no code.

| column | meaning |
|---|---|
| `org_code` | PK |
| `org_name` | most frequent normalized `hospital_mo` for the code |
| `org_key` | `name_key(org_name)` |
| `region_code` | the hospital's own region: dataset-3 `region_in` of the same hospital (via `org_key`) if it appears there, else the most frequent origin prefix of its referrals |
| `region_method` | `admission_refusals_region` or `majority_origin_prefix` |
| `n_referrals` | referrals in dataset 1 |
| `n_origin_regions` | distinct origin region prefixes among its referrals |
| `ersb_id` | matched dataset-4 row (`ersb_snapshot`), NULL if unmatched |
| `match_score` | 100 for exact matches; `token_set_ratio` for fuzzy matches; NULL for manual decisions |
| `match_method` | `exact`, `fuzzy`, `manual` (decided in `ml/configs/org_matches.yaml`; `ersb_id` is NULL for a manual reject), or NULL (unmatched) |

**ERSB matching:**

1. **exact** — equal `name_key`. If several ERSB rows share the key (dataset 4 has a few duplicate
   names), the row with the largest `discharged_total` wins.
2. **fuzzy** — only when there is no exact match, computed on **core keys** (2.2) with rapidfuzz.
   Candidates need `token_set_ratio ≥ fuzzy_min_score` (90). A candidate is **accepted only if** both
   names contain the same number tokens (`№14` ≠ `№15`) **and** `token_sort_ratio ≥ fuzzy_min_sort_score` (90).
   `token_sort_ratio` rejects subset matches (`Шалкарская районная больница` vs `Шалкарская районная
   туберкулезная больница`) that `token_set_ratio` scores 100. The best accepted candidate wins
   (highest sort, then set score).
3. otherwise unmatched (NULL).
4. **manual overrides** from `ml/configs/org_matches.yaml` are applied last (see below).

On the first run plain `token_set_ratio ≥ 90` on full names produced 17 fuzzy matches, of which
about 11 were different organizations; the guarded rule accepts 6, all correct on manual review.
`reports/01_org_matching.csv` lists every accepted fuzzy match and, for unmatched hospitals, the best
rejected near-miss with the reason (`decision`, `reject_reason`, both scores).

#### Manual overrides: `ml/configs/org_matches.yaml`

Hand-maintained and versioned in git, the counterpart of `regions.yaml` for hospital ↔ ERSB matching.

```yaml
accept:
  - {org_code: '028V', ersb_id: 792, note: "why this is the same organization"}
reject:
  - {org_code: 'XXXX', ersb_id: 123, note: "why this is not"}
```

| rule | effect |
|---|---|
| `accept` org_code → ersb_id | sets that ERSB row, whatever the automatic result was (exact, fuzzy, rejected near-miss or none); `match_method = manual`, `match_score = NULL` |
| `reject` org_code → ersb_id | if the automatic matching produced exactly this pair, the hospital becomes unmatched (`ersb_id = NULL`, `match_method = manual`); there is no fallback to the next candidate. If the pair was not produced, the entry is kept as a guard and listed under `manual_rejects_not_triggered` in `_manifest.json` |
| precedence | manual decisions always win over automatic ones (accept over automatic reject, reject over automatic accept) |
| validation | the run stops if an `org_code` or `ersb_id` does not exist, if one org_code is accepted for two different ERSB rows, or if the same pair is both accepted and rejected |

`org_code` must be quoted (YAML would read `0286` as the number 286). Manual decisions appear in
`reports/01_org_matching.csv` with `decision = manual_accept / manual_reject` and the `note` as
`reject_reason`. `ersb_snapshot.org_code` then follows the manual result.

Seeded entry: `028V` → ERSB 792 — the same Almaty clinic, spelled `"Городская поликлиника № 4" …
Управления общественного здравоохранения` in dataset 1 and `"Городская поликлиника №4" … Управления
общественного здоровья` in ERSB; the automatic rule rejected it (`token_sort_ratio` 87 < 90).

### `dim_icd` — ICD-10 code → name

There is no official ICD-10 dictionary in the open data. `dim_icd` keeps, for every code that appears in dataset 1
(`diagnosis_name`) or dataset 3 (`icd_name`), the most frequent spelling across both sources (ties: the first spelling in sort order).

| column | meaning |
|---|---|
| `icd10_code` | PK, upper-case as in the facts (`O80.0`, `M42.1`, `O99`) |
| `icd10_name` | most frequent name spelling |
| `name_share` | share of named rows of the code that use that spelling (1.0 = all agree) |
| `n_referrals` | dataset-1 referrals with the code (0 for codes seen only in dataset 3) |

Used by the API for `diagnosis_name` on referrals and for names of 3-character codes in explanations.

### Deterministic majority votes

Every "most frequent value" in the dictionaries (`dim_profile.profile_name`, the region vote, `dim_organization`
name, key and region) uses `arg_max(value, struct(count, value))`: on equal counts the value later in sort order wins, so every
`make ingest` produces the same dictionaries. Before step 6 a plain `arg_max(value, count)` picked an arbitrary one of
the tied values; 5 hospitals have tied region-prefix votes, and two ingests assigned two of them to different
regions (Акмолинская → г. Астана, Жамбылская → Алматинская область), which moved a few region-level counts (e.g.
ZIQ9 × 241 is now «место 1 из 245» instead of 244).

### `ersb_snapshot` — dataset 4

| column | meaning |
|---|---|
| `ersb_id` | row number in the source file (PK) |
| `org_name`, `org_key` | normalized organization name and matching key |
| `discharged_total`, `discharged_children`, `treated_budget`, `treated_paid`, `discharged_within_day`, `deaths_total`, `bed_days` | as in source (INTEGER) |
| `amount_to_pay` | as in source, `NUMERIC(20,2)` |
| `avg_length_of_stay` | **derived**: `bed_days / discharged_total`; NULL if `discharged_total = 0` |
| `org_code` | best matching `dim_organization` code (highest `match_score`, then most referrals); NULL if no hospital matched |
| `n_matched_org_codes` | how many hospital codes matched this ERSB row |
| `sdu_load_date` | as in source |

The snapshot has no period column. `treated_budget + treated_paid` does not equal
`discharged_total` for most rows; the column semantics need confirmation from the data owner.

---

## 4. Facts

### `fact_referral` — dataset 1, one row per referral (767 130 rows)

Rows with a repeated `hospitalization_code` are **kept** and flagged.

| column | source / derivation |
|---|---|
| `referral_id` | surrogate PK, `row_number()` ordered by code, registration, outcome dates, referring org, diagnosis (stable across runs) |
| `hospitalization_code` | as in source |
| `region_code` | code part 1 — patient's region of origin (FK `dim_region`) |
| `org_code` | code part 2 — receiving hospital (FK `dim_organization`) |
| `profile_code` | code part 3 — bed profile (FK `dim_profile`) |
| `seq_no` | code part 4 (sometimes with a letter suffix, e.g. `72S`) |
| `is_dup_code` | the same `hospitalization_code` occurs on more than one row |
| `hospital_region_code` | `dim_organization.region_code` of `org_code` |
| `referring_mo`, `hospital_mo` | normalized names (2.2) |
| `icd10_code` | `icd10_ref_diag_code`, trimmed, upper-case |
| `diagnosis_name`, `bed_profile`, `territorial_type`, `referral_purpose`, `finance_source` | cleaned text (2.1) |
| `registration_dt`, `polyclinic_dt`, `hospitalization_dt`, `refusal_dt`, `sdu_load_date` | as in source |
| `planned_dt_raw` | `planned_dt` as in source |
| `planned_dt` | `planned_dt_raw`, NULL if outside [2024-06-01, 2026-06-30] |
| `planned_dt_out_of_range` | `planned_dt_raw` was set to NULL by that rule |
| `outcome` | `hospitalized` if `hospitalization_dt` is set; else `refused` if `refusal_dt` is set; else `open` |
| `outcome_conflict` | both `hospitalization_dt` and `refusal_dt` are set (treated as hospitalized) |
| `registration_date` | `date(registration_dt)` |
| `registration_weekday` | ISO weekday of `registration_date` (1 = Monday … 7 = Sunday) |
| `planned_week` | Monday of the week of `planned_dt` (NULL if `planned_dt` is NULL) |
| `hospitalization_date`, `refusal_date` | dates of the timestamps |
| `resolution_date` | the date the referral left the queue: `hospitalization_date` for hospitalized, `refusal_date` for refused, NULL for open |
| `wait_days` | hospitalized only: `max(hospitalization_date − registration_date, 0)` in days |
| `wait_to_refusal_days` | refused only: `max(refusal_date − registration_date, 0)` |
| `same_day_registration` | `hospitalization_dt < registration_dt + 1 day` (admitted within 24 h of registration, or registered after admission); false if not hospitalized |
| `retro_registration` | `hospitalization_dt < registration_dt` (referral registered after the admission) |
| `planned_lag_days` | `date(planned_dt) − registration_date` (NULL when `planned_dt` is NULL) |

### `fact_admission_refusal` — dataset 3, one row per refusal (1 508 732 rows)

| column | source / derivation |
|---|---|
| `refusal_id` | surrogate PK, ordered by `refuse_dt`, part, org, diagnosis, attached org, amount |
| `source_part` | the "Часть N из 6" number of the source file |
| `region_in` | normalized hospital region name |
| `region_code` | `region_in` → `dim_region` via `region_lookup` |
| `org_in` | normalized hospital name |
| `org_code` | hospital code: `dim_organization` rows with the same `org_key`; if several, the one in the same `region_code`; if still ambiguous, the one with most referrals. NULL if the hospital does not occur in dataset 1 (e.g. infectious-disease hospitals, ~1% of rows) |
| `org_match_method` | `exact` (one candidate), `exact_region` (disambiguated by region), `exact_ambiguous`, NULL |
| `resident`, `insured`, `benefit_cat`, `finance_src`, `icd_name` | cleaned text |
| `refuse_dt` | as in source |
| `refuse_date` | `date(refuse_dt)` |
| `attach_region`, `attach_org` | normalized names of the patient's attachment region / primary-care organization |
| `attach_region_code` | `attach_region` → code (historical names like `Южно-Казахстанская область` stay NULL unless added as `aliases`) |
| `icd10_code` | `icd10`, trimmed, upper-case |
| `amount` | `NUMERIC(14,2)` |
| `sdu_load_date` | as in source |

Dataset 3 is ~26× larger than the refusals recorded in dataset 1 for the same period: it covers
**all** admission-unit refusals, not only planned referrals. Do not treat it as the refusal outcome
of `fact_referral`.

---

## 5. Daily aggregates

Materialized tables over the calendar window **[`window_start`, `window_end`] = [2025-01-01, 2025-03-31]**.

### `agg_daily_hospital_profile` — (date, org_code, profile_code), dense

One row for every date in the window × every (org_code, profile_code) pair that has referrals —
also on days with no events.

| column | derivation |
|---|---|
| `date`, `org_code`, `profile_code` | PK |
| `region_code` | the hospital's region (`dim_organization.region_code`) |
| `registrations` | referrals with `registration_date = date` |
| `hospitalizations` | referrals with `outcome = 'hospitalized'` and `hospitalization_date = date` |
| `refusals` | referrals with `outcome = 'refused'` and `refusal_date = date` |
| `queue_length` | referrals **waiting at the end of `date`**: `registration_date ≤ date` and not resolved by then (`resolution_date > date`, or open) |

`queue_length` is computed as a running sum: +1 on `registration_date`, −1 on
`greatest(resolution_date, registration_date)` for resolved referrals (open referrals never leave),
plus the carry-in of referrals registered before `window_start` and still waiting. The `greatest()`
keeps referrals registered after their admission (`retro_registration`) out of the queue entirely.

**Warm-up / left censoring.** The source has no referrals registered before 2025-01-01, so the
queue starts near zero and fills up during January. 90% of referrals leave the queue within about
a month, so levels are usable from early February (the baseline computes this date), but they
remain a lower bound. Trends need correcting for the history that is still missing; the baseline
does this in section 6.

### `agg_daily_region_profile` — (date, region_code, profile_code), dense

Sum of `agg_daily_hospital_profile` over hospitals, grouped by the **hospital's** region
(`dim_organization.region_code`), not the patient's origin region. Same four metrics.

### `agg_daily_admission_refusals` — (date, org_code), sparse

`refusals` = rows of `fact_admission_refusal` per `refuse_date` and `org_code`, with `region_code`
of the hospital. Only days with at least one refusal; rows without `org_code` are excluded (counted
in the baseline sanity checks).

---

## 6. Parquet and Postgres load

1. Everything is built in a temporary DuckDB database (`data/processed/_work.duckdb`, memory limit
   `DUCKDB_MEMORY_LIMIT`, spills to disk) and written to `data/processed/<table>.parquet` (zstd).
   The DuckDB file is deleted after the run.
2. `data/processed/_manifest.json` records: parameters, files used/skipped per dataset, row counts,
   dictionary statistics, Postgres load timings.
3. Load (`load_postgres.py`): one transaction — `TRUNCATE` all tables, then per table (FK order)
   stream Parquet → Arrow batches → CSV → `COPY`, check `count(*)` equals the Parquet row count,
   `ANALYZE`, commit. Any error rolls back and the previous data stays intact.

The schema (types, PKs, FKs from facts to dimensions, indexes on date, org_code, region_code,
profile_code) is Alembic migration `backend/alembic/versions/0001_initial_data_layer.py`, generated
from and checked against `backend/app/db/models.py` (`alembic check`).

---

## 7. Known limitations

- **3 months of registrations** (Q1 2025): no seasonality; queue levels are lower bounds (section 5).
- **Region codes 19 and 79** have ambiguous votes (Almaty region ↔ Almaty city, Shymkent ↔ Turkestan
  region patient flows); the mapping matches KATO but should be confirmed in `regions.yaml`.
- **No BIN / organization IDs** anywhere: hospitals are linked across datasets by name only.
- **ERSB period unknown**: throughput proxies assume one year.
- **`hospital_region_code` for ~2/3 of hospitals** comes from the majority origin prefix (they are
  absent from dataset 3) — correct for local hospitals, may be wrong for national centres.
