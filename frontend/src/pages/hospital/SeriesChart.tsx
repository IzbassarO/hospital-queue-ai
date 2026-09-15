import { useMemo } from "react";
import {
  Bar,
  CartesianGrid,
  ComposedChart,
  Legend,
  Line,
  ReferenceArea,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import type { HospitalCard } from "../../api/types";
import { Section } from "../../components/PageHeader";
import { t } from "../../i18n";
import { fmtDate, fmtDayMonth, fmtNumber } from "../../lib/format";

// one accent + neutrals; forecast = same hues, dashed, no fill
const COLORS = {
  registrations: "#1f5fae",
  hospitalizations: "#5b6b7f",
  refusals: "#b8c2ce",
  queue: "#1c2430",
};

type Row = {
  date: string;
  registrations?: number;
  hospitalizations?: number;
  refusals?: number;
  queue?: number;
  forecastRegistrations?: number;
  forecastHospitalizations?: number;
};

const SERIES_LABELS: Record<string, string> = {
  registrations: t.hospital.series.registrations,
  hospitalizations: t.hospital.series.hospitalizations,
  refusals: t.hospital.series.refusals,
  queue: t.hospital.series.queue,
  forecastRegistrations: t.hospital.series.forecastRegistrations,
  forecastHospitalizations: t.hospital.series.forecastHospitalizations,
};

export function SeriesChart({ card }: { card: HospitalCard }) {
  const { series, forecast } = card;
  const today = card.status.as_of_date;

  const rows = useMemo<Row[]>(() => {
    const observed: Row[] = series.map((p) => ({
      date: p.date,
      registrations: p.registrations,
      hospitalizations: p.hospitalizations,
      refusals: p.refusals,
      queue: p.queue,
    }));
    const predicted: Row[] = forecast.points.map((p) => ({
      date: p.date,
      forecastRegistrations: p.registrations,
      forecastHospitalizations: p.hospitalizations,
    }));
    return [...observed, ...predicted];
  }, [series, forecast.points]);

  const first = series[0]?.date;
  const lastForecast = forecast.points.at(-1)?.date;
  const method = forecast.method
    ? (t.hospital.forecastMethod[forecast.method] ?? forecast.method)
    : null;

  return (
    <Section
      title={t.hospital.chartTitle}
      caption={
        first
          ? t.hospital.chartCaption(
              fmtDate(first),
              fmtDate(today),
              fmtDate(lastForecast ?? today),
            )
          : undefined
      }
      id="chart"
    >
      <figure className="card space-y-3 p-4">
        <div
          className="h-[380px]"
          role="img"
          aria-label={t.hospital.chartTitle}
        >
          <ResponsiveContainer width="100%" height="100%">
            <ComposedChart
              data={rows}
              margin={{ top: 24, right: 8, bottom: 0, left: 0 }}
              barGap={0}
              barCategoryGap="12%"
            >
              <CartesianGrid stroke="#e3e8ee" vertical={false} />
              {lastForecast ? (
                <ReferenceArea
                  x1={forecast.points[0]?.date}
                  x2={lastForecast}
                  yAxisId="flow"
                  fill="#eef4fb"
                  fillOpacity={0.8}
                />
              ) : null}
              <XAxis
                dataKey="date"
                tickFormatter={fmtDayMonth}
                interval={6}
                tick={{ fontSize: 13, fill: "#536072" }}
                tickLine={false}
                axisLine={{ stroke: "#aab4c1" }}
              />
              <YAxis
                yAxisId="flow"
                allowDecimals={false}
                tick={{ fontSize: 13, fill: "#536072" }}
                width={44}
                axisLine={false}
                tickLine={false}
              />
              <YAxis
                yAxisId="queue"
                orientation="right"
                allowDecimals={false}
                tick={{ fontSize: 13, fill: "#1c2430" }}
                width={52}
                axisLine={false}
                tickLine={false}
              />
              <Tooltip
                labelFormatter={(label) => fmtDate(String(label))}
                formatter={(value, name) => [
                  fmtNumber(
                    Number(value),
                    Number.isInteger(Number(value)) ? 0 : 1,
                  ),
                  SERIES_LABELS[String(name)] ?? String(name),
                ]}
              />
              <Legend
                formatter={(value) => (
                  <span className="text-sm text-ink">
                    {SERIES_LABELS[String(value)] ?? value}
                  </span>
                )}
                wrapperStyle={{ paddingTop: 8 }}
              />
              <Bar
                yAxisId="flow"
                dataKey="registrations"
                fill={COLORS.registrations}
                isAnimationActive={false}
              />
              <Bar
                yAxisId="flow"
                dataKey="hospitalizations"
                fill={COLORS.hospitalizations}
                isAnimationActive={false}
              />
              <Bar
                yAxisId="flow"
                dataKey="refusals"
                fill={COLORS.refusals}
                isAnimationActive={false}
              />
              <Line
                yAxisId="queue"
                dataKey="queue"
                stroke={COLORS.queue}
                strokeWidth={2.5}
                dot={false}
                isAnimationActive={false}
                connectNulls={false}
              />
              <Line
                yAxisId="flow"
                dataKey="forecastRegistrations"
                stroke={COLORS.registrations}
                strokeWidth={2.5}
                strokeDasharray="7 5"
                dot={{ r: 3, fill: "white", strokeWidth: 2 }}
                isAnimationActive={false}
              />
              <Line
                yAxisId="flow"
                dataKey="forecastHospitalizations"
                stroke={COLORS.hospitalizations}
                strokeWidth={2.5}
                strokeDasharray="2 4"
                dot={{ r: 3, fill: "white", strokeWidth: 2 }}
                isAnimationActive={false}
              />
              <ReferenceLine
                yAxisId="flow"
                x={today}
                stroke="#1c2430"
                strokeWidth={1.5}
                strokeDasharray="4 3"
                label={{
                  value: t.hospital.today,
                  position: "top",
                  fill: "#1c2430",
                  fontSize: 14,
                  fontWeight: 600,
                }}
              />
            </ComposedChart>
          </ResponsiveContainer>
        </div>
        <figcaption className="space-y-1 text-sm text-muted">
          <p>
            {forecast.points.length ? forecast.note : t.hospital.noForecast}
          </p>
          {method && forecast.model_version ? (
            <p>{t.hospital.forecastMeta(method, forecast.model_version)}</p>
          ) : null}
        </figcaption>
      </figure>
    </Section>
  );
}
