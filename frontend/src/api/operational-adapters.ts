/** Presentation only: no scientific calculation, severity assignment or rank sorting. */
import type {
  OperationalCounts,
  OperationalSnapshotResponse,
  OperationalSignalResponse,
  OperationalForecastResponse,
  OperationalOverviewResponse,
  OperationalRegionResponse,
  OperationalHospitalProfileResponse,
  ModelAssuranceCapabilityResponse,
  ModelAssuranceSnapshotResponse,
  SignalExplanationResponse,
  SourceProvenance,
} from "./generated";
import { t } from "../i18n";
import { fmtDate, fmtDateTime, fmtNumber } from "../lib/format";

export const label = (value: string | null | undefined) =>
  value == null ? t.common.noData : (t.tower.status[value] ?? value);
export const number = (value: number | null | undefined) =>
  value == null ? t.common.noData : fmtNumber(value, 1);
export type Fact = { label: string; value: string };
export type Severity = OperationalSignalResponse["severity"];
export type Support = OperationalSignalResponse["support_status"];
export const sourceFacts = (
  sources: Record<string, SourceProvenance>,
): Fact[] =>
  Object.entries(sources).flatMap(([name, p]) => [
    { label: `${name} · run`, value: p.run_id },
    {
      label: `${name} · scientific SHA256`,
      value: p.scientific_identity_sha256,
    },
    {
      label: `${name} · artifact SHA256`,
      value: Array.isArray(p.artifact_sha256)
        ? p.artifact_sha256.join(" · ")
        : p.artifact_sha256,
    },
    ...(
      [
        "dataset_identity_sha256",
        "config_identity_sha256",
        "code_identity_sha256",
      ] as const
    ).map((key) => ({
      label: `${name} · ${key}`,
      value: p[key] ?? t.tower.status.UNKNOWN,
    })),
  ]);
export function snapshotView(d: OperationalSnapshotResponse) {
  return {
    id: d.publication_id,
    identity: d.publication_identity_sha256,
    assuranceIdentity: d.assurance_identity_sha256,
    origin: d.current_origin,
    freshness: d.freshness_state,
    status: d.publication_status,
    published: fmtDateTime(d.published_at),
    limitations: d.limitations,
    facts: [
      { label: "Publication SHA256", value: d.publication_identity_sha256 },
      { label: "Assurance SHA256", value: d.assurance_identity_sha256 },
      { label: "Code commit", value: d.source_code_commit },
      ...sourceFacts(d.source_provenance),
    ],
  };
}
export type SnapshotView = ReturnType<typeof snapshotView>;
export function countsView(d: OperationalCounts) {
  // Defaults are defined by the API contract; no scoring or inference.
  return {
    total: d.total_signals ?? 0,
    high: d.high ?? 0,
    direct: d.direct_supported ?? 0,
    calibrated: d.calibrated ?? 0,
    severity: [
      ["HIGH", d.high],
      ["ELEVATED", d.elevated],
      ["WATCH", d.watch],
      ["NORMAL", d.normal],
      ["UNSUPPORTED", d.unsupported_severity],
    ].map(([key, count]) => ({
      label: label(String(key)),
      value: Number(count ?? 0),
    })),
    support: [
      ["DIRECT_SUPPORTED", d.direct_supported],
      ["FALLBACK_LIMITED", d.fallback_limited],
      ["UNSUPPORTED", d.unsupported_support],
    ].map(([key, count]) => ({
      label: label(String(key)),
      value: Number(count ?? 0),
    })),
  };
}
export type CountsView = ReturnType<typeof countsView>;
export function signalView(d: OperationalSignalResponse) {
  return {
    id: d.signal_id,
    seriesId: d.series_id,
    origin: d.origin,
    target: d.target,
    org: d.org_code,
    region: d.region_code,
    profile: d.profile_code,
    rank: d.inbox_rank,
    severity: d.severity,
    support: d.support_status,
    fallback: label(d.fallback_status),
    uncertainty: label(d.uncertainty_status),
    headline: d.headline,
    reason: d.concise_reason,
    typeLabel:
      d.signal_type === "preventive_flow_pressure"
        ? t.tower.preventive
        : t.tower.observed,
    forecast: number(d.forecast_value),
    interval:
      d.uncertainty_status === "CALIBRATED"
        ? `${number(d.uncertainty_lower)} – ${number(d.uncertainty_upper)}`
        : t.tower.noInterval,
    materiality: label(d.materiality_status),
    pressure: d.pressure_basis,
    reasons: d.reason_codes,
    evidence: d.evidence_facts ?? [],
    limitations: d.limitations ?? [],
    identity: d.publication_identity_sha256,
    // Raw published numbers for visual compositions (formatting happens in the view, never recomputation).
    rawForecast: d.forecast_value,
    rawInterval:
      d.uncertainty_status === "CALIBRATED" &&
      d.uncertainty_lower != null &&
      d.uncertainty_upper != null
        ? ([d.uncertainty_lower, d.uncertainty_upper] as [number, number])
        : null,
    rawThreshold: d.threshold_value,
    rawThresholdStatus: d.threshold_status,
    rawLeadDays: d.lead_time_days,
    rawCrossing: d.first_crossing_date,
    rawMateriality: d.materiality_status,
    rawDataFreshness: d.data_freshness,
    facts: [
      { label: t.tower.origin, value: fmtDate(d.origin) },
      { label: t.tower.target, value: label(d.target) },
      { label: t.tower.threshold, value: number(d.threshold_value) },
      {
        label: t.tower.threshold + " · статус",
        value: label(d.threshold_status),
      },
      { label: t.tower.materiality, value: label(d.materiality_status) },
      {
        label: t.tower.crossing,
        value: d.first_crossing_date
          ? fmtDate(d.first_crossing_date)
          : t.common.noData,
      },
      { label: t.tower.lead, value: number(d.lead_time_days) },
      {
        label: t.tower.dataAsOf,
        value: d.data_freshness ? fmtDate(d.data_freshness) : t.common.noData,
      },
      ...(d.anomaly_evidence
        ? [
            {
              label: t.tower.observed,
              value: number(d.anomaly_evidence.observed_value),
            },
            { label: "Robust z", value: number(d.anomaly_evidence.robust_z) },
            { label: "MAD", value: number(d.anomaly_evidence.reference_mad) },
            {
              label: "Reference n",
              value: number(d.anomaly_evidence.reference_sample_count),
            },
            {
              label: "Reference max date",
              value: fmtDate(d.anomaly_evidence.reference_max_date),
            },
          ]
        : []),
    ],
    provenance: [
      { label: "Signal ID", value: d.signal_id },
      { label: "Series ID", value: d.series_id },
      { label: "Publication SHA256", value: d.publication_identity_sha256 },
      ...sourceFacts(d.source_provenance),
    ],
  };
}
export type SignalView = ReturnType<typeof signalView>;
export const overviewView = (d: OperationalOverviewResponse) => ({
  snapshot: snapshotView(d.snapshot),
  counts: countsView(d.national),
  regions: d.regions.map((r) => ({
    code: r.region_code,
    counts: countsView(r.counts),
  })),
});
export const regionView = (d: OperationalRegionResponse) => ({
  snapshot: snapshotView(d.snapshot),
  code: d.region_code,
  counts: countsView(d.counts),
  signals: d.top_signals.map(signalView),
  forecastCount: d.forecast_point_count,
});
export const hospitalView = (d: OperationalHospitalProfileResponse) => ({
  snapshot: snapshotView(d.snapshot),
  org: d.org_code,
  region: d.region_code,
  profile: d.profile_code,
  counts: countsView(d.counts),
  signals: d.signals.map(signalView),
  forecastCount: d.forecast_point_count,
  origins: d.available_origins,
  targets: d.available_targets,
});
export function forecastGroups(rows: OperationalForecastResponse[]) {
  const groups = new Map<string, ForecastSeries>();
  for (const d of rows) {
    const key = `${d.publication_identity_sha256}:${d.series_id}:${d.origin}:${d.target}`;
    let group = groups.get(key);
    if (!group) {
      group = {
        key,
        seriesId: d.series_id,
        identity: d.publication_identity_sha256,
        origin: d.origin,
        target: label(d.target),
        profile: d.profile_code ?? null,
        points: [],
        limitations: [],
        provenance: sourceFacts(d.source_provenance),
      };
      groups.set(key, group);
    }
    const band =
      d.uncertainty_status === "CALIBRATED" ? d.calibrated_uncertainty : null;
    group.points.push({
      date: d.target_date,
      central: d.support_status === "UNSUPPORTED" ? null : d.central_value,
      interval:
        band && d.support_status !== "UNSUPPORTED"
          ? [band.lower, band.upper]
          : null,
      coverage: band
        ? `${number(band.nominal_coverage * 100)}%`
        : t.common.noData,
      support: label(d.support_status),
      fallback: label(d.fallback_status),
      uncertainty: label(d.uncertainty_status),
      semantics: label(d.central_semantics),
    });
    group.limitations.push(...(d.limitations ?? []));
  }
  return [...groups.values()].map((g) => ({
    ...g,
    points: g.points.sort((a, b) => a.date.localeCompare(b.date)),
    limitations: [...new Set(g.limitations)],
  }));
}
export interface ForecastSeries {
  key: string;
  seriesId: string;
  identity: string;
  origin: string;
  target: string;
  profile: string | null;
  points: {
    date: string;
    central: number | null;
    interval: [number, number] | null;
    coverage: string;
    support: string;
    fallback: string;
    uncertainty: string;
    semantics: string;
  }[];
  limitations: string[];
  provenance: Fact[];
}
export function explanationView(d: SignalExplanationResponse) {
  return {
    summary: d.summary,
    why: d.why_flagged,
    evidence: d.key_evidence.map((e) => ({
      label: e.statement,
      value: e.value == null ? t.common.noData : String(e.value),
    })),
    uncertainty: d.uncertainty.narrative,
    support: d.support.narrative,
    supportStatus: d.support.status,
    fallback: label(d.support.fallback_status),
    limitations: d.limitations,
    questions: d.suggested_review_questions,
    generation:
      d.generation_mode === "DETERMINISTIC"
        ? t.tower.deterministic
        : d.generation_mode === "DETERMINISTIC_FALLBACK"
          ? t.tower.deterministicFallback
          : t.tower.narrated,
    identity: d.provenance.publication_identity_sha256,
    provenance: [
      { label: "Publication", value: d.provenance.publication_id },
      {
        label: "Publication SHA256",
        value: d.provenance.publication_identity_sha256,
      },
      {
        label: "Assurance SHA256",
        value: d.provenance.assurance_identity_sha256,
      },
      ...sourceFacts(d.provenance.source_provenance),
    ],
    capabilities: d.provenance.model_assurance_capabilities.map((c) => ({
      id: c.capability_id,
      evidence: label(c.evidence_status),
      acceptance: label(c.acceptance_verdict),
      consumption: label(c.product_consumption_status),
      governance: [
        c.human_review_required ? t.tower.human : null,
        !c.autonomous_action ? t.tower.noAutonomy : null,
        !c.capacity_checked ? t.tower.noCapacity : null,
        !c.causal_effect_claimed ? t.tower.noCausal : null,
      ].filter((v): v is string => v !== null),
    })),
  };
}
export function capabilityView(d: ModelAssuranceCapabilityResponse) {
  return {
    id: d.capability_id,
    title: d.display_name,
    status: d.evidence_status,
    acceptance: label(d.acceptance_verdict),
    consumption: label(d.product_consumption_status),
    support: d.support.support_semantics.map(label),
    range: d.support.range_semantics.map(label),
    freshness: label(d.freshness.state),
    freshnessReason: d.freshness.reason,
    limitations: d.limitations,
    claims: d.allowed_claims,
    evidence: d.evidence,
    governance: [
      d.governance.human_review_required ? t.tower.human : null,
      !d.governance.autonomous_action ? t.tower.noAutonomy : null,
      !d.governance.capacity_checked ? t.tower.noCapacity : null,
      !d.governance.causal_effect_claimed ? t.tower.noCausal : null,
      !d.governance.serving_claim ? t.tower.noServing : null,
    ].filter((v): v is string => v !== null),
    identities: Object.entries(d.identities).map(([key, value]) => ({
      label: key,
      value: `${label(value.status)} · ${Array.isArray(value.value) ? value.value.join(" · ") : (value.value ?? value.reason)}`,
    })),
  };
}
export const assuranceView = (d: ModelAssuranceSnapshotResponse) => ({
  id: d.assurance_id,
  identity: d.assurance_identity_sha256,
  published: fmtDateTime(d.published_at),
  frozen: d.ml_freeze_status === "ML_CORE_CLOSED_FROZEN",
  facts: [
    { label: "Assurance SHA256", value: d.assurance_identity_sha256 },
    { label: "Code commit", value: d.source_code_commit },
    { label: "Contract", value: d.contract_version },
  ],
});
