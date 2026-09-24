/**
 * "Explain in plain words": a deterministic paragraph builder over the published facts of one alert. No language
 * model is involved; every sentence is a template filled with values from the API or the labelled simulation.
 * Templates exist in Russian and Kazakh and follow the current language.
 */
import { getLang, t } from "../../i18n";
import { fmtDate, fmtNumber } from "../../lib/format";
import { reasonLabel } from "../../demo/language";
import type { Urgency } from "../synthetic";
import { daysBetween, flowDecimals, urgencyOf } from "../synthetic";
import type { SimAlert } from "./simulation";

export interface PlainExplanation {
  urgency: Urgency;
  paragraphs: string[];
}

interface Templates {
  expects: (
    hospital: string,
    profile: string,
    central: string,
    threshold: string | null,
  ) => string;
  support: Record<"DIRECT_SUPPORTED" | "FALLBACK_LIMITED" | "other", string>;
  spread: (lower: string, upper: string, coverage: string) => string;
  crossing: (date: string, lead: number | null) => string;
  confirmed: (observed: string) => string;
  notConfirmed: string;
  unverified: string;
  escalated: string;
  queue: (n: number) => string;
  noQueue: string;
  role: string;
}

const RU: Templates = {
  expects: (hospital, profile, central, threshold) =>
    `В стационаре «${hospital}» по профилю «${profile.toLowerCase()}» модель ожидает ${central} регистраций в день${threshold ? ` при обычном уровне ${threshold}` : ""}.`,
  support: {
    DIRECT_SUPPORTED: "Прогноз опирается на собственную историю этого ряда.",
    FALLBACK_LIMITED:
      "Собственной истории ряда мало, поэтому прогноз построен по региону и профилю — доверять ему стоит осторожнее.",
    other:
      "Данных ряда недостаточно, чтобы считать сигнал подтверждённым свидетельством.",
  },
  spread: (lower, upper, coverage) =>
    `Разброс прогноза — от ${lower} до ${upper} регистраций в день (интервал с номинальным покрытием ${coverage}).`,
  crossing: (date, lead) => {
    const when =
      lead === null
        ? ""
        : lead < 0
          ? " — дата уже прошла"
          : lead === 0
            ? " — сегодня"
            : lead === 1
              ? " — завтра"
              : lead < 5
                ? ` — через ${lead} дня`
                : ` — через ${lead} дней`;
    return `Первое превышение ожидается ${date}${when}.`;
  },
  confirmed: (observed) =>
    `В симуляции это подтвердилось: наблюдаемый поток составил ${observed} регистраций в день.`,
  notConfirmed:
    "В симуляции поток остался ниже ориентира — сигнал не подтвердился.",
  unverified:
    "Данные из региона не поступили, поэтому система не может ни подтвердить, ни снять предупреждение — и не додумывает.",
  escalated:
    "Наблюдаемый поток оказался выше ожидаемого, и уровень сигнала повышен по факту, а не по прогнозу.",
  queue: (n) =>
    `В окно прогноза попадают ${n} ${n === 1 ? "направление" : n < 5 ? "направления" : "направлений"} из очереди на плановую госпитализацию — им стоит подтвердить даты заранее.`,
  noQueue: "В окно прогноза не попадает ни одно направление из очереди.",
  role: "Система не распределяет пациентов и не назначает лечение: она показывает, где ждать давление, а решение принимает специалист.",
};

const KK: Templates = {
  expects: (hospital, profile, central, threshold) =>
    `«${hospital}» стационарында «${profile.toLowerCase()}» бейіні бойынша модель күніне ${central} тіркеу күтеді${threshold ? ` (әдеттегі деңгей ${threshold})` : ""}.`,
  support: {
    DIRECT_SUPPORTED: "Болжам осы қатардың өз тарихына сүйенеді.",
    FALLBACK_LIMITED:
      "Қатардың өз тарихы аз, сондықтан болжам өңір мен бейін бойынша құрылған — оған сақтықпен сену керек.",
    other: "Сигналды расталған дәлел деп санауға қатар деректері жеткіліксіз.",
  },
  spread: (lower, upper, coverage) =>
    `Болжамның ауытқуы — күніне ${lower}-ден ${upper}-ге дейін тіркеу (номиналды қамтуы ${coverage} аралық).`,
  crossing: (date, lead) => {
    const when =
      lead === null
        ? ""
        : lead < 0
          ? " — күні өтіп кетті"
          : lead === 0
            ? " — бүгін"
            : lead === 1
              ? " — ертең"
              : ` — ${lead} күннен кейін`;
    return `Алғашқы асып кету ${date} күтіледі${when}.`;
  },
  confirmed: (observed) =>
    `Симуляцияда бұл расталды: байқалған ағын күніне ${observed} тіркеу болды.`,
  notConfirmed: "Симуляцияда ағын бағдардан төмен қалды — сигнал расталмады.",
  unverified:
    "Өңірден деректер түспеді, сондықтан жүйе ескертуді растай да, алып тастай да алмайды — және ойдан шығармайды.",
  escalated:
    "Байқалған ағын күтілгеннен жоғары болып шықты, сигнал деңгейі болжам бойынша емес, факт бойынша көтерілді.",
  queue: (n) =>
    `Болжам терезесіне жоспарлы госпитализация кезегінен ${n} жолдама түседі — олардың күндерін алдын ала растаған жөн.`,
  noQueue: "Болжам терезесіне кезектегі бірде-бір жолдама түспейді.",
  role: "Жүйе пациенттерді бөлмейді және ем тағайындамайды: ол қысымды қай жерден күту керектігін көрсетеді, ал шешімді маман қабылдайды.",
};

export function plainExplanation(
  alert: SimAlert,
  waiting: number,
  today: string,
): PlainExplanation {
  const tpl = getLang() === "kk" ? KK : RU;
  const central =
    alert.central === null
      ? "—"
      : fmtNumber(alert.central, flowDecimals(alert.central));
  const threshold =
    alert.threshold === null
      ? null
      : fmtNumber(alert.threshold, flowDecimals(alert.threshold));
  const lead = alert.crossing ? daysBetween(today, alert.crossing) : null;

  const first: string[] = [
    tpl.expects(alert.hospitalName, alert.profileName, central, threshold),
  ];
  const reason = alert.reasons.map(reasonLabel).find((r) => !/_/.test(r));
  if (reason) first.push(`${reason}.`);

  const second: string[] = [];
  if (alert.lower !== null && alert.upper !== null && alert.coverage)
    second.push(
      tpl.spread(
        fmtNumber(alert.lower, flowDecimals(alert.lower)),
        fmtNumber(alert.upper, flowDecimals(alert.upper)),
        alert.coverage,
      ),
    );
  second.push(
    alert.support === "DIRECT_SUPPORTED"
      ? tpl.support.DIRECT_SUPPORTED
      : alert.support === "FALLBACK_LIMITED"
        ? tpl.support.FALLBACK_LIMITED
        : tpl.support.other,
  );

  const third: string[] = [];
  if (alert.crossing) third.push(tpl.crossing(fmtDate(alert.crossing), lead));
  if (alert.phase === "confirmed" && alert.observed !== null)
    third.push(
      tpl.confirmed(fmtNumber(alert.observed, flowDecimals(alert.observed))),
    );
  else if (alert.phase === "not_confirmed") third.push(tpl.notConfirmed);
  else if (alert.phase === "unverified") third.push(tpl.unverified);
  else if (alert.phase === "escalated") third.push(tpl.escalated);

  const fourth = [waiting === 0 ? tpl.noQueue : tpl.queue(waiting), tpl.role];

  return {
    urgency: urgencyOf(
      alert.severity,
      lead ?? alert.lead,
      alert.central,
      alert.support,
    ),
    paragraphs: [first, second, third, fourth]
      .map((p) => p.join(" "))
      .filter(Boolean),
  };
}

export const urgencyText = (u: Urgency) => ({
  label: t.control.urgency[u],
  hint: t.control.urgency[`${u}Hint` as const],
});
