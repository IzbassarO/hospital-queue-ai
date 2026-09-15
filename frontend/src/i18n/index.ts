/**
 * i18n entry point. The UI imports `t` from here and never from a language file directly, so adding a language
 * means a second file with the `Messages` shape and a switch below.
 */
import { type Messages, ru } from "./ru";

export const t: Messages = ru;
export const LANG = "ru";
export type { Messages };
