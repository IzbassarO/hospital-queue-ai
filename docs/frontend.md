# Frontend — hospital-queue-ai

Web UI for a specialist of a regional health department who plans bed capacity. One scenario: *where is the load,
why, what are the alternatives, what did a person decide*. Built strictly against the existing API
([docs/api.md](api.md)); it has no data or logic of its own beyond display formatting.

- Stack: React 18, Vite, TypeScript, react-router 7, TanStack Query 5, Recharts 3, Tailwind CSS 4 (npm, no CDN),
  ESLint + Prettier (defaults), Vitest + Testing Library. No component library.
- Language: Russian only; every UI string lives in `frontend/src/i18n/ru.ts` (the UI imports `t` from `src/i18n`, so
  another language is one more file with the same `Messages` shape). Domain texts (model cards, factor labels, data
  source, formula parameters) come from the API.
- Access: the browser holds **no** credentials. The proxy in front of the UI adds `X-API-Key` server-side — nginx in
  docker, the Vite dev server for `make web-dev`, both from `DEMO_API_KEY` in the environment (role specialist).
  `VITE_API_KEY` still exists for a build that must carry its own key, but it is empty in every supported setup and
  `make audit` fails if a key ends up in the bundle.
- Runs: `make up` → http://localhost:3000 (nginx serves the build and proxies `/api` to the backend);
  `make web-dev` → http://localhost:5173 (Vite, `/api` proxied to `localhost:8000`; `API_PROXY_TARGET` to change).

## Screen map and API calls

All requests go to the same origin under `/api/v1` (`VITE_API_BASE` overrides it at build time).

| route | screen | API calls |
|---|---|---|
| `/` | **Обзор** — national KPIs (queue, median wait, refusal rate, hospitals with high load), data source and `as_of_date` (from `/config`), regions table sorted by default by the share of hospital profiles with high load (descending), also sortable by max load index, queue, refusal rate, median wait, high-load hospitals; row → region | `GET /overview`, `GET /config` |
| `/regions/:code?profile=&offset=` | **Регион** — region KPIs; profile selector (profiles of the region, highest regional load first, names from the dictionary); status of the region × profile; hospitals of the selected profile ranked by `load_index` with status badge, queue, backlog, median wait, refusal rate, 14-day forecast, excess trend; row → card. Profile and page live in the URL | `GET /regions/{code}`, `GET /dictionaries`, `GET /regions/{code}/hospitals?profile=&limit=50&offset=`, `GET /config` (national median trend for the column hint) |
| `/hospitals/:org/profiles/:profile` | **Карточка стационара** (top to bottom): header with name, region, profile, rank, status badge, `load_index` with its three component bars and a formula tooltip; «Скачать отчёт» XLSX / PDF; KPI strip (queue, backlog, median wait, refusal rate, registrations 28 d, forecast 14 d); chart; «Почему»; «Рекомендации» with decision form and history; «Направления» | see below |
| `/alerts?region=&profile=&status=&offset=` | **Сигналы** — alerts with reasons, status, index, rank in region, queue, backlog, refusal rate, excess trend; region, profile and status filters (in the URL); caption from the alert rule; link to the card | `GET /alerts?region=&profile=&status=&limit=50&offset=`, `GET /dictionaries`, `GET /config` |
| `/models` | **О моделях** — per model: title, version, training date, train / test (or backtest) windows, headline metrics vs the best baseline on the same rows (names from `display_names`), intended use and limitations from the model card | `GET /models` |
| every screen | header shows «Данные на dd.mm.yyyy» and «роль: специалист» (or «нет доступа к API») | `GET /health`, `GET /me` |

Hospital card, section by section:

| section | API call | notes |
|---|---|---|
| header, KPI strip | `GET /hospitals/{org}/profiles/{profile}` → `status` | component bars show `components.*_score` with weights from `/config`; the formula tooltip is filled with the `/config` weights, caps and thresholds |
| chart | same response → `series`, `forecast` | bars: registrations, hospitalizations, refusals; line: queue (right axis); after the dashed «сегодня» marker (`as_of_date`) the 14-day forecast of registrations and hospitalizations as dashed lines on a shaded band; `forecast.note` under the chart. **No queue forecast is drawn** (the API does not return one) |
| Почему | same response → `explanation_factors` | two lists (wait time, refusal risk): arrow icon + title for direction, `short_label` from the API (full `label` as tooltip), `most_common_value_display`, mean effect in дн. / п.п., share of referrals with the factor in their top 5 |
| Рекомендации | `GET …/recommendations` | alternatives with current vs alternative wait, delta, refusal rates, backlogs, the API's Russian explanation, badge «оценка по историческим медианам», rule text, `reason` when there are none, `disclaimer`. Persistent line «Решение принимает специалист. Система только предлагает.» |
| decision form | `POST /decisions` | Подтвердить / Отклонить / Отложить open a small form (comment, actor; actor required and remembered in `localStorage`); body carries `region_code`, `org_code`, `profile_code`, `recommendation_id`, `alternative_org_code`, `action` and an `idempotency_key` generated per submission content (a double submit or retry gets the stored row back); on 201/200 the history query is invalidated. Needs a specialist key (`403` otherwise, shown in the form) |
| История решений | `GET /decisions?org=&profile=&limit=100` | newest first; the alternative by `alternative_org_name` and code |
| «Скачать отчёт» | `GET …/export?format=xlsx\|pdf` | fetched with the API key (a plain link cannot send the header) and saved through an object URL; errors shown next to the buttons |
| Направления | `GET …/referrals?sort=risk\|wait&limit=20&offset=` | server-side sort and paging; diagnosis code with `diagnosis_name`; expandable row with the top-5 factors of both models (`short_label`, `value_display`, `effect_in_unit` + `unit`) |

## Demo path

`/` → «г. Астана» → profile «Патологии беременности» → ZIQ9 (Городской перинатальный центр) → recommendations →
«Подтвердить» (comment, actor, «Записать решение») → the row appears in «История решений» → «Сигналы» shows the
same hospital first with its reasons → link back to the card. Every API call on this path answers in < 100 ms
against the docker stack; screens render in ≈ 0.1–0.25 s.

## Design rules

- Light background, one accent (blue `#174c8f`); status colours red / amber / green / grey are always paired with an
  icon **and** a text label (Высокая / Повышенная / Норма / Недостаточно данных) and differ in lightness, so they
  survive greyscale projectors.
- Tables: sticky header, numbers right-aligned with tabular figures and Russian thousands separators, sortable
  columns announced with `aria-sort`. Dates `dd.mm.yyyy` (formatted from the ISO string, no time-zone shift).
- Every data block has a loading skeleton and an error state. API unreachable (network error, or 502/504 from
  nginx) → «API недоступен. Адрес запроса: <absolute URL>» with a retry button; 404 and 503 show the API's `detail`.
- Desktop tool: layout from 1024 px (`body { min-width: 1024px }`), content max 1440 px. No emojis; icons are
  inline SVG.
- Keyboard: skip link, visible focus ring, tooltips open on focus, rows are clickable but every row also contains a
  real link or button.

## Code structure

```
frontend/
├── src/
│   ├── api/          schema.ts (runtime response checks), types.ts (schemas → TS types), client.ts (fetch with
│   │                 X-API-Key, file download, ApiError with URL), queries.ts (TanStack Query hooks and keys)
│   ├── i18n/         ru.ts (all strings), index.ts (`t`)
│   ├── lib/          format.ts (numbers, days, %, dates), paths.ts (links)
│   ├── components/   Layout, DataTable, StatusBadge, LoadIndexBars, InfoTip, Kpi, Pagination, Skeleton,
│   │                 ErrorState, QueryState, PageHeader, Direction, icons
│   ├── pages/        OverviewPage, RegionPage, AlertsPage, ModelsPage, NotFoundPage,
│   │                 hospital/ (HospitalPage, CardHeader, ExportButtons, SeriesChart, WhyPanel, Recommendations,
│   │                 ReferralsTable)
│   ├── test/         setup.ts, mockApi.ts, fixtures/*.json (responses captured from the running API), routes.test.tsx
│   ├── routes.tsx    route table
│   └── main.tsx      QueryClient + router
├── Dockerfile        node:22-alpine build → nginx:1.29-alpine
├── nginx.conf.template  SPA fallback, /api proxy to backend:8000 with server-side X-API-Key, caching, /healthz
└── package.json      scripts: dev, build, lint, format, test
```

Every API response is validated at runtime against the schema in `src/api/types.ts` (mirroring
`backend/app/schemas`); a changed field fails loudly with its path instead of rendering an empty cell.

## Tests and checks

| command | what |
|---|---|
| `make web-test` | Vitest (30 tests): the header role label; the default sort by `high_load_share`; alert filters in the request and URL; the export button; every route renders with real captured responses; the decision form POSTs the expected body; the API-down message shows the URL; the client parses every endpoint's captured response **and the JSON examples of docs/api.md §6** (placeholders `…` stripped), and reports shape errors with the field path; formatting |
| `make web-lint` | ESLint (typescript-eslint, react-hooks) + `prettier --check` |
| `make web-build` | `tsc -b` + Vite production build |
| `make audit` | runs web-lint and web-build too (when `frontend/package.json` exists) |

Fixtures in `src/test/fixtures/` were captured from `make up` and trimmed (fewer regions / profiles); refresh them
when the API contract changes.

## API gaps (step 5) — closed in step 6

All gaps found while building the UI were closed in the API; the UI no longer duplicates domain texts:

| gap | now |
|---|---|
| model limitations duplicated in `ru.ts` | `GET /models` → `intended_use`, `limitations`, `display_names` from `ml/configs/model_cards.yaml` (artifact `card.json` → `model_registry.card`) |
| `load_index` weights / caps, data source hard-coded | `GET /config` → weights, caps, thresholds, alert and recommendation rules, data-source description; the formula tooltip, alert caption and source note are built from it |
| history parsed the alternative from `recommendation_id` | `decision_log.alternative_org_code`; `Decision.alternative_org_name`; the form sends `alternative_org_code` |
| no diagnosis name on referrals | `ReferralItem.diagnosis_name` from `dim_icd` (built at ingest) |
| UI kept its own short factor labels | `short_label` on card and referral factors (`explain_templates.yaml`) |
| per-referral factor unit implicit | `unit` and `effect_in_unit` on every referral factor |
| no data-source description | `GET /config` → `data_source` |
| alerts: no profile / status filter, no `status_label` / `region_rank` | `GET /alerts?profile=&status=`; `status_label`, `region_rank`, `region_n_ranked` |
| `POST /decisions` not idempotent | `idempotency_key` (unique); the form generates one per submission content — a retry returns the stored row with `200` |
| stale recommendations example in docs/api.md | refreshed from the running API |

Also added in step 6: `high_load_share` on area rows (overview table, default sort descending; max index kept as a
column), the role label «роль: …» in the header (`GET /me`), «Скачать отчёт» (XLSX / PDF) on the card, and the API key
added by the proxy server-side (`DEMO_API_KEY` in the nginx / dev-server environment; see docs/security.md for what
that implies).
