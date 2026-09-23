# Slice 6 — Guided Decision Journey and review-evidence publication

Slice 6 redesigns the primary demo experience at the product-concept level and publishes the two remaining accepted,
evaluation-only capabilities (forecast stress tests, constrained decision alternatives) through the same explicit
publication architecture as Slice 5. No ML run, retraining, scenario execution or decision-alternative acceptance
was performed; every value is copied from the checksummed frozen artifacts and verified against the referenced
Model Assurance and operational publications.

## Product structure

| Route | Role |
| --- | --- |
| `/` → `/demo/detect` | Primary guided journey (five focused scenes, stepper model, no long dashboard) |
| `/demo/:scene` | `detect`, `understand`, `test`, `review`, `trust`; optional `?signal=<id>` |
| `/operations` | Secondary “Operations view”: the unchanged Control Tower overview |
| `/signals`, `/signals/:id`, `/regions/:code`, `/hospitals/:org/profiles/:profile`, `/assurance` (+ `/alerts`, `/models`) | Detailed operational/reference views, unchanged |

Navigation: top progress bar (five steps with `aria-current="step"`), Previous/Next controls, ← / → keys (ignored
inside inputs and while a dialog is open), “Открыть операционный режим”, and a “Гид по системе” link back from the
operations shell.

## Default subject

The subject is the published rank-1 signal of the current origin (`GET /operational-intelligence/signals?limit=1`),
never a browser-side choice. With the Slice 5 publication this is `cc50965694cb0b6862928df5` (`hp:000V:391`,
Костанайская областная больница, профиль 391, регион 39, origin 2025-03-17, target registrations). Scientific values
(central 5.917, calibrated 80% bounds 1.373–23.675, historical-flow reference 1.0, first crossing 2025-03-18,
lead 1 day) are read from the API. Hospital names come from the `organizations` list added to `GET /dictionaries`.

## Scenes and their real data

| Scene | Data |
| --- | --- |
| DETECT | `OI/signals?limit=1`, `OI/signals/{id}`, `OI/regions/39` (counts + top signals), `OI/overview` (regional HIGH counts), `OI/forecasts` (coverage), `/dictionaries` |
| UNDERSTAND | `OI/forecasts` (14 central points + calibrated bounds), `OI/signals/{id}/explanation` (deterministic), `/hospitals/000V/profiles/391` (observed daily registrations **up to the origin only**, from the operational data mart; context, not part of the frozen publication) |
| TEST | `review-evidence/signals/{id}/stress-test`: identity reproduction + ×0.90 / ×1.10 / ×1.20 outcomes and 14 daily cells each (baseline central + calibrated bounds vs scenario central + derived sensitivity range), network counts from the accepted scenario summary |
| REVIEW | `review-evidence/signals/{id}/decision-alternatives` (the subject’s four budget sets: all abstained, RECEIVER_BLOCKED, 61 candidates / 4 eligible, minimum fraction 0.886) and `review-evidence/decision-alternatives?origin=&region=39&with_alternatives=true` → lowest-rank donor with alternatives (22VJ/031, rank 9 → receiver 0FU6/031, fraction 0.303, VERIFIED_FULL_ENGINE) |
| TRUST | `/model-assurance`, `/model-assurance/capabilities` (calibration coverage 83% validation / 70% final test, accepted/rejected/evaluation-only counts), `OI/overview` snapshot, `review-evidence/overview` |

## Review-evidence publication (new backend slice)

- Alembic `0009`: `review_evidence_snapshot`, `review_scenario`, `review_scenario_entity`, `review_scenario_cell`,
  `review_alternative_set`, `review_alternative`.
- `app/schemas/review_evidence.py` (bundle + DTOs), `app/services/review_evidence.py`, `app/repositories/review_evidence.py`,
  five `GET /review-evidence/...` routes (documented in `docs/api.md`, stable operation IDs in `tools/openapi_contract.py`),
  `python -m app.cli publish-review-evidence`, `make review-evidence-bundle`, `make review-evidence-publish`.
- `tools/review_evidence_bundle.py` reuses the Slice 5 `Evidence` verifier (assurance identity, all 13 capability run
  manifests, summary/evaluation checkpoint identities, every artifact file checksum) and projects: every primary-Inbox
  registrations entity at the explicit final-test origin (2,521) × four standard scenarios (10,084 entity rows,
  141,176 daily cells) and all 460 accepted alternative sets (430 alternatives). The population rule is fixed, not a
  demo selection.
- Publication verifies `forecast_stress_test` and `decision_alternatives` against the referenced Model Assurance
  snapshot (ACCEPTED, ACCEPT/ACCEPT_WITH_P2, EVALUATION_ONLY, NO_PROMOTION, human review required, no autonomy /
  capacity / causal / serving claim, matching run/scientific/artifact/dataset/config/code identities), requires the
  referenced operational publication identity and origin, and rejects the bundle unless the identity scenario reproduces
  every published central forecast exactly (SQL join, tolerance 1e-9).
- Local publication: `review-evidence-slice6-final-test-2025-03-17-v1`, identity
  `e07be2f158c69ed50c9da2286a9459424947d02266e5094c5627b7648be33c22`, referencing operational
  `43da33ec…` and assurance `f504defe…`.

## Human-language layer

`frontend/src/demo/language.ts` maps machine vocabulary to approved Russian: reason codes
(`CALIBRATED_LOWER_EXCEEDS_HISTORICAL_FLOW_THRESHOLD` → «Даже нижняя граница калиброванного интервала выше исторического
ориентира потока»), statuses (`materiality_rule_not_triggered` → «Порог материальности не отсеял сигнал»), abstention
codes, verification states, range results, capability names, and the English published sentences of the explanation
endpoint (exact and pattern forms). Unmapped sentences are never shown in the primary surface; they stay in the
“Технические идентификаторы” disclosure. Headlines are rebuilt from severity and lead time
(«Потенциальное высокое давление потока — в течение 1 дня»); the English model headline is never rendered.

## Motion

Scene entry (fade/rise 420 ms), panel rise, band clip reveal and line draw on the forecast chart, bar reveal on
transfer/region charts, count-up on primary stats (600 ms, `requestAnimationFrame`), drawer slide. All finite;
`prefers-reduced-motion` disables CSS animation and makes `useCountUp` return the final value immediately
(tested with a mocked `matchMedia`).

## Tests

`frontend/src/test/demo.test.tsx` (15 tests, fixtures shaped from the live responses of the demo signal): default
rank-1 subject and request shape, progress/next/previous/keyboard navigation, mapped reasons and explanation drawer
(focus, Escape, raw enum only behind the technical disclosure), stress-test outcomes and scenario switching,
abstention + same-region verified alternative, six trust indicators with real coverage and hidden hashes, forbidden
language guard per scene (recommendation / routing / optimization / capacity planning / free beds / Digital Twin /
English model headline; negations live in `data-nonclaim` blocks), reduced-motion rendering, explicit `?signal=`,
missing publication, unpublished review evidence, and the operations route. Existing route tests were repointed
from `/` to `/operations` without weakening; backend adds publication, migration, builder and API tests.

## Known limits

- Observed history in UNDERSTAND comes from the legacy hospital card (mart as-of 2025-03-31), truncated at the
  origin; if the marts are absent the chart shows the forecast only.
- The REVIEW example is the same-region, lowest-rank donor set with alternatives at the current origin; with a
  different publication the rule may select another set or none (explicit empty state).
- Hospital names are the quoted part of the registry title; long legal prefixes are dropped for display only.
