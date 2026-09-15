import { useModels } from "../api/queries";
import type { MetricRow, ModelInfo } from "../api/types";
import { PageHeader } from "../components/PageHeader";
import { QueryState } from "../components/QueryState";
import { BlockSkeleton } from "../components/Skeleton";
import { t } from "../i18n";
import { fmtDate, fmtDateTime, fmtNumber, fmtPercent } from "../lib/format";

type MetricSpec = {
  key: string;
  better: "lower" | "higher";
  format: (v: number) => string;
};

// headline metrics per model (docs/model_card.md §5); "best baseline" = best on the first metric
const METRICS: Record<string, MetricSpec[]> = {
  wait_time: [
    { key: "mae", better: "lower", format: (v) => fmtNumber(v, 1) },
    { key: "wape", better: "lower", format: (v) => fmtPercent(v) },
    { key: "within_7d", better: "higher", format: (v) => fmtPercent(v) },
    { key: "spearman", better: "higher", format: (v) => fmtNumber(v, 2) },
  ],
  refusal_risk: [
    { key: "roc_auc", better: "higher", format: (v) => fmtNumber(v, 3) },
    { key: "pr_auc", better: "higher", format: (v) => fmtNumber(v, 3) },
    { key: "brier", better: "lower", format: (v) => fmtNumber(v, 4) },
    { key: "precision_top", better: "higher", format: (v) => fmtPercent(v) },
  ],
};

const numeric = (row: MetricRow, key: string): number | null =>
  typeof row[key] === "number" ? (row[key] as number) : null;
const text = (row: MetricRow, key: string): string =>
  typeof row[key] === "string" ? (row[key] as string) : "";

function bestBaseline(
  baselines: MetricRow[],
  spec: MetricSpec,
): MetricRow | undefined {
  const scored = baselines.filter((b) => numeric(b, spec.key) !== null);
  return scored.sort((a, b) => {
    const diff = (numeric(a, spec.key) ?? 0) - (numeric(b, spec.key) ?? 0);
    return spec.better === "lower" ? diff : -diff;
  })[0];
}

function cell(row: MetricRow | undefined, spec: MetricSpec) {
  const v = row ? numeric(row, spec.key) : null;
  return v === null ? t.common.noData : spec.format(v);
}

function ReferralModelTable({ model }: { model: ModelInfo }) {
  const specs = METRICS[model.model_name] ?? [];
  const headline = model.headline[0];
  const best = specs[0] ? bestBaseline(model.baselines, specs[0]) : undefined;
  return (
    <table className="w-full border-collapse text-[15px]">
      <thead>
        <tr className="border-b-2 border-line bg-[#eef1f5]">
          <th scope="col" className="px-3 py-2 text-left">
            {t.models.metric}
          </th>
          <th scope="col" className="px-3 py-2 text-right">
            {t.models.model}
          </th>
          <th scope="col" className="px-3 py-2 text-right">
            {t.models.bestBaseline}
            {best ? (
              <span className="block text-sm font-normal text-muted">
                {named(text(best, "model"))}
              </span>
            ) : null}
          </th>
        </tr>
      </thead>
      <tbody>
        {specs.map((spec) => (
          <tr key={spec.key} className="border-b border-line/70">
            <th scope="row" className="px-3 py-2 text-left font-medium">
              {t.models.metricNames[spec.key] ?? spec.key}{" "}
              <span className="text-sm font-normal text-muted">
                (
                {spec.better === "lower"
                  ? t.models.betterLower
                  : t.models.betterHigher}
                )
              </span>
            </th>
            <td className="num px-3 py-2 font-semibold">
              {cell(headline, spec)}
            </td>
            <td className="num px-3 py-2">{cell(best, spec)}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function ForecastModelTable({ model }: { model: ModelInfo }) {
  const wape: MetricSpec = {
    key: "wape",
    better: "lower",
    format: (v) => fmtPercent(v),
  };
  return (
    <table className="w-full border-collapse text-[15px]">
      <thead>
        <tr className="border-b-2 border-line bg-[#eef1f5]">
          <th scope="col" className="px-3 py-2 text-left">
            {t.models.target}
          </th>
          <th scope="col" className="px-3 py-2 text-left">
            {t.models.series}
          </th>
          <th scope="col" className="px-3 py-2 text-right">
            {t.models.model}, WAPE{" "}
            <span className="block text-sm font-normal text-muted">
              {t.models.betterLower}
            </span>
          </th>
          <th scope="col" className="px-3 py-2 text-right">
            {t.models.bestBaseline}, WAPE
          </th>
        </tr>
      </thead>
      <tbody>
        {model.headline.map((row) => {
          const peers = model.baselines.filter(
            (b) =>
              text(b, "target") === text(row, "target") &&
              text(b, "series_level") === text(row, "series_level"),
          );
          const best = bestBaseline(peers, wape);
          return (
            <tr
              key={`${text(row, "target")}-${text(row, "series_level")}`}
              className="border-b border-line/70"
            >
              <td className="px-3 py-2">
                {t.models.targets[text(row, "target")] ?? text(row, "target")}
              </td>
              <td className="px-3 py-2">
                {t.models.seriesLevels[text(row, "series_level")] ??
                  text(row, "series_level")}
              </td>
              <td className="num px-3 py-2 font-semibold">{cell(row, wape)}</td>
              <td className="num px-3 py-2">
                {cell(best, wape)}
                {best ? (
                  <span className="block text-sm text-muted">
                    {named(text(best, "method"))}
                  </span>
                ) : null}
              </td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}

const named = (name: string) => t.models.methodNames[name] ?? name;

function windowText(value: unknown): string {
  return Array.isArray(value) && value.length === 2
    ? `${fmtDate(String(value[0]))} — ${fmtDate(String(value[1]))}`
    : t.common.noData;
}

function ModelCard({ model }: { model: ModelInfo }) {
  const testRows =
    model.population && typeof model.population.test_rows === "number"
      ? model.population.test_rows
      : null;
  return (
    <article
      className="card space-y-4 p-5"
      aria-labelledby={`model-${model.model_name}`}
    >
      <header className="space-y-1">
        <h2 id={`model-${model.model_name}`} className="text-xl font-semibold">
          {model.title}
        </h2>
        <dl className="flex flex-wrap gap-x-6 gap-y-1 text-sm">
          {[
            [t.models.version, model.version],
            [t.models.trainedAt, fmtDateTime(model.trained_at)],
            // referral models: train / test; load forecast: series selection, backtest origins, data through
            ...(model.train_window.train
              ? [
                  [t.models.trainWindow, windowText(model.train_window.train)],
                  [t.models.testWindow, windowText(model.train_window.test)],
                ]
              : [
                  [
                    t.models.seriesSelection,
                    windowText(model.train_window.series_selection),
                  ],
                  [
                    t.models.backtestOrigins,
                    Array.isArray(model.train_window.backtest_origins)
                      ? model.train_window.backtest_origins
                          .map((d) => fmtDate(String(d)))
                          .join(", ")
                      : t.common.noData,
                  ],
                  [
                    t.models.dataThrough,
                    fmtDate(
                      String(model.train_window.final_model_data_through ?? ""),
                    ),
                  ],
                ]),
            ...(testRows !== null
              ? [[t.models.population, t.models.testRows(testRows)]]
              : []),
          ].map(([label, value]) => (
            <div key={label} className="flex gap-1.5">
              <dt className="text-muted">{label}:</dt>
              <dd className="font-medium tabular-nums">{value}</dd>
            </div>
          ))}
        </dl>
      </header>
      <div className="overflow-x-auto">
        {model.model_name === "load_forecast" ? (
          <ForecastModelTable model={model} />
        ) : (
          <ReferralModelTable model={model} />
        )}
      </div>
      {model.beats_baselines !== null ? (
        <p className="font-medium">
          {model.beats_baselines ? t.models.beatsYes : t.models.beatsNo}
        </p>
      ) : null}
      {t.models.limitations[model.model_name] ? (
        <div>
          <h3 className="font-semibold">{t.models.limitationsTitle}</h3>
          <p className="leading-relaxed">
            {t.models.limitations[model.model_name]}
          </p>
        </div>
      ) : null}
    </article>
  );
}

export function ModelsPage() {
  const models = useModels();
  return (
    <>
      <PageHeader title={t.models.title}>
        <p className="max-w-4xl text-muted">{t.models.intro}</p>
      </PageHeader>
      <QueryState query={models} skeleton={<BlockSkeleton height="h-96" />}>
        {(data) => (
          <div className="space-y-5">
            {data.map((model) => (
              <ModelCard key={model.model_name} model={model} />
            ))}
          </div>
        )}
      </QueryState>
    </>
  );
}
