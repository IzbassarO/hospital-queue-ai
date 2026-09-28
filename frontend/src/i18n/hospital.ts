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
      withEstimates: (model: string, origin: string) =>
        `Измеренная очередь на ${origin} и рядом — оценки модели ${model} на ту же дату. Оценки считаны по истории до ${origin}: ни один исход после неё в них не входит.`,
    },
    outcome: {
      ADMITTED: "госпитализирован",
      REFUSED: "отказ",
      STILL_WAITING_AT_CUTOFF: "так и ждёт",
      on: (date: string, days: number) =>
        `${date} · +${days} ${plural(days, "день", "дня", "дней")}`,
    },
  },
  estimates: {
    columns: {
      admitted: "Шанс попасть",
      refused: "Риск отказа",
      window: "Окно госпитализации",
      tier: "Основание оценки",
    },
    byDay: (days: number) => `к ${days} дн.`,
    refusedBy: (days: number) => `отказ к ${days} дн.`,
    none: "нет оценки",
    noneHint: "Это направление не входит в опубликованный набор оценок.",
    degenerate: {
      short: "нет сопоставимых исходов",
      count: (n: string, total: string) =>
        `${n} из ${total} направлений с вырожденной оценкой на 30 дней.`,
    },
    stillWaiting: (pct: string) => `ещё в очереди ${pct}`,
    window: {
      range: (from: string, to: string) => `${from}–${to} дн.`,
      coverage: (pct: string) => `интервал ${pct}`,
      abstainShort: "окно не назначено",
      abstain: {
        NO_ADMISSION_IN_COMPARABLE_HISTORY:
          "В сопоставимой истории нет ни одной госпитализации в пределах горизонта модели, поэтому окно не назначается.",
      },
    },
    tier: {
      hospital_profile: "по этому стационару и профилю",
      region_profile: "по региону",
      profile: "по профилю",
      national: "по всей стране",
    },
    tierRows: (n: number) =>
      `${n} ${plural(n, "сопоставимое наблюдение", "сопоставимых наблюдения", "сопоставимых наблюдений")}`,
    tierHint:
      "Откуда взята историческая кривая. Это происхождение оценки, а не её точность.",
    attention: {
      sort: "Высокий риск отказа",
      filter: "Только высокий риск отказа",
      tag: "проверить",
      title: "Высокий риск отказа — административное действие",
      rule: (pct: string) =>
        `Порог опубликован вместе с оценками: верхний дециль по всей когорте, P(отказ ≤ 30 дн.) ≥ ${pct}.`,
      use: "Что делать: проверить, действительно ли направление, и связаться с пациентом. Это не медицинская оценка, не приоритет госпитализации и не основание отказать.",
      count: (n: string, total: string) => `${n} из ${total} выше порога`,
      needsPublication:
        "Для этого порядка нужна опубликованная модель оценок на ту же дату отсчёта.",
    },
  },
  why: {
    title: "Почему эта модель",
    subtitle: (metric: string) =>
      `Турнир на дату отсчёта. Метрика и правило зафиксированы до запуска: ${metric}.`,
    ruleLabel: "Правило выбора",
    quoted: "дословно из публикации",
    fallbackNote:
      "Ни один кандидат не прошёл правило, поэтому работает базовая модель. Это результат правила, а не выбор постфактум.",
    columns: {
      model: "Модель",
      role: "Роль",
      overall: "Brier, всего",
      horizon: (days: number) => `${days} дн.`,
      delta: "Δ к базовой",
      worst: "Худшая группа",
      verdict: "Итог",
    },
    roles: { baseline: "базовая", candidate: "кандидат" },
    verdict: {
      accepted: "принята",
      rejected: "отклонена",
      baseline: "точка отсчёта",
      serving: "работает",
    },
    models: {
      aalen_johansen: "Aalen—Johansen, иерархическая",
      xgboost_aft: "XGBoost AFT",
      discrete_competing_risk: "LightGBM, дискретные конкурирующие риски",
    },
    hint: "Brier — средняя квадратичная ошибка вероятности: меньше — лучше. Δ считается к базовой модели, отрицательное значение означает улучшение.",
    tiers: "На чём стоят оценки",
    abstained: (n: string, total: string) =>
      `${n} из ${total} направлений без окна госпитализации: модель воздержалась`,
    run: (id: string) => `прогон ${id}`,
    identity: "идентичность публикации",
  },
  calibration: {
    title: "Насколько сбылись оценки",
    lead: (n: string) =>
      `Все ${n} направлений публикации, разбитые на 10 групп по обещанной вероятности. Точка на диагонали означает: сколько модель обещала, столько и произошло.`,
    horizon: "госпитализация к 14 дн.",
    axisPredicted: "модель обещала",
    axisObserved: "произошло на деле",
    diagonal: "идеальная калибровка",
    point: (predicted: string, observed: string, n: number) =>
      `обещано ${predicted}, госпитализировано ${observed}, направлений ${n}`,
    summary: (predicted: string, observed: string) =>
      `В среднем модель обещала ${predicted}, госпитализировали ${observed}.`,
    verdict: {
      over: "Модель систематически завышает шанс попасть — на экране это верхняя граница, а не обещание.",
      under: "Модель систематически занижает шанс попасть.",
      close: "Систематического смещения не видно.",
    },
    columns: {
      band: "Обещано",
      n: "Направлений",
      observed: "Госпитализировано",
    },
    empty: "Калибровка не публиковалась.",
  },
  tabs: {
    label: "Разделы очереди",
    queue: "Кто ждёт",
    worklist: "На сверку",
  },
  worklist: {
    title: "Список на сверку",
    subtitle: (origin: string) =>
      `Порядок, в котором бюро госпитализации может сверять направления с пациентом и документами, на дату отсчёта ${origin}`,
    decision:
      "Решение остаётся за специалистом: список ничего не снимает с очереди и ничего не меняет в ней.",
    notAQueue: (formal: string) =>
      `Очередь стационара — ${formal} направлений, и она не меняется: список лишь задаёт порядок сверки для всех них. Ни одно направление не вычитается из очереди.`,
    totals: {
      formal: "в очереди, все в порядке сверки",
      warning: "с малой сопоставимой историей",
      warningShare: "доля с малой историей",
    },
    rule: "Как упорядочен список",
    ruleHint:
      "Порядок зафиксирован до проверки на исходах. Он подсказывает, с чего начать сверку, и ничего не решает.",
    table: {
      title: "Что сверить",
      rank: "№ по стране",
      rankHint:
        "Место в общем опубликованном порядке по стране, поэтому нумерация у стационара идёт с пропусками.",
      code: "Направление",
      profile: "Профиль",
      waited: "Ждёт, дн.",
      priority: "Приоритет",
      priorityHint:
        "Оценка приоритета сверки от 0 до 1: чем выше, тем раньше сверять. Это не вероятность и не вердикт.",
      support: "Опора оценки",
      chance: "Шанс попасть",
    },
    history: {
      tag: "мало сопоставимой истории",
      hint: "Низкая вероятность здесь означает нехватку наблюдений, а не уверенность модели.",
      filter: "Только с малой историей",
      all: "Все строки",
      reasons: {
        insufficient_comparable_history: "мало сопоставимых направлений",
        insufficient_and_degenerate_comparable_history:
          "мало сопоставимых направлений и ни одной госпитализации среди них",
        degenerate_conditional_distribution:
          "в сопоставимой истории после такого срока не было госпитализаций",
      },
    },
    order: {
      rank: "По приоритету",
      longest: "Дольше всех",
    },
    yieldTitle: "Что дала бы сверка в этом порядке",
    yieldLead: (base: string, checked: string, share: string, lift: string) =>
      `По всей очереди неактуальными оказались ${base} направлений. Лучше всего порядок сработал на первых ${checked}: ${share}, в ${lift} раза больше базовой доли.`,
    yieldColumns: {
      checked: "Первые N",
      found: "Из них неактуальны",
      share: "Доля",
      lift: "К базе",
    },
    yieldBase: "Вся очередь",
    yieldWeak:
      "Порядок помогает скромно и неровно: в части верхушки списка доля не выше, чем по всей очереди. Это порядок работы для бюро, а не классификатор неактуальных направлений.",
    regionTitle: "По регионам",
    regionLead:
      "Очередь каждого региона и сколько в ней направлений с малой сопоставимой историей.",
    regionColumns: {
      region: "Регион",
      warning: "Мало истории",
      formal: "В очереди",
      share: "Доля",
    },
    thisRegion: "этот регион",
    showAllRegions: "Показать все регионы",
    hideRegions: "Свернуть",
    source: (id: string, source: string) =>
      `публикация: ${id} · источник: ${source}`,
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
