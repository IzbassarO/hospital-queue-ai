import { useSearchParams } from "react-router-dom";
import {
  useOperationalOverview,
  useSignals,
  type SignalFilters,
} from "../api/operational";
import { useDictionaries } from "../api/queries";
import { label } from "../api/operational-adapters";
import { PageHeader } from "../components/PageHeader";
import { Pagination } from "../components/Pagination";
import {
  EvidenceState,
  Notice,
  Publication,
} from "../components/control/Evidence";
import { SignalList } from "../components/control/SignalList";
import { t } from "../i18n";

const severities = [
  "HIGH",
  "ELEVATED",
  "WATCH",
  "NORMAL",
  "UNSUPPORTED",
] as const;
const supports = [
  "DIRECT_SUPPORTED",
  "FALLBACK_LIMITED",
  "UNSUPPORTED",
] as const;
const valid = <T extends string>(
  values: readonly T[],
  value: string | null,
): T | undefined => values.find((v) => v === value);
const FILTERS = ["region", "profile", "severity", "support"] as const;
export function AlertsPage() {
  const [params, setParams] = useSearchParams();
  const offsetValue = Number(params.get("offset") ?? 0);
  const offset =
    Number.isSafeInteger(offsetValue) && offsetValue >= 0 ? offsetValue : 0;
  // Old status links retain their meaning where the old vocabulary has a counterpart.
  const legacy = params.get("status");
  const legacySeverity =
    legacy === "insufficient_data" ? "UNSUPPORTED" : legacy?.toUpperCase();
  const filters: SignalFilters = {
    org: params.get("org") || undefined,
    region: params.get("region") || undefined,
    profile: params.get("profile") || undefined,
    severity: valid(
      severities,
      params.get("severity") ?? legacySeverity ?? null,
    ),
    support: valid(supports, params.get("support")),
  };
  const query = useSignals({ ...filters, limit: 20, offset });
  const overview = useOperationalOverview();
  const dictionaries = useDictionaries();
  function change(key: string, value: string) {
    const next = new URLSearchParams(params);
    next.delete("offset");
    next.delete("status");
    if (key !== "severity" && filters.severity)
      next.set("severity", filters.severity);
    if (value) next.set(key, value);
    else next.delete(key);
    setParams(next);
  }
  const options = {
    region:
      dictionaries.data?.regions.map((r) => ({
        value: r.code,
        name: r.name,
      })) ?? [],
    profile:
      dictionaries.data?.profiles.map((p) => ({
        value: p.code,
        name: p.name,
      })) ?? [],
    severity: severities.map((value) => ({ value, name: label(value) })),
    support: supports.map((value) => ({ value, name: label(value) })),
  };
  return (
    <div className="space-y-6 page-reveal">
      <PageHeader title={t.tower.signals}>
        <p className="text-muted">{t.tower.rankHint}</p>
      </PageHeader>
      <EvidenceState query={overview}>
        {(data) => <Publication snapshot={data.snapshot} />}
      </EvidenceState>
      <div
        className="card grid gap-4 p-4 sm:grid-cols-2 xl:grid-cols-4"
        role="group"
        aria-label={t.tower.signals}
      >
        {FILTERS.map((key) => (
          <div key={key}>
            <label
              className="mb-1 block text-sm font-medium"
              htmlFor={`signal-${key}`}
            >
              {t.tower[key]}
            </label>
            <select
              id={`signal-${key}`}
              className="field"
              value={filters[key] ?? ""}
              onChange={(e) => change(key, e.target.value)}
            >
              <option value="">{t.tower.all}</option>
              {filters[key] &&
              !options[key].some((o) => o.value === filters[key]) ? (
                <option value={filters[key] ?? ""}>{filters[key]}</option>
              ) : null}
              {options[key].map((o) => (
                <option key={o.value} value={o.value}>
                  {o.name}
                </option>
              ))}
            </select>
          </div>
        ))}
      </div>
      {dictionaries.isError ? (
        <Notice>{t.tower.namesUnavailable}</Notice>
      ) : null}
      <EvidenceState query={query}>
        {(data) => (
          <>
            <p className="text-sm text-muted">{t.common.total(data.total)}</p>
            <SignalList
              signals={data.items}
              identity={overview.data?.snapshot.identity}
            />
            <Pagination
              total={data.total}
              limit={data.limit}
              offset={offset}
              busy={query.isFetching}
              onChange={(next) => {
                const search = new URLSearchParams(params);
                search.set("offset", String(next));
                setParams(search);
              }}
            />
          </>
        )}
      </EvidenceState>
    </div>
  );
}
