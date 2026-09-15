/**
 * Every user-visible string of the UI. Russian only for now; another language is a file with the same shape
 * (`Messages`) selected in ./index.ts. Domain texts are NOT duplicated here: model cards, factor short labels,
 * the data-source description and every number of the load_index formula come from the API (GET /models,
 * explanations, GET /config); the templates below only put those values into sentences.
 */
import type { DecisionAction, Status } from "../api/types";

const plural = (n: number, one: string, few: string, many: string) => {
  const mod10 = n % 10;
  const mod100 = n % 100;
  if (mod10 === 1 && mod100 !== 11) return one;
  if (mod10 >= 2 && mod10 <= 4 && (mod100 < 12 || mod100 > 14)) return few;
  return many;
};

export const ru = {
  app: {
    title: "Очереди на плановую госпитализацию",
    subtitle: "Мониторинг нагрузки стационаров",
    skipToContent: "Перейти к содержимому",
    role: (role: string) => `роль: ${role}`,
    roleTitle: (label: string) => `API-ключ: ${label}`,
    noKey: "нет доступа к API",
    footer:
      "Прототип на открытых данных Министерства здравоохранения РК. Показатели рассчитаны на дату среза, это не данные в реальном времени.",
  },
  nav: {
    overview: "Обзор",
    alerts: "Сигналы",
    models: "О моделях",
    main: "Основная навигация",
    breadcrumbs: "Навигационная цепочка",
  },
  common: {
    noData: "—",
    loading: "Загрузка…",
    retry: "Повторить",
    back: "Назад",
    open: "Открыть",
    total: (n: number) => `Всего: ${n.toLocaleString("ru-RU")}`,
    page: (from: number, to: number, total: number) =>
      `${from.toLocaleString("ru-RU")}–${to.toLocaleString("ru-RU")} из ${total.toLocaleString("ru-RU")}`,
    prevPage: "Предыдущая страница",
    nextPage: "Следующая страница",
    pagination: "Постраничная навигация",
    sortAsc: "по возрастанию",
    sortDesc: "по убыванию",
    sortBy: (column: string) => `Сортировать по столбцу «${column}»`,
    asOf: (date: string) => `Данные на ${date}`,
    source: (
      publisher: string,
      description: string,
      period: string,
      date: string,
    ) =>
      `Источник: ${publisher}. ${description} Период: ${period}. Срез на ${date}; окно показателей — последние 28 дней.`,
    hospitals: (n: number) =>
      `${n.toLocaleString("ru-RU")} ${plural(n, "стационар", "стационара", "стационаров")}`,
    referrals: (n: number) =>
      `${n.toLocaleString("ru-RU")} ${plural(n, "направление", "направления", "направлений")}`,
  },
  units: {
    days: "дн.",
    pp: "п.п.",
    ppPerWeek: "п.п./нед.",
    percentPerWeek: "%/нед.",
    people: "чел.",
  },
  status: {
    high: "Высокая",
    elevated: "Повышенная",
    normal: "Норма",
    insufficient_data: "Недостаточно данных",
  } satisfies Record<Status, string>,
  statusLong: {
    high: "Высокая нагрузка",
    elevated: "Повышенная нагрузка",
    normal: "Нормальная нагрузка",
    insufficient_data: "Недостаточно данных для индекса нагрузки",
  } satisfies Record<Status, string>,
  errors: {
    title: "Не удалось загрузить данные",
    network: (url: string) => `API недоступен. Адрес запроса: ${url}`,
    networkHint:
      "Проверьте, что backend запущен (make up) и отвечает на /api/v1/health.",
    http: (status: number, url: string) =>
      `Ответ API ${status} на запрос ${url}`,
    notBuilt: "Витрины данных ещё не построены: выполните make marts.",
    notFound: "Объект не найден",
    auth: "API требует ключ доступа: ключ не задан, неверен или отозван (VITE_API_KEY / DEMO_API_KEY).",
    forbidden: "Недостаточно прав для этого действия.",
    shape: (url: string) =>
      `Ответ API не соответствует ожидаемому формату: ${url}`,
    pageNotFound: "Страница не найдена",
    toOverview: "Перейти к обзору",
  },
  metrics: {
    queueNow: "Очередь сейчас",
    queueNowHint:
      "Направления, ожидающие госпитализации на конец дня среза (нижняя оценка)",
    medianWait: "Медиана ожидания",
    medianWaitHint: "Медиана дней от направления до госпитализации за 28 дней",
    refusalRate: "Доля отказов",
    refusalRateHint: "Отказы / (госпитализации + отказы) за 28 дней",
    hospitalsHighLoad: "Стационары с высокой нагрузкой",
    hospitalsHighLoadHint:
      "Стационары, у которых хотя бы один профиль имеет индекс нагрузки ≥ 70",
    backlog: "Срок рассасывания очереди",
    backlogShort: "Рассасывание",
    backlogHint:
      "Очередь / среднее число госпитализаций в день за 28 дней; не рассчитывается при < 0,5 в день",
    registrations28: "Направления за 28 дней",
    forecast14: "Прогноз направлений на 14 дней",
    forecast14Short: "Прогноз 14 дн.",
    loadIndex: "Индекс нагрузки",
    loadIndexMax: "Макс. индекс нагрузки",
    excessTrend: "Рост очереди сверх медианы",
    excessTrendShort: "Рост сверх медианы",
    excessTrendHint: (median: string) =>
      `Тренд очереди за 4 недели минус медианный тренд по стране (${median}), п.п. в неделю`,
    status: "Статус",
    hospital: "Стационар",
    region: "Регион",
    profile: "Профиль",
    hospitals: "Стационары",
    rank: (rank: number, n: number) => `Место ${rank} из ${n} в регионе`,
  },
  loadIndex: {
    components: "Составляющие индекса",
    backlog: "Срок рассасывания очереди",
    refusal: "Доля отказов",
    trend: "Рост очереди",
    weight: (w: number) => `вес ${w}%`,
    undefinedComponent: "не определена",
    formulaTitle: "Как считается индекс нагрузки",
    /** tooltip text; every number comes from GET /config (ml/configs/serving.yaml) */
    formula: (c: {
      backlog: string;
      refusal: string;
      trend: string;
      refusalCap: string;
      trendCap: string;
      minRegistrations: number;
      high: string;
      elevated: string;
    }) => [
      "Индекс от 0 до 100 показывает, насколько загружен стационар по профилю относительно других стационаров того же профиля по стране.",
      `Индекс = 100 × (${c.backlog} · очередь + ${c.refusal} · отказы + ${c.trend} · рост очереди), каждая составляющая от 0 до 1.`,
      "Очередь — место по сроку рассасывания очереди среди стационаров того же профиля (1 — самый долгий срок).",
      `Отказы — доля отказов за 28 дней, делённая на ${c.refusalCap} (${c.refusalCap} и выше = 1).`,
      `Рост очереди — превышение тренда очереди над медианой по стране, делённое на ${c.trendCap} п.п. в неделю; рост не быстрее медианы = 0.`,
      `Если составляющая не определена, веса остальных пересчитываются. Индекс рассчитывается при не менее ${c.minRegistrations} направлениях за 28 дней. Высокая нагрузка — от ${c.high}, повышенная — от ${c.elevated}.`,
    ],
  },
  overview: {
    title: "Обзор по стране",
    regionsTitle: "Регионы",
    regionsCaption: "Нажмите на регион, чтобы увидеть профили и стационары",
    columns: {
      region: "Регион",
      loadIndexMax: "Макс. индекс",
      queue: "Очередь",
      refusalRate: "Отказы",
      medianWait: "Медиана ожидания",
      highLoad: "Стационары с высокой нагрузкой",
      highLoadShare: "Доля профилей с высокой нагрузкой",
    },
    highLoadShareHint:
      "Доля профилей стационаров региона с индексом нагрузки не ниже порога высокой нагрузки среди профилей, для которых индекс рассчитан",
  },
  region: {
    kpisTitle: "Показатели региона",
    profileLabel: "Профиль койки",
    profileHint: "Профили отсортированы по индексу нагрузки региона",
    hospitalsTitle: (profile: string) => `Стационары по профилю «${profile}»`,
    hospitalsCaption:
      "По индексу нагрузки, от высокого к низкому. Нажмите на строку, чтобы открыть карточку.",
    noProfiles: "В регионе нет профилей с направлениями",
    noHospitals: "Нет стационаров по выбранному профилю",
    dayHospital: "дневной стационар",
    profileSummary: (n: number, high: number) =>
      `${n.toLocaleString("ru-RU")} ${plural(n, "стационар", "стационара", "стационаров")}, с высокой нагрузкой: ${high}`,
  },
  hospital: {
    kpisTitle: "Ключевые показатели",
    chartTitle: "Направления, госпитализации, отказы и очередь по дням",
    chartCaption: (from: string, to: string, fcTo: string) =>
      `Факт ${from} — ${to}, прогноз направлений и госпитализаций до ${fcTo}. Прогноз очереди не строится.`,
    today: "сегодня",
    series: {
      registrations: "Направления",
      hospitalizations: "Госпитализации",
      refusals: "Отказы",
      queue: "Очередь (правая шкала)",
      forecastRegistrations: "Прогноз направлений",
      forecastHospitalizations: "Прогноз госпитализаций",
    },
    chartTable: "Таблица данных графика",
    date: "Дата",
    noForecast: "Прогноз для этого стационара отсутствует",
    forecastMethod: {
      model: "модель C",
      region_share_fallback: "доля стационара в прогнозе региона",
    } as Record<string, string>,
    forecastMeta: (method: string, version: string) =>
      `Метод: ${method}; версия модели ${version}.`,
  },
  export: {
    title: "Скачать отчёт",
    xlsx: "Excel (XLSX)",
    pdf: "PDF",
    downloading: "Подготовка файла…",
    failed: "Не удалось скачать отчёт",
  },
  why: {
    title: "Почему",
    caption: (n: number) =>
      `Факторы, которые модели чаще всего связывают с прогнозами по ${n.toLocaleString("ru-RU")} ${plural(n, "направлению", "направлениям", "направлениям")} тестового периода (март 2025). Это связи в данных, а не причины.`,
    waitTitle: "Время ожидания",
    waitUnit: "среднее влияние на прогноз ожидания, дней",
    riskTitle: "Риск отказа",
    riskUnit: "среднее влияние на вероятность отказа, п.п.",
    typicalValue: "Типичное значение",
    share: (share: string) => `в топ-5 у ${share} направлений`,
    up: "увеличивает",
    down: "уменьшает",
    empty: "Нет направлений с прогнозами в тестовом периоде",
  },
  recommendations: {
    title: "Рекомендации",
    humanDecides: "Решение принимает специалист. Система только предлагает.",
    methodBadge: "оценка по историческим медианам",
    notEligible: "Рекомендации не формируются",
    rule: (topPercent: number, delta: string) =>
      `Правило: стационар входит в ${topPercent}% самых загруженных в регионе; альтернативы — стационары того же региона и профиля с меньшим сроком рассасывания очереди и медианой ожидания меньше на ${delta} и более.`,
    waitCurrent: "Ожидание сейчас",
    waitAlternative: "Ожидание в альтернативе",
    delta: "Разница",
    deltaValue: (days: string) => `на ${days} меньше`,
    refusalCurrent: "Отказы сейчас",
    refusalAlternative: "Отказы в альтернативе",
    backlog: "Рассасывание очереди",
    backlogCompare: (current: string, alternative: string) =>
      `${alternative} против ${current}`,
    loadIndexAlternative: "Индекс нагрузки альтернативы",
    openCard: "Карточка альтернативы",
    alternativeTitle: (i: number) => `Альтернатива ${i}`,
    actions: {
      confirm: "Подтвердить",
      reject: "Отклонить",
      defer: "Отложить",
    } satisfies Record<DecisionAction, string>,
    form: {
      title: (action: string) => `${action}: запись решения`,
      comment: "Комментарий",
      commentPlaceholder: "Например: согласовано с заведующим отделением",
      actor: "Кто принимает решение",
      actorPlaceholder: "ФИО, организация",
      actorRequired: "Укажите, кто принимает решение",
      submit: "Записать решение",
      submitting: "Запись…",
      cancel: "Отмена",
      saved: "Решение записано",
      failed: "Не удалось записать решение",
    },
  },
  decisions: {
    title: "История решений",
    caption: "Решения по этому стационару и профилю, новые сверху",
    empty: "Решений пока нет",
    columns: {
      createdAt: "Дата и время",
      action: "Решение",
      alternative: "Альтернатива",
      actor: "Кто",
      comment: "Комментарий",
    },
    actionPast: {
      confirm: "Подтверждено",
      reject: "Отклонено",
      defer: "Отложено",
    } satisfies Record<DecisionAction, string>,
    general: "без рекомендации",
  },
  referrals: {
    title: "Направления тестового периода",
    caption:
      "Март 2025: прогнозы моделей A (ожидание) и B (риск отказа) по каждому направлению",
    sortLabel: "Сортировка",
    sortRisk: "по риску отказа",
    sortWait: "по прогнозу ожидания",
    columns: {
      date: "Дата направления",
      diagnosis: "Диагноз (МКБ-10)",
      diagnosisName: "Название диагноза",
      purpose: "Цель",
      predWait: "Прогноз ожидания",
      refusalProb: "Вероятность отказа",
      details: "Объяснение",
    },
    highRisk: "высокий риск",
    expand: "Показать объяснение",
    collapse: "Скрыть объяснение",
    explanationWait: "Почему такой прогноз ожидания",
    explanationRisk: "Почему такой риск отказа",
    empty: "Нет направлений в тестовом периоде",
  },
  alerts: {
    title: "Сигналы",
    caption: (loadMin: string, trendMin: string, queueMin: number) =>
      `Стационары с индексом нагрузки ≥ ${loadMin} или очередью, растущей на ${trendMin} п.п. в неделю быстрее медианы по стране (при очереди от ${queueMin} человек)`,
    profileFilter: "Профиль",
    allProfiles: "Все профили",
    statusFilter: "Статус",
    allStatuses: "Все статусы",
    regionFilter: "Регион",
    allRegions: "Все регионы",
    empty: "Сигналов нет",
    openCard: "Открыть карточку",
  },
  models: {
    title: "О моделях",
    intro:
      "Три модели обучены на направлениях января–февраля 2025 года и проверены на марте 2025 года. Ниже — их точность в сравнении с простыми правилами (базовыми линиями), рассчитанными на тех же данных.",
    version: "Версия",
    trainedAt: "Обучена",
    trainWindow: "Обучение",
    testWindow: "Проверка",
    population: "Данные проверки",
    metric: "Метрика",
    model: "Модель",
    bestBaseline: "Лучшая базовая линия",
    series: "Ряд",
    target: "Что прогнозируется",
    betterLower: "меньше — лучше",
    betterHigher: "больше — лучше",
    beatsYes:
      "Модель лучше сезонной наивной базовой линии во всех ячейках бэктеста",
    beatsNo: "Модель не везде лучше сезонной наивной базовой линии",
    limitationsTitle: "Ограничения",
    testRows: (n: number) => `${n.toLocaleString("ru-RU")} строк`,
    seriesSelection: "Отбор рядов по данным",
    backtestOrigins: "Точки прогноза в бэктесте",
    dataThrough: "Финальная модель обучена на данных до",
    intendedUse: "Назначение",
  },
};

export type Messages = typeof ru;
