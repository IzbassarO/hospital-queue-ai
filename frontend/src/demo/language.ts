/**
 * Human-language layer for the guided journey. Maps published machine vocabulary (reason codes, statuses,
 * English evidence sentences) to approved Russian product language. Unknown tokens are never invented:
 * they stay in the technical provenance layer and are reported by `isTechnical`.
 */
import { t } from "../i18n";
import { fmtDate, fmtNumber } from "../lib/format";

export type Severity = "HIGH" | "ELEVATED" | "WATCH" | "NORMAL" | "UNSUPPORTED";

export const severityLabel = (value: string): string =>
  t.tower.status[value] ?? value;

/** Adjective form used in the DETECT headline ("Потенциальное … давление потока"). */
export const severityAdjective: Record<string, string> = {
  HIGH: "высокое",
  ELEVATED: "повышенное",
  WATCH: "умеренное",
  NORMAL: "нормальное",
  UNSUPPORTED: "неподтверждённое",
};

export const REASON_CODES: Record<string, string> = {
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

export const STATUS_LABELS: Record<string, string> = {
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

export const ABSTENTION_CODES: Record<string, string> = {
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

export const statusLabel = (value: string | null | undefined): string =>
  value == null ? t.common.noData : (STATUS_LABELS[value] ?? value);

export const reasonLabel = (code: string): string => REASON_CODES[code] ?? code;

export const abstentionLabel = (code: string): string =>
  ABSTENTION_CODES[code] ?? code;

/** Machine tokens that must not appear in primary copy: SHOUTING_SNAKE or lower_snake with two+ parts. */
export const isTechnical = (value: string): boolean =>
  /\b[A-Z][A-Z0-9]+(?:_[A-Z0-9]+)+\b/.test(value) ||
  /\b[a-z0-9]+(?:_[a-z0-9]+){2,}\b/.test(value);

const dateOf = (iso: string) => fmtDate(iso);

/** English published sentences → Russian. Returns null when the sentence is not part of the approved map. */
export function translateSentence(text: string): string | null {
  const exact: Record<string, string> = {
    "Calibrated lower forecast bound exceeds the hospital/profile historical high-flow threshold.":
      REASON_CODES.CALIBRATED_LOWER_EXCEEDS_HISTORICAL_FLOW_THRESHOLD,
    "Central forecast exceeds the hospital/profile historical high-flow threshold.":
      REASON_CODES.CENTRAL_FORECAST_EXCEEDS_HISTORICAL_FLOW_THRESHOLD,
    "Calibrated upper forecast bound exceeds the hospital/profile historical high-flow threshold.":
      REASON_CODES.CALIBRATED_UPPER_EXCEEDS_HISTORICAL_FLOW_THRESHOLD,
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
  if (text in exact) return exact[text];
  let m =
    /^The published first crossing date is (\d{4}-\d{2}-\d{2}) with a (\d+)-day lead time\.$/.exec(
      text,
    );
  if (m)
    return `Первое превышение ожидается ${dateOf(m[1])}, опережение ${m[2]} дн.`;
  m =
    /^Displayed severity evidence is horizon (\d+) on (\d{4}-\d{2}-\d{2})\.$/.exec(
      text,
    );
  if (m) return `Уровень определён по горизонту ${m[1]} (${dateOf(m[2])})`;
  m = /^The calibrated uncertainty interval is ([\d.]+) to ([\d.]+)\.$/.exec(
    text,
  );
  if (m)
    return `Калиброванный интервал: от ${fmtNumber(Number(m[1]), 1)} до ${fmtNumber(Number(m[2]), 1)}`;
  m =
    /^The published signal is fallback-limited \(([A-Z_]+)\); interpret it with that limitation\.$/.exec(
      text,
    );
  if (m) return `Сигнал построен на резервном прогнозе (${statusLabel(m[1])})`;
  m =
    /^A (HIGH|ELEVATED|WATCH|NORMAL) preventive-flow signal was published for (registrations|cohort_hospitalizations) using historical_flow_proxy_v1\. It is an attention flag for human review, not a physical-capacity finding\.$/.exec(
      text,
    );
  if (m)
    return `Опубликован превентивный сигнал уровня «${severityLabel(m[1])}» по ряду «${t.tower.status[m[2]] ?? m[2]}» относительно исторического ориентира потока. Это флаг внимания для проверки специалистом, не вывод о физической вместимости.`;
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

export const CAPABILITY_NAMES: Record<string, string> = {
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
  CAPABILITY_NAMES[id] ?? id;
