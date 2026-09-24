/** Control-centre endpoints: the specialist's decisions (persisted) and the assistant proxy. */
import { useQuery } from "@tanstack/react-query";
import type { AssistantRequest, SpecialistDecisionCreate } from "./generated";
import { buildPath, request } from "./client";
import {
  bool,
  isoDate,
  isoDateTime,
  literal,
  nullable,
  num,
  object,
  str,
} from "./schema";
import { pageSchema } from "./types";

export const specialistDecisionSchema = object({
  id: num,
  created_at: isoDateTime,
  origin: isoDate,
  run_id: nullable(str),
  sim_day: num,
  subject_kind: literal("alert", "patient"),
  subject_id: str,
  region_code: nullable(str),
  org_code: nullable(str),
  profile_code: nullable(str),
  action: literal("accept", "decline", "clarify", "confirm", "postpone"),
  comment: nullable(str),
  actor: nullable(str),
  idempotency_key: nullable(str),
  api_key_label: nullable(str),
});
export const assistantStatusSchema = object({
  configured: bool,
  provider: nullable(str),
  model: nullable(str),
});
export const assistantReplySchema = object({
  text: str,
  provider: str,
  model: str,
});

export const specialistApi = {
  decisions: (origin: string, runId: string) =>
    request(
      pageSchema(specialistDecisionSchema),
      buildPath("/specialist-decisions", {
        origin,
        run_id: runId,
        limit: 500,
        offset: 0,
      }),
    ),
  createDecision: (payload: SpecialistDecisionCreate) =>
    request(specialistDecisionSchema, "/specialist-decisions", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }),
  assistantStatus: () => request(assistantStatusSchema, "/assistant/status"),
  ask: (payload: AssistantRequest) =>
    request(assistantReplySchema, "/assistant", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }),
};

export const useSpecialistDecisions = (
  origin: string | null,
  runId: string | null,
) =>
  useQuery({
    queryKey: ["specialist-decisions", origin, runId],
    queryFn: () => specialistApi.decisions(origin ?? "", runId ?? ""),
    enabled: Boolean(origin && runId),
    staleTime: 60_000,
    retry: false,
  });

export const useAssistantStatus = () =>
  useQuery({
    queryKey: ["assistant", "status"],
    queryFn: specialistApi.assistantStatus,
    staleTime: 5 * 60_000,
    retry: false,
  });
