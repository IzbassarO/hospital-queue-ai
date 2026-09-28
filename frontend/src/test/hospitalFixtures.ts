/**
 * Waiting-list fixtures shaped like the real published responses of `waiting-list-origin-2025-03-17-v1`.
 * Counts are small so a test can assert them exactly; the shape is the published one.
 */
import type {
  WaitingHospitalDetailResponse,
  WaitingHospitalResponse,
  WaitingReferralResponse,
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
