# Frontend — hospital-queue-ai

Web UI for a specialist of a regional health department who plans bed capacity. One scenario: *where is the load,
why, what are the alternatives, what did a person decide*. Built strictly against the existing API
([docs/api.md](api.md)); it has no data or logic of its own beyond display formatting.

- Stack: React 18, Vite, TypeScript, react-router 7, TanStack Query 5, Recharts 3, Tailwind CSS 4 (npm, no CDN),
  ESLint + Prettier (defaults), Vitest + Testing Library. No component library.
- Language: Russian only; every user-visible string lives in `frontend/src/i18n/ru.ts` (the UI imports `t` from
  `src/i18n`, so another language is one more file with the same `Messages` shape).
- Runs: `make up` → http://localhost:3000 (nginx serves the build and proxies `/api` to the backend);
  `make web-dev` → http://localhost:5173 (Vite, `/api` proxied to `localhost:8000`; `API_PROXY_TARGET` to change).

## Screen map and API calls

All requests go to the same origin under `/api/v1` (`VITE_API_BASE` overrides it at build time).

| route | screen | API calls |
|---|---|---|
| `/` | **Обзор** — national KPIs (queue, median wait, refusal rate, hospitals with high load), data source and `as_of_date`, regions table sortable by max load index, queue, refusal rate, median wait, high-load hospitals; row → region | `GET /overview` |
| `/regions/:code?profile=&offset=` | **Регион** — region KPIs; profile selector (profiles of the region, highest regional load first, names from the dictionary); status of the region × profile; hospitals of the selected profile ranked by `load_index` with status badge, queue, backlog, median wait, refusal rate, 14-day forecast, excess trend; row → card. Profile and page live in the URL | `GET /regions/{code}`, `GET /dictionaries`, `GET /regions/{code}/hospitals?profile=&limit=50&offset=`, `GET /overview` (national median trend for the column hint) |
| `/hospitals/:org/profiles/:profile` | **Карточка стационара** (top to bottom): header with name, region, profile, rank, status badge, `load_index` with its three component bars and a formula tooltip; KPI strip (queue, backlog, median wait, refusal rate, registrations 28 d, forecast 14 d); chart; «Почему»; «Рекомендации» with decision form and history; «Направления» | see below |
| `/alerts?region=&offset=` | **Сигналы** — alerts with reasons, status, index, queue, backlog, refusal rate, excess trend; region filter; link to the card | `GET /alerts?region=&limit=50&offset=`, `GET /dictionaries` |
| `/models` | **О моделях** — per model: title, version, training date, train / test (or backtest) windows, headline metrics vs the best baseline on the same rows, limitations paragraph | `GET /models` |
| every screen | header shows «Данные на dd.mm.yyyy» | `GET /health` |

Hospital card, section by section:

| section | API call | notes |
|---|---|---|
| header, KPI strip | `GET /hospitals/{org}/profiles/{profile}` → `status` | component bars show `components.*_score`; weights 60 / 25 / 15 % are fixed in the UI (docs/api.md §3) |
| chart | same response → `series`, `forecast` | bars: registrations, hospitalizations, refusals; line: queue (right axis); after the dashed «сегодня» marker (`as_of_date`) the 14-day forecast of registrations and hospitalizations as dashed lines on a shaded band; `forecast.note` under the chart. **No queue forecast is drawn** (the API does not return one) |
| Почему | same response → `explanation_factors` | two lists (wait time, refusal risk): arrow icon + title for direction, short feature label (`t.features`, API label as tooltip), `most_common_value_display`, mean effect in дн. / п.п., share of referrals with the factor in their top 5 |
| Рекомендации | `GET …/recommendations` | alternatives with current vs alternative wait, delta, refusal rates, backlogs, the API's Russian explanation, badge «оценка по историческим медианам», rule text, `reason` when there are none, `disclaimer`. Persistent line «Решение принимает специалист. Система только предлагает.» |
| decision form | `POST /decisions` | Подтвердить / Отклонить / Отложить open a small form (comment, actor; actor required and remembered in `localStorage`); body carries `region_code`, `org_code`, `profile_code`, `recommendation_id`, `action`; on 201 the history query is invalidated |
| История решений | `GET /decisions?org=&profile=&limit=100` | newest first; the alternative is shown by the org code at the end of `recommendation_id` |
| Направления | `GET …/referrals?sort=risk\|wait&limit=20&offset=` | server-side sort and paging; expandable row with the top-5 factors of both models (`value_display`, effect in дн. / п.п.) |

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
│   ├── api/          schema.ts (runtime response checks), types.ts (schemas → TS types), client.ts (fetch,
│   │                 ApiError with URL), queries.ts (TanStack Query hooks and keys)
│   ├── i18n/         ru.ts (all strings), index.ts (`t`)
│   ├── lib/          format.ts (numbers, days, %, dates), paths.ts (links), features.ts (short factor labels)
│   ├── components/   Layout, DataTable, StatusBadge, LoadIndexBars, InfoTip, Kpi, Pagination, Skeleton,
│   │                 ErrorState, QueryState, PageHeader, Direction, icons
│   ├── pages/        OverviewPage, RegionPage, AlertsPage, ModelsPage, NotFoundPage,
│   │                 hospital/ (HospitalPage, CardHeader, SeriesChart, WhyPanel, Recommendations, ReferralsTable)
│   ├── test/         setup.ts, mockApi.ts, fixtures/*.json (responses captured from the running API), routes.test.tsx
│   ├── routes.tsx    route table
│   └── main.tsx      QueryClient + router
├── Dockerfile        node:22-alpine build → nginx:1.29-alpine
├── nginx.conf        SPA fallback, /api proxy to backend:8000, asset caching, /healthz
└── package.json      scripts: dev, build, lint, format, test
```

Every API response is validated at runtime against the schema in `src/api/types.ts` (mirroring
`backend/app/schemas`); a changed field fails loudly with its path instead of rendering an empty cell.

## Tests and checks

| command | what |
|---|---|
| `make web-test` | Vitest (24 tests): every route renders with real captured responses; the decision form POSTs the expected body; the API-down message shows the URL; the client parses every endpoint's captured response **and the JSON examples of docs/api.md §6** (placeholders `…` stripped), and reports shape errors with the field path; formatting |
| `make web-lint` | ESLint (typescript-eslint, react-hooks) + `prettier --check` |
| `make web-build` | `tsc -b` + Vite production build |
| `make audit` | runs web-lint and web-build too (when `frontend/package.json` exists) |

Fixtures in `src/test/fixtures/` were captured from `make up` and trimmed (fewer regions / profiles); refresh them
when the API contract changes.

## API gaps found while building the UI

The backend was not changed in this step. Things the UI works around:

1. **No model limitations in `GET /models`.** The limitations paragraphs are copied from `docs/model_card.md` §5/§7
   into `ru.ts` and can drift. Suggest a `limitations` (and `intended_use`) field per model.
2. **`load_index` weights and caps are not in the API** (only the component scores and, in `/overview`, the status
   thresholds). The UI hard-codes 60 / 25 / 15 % and the formula text. Suggest `thresholds.load_index_weights` and
   caps in `/overview` (they are already in `mart_build_info.config`).
3. **Decisions do not carry the alternative.** `GET /decisions` returns only `recommendation_id`; the history shows
   the alternative's org code parsed from the id format `rec-v1:…:<alternative org>`. Suggest
   `alternative_org_code` / `alternative_org_name` in `Decision`.
4. **No diagnosis name on referrals** — only `icd10_code` (the explanations have names for 3-character codes only).
5. **Short feature labels.** Explanation factors have long labels ("медианное ожидание в стационаре по профилю до даты
   направления, дней"); the UI keeps its own short labels per feature. Suggest a `short_label`.
6. **Per-referral factor units are implicit.** `effect` is days for `wait_time` and a probability share for
   `refusal_risk`; the unit is inferred from the list key (the card-level factors carry `unit`, referral factors do not).
7. **No data-source description** in `/health` or `/overview`; the source line under the KPIs is static text.
8. **Alerts cannot be filtered by profile or status**, and alert items lack `status_label` / `region_rank`.
9. **`POST /decisions` is not idempotent**: a double submit creates two rows (the UI disables the button while the
   request is pending).
10. Doc inconsistency: the `GET …/recommendations` example in docs/api.md still shows `current.load_index` 98.6
    (the value before the excess-trend fix; the live API returns 96.6).
