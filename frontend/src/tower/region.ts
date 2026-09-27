/**
 * "Only my region": a bureau specialist works one oblast. The choice is a per-browser convenience kept in
 * localStorage and shared by the inbox and the map through a tiny external store; an empty code means the whole
 * country. The store lives apart from the component so that editing one does not reload the other.
 */
import { useSyncExternalStore } from "react";

const STORAGE_KEY = "hqai.region";
const listeners = new Set<() => void>();

function read(): string {
  try {
    return globalThis.localStorage?.getItem(STORAGE_KEY) ?? "";
  } catch {
    return "";
  }
}

let current = read();

export function setRegionFilter(code: string): void {
  if (code === current) return;
  current = code;
  try {
    if (code) globalThis.localStorage?.setItem(STORAGE_KEY, code);
    else globalThis.localStorage?.removeItem(STORAGE_KEY);
  } catch {
    // private mode: the choice lives for the session only
  }
  listeners.forEach((listener) => listener());
}

const subscribe = (listener: () => void) => {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
};

const get = () => current;

/** Test hook: back to the whole country. */
export function resetRegionFilter(): void {
  setRegionFilter("");
}

export function useRegionFilter(): [string, (code: string) => void] {
  return [useSyncExternalStore(subscribe, get, get), setRegionFilter];
}
