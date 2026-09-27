/** Labels of the synthetic layer: the tag on every generated element, and the note shown when the layer is off. */
import { t } from "../../i18n";
import { fmtDate } from "../../lib/format";

export function SyntheticTag({ published = false }: { published?: boolean }) {
  return (
    <span
      className={`synthetic-tag ${published ? "is-published" : ""}`}
      title={published ? t.control.publication : t.control.synthetic}
    >
      {published ? t.control.publishedTag : t.control.syntheticTag}
    </span>
  );
}

/** The counterpart of SyntheticTag for a block that carries published facts only. */
export function PublishedTag() {
  return <SyntheticTag published />;
}

export function SyntheticOffNote({ origin }: { origin: string }) {
  return (
    <section
      className="simbar simbar-off"
      role="status"
      aria-label={t.control.syntheticOff.title}
    >
      <strong>{t.control.syntheticOff.title}</strong>
      <p>{t.control.syntheticOff.body(fmtDate(origin))}</p>
    </section>
  );
}
