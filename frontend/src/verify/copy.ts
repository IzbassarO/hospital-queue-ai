/** Shortened hashes and copying them in full, shared by the verification page and the decision receipt. */
import { useEffect, useState } from "react";

export const shortHash = (hash: string) =>
  hash.length > 20 ? `${hash.slice(0, 8)}…${hash.slice(-8)}` : hash;

/** Copy text; resolves false when the browser refuses (no clipboard API outside a secure context). */
export async function copyText(text: string): Promise<boolean> {
  try {
    if (navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(text);
      return true;
    }
  } catch {
    // fall through to the selection fallback
  }
  try {
    const area = document.createElement("textarea");
    area.value = text;
    area.setAttribute("readonly", "");
    area.style.position = "fixed";
    area.style.opacity = "0";
    document.body.appendChild(area);
    area.select();
    const ok = document.execCommand?.("copy") ?? false;
    area.remove();
    return ok;
  } catch {
    return false;
  }
}

export function useCopied(): [boolean, (text: string) => void] {
  const [copied, setCopied] = useState(false);
  useEffect(() => {
    if (!copied) return;
    const timer = window.setTimeout(() => setCopied(false), 1800);
    return () => window.clearTimeout(timer);
  }, [copied]);
  return [copied, (text: string) => void copyText(text).then(setCopied)];
}
