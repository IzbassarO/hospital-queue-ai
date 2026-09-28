/**
 * Waiting-list transport: runtime guards over the generated DTOs, then query hooks.
 *
 * This publication carries no model output, and nothing here derives one. `observed_after_origin` is hindsight —
 * the guard keeps its `disclosure` marker on every row so the UI cannot lose it on the way to the screen.
 */
import { useQuery } from "@tanstack/react-query";
import type {
  WaitingHospitalDetailResponse,
  WaitingHospitalResponse,
  WaitingReferralResponse,
} from "./generated";
import { buildPath, request } from "./client";
import {
  array,
  bool,
  isoDate,
  literal,
  nullable,
  num,
  object,
  str,
  type Schema,
} from "./schema";
import { pageSchema } from "./types";

const base = "/waiting-list";
const enc = encodeURIComponent;

const supportClassSchema = literal("SUFFICIENT", "LIMITED", "SPARSE");
const observedStatusSchema = literal(
  "ADMITTED",
  "REFUSED",
  "STILL_WAITING_AT_CUTOFF",
);

const publicationFields = {
  publication_id: str,
  publication_identity_sha256: str,
  origin: isoDate,
};

export const waitingHospitalSchema: Schema<WaitingHospitalResponse> = object({
  ...publicationFields,
  org_code: str,
  org_name: str,
  region_code: str,
  region_name: str,
  waiting_count: num,
  profile_count: num,
  median_days_waited: num,
  max_days_waited: num,
  support_class: supportClassSchema,
});

const observedAfterOriginSchema = object({
  disclosure: literal("HINDSIGHT_NOT_AVAILABLE_AT_ORIGIN"),
  status: observedStatusSchema,
  event_date: nullable(isoDate),
  days_from_origin: nullable(num),
});

export const waitingReferralSchema: Schema<WaitingReferralResponse> = object({
  ...publicationFields,
  referral_id: num,
  hospitalization_code: str,
  is_duplicate_code: bool,
  org_code: str,
  region_code: str,
  patient_region_code: str,
  profile_code: str,
  profile_name: str,
  registration_date: isoDate,
  days_waited_at_origin: num,
  observed_after_origin: observedAfterOriginSchema,
});

export const waitingHospitalDetailSchema: Schema<WaitingHospitalDetailResponse> =
  object({
    ...publicationFields,
    org_code: str,
    org_name: str,
    region_code: str,
    region_name: str,
    waiting_count: num,
    profile_count: num,
    median_days_waited: num,
    max_days_waited: num,
    support_class: supportClassSchema,
    profiles: array(
      object({
        profile_code: str,
        profile_name: str,
        waiting_count: num,
        median_days_waited: num,
        max_days_waited: num,
      }),
    ),
    days_waited_histogram: array(
      object({ from_days: num, to_days: nullable(num), count: num }),
    ),
    observed_after_origin: object({
      disclosure: literal("HINDSIGHT_NOT_AVAILABLE_AT_ORIGIN"),
      admitted: num,
      refused: num,
      still_waiting_at_cutoff: num,
    }),
  });

export type WaitingHospital = WaitingHospitalResponse;
export type WaitingHospitalDetail = WaitingHospitalDetailResponse;
export type WaitingReferral = WaitingReferralResponse;
export type ReferralOrder = "longest_wait" | "shortest_wait";

/** The API pages at 500; the picker needs every hospital of the publication, which is 640 rows. */
const HOSPITALS_PAGE = 500;
const HOSPITALS_MAX_PAGES = 8;

export const waitingListApi = {
  hospitals: async (): Promise<WaitingHospital[]> => {
    const items: WaitingHospital[] = [];
    for (let page = 0; page < HOSPITALS_MAX_PAGES; page++) {
      const d = await request(
        pageSchema(waitingHospitalSchema),
        buildPath(`${base}/hospitals`, {
          limit: HOSPITALS_PAGE,
          offset: page * HOSPITALS_PAGE,
        }),
      );
      items.push(...d.items);
      if (d.items.length < HOSPITALS_PAGE || items.length >= d.total) break;
    }
    return items;
  },
  hospital: async (org: string): Promise<WaitingHospitalDetail> =>
    request(waitingHospitalDetailSchema, `${base}/hospitals/${enc(org)}`),
  referrals: async (
    org: string,
    query: {
      profile?: string | null;
      order?: ReferralOrder;
      limit: number;
      offset: number;
    },
  ) =>
    request(
      pageSchema(waitingReferralSchema),
      buildPath(`${base}/hospitals/${enc(org)}/referrals`, query),
    ),
};

const STALE = 5 * 60 * 1000;

export const useWaitingHospitals = () =>
  useQuery({
    queryKey: ["waiting-list", "hospitals"],
    queryFn: waitingListApi.hospitals,
    staleTime: STALE,
  });

export const useWaitingHospital = (org: string | null) =>
  useQuery({
    queryKey: ["waiting-list", "hospital", org],
    queryFn: () => waitingListApi.hospital(org as string),
    enabled: Boolean(org),
    staleTime: STALE,
  });

export const useWaitingReferrals = (
  org: string | null,
  query: {
    profile?: string | null;
    order?: ReferralOrder;
    limit: number;
    offset: number;
  },
) =>
  useQuery({
    queryKey: ["waiting-list", "referrals", org, query],
    queryFn: () => waitingListApi.referrals(org as string, query),
    enabled: Boolean(org),
    staleTime: STALE,
    placeholderData: (previous) => previous,
  });
