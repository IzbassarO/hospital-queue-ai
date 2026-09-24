/**
 * i18n entry point. `t` is a proxy over the current language's messages, so every component reads the live
 * language at render time. Switching the language notifies subscribers (`useLang`); layouts re-key their page so
 * the whole tree re-renders. The chosen language is remembered in localStorage.
 */
import { useSyncExternalStore } from "react";
import { kk } from "./kk";
import { type Messages, ru } from "./ru";

export type Lang = "ru" | "kk";
export const LANGS: Lang[] = ["ru", "kk"];
const STORAGE_KEY = "hqai.lang";
const MESSAGES: Record<Lang, Messages> = { ru, kk };

function readStored(): Lang {
  try {
    const stored = globalThis.localStorage?.getItem(STORAGE_KEY);
    return stored === "kk" ? "kk" : "ru";
  } catch {
    return "ru";
  }
}

let current: Lang = readStored();
const listeners = new Set<() => void>();

export const getLang = (): Lang => current;
export function setLang(lang: Lang): void {
  if (lang === current) return;
  current = lang;
  try {
    globalThis.localStorage?.setItem(STORAGE_KEY, lang);
  } catch {
    // private mode: the choice lives for the session only
  }
  if (typeof document !== "undefined") document.documentElement.lang = lang;
  listeners.forEach((l) => l());
}
const subscribe = (listener: () => void) => {
  listeners.add(listener);
  return () => listeners.delete(listener);
};
/** Current language, re-rendering the caller when it changes. */
export const useLang = (): Lang =>
  useSyncExternalStore(subscribe, getLang, getLang);

export const t: Messages = new Proxy({} as Messages, {
  get: (_target, key) => MESSAGES[current][key as keyof Messages],
  ownKeys: () => Reflect.ownKeys(MESSAGES[current]),
  getOwnPropertyDescriptor: (_target, key) =>
    Object.getOwnPropertyDescriptor(MESSAGES[current], key),
});
export type { Messages };
