import { useId, useState } from "react";
import {
  Area,
  CartesianGrid,
  ComposedChart,
  Line,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { useForecasts, type ForecastFilters } from "../../api/operational";
import { number, type ForecastSeries } from "../../api/operational-adapters";
import { t } from "../../i18n";
import { fmtDate } from "../../lib/format";
import {
  EvidenceState,
  Empty,
  Limitations,
  Notice,
  Provenance,
} from "./Evidence";

export function ForecastChart({
  series,
  partial = false,
}: {
  series: ForecastSeries;
  partial?: boolean;
}) {
  const id = useId();
  const hasForecast = series.points.some((p) => p.central !== null);
  return (
    <figure className="card space-y-4 p-5 chart-reveal" aria-labelledby={id}>
      <figcaption id={id}>
        <h3 className="font-semibold">
          {series.target} · {series.profile ?? series.seriesId}
        </h3>
        <p className="text-sm text-muted">
          {t.tower.origin}: {fmtDate(series.origin)} · {t.tower.forecast} /{" "}
          {t.tower.interval}
        </p>
        {partial ? (
          <p className="text-sm font-medium">{t.tower.partialForecast}</p>
        ) : null}
      </figcaption>
      {!hasForecast ? (
        <Empty>{t.tower.status.UNSUPPORTED}</Empty>
      ) : (
        <div
          className="h-72 min-w-0"
          aria-label={`${t.tower.forecast} · ${t.tower.interval}`}
        >
          <ResponsiveContainer
            width="100%"
            height="100%"
            minWidth={0}
            initialDimension={{ width: 700, height: 288 }}
          >
            <ComposedChart
              data={series.points}
              margin={{ left: 0, right: 12, top: 10, bottom: 8 }}
              accessibilityLayer
            >
              <CartesianGrid
                stroke="#dce3e7"
                strokeDasharray="3 3"
                vertical={false}
              />
              <XAxis dataKey="date" tickFormatter={fmtDate} minTickGap={35} />
              <YAxis width={48} />
              <Tooltip
                labelFormatter={(v) => fmtDate(String(v))}
                formatter={(v, name) => [
                  Array.isArray(v)
                    ? `${number(Number(v[0]))} – ${number(Number(v[1]))}`
                    : number(v == null ? null : Number(v)),
                  name,
                ]}
              />
              <Area
                dataKey="interval"
                name={t.tower.interval}
                type="linear"
                stroke="none"
                fill="#9bbbd1"
                fillOpacity={0.45}
                connectNulls={false}
                isAnimationActive={false}
              />
              <Line
                dataKey="central"
                name={t.tower.forecast}
                type="linear"
                stroke="#18576b"
                strokeWidth={2.5}
                dot={{ r: 3 }}
                connectNulls={false}
                isAnimationActive={false}
              />
            </ComposedChart>
          </ResponsiveContainer>
        </div>
      )}
      {series.points.some((p) => p.interval === null) ? (
        <Notice>{t.tower.noInterval}</Notice>
      ) : null}
      <p className="text-sm text-muted">{t.tower.noObserved}</p>
      <details>
        <summary>{t.tower.values}</summary>
        <div className="mt-3 overflow-x-auto">
          <table className="evidence-table">
            <caption className="sr-only">{t.tower.values}</caption>
            <thead>
              <tr>
                {[
                  t.tower.date,
                  t.tower.forecast,
                  t.tower.interval,
                  t.tower.coverage,
                  t.tower.support,
                  t.tower.fallback,
                  t.tower.uncertainty,
                ].map((h) => (
                  <th scope="col" key={h}>
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {series.points.map((p) => (
                <tr key={p.date}>
                  <th scope="row">{fmtDate(p.date)}</th>
                  <td>
                    {number(p.central)}
                    <small className="block">{p.semantics}</small>
                  </td>
                  <td>
                    {p.interval
                      ? p.interval.map(number).join(" – ")
                      : t.common.noData}
                  </td>
                  <td>{p.coverage}</td>
                  <td>{p.support}</td>
                  <td>{p.fallback}</td>
                  <td>{p.uncertainty}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </details>
      <Limitations items={series.limitations} />
      <Provenance items={series.provenance} />
    </figure>
  );
}
export function ForecastPanel({
  filters,
  identity,
  seriesId,
}: {
  filters: ForecastFilters;
  identity: string;
  seriesId?: string;
}) {
  // Parent keys the panel by context so pagination and selected series cannot leak across subjects.
  const [offset, setOffset] = useState(0);
  const [selected, setSelected] = useState("");
  const id = useId();
  const query = useForecasts({ ...filters, limit: 500, offset });
  return (
    <section className="space-y-3">
      <h2 className="text-xl font-semibold">{t.tower.outlook}</h2>
      <EvidenceState query={query}>
        {(data) => {
          if (data.series.some((s) => s.identity !== identity))
            return <Notice>{t.tower.publicationChanged}</Notice>;
          const series = seriesId
            ? data.series.filter((s) => s.seriesId === seriesId)
            : data.series;
          const active = series.find((s) => s.key === selected) ?? series[0];
          return (
            <>
              {data.total > data.limit ? (
                <Notice>{t.tower.partial}</Notice>
              ) : null}
              {series.length > 1 ? (
                <div>
                  <label
                    htmlFor={id}
                    className="mb-1 block text-sm font-medium"
                  >
                    {t.tower.series}
                  </label>
                  <select
                    className="field"
                    id={id}
                    value={active?.key ?? ""}
                    onChange={(e) => setSelected(e.target.value)}
                  >
                    {series.map((s) => (
                      <option key={s.key} value={s.key}>
                        {s.target} · {s.profile ?? s.seriesId} ·{" "}
                        {fmtDate(s.origin)}
                      </option>
                    ))}
                  </select>
                </div>
              ) : null}
              {active ? (
                <ForecastChart
                  key={active.key}
                  series={active}
                  partial={data.total > data.limit || data.offset > 0}
                />
              ) : (
                <Empty>
                  {data.total > data.limit || data.offset > 0
                    ? t.tower.noForecastOnPage
                    : t.tower.noForecast}
                </Empty>
              )}
              {data.total > data.limit ? (
                <div className="flex gap-2">
                  <button
                    className="btn"
                    disabled={offset === 0}
                    onClick={() => {
                      setOffset(Math.max(0, offset - 500));
                      setSelected("");
                    }}
                  >
                    {t.common.prevPage}
                  </button>
                  <span>
                    {t.common.page(
                      offset + 1,
                      Math.min(offset + 500, data.total),
                      data.total,
                    )}
                  </span>
                  <button
                    className="btn"
                    disabled={offset + 500 >= data.total}
                    onClick={() => {
                      setOffset(offset + 500);
                      setSelected("");
                    }}
                  >
                    {t.common.nextPage}
                  </button>
                </div>
              ) : null}
            </>
          );
        }}
      </EvidenceState>
    </section>
  );
}
