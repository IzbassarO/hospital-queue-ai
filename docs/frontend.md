# Frontend — Control Tower Experience v1

The Kazakhstan Hospital Flow Control Tower presents published signals, forecasts and versioned evidence for human decision support. ML CORE remains closed/frozen. Pressure means `historical_flow_proxy_v1`; it does not measure physical capacity. Decision alternatives remain retrospective mathematical alternatives for human review and are shown only as an assurance capability.

The stack remains React 18, TypeScript, Vite, React Router, TanStack Query, Recharts and Tailwind. No new dependency was added. Russian UI copy is in `src/i18n/tower.ts`, composed into `ru.ts` and exposed through the existing `t` entry point. Published evidence narratives are displayed verbatim.

## Data boundary

`src/api/generated` (OpenAPI-owned transport types) → `operational-schemas.ts` (runtime response guards, checked against generated DTOs) → `operational-adapters.ts` (semantic view models) → `operational.ts` (fetch/query hooks) → pages and `components/control`.

The shared client still handles authentication, HTTP/network errors and JSON decoding. Runtime guards supply only explicit backend defaults for omitted optional properties; supplied values are validated without numeric coercion. The adapters only format labels, numbers and dates, group forecast points by publication/series/origin/target, and suppress unsupported chart points. Severity and inbox rank are displayed as published. The frontend never reads ML artifacts, fits models, reconstructs intervals, or computes scientific ranking.

All endpoint paths below are prefixed with `/api/v1`. The shell calls `/operational-intelligence/overview` for publication state and retains `/me` for the role. `/dictionaries` is retained for region/profile names. Hospital names are absent from these DTOs, so hospital codes are explicitly labelled.

## Routes, queries and actual consumers

Let `OI` mean `/operational-intelligence` in this table.

| Screen / route | Removed from mounted screen | New calls, hooks, adapters and consumers | Behavior proof in `src/test/routes.test.tsx` |
| --- | --- | --- | --- |
| Overview `/` | `/overview` (`useOverview`), `/config` (`useConfig`) | `OI/overview` → `useOperationalOverview` → `overviewView` → `OverviewPage`, `Publication`, `Summary`, regional matrix; `OI/signals?limit=5&offset=0` → `useSignals` → `signalView` → `SignalList`; `OI/forecasts?level=national&origin=…&limit=500&offset=…` → `useForecasts` → `forecastGroups` → `ForecastPanel` | “Overview renders operational counts, region matrix, server-ranked signals and national forecast” asserts response values and exact endpoint/filter use |
| Signals `/signals`; compatibility `/alerts` | `/alerts` (`useAlerts`), `/config` | `OI/signals?region=&profile=&severity=&support=&org=&limit=20&offset=` → `useSignals` → `signalView` → `AlertsPage` / `SignalList`; `OI/overview` → `useOperationalOverview` → `overviewView` → `Publication` | Both route aliases render; server filter results, URL state, pagination reset, rank and separate severity/support styles are asserted |
| Investigation `/signals/:signalId` | New screen | `OI/signals/{id}` → `useSignal` → `signalView` → `SignalPage`; `OI/forecasts?origin=&org=&region=&profile=&target=&level=&limit=500&offset=` → `useForecasts` → `forecastGroups` → `ForecastPanel` | “Signal detail loads its endpoint…” checks limitations, historical reference, interval values, coverage and matching forecast query |
| Explanation drawer | New experience; old hospital factor panel is unmounted | `OI/signals/{id}/explanation` → `useExplanation` → `explanationView` → `ExplanationDrawer`, requested on open | “Explain opens a deterministic evidence drawer…” proves endpoint, all sections, focus trap, Escape, inert background and focus restoration; fallback, error and publication mismatch tests |
| Region `/regions/:code?profile=` | `/regions/{code}` (`useRegion`), `/regions/{code}/hospitals` (`useRegionHospitals`), `/overview`, `/config` | `OI/regions/{code}` → `useOperationalRegion` → `regionView` → `RegionPage`, `Summary`, `Publication`; `OI/signals?region=&profile=&limit=10&offset=0` → `useSignals` → `signalView` → `SignalList`; `OI/forecasts?level=region&region=&profile=&origin=…` → `useForecasts` → `forecastGroups` → `ForecastPanel` | “Region → hospital drill-down calls the new contracts” proves regional request, profile filtering and hospital navigation |
| Hospital/profile `/hospitals/:org/profiles/:profile` | `/hospitals/{org}/profiles/{profile}` (`useHospitalCard`), its `/recommendations`, `/referrals`, `/export` subpaths and `/decisions` (GET/POST) are unmounted | `OI/hospitals/{org}/profiles/{profile}` → `useOperationalHospital` → `hospitalView` → `HospitalPage`, `Summary`, `SignalList`, `Publication`; `OI/forecasts?level=hospital&org=&profile=&origin=…` → `useForecasts` → `forecastGroups` → `ForecastPanel` | Same drill-down test proves hospital endpoint and hospital forecast request; separate loading, error, absent-object and empty-signal tests |
| Evidence & Assurance `/assurance`; compatibility `/models` | `/models` (`useModels`) | `/model-assurance` and `/model-assurance/capabilities` → `useAssurance` → `assuranceView` / `capabilityView` → `ModelsPage` capability cards | Both aliases prove rejected/not-for-product, acceptance, evaluation-only, governance and collapsed identities |

The assurance query reads snapshot → capabilities → snapshot and rejects a detected active-identity change. Signal lists, forecasts and explanations check publication identity before being combined with an existing context. This detects observed changes; the API does not offer pinned snapshot queries and cannot provide a multi-request transaction.

## Product experience

Navigation is Overview → Signals → Evidence & Assurance. Region and hospital routes are drill-down destinations. `/alerts` and `/models` remain functional aliases. Old `status=high|elevated|normal|insufficient_data` signal links map to the corresponding severity enum; region/profile query parameters are retained. The old regional `offset` no longer pages a legacy hospital table.

Overview shows published signal counts, severity distribution, support mix, a regional matrix, the first five server-ranked signals and a selectable national forecast series. Counts include all published signal states and are not described as patients, live events or physical capacity. No map geometry is fabricated. No client-side severity sorting is applied.

Signals expose region, profile, severity and support filters supported by the API. `org` deep-link filtering is also retained. The `FALLBACK_LIMITED` support filter selects limited fallback support; there is no invented independent fallback-status API filter. Each row separates severity, support and fallback, shows forecast/interval/materiality, preserves rank and provides Investigate / Why this signal actions.

Investigation displays the subject, signal type, date, target, forecast, calibrated bounds, historical reference/status, materiality, first crossing/lead time, reason codes, evidence facts and limitations. Observed anomaly fields are kept separate from preventive pressure. The drawer presents summary, why flagged, key evidence, uncertainty, support, limitations, review questions, provenance and generation mode. Review questions are not presented as instructions or recommendations. Returned human-review, autonomy, capacity-check and causal-claim governance is visible in the drawer. No prompts are exposed.

`ForecastChart` uses Recharts with a central line and a calibrated range area. Raw quantiles are never substituted for calibrated intervals. Unsupported points create gaps. Dates are ordered for display within a single series/origin/target; distinct series are selectable, not merged. The API does not supply an observed time series, which is stated explicitly. An expandable numeric table exposes dates, central semantics, calibrated bounds, nominal coverage, support/fallback and uncertainty state. A 500-point page can be partial; pagination and a partial-data notice in the chart caption remain visible. Pages are not accumulated into a complete curve. A matching series absent from the current page is described as absent on this page, not unpublished.

Assurance cards show capability evidence status, acceptance verdict, product consumption, support semantics, freshness reason, limitations and governance independently. Rejected challengers remain rejected/not for product. Decision alternatives remain evaluation only. Identity hashes are inside disclosure sections. Model metrics are not re-ranked in the browser.

## States, accessibility and motion

- `EvidenceState` provides loading skeletons, missing-publication/object state, auth/forbidden messages, malformed-response failure and retryable network/server errors. Empty lists/charts have explicit text.
- `Publication` separates date of origin, publication time, publication status and freshness. UNKNOWN, STALE, DEGRADED and EMPTY have deliberate messages; freshness is not inferred from timestamps.
- Semantic headings, table captions/header scopes, visible focus, skip-to-main link, labelled filters and textual severity/support cues. Support uses neutral borders, including dashed fallback styling; severity colours only reflect API severity.
- Drawer has `role=dialog`, accessible title, `aria-modal`, initial close-button focus, Tab/Shift-Tab containment, Escape, background `inert`, body scroll lock and focus restoration.
- Maximum content width 1440px, flexible grids, locally scrollable tables and a drawer capped at 680px. No fixed 1024px body minimum.
- CSS page/card reveal, KPI fade, chart reveal, drawer entry, bounded skeleton shimmer and hover/focus transitions. No animation dependency. `prefers-reduced-motion` disables all animations/transitions; Recharts animation is disabled so chart motion is not required to understand values.

## Remaining legacy code

`src/api/client.ts`, `queries.ts`, `types.ts` and legacy runtime schemas still retain the old transport helpers. Only `/me` and `/dictionaries` are used by the new route tree. These retained hospital components are **not mounted**: `CardHeader`, `SeriesChart`, `WhyPanel`, `Recommendations`, `ReferralsTable`, `ExportButtons`. They retain their legacy recommendation/decision/referral/export logic. Their previous route-level behavior is not claimed as part of this slice. Remounting them would reintroduce legacy calls and terminology; the route tests reject those calls. The existing hospital summary API returns at most 500 signals and derives counts from those rows; the UI cannot establish a full total from that response. For larger subjects, use the Signals inbox with org/profile filters. This backend limitation is deferred; no contract is changed here. The old registry/metric fixtures and client tests remain for those retained helpers.

## Running and verification

`make web-dev` serves the frontend with the same-origin API proxy. `make up` builds the stack. Existing proxy authentication remains unchanged: nginx/Vite adds `X-API-Key` server-side; supported builds do not embed credentials. See [security.md](security.md).

From `frontend`: `npm test`, `npm run lint`, `npm run typecheck`, `npm run build`. From repository root: `make audit`, `git diff --check`, `git status`. The audit checks generation against `backend/openapi.json` in a temporary directory; generated files are not edited by hand.

Route tests use synthetic typed API fixtures and a fetch mock that rejects legacy metric calls. They exercise actual client parsing, adapters, hooks and rendering rather than mocking the hooks. Adapter tests additionally protect series isolation, unsupported gaps, server-owned severity/rank and assurance publication changes. Existing API client/format tests remain.

A populated demo requires current Model Assurance and Operational Intelligence publications in PostgreSQL. On 2026-09-22 the existing local proxy returned 404 for both current publications. Browser validation used synthetic fixtures against the production frontend build; no evidence was regenerated or published. This is a demo-data prerequisite, not a frontend contract defect. Full review results are in [control-tower-slice-4.md](control-tower-slice-4.md).
