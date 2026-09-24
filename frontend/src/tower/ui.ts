/** UI state that must survive navigation: the task explorer and the subject opened in the dialog. */
import { useSyncExternalStore } from "react";

export type Subject =
  { kind: "alert"; id: string } | { kind: "patient"; id: string };
interface UiState {
  explorerOpen: boolean;
  subject: Subject | null;
}
let state: UiState = { explorerOpen: false, subject: null };
const listeners = new Set<() => void>();
const get = () => state;
const subscribe = (l: () => void) => {
  listeners.add(l);
  return () => listeners.delete(l);
};
function set(patch: Partial<UiState>) {
  state = { ...state, ...patch };
  listeners.forEach((l) => l());
}
export const useUi = () => useSyncExternalStore(subscribe, get, get);
export const toggleExplorer = () => set({ explorerOpen: !state.explorerOpen });
export const closeExplorer = () => set({ explorerOpen: false });
export const openSubject = (subject: Subject) => set({ subject });
export const closeSubject = () => set({ subject: null });
