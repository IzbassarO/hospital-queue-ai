# Demo frontend — handoff schema

Purpose: a self-contained map of how the demo frontend is built, so that a fresh session can continue the work
without re-deriving anything. Part A is the **control centre** at `/` (map, notifications, queue, simulation), part B
the six-scene story at `/demo/*`. Read this first, then [demo-publication-slice-6.md](demo-publication-slice-6.md)
for the publication slice and data facts.

## A. Control centre (`/`, `/notifications`, `/queue`; `frontend/src/tower`)

What it is: the practical face of the project for the GovTech Camp defence. Real inputs (published model) and a
labelled synthetic layer, side by side, with the specialist in the loop. Two languages (RU / KZ) everywhere.

### Pages and shell

| Route | Component | Contents |
| --- | --- | --- |
| `/` | `TowerPage.tsx` | lead, `WaitingStrip` (waiting within 7 / 14 / 30 days + open tasks), `SimulationBar`, map + `Feed`, `FocusPanel` (when a hospital is selected), `PriorityList` (top 5 tasks), non-claims |
| `/notifications` | `NotificationsPage.tsx` | master–detail: list on the left (filters: all / pending / confirmed / forecast), `SubjectContent` on the right |
| `/queue` | `QueuePage.tsx` | waiting strip, the full 30-day synthetic queue (`PatientQueue`, 25 per page), decision journal |
| shell | `TowerLayout.tsx` + `TaskHost.tsx` | brand, nav (centre, notifications, queue, "how it works" menu → `/demo/*`), origin state, `LanguageSwitch` (RU/KZ), `TaskBell` (open-task count) → `Explorer` drawer; `SubjectDialog` host. `DemoLayout` mounts the same `TaskHost`, switch and bell, so tasks are reachable from the story too |

State that must survive navigation lives outside React: the simulation (`sim/useSimulation.ts`, module store,
`useSimState()` / `dispatchSim()` for the shell) and the UI (`ui.ts`: explorer open, subject in the dialog).
Full page reloads reset both (nothing is persisted to storage except the language).

### Data (`useTowerData.ts`, `useTowerModel.ts`)

| Block | Real input | Synthetic (labelled) |
| --- | --- | --- |
| Lead / counters | `OI/overview` (origin, counts), mart overview (`registrations_28d / 28` = daily base) | — |
| Map (`components/KazMap.tsx`) | registry (1 406 orgs), HIGH + ELEVATED signals (`severity=` filter, limit 500 each), region counts | hospital positions: `synthetic.ts: placeHospitals` — town stem in the legal name → town anchor, else region capital; hospitals of one anchor spread on a golden-angle disc and are pushed back inside the region polygon (`geo/project.ts: pointInRegion`), so no dot sits outside a border; tooltips name the neighbours of the same town |
| Alerts | up to 60 readable alerts (central ≥ 0.5): HIGH by rank, then ELEVATED | phase (forecast → decision → confirmed / not confirmed / unverified / escalated), observed flow, the specialist's decision |
| Queue | crossing windows of the alerts | pseudonymous referrals `Н-####` (`generatePatients`, ⅔ in the 14-day window, ⅓ up to day 30), statuses: waiting → request → confirmed / admitted / delayed / declined / unverified |

### Simulation (`sim/simulation.ts`, pure reducer, seeded `mulberry32`)

A day is a clock from 08:00 to 18:00 (`clock` minutes since 08:00). `tick` computes the whole day's events, each
with a synthetic time; `advance` moves the clock (`useSimulation`: 120 ms per tick, `DAY_MS = 14 s` at ×1) and
reveals events as it passes their time (`visibleEvents`). **The clock stops on the first actionable event**
(`ACTIONABLE`: decision_needed, patient_request, escalated) and sets `pausedForDecision`; the specialist answers
through the dialog or presses play again. "Next day" (`tick` action) reveals a whole day at once.

Per day: 08:xx arrivals = daily base × scenario multiplier × noise; 09–11 the model asks the specialist (HIGH, or
ELEVATED crossing within 3 days; ≤ 2 per day); 10–11 urgent requests for tomorrow's admissions at pressured
hospitals (≤ 2 per day, `patient_request`); 12–15 crossings compared with a synthetic observed flow (central ×
multiplier × noise) → confirmed / not confirmed; outage region → unverified (never filled in); 16:xx one ELEVATED
series may escalate on observed flow under stress; 17:xx admissions happen or slip 1–3 days (confirmed ones never
slip). Human actions: alerts `accept | decline | clarify`, patients `confirm | decline | postpone` (+3 days);
both are logged as events and counted. Scenario or reset re-initialises from the seeds. Published values
(forecast, threshold, crossing, severity) are never recomputed.

Selectors: `sim/tasks.ts` — `pendingTasks` (open alerts + requests, first come first served, then urgency) and
`waitingWithin(days)`; `sim/verdict.ts` — "should the specialist step in?" yes / no / unclear with reasons, built
only from published facts + simulation state (an attention reading, never an instruction; the dialog says so);
`sim/explain.ts` — the deterministic plain-language paragraphs.

### Subject dialog and page (`components/SubjectContent.tsx`, `SubjectDialog.tsx`, `subject.ts`)

Order inside: brief (hospital / patient, profile, region, when) → AI assistant bubble → verdict with reasons →
facts ledger → plain explanation → decision (Принять / Отклонить / Запросить данные or Перенести, comment,
Отмена) → link to the story for this signal. The modal closes on ×, Escape, Отмена and a click outside.

AI assistant (`ai/assistant.ts`) is an **empty transport**: with `VITE_ASSISTANT_URL` unset the UI shows the stub
reply and the "не подключён" badge; when set, the browser POSTs `AssistantRequest` (language, question, facts,
deterministic explanation, subject) to that URL — which must be a backend proxy holding the provider key — and
renders `{ text }`. No provider is called from the browser.

### Persistence, database, assistant (v3)

- **The simulation survives a reload.** `sim/useSimulation.ts` saves the store (debounced) to `localStorage`
  (`hqai.sim.v1`) keyed by origin + alert ids and restores it on the next load (paused). `clearSavedSimulation()`
  for tests. The language (`hqai.lang`) and the walkthrough flag (`hqai.tour.v1`) are the only other keys.
- **Decisions live in Postgres.** `POST/GET /api/v1/specialist-decisions` (table `specialist_decision`, Alembic
  `0010` + `0011`, `backend/app/services/specialist_decisions.py`). Every simulation run has a `runId`
  (`SimState.runId`, new on "Сначала" and on a scenario change). `useTowerModel.ts: persistDecision` writes every
  decision with that run id (idempotency key = run + subject + action); `useHydrateDecisions` replays only the
  rows of the current run after a reload, so a restart forgets the previous answers on screen while the table
  keeps them as history.
- **Assistant proxy.** `POST /api/v1/assistant` (+ `GET /assistant/status`) — `backend/app/services/assistant.py`
  calls the configured provider's OpenAI-compatible chat endpoint with a system prompt that keeps the claim
  boundaries (RU/KZ). Settings: `ASSISTANT_PROVIDER` (groq | openrouter | gemini | openai), `ASSISTANT_API_KEY`,
  `ASSISTANT_MODEL`, `ASSISTANT_BASE_URL` in `.env` (never in the browser). The bubble badge reads the status;
  the browser module `tower/ai/assistant.ts` only talks to the proxy. Groq needs a real `User-Agent` (Cloudflare).
- **Wait forecast and the urgency floor.** `useTowerData` fetches the legacy mart card of every alert's
  hospital × profile (`api.hospitalCard`: `median_wait_28d`, `queue_now`) and seeds the synthetic queue with it
  (`generatePatients`: wait = the hospital's historical median ± 35 %, queue size ∝ the mart queue; fallback =
  the national median). `synthetic.ts: urgencyOf` applies `URGENCY_FLOOR_PER_DAY = 1`: a series whose forecast
  is below one registration a day is never "high" urgency, and a fallback-supported forecast is capped at
  "medium"; the verdict lists the floor as a reason and never answers "yes" for such a series. Published
  severity is still shown as published.
- **Borders and anchors.** `geo/kaz-regions-2022.json`: the twenty current regions from OpenStreetMap (relations
  admin_level 4, ways stitched and simplified, ~91 KB); `geo/project.ts: MAP_VARIANT` switches back to the
  legacy Natural Earth file, which stays on disk. `geo/towns.generated.json`: 215 settlements / districts geocoded
  once from the hospital legal names (Nominatim); `placeHospitals` prefers a geocoded anchor of the same region,
  then the hand-made list, and drops any anchor outside the region polygon.
- **Walkthrough and export.** `components/Tour.tsx` (+ `tour-state.ts`): seven `data-tour` anchors, opens on the
  first visit of `/` once the page has rendered, re-opened by the "?" button. `export.ts`: CSV (UTF-8 BOM,
  semicolon) of the queue and the decision journal from `/queue`.

### i18n

`i18n/index.ts`: `t` is a Proxy over the current language's messages; `useLang()` / `setLang()`; the choice is
stored in `localStorage` (`hqai.lang`) and mirrored into `<html lang>`. Layouts re-key `<main>` on the language so
every component re-renders. Kazakh copies live in `control.kk.ts`, `demo.kk.ts`, `tower.kk.ts`, `kk.ts` (typed as
`Messages`, so a missing key fails `tsc`). `demo/language.ts` keeps RU and KK maps for reason codes, statuses,
abstention codes, capability names and the English published sentences, selected by `getLang()`. Registry names
(regions, profiles, hospitals) come from the API in Russian and are not translated.

Copy: `i18n/control.ts` (`t.control.*`). Styles: `tower/tower.css` (shares the tokens of `demo.css`; the map and
the simulation bar are the only dark surfaces; the feed is the phone-like column). Tests: `test/tower.test.tsx`
(big picture, the clock stopping on a task, dialog → verdict → decision → journal, click-outside, state surviving
navigation, notifications page, language switch). Forbidden vocabulary and machine tokens are checked on the
primary text; the verdict, plain explanations and non-claims sit in `data-nonclaim`.

## B. Six-scene story (`/demo/*`, `frontend/src/demo`)

## 1. What the demo is

A six-scene guided journey (stepper, one scene per route) that tells the story of one real published signal:

| # | Route | Scene | Component | Question it answers |
| --- | --- | --- | --- | --- |
| 1 | `/demo/flow` | Процесс | `FlowScene.tsx` | How one referral travels from registration to the specialist's decision (animated simulation) |
| 2 | `/demo/detect` | Обнаружение | `DetectScene.tsx` | Which signal was detected, where, how severe |
| 3 | `/demo/understand` | Понимание | `UnderstandScene.tsx` | What the model sees (forecast + calibrated band) and what it does not claim |
| 4 | `/demo/test` | Стресс-тест | `TestScene.tsx` | What happens to the signal under ×0.90 / ×1.10 / ×1.20 synthetic stress |
| 5 | `/demo/review` | Разбор | `ReviewScene.tsx` | Which mathematical alternatives are admissible (or why the engine abstained) |
| 6 | `/demo/trust` | Доверие | `TrustScene.tsx` | Six trust indicators + technical provenance |

`/` is the control centre (part A); `/demo` redirects to `/demo/flow`. The former operations view
(`/operations`, `/signals`, `/regions`, `/hospitals`, `/assurance`) was removed together with its pages, components,
legacy hooks, fixtures and copy; only `api/client.ts` (health, overview, dictionaries, hospital card) and
`api/queries.ts` (overview, dictionaries) remain of the legacy mart layer.

Hard rules that every scene follows (from the frozen ML science and the assurance claim boundaries):

- Russian UI; no raw enums / SHA256 / run IDs on the primary surface (they go into `<Technical>` disclosures).
- Never say: рекомендация, маршрутизация, оптимизация, планирование мощности, свободные койки, занятость,
  цифровой двойник, the English model headline. Negations are allowed only inside `data-nonclaim` containers.
- No scientific computation in the browser: no re-ranking, no recomputed severities, no invented numbers.
  Every number comes from an API response.

## 2. Files (all under `frontend/src`)

```
routes.tsx                     "/" → TowerLayout + TowerPage; /demo/:scene → DemoLayout + DemoScene; "*" → "/"
main.tsx                       imports index.css (base + shell utilities), demo/demo.css, tower/tower.css
i18n/demo.ts                   ALL Russian copy of the demo (scene labels, flow steps, detect/understand/test/review/trust)
i18n/ru.ts                     composes { tower, demo, ... } → `t.demo.*`
demo/journey.ts                SCENES order, SceneId, scenePath()
demo/DemoLayout.tsx            header (brand mark, progress bar, origin, "Открыть операционный режим"), footer
                               (Назад / Далее), ← → keyboard navigation (ignored in inputs / dialogs)
demo/scenes/DemoScene.tsx      switch(scene) → scene component
demo/scenes/SubjectState.tsx   loading / 404 / error frames: SubjectState (needs the subject signal), EvidenceState
demo/scenes/DemoEvidenceDrawer.tsx  modal drawer with the deterministic explanation, translated; focus trap, Escape
demo/useDemoSubject.ts         resolves the subject: rank-1 signal (signals?limit=1) or ?signal=<id>; names via
                               dictionaries (regions, profiles, organizations); forecast series; region summary
demo/language.ts               machine → Russian: REASON_CODES, STATUS_LABELS, ABSTENTION_CODES, CAPABILITY_NAMES,
                               translateSentence()/translateList() for the English published sentences, isTechnical()
demo/api.ts                    review-evidence runtime schemas + hooks: useReviewOverview, useStressTest,
                               useSignalAlternatives, useAlternativeSets, useAlternativeSet; useObservedHistory
                               (legacy hospital card series, truncated at the origin)
demo/primitives.tsx            Scene, Panel (tone: dark | paper | glass=black; eyebrow+title in a hairlined head),
                               SeverityPill, Stat (count-up; hero tiles only), StatGrid, Facts (label → value ledger),
                               FactLine (inline numbers), NonClaims (data-nonclaim; run-in title + prose),
                               Bullets (default | check | numbered), Technical (data-technical), Arrow, Legend
demo/glyphs.tsx                inline SVG line icons (referral, flow, forecast, signal, evidence, human, audit, play…)
demo/motion.ts                 useReducedMotion(), useCountUp(value, reduced) — no setState inside effect bodies
demo/charts/ForecastStory.tsx  SVG: observed bars (clipped + labelled above the axis) → origin → central line +
                               calibrated band gradient + threshold + first crossing
demo/charts/StressChart.tsx    SVG: baseline central/band (grey) vs scenario central/derived range (accent) + threshold
demo/charts/TransferChart.tsx  SVG: donor/receiver before→after bars per day with threshold ticks
demo/charts/RegionBars.tsx     horizontal bars of HIGH counts per region, subject region highlighted
demo/charts/scale.ts           niceTicks()
demo/demo.css                  the whole design system (tokens, header, buttons, scenes, panels, stats, severity,
                               charts, flow stage, drawer, motion, responsive, reduced-motion)
test/demo.test.tsx             behaviour tests of the demo (demoMock wraps operationalMock; fixtures below)
test/demoFixtures.ts           fixtures shaped from the live responses of the real demo signal
```

Backend counterpart used only by scenes 4–6: `backend/app/{schemas,services,repositories}/review_evidence.py`,
routes `GET /api/v1/review-evidence/...`, Alembic `0009`, builder `tools/review_evidence_bundle.py`.

## 3. Data flow (one pattern for every endpoint)

```
generated OpenAPI types (src/api/generated)  →  runtime guard (schema.ts objects; demo/api.ts, operational-schemas.ts)
  →  adapter view (operational-adapters.ts: signalView, forecastGroups, capabilityView …)
  →  TanStack Query hook (staleTime 60 s, retry false)  →  scene component  →  language.ts for labels
```

Endpoints per scene (all prefixed `/api/v1`):

- FLOW: `/overview` (mart: registrations_28d, n_hospital_profiles, n_hospitals), `/operational-intelligence/overview`
  (forecast_count, signal counts), `/operational-intelligence/signals?limit=1`, `/review-evidence/overview`,
  `/model-assurance` + `/capabilities`.
- DETECT: `OI/signals?limit=1`, `OI/regions/{region}`, `OI/overview`, `OI/forecasts?...level=hospital`, `/dictionaries`.
- UNDERSTAND: `OI/forecasts`, `OI/signals/{id}/explanation`, `/hospitals/{org}/profiles/{profile}` (observed history).
- TEST: `/review-evidence/signals/{id}/stress-test`.
- REVIEW: `/review-evidence/signals/{id}/decision-alternatives`,
  `/review-evidence/decision-alternatives?origin=&region=&with_alternatives=true`, `/review-evidence/decision-alternatives/{set_id}`.
- TRUST: `/model-assurance`, `/model-assurance/capabilities`, `OI/overview`, `/review-evidence/overview`.

## 4. How `/demo/test` is built (worked example)

1. `TestScene` calls `useDemoSubject()` (subject signal + names) and `useStressTest(signal.id)`.
2. `SubjectState` renders loading / 404 / error frames until the subject exists; `EvidenceState` does the same for
   the stress-test query (a 404 shows `t.demo.test.notPublished`, never a fake scene).
3. The response has `outcomes[]`, one per scenario (`baseline-identity`, `national-registrations-x0.90`, `x1.10`,
   `x1.20`). The identity outcome is shown as the "✓ Воспроизведение" line; the stressed ones become chips.
   The last stressed scenario (×1.20) is active by default; clicking a chip changes `selected`.
4. Left panel (`Panel tone="glass"`, black): `StressChart` with the active outcome's 14 `cells` — baseline central +
   calibrated bounds in grey, scenario central + derived sensitivity range in lime/emerald, amber dashed threshold,
   changed-severity days as amber dots. `key={scenario_id}` remounts it so the reveal animation replays.
5. Right column: outcome as a `Facts` ledger (severity before → after with `SeverityPill`, central `5,9 → 7,1` +
   relative delta as hint, rank before → after, first crossing, threshold), network counts from
   `scenario.network_summary` as one `.prose` paragraph (`t.demo.test.networkCells/networkEntities`, each in its
   own span) + `.footnote`, `NonClaims` with `t.demo.test.nonClaims`.
6. Scene foot: `Technical` with scenario id, classification, range semantics, publication identities, provenance run ids,
   evidence facts and limitations (English source strings stay here only).
7. The subtitle mentions «цифровой двойник» as a negation, so it is wrapped in `data-nonclaim="true"`.

Numbers shown are copied from the API: no delta, severity or rank is computed in the browser.

## 5. Design system (demo.css)

Tokens on `.demo-root` and `.demo-drawer-backdrop` (the drawer is portalled to `<body>`):

```
--c-bg #f3f4ef   --c-paper #fff   --c-ink #0f1512   --c-muted #6b776f   --c-line rgba(15,21,18,.09)
--c-dark #0c110f (black panels)   --c-on-dark #f3f4ef   --c-on-dark-muted #9aa69f
--c-accent #16a66e   --c-accent-strong #0e8a5b   --c-accent-soft #dbf5e8   --c-accent-ink #0b5c3d
--c-lime #cdeb5b (highlight on black)   --c-amber #d18a12   --c-red #d64b3a   (severity only)
--radius 16px   --radius-sm 10px   --ease cubic-bezier(.22,1,.36,1)
```

Panel tones: `panel` (white paper), `panel-glass` (black with lime accents — used for the primary visual of each
scene), `panel-paper` (soft emerald — used for "Почему сигнал отмечен"). Buttons: `btn-accent` (black),
`btn-lime`, `btn-ghost`. Severity pills: `sev-high|elevated|watch|normal|unsupported` (+ `.panel-glass` variants).
Charts get `.panel-glass` overrides so the same SVG works on paper and on black.

Editorial rules (the "dossier" look, introduced to remove the generic dashboard pattern):

- Section labels are sentence case, muted, never uppercase/tracked. Only `scene-kicker`, the brand kicker and the
  progress bar keep uppercase. A `Panel` renders eyebrow + title inside `.panel-head` with a hairline below.
- Facts outside the DETECT hero are `Facts` ledgers (`.facts` / `.fact`: label column, value, optional hint, hairlines
  between rows; `.facts-columns` for two columns). Stat tiles (`.stat-grid`) stay only in the black subject panel.
- Explanations are prose: `Bullets tone="numbered"` for reasons (CSS counters), `.prose` paragraphs for network
  counts and abstention reasons, `.footnote` for provenance remarks. `NonClaims` is a run-in title followed by the
  items as sentences (each item keeps its own `<span>` for tests) with an amber left rule, no box.
- Lists instead of card grids: TRUST uses `.trust-list` (two columns, numbered `01…06`, `<article>` per item),
  FLOW uses `.flow-focus` (subject with headline + mini ledger) and `.flow-route` (numbered next scenes),
  REVIEW checks use `.checks` (✓ / ! rows), DETECT region ranking is a hairlined table (`.region-rank`).

Motion: `scene-in`, `rise` (panels, staggered), `clip-reveal`/`line-reveal` (forecast band and line), `bar-reveal`,
`draw`, count-ups in `useCountUp`; flow rail/runner use CSS transitions driven by `--progress`. Everything is finite
and switched off under `prefers-reduced-motion`. Flow metrics (`.flow-metric`) are borderless numbers with a lime
left rule, not tiles.

## 6. Flow scene mechanics (`FlowScene.tsx`)

`ORDER` = referral → flow → forecast → signal → evidence → decision → audit. State: `active` index and `playing`;
`done` is derived (`active === last`). An effect schedules `setActive(i + 1)` every `STEP_MS` (2600 ms) while playing
and not at the end; reduced motion starts at the last step with autoplay off. Clicking a station pauses and selects it.
The rail fill and runner read `--progress = active / (ORDER.length - 1)`. Metrics per step are built in a `useMemo`
from the queries listed in §3. The "decision" step is styled as the human step (`is-human`, white glyph,
«Здесь решает человек»). Below the stage: `flow-next` = `.flow-focus` (subject in focus: name, profile · region,
severity + rank, DETECT headline, ledger of central / threshold / horizon, CTA → detect) and `.flow-route`
(numbered links to detect / test / review with the scene number from `SCENES`).

## 7. Tests and gates

- `frontend/src/test/demo.test.tsx`: flow simulation, detect subject, navigation (progress, next/prev, arrows),
  understand + drawer (focus, Escape, no raw enums outside `[data-technical]`), test scene chips and numbers, review
  abstention + same-region alternative, trust indicators, per-scene forbidden-language guard (`FORBIDDEN` regexes
  applied to `primaryText()` which strips `[data-technical]`, `[data-nonclaim]` and `svg title`), reduced motion,
  `?signal=`, missing publication, unpublished review evidence, `/operations` still works.
- `test/tower.test.tsx` covers the control centre (part A).
- Gates: `npm test`, `npm run lint`, `npm run typecheck`, `npm run build` (in `frontend/`), `make audit`,
  `git diff --check` (repo root). Rebuild the served UI with `docker compose up -d --build --wait frontend`.

## 8. Adding or changing a scene — checklist

1. Add copy to `i18n/demo.ts` (Russian, no forbidden vocabulary; negations go into `NonClaims`).
2. Add the scene id to `demo/journey.ts` (order = progress bar order) and a case in `DemoScene.tsx`.
3. Build the component from `primitives.tsx`; put raw identifiers only in `<Technical>`.
4. If new data is needed: add a runtime schema + hook in `demo/api.ts` (or `api/operational.ts`) — never fetch
   without a guard, never read ML artifacts.
5. Add fixtures to `test/demoFixtures.ts`, routes to `demoMock` in `demo.test.tsx`, and a behaviour test; the
   per-scene forbidden-language test iterates `SCENES` automatically.
6. Run the gates, rebuild the frontend container, look at it in Chrome at 1440 px.

## 9. Known limits / open ideas

- Observed history in UNDERSTAND comes from the legacy mart card (`as_of` 2025-03-31), truncated at the origin.
- The REVIEW example is the same-region, lowest-rank donor set with alternatives; another publication may select a
  different set or none (explicit empty state).
- Organization names are shortened to the quoted part of the registry title (`shortenOrganization`).
- "Спросить о сигнале" is a reserved slot only; no chat is implemented by design.
