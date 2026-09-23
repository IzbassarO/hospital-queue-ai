# Control Tower Slice 4 — adversarial pre-commit review

Date: 2026-09-22. Verdict: **ACCEPT WITH FIXES (applied)**. No commit or push performed. Review began with the actual diff and included all 14 modified and 13 untracked files. ML science, backend contracts, generated transport and the dependency lockfile are unchanged.

## Findings, fixes and remaining risks

Five regressions were reproduced against the pre-review implementation (5 failing / 62 passing tests), then fixed:

| Priority | Finding | Applied fix and behavioral proof |
| --- | --- | --- |
| P1 | A forecast page containing matching and mismatching publication identities within the same series could conceal the second identity during grouping. | Group by publication identity as well as series/origin/target. The mounted forecast test supplies a matching row followed by a mismatching row and verifies the panel refuses to combine them. |
| P2 | Runtime guards rejected valid omitted optional fields declared with defaults by the backend contract. | Apply only the backend's explicit defaults to omitted properties. Contract tests preserve supplied values and reject a numeric string. No scientific value is inferred or coerced. |
| P2 | Editing another filter on a legacy `status=high` link discarded the mapped HIGH severity. | Preserve the canonical severity while updating another filter. The mounted test verifies both filters reach the endpoint. |
| P2 | Explanation capability governance was returned but lost by the adapter. | Preserve and visibly render human review, no autonomy, capacity not checked and no causal claim. The drawer test checks the returned governance labels. |
| P2 | A matching forecast absent from the first page was described as unpublished, even when available later. | Distinguish page absence from publication absence, keep a partial-series caption and do not accumulate pages. A 501-point test navigates from a nonmatching first page to the matching final point and checks offset, values and partial disclosure. |

P0: none found. P1 code defects: the mixed-publication issue above is fixed; none remain identified.

The local live-demo prerequisite remains unresolved: fresh read-only requests to `http://localhost:3000/api/v1/model-assurance` and `/api/v1/operational-intelligence/overview` both returned **404**. A populated live walkthrough is blocked until the existing publication workflow is completed. This is an environment/data prerequisite, not a demonstrated frontend or backend contract defect; no evidence was regenerated or published.

Deferred P2 limitations:

- The existing hospital/profile API fetches at most 500 signals and derives counts from those rows (`backend/app/services/operational_intelligence.py`, `hospital_profile`). At the cap, the response does not establish a complete total and the UI's count-based partial check cannot discover further rows. Use the Signals inbox's org/profile filters for paginated browsing. Backend completeness metadata is outside this slice.
- Current-snapshot requests cannot be pinned to an atomic publication. Identity guards detect observed disagreement, but cannot prove transaction consistency, detect an intervening change that returns to the original identity, or establish identity from an empty page. No stronger guarantee is claimed.
- Forecast pagination can split a series. Every partial chart is labelled; pages stay separate. Finding a particular series may require paging because there is no series-id endpoint filter.
- Hospital names and observed time series are absent from these DTOs; codes and an explicit observed-data absence message are used. Published evidence narratives may remain English.

Safe to commit this frontend slice with these limits recorded. It is not yet ready for a populated live-data demonstration.

## Package, transport, validation and security

`frontend/package.json` changes **only** its description, from `hospital-queue-ai web UI for regional bed-capacity planning specialists` to `Kazakhstan hospital flow Control Tower for human decision support`. This removes an inaccurate capacity claim. Dependencies, devDependencies, scripts and version are unchanged; dependency objects match both HEAD and `package-lock.json`. No lockfile edit is needed.

`client.ts` changes only the visibility of `request<T>` to export the existing shared transport. Authentication, HTTP/network errors and JSON decoding are unchanged. The file retains old transport methods; it does not read artifacts or compute scientific semantics. New query hooks use generated DTOs through handwritten runtime guards and view-model adapters. Numeric/date formatting, unit display, forecast grouping and masking unsupported points are presentation work; severity, rank, acceptance, support, pressure and calibration remain backend-owned.

`operational-schemas.ts` accepts the documented defaults without replacing supplied valid values. It rejects malformed shapes/enums/types; it is not a duplicate implementation of all backend scientific validators. Generated types are checked structurally and were not edited. `git diff --exit-code -- backend ml frontend/src/api/generated frontend/package-lock.json` passes.

The new mounted sources do not read local files, import `hqai_ml`, expose artifact paths, or add credentials. The pre-existing optional `VITE_API_KEY` transport mechanism is unchanged; supported builds leave it empty and use server-side proxy authentication. This review does not claim the historical mechanism was removed. The audit secret and built-bundle scans pass with zero findings.

## Completed screens and endpoint evidence

Completed: Overview, Signals Inbox, Signal Investigation, Region, Hospital/Profile, Evidence & Assurance, plus the shared explanation drawer and forecast panel. Navigation remains Overview → Signals → Evidence & Assurance. No new feature or redesign was introduced during this review.

The [migration table](frontend.md#routes-queries-and-actual-consumers) records the exact old endpoint, new endpoint, hook, adapter, consuming component and named behavior test for each screen. All paths use `/api/v1`; `OI` below is `/operational-intelligence`:

| Screen | Query → endpoint → adapter → consumer |
| --- | --- |
| Overview | `useOperationalOverview` → `OI/overview` → `overviewView` → `OverviewPage`/`Summary`/`Publication`/region matrix; `useSignals` → `OI/signals?limit=5&offset=0` → `signalView` → `SignalList`; `useForecasts` → `OI/forecasts` (national, current origin, limit 500, offset) → `forecastGroups` → `ForecastPanel`/`ForecastChart` |
| Signals (`/signals`, `/alerts`) | `useSignals` → `OI/signals` (region/profile/severity/support/org, limit 20, offset) → `signalView` → `AlertsPage`/`SignalList`; overview query → `overviewView` → `Publication` |
| Investigation | `useSignal(id)` → `OI/signals/{id}` → `signalView` → `SignalPage`; `useForecasts` → `OI/forecasts` (subject/origin/target/level, limit 500, offset) → `forecastGroups` → matching-series forecast panel |
| Explanation | `useExplanation(id)` → `OI/signals/{id}/explanation` → `explanationView` → `ExplanationDrawer`, requested on open |
| Region | `useOperationalRegion(code)` → `OI/regions/{code}` → `regionView` → `RegionPage`/`Summary`/`Publication`; `useSignals` → `OI/signals` (region/profile, limit 10) → `signalView` → `SignalList`; region-filtered `useForecasts` → `forecastGroups` → forecast panel |
| Hospital/Profile | `useOperationalHospital(org,profile)` → `OI/hospitals/{org}/profiles/{profile}` → `hospitalView` → `HospitalPage`/`Summary`/`SignalList`/`Publication`; hospital-filtered `useForecasts` → `forecastGroups` → forecast panel |
| Assurance (`/assurance`, `/models`) | `useAssurance` → `/model-assurance`, `/model-assurance/capabilities`, `/model-assurance` → `assuranceView`/`capabilityView` → `ModelsPage` |

Publication mismatch prevents displaying a signal list, forecast page or explanation as evidence matching its current context. Assurance reads snapshot → capabilities → snapshot and reports HTTP-style 409 when active identity changes. Forecast grouping now retains every encountered publication identity for that check.

## Legacy and claim-boundary review

Only `/me` (role) and `/dictionaries` (names) remain intentionally reachable legacy API calls from the mounted route tree. `/alerts` and `/models` are route aliases to migrated screens, not legacy endpoint calls. Mounted pages do not call `/overview`, `/alerts`, `/models`, `/config`, legacy hospital cards, recommendations, decisions, referrals or exports.

Old `client.ts`/`queries.ts`/`types.ts` transport helpers and these hospital components remain **unmounted**: `CardHeader`, `SeriesChart`, `WhyPanel`, `Recommendations`, `ReferralsTable`, `ExportButtons`. Legacy copy also remains in unused `ru.ts` namespaces. Remounting these components would reintroduce old terminology and calls; every route test rejects those calls. Harmless dead code was not deleted.

Explicit `rg -n -i` searched mounted shell/pages/control components, tower copy and new adapters/guards for `capacity|bed.capacity|free.beds|occupancy|optimizer|recommender|recommendation|routing|digital.twin|causal|intervention` and Russian equivalents. Every match was manually reviewed: the negative physical-capacity statement, “capacity not checked”, “causal effect not claimed”, and DTO/validator/adapter governance fields. No affirmative forbidden claim was found in mounted static copy. A separate legacy-hook/path search matched only the `/alerts` and `/models` active-navigation aliases. Shared mounted copy was inspected; dormant recommendation copy is not rendered. Free-form returned evidence is displayed verbatim rather than rewritten into new claims.

Pressure is explicitly `historical_flow_proxy_v1`. Rejected challenger/not-for-product and decision-alternative evaluation-only statuses remain visibly distinct. Human review, no autonomous action, capacity not checked and no causal claim are rendered. The explanation uses returned structured values, limitations and generation mode; deterministic modes do not claim an LLM. Suggested review questions retain a questions label.

Central forecasts and calibrated ranges use different visuals and labels. Raw quantiles do not substitute for calibrated bounds; uncertainty is not renamed confidence. Unsupported points form gaps. Series, target, origin and publication identities are not spliced together.

## Accessibility, motion and states

The shell includes a skip link, active navigation, role and publication/freshness states. Tables have captions/header scopes, controls have labels, focus is visible, and severity/support have non-color text cues. Region visualization is a labelled matrix, not a fabricated geographic map. No live status is inferred.

The drawer has an accessible modal title, initial focus, Tab/Shift-Tab trap, Escape dismissal, trigger-focus restoration, inert background and scroll lock. Returned limitations and governance are visible. CSS provides finite page/card/KPI/chart/drawer reveals and a bounded skeleton shimmer; `prefers-reduced-motion` disables animations and transitions, and Recharts animation is disabled.

All six screens have tested loading, missing-publication/object and retryable error states; additional tests cover empty, degraded/stale, malformed-response and missing-uncertainty states. Loading assertions target the main screen, not just the shared shell.

Earlier implementation verification used real Chrome at 1280 × 900 and 375 × 900 against synthetic API fixtures, confirming no document overflow/exceptions and verifying drawer focus/Escape/reduced motion. Those browser checks were not rerun during this adversarial review; the current behavior suite and production build were rerun after the fixes.

## Tests and final quality gates

- `npm test`: **67 passed**, 4 files: 41 route behavior tests, 5 operational adapter/contract tests, 21 retained client/format tests. Two tests were added; existing tests were strengthened for the remaining reproduced gaps.
- Tests use actual fetch/guards/adapters/hooks/rendering, not mocked hooks. Exact paths/filters and returned values are asserted; all route tests disallow legacy metric requests. Region and Hospital tests use distinct counts, forecast counts and a hospital-only headline so shared fixtures cannot falsely prove migration.
- `npm run lint`: PASS (ESLint and Prettier).
- `npm run typecheck`: PASS.
- `npm run build`: PASS (671 modules; JS 718.58 kB, gzip 216.11 kB).
- `git diff --check`: PASS.

Full `make audit`: **all 14 checks PASS**, exit 0. Database checks ran with authorized local network access; the audit includes deterministic ML contract tests, not training or evidence regeneration.

| Check | Result |
| --- | --- |
| layout | PASS — 311 files, zero outside allowed set |
| secrets | PASS — 311 files, zero findings |
| architecture | PASS — ARCH001–ARCH005; existing ARCH006 deferred |
| openapi | PASS — stable operation IDs, snapshot current |
| alembic | PASS — no model/migration drift |
| ruff | PASS — lint clean, 145 files formatted |
| pytest | PASS — 100 backend tests |
| ml-pytest | PASS — 259 deterministic contract tests |
| api-docs | PASS — 29 routes documented, zero mismatches |
| api-auth | PASS — 28 authenticated routes, two health exemptions |
| web-contract | PASS — generated transport current |
| web-lint | PASS — ESLint and Prettier |
| web-build | PASS — TypeScript and Vite |
| web-bundle | PASS — four built files, zero secret findings |

`git diff --check`, `git diff --stat` and `git status` were run. Tracked diff: 14 files, 1,580 insertions and 1,368 deletions; the 13 new files below are excluded from that stat. Nothing is staged, committed or pushed.

## Exact changed-file inventory

Modified tracked files (14):

```text
docs/frontend.md
frontend/index.html
frontend/package.json
frontend/src/api/client.ts
frontend/src/components/Layout.tsx
frontend/src/i18n/ru.ts
frontend/src/index.css
frontend/src/pages/AlertsPage.tsx
frontend/src/pages/ModelsPage.tsx
frontend/src/pages/OverviewPage.tsx
frontend/src/pages/RegionPage.tsx
frontend/src/pages/hospital/HospitalPage.tsx
frontend/src/routes.tsx
frontend/src/test/routes.test.tsx
```

New untracked files (13; ordinary `git diff --stat` excludes them):

```text
docs/control-tower-slice-4.md
frontend/src/api/operational-adapters.ts
frontend/src/api/operational-schemas.ts
frontend/src/api/operational.test.ts
frontend/src/api/operational.ts
frontend/src/components/control/Evidence.tsx
frontend/src/components/control/ExplanationDrawer.tsx
frontend/src/components/control/ForecastChart.tsx
frontend/src/components/control/SignalList.tsx
frontend/src/i18n/tower.ts
frontend/src/pages/SignalPage.tsx
frontend/src/test/operationalFixtures.ts
frontend/src/test/operationalMock.ts
```

Review fixes touched only `operational-schemas.ts`, `operational-adapters.ts`, `operational.test.ts`, `ExplanationDrawer.tsx`, `ForecastChart.tsx`, `tower.ts`, `AlertsPage.tsx`, `routes.test.tsx` and these two documentation files. Other slice files were inspected and retained.
