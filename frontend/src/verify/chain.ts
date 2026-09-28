/**
 * Independent verification of the public ledger export in the browser: the same rules as tools/ledger_verify.py
 * (canonical line encoding, protocol v1 genesis, contiguous seq, prev_hash links, recomputed SHA-256 entry hashes,
 * optional trusted head). It never looks at the server's own verdict. What it cannot see — the private salts and the
 * current database rows — is the server verification's job (docs/transparency-ledger.md §7–8).
 */
import { CanonicalError, canonicalText, parseStrict } from "./canonical";
import { hashEngine, sha256Hex, type HashEngine } from "./sha256";

export interface PublicEntry {
  seq: number;
  created_at: string;
  event_type: string;
  subject: string;
  payload: Record<string, unknown>;
  prev_hash: string;
  entry_hash: string;
}

export const ZERO_HASH = "0".repeat(64);
export const GENESIS = {
  seq: 1,
  created_at: "2026-09-28T00:00:00.000000Z",
  event_type: "ledger.genesis",
  subject: "ledger:aqyl-kezek",
  payload: {
    canonicalization: "hqai-canonical-json-v1",
    commitment_scheme: "sha256-salted-v1",
    hash_algorithm: "sha256",
    protocol: "aqyl-kezek-transparency-ledger",
    protocol_version: 1,
  },
  prev_hash: ZERO_HASH,
} as const;

const FIELDS = [
  "created_at",
  "entry_hash",
  "event_type",
  "payload",
  "prev_hash",
  "seq",
  "subject",
];
const HASH = /^[0-9a-f]{64}$/;
const TIMESTAMP = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{6}Z$/;
const EVENT = /^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)+$/;

export interface TrustedHead {
  seq: number;
  hash: string;
}

export interface ChainVerdict {
  status: "OK" | "BROKEN";
  entries: number;
  verifiedThroughSeq: number;
  headSeq: number | null;
  headHash: string | null;
  failureSeq: number | null;
  reasonCode: string | null;
  detail: string | null;
  trustedHeadChecked: boolean;
  engine: HashEngine;
  durationMs: number;
}

class Broken extends Error {
  constructor(
    readonly code: string,
    readonly seq: number | null,
    detail: string,
  ) {
    super(detail);
  }
}

/** SHA-256 over the canonical form of the six hashed fields. */
export async function entryHash(
  entry: Omit<PublicEntry, "entry_hash">,
): Promise<string> {
  const material = {
    created_at: entry.created_at,
    event_type: entry.event_type,
    payload: entry.payload,
    prev_hash: entry.prev_hash,
    seq: entry.seq,
    subject: entry.subject,
  };
  return sha256Hex(new TextEncoder().encode(canonicalText(material)));
}

function checkEntry(value: unknown, expected: number): PublicEntry {
  if (
    typeof value !== "object" ||
    value === null ||
    Array.isArray(value) ||
    Object.keys(value).sort().join() !== FIELDS.join()
  )
    throw new Broken(
      "MALFORMED_ENTRY",
      expected,
      "an entry has exactly seven fields",
    );
  const e = value as Record<string, unknown>;
  if (typeof e.seq !== "number" || !Number.isInteger(e.seq) || e.seq < 1)
    throw new Broken("MALFORMED_ENTRY", expected, "seq");
  const seq = e.seq;
  if (typeof e.created_at !== "string" || !TIMESTAMP.test(e.created_at))
    throw new Broken("NONCANONICAL_VALUE", seq, "created_at");
  if (typeof e.event_type !== "string" || !EVENT.test(e.event_type))
    throw new Broken("MALFORMED_ENTRY", seq, "event_type");
  if (
    typeof e.subject !== "string" ||
    e.subject.length === 0 ||
    e.subject.length > 256
  )
    throw new Broken("MALFORMED_ENTRY", seq, "subject");
  if (
    typeof e.payload !== "object" ||
    e.payload === null ||
    Array.isArray(e.payload)
  )
    throw new Broken("MALFORMED_ENTRY", seq, "payload");
  for (const name of ["prev_hash", "entry_hash"])
    if (typeof e[name] !== "string" || !HASH.test(e[name] as string))
      throw new Broken("MALFORMED_ENTRY", seq, name);
  return e as unknown as PublicEntry;
}

function isGenesis(entry: PublicEntry): boolean {
  return (
    entry.seq === GENESIS.seq &&
    entry.created_at === GENESIS.created_at &&
    entry.event_type === GENESIS.event_type &&
    entry.subject === GENESIS.subject &&
    entry.prev_hash === GENESIS.prev_hash &&
    canonicalText(entry.payload) === canonicalText(GENESIS.payload)
  );
}

/** Split an export into lines; the export ends every line with "\n". */
export function exportLines(text: string): string[] {
  const lines = text.split("\n");
  if (lines.at(-1) === "") lines.pop();
  return lines;
}

/** Verify the JSONL export text. Never throws: the verdict carries the reason. */
export async function verifyExport(
  text: string,
  trusted?: TrustedHead | null,
  now: () => number = () => performance.now(),
): Promise<ChainVerdict> {
  const started = now();
  let previous: PublicEntry | null = null;
  let count = 0;
  let trustedSeen = false;
  const verdict = (
    status: "OK" | "BROKEN",
    code: string | null,
    seq: number | null,
    detail: string | null,
  ): ChainVerdict => ({
    status,
    entries: count,
    verifiedThroughSeq: previous?.seq ?? 0,
    headSeq: previous?.seq ?? null,
    headHash: previous?.entry_hash ?? null,
    failureSeq: seq,
    reasonCode: code,
    detail,
    trustedHeadChecked: Boolean(trusted) && trustedSeen,
    engine: hashEngine(),
    durationMs: Math.round(now() - started),
  });
  try {
    const lines = exportLines(text);
    for (const [index, line] of lines.entries()) {
      const expected: number = previous ? previous.seq + 1 : 1;
      let parsed: unknown;
      try {
        parsed = parseStrict(line);
      } catch (error) {
        throw new Broken(
          "NONCANONICAL_VALUE",
          expected,
          `line ${index + 1}: ${error instanceof Error ? error.message : String(error)}`,
        );
      }
      const entry = checkEntry(parsed, expected);
      if (canonicalText(entry) !== line)
        throw new Broken(
          "NONCANONICAL_ENCODING",
          entry.seq,
          `line ${index + 1} is not canonical`,
        );
      if (entry.seq !== expected) {
        const code =
          previous && entry.seq === previous.seq
            ? "DUPLICATE_SEQ"
            : entry.seq < expected
              ? "SEQUENCE_ORDER"
              : "SEQUENCE_GAP";
        throw new Broken(
          code,
          entry.seq,
          `expected ${expected}, found ${entry.seq}`,
        );
      }
      if (entry.seq === 1) {
        if (!isGenesis(entry))
          throw new Broken("GENESIS_INVALID", 1, "not the protocol genesis");
      } else if (entry.prev_hash !== previous?.entry_hash) {
        throw new Broken("PREV_HASH_MISMATCH", entry.seq, "prev_hash");
      }
      if ((await entryHash(entry)) !== entry.entry_hash)
        throw new Broken("ENTRY_HASH_MISMATCH", entry.seq, "entry_hash");
      if (trusted && entry.seq === trusted.seq) {
        if (entry.entry_hash !== trusted.hash)
          throw new Broken(
            "TRUSTED_HEAD_MISMATCH",
            entry.seq,
            "differs from the head recorded earlier",
          );
        trustedSeen = true;
      }
      previous = entry;
      count++;
    }
    if (!previous) return verdict("BROKEN", "EMPTY_LEDGER", null, "no entries");
    if (trusted && !trustedSeen)
      return verdict(
        "BROKEN",
        "TRUSTED_HEAD_MISSING",
        trusted.seq,
        "shorter than the head recorded earlier",
      );
    return verdict("OK", null, null, null);
  } catch (error) {
    if (error instanceof Broken)
      return verdict("BROKEN", error.code, error.seq, error.message);
    if (error instanceof CanonicalError)
      return verdict("BROKEN", "NONCANONICAL_VALUE", null, error.message);
    throw error;
  }
}
