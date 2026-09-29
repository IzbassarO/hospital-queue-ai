/**
 * The browser implementation against the shared vectors (docs/transparency-ledger-vectors.json), which the Python
 * verifiers are tested against too: identical canonical text, SHA-256, error codes and chain hashes.
 */
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";
import { canonicalText, parseStrict, CanonicalError } from "./canonical";
import { entryHash, verifyExport, type PublicEntry } from "./chain";
import { sha256Fallback, sha256Hex } from "./sha256";

interface Vectors {
  valid: { name: string; value: unknown; canonical: string; sha256: string }[];
  invalid: { name: string; json: string; error: string }[];
  noncanonical: { name: string; json: string; canonical: string }[];
  genesis: PublicEntry;
  chain: PublicEntry[];
}

const vectors = JSON.parse(
  readFileSync(
    resolve(process.cwd(), "../docs/transparency-ledger-vectors.json"),
    "utf8",
  ),
) as Vectors;
const bytes = (text: string) => new TextEncoder().encode(text);
const jsonl = (entries: unknown[]) =>
  entries.map((e) => `${canonicalText(e)}\n`).join("");

describe("canonical JSON vectors", () => {
  it.each(vectors.valid.map((v) => [v.name, v]))(
    "%s: same text and SHA-256 as Python",
    async (_name, vector) => {
      expect(canonicalText(vector.value)).toBe(vector.canonical);
      expect(await sha256Hex(bytes(vector.canonical))).toBe(vector.sha256);
      expect(sha256Fallback(bytes(vector.canonical))).toBe(vector.sha256);
      expect(parseStrict(vector.canonical)).toEqual(vector.value);
    },
  );

  it.each(vectors.invalid.map((v) => [v.name, v]))(
    "%s is rejected with the shared code",
    (_name, vector) => {
      let code: string | null = null;
      try {
        parseStrict(vector.json);
      } catch (error) {
        code = error instanceof CanonicalError ? error.code : "other";
      }
      expect(code).toBe(vector.error);
    },
  );

  it.each(vectors.noncanonical.map((v) => [v.name, v]))(
    "%s parses but re-encodes canonically",
    (_name, vector) => {
      const text = canonicalText(parseStrict(vector.json));
      expect(text).toBe(vector.canonical);
      expect(text).not.toBe(vector.json);
    },
  );

  it("rejects values the contract excludes", () => {
    expect(() => canonicalText(1.5)).toThrow(/FLOAT_NOT_ALLOWED/);
    expect(() => canonicalText({ A: 1 })).toThrow(/INVALID_KEY/);
    expect(() => canonicalText("\ud800")).toThrow(/LONE_SURROGATE/);
    expect(() => canonicalText(2 ** 53)).toThrow(/INTEGER_OUT_OF_RANGE/);
    expect(() => canonicalText(undefined)).toThrow(/UNSUPPORTED_TYPE/);
  });

  it("hashes long inputs identically with Web Crypto and the fallback", async () => {
    for (const size of [0, 55, 56, 63, 64, 65, 1000, 100_000]) {
      const data = bytes("ә".repeat(size));
      expect(sha256Fallback(data)).toBe(await sha256Hex(data));
    }
  });
});

describe("chain verification", () => {
  it("recomputes the golden chain hashes", async () => {
    for (const entry of vectors.chain)
      expect(await entryHash(entry)).toBe(entry.entry_hash);
    expect(vectors.chain[0]).toEqual(vectors.genesis);
  });

  it("verifies the golden chain", async () => {
    const verdict = await verifyExport(jsonl(vectors.chain));
    expect(verdict.status).toBe("OK");
    expect(verdict.entries).toBe(vectors.chain.length);
    expect(verdict.headHash).toBe(vectors.chain.at(-1)?.entry_hash);
  });

  const broken = async (
    entries: unknown[],
    trusted?: { seq: number; hash: string },
  ) => verifyExport(jsonl(entries), trusted);
  const clone = () => structuredClone(vectors.chain) as PublicEntry[];

  it("finds an altered payload", async () => {
    const chain = clone();
    (chain[3].payload as Record<string, unknown>).action = "decline";
    const verdict = await broken(chain);
    expect([verdict.status, verdict.failureSeq, verdict.reasonCode]).toEqual([
      "BROKEN",
      4,
      "ENTRY_HASH_MISMATCH",
    ]);
    expect(verdict.verifiedThroughSeq).toBe(3);
  });

  it("finds an altered prev_hash", async () => {
    const chain = clone();
    chain[2].prev_hash = "f".repeat(64);
    expect((await broken(chain)).reasonCode).toBe("PREV_HASH_MISMATCH");
  });

  it("finds a deleted middle entry", async () => {
    const chain = clone();
    chain.splice(1, 1);
    const verdict = await broken(chain);
    expect([verdict.failureSeq, verdict.reasonCode]).toEqual([
      3,
      "SEQUENCE_GAP",
    ]);
  });

  it("finds reordered entries", async () => {
    const chain = clone();
    [chain[1], chain[2]] = [chain[2], chain[1]];
    expect((await broken(chain)).reasonCode).toBe("SEQUENCE_GAP");
  });

  it("finds a duplicated seq", async () => {
    const chain = clone();
    chain.splice(2, 0, chain[1]);
    expect((await broken(chain)).reasonCode).toBe("DUPLICATE_SEQ");
  });

  it("checks a trusted head", async () => {
    const chain = clone();
    const ok = await broken(chain, { seq: 2, hash: chain[1].entry_hash });
    expect(ok.status).toBe("OK");
    expect(ok.trustedHeadChecked).toBe(true);
    const wrong = await broken(chain, { seq: 2, hash: "e".repeat(64) });
    expect(wrong.reasonCode).toBe("TRUSTED_HEAD_MISMATCH");
    const beyond = await broken(chain, { seq: 99, hash: "e".repeat(64) });
    expect(beyond.reasonCode).toBe("TRUSTED_HEAD_MISSING");
  });

  it("rejects a malformed canonical value and a non-canonical line", async () => {
    const floatLine = jsonl(vectors.chain).replace(
      '"sim_day":2',
      '"sim_day":2.0',
    );
    const verdict = await verifyExport(floatLine);
    expect([verdict.failureSeq, verdict.reasonCode]).toEqual([
      4,
      "NONCANONICAL_VALUE",
    ]);
    const spaced = jsonl(vectors.chain).replace(
      '{"created_at"',
      '{ "created_at"',
    );
    expect((await verifyExport(spaced)).reasonCode).toBe(
      "NONCANONICAL_ENCODING",
    );
  });

  it("rejects a forged genesis and an empty export", async () => {
    const chain = clone();
    chain[0].payload = { protocol: "other" };
    expect((await broken(chain)).reasonCode).toBe("GENESIS_INVALID");
    expect((await verifyExport("")).reasonCode).toBe("EMPTY_LEDGER");
  });
});
