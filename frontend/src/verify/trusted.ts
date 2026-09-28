/**
 * The head this browser saw last time: a (seq, hash) pair kept in localStorage. On the next visit the browser checks
 * that the ledger still contains exactly that entry, so a rewrite of history between visits is visible here even if
 * every hash after it was recomputed (docs/transparency-ledger.md §8). Per browser only; no server involved.
 */
import type { TrustedHead } from "./chain";

const KEY = "hqai.ledger.trustedHead";

export interface StoredHead extends TrustedHead {
  seenAt: string;
}

export function loadTrustedHead(): StoredHead | null {
  try {
    const raw = globalThis.localStorage?.getItem(KEY);
    if (!raw) return null;
    const value = JSON.parse(raw) as Partial<StoredHead>;
    if (
      typeof value.seq === "number" &&
      typeof value.hash === "string" &&
      /^[0-9a-f]{64}$/.test(value.hash) &&
      typeof value.seenAt === "string"
    )
      return { seq: value.seq, hash: value.hash, seenAt: value.seenAt };
  } catch {
    // unreadable or blocked storage: behave as a first visit
  }
  return null;
}

export function saveTrustedHead(head: StoredHead): void {
  try {
    globalThis.localStorage?.setItem(KEY, JSON.stringify(head));
  } catch {
    // private mode: nothing is remembered
  }
}

export function forgetTrustedHead(): void {
  try {
    globalThis.localStorage?.removeItem(KEY);
  } catch {
    // nothing to forget
  }
}
