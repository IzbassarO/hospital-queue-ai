/** A SHA-256 shown shortened (first 8 … last 8, monospace) but always copyable in full. */
import { t } from "../i18n";
import { shortHash, useCopied } from "./copy";

export function HashValue({
  hash,
  large = false,
}: {
  hash: string;
  large?: boolean;
}) {
  const [copied, copy] = useCopied();
  return (
    <span className={`hash-value ${large ? "is-large" : ""}`}>
      <code className="hash-code" title={hash}>
        {shortHash(hash)}
      </code>
      <button
        type="button"
        className="hash-copy"
        aria-label={t.verify.copyHash(hash)}
        onClick={() => copy(hash)}
      >
        {copied ? t.verify.copied : t.verify.copy}
      </button>
      <span className="sr-only" role="status">
        {copied ? t.verify.copied : ""}
      </span>
    </span>
  );
}
