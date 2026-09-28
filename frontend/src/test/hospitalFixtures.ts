/**
 * Waiting-list fixtures shaped like the real published responses of `waiting-list-origin-2025-03-17-v1`.
 * Counts are small so a test can assert them exactly; the shape is the published one.
 */
import type {
  QueueReferralResponse,
  ReferralEstimateResponse,
  ReferralEstimatesPublicationResponse,
  VerificationWorklistPublicationResponse,
  WaitingHospitalDetailResponse,
  WaitingHospitalResponse,
  WaitingReferralResponse,
  WorklistAreaResponse,
  WorklistHospitalResponse,
  WorklistItemResponse,
} from "../api/generated";

export const ORIGIN = "2025-03-17";
export const WAITING_IDENTITY = "1c".padEnd(64, "0");
const publication = {
  publication_id: "waiting-list-origin-2025-03-17-v1",
  publication_identity_sha256: WAITING_IDENTITY,
  origin: ORIGIN,
};

export const BIG_ORG = "01W9";
export const THIN_ORG = "0THIN";

export const hospitals: WaitingHospitalResponse[] = [
  {
    ...publication,
    org_code: BIG_ORG,
    org_name: "Областная клиническая больница",
    region_code: "61",
    region_name: "Туркестанская область",
    waiting_count: 240,
    profile_count: 3,
    median_days_waited: 31,
    max_days_waited: 71,
    support_class: "SUFFICIENT",
  },
  {
    ...publication,
    org_code: "0MID",
    org_name: "Городская больница №2",
    region_code: "59",
    region_name: "Северо-Казахстанская область",
    waiting_count: 24,
    profile_count: 2,
    median_days_waited: 12,
    max_days_waited: 40,
    support_class: "LIMITED",
  },
  {
    ...publication,
    org_code: THIN_ORG,
    org_name: "Районная больница",
    region_code: "59",
    region_name: "Северо-Казахстанская область",
    waiting_count: 6,
    profile_count: 1,
    median_days_waited: 4,
    max_days_waited: 9,
    support_class: "SPARSE",
  },
];

export const hospitalDetail: WaitingHospitalDetailResponse = {
  ...hospitals[0],
  profiles: [
    {
      profile_code: "081",
      profile_name: "Хирургические для взрослых",
      waiting_count: 150,
      median_days_waited: 33,
      max_days_waited: 71,
    },
    {
      profile_code: "031",
      profile_name: "Кардиологические для взрослых",
      waiting_count: 60,
      median_days_waited: 24,
      max_days_waited: 55,
    },
    {
      profile_code: "251",
      profile_name: "Неврологические для взрослых",
      waiting_count: 30,
      median_days_waited: 10,
      max_days_waited: 22,
    },
  ],
  days_waited_histogram: [
    { from_days: 0, to_days: 3, count: 10 },
    { from_days: 3, to_days: 7, count: 30 },
    { from_days: 7, to_days: 14, count: 20 },
    { from_days: 14, to_days: 30, count: 50 },
    { from_days: 30, to_days: 60, count: 110 },
    { from_days: 60, to_days: null, count: 20 },
  ],
  observed_after_origin: {
    disclosure: "HINDSIGHT_NOT_AVAILABLE_AT_ORIGIN",
    admitted: 190,
    refused: 45,
    still_waiting_at_cutoff: 5,
  },
};

export const thinDetail: WaitingHospitalDetailResponse = {
  ...hospitals[2],
  profiles: [
    {
      profile_code: "081",
      profile_name: "Хирургические для взрослых",
      waiting_count: 6,
      median_days_waited: 4,
      max_days_waited: 9,
    },
  ],
  days_waited_histogram: [
    { from_days: 0, to_days: 3, count: 2 },
    { from_days: 3, to_days: 7, count: 3 },
    { from_days: 7, to_days: 14, count: 1 },
    { from_days: 14, to_days: 30, count: 0 },
    { from_days: 30, to_days: 60, count: 0 },
    { from_days: 60, to_days: null, count: 0 },
  ],
  observed_after_origin: {
    disclosure: "HINDSIGHT_NOT_AVAILABLE_AT_ORIGIN",
    admitted: 4,
    refused: 2,
    still_waiting_at_cutoff: 0,
  },
};

const referral = (
  id: number,
  waited: number,
  status: "ADMITTED" | "REFUSED" | "STILL_WAITING_AT_CUTOFF",
  eventDate: string | null,
): WaitingReferralResponse => ({
  ...publication,
  referral_id: id,
  hospitalization_code: `61.${BIG_ORG}.081.${id}`,
  is_duplicate_code: id === 3,
  org_code: BIG_ORG,
  region_code: "61",
  patient_region_code: "61",
  profile_code: "081",
  profile_name: "Хирургические для взрослых",
  registration_date: "2025-01-20",
  days_waited_at_origin: waited,
  observed_after_origin: {
    disclosure: "HINDSIGHT_NOT_AVAILABLE_AT_ORIGIN",
    status,
    event_date: eventDate,
    days_from_origin: eventDate
      ? Math.round((Date.parse(eventDate) - Date.parse(ORIGIN)) / 86_400_000)
      : null,
  },
});

export const referrals: WaitingReferralResponse[] = [
  referral(1, 56, "ADMITTED", "2025-03-25"),
  referral(2, 40, "REFUSED", "2025-04-02"),
  referral(3, 21, "STILL_WAITING_AT_CUTOFF", null),
];

/**
 * Per-referral estimate fixtures, shaped like `referral-estimates-origin-2025-03-17-v1`.
 *
 * The three rows cover the three things the screen has to render without lying: a hospital-level estimate with an
 * admission window, a region-level fallback flagged for administrative follow-up, and a row where the model
 * abstained from a window and says why.
 */
export const ESTIMATES_IDENTITY = "5e".padEnd(64, "0");
export const ATTENTION_THRESHOLD = 0.215675;

const estimatePublication = {
  publication_id: "referral-estimates-origin-2025-03-17-v1",
  publication_identity_sha256: ESTIMATES_IDENTITY,
  origin: ORIGIN,
  selected_model: "aalen_johansen" as const,
  window_coverage: 0.8,
};

const estimate = (
  admitted: [number, number, number],
  refused: number,
  tier: ReferralEstimateResponse["estimate_tier"],
  rows: number,
  window: [number, number] | null,
): ReferralEstimateResponse => ({
  ...estimatePublication,
  estimate_tier: tier,
  similar_training_rows: rows,
  admitted_7d: admitted[0],
  admitted_14d: admitted[1],
  admitted_30d: admitted[2],
  refused_30d: refused,
  still_waiting_30d: Math.max(0, 1 - admitted[2] - refused),
  window_lower_days: window?.[0] ?? null,
  window_upper_days: window?.[1] ?? null,
  abstention_reason: window ? null : "NO_ADMISSION_IN_COMPARABLE_HISTORY",
  refusal_attention: refused >= ATTENTION_THRESHOLD,
  degenerate_30d:
    Math.max(admitted[2], refused, 1 - admitted[2] - refused) >= 1 - 1e-6,
});

export const estimatesByReferral: Record<number, ReferralEstimateResponse> = {
  1: estimate([0.41, 0.62, 0.78], 0.09, "hospital_profile", 320, [3, 21]),
  2: estimate([0.12, 0.2, 0.31], 0.34, "region_profile", 12, [8, 44]),
  // the shape the screen must not print as a confident 0%: the whole 30-day mass on "still waiting"
  3: estimate([0, 0, 0], 0, "profile", 0, null),
};

export const queueReferrals: QueueReferralResponse[] = referrals.map((row) => ({
  ...row,
  estimate: estimatesByReferral[row.referral_id] ?? null,
}));

const reliability = (
  horizon: number,
  outcome: "hospitalized" | "refused",
  points: [number, number][],
) =>
  points.map(([predicted, observed], index) => ({
    horizon_days: horizon,
    outcome,
    bin_index: index,
    n: 1000,
    mean_predicted: predicted,
    observed_rate: observed,
    probability_min: predicted,
    probability_max: predicted,
  }));

export const estimatesPublication: ReferralEstimatesPublicationResponse = {
  publication_id: estimatePublication.publication_id,
  schema_version: "referral_estimates_v1",
  contract_version: "1.0.0",
  publication_identity_sha256: ESTIMATES_IDENTITY,
  bundle_sha256: "ab".padEnd(64, "0"),
  source_code_commit: "0".repeat(40),
  origin: ORIGIN,
  outcome_cutoff: "2026-05-13T00:00:00",
  published_at: "2026-09-28T06:00:00Z",
  generated_at: "2026-09-28T05:59:00Z",
  referral_count: 65232,
  horizons: [7, 14, 30],
  admission_window_coverage: 0.8,
  source_run: {
    run_id: "b2-origin-2025-03-17-v2",
    artifact_identity_sha256: "dd".padEnd(64, "0"),
    scientific_identity_sha256: "bc".padEnd(64, "0"),
    training_sha256: "60".padEnd(64, "0"),
    scoring_sha256: "99".padEnd(64, "0"),
    seed: 42,
    library_versions: { python: "3.14.7", lightgbm: "4.7.0" },
  },
  selection: {
    metric: "mean_admission_and_refusal_brier_at_7_14_30",
    decision_rule: "Правило зафиксировано до запуска.",
    tolerance: 0.005,
    require_strict_overall_improvement: true,
    selected_model: "aalen_johansen",
    fallback_used: true,
    candidates: [
      {
        model_key: "aalen_johansen",
        role: "baseline",
        accepted: null,
        overall_mean_brier: 0.097865,
        overall_delta: null,
        worst_bucket_delta: null,
        strict_overall_improvement: null,
        within_bucket_tolerance: null,
        brier_by_horizon: { "7": 0.0784, "14": 0.097583, "30": 0.117648 },
      },
      {
        model_key: "discrete_competing_risk",
        role: "candidate",
        accepted: false,
        overall_mean_brier: 0.126045,
        overall_delta: 0.02818,
        worst_bucket_delta: 0.113977,
        strict_overall_improvement: false,
        within_bucket_tolerance: false,
        brier_by_horizon: { "7": 0.1102, "14": 0.126, "30": 0.1419 },
      },
      {
        model_key: "xgboost_aft",
        role: "candidate",
        accepted: false,
        overall_mean_brier: 0.104514,
        overall_delta: 0.006648,
        worst_bucket_delta: 0.023325,
        strict_overall_improvement: false,
        within_bucket_tolerance: false,
        brier_by_horizon: { "7": 0.0861, "14": 0.1044, "30": 0.1231 },
      },
    ],
  },
  calibration: {
    disclosure: "HINDSIGHT_NOT_AVAILABLE_AT_ORIGIN",
    model_key: "aalen_johansen",
    rows: 65232,
    bins: [
      ...reliability(14, "hospitalized", [
        [0.0, 0.06],
        [0.14, 0.1],
        [0.38, 0.24],
        [0.68, 0.51],
        [0.86, 0.68],
      ]),
      ...reliability(14, "refused", [
        [0.0, 0.05],
        [0.2, 0.14],
      ]),
      ...reliability(7, "hospitalized", [[0.2, 0.18]]),
      ...reliability(30, "hospitalized", [[0.5, 0.44]]),
    ],
  },
  estimate_tiers: {
    hospital_profile: 60634,
    region_profile: 3859,
    profile: 729,
    national: 10,
  },
  abstention_counts: { NO_ADMISSION_IN_COMPARABLE_HISTORY: 10454 },
  degeneracy: {
    definition: "Вся вероятностная масса на 30 дней пришлась на один исход.",
    count: 8984,
    by_outcome: { admitted: 590, still_waiting: 8154, refused: 240 },
  },
  attention: {
    metric: "refused_30d",
    quantile: 0.9,
    threshold: ATTENTION_THRESHOLD,
    definition: "Верхний дециль по всей когорте.",
    intended_use: "Административная проверка направления.",
    flagged_count: 6525,
  },
  limitations: ["Оценки origin-time."],
  matches_waiting_list: true,
};

/**
 * Verification-worklist fixtures, shaped like `verification-worklist-origin-2025-03-17-v2` (read from the B5.1
 * ghost-queue bundle, schema 2): the whole formal queue ranked, with the canonical national yield points.
 *
 * Small on purpose so a test can assert the counts exactly, and deliberately including rows that rest on thin
 * comparable history — the case the screen has to qualify rather than present as a confident number.
 */
export const WORKLIST_IDENTITY = "e9".padEnd(64, "0");
export const NOT_A_DECISION = {
  ru: "Это список на сверку, а не решение. Ни одно направление не снимается с очереди автоматически: решение принимает специалист.",
  kk: "Бұл — тексеруге арналған тізім, шешім емес. Бірде-бір жолдама кезектен автоматты түрде алынбайды: шешімді маман қабылдайды.",
};

const worklistFraming = {
  publication_id: "verification-worklist-origin-2025-03-17-v2",
  publication_identity_sha256: WORKLIST_IDENTITY,
  origin: ORIGIN,
  decision_owner: "SPECIALIST_DECIDES" as const,
  not_a_decision: NOT_A_DECISION,
};

const worklistItem = (
  rank: number,
  referral_id: number,
  waited: number,
  probability: number,
  score: number,
  tier: WorklistItemResponse["estimate_tier"],
  reason: WorklistItemResponse["history_quality_reason_code"],
): WorklistItemResponse => ({
  ...worklistFraming,
  referral_id,
  rank,
  org_code: BIG_ORG,
  region_code: "61",
  profile_code: "081",
  profile_name: "Хирургические для взрослых",
  days_waited_at_origin: waited,
  registration_date: "2025-01-20",
  hospitalization_code: `61.${BIG_ORG}.081.${referral_id}`,
  probability_admitted_30d: 0,
  probability_admitted_horizon: probability,
  horizon_days: 90,
  estimate_tier: tier,
  verification_priority_score: score,
  comparable_training_at_risk_rows: reason?.startsWith("insufficient")
    ? 12
    : 80,
  history_quality_warning: reason !== null,
  history_quality_reason_code: reason,
});

export const worklistItems: WorklistItemResponse[] = [
  worklistItem(
    1,
    11,
    71,
    0,
    1,
    "hospital_profile",
    "degenerate_conditional_distribution",
  ),
  worklistItem(
    2,
    12,
    54,
    0.02,
    0.24,
    "region_profile",
    "insufficient_comparable_history",
  ),
  worklistItem(3, 13, 33, 0.08, 0.2, "hospital_profile", null),
];

export const worklistRegions: WorklistAreaResponse[] = [
  {
    level: "region",
    code: "61",
    name: "Туркестанская область",
    region_code: null,
    formal_queue_count: 7960,
    history_quality_warning_count: 2381,
    history_quality_warning_share: 0.299121,
  },
  {
    level: "region",
    code: "59",
    name: "Северо-Казахстанская область",
    region_code: null,
    formal_queue_count: 2407,
    history_quality_warning_count: 687,
    history_quality_warning_share: 0.285418,
  },
];

export const worklistHospital: WorklistHospitalResponse = {
  ...worklistFraming,
  org_code: BIG_ORG,
  org_name: "Областная клиническая больница",
  region_code: "61",
  region_name: "Туркестанская область",
  formal_queue_count: 240,
  history_quality_warning_count: 2,
  history_quality_warning_share: 0.008333,
  region: worklistRegions[0],
  items: worklistItems,
  total: worklistItems.length,
  limit: 25,
  offset: 0,
};

export const worklistPublication: VerificationWorklistPublicationResponse = {
  publication_id: worklistFraming.publication_id,
  schema_version: "verification_worklist_v2",
  contract_version: "2.0.0",
  publication_identity_sha256: WORKLIST_IDENTITY,
  bundle_sha256: "ff".padEnd(64, "0"),
  source_code_commit: "0".repeat(40),
  origin: ORIGIN,
  published_at: "2026-09-28T09:00:00Z",
  generated_at: "2026-09-28T08:59:00Z",
  decision_owner: "SPECIALIST_DECIDES",
  not_a_decision: NOT_A_DECISION,
  source_publication: {
    publication_id: "ghost-queue-2025-03-17-v2",
    publication_identity_sha256:
      "b34c69702936dc7afe6f3781dbb028d2d4c743eb97c0234ba820e07940f6daaa",
    file_sha256:
      "219c4116e5e2c7e965123e12b456024bcd397fbb5a661924301d152ffde33edf",
    schema_version: 2,
    model: "origin-safe hierarchical Aalen-Johansen",
  },
  ranking: {
    definition: {
      ru: "Порядок сверки задаёт оценка приоритета от 0 до 1.",
      kk: "Тексеру ретін 0-ден 1-ге дейінгі басымдық бағасы анықтайды.",
    },
    keys: [
      "origin_safe_verification_priority desc",
      "days_waited_at_origin_desc",
      "referral_id_asc",
    ],
    score_name: "origin_safe_verification_priority",
    score_formula: "one_minus_p_admit_90d_x_wait_maturity_x_at_risk_support",
    wait_maturity_days: 30,
    minimum_comparable_at_risk_rows: 50,
    training_only_justification: "Зафиксировано до проверки на исходах.",
  },
  legacy_rule: {
    role: "AUDITED_REFERENCE_ONLY",
    reason_code: "waited_30d_and_p_admit_90d_below_0_10",
    minimum_days_waited: 30,
    horizon_days: 90,
    probability_strictly_below: 0.1,
    selected_count: 13328,
    training_only_justification: "Зафиксировано до проверки на исходах.",
    statement: {
      ru: "Прежнее правило отобрало бы 13 328 направлений. Оно оставлено только для сравнения.",
      kk: "Бұрынғы ереже 13 328 жолдаманы іріктер еді. Ол тек салыстыру үшін қалдырылды.",
    },
  },
  history_quality: {
    definition: {
      ru: "Мало сопоставимой истории: за оценкой меньше 50 сопоставимых направлений.",
      kk: "Салыстырмалы тарих аз: бағаның артында 50-ден аз салыстырмалы жолдама бар.",
    },
    warning_count: 19950,
    warning_share: 0.305831,
    reason_counts: {
      insufficient_comparable_history: 10895,
      insufficient_and_degenerate_comparable_history: 6463,
      degenerate_conditional_distribution: 2592,
    },
  },
  estimands: { conditioning: "conditional on remaining unresolved" },
  counts: { formal_queue_count: 65232, ranked_count: 65232 },
  yield_curve: {
    disclosure: "HINDSIGHT_NOT_AVAILABLE_AT_ORIGIN",
    definition: {
      ru: "Ретроспектива: если бы бюро сверяло записи в этом порядке.",
      kk: "Ретроспектива: бюро жазбаларды осы ретпен тексерсе.",
    },
    outcome_source: "waiting-list-origin-2025-03-17-v1",
    outcome_source_identity_sha256: WAITING_IDENTITY,
    base: { evaluated: 65232, no_longer_current: 19769, share: 0.303057 },
    points: [
      { checked: 500, no_longer_current: 159, share: 0.318, lift: 1.049308 },
      { checked: 1000, no_longer_current: 298, share: 0.298, lift: 0.983314 },
      { checked: 2000, no_longer_current: 768, share: 0.384, lift: 1.267089 },
      { checked: 5000, no_longer_current: 2040, share: 0.408, lift: 1.346282 },
      {
        checked: 13328,
        no_longer_current: 4842,
        share: 0.363295,
        lift: 1.19877,
      },
    ],
  },
  limitations: ["Список на сверку — это не очередь."],
};
