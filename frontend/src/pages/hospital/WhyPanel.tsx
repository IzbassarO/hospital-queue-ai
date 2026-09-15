import type { ExplanationFactor, HospitalCard } from "../../api/types";
import { Direction } from "../../components/Direction";
import { Section } from "../../components/PageHeader";
import { t } from "../../i18n";
import { fmtPercent, fmtSigned } from "../../lib/format";

function FactorList({
  title,
  unit,
  factors,
}: {
  title: string;
  unit: string;
  factors: ExplanationFactor[];
}) {
  return (
    <div className="card p-4">
      <h3 className="text-lg font-semibold">{title}</h3>
      <p className="mb-3 text-sm text-muted">{unit}</p>
      {factors.length === 0 ? (
        <p className="text-muted">{t.why.empty}</p>
      ) : (
        <ol className="divide-y divide-line/70">
          {factors.map((f) => (
            <li key={f.feature} className="flex items-start gap-3 py-2.5">
              <Direction direction={f.direction} />
              <div className="min-w-0 flex-1">
                <p className="font-medium" title={f.label}>
                  {f.short_label}
                </p>
                <p className="break-words text-sm text-muted">
                  {t.why.typicalValue}:{" "}
                  <span className="text-ink">
                    {f.most_common_value_display}
                  </span>
                </p>
                <p className="text-sm text-muted">
                  {t.why.share(fmtPercent(f.share_in_top5, 0))}
                </p>
              </div>
              <p className="num text-lg font-semibold">
                {fmtSigned(f.mean_effect, 1, ` ${f.unit}`)}
              </p>
            </li>
          ))}
        </ol>
      )}
    </div>
  );
}

export function WhyPanel({
  factors,
}: {
  factors: HospitalCard["explanation_factors"];
}) {
  return (
    <Section
      title={t.why.title}
      caption={t.why.caption(factors.n_referrals)}
      id="why"
    >
      <div className="grid gap-4 lg:grid-cols-2">
        <FactorList
          title={t.why.waitTitle}
          unit={t.why.waitUnit}
          factors={factors.wait_time}
        />
        <FactorList
          title={t.why.riskTitle}
          unit={t.why.riskUnit}
          factors={factors.refusal_risk}
        />
      </div>
    </Section>
  );
}
