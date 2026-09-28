/**
 * "Почему эта модель" — the tournament that chose what the queue table serves.
 *
 * Every number is read from the publication: the pre-committed metric, the rule as it was written before the run,
 * each competitor's Brier score overall and per horizon, and the verdict the rule produced. Nothing is computed
 * here and nothing is hardcoded, so the panel cannot drift away from the model that is actually serving.
 *
 * The baseline winning is the interesting case, not an embarrassment: the panel says in words that no candidate
 * cleared the rule, which is what a reviewer needs to see to trust the rest of the screen.
 */
import { t } from "../i18n";
import { fmtNumber, fmtPercent, fmtSigned } from "../lib/format";
import type { ReferralEstimatesPublication } from "../api/referral-estimates";

const HORIZONS = [7, 14, 30] as const;

export function ModelChoiceBlock({
  publication,
}: {
  publication: ReferralEstimatesPublication;
}) {
  const { selection, attention, estimate_tiers, abstention_counts } =
    publication;
  const abstained = Object.values(abstention_counts).reduce(
    (sum, n) => sum + n,
    0,
  );
  const total = publication.referral_count;
  const count = (value: number) => fmtNumber(value, 0);
  const tiers = Object.entries(estimate_tiers)
    .filter(([, n]) => n > 0)
    .sort((a, b) => b[1] - a[1]);

  return (
    <section className="hos-block" aria-label={t.hospital.why.title}>
      <div className="block-head">
        <h2>{t.hospital.why.title}</h2>
        <p>{t.hospital.why.subtitle(selection.metric)}</p>
      </div>

      {/* quoted, not paraphrased: this is the sentence that was frozen before the run, and the publication
          carries one Russian original. The label says so, so a Kazakh reader knows it is a quotation rather
          than a missing translation. */}
      <div className="hos-rule">
        <h3>
          {t.hospital.why.ruleLabel}{" "}
          <em className="hos-quoted">{t.hospital.why.quoted}</em>
        </h3>
        <p lang="ru">{selection.decision_rule}</p>
      </div>

      <div className="hos-table-scroll">
        <table className="hos-table hos-why-table">
          <thead>
            <tr>
              <th scope="col">{t.hospital.why.columns.model}</th>
              <th scope="col" className="is-secondary">
                {t.hospital.why.columns.role}
              </th>
              <th scope="col" className="is-num">
                {t.hospital.why.columns.overall}
              </th>
              {HORIZONS.map((h) => (
                <th key={h} scope="col" className="is-num is-secondary">
                  {t.hospital.why.columns.horizon(h)}
                </th>
              ))}
              <th scope="col" className="is-num">
                {t.hospital.why.columns.delta}
              </th>
              <th scope="col">{t.hospital.why.columns.verdict}</th>
            </tr>
          </thead>
          <tbody>
            {selection.candidates.map((row) => {
              const serving = row.model_key === selection.selected_model;
              const delta = row.overall_delta ?? null;
              const verdict =
                row.role === "baseline"
                  ? serving
                    ? t.hospital.why.verdict.serving
                    : t.hospital.why.verdict.baseline
                  : row.accepted
                    ? t.hospital.why.verdict.accepted
                    : t.hospital.why.verdict.rejected;
              return (
                <tr key={row.model_key} className={serving ? "is-serving" : ""}>
                  {/* the verdict column already says which model serves; repeating it here only crowds the name */}
                  <th scope="row">{t.hospital.why.models[row.model_key]}</th>
                  <td className="is-secondary">
                    {t.hospital.why.roles[row.role]}
                  </td>
                  <td className="is-num">
                    <b>{fmtNumber(row.overall_mean_brier, 4)}</b>
                  </td>
                  {HORIZONS.map((h) => (
                    <td key={h} className="is-num is-secondary">
                      {fmtNumber(row.brier_by_horizon[String(h)], 4)}
                    </td>
                  ))}
                  <td className="is-num">
                    {delta === null ? (
                      "—"
                    ) : (
                      <span
                        className={
                          delta < 0
                            ? "hos-delta is-better"
                            : "hos-delta is-worse"
                        }
                      >
                        {fmtSigned(delta, 4)}
                      </span>
                    )}
                  </td>
                  <td>
                    <span
                      className={`hos-verdictchip is-${
                        row.role === "baseline"
                          ? serving
                            ? "serving"
                            : "baseline"
                          : row.accepted
                            ? "accepted"
                            : "rejected"
                      }`}
                    >
                      {verdict}
                    </span>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      <p className="hos-sub-hint">{t.hospital.why.hint}</p>
      {selection.fallback_used ? (
        <p className="hos-warn" role="note">
          {t.hospital.why.fallbackNote}
        </p>
      ) : null}

      <div className="hos-sub">
        <h3>{t.hospital.why.tiers}</h3>
        <ul className="hos-tierlist" role="list">
          {tiers.map(([tier, n]) => (
            <li key={tier}>
              <span className={`hos-tier is-${tier}`}>
                {
                  t.hospital.estimates.tier[
                    tier as keyof typeof t.hospital.estimates.tier
                  ]
                }
              </span>
              <b>{fmtNumber(n, 0)}</b>
              <small>{fmtPercent(n / total, 1)}</small>
            </li>
          ))}
        </ul>
        <p className="hos-sub-hint">
          {t.hospital.why.abstained(count(abstained), count(total))} ·{" "}
          {t.hospital.estimates.attention.count(
            count(attention.flagged_count),
            count(total),
          )}
        </p>
        <p className="hos-sub-hint">
          <b>
            {t.hospital.estimates.degenerate.count(
              count(publication.degeneracy.count),
              count(total),
            )}
          </b>{" "}
          <span lang="ru">{publication.degeneracy.definition}</span>{" "}
          <em className="hos-quoted">{t.hospital.why.quoted}</em>
        </p>
        <p className="hos-sub-hint">
          {t.hospital.why.run(publication.source_run.run_id)} ·{" "}
          {t.hospital.why.identity}{" "}
          <code>{publication.publication_identity_sha256.slice(0, 12)}…</code>
        </p>
      </div>
    </section>
  );
}
