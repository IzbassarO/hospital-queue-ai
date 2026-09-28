/**
 * The compact proof shown under a recorded decision: its ledger entry number and SHA-256, a link to check it and a
 * copy of the full hash. The decision stays the primary action; this is the evidence that it was recorded.
 */
import { Link } from "react-router-dom";
import type { LedgerReceipt } from "../api/transparency";
import { t } from "../i18n";
import { shortHash, useCopied } from "./copy";

function downloadJson(receipt: LedgerReceipt): void {
  const body = `${JSON.stringify(receipt, null, 2)}\n`;
  const url = URL.createObjectURL(
    new Blob([body], { type: "application/json" }),
  );
  const link = document.createElement("a");
  link.href = url;
  link.download = `aqyl-kezek-receipt-${receipt.ledger_seq}.json`;
  link.click();
  URL.revokeObjectURL(url);
}

export function DecisionReceipt({
  receipt,
  onOpen,
}: {
  receipt: LedgerReceipt;
  onOpen?: () => void;
}) {
  const [copied, copy] = useCopied();
  return (
    <section
      className="decision-receipt"
      aria-label={t.verify.receipt.title}
      data-testid="decision-receipt"
    >
      <p className="decision-receipt-entry">
        <span className="decision-receipt-mark" aria-hidden="true">
          ✓
        </span>
        <strong>{t.verify.receipt.entry(receipt.ledger_seq)}</strong>
      </p>
      <p className="decision-receipt-hash">
        <span>{t.verify.receipt.hash}:</span>{" "}
        <code title={receipt.entry_hash}>{shortHash(receipt.entry_hash)}</code>
      </p>
      <div className="decision-receipt-actions">
        <Link
          className="btn-ghost btn-sm"
          to={receipt.verify_path}
          onClick={onOpen}
        >
          {t.verify.receipt.verify}
        </Link>
        <button
          type="button"
          className="btn-ghost btn-sm"
          aria-label={t.verify.copyHash(receipt.entry_hash)}
          onClick={() => copy(receipt.entry_hash)}
        >
          {copied ? t.verify.copied : t.verify.receipt.copy}
        </button>
        <button
          type="button"
          className="btn-link btn-sm"
          onClick={() => downloadJson(receipt)}
        >
          {t.verify.receipt.download}
        </button>
      </div>
      <p className="decision-receipt-note">{t.verify.receipt.note}</p>
    </section>
  );
}
