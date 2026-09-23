# Production Slice 5 — real evidence publication

This is an offline projection/publication of frozen evidence, not a new ML experiment. No fitting, calibration, HPO, candidate selection, scenario execution or decision-alternative acceptance run was performed.

## Preconditions

Started with a clean tree at `7507658c1b8f23bcf684f1764946a0414a9d8162`. [Slice 4 CI run 35806892683](https://github.com/IzbassarO/hospital-queue-ai/actions/runs/35806892683) completed successfully. Local Slice 4 checks passed (67 frontend tests, lint, typecheck). PostgreSQL was at migration 0008 with zero assurance/operational snapshot and child rows.

## Builder and publication scope

`tools/operational_bundle.py`, exposed as `make operational-intelligence-bundle`, reads only explicitly named accepted evidence. It validates the pinned Model Assurance identity, all 13 capability run references, the eight accepted chain runs, their scientific/data/config/code/artifact identities, summary checksums, selected evaluation checkpoint identities and all files in those evaluation artifacts. It rejects missing files, changed hashes, unaccepted runs, mixed upstream lineage, unsupported status vocabulary, duplicate/incomplete 14-day series, and changed/partial canonical ranks.

The builder imports the backend-owned input schema/parser offline. Runtime backend code neither imports the builder/ML package nor reads ML artifacts. Publication continues through the existing `app.cli` commands; no database schema or runtime dependency was added.

The explicit publication origin is **2025-03-17**, the accepted final-test origin, not a newest-directory lookup. All forecast subjects, both targets, all three levels and every horizon 1–14 from that origin are retained. Other accepted validation origins remain offline. This is a complete final-test-origin projection, not a sample selected to improve the demo.

Signals copy the four frozen product views: primary Inbox, data-quality, low-volume attention and flagged observed anomalies. Primary ranks remain unchanged. Other views retain null Inbox rank and are not promoted into the primary rank sequence. Secondary cohort research-only signals and normal registrations are not fabricated into warnings. Scenario/decision-alternative runs are verified for lineage/assurance but never projected as recommendations or operational actions.

Status mapping only translates frozen vocabulary into the existing product enums: supported/limited_history/no_history → DIRECT_SUPPORTED/FALLBACK_LIMITED/UNSUPPORTED; regional fallback stays REGION_PROFILE_FALLBACK. A supported aggregate with an explicit proxy fallback is FALLBACK_LIMITED rather than falsely direct. Original labels are retained in evidence facts. Observed-anomaly support refers to its accepted robust historical reference, not calibrated forecast support. No thresholds, severity, rank, ratios, materiality or calibrated values are recomputed.

Raw model quantiles are copied unchanged, including negative/crossed unrepaired values. National historical region-quantile sums are retained verbatim as labelled evidence facts, with `raw_quantiles=null` and no calibrated interval: these sums are not national predictive quantiles. Source `__region__`/`__national__` sentinels become null hospital/region identifiers at aggregate levels; no hospital names or physical-capacity data are invented. Central values and level-local calibrated 80% intervals remain distinct.

`generated_at=null` avoids audit-time nondeterminism; PostgreSQL records actual publication time separately. Output keys/rows have stable order and canonical hashes. A second complete build verified byte-identical bundle and report files. Existing outputs cannot silently be overwritten with different content.

## Product defects demonstrated and fixed

- **P1 publication compatibility:** the original product validator incorrectly required raw quantiles to be nonnegative and ordered and every central forecast to lie within its separately retained calibrated interval. The final-test artifact contains 23,111 raw crossing rows and 9,171 central values outside the retained intervals. Repairing them in the builder would change accepted science. Raw values now need only be finite; calibrated bounds still must be nonnegative and ordered. Publication preserves 53,383 negative raw-p10 rows (national proxy values are separately labelled). OpenAPI was regenerated; generated TypeScript remained byte-identical.
- **P2 mobile layout:** the real reason code `CALIBRATED_LOWER_EXCEEDS_HISTORICAL_FLOW_THRESHOLD` overflowed a 375px screen. Evidence lists now wrap long tokens without altering or hiding them. This was reproduced in real Chrome, not inferred from fixtures.

## Frozen source identities

Assurance: `model-assurance-6b5-v1` / `f504defefdd87bcbb01c670b68469ba4c0e016be7f40ca89452baf69b73f39f5`.

| Source run | Scientific SHA256 | Assured summary artifact SHA256 |
| --- | --- | --- |
| `decision-alternatives-6b4-real-v3` | `fb7410fa230d4c252c58cbbe98e4ccfbe45102800d5422ba45f8ce79d788a7a8` | `4c7924e1a849f9d9396f8ea0443d918ab595aa64f1e72d5ffae0a76a5cbe1a4a` |
| `flow-calibration-6b2b2b-real-v1` | `e436f3b6f18f98e29992f481e37ffe30bee9c5ef87583f05d9206f8793a993bc` | `03a8157565a9fc6e9cf0c2f0d6b0337cbef363c9cfbcd54979dccd6905189b08` |
| `flow-evidence-6b2b1-corrected-v3` | `e1c041f65998d0fd5ed5ead4c906b4caf821e29a1ca1ef06143f9e0eff005150` | `5acc3bed21302f6b5b9fe39b931a3ec188f40adff03d4ceda4cf63754a2660b5` |
| `flow-hierarchy-6b2b3-real-v1` | `73b5514a97b7166e2423c5aaef797b65be358cb4e672e1e660410dba7d498406` | `d3ef9c4072f18eea9e8cd6c49dd4e696ed6adde61eb5029b5f094b34c31b5d11` |
| `flow-pressure-6b2c1-real-v2` | `f0439d2d256b576329a6255e1dd53c81f8ab9d5338d70bfeb655e2e3b092549a` | `e7a6e5d3475c5a836a8d008f2bd70fd59533a7361d690eee02fcc09c113abf80` |
| `flow-quantile-6b2b2-real-v1` | `f55dff24f115e23d2d0510dc230d0a0e89d4fa43d36daa55c078d00ffa44ddde` | `8685fec7d0e89534ec2ef91c662b38a81279daf8fe85c458787f8ad1fae51f40` |
| `flow-scenario-6b3-real-v1` | `483dd631ce27d02e351db5b8b8f1e7ac0325bf789c9f35daf897560dbcf51098` | `013445cbe4ca868e4552323bdea743bc0d56fa2ff304a4bc51304e5208119382` |
| `signal-prioritization-6b2c2-real-v2` | `103338a51e0907a8694abcdcabca37c84b55d5f9c440df9ad3bcd209a1d7c507` | `090ed11ac64d366651ca4425c1650a9cea5566dc69fd6fb40fb2660dbc0343b1` |

Full dataset/config/code identities and individual file hashes are retained in the generated `build-report.json`; they were matched against Model Assurance, not calculated from the current ML source tree.

## Exact frozen files consumed or integrity-checked

The builder reads the run manifests and summaries below to validate lineage. It projects values from `selected-central-forecast.parquet` and four prioritized `views/*.parquet` files; other evaluation files are checksum-verified only. It never invokes their generating pipelines.

```text
artifacts/decision_alternatives/decision-alternatives-6b4-real-v3/summaries/decision-alternatives-summary-1c8d8bec472d/artifact-manifest.json
artifacts/decision_alternatives/decision-alternatives-6b4-real-v3/summaries/decision-alternatives-summary-1c8d8bec472d/summary.json
artifacts/flow_calibration/flow-calibration-6b2b2b-real-v1/summaries/temporal-calibration-summary-6fb1dbb0bde0/artifact-manifest.json
artifacts/flow_calibration/flow-calibration-6b2b2b-real-v1/summaries/temporal-calibration-summary-6fb1dbb0bde0/summary.json
artifacts/flow_forecast/flow-evidence-6b2b1-corrected-v3/summaries/evidence-summary-c0f773dd1120/artifact-manifest.json
artifacts/flow_forecast/flow-evidence-6b2b1-corrected-v3/summaries/evidence-summary-c0f773dd1120/summary.json
artifacts/flow_hierarchy/flow-hierarchy-6b2b3-real-v1/evaluation/central-hierarchy-ac2f3e0e6813/alternative-analysis.json
artifacts/flow_hierarchy/flow-hierarchy-6b2b3-real-v1/evaluation/central-hierarchy-ac2f3e0e6813/artifact-manifest.json
artifacts/flow_hierarchy/flow-hierarchy-6b2b3-real-v1/evaluation/central-hierarchy-ac2f3e0e6813/metadata.json
artifacts/flow_hierarchy/flow-hierarchy-6b2b3-real-v1/evaluation/central-hierarchy-ac2f3e0e6813/selected-central-forecast.parquet
artifacts/flow_hierarchy/flow-hierarchy-6b2b3-real-v1/summaries/hierarchy-summary-14cf7d35b1e7/artifact-manifest.json
artifacts/flow_hierarchy/flow-hierarchy-6b2b3-real-v1/summaries/hierarchy-summary-14cf7d35b1e7/summary.json
artifacts/flow_pressure/flow-pressure-6b2c1-real-v2/evaluation/preventive-flow-pressure-fde9cfdb99b9/artifact-manifest.json
artifacts/flow_pressure/flow-pressure-6b2c1-real-v2/evaluation/preventive-flow-pressure-fde9cfdb99b9/daily-pressure-signals.parquet
artifacts/flow_pressure/flow-pressure-6b2c1-real-v2/evaluation/preventive-flow-pressure-fde9cfdb99b9/entity-pressure-signals.parquet
artifacts/flow_pressure/flow-pressure-6b2c1-real-v2/evaluation/preventive-flow-pressure-fde9cfdb99b9/metadata.json
artifacts/flow_pressure/flow-pressure-6b2c1-real-v2/evaluation/preventive-flow-pressure-fde9cfdb99b9/observed-flow-anomalies.parquet
artifacts/flow_pressure/flow-pressure-6b2c1-real-v2/evaluation/preventive-flow-pressure-fde9cfdb99b9/representative-examples.json
artifacts/flow_pressure/flow-pressure-6b2c1-real-v2/evaluation/preventive-flow-pressure-fde9cfdb99b9/retrospective-analysis.json
artifacts/flow_pressure/flow-pressure-6b2c1-real-v2/summaries/pressure-summary-ff3da39df8bf/artifact-manifest.json
artifacts/flow_pressure/flow-pressure-6b2c1-real-v2/summaries/pressure-summary-ff3da39df8bf/summary.json
artifacts/flow_prioritization/signal-prioritization-6b2c2-real-v2/evaluation/signals-inbox-3235b1cc1934/analysis.json
artifacts/flow_prioritization/signal-prioritization-6b2c2-real-v2/evaluation/signals-inbox-3235b1cc1934/artifact-manifest.json
artifacts/flow_prioritization/signal-prioritization-6b2c2-real-v2/evaluation/signals-inbox-3235b1cc1934/demo-artifacts.json
artifacts/flow_prioritization/signal-prioritization-6b2c2-real-v2/evaluation/signals-inbox-3235b1cc1934/metadata.json
artifacts/flow_prioritization/signal-prioritization-6b2c2-real-v2/evaluation/signals-inbox-3235b1cc1934/regional-summary.parquet
artifacts/flow_prioritization/signal-prioritization-6b2c2-real-v2/evaluation/signals-inbox-3235b1cc1934/secondary-research-evidence.parquet
artifacts/flow_prioritization/signal-prioritization-6b2c2-real-v2/evaluation/signals-inbox-3235b1cc1934/views/fallback_attention.parquet
artifacts/flow_prioritization/signal-prioritization-6b2c2-real-v2/evaluation/signals-inbox-3235b1cc1934/views/high_only.parquet
artifacts/flow_prioritization/signal-prioritization-6b2c2-real-v2/evaluation/signals-inbox-3235b1cc1934/views/observed_anomalies.parquet
artifacts/flow_prioritization/signal-prioritization-6b2c2-real-v2/evaluation/signals-inbox-3235b1cc1934/views/top_priority_all.parquet
artifacts/flow_prioritization/signal-prioritization-6b2c2-real-v2/evaluation/signals-inbox-3235b1cc1934/views/unsupported_data_quality.parquet
artifacts/flow_prioritization/signal-prioritization-6b2c2-real-v2/evaluation/signals-inbox-3235b1cc1934/views/watchlist_14d.parquet
artifacts/flow_prioritization/signal-prioritization-6b2c2-real-v2/evaluation/signals-inbox-3235b1cc1934/views/watchlist_7d.parquet
artifacts/flow_prioritization/signal-prioritization-6b2c2-real-v2/evaluation/signals-inbox-3235b1cc1934/views/zero_baseline_low_volume_attention.parquet
artifacts/flow_prioritization/signal-prioritization-6b2c2-real-v2/summaries/signals-inbox-summary-b358a5884e19/artifact-manifest.json
artifacts/flow_prioritization/signal-prioritization-6b2c2-real-v2/summaries/signals-inbox-summary-b358a5884e19/summary.json
artifacts/flow_quantile/flow-quantile-6b2b2-real-v1/summaries/quantile-summary-a480895b5fa7/artifact-manifest.json
artifacts/flow_quantile/flow-quantile-6b2b2-real-v1/summaries/quantile-summary-a480895b5fa7/presentation-examples.json
artifacts/flow_quantile/flow-quantile-6b2b2-real-v1/summaries/quantile-summary-a480895b5fa7/summary.json
artifacts/flow_scenario/flow-scenario-6b3-real-v1/summaries/scenario-summary-926559f25f4a/artifact-manifest.json
artifacts/flow_scenario/flow-scenario-6b3-real-v1/summaries/scenario-summary-926559f25f4a/summary.json
artifacts/flow_scenario/flow-scenario-6b3-real-v1/summaries/scenario-summary-926559f25f4a/validation.json
artifacts/model_assurance/model-assurance-6b5-v1/model_assurance.json
artifacts/runs/decision-alternatives-6b4-real-v3/run.json
artifacts/runs/flow-calibration-6b2b2b-real-v1/run.json
artifacts/runs/flow-evidence-6b2b1-corrected-v3/run.json
artifacts/runs/flow-hierarchy-6b2b3-real-v1/checkpoints/load_forecast--current--default--9d6c478b8ab75cfe.json
artifacts/runs/flow-hierarchy-6b2b3-real-v1/checkpoints/load_forecast--flow-hierarchy-central--central-hierarchy-and-fallback-v1--145e2a4b8b435443.json
artifacts/runs/flow-hierarchy-6b2b3-real-v1/run.json
artifacts/runs/flow-pressure-6b2c1-real-v2/checkpoints/load_forecast--current--default--9d6c478b8ab75cfe.json
artifacts/runs/flow-pressure-6b2c1-real-v2/checkpoints/load_forecast--preventive-flow-pressure--preventive-flow-pressure-v1--152220e91c2f623f.json
artifacts/runs/flow-pressure-6b2c1-real-v2/run.json
artifacts/runs/flow-quantile-6b2b2-real-v1/run.json
artifacts/runs/flow-scenario-6b3-real-v1/run.json
artifacts/runs/journey-full-confirmation-6b2a-20260917/run.json
artifacts/runs/signal-prioritization-6b2c2-real-v2/checkpoints/load_forecast--current--default--9d6c478b8ab75cfe.json
artifacts/runs/signal-prioritization-6b2c2-real-v2/checkpoints/load_forecast--signals-inbox--signals-inbox-v1--5a731f457b3ac7ee.json
artifacts/runs/signal-prioritization-6b2c2-real-v2/run.json
```

## Reproduction and generated outputs

From repository root:

```sh
make operational-intelligence-bundle
make assurance-publish BUNDLE="$PWD/artifacts/model_assurance/model-assurance-6b5-v1/model_assurance.json"
make operational-intelligence-publish BUNDLE="$PWD/artifacts/operational_intelligence/operational-intelligence-slice5-final-test-2025-03-17-v1/operational_intelligence.json"
```

All generated bundles, reports and real-data screenshots stay under ignored:

```text
artifacts/operational_intelligence/operational-intelligence-slice5-final-test-2025-03-17-v1/
```

`operational_intelligence.json` is approximately 354 MiB; `build-report.json` records all source-file hashes and the deterministic rehearsal selection. `live-smoke.json` records DB/API checks; `browser-smoke.json` and `live-*.png` record the real local UI walkthrough. Generated outputs are not staged or committed.

## Publication and database verification

- Model Assurance publication ID: `model-assurance-6b5-v1`; active snapshot **317**; **13 capabilities**. Idempotent republish returned snapshot 317 with no new snapshot.
- Operational publication ID: `operational-intelligence-slice5-final-test-2025-03-17-v1`; active snapshot **221**.
- Operational identity: `43da33ece7231a70348043c2bb8ec4b63161f94ed67dfe96e3c36de69c425cfd`.
- Model Assurance binding exactly matches the pinned frozen assurance identity and accepted source commit.
- Exactly one active snapshot in each model; both unique partial active-snapshot indexes exist. A post-audit DB/API rerun confirmed snapshot IDs and row counts were preserved. Before this activation there were no retained snapshots; no previous publication was discarded. Existing transaction/history tests cover supersession and replay.

| Rows | Count |
| --- | ---: |
| Assurance snapshots / capabilities | 1 / 13 |
| Operational snapshots | 1 |
| Forecasts: hospital | 183,036 |
| Forecasts: region | 39,928 |
| Forecasts: national | 2,716 |
| Forecasts: total | 225,680 |
| Ranked primary signals | 2,521 |
| Data-quality signals | 121 |
| Low-volume attention signals | 1,047 |
| Observed anomalies | 505 |
| Signals: total | 4,194 |

All 3,689 preventive signals retain `historical_flow_proxy_v1`; all 505 observed anomalies have a null pressure basis and separate residual/reference evidence. Overview totals include unranked attention/data-quality records and observed anomalies; they must not be described as 4,194 primary operational warnings or incidents.

## Deterministic rehearsal

Rule: lowest non-null accepted Inbox rank at the explicit final-test origin; no manual cherry-picking.

- Signal: `cc50965694cb0b6862928df5`, rank **1**.
- Series: `hp:000V:391`; hospital `000V`; profile `391`; region `39`.
- Origin `2025-03-17`; target `registrations`; forecast dates `2025-03-18`–`2025-03-31`.
- First point/selected signal: central **5.917120202733519**, historical-flow threshold **1.0**, calibrated bounds **1.373309576901387–23.674832462743403**, nominal coverage **0.8**. These are copied source values, not confidence or capacity scores.

Open `http://localhost:3000/`, choose Signals → rank 1 → Investigate → forecast/uncertainty → explanation → region → hospital/profile → Evidence & Assurance. Direct routes:

```text
/signals/cc50965694cb0b6862928df5
/regions/39
/hospitals/000V/profiles/391
/assurance
```

## Live API and UI verification

All nine populated API requests through the actual `localhost:3000` proxy returned 200: overview, signals, selected signal detail, explanation, matching forecasts, region, hospital/profile, Model Assurance and capabilities. The selected forecast response contains all 14 points. Detail and forecast central/bounds match exactly; all observed response identities match the active snapshot. Explanation generation is DETERMINISTIC. The previous publication 404 blocker is gone.

The live API serves PostgreSQL data only. Docker backend/frontend images were rebuilt from the working tree; no mocks or fixture server were used for Slice 5.

## Verification and remaining limits

Real Chrome completed Overview → Signals → Investigation → forecast/uncertainty → Explanation → Region → Hospital/Profile → Assurance against `localhost:3000`, plus investigation at 375px. All 22 recorded API responses were 200; there were no browser exceptions or document overflow. The drawer rendered real deterministic evidence and governance, opened with close-button focus and inert background, and closed on Escape. Real chart and mobile screenshots were inspected. The first browser harness attempt expected an untranslated enum and was corrected to the rendered Russian label; the real mobile overflow was fixed as described above.

Final checks:

- Frontend: **67 tests pass**, lint and typecheck pass.
- Builder/contract regression tests: **8 pass**, covering raw negative/crossed values, separate calibrated bounds, finite numbers, proxy distinction, partial fields, artifact tampering/missing files/path traversal and wrong assurance identity.
- `make audit`: **all 14 checks PASS**. Layout 314 files; zero source secrets; architecture ARCH001–ARCH005 pass (existing ARCH006 deferred); OpenAPI current; no migration drift; Ruff clean/147 files formatted; **108 backend tests**; **259 deterministic ML contract tests**; all 29 API routes documented; 28 authenticated routes/two health exemptions; generated transport, web lint/build and four-file bundle secret scan pass.
- The audit includes deterministic ML tests only; no frozen evidence pipeline was executed.
- `git diff --check`: PASS. Five modified tracked files and three new files; no staged files, generated evidence, commit or push. ML sources/configs, backend services and generated frontend transport remain unchanged.

Exact source changes:

```text
Makefile
backend/app/schemas/operational_intelligence.py
backend/openapi.json
backend/tests/test_operational_bundle.py
frontend/src/components/control/Evidence.tsx
frontend/src/index.css
tools/operational_bundle.py
docs/demo-publication-slice-5.md
```

P0: none found. P1: publication validator incompatibility fixed; none outstanding. P2: mobile overflow fixed; known limitations below remain. No remaining populated-demo blocker. The local Control Tower is ready for a retrospective accepted-evidence demonstration. It is not a real-time hospital-state system.

Freshness stays UNKNOWN and the historical origin stays visible. This is ready to demonstrate accepted retrospective evidence, not today's hospital conditions. National uncertainty is unavailable; region intervals are level-local, not probabilistically reconciled. Forecast pages can split a series and retain partial-page disclosure; the selected hospital walkthrough contains a complete 14-point series. Existing hospital summary 500-row cap, unpinned multi-request snapshots, English evidence narratives and some raw enum labels remain P2 limits. No physical-capacity, causal, autonomous-routing or decision-alternative promotion claim is introduced.
