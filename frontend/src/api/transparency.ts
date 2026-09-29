/**
 * Transparency-ledger endpoints (docs/api.md, docs/transparency-ledger.md). Runtime schemas validate every response;
 * the transport types are generated from OpenAPI (./generated). The export is fetched as text because the browser
 * verifies its exact bytes, not a parsed copy.
 */
import { useQuery } from "@tanstack/react-query";
import { buildPath, request, requestText } from "./client";
import {
  array,
  isoDateTime,
  literal,
  nullable,
  num,
  object,
  record,
  str,
  unknownValue,
  type Infer,
} from "./schema";
import { pageSchema } from "./types";

export const ledgerReceiptSchema = object({
  ledger_seq: num,
  entry_hash: str,
  event_type: str,
  subject: str,
  created_at: isoDateTime,
  verify_path: str,
});
export type LedgerReceipt = Infer<typeof ledgerReceiptSchema>;

export const ledgerEntrySchema = object({
  seq: num,
  created_at: isoDateTime,
  event_type: str,
  subject: str,
  payload: record(unknownValue),
  prev_hash: str,
  entry_hash: str,
});
export type LedgerEntryItem = Infer<typeof ledgerEntrySchema>;

export const ledgerHeadSchema = object({
  seq: num,
  entry_hash: str,
  created_at: isoDateTime,
  chain_length: num,
  genesis_hash: str,
  protocol: str,
  protocol_version: num,
  canonicalization: str,
});
export type LedgerHead = Infer<typeof ledgerHeadSchema>;

const issueSchema = object({
  seq: nullable(num),
  reason_code: str,
  subject: nullable(str),
  detail: str,
});

export const ledgerVerificationSchema = object({
  status: literal("OK", "BROKEN"),
  mode: literal("server"),
  verified_at: isoDateTime,
  duration_ms: num,
  chain_length: num,
  verified_through_seq: num,
  head_seq: nullable(num),
  head_hash: nullable(str),
  failure_seq: nullable(num),
  reason_code: nullable(str),
  subject: nullable(str),
  issues: array(issueSchema),
  covered_decisions: num,
  covered_publications: num,
  checks: array(str),
});
export type LedgerVerification = Infer<typeof ledgerVerificationSchema>;

export const transparencyApi = {
  head: () => request(ledgerHeadSchema, "/transparency/head"),
  entries: (limit: number) =>
    request(
      pageSchema(ledgerEntrySchema),
      buildPath("/transparency/entries", { limit, order: "desc" }),
    ),
  entry: (seq: number) =>
    request(ledgerEntrySchema, `/transparency/entries/${seq}`),
  lookup: (query: { entry_hash?: string; subject?: string }) =>
    request(array(ledgerEntrySchema), buildPath("/transparency/lookup", query)),
  verify: () => request(ledgerVerificationSchema, "/transparency/verify"),
  exportText: () => requestText("/transparency/export"),
};

export const useLedgerHead = () =>
  useQuery({
    queryKey: ["transparency", "head"],
    queryFn: transparencyApi.head,
    staleTime: 10_000,
    retry: false,
  });

export const useLedgerEntries = (limit: number) =>
  useQuery({
    queryKey: ["transparency", "entries", limit],
    queryFn: () => transparencyApi.entries(limit),
    staleTime: 10_000,
    retry: false,
  });

/** The server's own verdict; re-run on demand (refetch). */
export const useServerVerification = () =>
  useQuery({
    queryKey: ["transparency", "verify"],
    queryFn: transparencyApi.verify,
    staleTime: 0,
    retry: false,
  });
