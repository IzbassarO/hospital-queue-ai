/**
 * Hospital mode copy (Russian). Every number on that screen comes from a published API response; these are frames
 * only. The screen never says the model knew an outcome: everything measured after the origin is labelled
 * "ретроспектива" in the interface itself, not only in a footnote.
 */
const plural = (n: number, one: string, few: string, many: string) => {
  const mod10 = n % 10;
  const mod100 = n % 100;
  if (mod10 === 1 && mod100 !== 11) return one;
  if (mod10 >= 2 && mod10 <= 4 && (mod100 < 12 || mod100 > 14)) return few;
  return many;
};

export const hospital = {
  nav: "Стационар",
  title: "Режим стационара",
  lead: (origin: string) =>
    `Один стационар на дату отсчёта ${origin}: что модель обещала на 14 дней вперёд, кто стоял в очереди в этот день и что произошло потом.`,
  loading: "Загружаем стационар…",
  pick: {
    title: "Выберите стационар",
    search: "Поиск по названию",
    searchPlaceholder: "Начните вводить название",
    region: "Регион",
    allRegions: "Вся страна",
    showSmall: "Показывать стационары с малыми очередями",
    smallTag: "мало данных",
    smallHint:
      "Меньше 20 направлений в очереди: по такому стационару нельзя делать выводы, но открыть его можно.",
    found: (n: number) =>
      `${n} ${plural(n, "стационар", "стационара", "стационаров")}`,
    empty: "Ничего не нашлось",
    emptyHint: "Измените запрос или выберите другой регион.",
    waiting: (n: number) => `${n} в очереди`,
    mapHint: "Стационар можно выбрать и точкой на карте центра управления.",
    change: "Другой стационар",
  },
  header: {
    origin: (date: string) => `Дата отсчёта ${date}`,
    waiting: "в очереди на дату отсчёта",
    profiles: "профилей коек",
    median: "медиана ожидания",
    longest: "дольше всех ждёт",
    days: "дн.",
    support: {
      SUFFICIENT: "очередь большая",
      LIMITED: "очередь небольшая",
      SPARSE: "мало данных",
    },
    sparseWarning:
      "В очереди меньше 20 направлений. Цифры ниже настоящие, но на такой выборке ни один вывод не устойчив.",
  },
  profileSelect: {
    label: "Профиль койки",
    hint: "Поток публикуется по паре «стационар × профиль»: у каждого профиля свой прогноз и свой порог.",
    waiting: (n: number) => `${n} в очереди`,
  },
  forecast: {
    title: "Что будет",
    subtitle: (origin: string) =>
      `Опубликованный прогноз регистраций на 14 дней вперёд от ${origin}`,
    empty: "Для этого профиля прогноз не публиковался.",
    emptyHint: "Выберите другой профиль койки.",
    central: "медиана прогноза (p50)",
    band: "калиброванный интервал 80%",
    threshold: "исторический порог",
    crossing: "первое превышение",
    noThreshold: "порог не публиковался",
    noCrossing: "порог не превышается за 14 дней",
    crossingOn: (date: string, lead: number) =>
      `${date} · через ${lead} ${plural(lead, "день", "дня", "дней")} после отсчёта`,
    severity: "уровень сигнала",
    severityNone: "сигнала нет",
    coverage: (pct: string) => `номинальное покрытие ${pct}`,
    support: "обеспеченность",
    facts: {
      threshold: "Порог",
      crossing: "Первое превышение",
      severity: "Сигнал",
      peak: "Максимум прогноза",
    },
  },
  waiting: {
    title: "Кто ждёт",
    subtitle: (origin: string) =>
      `Реальная очередь направлений на конец ${origin}, без единой модельной величины`,
    totals: {
      waiting: "направлений ждут",
      profiles: "профилей",
      median: "медиана ожидания, дн.",
      longest: "максимум ожидания, дн.",
    },
    byProfile: "По профилям коек",
    byProfileHint: "Доля профиля в очереди стационара.",
    histogram: "Сколько уже ждут",
    histogramHint:
      "Направления по числу дней, проведённых в очереди к дате отсчёта.",
    bucket: (from: number, to: number | null) =>
      to === null ? `${from}+ дн.` : `${from}–${to - 1} дн.`,
    bucketCount: (n: number) =>
      `${n} ${plural(n, "направление", "направления", "направлений")}`,
    table: {
      title: "Очередь направлений",
      code: "Направление",
      profile: "Профиль",
      registered: "Зарегистрировано",
      waited: "Ждёт, дн.",
      outcome: "Что было дальше",
      sortLongest: "Дольше всех",
      sortShortest: "Меньше всех",
      duplicate: "код повторяется в источнике",
      page: (from: number, to: number, total: number) =>
        `${from}–${to} из ${total}`,
      prev: "Назад",
      next: "Вперёд",
      allProfiles: "Все профили",
      noPredictions:
        "Оценок модели здесь нет: эта публикация — измеренные данные. Колонки для них появятся отдельным шагом.",
    },
    outcome: {
      ADMITTED: "госпитализирован",
      REFUSED: "отказ",
      STILL_WAITING_AT_CUTOFF: "так и ждёт",
      on: (date: string, days: number) =>
        `${date} · +${days} ${plural(days, "день", "дня", "дней")}`,
    },
  },
  replay: {
    title: "Что было на самом деле",
    subtitle: "День за днём с 18.03 по 31.03: прогноз против факта",
    lead: "Каждый день сравнивается с интервалом, опубликованным на дату отсчёта. Ничего не пересчитывается задним числом.",
    notStarted: "День не выбран",
    range: (from: string, to: string) => `${from} — ${to}`,
    day: (n: number) => `День ${n}`,
    dayOf: (n: number, total: number) => `${n} из ${total}`,
    start: "Смотреть",
    pause: "Пауза",
    step: "Шаг",
    reset: "Сначала",
    inBand: "в интервале",
    outBand: "вне интервала",
    above: "выше интервала",
    below: "ниже интервала",
    tally: (hit: number, total: number) =>
      `${hit} из ${total} ${plural(hit, "дня", "дней", "дней")} в интервале`,
    tallyPending: "нажмите «Смотреть» или «Шаг»",
    actual: "факт",
    expected: "интервал прогноза",
    columns: {
      date: "Дата",
      forecast: "Интервал",
      actual: "Факт",
      verdict: "Итог",
    },
    empty: "Для этого профиля нет ни прогноза, ни факта за эти дни.",
  },
  hindsight: {
    tag: "ретроспектива",
    title: "Это ретроспектива",
    note: (origin: string) =>
      `Исходы стали известны после ${origin}. На дату отсчёта модель их не знала и не могла использовать.`,
    short: (origin: string) => `известно после ${origin}`,
  },
  errors: {
    unknown: "Стационар не найден",
    unknownHint:
      "В опубликованной очереди на дату отсчёта у этого стационара нет направлений.",
    back: "К выбору стационара",
  },
};
