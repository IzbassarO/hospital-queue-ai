/**
 * Human-language layer for the guided journey. Maps published machine vocabulary (reason codes, statuses,
 * English evidence sentences) to approved Russian product language. Unknown tokens are never invented:
 * they stay in the technical provenance layer and are reported by `isTechnical`.
 */
import { getLang, t } from "../i18n";
import { fmtDate, fmtNumber } from "../lib/format";

/** Pick the map of the current language. Kazakh maps mirror the Russian ones key by key. */
const pick = <T>(ru: T, kk: T): T => (getLang() === "kk" ? kk : ru);

export type Severity = "HIGH" | "ELEVATED" | "WATCH" | "NORMAL" | "UNSUPPORTED";

export const severityLabel = (value: string): string =>
  t.tower.status[value] ?? value;

/** Adjective form used in the DETECT headline ("Потенциальное … давление потока"). */
const SEVERITY_ADJECTIVE_RU: Record<string, string> = {
  HIGH: "высокое",
  ELEVATED: "повышенное",
  WATCH: "умеренное",
  NORMAL: "нормальное",
  UNSUPPORTED: "неподтверждённое",
};
const SEVERITY_ADJECTIVE_KK: Record<string, string> = {
  HIGH: "жоғары",
  ELEVATED: "көтеріңкі",
  WATCH: "орташа",
  NORMAL: "қалыпты",
  UNSUPPORTED: "расталмаған",
};
export const severityAdjective: Record<string, string> = new Proxy(
  {},
  {
    get: (_target, key) =>
      pick(SEVERITY_ADJECTIVE_RU, SEVERITY_ADJECTIVE_KK)[key as string],
  },
);

const REASON_CODES_RU: Record<string, string> = {
  CALIBRATED_LOWER_EXCEEDS_HISTORICAL_FLOW_THRESHOLD:
    "Даже нижняя граница калиброванного интервала выше исторического ориентира потока",
  CENTRAL_FORECAST_EXCEEDS_HISTORICAL_FLOW_THRESHOLD:
    "Центральный прогноз выше исторического ориентира потока",
  CALIBRATED_UPPER_EXCEEDS_HISTORICAL_FLOW_THRESHOLD:
    "Верхняя граница интервала выше исторического ориентира — режим наблюдения",
  FORECAST_BELOW_HISTORICAL_FLOW_THRESHOLD:
    "Прогноз ниже исторического ориентира потока",
  OBSERVED_WEEKLY_RESIDUAL_EXCEEDS_ROBUST_THRESHOLD:
    "Наблюдаемый недельный поток необычен относительно собственной истории",
  SCENARIO_SENSITIVITY_RANGE_UNAVAILABLE:
    "Для сценария нет пригодной неопределённости базовой линии",
};

const STATUS_LABELS_RU: Record<string, string> = {
  materiality_rule_not_triggered: "Порог материальности не отсеял сигнал",
  materiality_rule_triggered: "Сигнал ниже порога материальности",
  supported: "Ориентир подтверждён историей ряда",
  unsupported: "Ориентир не подтверждён историей ряда",
  none: "Аномалий не наблюдается",
  UNUSUAL_HIGH: "Необычно высокий наблюдаемый поток",
  UNUSUAL_LOW: "Необычно низкий наблюдаемый поток",
  DIRECT_SUPPORTED: "Прямая поддержка данными",
  FALLBACK_LIMITED: "Резервный прогноз, ограниченная поддержка",
  UNSUPPORTED: "Не поддержан данными",
  CALIBRATED: "Калиброванный интервал",
  INSUFFICIENT_CALIBRATION_SUPPORT: "Недостаточно данных для калибровки",
  UNAVAILABLE: "Интервал недоступен",
  NOT_APPLICABLE: "Не требуется",
  REGION_PROFILE_FALLBACK: "Резерв: регион × профиль",
  OTHER_FALLBACK: "Другой резервный источник",
  DETERMINISTIC: "Детерминированное объяснение из опубликованных свидетельств",
  DETERMINISTIC_FALLBACK:
    "Детерминированное объяснение из опубликованных свидетельств · резервный режим",
  NARRATED: "Объяснение с текстовым сопровождением",
  VERIFIED_FULL_ENGINE: "Полная проверка сценарным движком пройдена",
  FAST_PATH_ONLY: "Только быстрая проверка",
  VERIFICATION_FAILED: "Проверка не пройдена",
  COMPLETE: "Полный диапазон",
  RANGE_LIMITED: "Ограниченный диапазон",
  ROBUST_TO_TRANSFORMED_RANGE: "Устойчиво к производному диапазону",
  NOT_ROBUST_TO_TRANSFORMED_RANGE: "Не устойчиво к производному диапазону",
  RANGE_EVIDENCE_INCOMPLETE: "Свидетельства диапазона неполны",
  NOT_PHYSICAL_CAPACITY_VALIDATED: "Физическая вместимость не проверялась",
  THRESHOLD_COMPARATOR_ASSUMPTION:
    "Ориентир приёмника — историческая величина, не пересчитанная под перенос",
  PHYSICAL_FEASIBILITY_UNKNOWN: "Физическая осуществимость неизвестна",
  direct_supported: "Прямая поддержка данными",
  fallback_or_limited_history: "Резервный прогноз, ограниченная история",
  TRANSFORMED_BASELINE_UNCERTAINTY_RANGE:
    "Производный диапазон чувствительности",
  NOT_SCENARIO_ADJUSTED: "Сценарий не затрагивает",
  identity: "Воспроизведение базовой линии",
  demand_multiplier: "Множитель ожидаемых регистраций",
  all_hospitals: "все стационары",
  ACCEPTED: "Принято",
  REJECTED: "Отклонено",
  EXPERIMENTAL: "Экспериментально",
  EVALUATION_ONLY: "Только для оценки",
  ELIGIBLE_AFTER_INGESTION: "Допустимо в продукте после публикации",
  NOT_FOR_PRODUCT: "Не для продукта",
  REFERENCE_ONLY: "Справочно",
};

const ABSTENTION_CODES_RU: Record<string, string> = {
  RECEIVER_BLOCKED:
    "Ни у одного ряда-приёмника того же профиля в регионе нет модельного запаса по историческому ориентиру на всех затронутых днях",
  RECEIVER_OUTSIDE_SAME_REGION_POLICY:
    "Ряд-кандидат находится вне региона донора (политика «тот же регион»)",
  TRANSFER_BUDGET_INSUFFICIENT:
    "Бюджет переноса меньше минимально необходимой доли",
  NO_ELIGIBLE_RECEIVER: "Подходящих рядов-приёмников нет",
  DONOR_NOT_CENTRAL_DRIVEN:
    "Превышение донора не определяется центральным прогнозом",
};

const REASON_CODES_KK: Record<string, string> = {
  CALIBRATED_LOWER_EXCEEDS_HISTORICAL_FLOW_THRESHOLD:
    "Калибрленген аралықтың төменгі шекарасының өзі ағынның тарихи бағдарынан жоғары",
  CENTRAL_FORECAST_EXCEEDS_HISTORICAL_FLOW_THRESHOLD:
    "Орталық болжам ағынның тарихи бағдарынан жоғары",
  CALIBRATED_UPPER_EXCEEDS_HISTORICAL_FLOW_THRESHOLD:
    "Аралықтың жоғарғы шекарасы тарихи бағдардан жоғары — бақылау режимі",
  FORECAST_BELOW_HISTORICAL_FLOW_THRESHOLD:
    "Болжам ағынның тарихи бағдарынан төмен",
  OBSERVED_WEEKLY_RESIDUAL_EXCEEDS_ROBUST_THRESHOLD:
    "Байқалған апталық ағын өз тарихына қатысты әдеттен тыс",
  SCENARIO_SENSITIVITY_RANGE_UNAVAILABLE:
    "Сценарий үшін базалық сызықтың жарамды белгісіздігі жоқ",
};
const STATUS_LABELS_KK: Record<string, string> = {
  materiality_rule_not_triggered: "Маңыздылық шегі сигналды сүзіп тастамады",
  materiality_rule_triggered: "Сигнал маңыздылық шегінен төмен",
  supported: "Бағдар қатар тарихымен расталған",
  unsupported: "Бағдар қатар тарихымен расталмаған",
  none: "Аномалиялар байқалмайды",
  UNUSUAL_HIGH: "Әдеттен тыс жоғары байқалған ағын",
  UNUSUAL_LOW: "Әдеттен тыс төмен байқалған ағын",
  DIRECT_SUPPORTED: "Деректермен тікелей қолдау",
  FALLBACK_LIMITED: "Резервтік болжам, шектеулі қолдау",
  UNSUPPORTED: "Деректермен қолдаусыз",
  CALIBRATED: "Калибрленген аралық",
  INSUFFICIENT_CALIBRATION_SUPPORT: "Калибрлеуге деректер жеткіліксіз",
  UNAVAILABLE: "Аралық қолжетімсіз",
  NOT_APPLICABLE: "Қажет емес",
  REGION_PROFILE_FALLBACK: "Резерв: өңір × бейін",
  OTHER_FALLBACK: "Басқа резервтік көз",
  DETERMINISTIC: "Жарияланған дәлелдерден детерминирленген түсіндірме",
  DETERMINISTIC_FALLBACK:
    "Жарияланған дәлелдерден детерминирленген түсіндірме · резервтік режим",
  NARRATED: "Мәтіндік сүйемелдеуі бар түсіндірме",
  VERIFIED_FULL_ENGINE: "Сценарий қозғалтқышының толық тексеруінен өтті",
  FAST_PATH_ONLY: "Тек жылдам тексеру",
  VERIFICATION_FAILED: "Тексеруден өтпеді",
  COMPLETE: "Толық ауқым",
  RANGE_LIMITED: "Шектеулі ауқым",
  ROBUST_TO_TRANSFORMED_RANGE: "Туынды ауқымға төзімді",
  NOT_ROBUST_TO_TRANSFORMED_RANGE: "Туынды ауқымға төзімсіз",
  RANGE_EVIDENCE_INCOMPLETE: "Ауқым дәлелдері толық емес",
  NOT_PHYSICAL_CAPACITY_VALIDATED: "Физикалық сыйымдылық тексерілмеді",
  THRESHOLD_COMPARATOR_ASSUMPTION:
    "Қабылдаушының бағдары — ауыстыруға қайта есептелмеген тарихи шама",
  PHYSICAL_FEASIBILITY_UNKNOWN: "Физикалық жүзеге асырылуы белгісіз",
  direct_supported: "Деректермен тікелей қолдау",
  fallback_or_limited_history: "Резервтік болжам, шектеулі тарих",
  TRANSFORMED_BASELINE_UNCERTAINTY_RANGE: "Туынды сезімталдық ауқымы",
  NOT_SCENARIO_ADJUSTED: "Сценарий қозғамайды",
  identity: "Базалық сызықты қайта жаңғырту",
  demand_multiplier: "Күтілетін тіркеулер көбейткіші",
  all_hospitals: "барлық стационарлар",
  ACCEPTED: "Қабылданды",
  REJECTED: "Қабылданбады",
  EXPERIMENTAL: "Эксперименттік",
  EVALUATION_ONLY: "Тек бағалау үшін",
  ELIGIBLE_AFTER_INGESTION: "Жарияланымнан кейін өнімде рұқсат етілген",
  NOT_FOR_PRODUCT: "Өнім үшін емес",
  REFERENCE_ONLY: "Анықтамалық",
};
const ABSTENTION_CODES_KK: Record<string, string> = {
  RECEIVER_BLOCKED:
    "Өңірдегі сол бейіндегі бірде-бір қабылдаушы-қатарда қозғалған күндердің барлығында тарихи бағдар бойынша модельдік қор жоқ",
  RECEIVER_OUTSIDE_SAME_REGION_POLICY:
    "Кандидат-қатар донор өңірінен тыс («сол өңір» саясаты)",
  TRANSFER_BUDGET_INSUFFICIENT: "Ауыстыру бюджеті ең аз қажетті үлестен аз",
  NO_ELIGIBLE_RECEIVER: "Лайықты қабылдаушы-қатарлар жоқ",
  DONOR_NOT_CENTRAL_DRIVEN:
    "Донордың асып кетуі орталық болжаммен анықталмайды",
};
const CAPABILITY_NAMES_KK: Record<string, string> = {
  flow_point_forecast: "Ағынның нүктелік болжамы",
  flow_quantile_forecast: "Ағынның квантильдік болжамы",
  flow_temporal_calibration: "Аралықтарды уақыттық калибрлеу",
  flow_hierarchical_coherence: "Иерархиялық келісімділік",
  preventive_flow_pressure: "Ағынның алдын ала қысымы",
  observed_unusual_flow: "Байқалған әдеттен тыс ағын",
  signal_prioritization: "Сигналдарды басымдау",
  forecast_stress_test: "Болжамның стресс-тесті",
  decision_alternatives: "Талдауға арналған математикалық баламалар",
  patient_journey_hospitalization: "Пациент жолы · госпитализация",
  patient_journey_refusal: "Пациент жолы · бас тарту тәуекелі",
  patient_journey_competing_risk_baseline:
    "Пациент жолы · бәсекелес тәуекелдердің базалық моделі",
  patient_journey_competing_risk_ml_challenger:
    "Пациент жолы · ML-үміткер (қабылданбаған)",
};

export const statusLabel = (value: string | null | undefined): string =>
  value == null
    ? t.common.noData
    : (pick(STATUS_LABELS_RU, STATUS_LABELS_KK)[value] ?? value);

export const reasonLabel = (code: string): string =>
  pick(REASON_CODES_RU, REASON_CODES_KK)[code] ?? code;

export const abstentionLabel = (code: string): string =>
  pick(ABSTENTION_CODES_RU, ABSTENTION_CODES_KK)[code] ?? code;

/** Machine tokens that must not appear in primary copy: SHOUTING_SNAKE or lower_snake with two+ parts. */
export const isTechnical = (value: string): boolean =>
  /\b[A-Z][A-Z0-9]+(?:_[A-Z0-9]+)+\b/.test(value) ||
  /\b[a-z0-9]+(?:_[a-z0-9]+){2,}\b/.test(value);

const dateOf = (iso: string) => fmtDate(iso);

const EXACT_KK: Record<string, string> = {
  "Calibrated lower forecast bound exceeds the hospital/profile historical high-flow threshold.":
    REASON_CODES_KK.CALIBRATED_LOWER_EXCEEDS_HISTORICAL_FLOW_THRESHOLD,
  "Central forecast exceeds the hospital/profile historical high-flow threshold.":
    REASON_CODES_KK.CENTRAL_FORECAST_EXCEEDS_HISTORICAL_FLOW_THRESHOLD,
  "Calibrated upper forecast bound exceeds the hospital/profile historical high-flow threshold.":
    REASON_CODES_KK.CALIBRATED_UPPER_EXCEEDS_HISTORICAL_FLOW_THRESHOLD,
  "Derived scenario sensitivity lower bound exceeds the hospital/profile historical high-flow threshold.":
    "Туынды сезімталдық ауқымының төменгі шекарасының өзі тарихи бағдардан жоғары",
  "Derived scenario sensitivity upper bound exceeds the hospital/profile historical high-flow threshold.":
    "Туынды ауқымның жоғарғы шекарасы тарихи бағдардан жоғары — бақылау",
  "Forecast uses direct model support.":
    "Болжам модельдің тікелей қолдауына сүйенеді",
  "Calibrated uncertainty is available.": "Калибрленген белгісіздік қолжетімді",
  "Published central forecast value.": "Жарияланған орталық болжам",
  "Published historical-flow reference value.":
    "Ағынның жарияланған тарихи бағдары",
  "Published materiality classification.": "Жарияланған маңыздылық",
  "Published weekly residual differs from its historical robust reference; no causal claim.":
    "Апталық қалдық тұрақты тарихи бағдардан ерекшеленеді; себептілік мәлімделмейді",
  "The published signal is directly supported for this series.":
    "Сигнал осы қатардың деректерімен тікелей қолдалады",
  "The published signal is unsupported and must not be treated as supported evidence.":
    "Сигнал деректермен қолдалмайды және расталған дәлел деп саналмайды",
  "Human review required; no autonomous routing or causal effect claim.":
    "Маманның тексеруі қажет; автономды әрекеттер мен себептік мәлімдемелер жоқ",
  "Retrospective final-test origin 2025-03-17; not a live forecast or current hospital condition.":
    "Ретроспективті есеп күні 17.03.2025; бұл стационардың ағымдағы жай-күйі емес",
  "historical_flow_proxy_v1 compares historical flow; physical capacity is not measured or checked.":
    "Бағдар тарихи ағынды салыстырады; физикалық сыйымдылық өлшенбейді",
  "only 90 days of registration history; no annual-seasonality claim":
    "Тіркеулер тарихы — 90 күн; жылдық маусымдылық бағаланбайды",
  "cohort_hospitalizations are Q1-referral-cohort events, not total admissions":
    "Когорта госпитализациялары — I тоқсандағы жолдамалар когортасының оқиғалары, барлық түсімдер емес",
  "no physical bed capacity, occupied-bed, or free-bed data are available or inferred":
    "Төсек-орындар мен олардың толымдылығы туралы деректер жоқ және шығарылмайды",
  "retrospective events are high-flow proxy exceedances, not operational incidents":
    "Ретроспективті оқиғалар — тарихи бағдардан асып кетулер, оқыс оқиғалар емес",
  "Freshness UNKNOWN: no approved refresh SLA; publication time is not evidence freshness.":
    "Өзектілік анықталмаған: бекітілген жаңарту регламенті жоқ",
  "Central forecasts only; no probabilistic reconciliation claim":
    "Тек орталық болжамдар; ықтималдық келісімділік мәлімделмейді",
  "Does not promise perfect 80 percent coverage; national proxy excluded from calibration claims.":
    "Дәл 80% қамту уәде етілмейді; ұлттық прокси калибрлеуден шығарылған",
  "This explanation supports human review only and does not prescribe or automate action.":
    "Түсіндірме маманның тексеруін қолдайды және әрекеттерді бұйырмайды",
  "What current local operational context is relevant to a human review?":
    "Тексеру үшін қандай ағымдағы жергілікті контекст маңызды?",
  "How do the published uncertainty and support limitations affect interpretation of this signal?":
    "Жарияланған белгісіздік пен қолдау шектеулері сигналды оқуға қалай әсер етеді?",
  "Is more recent observed information available for comparison?":
    "Салыстыру үшін жаңарақ бақылаулар бар ма?",
};

/** English published sentences → current language. Returns null when the sentence is not part of the approved map. */
export function translateSentence(text: string): string | null {
  const kk = getLang() === "kk";
  const exact: Record<string, string> = {
    "Calibrated lower forecast bound exceeds the hospital/profile historical high-flow threshold.":
      REASON_CODES_RU.CALIBRATED_LOWER_EXCEEDS_HISTORICAL_FLOW_THRESHOLD,
    "Central forecast exceeds the hospital/profile historical high-flow threshold.":
      REASON_CODES_RU.CENTRAL_FORECAST_EXCEEDS_HISTORICAL_FLOW_THRESHOLD,
    "Calibrated upper forecast bound exceeds the hospital/profile historical high-flow threshold.":
      REASON_CODES_RU.CALIBRATED_UPPER_EXCEEDS_HISTORICAL_FLOW_THRESHOLD,
    "Derived scenario sensitivity lower bound exceeds the hospital/profile historical high-flow threshold.":
      "Даже нижняя граница производного диапазона чувствительности выше исторического ориентира",
    "Derived scenario sensitivity upper bound exceeds the hospital/profile historical high-flow threshold.":
      "Верхняя граница производного диапазона выше исторического ориентира — наблюдение",
    "Forecast uses direct model support.":
      "Прогноз опирается на прямую поддержку модели",
    "Calibrated uncertainty is available.":
      "Доступна калиброванная неопределённость",
    "Published central forecast value.": "Опубликованный центральный прогноз",
    "Published historical-flow reference value.":
      "Опубликованный исторический ориентир потока",
    "Published materiality classification.": "Опубликованная материальность",
    "Published weekly residual differs from its historical robust reference; no causal claim.":
      "Недельный остаток отличается от устойчивого исторического ориентира; причинность не утверждается",
    "The published signal is directly supported for this series.":
      "Сигнал напрямую поддержан данными этого ряда",
    "The published signal is unsupported and must not be treated as supported evidence.":
      "Сигнал не поддержан данными и не может считаться подтверждённым свидетельством",
    "Human review required; no autonomous routing or causal effect claim.":
      "Требуется проверка специалистом; автономных действий и причинных утверждений нет",
    "Retrospective final-test origin 2025-03-17; not a live forecast or current hospital condition.":
      "Ретроспективная дата отсчёта 17.03.2025; это не текущее состояние стационара",
    "historical_flow_proxy_v1 compares historical flow; physical capacity is not measured or checked.":
      "Ориентир сравнивает исторический поток; физическая вместимость не измеряется",
    "only 90 days of registration history; no annual-seasonality claim":
      "История регистраций — 90 дней; годовая сезонность не оценивается",
    "cohort_hospitalizations are Q1-referral-cohort events, not total admissions":
      "Госпитализации когорты — события когорты направлений I квартала, не все поступления",
    "no physical bed capacity, occupied-bed, or free-bed data are available or inferred":
      "Данных о койках и их занятости нет, и они не выводятся",
    "retrospective events are high-flow proxy exceedances, not operational incidents":
      "Ретроспективные события — превышения исторического ориентира, не инциденты",
    "Freshness UNKNOWN: no approved refresh SLA; publication time is not evidence freshness.":
      "Актуальность не установлена: утверждённого регламента обновления нет",
    "Central forecasts only; no probabilistic reconciliation claim":
      "Только центральные прогнозы; вероятностная согласованность не утверждается",
    "Does not promise perfect 80 percent coverage; national proxy excluded from calibration claims.":
      "Точное покрытие 80% не обещается; национальный прокси исключён из калибровки",
    "This explanation supports human review only and does not prescribe or automate action.":
      "Объяснение поддерживает проверку специалистом и не предписывает действий",
    "What current local operational context is relevant to a human review?":
      "Какой текущий местный контекст важен для проверки?",
    "How do the published uncertainty and support limitations affect interpretation of this signal?":
      "Как опубликованная неопределённость и ограничения поддержки влияют на прочтение сигнала?",
    "Is more recent observed information available for comparison?":
      "Есть ли более свежие наблюдения для сравнения?",
  };
  if (kk && text in EXACT_KK) return EXACT_KK[text];
  if (text in exact) return exact[text];
  let m =
    /^The published first crossing date is (\d{4}-\d{2}-\d{2}) with a (\d+)-day lead time\.$/.exec(
      text,
    );
  if (m)
    return kk
      ? `Алғашқы асып кету ${dateOf(m[1])} күтіледі, озу ${m[2]} күн.`
      : `Первое превышение ожидается ${dateOf(m[1])}, опережение ${m[2]} дн.`;
  m =
    /^Displayed severity evidence is horizon (\d+) on (\d{4}-\d{2}-\d{2})\.$/.exec(
      text,
    );
  if (m)
    return kk
      ? `Деңгей ${m[1]} көкжиегі бойынша анықталды (${dateOf(m[2])})`
      : `Уровень определён по горизонту ${m[1]} (${dateOf(m[2])})`;
  m = /^The calibrated uncertainty interval is ([\d.]+) to ([\d.]+)\.$/.exec(
    text,
  );
  if (m)
    return kk
      ? `Калибрленген аралық: ${fmtNumber(Number(m[1]), 1)}-ден ${fmtNumber(Number(m[2]), 1)}-ге дейін`
      : `Калиброванный интервал: от ${fmtNumber(Number(m[1]), 1)} до ${fmtNumber(Number(m[2]), 1)}`;
  m =
    /^The published signal is fallback-limited \(([A-Z_]+)\); interpret it with that limitation\.$/.exec(
      text,
    );
  if (m)
    return kk
      ? `Сигнал резервтік болжамға құрылған (${statusLabel(m[1])})`
      : `Сигнал построен на резервном прогнозе (${statusLabel(m[1])})`;
  m =
    /^A (HIGH|ELEVATED|WATCH|NORMAL) preventive-flow signal was published for (registrations|cohort_hospitalizations) using historical_flow_proxy_v1\. It is an attention flag for human review, not a physical-capacity finding\.$/.exec(
      text,
    );
  if (m)
    return kk
      ? `«${t.tower.status[m[2]] ?? m[2]}» қатары бойынша ағынның тарихи бағдарына қатысты «${severityLabel(m[1])}» деңгейлі алдын ала сигнал жарияланды. Бұл маман тексеруіне арналған назар белгісі, физикалық сыйымдылық туралы қорытынды емес.`
      : `Опубликован превентивный сигнал уровня «${severityLabel(m[1])}» по ряду «${t.tower.status[m[2]] ?? m[2]}» относительно исторического ориентира потока. Это флаг внимания для проверки специалистом, не вывод о физической вместимости.`;
  return null;
}

/** Translate a published list, keeping only sentences with an approved Russian form; the rest are technical. */
export function translateList(items: string[]): {
  human: string[];
  technical: string[];
} {
  const human: string[] = [];
  const technical: string[] = [];
  for (const item of items) {
    const translated = translateSentence(item);
    if (translated) human.push(translated);
    else technical.push(item);
  }
  return { human: [...new Set(human)], technical };
}

export const number1 = (value: number | null | undefined) =>
  value == null ? t.common.noData : fmtNumber(value, 1);

export const percent0 = (share: number | null | undefined) =>
  share == null ? t.common.noData : `${fmtNumber(share * 100, 0)}%`;

export const percent1 = (share: number | null | undefined) =>
  share == null ? t.common.noData : `${fmtNumber(share * 100, 1)}%`;

const CAPABILITY_NAMES_RU: Record<string, string> = {
  flow_point_forecast: "Точечный прогноз потока",
  flow_quantile_forecast: "Квантильный прогноз потока",
  flow_temporal_calibration: "Временная калибровка интервалов",
  flow_hierarchical_coherence: "Иерархическая согласованность",
  preventive_flow_pressure: "Превентивное давление потока",
  observed_unusual_flow: "Наблюдаемый необычный поток",
  signal_prioritization: "Приоритизация сигналов",
  forecast_stress_test: "Стресс-тест прогноза",
  decision_alternatives: "Математические альтернативы для разбора",
  patient_journey_hospitalization: "Путь пациента · госпитализация",
  patient_journey_refusal: "Путь пациента · риск отказа",
  patient_journey_competing_risk_baseline:
    "Путь пациента · базовая модель конкурирующих рисков",
  patient_journey_competing_risk_ml_challenger:
    "Путь пациента · ML-претендент (отклонён)",
};
export const capabilityName = (id: string): string =>
  pick(CAPABILITY_NAMES_RU, CAPABILITY_NAMES_KK)[id] ?? id;
