/**
 * A data limitation, labelled rather than hidden: hospital, region and profile names come from the registry in
 * Russian and are never translated. The note renders only in a language whose copy defines it (Kazakh).
 */
import { t } from "../../i18n";

export function RegistryNote({ className = "" }: { className?: string }) {
  const text = t.control.registryNames;
  if (!text) return null;
  return <span className={`registry-note ${className}`}>{text}</span>;
}
