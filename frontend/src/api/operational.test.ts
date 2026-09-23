import { afterEach, describe, expect, it, vi } from "vitest";
import { forecastGroups, signalView } from "./operational-adapters";
import {
  operationalOverviewSchema,
  signalSchema,
  forecastSchema,
  explanationSchema,
} from "./operational-schemas";
import { overview, explanation } from "../test/operationalFixtures";
import { operationalApi } from "./operational";
import {
  forecast,
  signal,
  assurance,
  capabilities,
} from "../test/operationalFixtures";
import { jsonResponse } from "../test/mockApi";

afterEach(() => vi.unstubAllGlobals());
describe("Evidence presentation boundaries", () => {
  it("never merges different targets, origins or series into one forecast", () => {
    const groups = forecastGroups([
      forecast,
      { ...forecast, target_date: "2025-04-02", horizon: 2 },
      { ...forecast, target: "cohort_hospitalizations" },
      { ...forecast, origin: "2025-03-30", horizon: 2 },
      { ...forecast, series_id: "another-series" },
    ]);
    expect(groups).toHaveLength(4);
    expect(groups.map((g) => g.points.length)).toEqual([2, 1, 1, 1]);
    expect(groups[0].points[0].interval).toEqual([11, 19]);
  });
  it("unsupported forecasts create a gap, without inventing an interval from raw quantiles", () => {
    const group = forecastGroups([
      forecast,
      {
        ...forecast,
        target_date: "2025-04-02",
        horizon: 2,
        support_status: "UNSUPPORTED",
        fallback_status: "UNSUPPORTED",
        calibrated_uncertainty: null,
        uncertainty_status: "UNAVAILABLE",
      },
    ])[0];
    expect(group.points[1].central).toBeNull();
    expect(group.points[1].interval).toBeNull();
    expect(group.points[0].central).toBe(15);
  });
  it("does not recalculate severity or ranking from the forecast value", () => {
    const view = signalView({
      ...signal,
      severity: "WATCH",
      inbox_rank: 42,
      forecast_value: 100000,
    });
    expect(view.severity).toBe("WATCH");
    expect(view.rank).toBe(42);
  });
  it("rejects assurance capabilities if the active snapshot changes during the read", async () => {
    vi.stubGlobal(
      "fetch",
      vi
        .fn()
        .mockResolvedValueOnce(jsonResponse(assurance))
        .mockResolvedValueOnce(jsonResponse(capabilities))
        .mockResolvedValueOnce(
          jsonResponse({
            ...assurance,
            assurance_identity_sha256: "f".repeat(64),
          }),
        ),
    );
    await expect(operationalApi.assurance()).rejects.toMatchObject({
      status: 409,
    });
  });
});

describe("Generated contract optional fields", () => {
  it("accepts omitted backend-default fields without changing supplied values", () => {
    const provenance = {
      flow_forecast: {
        run_id: "fixture-flow",
        scientific_identity_sha256: "b".repeat(64),
        artifact_sha256: "c".repeat(64),
      },
    };
    const minimalSignal = {
      signal_id: signal.signal_id,
      signal_type: signal.signal_type,
      series_id: signal.series_id,
      origin: signal.origin,
      target: signal.target,
      severity: signal.severity,
      headline: signal.headline,
      concise_reason: signal.concise_reason,
      support_status: "UNSUPPORTED",
      fallback_status: "UNSUPPORTED",
      uncertainty_status: "UNAVAILABLE",
      pressure_basis: "historical_flow_proxy_v1",
      reason_codes: signal.reason_codes,
      provenance_keys: signal.provenance_keys,
      publication_identity_sha256: signal.publication_identity_sha256,
      source_provenance: provenance,
    };
    expect(signalSchema.parse(minimalSignal)).toMatchObject({
      ...minimalSignal,
      inbox_rank: null,
      evidence_facts: [],
      observed_anomaly_present: false,
    });
    expect(
      operationalOverviewSchema.parse({
        ...overview,
        national: { high: 17 },
        snapshot: { ...overview.snapshot, source_provenance: provenance },
      }).national,
    ).toMatchObject({ high: 17, total_signals: 0 });
    const minimalForecast = {
      ...forecast,
      level: "national",
      central_semantics: "POINT_FORECAST",
      calibration_status: "NOT_APPLICABLE",
      uncertainty_status: "UNAVAILABLE",
      source_provenance: provenance,
    };
    for (const key of [
      "org_code",
      "region_code",
      "profile_code",
      "raw_quantiles",
      "calibrated_uncertainty",
      "evidence_facts",
      "limitations",
    ] as const)
      delete minimalForecast[key];
    expect(forecastSchema.parse(minimalForecast).central_value).toBe(
      forecast.central_value,
    );
    expect(
      explanationSchema.parse({
        ...explanation,
        key_evidence: [
          { code: "NOTE", statement: "No numeric value supplied" },
        ],
      }).key_evidence[0].value,
    ).toBeNull();
    expect(() =>
      operationalOverviewSchema.parse({
        ...overview,
        national: { high: "17" },
      }),
    ).toThrow();
  });
});
